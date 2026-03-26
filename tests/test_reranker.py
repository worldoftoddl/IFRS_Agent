"""Cohere Reranker 테스트.

app/reranker.py가 Cohere rerank-v3.5 API를 호출하여
문서를 재정렬하고, search_ifrs 파이프라인에 통합되는지 검증.
"""

import os

import pytest
from dotenv import load_dotenv

load_dotenv()


class TestRerankerModule:
    """reranker 모듈 기능 검증."""

    def test_import_rerank(self):
        """rerank 함수를 임포트할 수 있어야 한다."""
        from app.reranker import rerank

        assert callable(rerank)

    def test_rerank_returns_indices(self):
        """rerank가 재정렬된 인덱스 리스트를 반환해야 한다."""
        from app.reranker import rerank

        docs = [
            "충당부채는 지출하는 시기 또는 금액이 불확실한 부채이다.",
            "리스이용자는 리스개시일에 사용권자산과 리스부채를 인식한다.",
            "충당부채는 다음의 요건을 모두 충족하는 경우에 인식한다.",
        ]
        indices = rerank("충당부채 인식 조건", docs, top_n=2)

        assert isinstance(indices, list)
        assert len(indices) == 2
        assert all(isinstance(i, int) for i in indices)
        assert all(0 <= i < len(docs) for i in indices)

    def test_rerank_relevance_ordering(self):
        """관련 문서가 비관련 문서보다 상위에 와야 한다."""
        from app.reranker import rerank

        docs = [
            "날씨가 좋습니다.",
            "충당부채는 다음의 요건을 모두 충족하는 경우에 인식한다.",
            "오늘 점심은 파스타입니다.",
        ]
        indices = rerank("충당부채 인식 조건", docs, top_n=3)

        # 인덱스 1 (충당부채 문단)이 최상위여야 함
        assert indices[0] == 1

    def test_rerank_empty_docs(self):
        """빈 문서 리스트에 대해 빈 결과를 반환해야 한다."""
        from app.reranker import rerank

        indices = rerank("테스트", [], top_n=5)
        assert indices == []

    def test_rerank_top_n_limits_output(self):
        """top_n이 결과 수를 제한해야 한다."""
        from app.reranker import rerank

        docs = ["문서1", "문서2", "문서3", "문서4", "문서5"]
        indices = rerank("테스트", docs, top_n=3)
        assert len(indices) <= 3

    @pytest.mark.skipif(
        not os.environ.get("COHERE_API_KEY"),
        reason="COHERE_API_KEY 환경변수 없음",
    )
    def test_cohere_api_key_configured(self):
        """COHERE_API_KEY가 설정되어 있어야 한다."""
        assert os.environ.get("COHERE_API_KEY")


class TestRerankerIntegration:
    """Reranker + 검색 파이프라인 통합 테스트."""

    def test_search_ifrs_with_reranker(self):
        """search_ifrs가 reranker를 사용하여 결과를 반환해야 한다."""
        from app.tools import search_ifrs

        result = search_ifrs.invoke("충당부채 인식 조건")
        assert "기준서" in result
        assert len(result) > 100
