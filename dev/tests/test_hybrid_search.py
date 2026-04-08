"""BM25 + Dense 순수 RRF 하이브리드 검색 테스트.

_step2_search_hybrid가 dense(벡터)와 BM25(키워드)를 RRF로 결합하여
정확한 용어 매칭과 의미 검색을 동시에 수행하는지 검증한다.
"""

import pytest
from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection
from app.embedder import embed_query
from app.tools import (
    _step1_identify_standard,
    _step2_search_hybrid,
)


class TestHybridSearch:
    """순수 RRF 하이브리드 검색 테스트."""

    def test_hybrid_returns_results(self):
        """하이브리드 검색 결과가 비어있지 않아야 한다."""
        query = "충당부채 인식 조건"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_hybrid(conn, query_emb, query, standard_ids)

        assert len(rows) > 0

    def test_rrf_score_positive(self):
        """모든 결과의 rrf_score가 0보다 커야 한다."""
        query = "리스 식별"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_hybrid(conn, query_emb, query, standard_ids)

        for row in rows:
            assert row[5] > 0, f"rrf_score가 0 이하: {row[5]}"

    def test_exact_term_boosted_by_bm25(self):
        """BM25가 정확한 용어를 매칭하여 dense-only 대비 결과가 개선되어야 한다.
        개념체계를 검색 범위에 직접 포함하여 BM25 효과를 검증."""
        query = "이행가치"
        query_emb = embed_query(query)

        with get_connection() as conn:
            # 개념체계를 명시적으로 포함하여 BM25 효과 격리 테스트
            standard_ids = ["재무보고 개념체계"]
            rows, _ = _step2_search_hybrid(conn, query_emb, query, standard_ids)

        assert len(rows) > 0
        all_content = " ".join(r[4] for r in rows)
        assert "이행가치" in all_content, (
            "개념체계 내 '이행가치' BM25 매칭 실패"
        )

    def test_dense_fallback_when_no_bm25_match(self):
        """BM25 매칭이 없는 의미 검색도 동작해야 한다 (dense fallback)."""
        query = "회사가 미래에 돈을 지불해야 할 의무"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_hybrid(conn, query_emb, query, standard_ids)

        assert len(rows) > 0, "BM25 매칭 없는 의미 검색에서도 결과가 있어야 함"

    def test_hybrid_excludes_bc_ie(self):
        """하이브리드에서도 bc/ie 컴포넌트는 제외되어야 한다 (authority 필터)."""
        query = "수행의무 판단 기준"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=3)
            # 일반 기준서만 선택 (base_authority=1)
            standard_ids = [s[0] for s in standards if s[0].startswith("K-IFRS")]
            rows, _ = _step2_search_hybrid(conn, query_emb, query, standard_ids)

        components = {r[2] for r in rows}
        assert "bc" not in components, f"bc가 포함됨: {components}"
        assert "ie" not in components, f"ie가 포함됨: {components}"

    def test_hybrid_includes_standard_id(self):
        """결과 각 행에 standard_id(7번째 컬럼)가 포함되어야 한다."""
        query = "금융자산 분류"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_hybrid(conn, query_emb, query, standard_ids)

        for row in rows:
            assert len(row) >= 7
            assert row[6] in standard_ids

    def test_hybrid_returns_para_numbers(self):
        """para_numbers가 올바르게 추출되어야 한다."""
        query = "충당부채 인식"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            _, para_nums = _step2_search_hybrid(conn, query_emb, query, standard_ids)

        assert isinstance(para_nums, list)
        assert len(para_nums) > 0

    def test_conceptual_framework_measurement_found(self):
        """개념체계 측정 관련 질문에서 '원가' 또는 '측정' 관련 문단이 반환되어야 한다."""
        query = "역사적 원가 현행원가 이행가치 측정기준"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_hybrid(conn, query_emb, query, standard_ids)

        all_content = " ".join(r[4] for r in rows)
        assert "원가" in all_content or "측정" in all_content, (
            "측정 관련 내용이 결과에 없음"
        )

    def test_search_ifrs_uses_hybrid(self):
        """search_ifrs 도구가 하이브리드 검색 결과를 반환하는지 확인."""
        from app.tools import search_ifrs

        result = search_ifrs.invoke("충당부채 인식 조건")
        assert "기준서" in result
        assert len(result) > 100
