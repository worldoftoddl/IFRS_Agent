"""감사기준 PostgreSQL 검색 도구 테스트."""

import pytest

from app import audit_tools


def test_fixed_k_tools_call_common_search(monkeypatch):
    calls = []

    def fake_search(query: str, *, top_k: int) -> str:
        calls.append((query, top_k))
        return f"k={top_k}: {query}"

    monkeypatch.setattr(audit_tools, "_search_audit_standards", fake_search)

    assert audit_tools.search_audit_standards_k1.invoke({"query": "계속기업"}) == "k=1: 계속기업"
    assert audit_tools.search_audit_standards_k3.invoke({"query": "계속기업"}) == "k=3: 계속기업"
    assert audit_tools.search_audit_standards_k5.invoke({"query": "계속기업"}) == "k=5: 계속기업"
    assert calls == [("계속기업", 1), ("계속기업", 3), ("계속기업", 5)]


def test_format_audit_results_includes_candidates_and_chunks():
    candidates = [
        audit_tools._AuditCandidate("ISA-570", "계속기업", 0.482),
        audit_tools._AuditCandidate("ISA-315", "중요왜곡표시위험의 식별과 평가", 0.301),
    ]
    chunks = [
        audit_tools._AuditChunk(
            chunk_id="ISA-570:requirements:d3390c5f:12.",
            standard_id="ISA-570",
            title="계속기업",
            para_number="12.",
            component="requirements",
            section_title="경영진 평가에 대한 감사인의 평가",
            content_markdown=(
                "12.\t감사인은 계속기업으로서의 존속능력에 대한 "
                "경영진의 평가를 평가한다."
            ),
            score=0.0168,
        )
    ]

    result = audit_tools._format_audit_results("계속기업 평가", 3, candidates, chunks)

    assert result.startswith("# 감사기준 검색 결과 (k=3)")
    assert "- ISA-570 계속기업" in result
    assert "**[ISA-570] 문단 12.**" in result
    assert "chunk_id: ISA-570:requirements:d3390c5f:12." in result


def test_format_audit_results_rejects_low_similarity():
    candidates = [audit_tools._AuditCandidate("ISA-570", "계속기업", 0.1)]

    result = audit_tools._format_audit_results("무관한 질문", 1, candidates, [])

    assert result == "관련 감사기준을 찾을 수 없습니다. 감사기준 관련 질문을 입력해 주세요."


def test_invalid_audit_schema_env_is_rejected(monkeypatch):
    monkeypatch.setenv("AUDIT_SCHEMA", "audit;drop")

    with pytest.raises(RuntimeError):
        audit_tools._audit_schema()


def test_audit_tools_are_registered_on_main_agent():
    from app.agent import MAIN_TOOLS

    tool_names = {tool.name for tool in MAIN_TOOLS}
    assert {
        "search_audit_standards_k1",
        "search_audit_standards_k3",
        "search_audit_standards_k5",
    } <= tool_names


def test_audit_tool_descriptions_guide_k_selection():
    assert "명확한 단일 개념" in audit_tools.search_audit_standards_k1.description
    assert "기본 검색 도구" in audit_tools.search_audit_standards_k3.description
    assert "한 번만 호출" in audit_tools.search_audit_standards_k3.description
    assert "기본값으로 사용하지 마세요" in audit_tools.search_audit_standards_k5.description


def test_system_prompt_limits_audit_tool_repetition():
    from app.prompts import SYSTEM_PROMPT

    assert "감사기준 도구 중 정확히 하나만 1회 호출" in SYSTEM_PROMPT
    assert "검색어만 바꿔 반복 호출하지 마세요" in SYSTEM_PROMPT
    assert "명확한 단일 개념" in SYSTEM_PROMPT
