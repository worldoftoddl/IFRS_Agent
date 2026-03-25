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
        """plainto_tsquery로 BM25 검색이 동작해야 한다."""
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, ts_rank(content_tsv, q) AS rank
                FROM chunks,
                     plainto_tsquery('simple', '충당부채 인식') q
                WHERE content_tsv @@ q
                ORDER BY rank DESC
                LIMIT 5
                """
            ).fetchall()
        assert len(rows) > 0, "BM25 검색 결과가 없음"

    def test_bm25_search_matches_exact_term(self):
        """정확한 용어 '이행가치'로 검색 시 해당 용어가 포함된 문단이 반환되어야 한다."""
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, content_text
                FROM chunks,
                     plainto_tsquery('simple', '이행가치') q
                WHERE content_tsv @@ q
                LIMIT 5
                """
            ).fetchall()
        assert len(rows) > 0, "'이행가치' BM25 검색 결과가 없음"
        assert any("이행가치" in r[1] for r in rows), (
            "반환된 문단에 '이행가치'가 포함되지 않음"
        )

    def test_trigger_exists(self):
        """content_text 변경 시 content_tsv를 자동 갱신하는 트리거가 존재해야 한다."""
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT trigger_name FROM information_schema.triggers
                WHERE event_object_table = 'chunks'
                  AND trigger_name = 'trg_chunks_tsv'
                """
            ).fetchone()
        assert row is not None, "trg_chunks_tsv 트리거가 없음"
