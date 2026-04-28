"""감사기준 서브에이전트용 검색 도구 테스트."""

from app import audit_subagent_tools


def test_audit_subagent_retrieval_uses_dense_similarity():
    dense_code = audit_subagent_tools._search_audit_dense.__code__

    assert any(
        "embedding <=>" in const
        for const in dense_code.co_consts
        if isinstance(const, str)
    )


def test_audit_standard_id_validation():
    assert audit_subagent_tools._valid_audit_standard_id("ISA-320")
    assert audit_subagent_tools._valid_audit_standard_id("ISQM-1")
    assert audit_subagent_tools._valid_audit_standard_id("ASSR-3000")
    assert audit_subagent_tools._valid_audit_standard_id("FRMK-1")
    assert not audit_subagent_tools._valid_audit_standard_id("K-IFRS 1115")
    assert not audit_subagent_tools._valid_audit_standard_id("invalid")


def test_paragraph_candidates_accept_dotted_and_plain_numbers():
    assert audit_subagent_tools._paragraph_candidates("9") == ["9", "9."]
    assert audit_subagent_tools._paragraph_candidates("9.") == ["9.", "9"]
    assert audit_subagent_tools._paragraph_candidates(" A13. ") == ["A13.", "A13"]


def test_row_to_dict_shape():
    row = audit_subagent_tools._AuditRow(
        chunk_id="ISA-320:definitions:571f5389:9.",
        standard_id="ISA-320",
        title="감사의 계획수립과 수행에 있어서의 중요성",
        para_number="9.",
        component="definitions",
        section_title="용어의 정의",
        content_markdown="9.\t수행중요성이란...",
        score=0.92,
    )

    result = audit_subagent_tools._row_to_dict(row)

    assert result == {
        "chunk_id": "ISA-320:definitions:571f5389:9.",
        "standard_id": "ISA-320",
        "title": "감사의 계획수립과 수행에 있어서의 중요성",
        "para_number": "9.",
        "component": "definitions",
        "section_title": "용어의 정의",
        "content_markdown": "9.\t수행중요성이란...",
        "score": 0.92,
    }


def test_retrieve_audit_standards_description_mentions_dense_reranker():
    description = audit_subagent_tools.retrieve_audit_standards.description

    assert "Dense 검색 + Reranker" in description
    assert "1회만" in description
