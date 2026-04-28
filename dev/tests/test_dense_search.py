"""K-IFRS Dense 검색 테스트.

_step2_search_dense가 여러 기준서의 권위 문단을 벡터 검색하고,
search_ifrs가 Dense 후보 + Reranker 파이프라인으로 결과를 반환하는지 검증한다.
"""

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection  # noqa: E402
from app.embedder import embed_query  # noqa: E402
from app.tools import _step1_identify_standard, _step2_search_dense  # noqa: E402


class TestDenseSearch:
    """Dense 복수 기준서 검색 테스트."""

    def test_dense_returns_results(self):
        """Dense 검색 결과가 비어있지 않아야 한다."""
        query = "충당부채 인식 조건"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_dense(conn, query_emb, standard_ids)

        assert len(rows) > 0

    def test_similarity_score_positive(self):
        """모든 결과의 similarity score가 0보다 커야 한다."""
        query = "리스 식별"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_dense(conn, query_emb, standard_ids)

        for row in rows:
            assert row[5] > 0, f"similarity가 0 이하: {row[5]}"

    def test_dense_excludes_bc_ie(self):
        """Dense 검색에서도 bc/ie 컴포넌트는 제외되어야 한다."""
        query = "수행의무 판단 기준"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=3)
            standard_ids = [s[0] for s in standards if s[0].startswith("K-IFRS")]
            rows, _ = _step2_search_dense(conn, query_emb, standard_ids)

        components = {r[2] for r in rows}
        assert "bc" not in components, f"bc가 포함됨: {components}"
        assert "ie" not in components, f"ie가 포함됨: {components}"

    def test_dense_includes_standard_id(self):
        """결과 각 행에 standard_id(7번째 컬럼)가 포함되어야 한다."""
        query = "금융자산 분류"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_dense(conn, query_emb, standard_ids)

        for row in rows:
            assert len(row) >= 7
            assert row[6] in standard_ids

    def test_dense_returns_para_numbers(self):
        """para_numbers가 올바르게 추출되어야 한다."""
        query = "충당부채 인식"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            _, para_nums = _step2_search_dense(conn, query_emb, standard_ids)

        assert isinstance(para_nums, list)
        assert len(para_nums) > 0

    def test_conceptual_framework_measurement_found(self):
        """개념체계 측정 관련 질문에서 관련 문단이 반환되어야 한다."""
        query = "역사적 원가 현행원가 이행가치 측정기준"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_dense(conn, query_emb, standard_ids)

        all_content = " ".join(r[4] for r in rows)
        assert "원가" in all_content or "측정" in all_content, (
            "측정 관련 내용이 결과에 없음"
        )

    def test_search_ifrs_uses_dense_pipeline(self):
        """search_ifrs 도구가 Dense + Reranker 결과를 반환하는지 확인."""
        from app.tools import search_ifrs

        result = search_ifrs.invoke("충당부채 인식 조건")
        assert "기준서" in result
        assert len(result) > 100
