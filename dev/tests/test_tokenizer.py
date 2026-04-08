"""kiwipiepy 기반 한국어 토크나이저 테스트.

app/tokenizer.py가 한국어 텍스트를 형태소 분석하여
BM25 인덱싱/검색에 적합한 토큰 문자열을 생성하는지 검증.
"""

import pytest
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


class TestBM25WithKiwi:
    """kiwipiepy 토큰화 후 BM25 검색 동작 검증."""

    def test_bm25_matches_after_kiwi_tokenization(self):
        """kiwipiepy 토큰화된 tsvector에서 BM25 검색이 매칭되어야 한다."""
        from app.db import get_connection
        from app.tokenizer import tokenize_for_index, tokenize_for_query

        doc = "충당부채는 다음의 요건을 모두 충족하는 경우에 인식한다"
        query = "충당부채 인식"

        doc_tokens = tokenize_for_index(doc)
        query_tokens = tokenize_for_query(query)

        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT to_tsvector('simple', %(doc)s)
                    @@ plainto_tsquery('simple', %(query)s) AS matched
                """,
                {"doc": doc_tokens, "query": query_tokens},
            ).fetchone()

        assert row[0] is True, (
            f"BM25 매칭 실패. doc_tokens='{doc_tokens}', query_tokens='{query_tokens}'"
        )

    def test_ihaeng_gachi_matches(self):
        """'이행가치란' 문서가 '이행가치' 쿼리와 매칭되어야 한다."""
        from app.db import get_connection
        from app.tokenizer import tokenize_for_index, tokenize_for_query

        doc_tokens = tokenize_for_index("이행가치는 부채를 이행할 때 이전하게 될 현금흐름의 현재가치")
        query_tokens = tokenize_for_query("이행가치")

        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT to_tsvector('simple', %(doc)s)
                    @@ plainto_tsquery('simple', %(query)s) AS matched
                """,
                {"doc": doc_tokens, "query": query_tokens},
            ).fetchone()

        assert row[0] is True
