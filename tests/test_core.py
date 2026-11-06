from datetime import date, timedelta
from decimal import Decimal, localcontext
import math
import random
import unittest

from bondcalc.core import (Bond, ZeroCurve, analytics, cashflows, curve_price,
                           key_rate_risk, price, scenarios, shift_months, solve_ytm)
from bondcalc.report import build_report, load_case, market_comparison, parse_bond


class BondTests(unittest.TestCase):
    def setUp(self):
        self.bond = Bond(date(2025, 6, 10), date(2028, 6, 10), .0225)
        self.settlement = date(2025, 10, 14)

    def test_independent_two_payment_reference(self):
        b = Bond(date(2024, 1, 1), date(2026, 1, 1), .05, face=100, frequency=1)
        r = analytics(b, b.issue, .1)
        # Independent closed form: 5/1.1 + 105/1.1^2.
        expected = 91.32231404958678
        self.assertAlmostEqual(r["dirty_price"], expected, places=11)
        self.assertAlmostEqual(r["macaulay_duration"], (5 / 1.1 + 2 * 105 / 1.1**2) / expected)
        self.assertAlmostEqual(r["modified_duration"], r["macaulay_duration"] / 1.1)
        self.assertAlmostEqual(r["convexity"], (2 * 5 / 1.1**3 + 6 * 105 / 1.1**4) / expected)

    def test_par_on_coupon_date(self):
        for mode in ("compound", "ktb_simple"):
            self.assertAlmostEqual(price(self.bond, self.bond.issue, .0225, convention=mode), 10000, places=8)

    def test_independent_ktb_decimal_reference(self):
        # Dates and six amounts are specified independently of schedule().
        with localcontext() as ctx:
            ctx.prec = 50
            q = 1 + Decimal("0.02565") / 2
            f = Decimal(57) / Decimal(183)  # Oct 14 -> Dec 10 / Jun 10 -> Dec 10
            total = sum(Decimal("112.5") / q**k for k in range(6)) + Decimal(10000) / q**5
            expected = float(total / (1 + Decimal("0.02565") / 2 * f))
        self.assertAlmostEqual(price(self.bond, self.settlement, .02565, convention="ktb_simple"), expected, places=8)

    def test_accrued_interest(self):
        flows, accrued, f = cashflows(self.bond, self.settlement)
        self.assertEqual(len(flows), 6)
        self.assertAlmostEqual(accrued, 112.5 * 126 / 183)
        self.assertAlmostEqual(f, 57 / 183)
        self.assertEqual(flows[-1].amount, 10112.5)
        self.assertAlmostEqual(sum(flow.principal for flow in flows), 10000)

    def test_clean_dirty_identity(self):
        r = analytics(self.bond, self.settlement, .03)
        self.assertAlmostEqual(r["dirty_price"], r["clean_price"] + r["accrued_interest"])
        self.assertAlmostEqual(sum(c["pv_weight"] for c in r["cashflows"]), 1)

    def test_coupon_boundary_excludes_paid_coupon(self):
        on = date(2025, 12, 10)
        before = on - timedelta(days=1)
        after = on + timedelta(days=1)
        self.assertEqual(len(cashflows(self.bond, before)[0]), 6)
        self.assertEqual(len(cashflows(self.bond, on)[0]), 5)
        self.assertEqual(cashflows(self.bond, on)[1], 0)
        self.assertGreater(cashflows(self.bond, after)[1], 0)

    def test_near_maturity(self):
        d = self.bond.maturity - timedelta(days=1)
        for mode in ("compound", "ktb_simple"):
            r = analytics(self.bond, d, .025, convention=mode)
            self.assertEqual(len(r["cashflows"]), 1)
            self.assertLess(abs(r["dirty_price"] - 10112.5), 1)
            self.assertGreater(r["modified_duration"], 0)

    def test_zero_coupon_duration(self):
        b = Bond(date(2024, 1, 1), date(2029, 1, 1), 0, face=100)
        r = analytics(b, b.issue, .04)
        self.assertAlmostEqual(r["dirty_price"], 100 / 1.02**10)
        self.assertAlmostEqual(r["macaulay_duration"], 5)
        self.assertAlmostEqual(r["modified_duration"], 5 / 1.02)
        self.assertAlmostEqual(r["convexity"], 5 * 5.5 / 1.02**2)

    def test_zero_and_negative_yields(self):
        for rate in (0, -.005, -.1):
            for mode in ("compound", "ktb_simple"):
                p = price(self.bond, self.settlement, rate, kind="clean", convention=mode)
                self.assertAlmostEqual(solve_ytm(self.bond, self.settlement, p, convention=mode), rate, places=10)

    def test_randomized_ytm_roundtrips(self):
        rng = random.Random(492)
        for _ in range(40):
            rate = rng.uniform(-.05, .3)
            settlement = self.bond.issue + timedelta(days=rng.randrange(1, 1050))
            for mode in ("compound", "ktb_simple"):
                for kind in ("clean", "dirty"):
                    p = price(self.bond, settlement, rate, kind=kind, convention=mode)
                    self.assertAlmostEqual(solve_ytm(self.bond, settlement, p, kind=kind, convention=mode), rate, places=8)

    def test_analytic_risk_against_finite_differences(self):
        h = 1e-5
        for mode in ("compound", "ktb_simple"):
            for settlement in (self.bond.issue, self.settlement, self.bond.maturity - timedelta(days=1)):
                r = analytics(self.bond, settlement, .03, convention=mode)
                p = r["dirty_price"]
                up = price(self.bond, settlement, .03 + h, convention=mode)
                down = price(self.bond, settlement, .03 - h, convention=mode)
                self.assertAlmostEqual(r["modified_duration"], (down - up) / (2 * h * p), delta=1e-7)
                self.assertAlmostEqual(r["convexity"], (up + down - 2 * p) / (h * h * p), delta=1e-4)

    def test_convexity_improves_approximation(self):
        for mode in ("compound", "ktb_simple"):
            for row in scenarios(self.bond, self.settlement, .03, (-100, -50, 50, 100), convention=mode):
                self.assertLess(abs(row["quadratic_error"]), abs(row["linear_error"]))

    def test_monotonic_price_and_dv01_scaling(self):
        self.assertGreater(price(self.bond, self.settlement, .02), price(self.bond, self.settlement, .03))
        b = Bond(self.bond.issue, self.bond.maturity, .0225, face=100000000)
        small = analytics(self.bond, self.settlement, .03)
        large = analytics(b, self.settlement, .03)
        self.assertAlmostEqual(large["dv01"], small["dv01"] * 10000, places=6)
        self.assertAlmostEqual(large["modified_duration"], small["modified_duration"])

    def test_end_of_month_and_leap_year(self):
        b = Bond(date(2024, 2, 29), date(2026, 2, 28), .04, end_of_month=True)
        self.assertEqual(b.schedule(), (date(2024, 8, 31), date(2025, 2, 28), date(2025, 8, 31), date(2026, 2, 28)))
        self.assertAlmostEqual(price(b, b.issue, .04), 10000, places=8)
        self.assertEqual(shift_months(date(2024, 8, 30), -12), date(2023, 8, 30))

    def test_invalid_dates_and_stubs(self):
        for s in (self.bond.issue - timedelta(days=1), self.bond.maturity, date(2030, 1, 1)):
            with self.assertRaises(ValueError):
                price(self.bond, s, .03)
        with self.assertRaises(ValueError):
            Bond(date(2025, 6, 11), date(2028, 6, 10), .03)

    def test_invalid_numbers(self):
        for rate in (math.nan, math.inf, -2):
            with self.assertRaises(ValueError):
                price(self.bond, self.settlement, rate)
        for face in (0, -1, math.nan):
            with self.assertRaises(ValueError):
                Bond(self.bond.issue, self.bond.maturity, .03, face=face)
        for freq in (0, 3, 2.0, True):
            with self.assertRaises(ValueError):
                Bond(self.bond.issue, self.bond.maturity, .03, frequency=freq)
        for target in (0, -100, math.nan):
            with self.assertRaises(ValueError):
                solve_ytm(self.bond, self.settlement, target, kind="dirty")
        with self.assertRaises(ValueError):
            price(self.bond, self.settlement, .03, kind="unknown")


class CurveTests(unittest.TestCase):
    def setUp(self):
        self.bond = Bond(date(2025, 6, 10), date(2035, 6, 10), .035)
        self.s = date(2025, 10, 14)
        self.curve = ZeroCurve((.5, 1, 2, 3, 5, 10, 20, 30), (.03,) * 8)

    def test_flat_curve_matches_compound_ytm(self):
        self.assertAlmostEqual(curve_price(self.bond, self.s, self.curve), price(self.bond, self.s, .03), places=8)
        risk = key_rate_risk(self.bond, self.s, self.curve)
        self.assertAlmostEqual(risk["krd_sum"], analytics(self.bond, self.s, .03)["modified_duration"], delta=2e-6)

    def test_nonflat_krd_sum_matches_parallel(self):
        curve = ZeroCurve(self.curve.tenors, (.02, .023, .026, .03, .032, .035, .039, .04))
        risk = key_rate_risk(self.bond, self.s, curve)
        self.assertAlmostEqual(risk["krd_sum"], risk["parallel_duration"], delta=2e-6)

    def test_single_node_zero_coupon_exposure(self):
        b = Bond(date(2025, 1, 1), date(2030, 1, 1), 0)
        curve = ZeroCurve((1, 3, 5, 10), (.03,) * 4)
        risk = key_rate_risk(b, b.issue, curve)
        for i, row in enumerate(risk["nodes"]):
            if i == 2:
                self.assertAlmostEqual(row["key_rate_duration"], 5 / 1.015, delta=1e-6)
            else:
                self.assertEqual(row["key_rate_duration"], 0)

    def test_interpolation_and_endpoint_extension(self):
        c = ZeroCurve((1, 3), (.02, .04))
        self.assertEqual(c.rate(.1), .02)
        self.assertAlmostEqual(c.rate(2), .03)
        self.assertEqual(c.rate(30), .04)
        self.assertEqual(c.bumped(0, .001).rates, (.021, .04))

    def test_invalid_curve(self):
        for tenors, rates in [((1,), (.03,)), ((1, 1), (.02, .03)), ((2, 1), (.02, .03)),
                              ((0, 1), (.02, .03)), ((1, 2), (.02, math.nan))]:
            with self.assertRaises(ValueError):
                ZeroCurve(tenors, rates)
        for bump in (0, -1, math.nan):
            with self.assertRaises(ValueError):
                key_rate_risk(self.bond, self.s, self.curve, bump)


class ReportTests(unittest.TestCase):
    def test_example_does_not_fabricate_market_validation(self):
        report = build_report(load_case())
        self.assertEqual(report["market_comparison"]["status"], "pending")
        self.assertIsNone(report["input"]["market_observation"])

    def test_observation_normalization_and_mismatch(self):
        case = load_case()
        b, s = parse_bond(case)
        result = analytics(b, s, case["ytm"], convention=case["convention"])
        # Synthetic unit-test observation only, never written as market evidence.
        obs = {"price": 100, "price_kind": "dirty", "quote_face": 100,
               "settlement": s.isoformat(), "observed_at": "synthetic unit test", "source_url": "test://fixture",
               "instrument_name": b.name, "ytm": case["ytm"]}
        cmp = market_comparison(b, s, result, obs)
        self.assertEqual(cmp["observed_price_scaled"], 10000)
        self.assertAlmostEqual(cmp["price_difference"], result["dirty_price"] - 10000)
        for key, value in (("ytm", .05), ("settlement", "2025-10-13"), ("instrument_name", "other"), ("price", math.nan), ("source_url", "")):
            with self.assertRaises(ValueError):
                market_comparison(b, s, result, {**obs, key: value})


if __name__ == "__main__":
    unittest.main()
