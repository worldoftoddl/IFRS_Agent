"""Step 1 유사도 임계값 테스트.

회계와 무관한 질문에 대해 search_ifrs가 저유사도 결과를
반환하지 않고 적절한 안내 메시지를 반환하는지 검증한다.
"""

import pytest
from dotenv import load_dotenv

load_dotenv()

from app.tools import search_ifrs, _step1_identify_standard, _SIMILARITY_THRESHOLD
from app.db import get_connection
from app.embedder import embed_query


class TestSimilarityThreshold:
    """유사도 임계값 테스트."""

    def test_threshold_constant_exists(self):
        """_SIMILARITY_THRESHOLD 상수가 정의되어 있어야 한다."""
        assert isinstance(_SIMILARITY_THRESHOLD, float)
        assert 0 < _SIMILARITY_THRESHOLD < 1

    def test_relevant_query_passes_threshold(self):
        """회계 관련 질문은 임계값을 통과해야 한다."""
        result = search_ifrs.invoke("충당부채 인식 조건")
        assert "찾을 수 없습니다" not in result
        assert "기준서" in result

    def test_irrelevant_query_blocked_by_threshold(self):
        """회계와 무관한 질문은 임계값에 걸려 안내 메시지를 반환해야 한다."""
        result = search_ifrs.invoke("오늘 날씨 어때")
        assert "찾을 수 없습니다" in result or "유사도" in result

    def test_irrelevant_english_query_blocked(self):
        """영어 무관 질문도 임계값에 걸려야 한다."""
        result = search_ifrs.invoke("hello world how are you")
        assert "찾을 수 없습니다" in result or "유사도" in result

    def test_borderline_query_still_returns_results(self):
        """'리스 식별' 같은 짧은 관련 질문(유사도 ~0.3)은 통과해야 한다."""
        result = search_ifrs.invoke("리스 식별")
        assert "찾을 수 없습니다" not in result

    def test_step1_returns_empty_for_low_similarity(self):
        """_step1_identify_standard에 임계값 적용 시 저유사도 결과가 필터링되어야 한다."""
        emb = embed_query("맛있는 파스타 레시피")
        with get_connection() as conn:
            standards = _step1_identify_standard(conn, emb, top_k=5)

        # 모든 결과가 임계값 미만이어야 함
        if standards:
            top_sim = standards[0][2]
            assert top_sim < _SIMILARITY_THRESHOLD, (
                f"무관 질문인데 유사도 {top_sim:.3f}가 임계값 {_SIMILARITY_THRESHOLD}을 초과"
            )
