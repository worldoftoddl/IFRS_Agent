"""K-IFRS 검색 파이프라인 평가 프레임워크.

Golden dataset으로 Recall@K, MRR, Standard Accuracy를 산출한다.
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
    _SIMILARITY_THRESHOLD,
    _step1_identify_standard,
    _step2_search_hybrid,
)

GOLDEN_PATH = Path(__file__).parent / "golden_dataset.json"


def load_golden() -> list[dict]:
    """Golden dataset 로드."""
    return json.loads(GOLDEN_PATH.read_text())


def run_evaluation(item: dict, top_k: int = 10) -> dict:
    """단일 질문에 대해 검색 파이프라인을 실행하고 결과를 반환."""
    query = item["query"]
    expected_paras = set(item["expected_paragraphs"])

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
        rows, _ = _step2_search_hybrid(conn, query_emb, query, standard_ids, top_k=top_k)

    # primary_standard 판정
    if rows:
        std_counts = Counter(r[6] for r in rows)
        primary_std = std_counts.most_common(1)[0][0]
    else:
        primary_std = standards[0][0] if standards else None

    # 결과 문단 번호 추출
    found_paras = [r[1] for r in rows if r[1]]

    # first_correct_rank: expected_paragraphs 중 처음 등장하는 순위 (1-indexed)
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
            {"chunk_id": r[0], "para": r[1], "standard_id": r[6], "score": float(r[5])}
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
    golden = load_golden()
    results = []
    total_time = 0.0

    for item in golden:
        t0 = time.time()
        result = run_evaluation(item)
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
    config = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    run_full_evaluation(config)
