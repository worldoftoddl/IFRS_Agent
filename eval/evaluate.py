"""K-IFRS 검색 파이프라인 평가 프레임워크.

Golden dataset으로 Recall@K, MRR, Standard Accuracy를 산출한다.
다양한 검색 설정(RRF 파라미터, dense-only, bm25-only)으로 비교 가능.
"""

import json
import sys
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection  # noqa: E402
from app.embedder import embed_query  # noqa: E402
from app.tools import (  # noqa: E402
    _COMPONENT_ORDER,
    _SIMILARITY_THRESHOLD,
    _step1_identify_standard,
    _step2_search_hybrid,
    _step2_search_multi,
)

GOLDEN_PATH = Path(__file__).parent / "golden_dataset.json"

# ---------------------------------------------------------------------------
# 검색 설정: 파라미터 튜닝용
# ---------------------------------------------------------------------------

SEARCH_CONFIGS: dict[str, dict] = {
    "baseline": {"rrf_k": 60, "pool_size": 30, "mode": "hybrid"},
    "rrf_k20": {"rrf_k": 20, "pool_size": 30, "mode": "hybrid"},
    "rrf_k100": {"rrf_k": 100, "pool_size": 30, "mode": "hybrid"},
    "pool50": {"rrf_k": 60, "pool_size": 50, "mode": "hybrid"},
    "dense_only": {"rrf_k": 60, "pool_size": 30, "mode": "dense_only"},
    "bm25_only": {"rrf_k": 60, "pool_size": 30, "mode": "bm25_only"},
}


def load_golden() -> list[dict]:
    """Golden dataset 로드."""
    return json.loads(GOLDEN_PATH.read_text())


def _search_bm25_only(
    conn, query_text: str, standard_ids: list[str], top_k: int = 10
) -> list[tuple]:
    """BM25 전용 검색 (평가용)."""
    rows_auth = conn.execute(
        "SELECT standard_id, base_authority FROM standards WHERE standard_id = ANY(%s)",
        (list(standard_ids),),
    ).fetchall()
    auth_pairs = [(r[0], r[1]) for r in rows_auth]
    if not auth_pairs:
        return []

    rows = conn.execute(
        """
        SELECT c.chunk_id, c.para_number, c.component, c.section_title,
               c.content_markdown,
               ts_rank(c.content_tsv, plainto_tsquery('simple', %(query)s)) AS score,
               c.standard_id
        FROM chunks c
        JOIN UNNEST(%(sids)s::text[], %(auths)s::int[]) AS auth(sid, max_auth)
          ON c.standard_id = auth.sid AND c.authority <= auth.max_auth
        WHERE c.content_tsv @@ plainto_tsquery('simple', %(query)s)
        ORDER BY score DESC
        LIMIT %(top_k)s
        """,
        {
            "query": query_text,
            "sids": [p[0] for p in auth_pairs],
            "auths": [p[1] for p in auth_pairs],
            "top_k": top_k,
        },
    ).fetchall()
    return sorted(rows, key=lambda r: (_COMPONENT_ORDER.get(r[2], 99), -r[5]))


def run_evaluation(item: dict, config: dict | None = None, top_k: int = 10) -> dict:
    """단일 질문에 대해 검색 파이프라인을 실행하고 결과를 반환."""
    if config is None:
        config = SEARCH_CONFIGS["baseline"]

    query = item["query"]
    expected_paras = set(item["expected_paragraphs"])
    mode = config.get("mode", "hybrid")
    rrf_k = config.get("rrf_k", 60)
    pool_size = config.get("pool_size", 30)

    query_emb = embed_query(query)

    with get_connection() as conn:
        standards = _step1_identify_standard(conn, query_emb, top_k=5)

        if not standards or standards[0][2] < _SIMILARITY_THRESHOLD:
            return {
                **item,
                "found_paragraphs": [],
                "primary_standard": None,
                "first_correct_rank": None,
                "all_results": [],
            }

        standard_ids = [s[0] for s in standards if s[2] >= _SIMILARITY_THRESHOLD]

        if mode == "hybrid":
            rows, _ = _step2_search_hybrid(
                conn, query_emb, query, standard_ids,
                top_k=top_k, rrf_k=rrf_k, pool_size=pool_size,
            )
        elif mode == "dense_only":
            rows, _ = _step2_search_multi(conn, query_emb, standard_ids, top_k=top_k)
        elif mode == "bm25_only":
            rows = _search_bm25_only(conn, query, standard_ids, top_k=top_k)
        else:
            raise ValueError(f"Unknown mode: {mode}")

    # primary_standard 판정
    std_col = 6  # standard_id 컬럼 인덱스
    if rows:
        std_counts = Counter(r[std_col] for r in rows)
        primary_std = std_counts.most_common(1)[0][0]
    else:
        primary_std = standards[0][0] if standards else None

    # 결과 문단 번호 추출
    found_paras = [r[1] for r in rows if r[1]]

    # first_correct_rank
    first_rank = None
    for i, para in enumerate(found_paras, 1):
        if para in expected_paras:
            first_rank = i
            break

    return {
        **item,
        "found_paragraphs": found_paras,
        "primary_standard": primary_std,
        "first_correct_rank": first_rank,
        "all_results": [
            {"chunk_id": r[0], "para": r[1], "standard_id": r[std_col], "score": float(r[5])}
            for r in rows
        ],
    }


def compute_metrics(result: dict) -> dict:
    """단일 평가 결과에서 metrics를 산출."""
    expected = set(result["expected_paragraphs"])
    found = set(result["found_paragraphs"])

    recall = len(found & expected) / len(expected) if expected else 0.0
    mrr = 1.0 / result["first_correct_rank"] if result["first_correct_rank"] else 0.0
    std_acc = 1 if result.get("primary_standard") == result["expected_standard"] else 0

    return {
        "recall": recall,
        "mrr": mrr,
        "std_accuracy": std_acc,
    }


def run_full_evaluation(config_name: str = "baseline") -> dict:
    """전체 golden dataset 평가 실행."""
    config = SEARCH_CONFIGS.get(config_name, SEARCH_CONFIGS["baseline"])
    golden = load_golden()
    results = []
    total_time = 0.0

    print(f"Config: {config_name} — {config}")

    for item in golden:
        t0 = time.time()
        result = run_evaluation(item, config=config)
        elapsed = time.time() - t0
        total_time += elapsed

        metrics = compute_metrics(result)
        result["metrics"] = metrics
        result["latency_sec"] = round(elapsed, 2)
        results.append(result)

        status = "HIT" if metrics["recall"] > 0 else "MISS"
        print(
            f"  [{status}] {item['id']}: recall={metrics['recall']:.2f} "
            f"mrr={metrics['mrr']:.2f} std={'OK' if metrics['std_accuracy'] else 'FAIL'} "
            f"({elapsed:.1f}s)"
        )

    # 집계
    avg_recall = sum(r["metrics"]["recall"] for r in results) / len(results)
    avg_mrr = sum(r["metrics"]["mrr"] for r in results) / len(results)
    std_acc = sum(r["metrics"]["std_accuracy"] for r in results) / len(results)
    avg_latency = total_time / len(results)

    summary = {
        "config": config_name,
        "config_params": config,
        "n_queries": len(results),
        "avg_recall": round(avg_recall, 3),
        "avg_mrr": round(avg_mrr, 3),
        "std_accuracy": round(std_acc, 3),
        "avg_latency_sec": round(avg_latency, 2),
        "total_time_sec": round(total_time, 1),
        "results": results,
    }

    # 결과 저장
    out_path = Path(__file__).parent / "results" / f"{config_name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print(f"\n{'='*60}")
    print(f"Config: {config_name}")
    print(f"Queries: {len(results)}")
    print(f"Avg Recall@10: {avg_recall:.3f}")
    print(f"Avg MRR: {avg_mrr:.3f}")
    print(f"Std Accuracy: {std_acc:.3f}")
    print(f"Avg Latency: {avg_latency:.2f}s")
    print(f"Results saved: {out_path}")

    return summary


if __name__ == "__main__":
    config_name = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    run_full_evaluation(config_name)
