"""Cohere Reranker 래퍼."""

import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass

import cohere

logger = logging.getLogger(__name__)

_client: cohere.Client | None = None

# ---------------------------------------------------------------------------
# 리랭커 캐시 — 동일 (query, documents) 조합 재호출 방지 (~1-2s 절감)
# ---------------------------------------------------------------------------
_RERANK_CACHE_TTL = 300  # 5분
_RERANK_CACHE_MAX_SIZE = 100


@dataclass
class _RerankCacheEntry:
    indices: list[int]
    created_at: float


_rerank_cache: dict[str, _RerankCacheEntry] = {}
_rerank_cache_lock = threading.Lock()


def _rerank_cache_key(query: str, documents: list[str], top_n: int) -> str:
    """(query, documents, top_n)의 해시 키 생성."""
    h = hashlib.sha256()
    h.update(query.encode())
    for doc in documents:
        h.update(doc.encode())
    h.update(str(top_n).encode())
    return h.hexdigest()


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

    동일 (query, documents, top_n) 조합은 캐시에서 반환.

    Args:
        query: 검색 쿼리
        documents: 재정렬할 문서 텍스트 리스트
        top_n: 반환할 상위 문서 수

    Returns:
        재정렬된 문서의 원본 인덱스 리스트 (relevance 내림차순)
    """
    if not documents:
        return []

    now = time.monotonic()
    cache_key = _rerank_cache_key(query, documents, top_n)

    # 캐시 확인
    with _rerank_cache_lock:
        entry = _rerank_cache.get(cache_key)
        if entry and (now - entry.created_at) < _RERANK_CACHE_TTL:
            logger.debug("Reranker 캐시 히트: %s", query[:40])
            return entry.indices

    try:
        client = _get_client()
        response = client.rerank(
            model="rerank-v3.5",
            query=query,
            documents=documents,
            top_n=min(top_n, len(documents)),
        )
        indices = [r.index for r in response.results]

        # 캐시 저장
        with _rerank_cache_lock:
            _rerank_cache[cache_key] = _RerankCacheEntry(
                indices=indices, created_at=now
            )
            expired = [
                k
                for k, v in _rerank_cache.items()
                if (now - v.created_at) >= _RERANK_CACHE_TTL
            ]
            for k in expired:
                del _rerank_cache[k]
            while len(_rerank_cache) > _RERANK_CACHE_MAX_SIZE:
                oldest = min(_rerank_cache, key=lambda k: _rerank_cache[k].created_at)
                del _rerank_cache[oldest]

        return indices
    except Exception as e:
        logger.warning("Reranker 실패, RRF 순서 유지: %s", e)
        return list(range(min(top_n, len(documents))))
