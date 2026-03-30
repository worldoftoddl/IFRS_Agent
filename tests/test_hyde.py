"""HyDE (Hypothetical Document Embeddings) 테스트.

TDD RED phase: 구현 전에 작성.
"""

from dotenv import load_dotenv

load_dotenv()


class TestHyDEFunction:
    """generate_hypothetical_answer 함수 테스트."""

    def test_function_exists(self):
        """hyde 모듈에 generate_hypothetical_answer 함수가 존재해야 한다."""
        from app.hyde import generate_hypothetical_answer
        assert callable(generate_hypothetical_answer)

    def test_returns_string(self):
        """가상 답변은 문자열이어야 한다."""
        from app.hyde import generate_hypothetical_answer
        result = generate_hypothetical_answer("충당부채 인식 조건은?")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_answer_longer_than_query(self):
        """가상 답변은 원본 쿼리보다 길어야 한다 (임베딩에 더 많은 정보 제공)."""
        from app.hyde import generate_hypothetical_answer
        query = "충당부채 인식 조건은?"
        result = generate_hypothetical_answer(query)
        assert len(result) > len(query), (
            f"가상 답변({len(result)}자)이 쿼리({len(query)}자)보다 짧음"
        )

    def test_answer_contains_relevant_terms(self):
        """가상 답변에 관련 회계 용어가 포함되어야 한다."""
        from app.hyde import generate_hypothetical_answer
        result = generate_hypothetical_answer("충당부채 인식 조건은?")
        # 충당부채 관련 핵심 용어 중 최소 하나 포함
        terms = ["충당부채", "의무", "인식", "부채", "유출"]
        assert any(t in result for t in terms), (
            f"관련 용어 없음: {result[:200]}"
        )

    def test_graceful_degradation(self):
        """API 실패 시 원본 쿼리를 반환해야 한다 (graceful degradation)."""
        from app.hyde import generate_hypothetical_answer
        # 빈 쿼리도 처리 가능해야 함
        result = generate_hypothetical_answer("")
        assert isinstance(result, str)


class TestHyDEEvalConfig:
    """평가 설정 테스트."""

    def test_hyde_config_exists(self):
        """hyde 평가 설정이 존재해야 한다."""
        from eval.evaluate import SEARCH_CONFIGS
        assert "hyde" in SEARCH_CONFIGS
        cfg = SEARCH_CONFIGS["hyde"]
        assert cfg.get("hyde") is True
