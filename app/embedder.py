"""Upstage Solar Embedding 쿼리 래퍼."""

import logging
import os
import threading
import time

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

logger = logging.getLogger(__name__)

# Upstage embedding-query 최대 4000토큰, 한국어 ~1.3 chars/token → 5000자 절단
_MAX_CHARS = 5000

_client: OpenAI | None = None
_client_lock = threading.Lock()


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
    """검색 쿼리를 Upstage embedding-query로 임베딩."""
    clean = text.strip() or "empty"
    if len(clean) > _MAX_CHARS:
        clean = clean[:_MAX_CHARS]

    client = _get_client()
    for attempt in range(max_retries):
        try:
            response = client.embeddings.create(input=clean, model="embedding-query")
            return response.data[0].embedding
        except (APIConnectionError, APITimeoutError, RateLimitError) as e:
            if attempt == max_retries - 1:
                raise
            wait = 2**attempt
            logger.warning("Embedding 시도 %d 실패: %s — %d초 후 재시도", attempt + 1, e, wait)
            time.sleep(wait)
    raise RuntimeError("embed_query: 모든 재시도 실패")  # max_retries <= 0인 경우 도달
