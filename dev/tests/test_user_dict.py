"""kiwipiepy 사용자 사전 테스트.

K-IFRS 핵심 복합명사가 사용자 사전에 등록되어
kiwipiepy 토큰화 시 분리되지 않고 보존되는지 검증.
"""

import pytest
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

DICT_PATH = Path(__file__).parent.parent / "app" / "kiwi_user_dict.txt"


class TestUserDictFile:
    """사용자 사전 파일 검증."""

    def test_dict_file_exists(self):
        """kiwi_user_dict.txt 파일이 존재해야 한다."""
        assert DICT_PATH.exists()

    def test_dict_has_min_terms(self):
        """최소 50개 이상의 용어가 등록되어야 한다."""
        terms = [l.strip() for l in DICT_PATH.read_text().splitlines() if l.strip() and not l.startswith("#")]
        assert len(terms) >= 50, f"용어 {len(terms)}개 — 최소 50개 필요"

    def test_dict_contains_key_terms(self):
        """핵심 K-IFRS 복합명사가 포함되어야 한다."""
        content = DICT_PATH.read_text()
        key_terms = ["충당부채", "사용권자산", "이행가치", "공정가치", "리스부채", "당기손익"]
        for term in key_terms:
            assert term in content, f"'{term}'이 사전에 없음"


class TestTokenizerWithDict:
    """사용자 사전 적용 후 토큰화 검증."""

    def test_compound_nouns_preserved(self):
        """복합명사가 분리되지 않고 보존되어야 한다."""
        from app.tokenizer import tokenize_for_index

        test_cases = [
            ("충당부채는 현재의무이다", "충당부채"),
            ("사용권자산을 인식한다", "사용권자산"),
            ("이행가치로 측정한다", "이행가치"),
            ("공정가치 측정", "공정가치"),
            ("리스부채를 인식한다", "리스부채"),
        ]
        for text, expected_term in test_cases:
            result = tokenize_for_index(text)
            assert expected_term in result, (
                f"'{expected_term}'이 분리됨: '{text}' → '{result}'"
            )

    def test_query_term_preserved(self):
        """쿼리에서도 복합명사가 보존되어야 한다."""
        from app.tokenizer import tokenize_for_query

        result = tokenize_for_query("충당부채 인식 조건")
        assert "충당부채" in result

    def test_bm25_matches_with_compound_nouns(self):
        """사용자 사전 적용 후 BM25 매칭이 동작해야 한다."""
        from app.db import get_connection
        from app.tokenizer import tokenize_for_query

        query_tokens = tokenize_for_query("충당부채 인식")
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id
                FROM chunks,
                     plainto_tsquery('simple', %s) q
                WHERE content_tsv @@ q
                LIMIT 5
                """,
                (query_tokens,),
            ).fetchall()
        assert len(rows) > 0, f"BM25 매칭 실패 (tokens='{query_tokens}')"
