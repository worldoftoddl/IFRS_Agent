"""Phase 3 — 에이전트 기반 end-to-end 평가 테스트.

검증 대상:
- extract_paragraph_citations: 최종 답변에서 기준서/문단 인용 추출
- run_agent_evaluation: agent.invoke → 결과 dict 반환
"""

from dotenv import load_dotenv

load_dotenv()


class TestExtractParagraphCitations:
    """최종 답변 텍스트에서 (standard_id, para_number) 인용 추출."""

    def test_basic_citation(self):
        from eval.evaluate_agent import extract_paragraph_citations

        text = "K-IFRS 1037 문단 14에 따르면, 충당부채는 과거사건의 결과입니다."
        result = extract_paragraph_citations(text)
        assert ("K-IFRS 1037", "14") in result

    def test_multiple_citations(self):
        from eval.evaluate_agent import extract_paragraph_citations

        text = (
            "K-IFRS 1037 문단 14에 따르면 ... 또한 K-IFRS 1037 문단 36에서도 "
            "측정 방법을 규정하고 있으며, K-IFRS 1115 문단 22에서는..."
        )
        result = extract_paragraph_citations(text)
        assert ("K-IFRS 1037", "14") in result
        assert ("K-IFRS 1037", "36") in result
        assert ("K-IFRS 1115", "22") in result

    def test_korean_prefix_paragraph(self):
        """한국 고유 추가사항 문단 '한15' 추출."""
        from eval.evaluate_agent import extract_paragraph_citations

        text = "K-IFRS 1115 문단 한15에 따르면..."
        result = extract_paragraph_citations(text)
        assert ("K-IFRS 1115", "한15") in result

    def test_paragraph_with_letter_suffix(self):
        """'14A', '82B' 같은 문단 번호 추출."""
        from eval.evaluate_agent import extract_paragraph_citations

        text = "K-IFRS 1037 문단 14A에서는..."
        result = extract_paragraph_citations(text)
        assert ("K-IFRS 1037", "14A") in result

    def test_no_citations(self):
        from eval.evaluate_agent import extract_paragraph_citations

        text = "오늘 날씨가 좋네요."
        result = extract_paragraph_citations(text)
        assert result == []

    def test_deduplicates_same_citation(self):
        from eval.evaluate_agent import extract_paragraph_citations

        text = "K-IFRS 1037 문단 14 ... K-IFRS 1037 문단 14 ..."
        result = extract_paragraph_citations(text)
        # 동일한 (sid, para)는 한 번만
        assert result.count(("K-IFRS 1037", "14")) == 1

    def test_conceptual_framework(self):
        """개념체계 인용도 감지 (선택적 — 지원하면 좋음)."""
        from eval.evaluate_agent import extract_paragraph_citations

        text = "재무보고 개념체계 문단 4.5에 따르면..."
        result = extract_paragraph_citations(text)
        # 개념체계도 감지 가능해야 함 (느슨한 검증)
        assert any("개념체계" in sid for sid, _ in result)

    # --- 누락 패턴 테스트 (Phase 1 확장) ---

    def test_decimal_paragraph(self):
        """소수점 문단 번호 '4.1.2', '5.5.3' 추출."""
        from eval.evaluate_agent import extract_paragraph_citations

        text = "K-IFRS 1109 문단 4.1.2에 따라 금융자산을 분류합니다."
        result = extract_paragraph_citations(text)
        assert ("K-IFRS 1109", "4.1.2") in result

    def test_decimal_paragraph_with_letter(self):
        """소수점+문자 문단 번호 '4.1.2A' 추출."""
        from eval.evaluate_agent import extract_paragraph_citations

        text = "K-IFRS 1109 문단 4.1.2A에 해당하는 경우"
        result = extract_paragraph_citations(text)
        assert ("K-IFRS 1109", "4.1.2A") in result

    def test_b_prefix_paragraph(self):
        """B접두 문단 'B9', 'B21' 추출."""
        from eval.evaluate_agent import extract_paragraph_citations

        text = "K-IFRS 1116 문단 B9에서 리스 식별 기준을 제시합니다."
        result = extract_paragraph_citations(text)
        assert ("K-IFRS 1116", "B9") in result

    def test_kifrs_with_je_prefix(self):
        """'K-IFRS 제1037호' 형식 추출."""
        from eval.evaluate_agent import extract_paragraph_citations

        text = "K-IFRS 제1037호 문단 14에 따르면..."
        result = extract_paragraph_citations(text)
        assert ("K-IFRS 1037", "14") in result

    def test_paragraph_range(self):
        """문단 범위 '42~43' — 각각 별도 인용으로 분리."""
        from eval.evaluate_agent import extract_paragraph_citations

        text = "K-IFRS 1037 문단 42~43에서 규정하고 있습니다."
        result = extract_paragraph_citations(text)
        assert ("K-IFRS 1037", "42") in result
        assert ("K-IFRS 1037", "43") in result

    def test_conceptual_framework_without_prefix(self):
        """'개념체계 문단 6.4' (재무보고 없이) 추출."""
        from eval.evaluate_agent import extract_paragraph_citations

        text = "개념체계 문단 6.4에 따르면 역사적 원가는..."
        result = extract_paragraph_citations(text)
        assert any("개념체계" in sid for sid, _ in result)
        assert any(para == "6.4" for _, para in result)

    def test_standalone_paragraph_with_context(self):
        """K-IFRS 언급 후 '문단 36' 단독 — 가장 가까운 기준서에 귀속."""
        from eval.evaluate_agent import extract_paragraph_citations

        text = (
            "K-IFRS 1037에 따르면 충당부채의 측정은 다음과 같습니다.\n"
            "> **문단 36**: 최선의 추정치로 측정한다.\n"
            "> **문단 37**: 위험과 불확실성을 고려한다."
        )
        result = extract_paragraph_citations(text)
        assert ("K-IFRS 1037", "36") in result
        assert ("K-IFRS 1037", "37") in result


class TestRunAgentEvaluation:
    """agent.invoke 기반 E2E 평가."""

    def test_returns_result_dict_shape(self):
        """반환 dict가 필수 키를 가진다."""
        from eval.evaluate_agent import run_agent_evaluation

        item = {
            "id": "q001",
            "query": "충당부채 인식 조건은?",
            "expected_standard": "K-IFRS 1037",
            "expected_paragraphs": ["14", "15", "16"],
            "category": "인식",
            "difficulty": "easy",
        }
        result = run_agent_evaluation(item)
        assert isinstance(result, dict)
        required = {
            "id", "query", "expected_standard", "expected_paragraphs",
            "answer_text", "cited_paragraphs", "latency_sec",
        }
        assert required <= set(result.keys()), (
            f"누락된 키: {required - set(result.keys())}"
        )

    def test_answer_text_is_nonempty_string(self):
        from eval.evaluate_agent import run_agent_evaluation

        item = {
            "id": "q001",
            "query": "충당부채 인식 조건은?",
            "expected_standard": "K-IFRS 1037",
            "expected_paragraphs": ["14"],
            "category": "인식",
            "difficulty": "easy",
        }
        result = run_agent_evaluation(item)
        assert isinstance(result["answer_text"], str)
        assert len(result["answer_text"]) > 50, "답변이 너무 짧음"

    def test_cites_expected_standard_for_easy_query(self):
        """쉬운 질문은 expected_standard를 인용해야 한다 (smoke)."""
        from eval.evaluate_agent import run_agent_evaluation

        item = {
            "id": "q001",
            "query": "충당부채 인식 조건은?",
            "expected_standard": "K-IFRS 1037",
            "expected_paragraphs": ["14", "15", "16"],
            "category": "인식",
            "difficulty": "easy",
        }
        result = run_agent_evaluation(item)
        cited_sids = {sid for sid, _ in result["cited_paragraphs"]}
        assert "K-IFRS 1037" in cited_sids, (
            f"기대 기준서 K-IFRS 1037 미인용. cited={cited_sids}"
        )


class TestRunAdhocQuery:
    """문자열 질의를 직접 받는 ad-hoc 평가 함수."""

    def test_returns_result_dict_shape(self):
        from eval.evaluate_agent import run_adhoc_query

        result = run_adhoc_query("충당부채 인식 조건은?")
        assert isinstance(result, dict)
        required = {"query", "answer_text", "cited_paragraphs", "latency_sec"}
        assert required <= set(result.keys()), (
            f"누락된 키: {required - set(result.keys())}"
        )

    def test_answer_text_is_nonempty(self):
        from eval.evaluate_agent import run_adhoc_query

        result = run_adhoc_query("리스 이용자의 최초 인식 회계처리는?")
        assert isinstance(result["answer_text"], str)
        assert len(result["answer_text"]) > 50, "답변이 너무 짧음"

    def test_cited_paragraphs_are_tuples(self):
        from eval.evaluate_agent import run_adhoc_query

        result = run_adhoc_query("충당부채 인식 조건은?")
        for item in result["cited_paragraphs"]:
            assert isinstance(item, tuple) and len(item) == 2
