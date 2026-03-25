"""Upstage Solar Embedding 쿼리 래퍼."""

import os
import time

from openai import OpenAI

# Upstage embedding-query 최대 4000토큰, 한국어 ~1.3 chars/token → 5000자 절단
_MAX_CHARS = 5000

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ.get("UPSTAGE_API_KEY", ""),
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
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = 2**attempt
            time.sleep(wait)
    return []
