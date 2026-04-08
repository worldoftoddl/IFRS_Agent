"""tsvector 컬럼 및 GIN 인덱스 존재 검증.

chunks 테이블에 content_tsv 컬럼이 추가되고,
GIN 인덱스가 생성되어 BM25 검색이 가능한지 검증한다.
"""

import pytest
from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection


class TestTsvectorSetup:
    """tsvector 인프라 검증."""

    def test_content_tsv_column_exists(self):
        """chunks 테이블에 content_tsv 컬럼이 존재해야 한다."""
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'chunks' AND column_name = 'content_tsv'
                """
            ).fetchone()
        assert row is not None, "content_tsv 컬럼이 chunks 테이블에 없음"

    def test_content_tsv_populated(self):
        """content_tsv 컬럼이 NULL이 아닌 데이터로 채워져 있어야 한다."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT count(*) FROM chunks WHERE content_tsv IS NOT NULL"
            ).fetchone()
            total = conn.execute("SELECT count(*) FROM chunks").fetchone()
        assert row[0] == total[0], (
            f"content_tsv가 채워진 행: {row[0]}/{total[0]}"
        )

    def test_gin_index_exists(self):
        """content_tsv에 GIN 인덱스가 존재해야 한다."""
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT indexname FROM pg_indexes
                WHERE tablename = 'chunks'
                  AND indexdef LIKE '%gin%'
                  AND indexdef LIKE '%content_tsv%'
                """
            ).fetchone()
        assert row is not None, "content_tsv GIN 인덱스가 없음"

    def test_bm25_search_returns_results(self):
        """kiwipiepy 토큰화된 쿼리로 BM25 검색이 동작해야 한다."""
        from app.tokenizer import tokenize_for_query

        query_tokens = tokenize_for_query("충당부채 인식")
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, ts_rank(content_tsv, q) AS rank
                FROM chunks,
                     plainto_tsquery('simple', %s) q
                WHERE content_tsv @@ q
                ORDER BY rank DESC
                LIMIT 5
                """,
                (query_tokens,),
            ).fetchall()
        assert len(rows) > 0, f"BM25 검색 결과 없음 (query_tokens='{query_tokens}')"

    def test_bm25_search_matches_exact_term(self):
        """'이행가치' 토큰화 후 BM25 매칭이 되어야 한다."""
        from app.tokenizer import tokenize_for_query

        query_tokens = tokenize_for_query("이행가치")
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, content_text
                FROM chunks,
                     plainto_tsquery('simple', %s) q
                WHERE content_tsv @@ q
                LIMIT 5
                """,
                (query_tokens,),
            ).fetchall()
        assert len(rows) > 0, f"'이행가치' BM25 매칭 실패 (tokens='{query_tokens}')"
        assert any("이행" in r[1] or "가치" in r[1] for r in rows)
