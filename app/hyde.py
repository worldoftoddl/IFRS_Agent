"""HyDE (Hypothetical Document Embeddings) — 가상 답변 생성기.

사용자 쿼리를 직접 임베딩하는 대신, LLM이 생성한 가상 답변 문서를 임베딩한다.
가상 답변은 실제 기준서 문단과 어휘/구조가 유사하므로 임베딩 거리가 가까워진다.
"""

import logging
import os

from anthropic import Anthropic

logger = logging.getLogger(__name__)

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    return _client


_HYDE_PROMPT = """\
당신은 K-IFRS(한국채택국제회계기준) 전문가입니다.
아래 질문에 대해 K-IFRS 기준서 본문에 있을 법한 답변을 작성하세요.

규칙:
- 기준서 본문 스타일로 작성 (문단 번호 없이)
- 핵심 회계 용어를 반드시 포함
- 100~200자 내외로 간결하게
- 정확하지 않아도 됨 — 관련 용어가 포함되는 것이 중요

질문: {query}

답변:"""


def generate_hypothetical_answer(query: str) -> str:
    """쿼리에 대한 가상 답변을 생성.

    Claude Haiku를 사용하여 비용 최소화.
    실패 시 원본 쿼리를 반환 (graceful degradation).
    """
    if not query.strip():
        return query

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[
                {"role": "user", "content": _HYDE_PROMPT.format(query=query)},
            ],
        )
        text = response.content[0].text.strip()

        if not text:
            return query

        logger.debug("HyDE 가상 답변: %s → %s", query, text[:100])
        return text

    except Exception as e:
        logger.warning("HyDE 가상 답변 생성 실패, 원본 쿼리 사용: %s", e)
        return query
