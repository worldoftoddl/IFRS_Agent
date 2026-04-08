"""K-IFRS 재무 계산 도구 — 현재가치, 유효이자율, 상각표.

LLM이 자체적으로 할 수 없는 정확한 수치 계산을 제공한다.
모든 도구는 마크다운 테이블을 반환하여 챗봇 UI에서 깔끔하게 렌더링된다.
"""

from langchain_core.tools import tool


def _fmt(n: float) -> str:
    """숫자를 천 단위 콤마 형식으로 포맷팅."""
    if n == int(n):
        return f"{int(n):,}"
    return f"{n:,.2f}"


@tool
def calculate_present_value(
    cash_flows: list[float],
    discount_rate: float,
    periods: list[int] | None = None,
) -> str:
    """현금흐름의 현재가치를 계산합니다.

    충당부채(K-IFRS 1037), 리스부채(K-IFRS 1116), 금융상품(K-IFRS 1109) 측정에 활용.

    Args:
        cash_flows: 각 기간의 현금흐름 금액 리스트
        discount_rate: 할인율 (예: 0.10 = 10%)
        periods: 각 현금흐름의 기간 (미지정 시 1, 2, 3, ... 순차)
    """
    if not cash_flows:
        return "**오류**: 현금흐름이 비어 있습니다."
    if discount_rate < 0:
        return "**오류**: 할인율은 0 이상이어야 합니다."

    if periods is None:
        periods = list(range(1, len(cash_flows) + 1))

    if len(periods) != len(cash_flows):
        return "**오류**: cash_flows와 periods의 길이가 다릅니다."

    rows: list[str] = []
    total_pv = 0.0

    for cf, t in zip(cash_flows, periods, strict=True):
        if discount_rate == 0:
            pv = cf
        else:
            pv = cf / (1 + discount_rate) ** t
        total_pv += pv
        rows.append(f"| {t} | {_fmt(cf)} | {_fmt(pv)} |")

    header = (
        f"**현재가치 계산** (할인율: {discount_rate * 100:.2f}%)\n\n"
        "| 기간 | 현금흐름 | 현재가치 |\n"
        "|------|---------|--------|\n"
    )
    footer = f"\n| **합계** | **{_fmt(sum(cash_flows))}** | **{_fmt(total_pv)}** |"

    return header + "\n".join(rows) + footer


@tool
def calculate_effective_interest_rate(
    initial_amount: float,
    periodic_payments: list[float],
    final_payment: float,
    num_periods: int,
) -> str:
    """유효이자율(EIR)을 Newton-Raphson 방법으로 계산합니다.

    금융자산/부채의 상각후원가 측정(K-IFRS 1109)에 활용.

    Args:
        initial_amount: 최초 인식 금액 (발행가/취득원가)
        periodic_payments: 각 기간의 이자 지급액 리스트
        final_payment: 만기 시 원금 상환액
        num_periods: 총 기간 수
    """
    if initial_amount <= 0:
        return "**오류**: 최초 인식 금액은 양수여야 합니다."
    if num_periods <= 0:
        return "**오류**: 기간 수는 양수여야 합니다."

    # 기간별 현금흐름 구성
    cfs = list(periodic_payments[:num_periods])
    while len(cfs) < num_periods:
        cfs.append(0.0)
    cfs[-1] += final_payment  # 마지막 기간에 원금 상환 추가

    # NPV(r) = -initial_amount + sum(cf_t / (1+r)^t)
    def npv(r: float) -> float:
        return -initial_amount + sum(cf / (1 + r) ** t for t, cf in enumerate(cfs, 1))

    # NPV'(r) = sum(-t * cf_t / (1+r)^(t+1))
    def npv_deriv(r: float) -> float:
        return sum(-t * cf / (1 + r) ** (t + 1) for t, cf in enumerate(cfs, 1))

    # Newton-Raphson
    r = 0.05  # 초기 추정값
    for _ in range(200):
        f_val = npv(r)
        f_deriv = npv_deriv(r)
        if abs(f_deriv) < 1e-15:
            return "**오류**: 유효이자율을 계산할 수 없습니다 (수렴 실패)."
        r_new = r - f_val / f_deriv
        if abs(r_new - r) < 1e-10:
            r = r_new
            break
        r = r_new
    else:
        return "**오류**: 유효이자율을 계산할 수 없습니다 (수렴 실패)."

    if r < -1 or r > 10:
        return "**오류**: 유효이자율을 계산할 수 없습니다 (비정상 범위)."

    # 검증: NPV가 0에 근접하는지
    verification = npv(r)

    return (
        f"**유효이자율(EIR) 계산 결과**\n\n"
        f"- 최초 인식 금액: {_fmt(initial_amount)}\n"
        f"- 기간별 이자: {_fmt(periodic_payments[0]) if periodic_payments else '0'}\n"
        f"- 만기 상환액: {_fmt(final_payment)}\n"
        f"- 기간: {num_periods}기\n\n"
        f"**유효이자율: {r * 100:.4f}%**\n\n"
        f"검증 (NPV ≈ 0): {_fmt(verification)}"
    )


@tool
def build_amortization_schedule(
    principal: float,
    rate: float,
    payments: list[float] | None = None,
    num_periods: int = 0,
) -> str:
    """상각표를 생성합니다.

    리스부채(K-IFRS 1116), 사채(K-IFRS 1109) 등의 이자비용·장부금액 변동 추적에 활용.

    Args:
        principal: 최초 원금 (장부금액)
        rate: 이자율 (유효이자율, 예: 0.05 = 5%)
        payments: 각 기간의 납부액 리스트 (미지정 시 균등상환)
        num_periods: 총 기간 수 (payments 미지정 시 필수)
    """
    if principal <= 0:
        return "**오류**: 원금은 양수여야 합니다."
    if rate < 0:
        return "**오류**: 이자율은 0 이상이어야 합니다."

    if payments is not None:
        num_periods = len(payments)
    elif num_periods <= 0:
        return "**오류**: 기간 수를 지정하거나 payments를 제공해야 합니다."

    # 균등상환 납부액 계산
    if payments is None:
        if rate == 0:
            pmt = principal / num_periods
        else:
            pmt = principal * rate * (1 + rate) ** num_periods / (
                (1 + rate) ** num_periods - 1
            )
        payments = [pmt] * num_periods

    # 상각표 생성
    balance = principal
    rows: list[str] = []
    total_interest = 0.0
    total_principal_repaid = 0.0

    for i, payment in enumerate(payments, 1):
        interest = balance * rate
        principal_repaid = payment - interest
        balance = balance - principal_repaid
        total_interest += interest
        total_principal_repaid += principal_repaid

        # 마지막 기간 잔액 보정
        if i == len(payments):
            balance = max(balance, 0)
            if abs(balance) < 0.01:
                balance = 0

        rows.append(
            f"| {i} | {_fmt(payment)} | {_fmt(interest)} "
            f"| {_fmt(principal_repaid)} | {_fmt(balance)} |"
        )

    header = (
        f"**상각표** (원금: {_fmt(principal)}, 이자율: {rate * 100:.2f}%)\n\n"
        "| 기간 | 납부액 | 이자비용 | 원금상환 | 잔액 |\n"
        "|------|-------|---------|---------|------|\n"
    )
    footer = (
        f"\n| **합계** | **{_fmt(sum(payments))}** | **{_fmt(total_interest)}** "
        f"| **{_fmt(total_principal_repaid)}** | - |"
    )

    return header + "\n".join(rows) + footer
