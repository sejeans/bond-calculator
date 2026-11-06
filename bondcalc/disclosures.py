"""Coarse cross-check against disclosed transactions, not exact market quotes."""

from datetime import date, timedelta
import json
from .core import Bond, price
from .report import ROOT, save_report


def compare_disclosures():
    data = json.loads((ROOT / "data" / "disclosed_trades.json").read_text(encoding="utf-8"))
    b = dict(data["bond"])
    b["issue"], b["maturity"] = date.fromisoformat(b["issue"]), date.fromisoformat(b["maturity"])
    bond = Bond(**b)
    rows = []
    for trade in data["trades"]:
        trade_day = date.fromisoformat(trade["trade_date"])
        disclosed_price = trade["trade_amount_eok"] / trade["face_amount_eok"] * bond.face
        half_width = .05 / trade["face_amount_eok"] * bond.face
        alternatives = []
        for lag in (0, 1):
            settlement = trade_day + timedelta(days=lag)
            modeled = price(bond, settlement, trade["yield_pct"] / 100, convention="ktb_simple")
            alternatives.append({"assumed_settlement": settlement.isoformat(),
                                 "assumed_calendar_day_lag": lag,
                                 "model_dirty_price": modeled,
                                 "model_minus_disclosed_unit_price": modeled - disclosed_price})
        rows.append({"disclosed_trade": trade, "disclosed_implied_unit_price": disclosed_price,
                     "assumed_rounding_half_width": half_width,
                     "settlement_scenarios": alternatives})
    return {"status": "coarse_comparison_only", "source": data["source"],
            "bond": data["bond"], "limitations": data["limitations"], "comparisons": rows}


def main():
    report = compare_disclosures()
    save_report(report, ROOT / "reports" / "disclosure-comparison.json")
    print("3 disclosed trades compared; settlement and price-kind assumptions apply.")
    for row in report["comparisons"]:
        value = row["disclosed_implied_unit_price"]
        prices = [round(s["model_dirty_price"], 6) for s in row["settlement_scenarios"]]
        print(f"Disclosed unit price={value:.6f}; model [same day, next day]={prices}")


if __name__ == "__main__":
    main()
