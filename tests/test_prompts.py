"""시스템 프롬프트가 필요한 지침을 포함하는지 검증.

Agent가 올바르게 동작하려면 프롬프트에 특정 규칙이 반드시 포함되어야 한다.
"""

from app.prompts import SYSTEM_PROMPT


class TestSystemPromptContents:
    """시스템 프롬프트 필수 지침 검증."""

    def test_contains_tool_usage_instruction(self):
        """도구 사용 지시가 포함되어야 한다."""
        assert "search_ifrs" in SYSTEM_PROMPT

    def test_contains_authority_level_guidance(self):
        """권위 수준 구분 지침이 포함되어야 한다."""
        assert "Level 1" in SYSTEM_PROMPT
        assert "Level 4" in SYSTEM_PROMPT

    def test_contains_korean_response_instruction(self):
        """한국어 답변 지시가 포함되어야 한다."""
        assert "한국어" in SYSTEM_PROMPT

    def test_contains_repeat_call_limit(self):
        """동일 도구 반복 호출 제한 규칙이 포함되어야 한다."""
        assert "3회" in SYSTEM_PROMPT or "3번" in SYSTEM_PROMPT

    def test_contains_search_failure_fallback(self):
        """검색 실패 시 행동 지침이 포함되어야 한다."""
        assert "부족" in SYSTEM_PROMPT or "없으면" in SYSTEM_PROMPT

    def test_contains_tool_error_guidance(self):
        """도구 에러 시 안내 지침이 포함되어야 한다."""
        assert "에러" in SYSTEM_PROMPT or "오류" in SYSTEM_PROMPT

    def test_contains_citation_instruction(self):
        """근거 문단 인용 지시가 포함되어야 한다."""
        assert "문단" in SYSTEM_PROMPT
        assert "인용" in SYSTEM_PROMPT
