"""Phase 3 — 에이전트 기반 end-to-end 평가.

기존 eval/evaluate.py는 retriever(검색 파이프라인)만 평가했다면,
이 모듈은 **메인 에이전트가 서브에이전트를 거쳐 생성한 최종 답변**을
golden dataset과 비교하여 실제 end-to-end 품질을 측정한다.

지표:
- Cited Recall: 최종 답변에 expected_paragraphs가 몇 개 인용되었는지
- Standard Accuracy: 최종 답변에 expected_standard가 인용되었는지
- Latency: 질문 → 최종 답변까지 전체 시간
"""

import json
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

load_dotenv()

from app.agent import agent  # noqa: E402

GOLDEN_PATH = Path(__file__).parent / "golden_dataset.json"

# ---------------------------------------------------------------------------
# Citation regex patterns
# ---------------------------------------------------------------------------

# K-IFRS 인용 (제 접두어, 소수점 문단, B/AG 접두 문단, 범위 지원)
# 예: "K-IFRS 1037 문단 14", "K-IFRS 제1109호 문단 4.1.2A", "K-IFRS 1116 문단 B9"
# 문단 범위: "K-IFRS 1037 문단 42~43" → 후처리에서 분리
_CITATION_RE = re.compile(
    r"K-IFRS\s+(?:제)?(\d{4})(?:호)?\s*문단\s*"
    r"(한?[A-Z]{0,2}\d+(?:\.\d+)*[A-Z]?(?:~한?[A-Z]{0,2}\d+(?:\.\d+)*[A-Z]?)?)"
)

# 개념체계 인용 — "재무보고" 선택적
# 예: "재무보고 개념체계 문단 4.5", "개념체계 문단 6.4"
_CONCEPTUAL_RE = re.compile(
    r"(?:재무보고\s*)?개념체계\s*문단\s*(\d+(?:\.\d+)*)"
)

# K-IFRS 기준서 언급 (문단 없이) — standalone 문단 귀속용
# 예: "K-IFRS 1037에 따르면", "K-IFRS 제1109호"
_STANDARD_MENTION_RE = re.compile(
    r"K-IFRS\s+(?:제)?(\d{4})(?:호)?"
)

# Standalone 문단 참조 (K-IFRS 접두 없이 "문단 XX"만)
# 예: "> **문단 36**:", "(문단 14)", "문단 B21~B23"
_STANDALONE_PARA_RE = re.compile(
    r"(?<!\d)문단\s*\**"
    r"(한?[A-Z]{0,2}\d+(?:\.\d+)*[A-Z]?(?:~한?[A-Z]{0,2}\d+(?:\.\d+)*[A-Z]?)?)"
    r"\**"
)


def _expand_range(para: str) -> list[str]:
    """문단 범위를 개별 번호로 분리. '42~43' → ['42', '43']."""
    if "~" not in para:
        return [para]
    parts = para.split("~")
    if len(parts) == 2:
        return [parts[0].strip(), parts[1].strip()]
    return [para]


def _find_nearest_standard(text: str, pos: int) -> str | None:
    """텍스트에서 pos 이전에 가장 가까운 K-IFRS 기준서 ID를 찾는다."""
    best_sid = None
    best_dist = float("inf")
    for m in _STANDARD_MENTION_RE.finditer(text):
        if m.start() <= pos:
            dist = pos - m.start()
            if dist < best_dist:
                best_dist = dist
                best_sid = f"K-IFRS {m.group(1)}"
    return best_sid


def extract_paragraph_citations(text: str) -> list[tuple[str, str]]:
    """최종 답변 텍스트에서 (standard_id, para_number) 인용을 모두 추출.

    지원 형식:
    - "K-IFRS 1037 문단 14" / "K-IFRS 제1037호 문단 14"
    - "K-IFRS 1109 문단 4.1.2A" (소수점, B/AG 접두)
    - "K-IFRS 1037 문단 42~43" (범위 → 개별 분리)
    - "K-IFRS 1115 문단 한15" (한국 고유)
    - "개념체계 문단 6.4" / "재무보고 개념체계 문단 4.5"
    - "> **문단 36**:" (standalone — 가장 가까운 K-IFRS에 귀속)
    동일 인용 중복 제거. 등장 순서 보존.
    """
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    # _CITATION_RE가 이미 매칭한 위치를 기록 (standalone 중복 방지)
    matched_spans: list[tuple[int, int]] = []

    def _add(sid: str, para: str) -> None:
        key = (sid, para)
        if key not in seen:
            seen.add(key)
            result.append(key)

    # 1) K-IFRS XXXX 문단 YY (명시적 기준서 + 문단)
    for m in _CITATION_RE.finditer(text):
        sid = f"K-IFRS {m.group(1)}"
        for para in _expand_range(m.group(2)):
            _add(sid, para)
        matched_spans.append((m.start(), m.end()))

    # 2) 개념체계 문단
    for m in _CONCEPTUAL_RE.finditer(text):
        _add("재무보고 개념체계", m.group(1))
        matched_spans.append((m.start(), m.end()))

    # 3) Standalone 문단 (K-IFRS 없이 "문단 XX"만) — 가장 가까운 기준서에 귀속
    for m in _STANDALONE_PARA_RE.finditer(text):
        # 이미 위에서 매칭된 범위에 속하면 스킵
        if any(s <= m.start() < e for s, e in matched_spans):
            continue
        sid = _find_nearest_standard(text, m.start())
        if sid:
            for para in _expand_range(m.group(1)):
                _add(sid, para)

    return result


def _extract_final_answer(state: dict) -> str:
    """deepagents 실행 결과 state에서 최종 AI 메시지 텍스트를 추출."""
    messages = state.get("messages", [])
    for msg in reversed(messages):
        # AIMessage인지 확인 (content만 있고 tool_calls는 비어야 최종 답변)
        msg_type = type(msg).__name__
        if msg_type in ("AIMessage",) and not getattr(msg, "tool_calls", None):
            content = msg.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                ]
                return "".join(parts)
    return ""


def run_adhoc_query(query: str) -> dict:
    """임의의 질문 문자열로 에이전트를 호출하고 결과를 반환.

    golden dataset 없이 자유 질의할 때 사용.

    Returns:
        {
            "query": str,
            "answer_text": 최종 답변 전문,
            "cited_paragraphs": [(standard_id, para), ...],
            "latency_sec": float,
        }
    """
    t0 = time.time()
    state = agent.invoke(
        {"messages": [HumanMessage(content=query)]},
    )
    elapsed = time.time() - t0

    answer_text = _extract_final_answer(state)
    cited = extract_paragraph_citations(answer_text)

    return {
        "query": query,
        "answer_text": answer_text,
        "cited_paragraphs": cited,
        "latency_sec": round(elapsed, 2),
    }


def run_agent_evaluation(item: dict) -> dict:
    """단일 golden 항목에 대해 agent.invoke를 실행하고 결과 반환.

    Returns:
        {
            "id", "query", "expected_standard", "expected_paragraphs",
            "answer_text": 최종 답변 전문,
            "cited_paragraphs": [(standard_id, para), ...],
            "latency_sec": float,
        }
    """
    t0 = time.time()
    state = agent.invoke(
        {"messages": [HumanMessage(content=item["query"])]},
    )
    elapsed = time.time() - t0

    answer_text = _extract_final_answer(state)
    cited = extract_paragraph_citations(answer_text)

    return {
        "id": item["id"],
        "query": item["query"],
        "expected_standard": item["expected_standard"],
        "expected_paragraphs": item["expected_paragraphs"],
        "answer_text": answer_text,
        "cited_paragraphs": cited,
        "latency_sec": round(elapsed, 2),
    }


def compute_agent_metrics(result: dict) -> dict:
    """에이전트 결과에서 지표 계산."""
    expected_std = result["expected_standard"]
    expected_paras = set(result["expected_paragraphs"])
    cited = result["cited_paragraphs"]

    cited_stds = {sid for sid, _ in cited}
    cited_paras_in_expected_std = {
        para for sid, para in cited if sid == expected_std
    }

    std_hit = 1 if expected_std in cited_stds else 0
    cited_recall = (
        len(cited_paras_in_expected_std & expected_paras) / len(expected_paras)
        if expected_paras
        else 0.0
    )

    return {
        "std_hit": std_hit,
        "cited_recall": round(cited_recall, 3),
        "n_citations": len(cited),
    }


def run_full_agent_evaluation(output_name: str = "subagent") -> dict:
    """전체 36문항 end-to-end 평가."""
    golden = json.loads(GOLDEN_PATH.read_text())
    results = []
    total_time = 0.0

    print(f"Agent E2E 평가 시작 — {len(golden)}문항")

    for item in golden:
        try:
            result = run_agent_evaluation(item)
        except Exception as e:
            print(f"  [ERR] {item['id']}: {e}")
            result = {
                "id": item["id"],
                "query": item["query"],
                "expected_standard": item["expected_standard"],
                "expected_paragraphs": item["expected_paragraphs"],
                "answer_text": "",
                "cited_paragraphs": [],
                "latency_sec": 0.0,
                "error": str(e),
            }

        metrics = compute_agent_metrics(result)
        result["metrics"] = metrics
        total_time += result["latency_sec"]
        results.append(result)

        print(
            f"  [{('HIT' if metrics['std_hit'] else 'MISS'):>4}] {item['id']}: "
            f"cited_recall={metrics['cited_recall']:.2f} "
            f"n_cit={metrics['n_citations']} "
            f"({result['latency_sec']:.1f}s)"
        )

    # 집계
    if not results:
        raise ValueError(f"Golden dataset이 비어 있습니다: {GOLDEN_PATH}")
    avg_recall = sum(r["metrics"]["cited_recall"] for r in results) / len(results)
    std_acc = sum(r["metrics"]["std_hit"] for r in results) / len(results)
    avg_latency = total_time / len(results)

    summary = {
        "config": output_name,
        "n_queries": len(results),
        "avg_cited_recall": round(avg_recall, 3),
        "std_accuracy": round(std_acc, 3),
        "avg_latency_sec": round(avg_latency, 2),
        "total_time_sec": round(total_time, 1),
        "results": results,
    }

    out_path = Path(__file__).parent / "results" / f"{output_name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str)
    )

    print(f"\n{'='*60}")
    print(f"Config: {output_name}")
    print(f"Queries: {len(results)}")
    print(f"Avg Cited Recall: {avg_recall:.3f}")
    print(f"Std Accuracy: {std_acc:.3f}")
    print(f"Avg Latency: {avg_latency:.2f}s")
    print(f"Saved: {out_path}")

    return summary


if __name__ == "__main__":
    output_name = sys.argv[1] if len(sys.argv) > 1 else "subagent"
    run_full_agent_evaluation(output_name)
