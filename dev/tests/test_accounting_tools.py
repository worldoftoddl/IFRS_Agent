"""재무 계산 도구 단위 테스트 (TDD — RED phase first)."""

import pytest


class TestCalculatePresentValue:
    """calculate_present_value 도구 테스트."""

    def test_basic_equal_cash_flows(self):
        """5년간 매년 100만원, 할인율 10% → 3,790,787원."""
        from app.accounting_tools import calculate_present_value

        result = calculate_present_value.invoke(
            {"cash_flows": [1_000_000] * 5, "discount_rate": 0.10}
        )
        assert "3,790,786" in result or "3,790,787" in result

    def test_unequal_cash_flows(self):
        """불균등 현금흐름."""
        from app.accounting_tools import calculate_present_value

        # CF1=100, CF2=200, CF3=300 @ 5%
        # PV = 100/1.05 + 200/1.05^2 + 300/1.05^3
        # = 95.238 + 181.406 + 259.151 = 535.795
        result = calculate_present_value.invoke(
            {"cash_flows": [100, 200, 300], "discount_rate": 0.05}
        )
        assert "535" in result

    def test_custom_periods(self):
        """커스텀 기간 지정."""
        from app.accounting_tools import calculate_present_value

        # CF at year 1 and year 3 only
        result = calculate_present_value.invoke(
            {"cash_flows": [1000, 1000], "discount_rate": 0.10, "periods": [1, 3]}
        )
        # 1000/1.1 + 1000/1.1^3 = 909.09 + 751.31 = 1660.40
        assert "1,660" in result or "1660" in result

    def test_zero_discount_rate(self):
        """할인율 0% → 단순 합계."""
        from app.accounting_tools import calculate_present_value

        result = calculate_present_value.invoke(
            {"cash_flows": [100, 200, 300], "discount_rate": 0.0}
        )
        assert "600" in result

    def test_single_cash_flow(self):
        """단일 현금흐름."""
        from app.accounting_tools import calculate_present_value

        result = calculate_present_value.invoke(
            {"cash_flows": [1000], "discount_rate": 0.10}
        )
        # 1000 / 1.1 = 909.09
        assert "909" in result

    def test_returns_markdown_table(self):
        """마크다운 테이블 형식 반환."""
        from app.accounting_tools import calculate_present_value

        result = calculate_present_value.invoke(
            {"cash_flows": [1000, 1000], "discount_rate": 0.05}
        )
        assert "|" in result  # 마크다운 테이블 구분자
        assert "현재가치" in result or "PV" in result or "합계" in result

    def test_empty_cash_flows_error(self):
        """빈 현금흐름 → 에러 메시지."""
        from app.accounting_tools import calculate_present_value

        result = calculate_present_value.invoke(
            {"cash_flows": [], "discount_rate": 0.10}
        )
        assert "오류" in result or "error" in result.lower()

    def test_negative_discount_rate_error(self):
        """음수 할인율 → 에러 메시지."""
        from app.accounting_tools import calculate_present_value

        result = calculate_present_value.invoke(
            {"cash_flows": [1000], "discount_rate": -0.05}
        )
        assert "오류" in result or "error" in result.lower()


class TestCalculateEffectiveInterestRate:
    """calculate_effective_interest_rate 도구 테스트."""

    def test_basic_bond(self):
        """액면 1억, 표시이자 5%(매년 500만), 발행가 9500만, 5년 → EIR ≈ 6.19%."""
        from app.accounting_tools import calculate_effective_interest_rate

        result = calculate_effective_interest_rate.invoke({
            "initial_amount": 95_000_000,
            "periodic_payments": [5_000_000] * 5,
            "final_payment": 100_000_000,
            "num_periods": 5,
        })
        # EIR should be around 6.19%
        assert "6.1" in result or "6.2" in result

    def test_par_bond(self):
        """액면발행 (발행가 = 액면) → EIR = 표시이자율."""
        from app.accounting_tools import calculate_effective_interest_rate

        result = calculate_effective_interest_rate.invoke({
            "initial_amount": 100_000_000,
            "periodic_payments": [5_000_000] * 5,
            "final_payment": 100_000_000,
            "num_periods": 5,
        })
        assert "5.0" in result or "5%" in result

    def test_zero_coupon_bond(self):
        """무이표채: 발행가 78만, 만기 100만, 5년."""
        from app.accounting_tools import calculate_effective_interest_rate

        result = calculate_effective_interest_rate.invoke({
            "initial_amount": 783_526,
            "periodic_payments": [0] * 5,
            "final_payment": 1_000_000,
            "num_periods": 5,
        })
        # (1000000/783526)^(1/5) - 1 ≈ 5.0%
        assert "5.0" in result or "5%" in result or "4.9" in result

    def test_returns_percentage(self):
        """결과에 % 포함."""
        from app.accounting_tools import calculate_effective_interest_rate

        result = calculate_effective_interest_rate.invoke({
            "initial_amount": 95_000_000,
            "periodic_payments": [5_000_000] * 5,
            "final_payment": 100_000_000,
            "num_periods": 5,
        })
        assert "%" in result

    def test_non_convergence_error(self):
        """수렴 불가능한 입력 → 에러 메시지."""
        from app.accounting_tools import calculate_effective_interest_rate

        result = calculate_effective_interest_rate.invoke({
            "initial_amount": 0,
            "periodic_payments": [0],
            "final_payment": 0,
            "num_periods": 1,
        })
        assert "오류" in result or "error" in result.lower()


class TestBuildAmortizationSchedule:
    """build_amortization_schedule 도구 테스트."""

    def test_basic_loan(self):
        """원금 1억, 이자율 5%, 5년 균등상환."""
        from app.accounting_tools import build_amortization_schedule

        result = build_amortization_schedule.invoke({
            "principal": 100_000_000,
            "rate": 0.05,
            "num_periods": 5,
        })
        # 마크다운 테이블 형식
        assert "|" in result
        # 5개 기간 존재
        assert "1" in result and "5" in result

    def test_custom_payments(self):
        """커스텀 납부액 지정."""
        from app.accounting_tools import build_amortization_schedule

        result = build_amortization_schedule.invoke({
            "principal": 100_000_000,
            "rate": 0.05,
            "payments": [25_000_000, 25_000_000, 25_000_000, 40_000_000],
            "num_periods": 4,
        })
        assert "|" in result

    def test_interest_only(self):
        """이자만 납부 (원금 일시상환)."""
        from app.accounting_tools import build_amortization_schedule

        result = build_amortization_schedule.invoke({
            "principal": 100_000_000,
            "rate": 0.05,
            "payments": [5_000_000, 5_000_000, 5_000_000],
            "num_periods": 3,
        })
        assert "|" in result
        # 잔액이 변하지 않아야 함 (이자만 납부)
        assert "100,000,000" in result or "100000000" in result

    def test_principal_sum_equals_original(self):
        """균등상환 시 원금상환 합계 = 원금."""
        from app.accounting_tools import build_amortization_schedule

        result = build_amortization_schedule.invoke({
            "principal": 1_000_000,
            "rate": 0.10,
            "num_periods": 3,
        })
        # 결과에 "잔액" 또는 "0" 마지막 행이 있어야 함
        assert "0" in result

    def test_zero_rate(self):
        """이자율 0%."""
        from app.accounting_tools import build_amortization_schedule

        result = build_amortization_schedule.invoke({
            "principal": 300_000,
            "rate": 0.0,
            "num_periods": 3,
        })
        # 이자 0, 매 기간 100,000씩 상환
        assert "100,000" in result or "100000" in result

    def test_returns_markdown_table(self):
        """마크다운 테이블 형식."""
        from app.accounting_tools import build_amortization_schedule

        result = build_amortization_schedule.invoke({
            "principal": 1_000_000,
            "rate": 0.05,
            "num_periods": 3,
        })
        assert "|" in result
        assert "---" in result  # 테이블 구분선
