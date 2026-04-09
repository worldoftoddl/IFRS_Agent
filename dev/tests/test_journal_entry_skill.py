"""journal-entry SKILL.md 품질 검증 테스트.

run 분석에서 발견된 문제:
1. 계산 문제에서 불필요하게 skill을 읽음 → description이 트리거 조건을 명확히 제한해야 함
2. "분개해줘" 후속 요청에 이전 답변 반복 → 후속 요청 가이드가 필요
3. 구체적 예시 없음 → 실제 분개 예시가 포함되어야 함
"""

from pathlib import Path

import yaml

SKILL_PATH = Path(__file__).parent.parent.parent / "app" / "skills" / "journal-entry" / "SKILL.md"


def _parse_skill(path: Path) -> tuple[dict, str]:
    """SKILL.md를 frontmatter(YAML)와 body로 분리."""
    text = path.read_text()
    assert text.startswith("---"), "frontmatter가 없음"
    parts = text.split("---", 2)
    frontmatter = yaml.safe_load(parts[1])
    body = parts[2]
    return frontmatter, body


class TestSkillFileStructure:
    """SKILL.md 파일 구조 검증."""

    def test_file_exists(self):
        assert SKILL_PATH.exists()

    def test_has_valid_frontmatter(self):
        fm, _ = _parse_skill(SKILL_PATH)
        assert fm["name"] == "journal-entry"
        assert "description" in fm


class TestTriggerCondition:
    """트리거 조건 — description이 분개/회계처리 요청에만 매칭되도록."""

    def test_description_mentions_journal_keywords(self):
        fm, _ = _parse_skill(SKILL_PATH)
        desc = fm["description"]
        assert "분개" in desc

    def test_description_excludes_calculation(self):
        """description이 순수 계산 문제까지 매칭되지 않도록."""
        fm, _ = _parse_skill(SKILL_PATH)
        desc = fm["description"]
        # description에 "계산", "풀이" 같은 단어가 없어야 함
        assert "계산" not in desc, "description이 계산 문제에도 매칭될 수 있음"
        assert "풀이" not in desc, "description이 풀이 문제에도 매칭될 수 있음"


class TestFollowUpGuidance:
    """후속 요청 가이드 — '이전 답변 기반 분개' 패턴 지원."""

    def test_has_follow_up_section(self):
        """이전 대화 컨텍스트 활용 안내가 있어야 함."""
        _, body = _parse_skill(SKILL_PATH)
        # "이전", "대화", "컨텍스트", "재검색" 중 관련 키워드 존재
        has_follow_up = any(
            kw in body for kw in ["이전", "재검색", "기존 답변", "대화 맥락"]
        )
        assert has_follow_up, "후속 요청 가이드가 없음"

    def test_warns_against_redundant_search(self):
        """불필요한 재검색 방지 안내가 있어야 함."""
        _, body = _parse_skill(SKILL_PATH)
        has_warning = any(
            kw in body for kw in ["재검색하지", "다시 검색하지", "검색 없이"]
        )
        assert has_warning, "불필요한 재검색 방지 안내가 없음"


class TestConcreteExamples:
    """구체적 분개 예시 포함 검증."""

    def test_has_journal_entry_example(self):
        """실제 차변/대변 분개 예시가 있어야 함."""
        _, body = _parse_skill(SKILL_PATH)
        assert "(차)" in body and "(대)" in body, "분개 예시가 없음"

    def test_has_multiple_transaction_types(self):
        """2개 이상의 거래 유형 예시가 있어야 함."""
        _, body = _parse_skill(SKILL_PATH)
        # 대표적인 거래 유형 키워드
        types_found = sum(
            1 for kw in ["차입원가", "리스", "사채", "충당부채", "수익", "감가상각"]
            if kw in body
        )
        assert types_found >= 2, f"거래 유형 예시가 부족함: {types_found}개"


class TestOutputFormat:
    """출력 형식 가이드 검증."""

    def test_has_date_format_guidance(self):
        """날짜별 분개 형식 안내가 있어야 함."""
        _, body = _parse_skill(SKILL_PATH)
        has_date = any(kw in body for kw in ["날짜", "일자", "시점"])
        assert has_date, "날짜별 분개 형식 안내가 없음"

    def test_has_balance_verification(self):
        """대차 균형 검증 안내가 있어야 함."""
        _, body = _parse_skill(SKILL_PATH)
        assert "대차" in body or "균형" in body, "대차 균형 검증 안내가 없음"

    def test_has_basis_citation_guidance(self):
        """근거 기준서 인용 안내가 있어야 함."""
        _, body = _parse_skill(SKILL_PATH)
        assert "근거" in body or "기준서" in body, "근거 인용 안내가 없음"
