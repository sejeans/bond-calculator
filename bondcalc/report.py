"""Reproducible JSON reports and independent observed-price comparisons."""

import json
from datetime import date
from pathlib import Path

from .core import Bond, ZeroCurve, analytics, key_rate_risk, scenarios, solve_ytm, finite

ROOT = Path(__file__).resolve().parents[1]


def load_case(path=None):
    data = json.loads(Path(path or ROOT / "data" / "ktb_example.json").read_text(encoding="utf-8-sig"))
    return data["input"] if "input" in data and "analytics" in data else data


def parse_bond(case):
    fields = dict(case["bond"])
    fields["issue"] = date.fromisoformat(fields["issue"])
    fields["maturity"] = date.fromisoformat(fields["maturity"])
    return Bond(**fields), date.fromisoformat(case["settlement"])


def market_comparison(bond, settlement, result, observation):
    if observation is None:
        return {"status": "pending", "reason": "독립적인 시장가격·동일 시점 YTM 쌍이 아직 입력되지 않았습니다."}
    required = ("price", "price_kind", "quote_face", "settlement", "observed_at", "source_url", "instrument_name", "ytm")
    if any(key not in observation or observation[key] in (None, "") for key in required):
        raise ValueError("시장 비교에는 가격, 종류, 액면기준, 결제일, 관측시각, 출처, 종목명, 동일 시점 YTM이 필요합니다.")
    if observation["settlement"] != settlement.isoformat() or observation["instrument_name"] != bond.name:
        raise ValueError("시장자료의 종목명·결제일이 계산 조건과 다릅니다.")
    kind = observation["price_kind"]
    if kind not in ("clean", "dirty"):
        raise ValueError("시장가격 종류는 clean 또는 dirty여야 합니다.")
    quote_face = finite(observation["quote_face"], "시장 액면기준")
    observed_price = finite(observation["price"], "시장가격")
    if quote_face <= 0 or observed_price <= 0:
        raise ValueError("시장가격과 액면기준은 양수여야 합니다.")
    quoted_yield = finite(observation["ytm"], "관측 YTM")
    if abs(quoted_yield - result["ytm"]) > 1e-12:
        raise ValueError("시장자료의 YTM과 입력 YTM이 다릅니다. 관측가격에서 역산한 YTM을 비교 기준으로 쓰지 마세요.")
    market = observed_price * bond.face / quote_face
    model = result[f"{kind}_price"]
    gap = model - market
    implied = solve_ytm(bond, settlement, market, kind=kind, convention=result["convention"])
    return {"status": "compared", "observation": observation, "model_price": model,
            "observed_price_scaled": market, "price_difference": gap,
            "price_difference_pct": gap / market * 100, "implied_ytm": implied,
            "yield_difference_bp": (implied - quoted_yield) * 10000,
            "note": "괴리 측정 결과입니다. 일치 판정은 호가단위·반올림·결제 관행 확인 후 수행하세요."}


def build_report(case):
    bond, settlement = parse_bond(case)
    result = analytics(bond, settlement, case["ytm"], convention=case.get("convention", "compound"))
    curve = ZeroCurve(tuple(case["curve"]["tenors"]), tuple(case["curve"]["rates"]))
    return {"input": case, "analytics": result,
            "scenarios": scenarios(bond, settlement, case["ytm"], convention=result["convention"]),
            "key_rate_risk": key_rate_risk(bond, settlement, curve),
            "market_comparison": market_comparison(bond, settlement, result, case.get("market_observation"))}


def save_report(report, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def text_summary(report):
    r = report["analytics"]
    k = report["key_rate_risk"]
    s = report["market_comparison"]
    return (f"{report['input']['bond']['name']} | 결제일 {report['input']['settlement']}\n"
            f"계산 기준: {r['convention']} | YTM {r['ytm'] * 100:.6f}%\n"
            f"Dirty {r['dirty_price']:,.6f} | Clean {r['clean_price']:,.6f} | 경과이자 {r['accrued_interest']:,.6f}\n"
            f"Macaulay {r['macaulay_duration']:.6f}년 | Modified {r['modified_duration']:.6f} | Convexity {r['convexity']:.6f}\n"
            f"DV01 {r['dv01']:,.6f}원 / 입력 액면금액\n"
            f"제로커브 KRD 합 {k['krd_sum']:.6f} | 평행이동 민감도 {k['parallel_duration']:.6f}\n"
            f"시장가격 검증: {'대기 — 독립적인 관측가격 미확보' if s['status'] == 'pending' else '비교 결과 생성 (합격 판정 아님)'}")
