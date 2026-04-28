"""Dense recall 보강 테스트 — 인접 문단 확장과 평가 설정."""

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection  # noqa: E402
from app.embedder import embed_query  # noqa: E402
from app.tools import _step1_identify_standard, _step2_search_dense  # noqa: E402


class TestDenseCandidatePool:
    """Dense 후보 풀 크기 조절 테스트."""

    def test_dense_accepts_top_k(self):
        """_step2_search_dense가 top_k 파라미터를 받아야 한다."""
        query = "충당부채 인식 조건"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_dense(conn, query_emb, standard_ids, top_k=20)

        assert len(rows) > 0
        assert len(rows) <= 20

    def test_dense_default_is_stable(self):
        """기본 dense 검색과 명시적 top_k=10 결과가 동일해야 한다."""
        query = "수익 인식 시점"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows_default, _ = _step2_search_dense(conn, query_emb, standard_ids)
            rows_explicit, _ = _step2_search_dense(
                conn, query_emb, standard_ids, top_k=10
            )

        assert [r[0] for r in rows_default] == [r[0] for r in rows_explicit]


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
            rows, _ = _step2_search_dense(conn, query_emb, standard_ids, top_k=5)

            original_count = len(rows)
            expanded = _expand_adjacent_paragraphs(conn, rows)

        assert len(expanded) >= original_count

    def test_expand_no_duplicates(self):
        """확장 후 중복 chunk_id가 없어야 한다."""
        from app.tools import _expand_adjacent_paragraphs

        query = "충당부채 인식 조건"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_dense(conn, query_emb, standard_ids, top_k=5)
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
            rows, _ = _step2_search_dense(conn, query_emb, standard_ids, top_k=5)
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
            rows, _ = _step2_search_dense(conn, query_emb, standard_ids, top_k=5)
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
        """확장된 행의 튜플 형식이 원본과 동일해야 한다."""
        from app.tools import _expand_adjacent_paragraphs

        query = "충당부채 측정"
        query_emb = embed_query(query)

        with get_connection() as conn:
            standards = _step1_identify_standard(conn, query_emb, top_k=5)
            standard_ids = [s[0] for s in standards]
            rows, _ = _step2_search_dense(conn, query_emb, standard_ids, top_k=5)
            expanded = _expand_adjacent_paragraphs(conn, rows)

        for row in expanded:
            assert len(row) == 7, f"컬럼 수 불일치: {len(row)} (expected 7)"


class TestEvalConfigs:
    """Dense 기반 평가 설정 검증."""

    def test_dense_reranker_config_exists(self):
        """dense_reranker 평가 설정이 존재해야 한다."""
        from eval.evaluate import SEARCH_CONFIGS

        assert "dense_reranker" in SEARCH_CONFIGS
        cfg = SEARCH_CONFIGS["dense_reranker"]
        assert cfg["mode"] == "dense"
        assert cfg.get("rerank") is True

    def test_phase1_config_exists(self):
        """phase1 통합 평가 설정이 존재해야 한다."""
        from eval.evaluate import SEARCH_CONFIGS

        assert "phase1" in SEARCH_CONFIGS
        cfg = SEARCH_CONFIGS["phase1"]
        assert cfg["mode"] == "dense"
        assert cfg.get("rerank") is True
        assert cfg.get("expand_adjacent") is True
