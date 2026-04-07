"""Upstage Solar Embedding 쿼리 래퍼."""

import logging
import os
import threading
import time
from dataclasses import dataclass

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

logger = logging.getLogger(__name__)

# Upstage embedding-query 최대 4000토큰, 한국어 ~1.3 chars/token → 5000자 절단
_MAX_CHARS = 5000

_client: OpenAI | None = None
_client_lock = threading.Lock()

# ---------------------------------------------------------------------------
# 임베딩 캐시 — 동일 쿼리에 대한 API 재호출 방지 (~2-3s 절감)
# ---------------------------------------------------------------------------
_EMBED_CACHE_TTL = 3600  # 1시간
_EMBED_CACHE_MAX_SIZE = 200


@dataclass
class _EmbedCacheEntry:
    embedding: list[float]
    created_at: float


_embed_cache: dict[str, _EmbedCacheEntry] = {}
_embed_cache_lock = threading.Lock()


def _get_client() -> OpenAI:
    """싱글턴 OpenAI 클라이언트 반환 (thread-safe)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                api_key = os.environ.get("UPSTAGE_API_KEY")
                if not api_key:
                    raise RuntimeError("UPSTAGE_API_KEY 환경변수가 설정되지 않았습니다.")
                _client = OpenAI(
                    api_key=api_key,
                    base_url="https://api.upstage.ai/v1",
                )
    return _client


def embed_query(text: str, max_retries: int = 3) -> list[float]:
    """검색 쿼리를 Upstage embedding-query로 임베딩. 동일 쿼리는 캐시 반환."""
    clean = text.strip() or "empty"
    if len(clean) > _MAX_CHARS:
        clean = clean[:_MAX_CHARS]

    now = time.monotonic()

    # 캐시 확인
    with _embed_cache_lock:
        entry = _embed_cache.get(clean)
        if entry and (now - entry.created_at) < _EMBED_CACHE_TTL:
            logger.debug("Embedding 캐시 히트: %s", clean[:40])
            return entry.embedding

    # API 호출
    client = _get_client()
    for attempt in range(max_retries):
        try:
            response = client.embeddings.create(input=clean, model="embedding-query")
            embedding = response.data[0].embedding

            # 캐시 저장
            with _embed_cache_lock:
                _embed_cache[clean] = _EmbedCacheEntry(
                    embedding=embedding, created_at=now
                )
                # 만료 항목 정리 + max size 제한
                expired = [
                    k
                    for k, v in _embed_cache.items()
                    if (now - v.created_at) >= _EMBED_CACHE_TTL
                ]
                for k in expired:
                    del _embed_cache[k]
                while len(_embed_cache) > _EMBED_CACHE_MAX_SIZE:
                    oldest = min(_embed_cache, key=lambda k: _embed_cache[k].created_at)
                    del _embed_cache[oldest]

            return embedding
        except (APIConnectionError, APITimeoutError, RateLimitError) as e:
            if attempt == max_retries - 1:
                raise
            wait = 2**attempt
            logger.warning("Embedding 시도 %d 실패: %s — %d초 후 재시도", attempt + 1, e, wait)
            time.sleep(wait)
    raise RuntimeError("embed_query: 모든 재시도 실패")
