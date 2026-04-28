"""kiwipiepy 기반 한국어 토크나이저 테스트.

app/tokenizer.py가 한국어 텍스트를 형태소 분석하여 기존 tsvector 유산과
용어 추출 보조 작업에 사용할 수 있는 토큰 문자열을 생성하는지 검증.
"""

from dotenv import load_dotenv

load_dotenv()


class TestTokenizer:
    """토크나이저 기능 검증."""

    def test_import_tokenizer(self):
        """tokenizer 모듈을 임포트할 수 있어야 한다."""
        from app.tokenizer import tokenize_for_index, tokenize_for_query

        assert callable(tokenize_for_index)
        assert callable(tokenize_for_query)

    def test_tokenize_splits_agglutinative(self):
        """교착어 조사가 분리되어야 한다. '충당부채는' → '충당' '부채' 포함."""
        from app.tokenizer import tokenize_for_index

        result = tokenize_for_index("충당부채는 현재의무이다")
        assert "충당" in result
        assert "부채" in result

    def test_query_matches_index(self):
        """쿼리 '충당부채'와 문서 '충당부채는'이 동일한 토큰을 공유해야 한다."""
        from app.tokenizer import tokenize_for_index, tokenize_for_query

        doc_tokens = set(tokenize_for_index("충당부채는 현재의무이다").split())
        query_tokens = set(tokenize_for_query("충당부채").split())

        overlap = doc_tokens & query_tokens
        assert len(overlap) > 0, (
            f"문서와 쿼리 토큰이 겹치지 않음. doc={doc_tokens}, query={query_tokens}"
        )

    def test_tokenize_preserves_numbers(self):
        """문단 번호가 보존되어야 한다."""
        from app.tokenizer import tokenize_for_index

        result = tokenize_for_index("14 충당부채는 다음의 요건을 모두 충족하는 경우에 인식한다")
        assert "14" in result

    def test_tokenize_empty_string(self):
        """빈 문자열에 대해 빈 문자열을 반환해야 한다."""
        from app.tokenizer import tokenize_for_index

        assert tokenize_for_index("") == ""

    def test_tokenize_for_query_strips_particles(self):
        """쿼리에서 조사가 분리되어 핵심 명사가 추출되어야 한다."""
        from app.tokenizer import tokenize_for_query

        result = tokenize_for_query("이행가치란 무엇인가")
        assert "이행" in result
        assert "가치" in result
