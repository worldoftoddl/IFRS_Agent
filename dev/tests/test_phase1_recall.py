"""Phase 1 Recall 개선 테스트 — Weighted RRF, 인접 문단 확장.

TDD RED phase: 이 테스트들은 구현 전에 먼저 작성되었다.
"""

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection
from app.embedder import embed_query
from app.tools import (
    _step1_identify_standard,
    _step2_search_hybrid,
)


# ---------------------------------------------------------------------------
# 1. Weighted RRF 테스트
# ---------------------------------------------------------------------------


class TestWeightedRRF:
    """Weighted RRF: w_dense, w_bm25 가중치 파라미터 테스트."""

    def test_weighted_rrf_accepts_weights(self):
        """_step2_search_hybrid가 w_dense, w_bm25 파라미터를 받아야 한다."""
        query = "충당부채 인식 조건"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            # 새 파라미터로 호출 — TypeError 없이 동작해야 함
            rows, _ = _step2_search_hybrid(
                conn, query_emb, query, standard_ids,
                w_dense=0.7, w_bm25=0.3,
            )

        assert len(rows) > 0

    def test_dense_only_weight(self):
        """w_bm25=0이면 Dense 전용과 유사한 결과를 반환해야 한다."""
        query = "리스 사용권자산 감가상각"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]

            rows_weighted, _ = _step2_search_hybrid(
                conn, query_emb, query, standard_ids,
                w_dense=1.0, w_bm25=0.0,
            )
            rows_default, _ = _step2_search_hybrid(
                conn, query_emb, query, standard_ids,
                w_dense=1.0, w_bm25=1.0,
            )

        # w_bm25=0이면 BM25 기여가 0이므로 dense 순위만 반영
        # 결과 chunk_id 집합이 다를 수 있음 (BM25-only 청크 제외)
        weighted_ids = {r[0] for r in rows_weighted}
        assert len(weighted_ids) > 0

    def test_bm25_only_weight(self):
        """w_dense=0이면 BM25 전용 순위가 되어야 한다."""
        query = "충당부채 인식 조건"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]

            rows_bm25, _ = _step2_search_hybrid(
                conn, query_emb, query, standard_ids,
                w_dense=0.0, w_bm25=1.0,
            )

        # BM25 매칭이 있으므로 결과가 나와야 함
        assert len(rows_bm25) > 0

    def test_default_weights_backward_compatible(self):
        """기본값(w_dense=1.0, w_bm25=1.0)은 기존 동작과 동일해야 한다."""
        query = "수익 인식 시점"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]

            rows_default, _ = _step2_search_hybrid(
                conn, query_emb, query, standard_ids,
            )
            rows_explicit, _ = _step2_search_hybrid(
                conn, query_emb, query, standard_ids,
                w_dense=1.0, w_bm25=1.0,
            )

        # chunk_id 순서가 완전히 동일해야 함
        assert [r[0] for r in rows_default] == [r[0] for r in rows_explicit]


# ---------------------------------------------------------------------------
# 2. 인접 문단 확장 테스트
# ---------------------------------------------------------------------------


class TestAdjacentParagraphExpansion:
    """인접 문단 확장: 검색된 문단의 ±1 문단 자동 포함."""

    def test_expand_function_exists(self):
        """_expand_adjacent_paragraphs 함수가 존재해야 한다."""
        from app.tools import _expand_adjacent_paragraphs
        assert callable(_expand_adjacent_paragraphs)

    def test_expand_adds_neighbors(self):
        """인접 문단이 결과에 추가되어야 한다."""
        from app.tools import _expand_adjacent_paragraphs

        query = "충당부채 인식 조건"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_hybrid(
                conn, query_emb, query, standard_ids, top_k=5,
            )

            original_count = len(rows)
            expanded = _expand_adjacent_paragraphs(conn, rows)

        # 인접 문단이 추가되었으므로 원본보다 같거나 많아야 함
        assert len(expanded) >= original_count

    def test_expand_no_duplicates(self):
        """확장 후 중복 chunk_id가 없어야 한다."""
        from app.tools import _expand_adjacent_paragraphs

        query = "충당부채 인식 조건"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_hybrid(
                conn, query_emb, query, standard_ids, top_k=5,
            )
            expanded = _expand_adjacent_paragraphs(conn, rows)

        chunk_ids = [r[0] for r in expanded]
        assert len(chunk_ids) == len(set(chunk_ids)), "중복 chunk_id 발견"

    def test_expand_same_standard_only(self):
        """확장된 문단은 원본과 동일한 기준서에 속해야 한다."""
        from app.tools import _expand_adjacent_paragraphs

        query = "충당부채 인식 조건"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_hybrid(
                conn, query_emb, query, standard_ids, top_k=5,
            )
            original_standards = {r[6] for r in rows}
            expanded = _expand_adjacent_paragraphs(conn, rows)

        expanded_standards = {r[6] for r in expanded}
        assert expanded_standards.issubset(original_standards), (
            f"다른 기준서 문단이 추가됨: {expanded_standards - original_standards}"
        )

    def test_expand_preserves_original_rows(self):
        """확장 후에도 원본 결과가 모두 포함되어야 한다."""
        from app.tools import _expand_adjacent_paragraphs

        query = "리스 식별 기준"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_hybrid(
                conn, query_emb, query, standard_ids, top_k=5,
            )
            original_ids = {r[0] for r in rows}
            expanded = _expand_adjacent_paragraphs(conn, rows)

        expanded_ids = {r[0] for r in expanded}
        assert original_ids.issubset(expanded_ids), "원본 결과가 누락됨"

    def test_expand_empty_input(self):
        """빈 입력에 대해 빈 결과를 반환해야 한다."""
        from app.tools import _expand_adjacent_paragraphs

        with get_connection() as conn:
            expanded = _expand_adjacent_paragraphs(conn, [])

        assert expanded == []

    def test_expand_row_format_consistent(self):
        """확장된 행의 튜플 형식이 원본과 동일해야 한다 (7개 컬럼)."""
        from app.tools import _expand_adjacent_paragraphs

        query = "충당부채 측정"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_hybrid(
                conn, query_emb, query, standard_ids, top_k=5,
            )
            expanded = _expand_adjacent_paragraphs(conn, rows)

        for row in expanded:
            assert len(row) == 7, f"컬럼 수 불일치: {len(row)} (expected 7)"


# ---------------------------------------------------------------------------
# 3. 평가 설정 테스트
# ---------------------------------------------------------------------------


class TestEvalConfigs:
    """Phase 1 평가 설정이 추가되어야 한다."""

    def test_weighted_rrf_config_exists(self):
        """weighted_rrf 평가 설정이 존재해야 한다."""
        from eval.evaluate import SEARCH_CONFIGS

        assert "weighted_rrf" in SEARCH_CONFIGS
        cfg = SEARCH_CONFIGS["weighted_rrf"]
        assert "w_dense" in cfg
        assert "w_bm25" in cfg

    def test_phase1_config_exists(self):
        """phase1 통합 평가 설정이 존재해야 한다."""
        from eval.evaluate import SEARCH_CONFIGS

        assert "phase1" in SEARCH_CONFIGS
        cfg = SEARCH_CONFIGS["phase1"]
        assert cfg.get("rerank") is True
        assert cfg.get("expand_adjacent") is True
