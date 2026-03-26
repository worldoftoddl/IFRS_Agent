"""Cohere Reranker 래퍼."""

import logging
import os

import cohere

logger = logging.getLogger(__name__)

_client: cohere.Client | None = None


def _get_client() -> cohere.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("COHERE_API_KEY")
        if not api_key:
            raise RuntimeError("COHERE_API_KEY 환경변수가 설정되지 않았습니다.")
        _client = cohere.Client(api_key=api_key)
    return _client


def rerank(query: str, documents: list[str], top_n: int = 10) -> list[int]:
    """Cohere rerank-v3.5로 문서를 재정렬. 재정렬된 인덱스 리스트 반환.

    Args:
        query: 검색 쿼리
        documents: 재정렬할 문서 텍스트 리스트
        top_n: 반환할 상위 문서 수

    Returns:
        재정렬된 문서의 원본 인덱스 리스트 (relevance 내림차순)
    """
    if not documents:
        return []

    try:
        client = _get_client()
        response = client.rerank(
            model="rerank-v3.5",
            query=query,
            documents=documents,
            top_n=min(top_n, len(documents)),
        )
        return [r.index for r in response.results]
    except Exception as e:
        logger.warning("Reranker 실패, RRF 순서 유지: %s", e)
        return list(range(min(top_n, len(documents))))
