"""Fixed-rate bullet bonds; rates are decimals, prices are currency amounts.

No finance/numerical dependencies. Regular coupon schedules only, no ex-coupon
period or business-day adjustment. See README for precise pricing conventions.
"""

from bisect import bisect_right
from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date
from math import exp, fsum, isfinite, log1p, log


def finite(value: float, label: str) -> float:
    if not isfinite(value):
        raise ValueError(f"{label}: 유한한 숫자를 입력하세요.")
    return value


def shift_months(anchor: date, months: int, end_of_month: bool = False) -> date:
    """Always shift from the original anchor, preventing February date drift."""
    index = anchor.year * 12 + anchor.month - 1 + months
    year, month0 = divmod(index, 12)
    month = month0 + 1
    last = monthrange(year, month)[1]
    return date(year, month, last if end_of_month else min(anchor.day, last))


@dataclass(frozen=True)
class Bond:
    issue: date
    maturity: date
    coupon_rate: float
    face: float = 10000.0
    frequency: int = 2
    end_of_month: bool = False
    name: str = "고정금리 이표채"

    def __post_init__(self):
        if not isinstance(self.issue, date) or not isinstance(self.maturity, date):
            raise ValueError("발행일과 만기일은 date 형식이어야 합니다.")
        if self.issue >= self.maturity:
            raise ValueError("만기일은 발행일 이후여야 합니다.")
        if type(self.frequency) is not int or self.frequency not in (1, 2, 4, 12):
            raise ValueError("이자 지급 횟수는 연 1, 2, 4, 12회 중 하나입니다.")
        if finite(self.face, "액면금액") <= 0 or finite(self.coupon_rate, "표면금리") < 0:
            raise ValueError("액면금액은 양수, 표면금리는 0 이상이어야 합니다.")
        if (self.maturity - self.issue).days > 366 * 100:
            raise ValueError("지원 만기는 최대 100년입니다.")
        # Reject irregular first periods rather than silently inventing coupons.
        dates = self.schedule()
        previous = shift_months(self.maturity, -len(dates) * (12 // self.frequency), self.end_of_month)
        if previous != self.issue:
            raise ValueError("발행일은 만기일에서 역산한 정규 이자주기에 맞아야 합니다. 단기·장기 첫 이표는 미지원입니다.")

    def schedule(self) -> tuple[date, ...]:
        dates = []
        k = 0
        while True:
            payment = shift_months(self.maturity, -k * (12 // self.frequency), self.end_of_month)
            if payment <= self.issue:
                return tuple(reversed(dates))
            dates.append(payment)
            k += 1


@dataclass(frozen=True)
class CashFlow:
    payment_date: date
    coupon: float
    principal: float
    amount: float
    periods: float
    years: float


def cashflows(bond: Bond, settlement: date) -> tuple[tuple[CashFlow, ...], float, float]:
    if not bond.issue <= settlement < bond.maturity:
        raise ValueError("결제일은 발행일 이상, 만기일 미만이어야 합니다. 선매출은 미지원입니다.")
    dates = bond.schedule()
    remaining = tuple(d for d in dates if d > settlement)
    previous = max((d for d in (bond.issue,) + dates if d <= settlement))
    following = remaining[0]
    fraction = (following - settlement).days / (following - previous).days
    coupon = bond.face * bond.coupon_rate / bond.frequency
    accrued = coupon * (settlement - previous).days / (following - previous).days
    flows = tuple(CashFlow(d, coupon, bond.face if d == bond.maturity else 0.0,
                           coupon + (bond.face if d == bond.maturity else 0.0),
                           k + fraction, (k + fraction) / bond.frequency)
                  for k, d in enumerate(remaining))
    return flows, accrued, fraction


def _discount(rate: float, frequency: int, k: int, fraction: float, convention: str):
    finite(rate, "금리")
    if rate <= -frequency:
        raise ValueError(f"금리는 {-frequency * 100}%보다 커야 합니다.")
    q = 1 + rate / frequency
    if convention == "compound":
        n = k + fraction
        exponent = -n * log1p(rate / frequency)
        a = n / (frequency * q)
        b = n / (frequency * q) ** 2
    elif convention == "ktb_simple":
        s = 1 + rate / frequency * fraction
        exponent = -k * log1p(rate / frequency) - log(s)
        a = k / (frequency * q) + fraction / (frequency * s)
        b = k / (frequency * q) ** 2 + (fraction / (frequency * s)) ** 2
    else:
        raise ValueError("계산 기준은 compound 또는 ktb_simple입니다.")
    return exponent, a, b


def price(bond: Bond, settlement: date, ytm: float, *, kind: str = "dirty", convention: str = "compound") -> float:
    """Dirty = PV of future cashflows. Clean = dirty - accrued interest."""
    if kind not in ("clean", "dirty"):
        raise ValueError("가격 종류는 clean 또는 dirty입니다.")
    flows, accrued, fraction = cashflows(bond, settlement)
    terms = []
    for k, flow in enumerate(flows):
        if flow.amount == 0:
            continue
        exponent, _, _ = _discount(ytm, bond.frequency, k, fraction, convention)
        log_pv = log(flow.amount) + exponent
        terms.append(exp(log_pv) if log_pv < 709 else float("inf"))
    result = fsum(terms)
    return result - accrued if kind == "clean" else result


def solve_ytm(bond: Bond, settlement: date, target_price: float, *, kind: str = "clean", convention: str = "compound") -> float:
    """Bisection with an expanding bracket, including negative yields."""
    finite(target_price, "시장가격")
    if kind not in ("clean", "dirty"):
        raise ValueError("가격 종류는 clean 또는 dirty입니다.")
    _, accrued, _ = cashflows(bond, settlement)
    dirty = target_price + accrued if kind == "clean" else target_price
    if dirty <= 0:
        raise ValueError("경과이자를 포함한 가격은 0보다 커야 합니다.")
    lower, upper = -bond.frequency + 1e-10, 0.1
    if price(bond, settlement, lower, convention=convention) < dirty:
        raise ValueError("입력 가격의 YTM이 수치해석 지원 범위를 벗어납니다.")
    while price(bond, settlement, upper, convention=convention) > dirty:
        upper = upper * 2 + 0.1
        if upper > 1e12:
            raise ValueError("입력 가격의 YTM이 수치해석 지원 범위를 벗어납니다.")
    for _ in range(220):
        middle = (lower + upper) / 2
        calculated = price(bond, settlement, middle, convention=convention)
        if abs(calculated - dirty) <= max(1e-10, dirty * 1e-12):
            return middle
        if calculated > dirty:
            lower = middle
        else:
            upper = middle
    raise ValueError("YTM 수렴 실패: 입력가격과 결제일을 확인하세요.")


def analytics(bond: Bond, settlement: date, ytm: float, *, convention: str = "compound") -> dict:
    flows, accrued, fraction = cashflows(bond, settlement)
    rows = []
    for k, flow in enumerate(flows):
        exponent, a, b = _discount(ytm, bond.frequency, k, fraction, convention)
        pv = flow.amount * exp(exponent)
        rows.append({"payment_date": flow.payment_date.isoformat(), "coupon": flow.coupon,
                     "principal": flow.principal, "amount": flow.amount, "years": flow.years,
                     "discount_factor": exp(exponent), "present_value": pv,
                     "duration_amount": pv * a, "convexity_amount": pv * (a * a + b)})
    dirty = fsum(row["present_value"] for row in rows)
    if not isfinite(dirty) or dirty <= 0:
        raise ValueError("계산가격이 지원 범위를 벗어납니다.")
    modified = fsum(row["duration_amount"] for row in rows) / dirty
    macaulay = fsum(row["years"] * row["present_value"] for row in rows) / dirty
    convexity = fsum(row["convexity_amount"] for row in rows) / dirty
    for row in rows:
        row["pv_weight"] = row["present_value"] / dirty
    return {"ytm": ytm, "convention": convention, "dirty_price": dirty,
            "clean_price": dirty - accrued, "accrued_interest": accrued,
            "macaulay_duration": macaulay, "modified_duration": modified,
            "convexity": convexity, "dv01": modified * dirty * 0.0001,
            "cashflows": rows}


def scenarios(bond: Bond, settlement: date, ytm: float, shocks_bp=(-100, -50, -25, -1, 0, 1, 25, 50, 100), *, convention="compound") -> list[dict]:
    base = analytics(bond, settlement, ytm, convention=convention)
    p = base["dirty_price"]
    rows = []
    for bp in shocks_bp:
        dy = finite(bp, "금리 충격") / 10000
        actual = price(bond, settlement, ytm + dy, convention=convention)
        linear = p * (1 - base["modified_duration"] * dy)
        quadratic = linear + p * 0.5 * base["convexity"] * dy * dy
        rows.append({"shock_bp": bp, "ytm": ytm + dy, "dirty_price": actual,
                     "change_amount": actual - p, "change_pct": (actual / p - 1) * 100,
                     "duration_price": linear, "convexity_price": quadratic,
                     "linear_error": linear - actual, "quadratic_error": quadratic - actual})
    return rows


@dataclass(frozen=True)
class ZeroCurve:
    """Nominal zero rates with bond-frequency compounding; linear interpolation.

    End nodes extend flat. These are zero rates, NOT benchmark bond YTMs.
    """
    tenors: tuple[float, ...]
    rates: tuple[float, ...]

    def __post_init__(self):
        object.__setattr__(self, "tenors", tuple(self.tenors))
        object.__setattr__(self, "rates", tuple(self.rates))
        if len(self.tenors) != len(self.rates) or len(self.tenors) < 2:
            raise ValueError("제로금리는 최소 2개이며 만기와 금리의 개수가 같아야 합니다.")
        if any(finite(t, "커브 만기") <= 0 for t in self.tenors):
            raise ValueError("커브 만기는 양수여야 합니다.")
        if any(b <= a for a, b in zip(self.tenors, self.tenors[1:])):
            raise ValueError("커브 만기는 중복 없이 오름차순이어야 합니다.")
        for r in self.rates:
            finite(r, "제로금리")

    def rate(self, years: float) -> float:
        finite(years, "할인기간")
        if years < 0:
            raise ValueError("할인기간은 0 이상이어야 합니다.")
        if years <= self.tenors[0]:
            return self.rates[0]
        if years >= self.tenors[-1]:
            return self.rates[-1]
        i = bisect_right(self.tenors, years) - 1
        w = (years - self.tenors[i]) / (self.tenors[i + 1] - self.tenors[i])
        return self.rates[i] * (1 - w) + self.rates[i + 1] * w

    def bumped(self, node: int | None, shift: float) -> "ZeroCurve":
        finite(shift, "커브 충격")
        if node is not None and (type(node) is not int or not 0 <= node < len(self.rates)):
            raise ValueError("커브 노드 번호가 범위를 벗어났습니다.")
        return replace(self, rates=tuple(r + (shift if node is None or i == node else 0)
                                          for i, r in enumerate(self.rates)))


def curve_price(bond: Bond, settlement: date, curve: ZeroCurve) -> float:
    flows, _, fraction = cashflows(bond, settlement)
    if any(r <= -bond.frequency for r in curve.rates):
        raise ValueError("제로금리가 할인 가능 범위를 벗어납니다.")
    return fsum(flow.amount * exp(_discount(curve.rate(flow.years), bond.frequency, k,
                                            fraction, "compound")[0])
                for k, flow in enumerate(flows))


def key_rate_risk(bond: Bond, settlement: date, curve: ZeroCurve, bump_bp: float = 1.0) -> dict:
    if finite(bump_bp, "키레이트 충격") <= 0:
        raise ValueError("키레이트 충격은 0보다 커야 합니다.")
    h = bump_bp / 10000
    p = curve_price(bond, settlement, curve)
    if not isfinite(p) or p <= 0:
        raise ValueError("커브 가격이 지원 범위를 벗어납니다.")
    rows = []
    for i, (tenor, rate) in enumerate(zip(curve.tenors, curve.rates)):
        down = curve_price(bond, settlement, curve.bumped(i, -h))
        up = curve_price(bond, settlement, curve.bumped(i, h))
        krd = (down - up) / (2 * h * p)
        rows.append({"tenor": tenor, "zero_rate": rate, "key_rate_duration": krd,
                     "key_rate_dv01": krd * p * 0.0001, "down_price": down, "up_price": up})
    parallel = (curve_price(bond, settlement, curve.bumped(None, -h)) -
                curve_price(bond, settlement, curve.bumped(None, h))) / (2 * h * p)
    total = fsum(row["key_rate_duration"] for row in rows)
    return {"curve_dirty_price": p, "bump_bp": bump_bp, "parallel_duration": parallel,
            "krd_sum": total, "sum_minus_parallel": total - parallel, "nodes": rows}
