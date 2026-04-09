"""verify_arithmetic 도구 테스트."""

from app.accounting_tools import verify_arithmetic


class TestVerifyArithmetic:
    """산술 검증 도구 기본 동작."""

    def test_simple_addition(self):
        result = verify_arithmetic.invoke({"expression": "750000 + 460000"})
        assert "1,210,000" in result

    def test_subtraction(self):
        result = verify_arithmetic.invoke({"expression": "750000 + 460000 - 1150000"})
        assert "60,000" in result

    def test_multiplication(self):
        result = verify_arithmetic.invoke({"expression": "1150000 * 0.4"})
        assert "460,000" in result

    def test_division(self):
        result = verify_arithmetic.invoke({"expression": "100000 / 4"})
        assert "25,000" in result

    def test_complex_expression(self):
        result = verify_arithmetic.invoke({"expression": "250000 + 2000 - 1000 + 101100"})
        assert "352,100" in result

    def test_parentheses(self):
        expr = "(200000 - 15000 + 3000 - 24000 + 4500) * 0.4"
        result = verify_arithmetic.invoke({"expression": expr})
        assert "67,400" in result

    def test_negative_result(self):
        result = verify_arithmetic.invoke({"expression": "100 - 500"})
        assert "-400" in result

    def test_returns_formatted_string(self):
        result = verify_arithmetic.invoke({"expression": "1 + 1"})
        assert "=" in result
        assert "**" in result


class TestVerifyArithmeticErrors:
    """에러 처리."""

    def test_empty_expression(self):
        result = verify_arithmetic.invoke({"expression": ""})
        assert "오류" in result

    def test_invalid_expression(self):
        result = verify_arithmetic.invoke({"expression": "abc + 123"})
        assert "오류" in result

    def test_division_by_zero(self):
        result = verify_arithmetic.invoke({"expression": "100 / 0"})
        assert "오류" in result

    def test_rejects_function_calls(self):
        """import, exec 등 위험한 호출 차단."""
        result = verify_arithmetic.invoke({"expression": "__import__('os').system('ls')"})
        assert "오류" in result


class TestConsolidationScenario:
    """run 파일에서 발견된 실제 연결재무제표 시나리오 검증."""

    def test_goodwill_calculation(self):
        """영업권 = 이전대가 + 비지배지분 - 순자산 공정가치."""
        result = verify_arithmetic.invoke({"expression": "750000 + 460000 - 1150000"})
        assert "60,000" in result

    def test_nci_at_acquisition(self):
        """비지배지분 = 순자산 × 비지배지분율."""
        result = verify_arithmetic.invoke({"expression": "1150000 * 0.4"})
        assert "460,000" in result

    def test_nci_balance_tracking(self):
        """비지배지분 잔액 = 취득일 + 귀속이익 - 배당."""
        result = verify_arithmetic.invoke(
            {"expression": "460000 + 36000 + 24000 + 67400 - 40000"}
        )
        assert "547,400" in result

    def test_cross_check_mismatch_detectable(self):
        """run에서 발생한 불일치(4,268,500 ≠ 3,578,500) 탐지 가능."""
        result1 = verify_arithmetic.invoke({"expression": "4300000 - 12000 - 19500"})
        result2 = verify_arithmetic.invoke({"expression": "3031100 + 547400"})
        # 두 결과가 다름을 확인할 수 있어야 함
        assert "4,268,500" in result1
        assert "3,578,500" in result2
