"""Multi-Query 변형 생성기.

LLM(Claude Haiku)으로 원본 쿼리를 3~4개 다른 관점의 변형으로 생성.
각 변형이 임베딩 공간에서 다른 영역을 탐색하여 후보 풀 다양성 확보.
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


_VARIANT_PROMPT = """\
당신은 K-IFRS(한국채택국제회계기준) 검색 전문가입니다.
아래 원본 쿼리를 벡터 검색에 최적화된 3개의 변형 쿼리로 변환하세요.

규칙:
- 각 변형은 원본과 다른 키워드/표현을 사용하되 같은 의미
- K-IFRS 기준서의 공식 용어를 활용
- 한국어로 작성
- 각 줄에 하나의 변형만 출력 (번호 없이)

원본 쿼리: {query}

변형 쿼리:"""


def generate_query_variants(query: str, n: int = 3) -> list[str]:
    """원본 쿼리를 N개의 변형으로 생성.

    Claude Haiku를 사용하여 비용 최소화.
    실패 시 원본 쿼리만 반환 (graceful degradation).
    """
    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[
                {"role": "user", "content": _VARIANT_PROMPT.format(query=query)},
            ],
        )
        text = response.content[0].text.strip()
        variants = [line.strip() for line in text.split("\n") if line.strip()]
        variants = variants[:n]

        if not variants:
            return [query]

        logger.debug("Multi-query 변형: %s → %s", query, variants)
        return variants

    except Exception as e:
        logger.warning("Multi-query 변형 생성 실패, 원본 사용: %s", e)
        return [query]
