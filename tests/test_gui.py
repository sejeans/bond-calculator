"""Hidden-window interaction checks; no user windows or persistent files."""
import tkinter as tk
import unittest

from bondcalc.gui import Calculator


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = Calculator(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        self.root.destroy()

    def test_initial_calculation_and_stale_results(self):
        self.assertIsNotNone(self.app.report)
        self.assertEqual(len(self.app.trees["flows"].get_children()), 6)
        self.assertEqual(len(self.app.trees["krd"].get_children()), 8)
        self.app.vars["ytm"].set("3.1")
        self.assertIsNone(self.app.report)
        self.assertEqual(str(self.app.export["state"]), "disabled")
        self.app.calculate()
        self.assertAlmostEqual(self.app.report["analytics"]["ytm"], .031)

    def test_inverse_yield_never_passes_as_independent_comparison(self):
        self.app.vars["market_price"].set("10000")
        self.app.invert()
        self.assertIsNotNone(self.app.report)
        self.assertTrue(self.app.yield_derived_from_price)
        self.assertEqual(self.app.report["market_comparison"]["status"], "pending")
        self.app.calculate()
        self.assertEqual(self.app.report["market_comparison"]["status"], "pending")
        self.assertTrue(any("역산" in n for n in self.app.report["input"]["notes"]))

    def test_invalid_input_clears_export(self):
        self.app.vars["maturity"].set("2020-01-01")
        self.app.calculate()
        self.assertIsNone(self.app.report)
        self.assertIn("입력 확인", self.app.status.get())


if __name__ == "__main__":
    unittest.main()
