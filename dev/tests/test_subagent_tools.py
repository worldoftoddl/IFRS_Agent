"""retrieval-distiller 서브에이전트용 도구 테스트.

3개 도구 검증:
- retrieve_ifrs: hybrid + reranker 무거운 파이프라인 (dict list 반환)
- lookup_paragraph: (standard_id, para_number) 직접 조회
- search_single_standard: 단일 기준서 Dense-only 검색
"""

from dotenv import load_dotenv

load_dotenv()

from app.subagent_tools import (  # noqa: E402
    lookup_paragraph,
    retrieve_ifrs,
    search_single_standard,
)

# 검색 결과 dict가 반드시 가져야 할 키
_EXPECTED_KEYS = {
    "chunk_id",
    "standard_id",
    "para_number",
    "component",
    "section_title",
    "content_markdown",
    "score",
}


class TestRetrieveIfrs:
    """retrieve_ifrs: search_ifrs와 동등한 무거운 파이프라인."""

    def test_returns_list_of_dicts(self):
        """결과는 dict 리스트여야 한다."""
        results = retrieve_ifrs.invoke({"query": "충당부채 인식 조건"})
        assert isinstance(results, list)
        assert len(results) > 0, "전형적인 질문에 빈 결과"
        for item in results:
            assert isinstance(item, dict)

    def test_each_item_has_required_keys(self):
        """각 원소가 필수 키를 모두 가져야 한다."""
        results = retrieve_ifrs.invoke({"query": "리스 식별 기준"})
        assert len(results) > 0
        for item in results:
            missing = _EXPECTED_KEYS - set(item.keys())
            assert not missing, f"누락된 키: {missing}"

    def test_score_is_positive_float(self):
        """score는 양수 float이어야 한다."""
        results = retrieve_ifrs.invoke({"query": "수익 인식 5단계"})
        assert len(results) > 0
        for item in results:
            assert isinstance(item["score"], float)
            assert item["score"] > 0

    def test_standard_id_matches_kifrs_format(self):
        """standard_id는 'K-IFRS' 또는 '재무보고 개념체계' 형식이어야 한다."""
        results = retrieve_ifrs.invoke({"query": "금융자산 분류"})
        assert len(results) > 0
        for item in results:
            sid = item["standard_id"]
            assert sid.startswith("K-IFRS") or "개념체계" in sid, f"예상치 못한 sid: {sid}"

    def test_empty_on_non_accounting_query(self):
        """회계 무관 질문은 빈 리스트를 반환해야 한다 (유사도 임계값)."""
        results = retrieve_ifrs.invoke({"query": "오늘 점심 메뉴 추천"})
        assert results == []

    def test_excludes_bc_ie_components(self):
        """authority 필터가 적용되어 bc/ie component는 제외되어야 한다."""
        results = retrieve_ifrs.invoke({"query": "수행의무 식별"})
        components = {r["component"] for r in results}
        assert "bc" not in components
        assert "ie" not in components


class TestLookupParagraph:
    """lookup_paragraph: 직접 조회 (검색 없음)."""

    def test_returns_dict_for_existing_paragraph(self):
        """존재하는 (standard_id, para_number)에 대해 dict 반환."""
        result = lookup_paragraph.invoke(
            {"standard_id": "K-IFRS 1037", "para_number": "14"}
        )
        assert result is not None
        assert isinstance(result, dict)
        assert result["standard_id"] == "K-IFRS 1037"
        assert result["para_number"] == "14"
        assert result["component"] == "main"
        assert "content_markdown" in result
        assert len(result["content_markdown"]) > 0

    def test_returns_none_for_nonexistent_paragraph(self):
        """존재하지 않는 문단은 None."""
        result = lookup_paragraph.invoke(
            {"standard_id": "K-IFRS 1037", "para_number": "99999"}
        )
        assert result is None

    def test_returns_none_for_nonexistent_standard(self):
        """존재하지 않는 기준서는 None."""
        result = lookup_paragraph.invoke(
            {"standard_id": "K-IFRS 9999", "para_number": "1"}
        )
        assert result is None

    def test_invalid_standard_id_format_returns_none(self):
        """잘못된 형식의 standard_id는 None (안전 처리)."""
        result = lookup_paragraph.invoke(
            {"standard_id": "invalid-id", "para_number": "1"}
        )
        assert result is None

    def test_result_has_expected_shape(self):
        """반환 dict가 기대한 키를 가진다."""
        result = lookup_paragraph.invoke(
            {"standard_id": "K-IFRS 1037", "para_number": "14"}
        )
        assert result is not None
        expected = {
            "chunk_id", "standard_id", "para_number",
            "component", "section_title", "content_markdown",
        }
        assert expected <= set(result.keys())


class TestSearchSingleStandard:
    """search_single_standard: 단일 기준서 Dense-only."""

    def test_returns_list_of_dicts(self):
        """결과는 dict 리스트."""
        results = search_single_standard.invoke(
            {"query": "충당부채 측정", "standard_id": "K-IFRS 1037"}
        )
        assert isinstance(results, list)
        assert len(results) > 0

    def test_all_results_same_standard(self):
        """모든 결과가 요청한 standard_id에 속해야 한다."""
        results = search_single_standard.invoke(
            {"query": "수행의무", "standard_id": "K-IFRS 1115"}
        )
        assert len(results) > 0
        for r in results:
            assert r["standard_id"] == "K-IFRS 1115"

    def test_each_result_has_required_keys(self):
        """각 원소가 필수 키를 가진다."""
        results = search_single_standard.invoke(
            {"query": "리스 부채 측정", "standard_id": "K-IFRS 1116"}
        )
        assert len(results) > 0
        for r in results:
            missing = _EXPECTED_KEYS - set(r.keys())
            assert not missing, f"누락된 키: {missing}"

    def test_empty_for_nonexistent_standard(self):
        """존재하지 않는 기준서는 빈 리스트."""
        results = search_single_standard.invoke(
            {"query": "아무거나", "standard_id": "K-IFRS 9999"}
        )
        assert results == []

    def test_invalid_standard_id_format_returns_empty(self):
        """잘못된 형식의 standard_id는 빈 리스트."""
        results = search_single_standard.invoke(
            {"query": "test", "standard_id": "not-valid"}
        )
        assert results == []

    def test_score_descending(self):
        """결과는 유사도(score) 내림차순으로 정렬되어야 한다."""
        results = search_single_standard.invoke(
            {"query": "금융부채 제거", "standard_id": "K-IFRS 1109"}
        )
        if len(results) >= 2:
            scores = [r["score"] for r in results]
            assert scores == sorted(scores, reverse=True), (
                f"score 내림차순 아님: {scores}"
            )
