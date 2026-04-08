"""Multi-Query Retrieval 테스트.

LLM으로 쿼리를 3~4개 변형 생성하고,
각각 dense 검색한 뒤 결과를 합쳐서 후보 풀 다양성을 확보하는지 검증.
"""

import pytest
from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection
from app.embedder import embed_query
from app.tools import _step1_identify_standard


class TestMultiQueryGenerator:
    """쿼리 변형 생성 검증."""

    def test_import_generate_query_variants(self):
        """generate_query_variants 함수를 임포트할 수 있어야 한다."""
        from app.multi_query import generate_query_variants

        assert callable(generate_query_variants)

    def test_generates_multiple_variants(self):
        """원본 쿼리에 대해 3개 이상의 변형을 생성해야 한다."""
        from app.multi_query import generate_query_variants

        variants = generate_query_variants("리스부채의 최초 측정은 어떻게 하나요?")
        assert len(variants) >= 3
        assert all(isinstance(v, str) for v in variants)
        assert all(len(v) > 0 for v in variants)

    def test_variants_differ_from_original(self):
        """변형이 원본과 다른 텍스트여야 한다."""
        from app.multi_query import generate_query_variants

        query = "충당부채 인식 조건"
        variants = generate_query_variants(query)
        # 최소 1개는 원본과 달라야 함
        assert any(v != query for v in variants)

    def test_variants_are_accounting_related(self):
        """변형이 회계 관련 내용이어야 한다 (한국어 포함)."""
        from app.multi_query import generate_query_variants

        variants = generate_query_variants("금융자산의 분류 기준")
        all_text = " ".join(variants)
        # 회계 관련 키워드가 하나 이상 포함
        accounting_terms = ["금융", "자산", "분류", "측정", "인식", "기준"]
        assert any(term in all_text for term in accounting_terms)


class TestMultiQuerySearch:
    """Multi-Query 검색 통합 테스트."""

    def test_import_step2_search_multi_query(self):
        """_step2_search_multi_query 함수를 임포트할 수 있어야 한다."""
        from app.tools import _step2_search_multi_query

        assert callable(_step2_search_multi_query)

    def test_multi_query_returns_results(self):
        """Multi-Query 검색이 결과를 반환해야 한다."""
        from app.tools import _step2_search_multi_query

        query = "충당부채 인식 조건"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_multi_query(conn, query, standard_ids)

        assert len(rows) > 0

    def test_multi_query_includes_standard_id(self):
        """결과에 standard_id(7번째 컬럼)가 포함되어야 한다."""
        from app.tools import _step2_search_multi_query

        query = "리스 식별"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_multi_query(conn, query, standard_ids)

        for row in rows:
            assert len(row) >= 7

    def test_multi_query_deduplicates(self):
        """다중 쿼리 결과에서 중복 chunk_id가 제거되어야 한다."""
        from app.tools import _step2_search_multi_query

        query = "충당부채 인식"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_multi_query(conn, query, standard_ids)

        chunk_ids = [r[0] for r in rows]
        assert len(chunk_ids) == len(set(chunk_ids)), "중복 chunk_id 존재"
