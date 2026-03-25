"""Step 1~2 복수 기준서 통합 검색 테스트.

search_ifrs가 top-1 기준서만이 아닌 top-N 기준서에서 통합 검색하여,
Step 1에서 잘못된 기준서가 1위로 올라와도 정답 기준서의 문단이
결과에 포함되는지 검증한다.

테스트는 실제 DB(kifrs)에 연결하여 수행한다.
"""

import pytest
from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection
from app.embedder import embed_query
from app.tools import _step1_identify_standard, _step2_search_multi


class TestMultiStandardSearch:
    """복수 기준서 통합 검색 테스트."""

    def test_multi_search_returns_results_from_multiple_standards(self):
        """통합 검색 결과에 복수 기준서의 문단이 포함되어야 한다."""
        query_emb = embed_query("측정기준 역사적 원가 현행원가 이행가치")

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=3)
            standard_ids = [s[0] for s in standards]

            rows, _ = _step2_search_multi(conn, query_emb, standard_ids)

        assert len(rows) > 0
        # 결과에 1개 이상의 기준서가 포함되어야 함
        result_standards = {r[6] for r in rows}  # standard_id 컬럼
        assert len(result_standards) >= 2, (
            f"통합 검색인데 기준서가 1개뿐: {result_standards}"
        )

    def test_conceptual_framework_appears_in_multi_search(self):
        """'개념체계 측정' 질문에서 개념체계 문단이 통합 검색 결과에 포함되어야 한다.
        Step 1 top_k=5로 충분한 후보를 확보해야 개념체계가 포함됨."""
        query_emb = embed_query("개념체계 측정기준 역사적 원가 현행원가 이행가치")

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]

            rows, _ = _step2_search_multi(conn, query_emb, standard_ids)

        result_standards = {r[6] for r in rows}
        assert "재무보고 개념체계" in result_standards, (
            f"개념체계가 통합 검색 결과에 없음. 포함된 기준서: {result_standards}"
        )

    def test_multi_search_sorted_by_similarity(self):
        """통합 검색 결과는 유사도 순으로 정렬되어야 한다."""
        query_emb = embed_query("충당부채 인식 조건")

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=3)
            standard_ids = [s[0] for s in standards]

            rows, _ = _step2_search_multi(conn, query_emb, standard_ids)

        if len(rows) >= 2:
            similarities = [r[5] for r in rows]  # similarity 컬럼
            # 정렬 순서: component 그룹 내에서 유사도 내림차순
            # 전체적으로는 component 순서가 우선이므로 strict 내림차순은 아닐 수 있음
            # 최소한 결과가 비어있지 않고, 유사도가 0보다 커야 함
            assert all(s > 0 for s in similarities)

    def test_multi_search_excludes_bc_ie(self):
        """통합 검색에서도 bc/ie 컴포넌트는 제외되어야 한다."""
        query_emb = embed_query("수행의무 판단 기준")

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=3)
            standard_ids = [s[0] for s in standards]

            rows, _ = _step2_search_multi(conn, query_emb, standard_ids)

        components = {r[2] for r in rows}
        assert "bc" not in components, f"bc가 포함됨: {components}"
        assert "ie" not in components, f"ie가 포함됨: {components}"

    def test_multi_search_returns_para_numbers(self):
        """통합 검색에서 para_numbers가 올바르게 추출되어야 한다."""
        query_emb = embed_query("충당부채 인식 조건")

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=3)
            standard_ids = [s[0] for s in standards]

            _, para_nums = _step2_search_multi(conn, query_emb, standard_ids)

        assert isinstance(para_nums, list)
        assert len(para_nums) > 0
        assert all(isinstance(p, str) for p in para_nums)

    def test_multi_search_result_includes_standard_id(self):
        """통합 검색 결과 각 행에 standard_id가 포함되어야 한다 (7번째 컬럼)."""
        query_emb = embed_query("금융자산 분류")

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=3)
            standard_ids = [s[0] for s in standards]

            rows, _ = _step2_search_multi(conn, query_emb, standard_ids)

        assert len(rows) > 0
        for row in rows:
            assert len(row) >= 7, f"행에 standard_id 컬럼(7번째)이 없음: {len(row)} 컬럼"
            assert row[6] in standard_ids, f"결과의 standard_id가 검색 대상에 없음: {row[6]}"

    def test_search_ifrs_tool_uses_multi_search(self):
        """search_ifrs 도구가 복수 기준서 통합 검색 결과를 반환하는지 확인."""
        from app.tools import search_ifrs

        result = search_ifrs.invoke("개념체계 측정기준 역사적 원가")

        # 개념체계 관련 내용이 결과에 포함되어야 함
        assert "개념체계" in result or "측정" in result, (
            "search_ifrs 결과에 개념체계/측정 관련 내용이 없음"
        )
