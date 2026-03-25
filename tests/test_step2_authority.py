"""Step 2 authority 동적 필터 테스트.

_step2_search_authoritative가 기준서의 base_authority에 따라
authority 필터를 동적으로 적용하는지 검증한다.

테스트는 실제 DB(kifrs)에 연결하여 수행한다.
"""

import pytest
from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection
from app.embedder import embed_query
from app.tools import _step2_search_authoritative


@pytest.fixture
def conn():
    """DB 커넥션 컨텍스트 매니저."""
    with get_connection() as c:
        yield c


@pytest.fixture
def query_emb():
    """테스트용 임베딩 벡터 (한 번만 생성)."""
    return embed_query("측정기준 역사적 원가 현행원가 이행가치")


class TestStep2AuthorityFilter:
    """Step 2 authority 필터가 base_authority에 따라 동적으로 적용되는지 검증."""

    def test_normal_standard_returns_authority_1_only(self, conn, query_emb):
        """일반 기준서(base_authority=1)는 authority=1 청크만 반환해야 한다."""
        rows, _ = _step2_search_authoritative(conn, query_emb, "K-IFRS 1037")

        assert len(rows) > 0, "K-IFRS 1037에서 검색 결과가 없음"
        authorities = {r[5] for r in rows}  # authority는 인덱스에 없으므로 DB에서 확인
        # 반환된 모든 청크의 component가 main/ag/definitions/transition이어야 함
        components = {r[2] for r in rows}
        assert components <= {"main", "ag", "definitions", "transition"}, (
            f"authority=1 기준서에서 bc/ie 컴포넌트가 반환됨: {components}"
        )

    def test_conceptual_framework_returns_authority_3(self, conn, query_emb):
        """개념체계(base_authority=3)는 authority<=3 청크를 반환해야 한다.
        authority=1만 반환하면 실패 — 개념체계 본문(authority=3)이 포함되어야 한다."""
        rows, _ = _step2_search_authoritative(conn, query_emb, "재무보고 개념체계")

        assert len(rows) >= 5, (
            f"개념체계에서 충분한 검색 결과가 없음 ({len(rows)}개) — authority 필터 문제"
        )

    def test_conceptual_framework_excludes_bc_ie(self, conn, query_emb):
        """개념체계에서도 bc/ie(authority=4)는 제외되어야 한다."""
        rows, _ = _step2_search_authoritative(conn, query_emb, "재무보고 개념체계")

        if len(rows) == 0:
            pytest.skip("개념체계 검색 결과 없음 — authority 필터 미수정")

        components = {r[2] for r in rows}
        assert "bc" not in components, "개념체계에서 bc 컴포넌트가 반환됨"
        assert "ie" not in components, "개념체계에서 ie 컴포넌트가 반환됨"

    def test_conceptual_framework_has_measurement_paragraphs(self, conn):
        """개념체계에서 '측정' 관련 문단(6장)이 검색되는지 확인."""
        emb = embed_query("이행가치 현행원가 공정가치 역사적 원가")
        rows, _ = _step2_search_authoritative(conn, emb, "재무보고 개념체계")

        if len(rows) == 0:
            pytest.fail("개념체계에서 측정 관련 검색 결과 없음 — authority 필터 문제")

        # 반환된 문단 중 section_title이나 content에 '측정' 관련 내용이 있어야 함
        all_content = " ".join(r[4] for r in rows)  # content_markdown
        assert "측정" in all_content or "원가" in all_content, (
            "개념체계 검색 결과에 측정 관련 내용이 없음"
        )

    def test_practice_statement_returns_results(self, conn):
        """실무서(base_authority=4)도 검색 가능해야 한다."""
        emb = embed_query("중요성 판단")
        rows, _ = _step2_search_authoritative(conn, emb, "실무서 2 중요성")

        assert len(rows) > 0, "실무서에서 검색 결과가 없음 — authority 필터 문제"

    def test_para_numbers_extracted(self, conn, query_emb):
        """para_numbers가 올바르게 추출되어야 한다."""
        _, para_nums = _step2_search_authoritative(conn, query_emb, "K-IFRS 1037")

        assert isinstance(para_nums, list)
        assert all(isinstance(p, str) for p in para_nums)
