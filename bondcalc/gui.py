"""Standard-library desktop UI. All calculations live in core.py."""

from copy import deepcopy
from datetime import date
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .core import Bond, solve_ytm
from .disclosures import compare_disclosures
from .report import load_case, build_report, save_report, ROOT

BG = "#f3f6fa"
INK = "#14253d"
TEAL = "#087f83"


class Calculator(ttk.Frame):
    def __init__(self, root, input_path=None):
        super().__init__(root, padding=18)
        self.pack(fill="both", expand=True)
        self.root = root
        self.case = load_case(input_path)
        self.report = None
        self.vars = {}
        self.metrics = {}
        self.trees = {}
        self.suspend = True
        self.yield_derived_from_price = False
        self.status = tk.StringVar(value="조건을 입력하고 계산하세요.")
        self._build()
        self.load_fields(self.case)
        self.suspend = False
        self.calculate()

    def _build(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        heading = ttk.Frame(self)
        heading.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        ttk.Label(heading, text="BOND LAB  /  채권 계산기", font=("맑은 고딕", 22, "bold")).pack(side="left")
        ttk.Label(heading, text="현금흐름에서 금리 위험까지", foreground=TEAL).pack(side="right")
        left = ttk.Frame(self, width=290)
        left.grid(row=1, column=0, sticky="ns", padx=(0, 18))
        ttk.Label(left, text="01  채권 조건", font=("맑은 고딕", 12, "bold")).pack(anchor="w", pady=(0, 10))
        for key, label in [("name", "종목명"), ("issue", "발행일  YYYY-MM-DD"),
                           ("maturity", "만기일  YYYY-MM-DD"), ("settlement", "결제일  YYYY-MM-DD"),
                           ("coupon", "표면금리  %"), ("face", "액면금액  원"),
                           ("frequency", "연간 이자 지급 횟수")]:
            self.field(left, key, label, choices=("1", "2", "4", "12") if key == "frequency" else None)
        self.vars["eom"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(left, text="월말 이표일 유지", variable=self.vars["eom"]).pack(anchor="w", pady=5)
        self.vars["eom"].trace_add("write", self.dirty)
        self.field(left, "convention", "할인 기준", choices=("국고채 단리", "교과서 복리"))
        self.field(left, "ytm", "만기수익률 YTM  %")
        ttk.Button(left, text="계산하기", command=self.calculate).pack(fill="x", pady=(12, 5))
        ttk.Button(left, text="입력 파일 열기", command=self.open_case).pack(fill="x", pady=3)
        self.export = ttk.Button(left, text="입력·결과 JSON 저장", command=self.export_report)
        self.export.pack(fill="x", pady=3)
        ttk.Label(left, text="금리 1bp = 0.01%p\n가격·DV01은 입력한 액면금액 기준\n정규 이표채 · 세전 · 휴일 조정 없음",
                  foreground="#607089", justify="left").pack(anchor="w", pady=12)
        book = ttk.Notebook(self)
        book.grid(row=1, column=1, sticky="nsew")
        tabs = {}
        for key, title in [("risk", "가격과 민감도"), ("flows", "현금흐름"),
                           ("curve", "키레이트 듀레이션"), ("market", "시장가격 비교")]:
            tab = ttk.Frame(book, padding=14)
            book.add(tab, text=title)
            tabs[key] = tab
        cards = ttk.Frame(tabs["risk"])
        cards.pack(fill="x")
        for i, (key, label) in enumerate([
            ("dirty_price", "Dirty 가격 / 경과이자 포함"), ("clean_price", "Clean 가격 / 경과이자 제외"),
            ("accrued_interest", "경과이자"), ("macaulay_duration", "Macaulay / 평균 회수기간"),
            ("modified_duration", "Modified / 금리 민감도"), ("convexity", "Convexity / 곡률"),
            ("dv01", "DV01 / 금리 1bp당 가격 변화"), ("ytm", "YTM / 만기수익률")]):
            card = ttk.LabelFrame(cards, text=label, padding=8)
            card.grid(row=i // 2, column=i % 2, sticky="ew", padx=4, pady=4)
            cards.columnconfigure(i % 2, weight=1)
            value = tk.StringVar(value="—")
            self.metrics[key] = value
            ttk.Label(card, textvariable=value, foreground=TEAL, font=("맑은 고딕", 16, "bold")).pack(anchor="w")
        self.chart = tk.Canvas(tabs["risk"], background="white", height=210, highlightthickness=0)
        self.chart.pack(fill="both", expand=True, pady=10)
        self.chart.bind("<Configure>", self.draw_chart)
        self.table(tabs["risk"], "scenarios", ["금리 충격 bp", "실제 가격", "변화율 %", "듀레이션 근사", "+컨벡시티 근사", "2차 근사 오차"], height=7)
        ttk.Label(tabs["risk"], text="민감도와 근사식의 분모는 Dirty 가격입니다. 단리 모드의 Modified는 가격 미분값입니다.",
                  wraplength=760, foreground="#607089").pack(anchor="w", pady=(8, 0))
        ttk.Label(tabs["flows"], text="미래 이자와 원금을 각각 할인해 현재가치를 더합니다.",
                  font=("맑은 고딕", 12, "bold")).pack(anchor="w", pady=(0, 10))
        self.table(tabs["flows"], "flows", ["지급일", "이자", "원금", "합계", "기간(년)", "할인계수", "현재가치", "비중 %"], height=22, expand=True)
        ttk.Label(tabs["flows"], text="결제일 당일 지급 이자는 제외합니다. 경과이자는 직전 이표일부터 결제일까지 계산합니다.",
                  wraplength=760, foreground="#607089").pack(anchor="w", pady=10)
        ttk.Label(tabs["curve"], text="02  만기별 제로금리", font=("맑은 고딕", 12, "bold")).pack(anchor="w")
        ttk.Label(tabs["curve"], text="중간 이자 없이 만기에만 받는 채권의 금리입니다. 국고채 대표 YTM을 그대로 넣은 시장커브로 해석하지 마세요.\n아래 기본값은 학습용 가정입니다. 노드 사이 선형 보간, 양 끝은 같은 금리로 연장합니다.",
                  wraplength=760, foreground="#607089").pack(anchor="w", pady=10)
        self.field(tabs["curve"], "tenors", "만기(년)  쉼표로 구분")
        self.field(tabs["curve"], "rates", "제로금리(%)  만기와 같은 개수")
        ttk.Button(tabs["curve"], text="현재 YTM으로 평탄 커브 설정", command=self.flat_curve).pack(anchor="w", pady=8)
        self.curve_summary = tk.StringVar()
        ttk.Label(tabs["curve"], textvariable=self.curve_summary, foreground=TEAL, wraplength=760).pack(anchor="w", pady=12)
        self.table(tabs["curve"], "krd", ["만기(년)", "제로금리 %", "키레이트 듀레이션", "키레이트 DV01"], height=12, expand=True)
        ttk.Label(tabs["curve"], text="각 노드를 ±1bp 움직여 재계산합니다. 제로커브는 복리 할인하므로 단리 YTM 모드와 가격·민감도가 다를 수 있습니다.",
                  wraplength=760, foreground="#607089").pack(anchor="w", pady=10)
        ttk.Label(tabs["market"], text="03  관측가격과 비교 / 가격에서 YTM 역산", font=("맑은 고딕", 12, "bold")).pack(anchor="w")
        ttk.Label(tabs["market"], text="입력 종목·결제일·액면금액과 같은 기준의 가격을 넣으세요.\n독립 검증에는 같은 시점에 관측한 가격과 YTM이 모두 필요합니다.",
                  wraplength=760, foreground="#607089").pack(anchor="w", pady=10)
        self.field(tabs["market"], "market_price", "관측가격 (선택, 왼쪽 액면금액 기준)")
        self.field(tabs["market"], "price_kind", "관측가격 종류", choices=("dirty", "clean"))
        self.field(tabs["market"], "observed_at", "관측시각 (예: 2025-10-13 15:30 KST)")
        self.field(tabs["market"], "source_url", "시장자료 출처 URL")
        ttk.Button(tabs["market"], text="관측가격에서 YTM 역산", command=self.invert).pack(anchor="w", pady=8)
        ttk.Button(tabs["market"], text="공시 실거래 3건 비교 보기", command=self.show_disclosures).pack(anchor="w", pady=4)
        ttk.Label(tabs["market"], text="역산한 YTM을 다시 같은 가격에 대입하면 수학적 왕복 확인이며 독립 시장 검증은 아닙니다.",
                  foreground="#607089", wraplength=760).pack(anchor="w", pady=4)
        self.market_text = tk.Text(tabs["market"], height=16, wrap="word", font=("맑은 고딕", 10),
                                   borderwidth=0, padx=10, pady=10)
        self.market_text.pack(fill="both", expand=True, pady=10)
        ttk.Label(self, textvariable=self.status, foreground=TEAL).grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def field(self, parent, key, label, choices=None):
        ttk.Label(parent, text=label).pack(anchor="w", pady=(5, 2))
        var = tk.StringVar()
        self.vars[key] = var
        widget = ttk.Combobox(parent, textvariable=var, values=choices, state="readonly") if choices else ttk.Entry(parent, textvariable=var)
        widget.pack(fill="x")
        var.trace_add("write", self.dirty)
        if key == "ytm":
            var.trace_add("write", self.manual_yield)

    def manual_yield(self, *_):
        self.yield_derived_from_price = False

    def table(self, parent, key, columns, height, expand=False):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=expand)
        tree = ttk.Treeview(frame, columns=list(range(len(columns))), show="headings", height=height)
        for i, title in enumerate(columns):
            tree.heading(i, text=title)
            tree.column(i, width=100 if i else 110, minwidth=80, anchor="e" if i else "center")
        vs = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hs = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.trees[key] = tree

    def dirty(self, *_):
        if self.suspend:
            return
        self.report = None
        self.export.configure(state="disabled")
        self.status.set("입력이 변경되었습니다. 계산하기를 누르세요.")
        for var in self.metrics.values():
            var.set("—")
        for tree in self.trees.values():
            tree.delete(*tree.get_children())
        self.chart.delete("all")
        self.curve_summary.set("")
        self.set_market_text("입력이 변경되었습니다. 다시 계산하세요.")

    def load_fields(self, case):
        self.suspend = True
        self.yield_derived_from_price = False
        b = case["bond"]
        values = {"name": b["name"], "issue": b["issue"], "maturity": b["maturity"],
                  "settlement": case["settlement"], "coupon": b["coupon_rate"] * 100,
                  "face": b["face"], "frequency": b["frequency"], "eom": b.get("end_of_month", False),
                  "ytm": case["ytm"] * 100, "convention": "국고채 단리" if case["convention"] == "ktb_simple" else "교과서 복리",
                  "tenors": ", ".join(str(x) for x in case["curve"]["tenors"]),
                  "rates": ", ".join(f"{x * 100:g}" for x in case["curve"]["rates"]),
                  "market_price": "", "price_kind": "dirty", "observed_at": "", "source_url": ""}
        obs = case.get("market_observation")
        if obs:
            if obs["settlement"] != case["settlement"] or obs["instrument_name"] != b["name"]:
                raise ValueError("시장자료 종목·결제일이 입력 조건과 다릅니다.")
            values.update(market_price=obs["price"] * b["face"] / obs["quote_face"],
                          price_kind=obs["price_kind"], observed_at=obs["observed_at"], source_url=obs["source_url"])
        for key, value in values.items():
            self.vars[key].set(value)
        self.suspend = False

    def input_case(self, include_market=True):
        v = {k: var.get() for k, var in self.vars.items()}
        b = {"name": v["name"], "issue": v["issue"], "maturity": v["maturity"],
             "coupon_rate": float(v["coupon"]) / 100, "face": float(v["face"]),
             "frequency": int(v["frequency"]), "end_of_month": v["eom"]}
        case = {"bond": b, "settlement": v["settlement"], "ytm": float(v["ytm"]) / 100,
                "convention": "ktb_simple" if v["convention"] == "국고채 단리" else "compound",
                "curve": {"tenors": [float(x) for x in v["tenors"].split(",")],
                          "rates": [float(x) / 100 for x in v["rates"].split(",")],
                          "description": "사용자 입력 또는 학습용 가정. 시장 제로커브 여부는 별도 확인."},
                "market_observation": None,
                "reference_sources": deepcopy(self.case.get("sources", self.case.get("reference_sources", []))),
                "notes": ["기본 예제 참고자료는 현재 편집된 입력값의 사실성을 보증하지 않습니다."]}
        if self.yield_derived_from_price:
            case["notes"].append("YTM은 입력 가격에서 역산한 값입니다. 독립 시장 검증에서 제외했습니다.")
        if include_market and not self.yield_derived_from_price and v["market_price"].strip():
            case["market_observation"] = {"price": float(v["market_price"]), "price_kind": v["price_kind"],
                                          "quote_face": b["face"], "settlement": v["settlement"],
                                          "instrument_name": b["name"], "observed_at": v["observed_at"],
                                          "source_url": v["source_url"], "ytm": case["ytm"]}
        return case

    def calculate(self):
        try:
            report = build_report(self.input_case())
            self.render(report)
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            self.dirty()
            self.status.set(f"입력 확인: {error}")

    def render(self, report):
        self.report = report
        r = report["analytics"]
        for key, var in self.metrics.items():
            value = r[key] * 100 if key == "ytm" else r[key]
            suffix = "%" if key == "ytm" else "년" if key == "macaulay_duration" else ""
            var.set(f"{value:,.6f}{suffix}")
        self.fill("scenarios", [[r[k] for k in ("shock_bp", "dirty_price", "change_pct", "duration_price", "convexity_price", "quadratic_error")] for r in report["scenarios"]])
        self.fill("flows", [[r[k] for k in ("payment_date", "coupon", "principal", "amount", "years", "discount_factor", "present_value")] + [r["pv_weight"] * 100] for r in r["cashflows"]])
        kr = report["key_rate_risk"]
        self.fill("krd", [[r["tenor"], r["zero_rate"] * 100, r["key_rate_duration"], r["key_rate_dv01"]] for r in kr["nodes"]])
        self.curve_summary.set(f"커브 Dirty 가격  {kr['curve_dirty_price']:,.6f}\nKRD 합  {kr['krd_sum']:.8f}    평행이동 민감도  {kr['parallel_duration']:.8f}    차이  {kr['sum_minus_parallel']:.2e}")
        comparison = report["market_comparison"]
        lines = ["시장가격 검증: 관측값 미입력" if comparison["status"] == "pending" else
                 f"시장가격 비교 (합격 판정 아님)\n모델−관측 가격: {comparison['price_difference']:,.6f}원\n가격 괴리율: {comparison['price_difference_pct']:.6f}%\n관측가격의 역산 YTM: {comparison['implied_ytm'] * 100:.6f}%\n관측 YTM과 차이: {comparison['yield_difference_bp']:.6f}bp"]
        lines += ["\n기본 예제 참고 출처 (현재 편집 조건과 일치 여부 확인)"]
        for source in report["input"].get("reference_sources", []):
            lines += [source["title"], source["url"]]
        lines += ["\n기본 예제의 발행일·표면금리·낙찰금리는 실제 자료입니다. 결제일은 분석 가정이고 제로커브는 학습용입니다. 실제 시장가격을 확보하기 전까지 시장 일치 검증은 대기 상태입니다."]
        self.set_market_text("\n".join(lines))
        self.export.configure(state="normal")
        self.status.set("계산 완료 · 표와 그래프는 현재 입력값 기준입니다.")
        self.draw_chart()

    def fill(self, key, rows):
        tree = self.trees[key]
        tree.delete(*tree.get_children())
        for row in rows:
            tree.insert("", "end", values=[f"{v:,.6f}" if isinstance(v, float) else v for v in row])

    def set_market_text(self, value):
        self.market_text.configure(state="normal")
        self.market_text.delete("1.0", "end")
        self.market_text.insert("1.0", value)
        self.market_text.configure(state="disabled")

    def flat_curve(self):
        self.vars["rates"].set(", ".join(self.vars["ytm"].get() for _ in self.vars["tenors"].get().split(",")))

    def show_disclosures(self):
        try:
            report = compare_disclosures()
            lines = ["공시 실거래 비교 (현재 왼쪽 입력값과 별개인 고정 예제)", report["source"]["title"], report["source"]["url"], ""]
            for row in report["comparisons"]:
                trade = row["disclosed_trade"]
                lines.append(f"{trade['trade_date']} / 권면 {trade['face_amount_eok']:,}억원 / 수익률 {trade['yield_pct']}%")
                lines.append(f"공시금액 환산단가: {row['disclosed_implied_unit_price']:,.6f}원")
                for scenario in row["settlement_scenarios"]:
                    lines.append(f"  결제일 {scenario['assumed_settlement']} 가정: {scenario['model_dirty_price']:,.6f}원 (차이 {scenario['model_minus_disclosed_unit_price']:+.6f}원)")
                lines.append("")
            lines += report["limitations"]
            self.set_market_text("\n".join(lines))
            self.status.set("공시 자료 3건 표시 · 실제 결제일·가격종류가 미확인이므로 정밀 일치 판정은 아닙니다.")
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.status.set(f"공시 비교 자료 확인: {error}")

    def invert(self):
        try:
            case = self.input_case(include_market=False)
            b = dict(case["bond"])
            b["issue"], b["maturity"] = date.fromisoformat(b["issue"]), date.fromisoformat(b["maturity"])
            y = solve_ytm(Bond(**b), date.fromisoformat(case["settlement"]), float(self.vars["market_price"].get()),
                          kind=self.vars["price_kind"].get(), convention=case["convention"])
            self.vars["ytm"].set(f"{y * 100:.10f}")
            self.yield_derived_from_price = True
            self.render(build_report(self.input_case(include_market=False)))
            self.status.set(f"YTM 역산: {y * 100:.8f}% · 독립 시장 검증은 아닙니다.")
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            self.status.set(f"역산 입력 확인: {error}")

    def draw_chart(self, *_):
        canvas = self.chart
        canvas.delete("all")
        if not self.report:
            return
        w, h = max(canvas.winfo_width(), 300), max(canvas.winfo_height(), 150)
        rows = self.report["scenarios"]
        ymin = min(r[k] for r in rows for k in ("dirty_price", "duration_price", "convexity_price"))
        ymax = max(r[k] for r in rows for k in ("dirty_price", "duration_price", "convexity_price"))
        pad = max((ymax - ymin) * .12, .01)
        ymin, ymax = ymin - pad, ymax + pad
        x = lambda bp: 78 + (bp + 100) / 200 * (w - 104)
        y = lambda value: h - 32 - (value - ymin) / (ymax - ymin) * (h - 72)
        for i in range(4):
            value = ymin + (ymax - ymin) * i / 3
            canvas.create_line(78, y(value), w - 26, y(value), fill="#e7edf5")
            canvas.create_text(70, y(value), text=f"{value:,.1f}", anchor="e", fill="#607089")
        for bp in (-100, -50, 0, 50, 100):
            canvas.create_text(x(bp), h - 16, text=f"{bp:+d}bp", fill="#607089")
        for key, color, label, dash, offset in [("dirty_price", TEAL, "실제 가격", None, 0),
                                               ("duration_price", "#a0adc0", "듀레이션", (4, 3), 150),
                                               ("convexity_price", "#c57b21", "+컨벡시티", (2, 2), 290)]:
            points = [v for row in rows for v in (x(row["shock_bp"]), y(row[key]))]
            canvas.create_line(*points, fill=color, width=2, dash=dash)
            canvas.create_text(80 + offset, 15, text=label, fill=color, anchor="w")

    def open_case(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")], initialdir=ROOT / "data")
        if not path:
            return
        try:
            case = load_case(path)
            if "input" in case and "analytics" in case:
                case = case["input"]
            build_report(case)
            self.case = case
            self.load_fields(case)
            self.calculate()
        except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
            messagebox.showerror("입력 파일 오류", str(error))

    def export_report(self):
        if not self.report:
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="bond-report.json", filetypes=[("JSON", "*.json")])
        if path:
            try:
                save_report(self.report, path)
                self.status.set(f"입력과 계산 결과 저장 완료: {path}")
            except OSError as error:
                messagebox.showerror("저장 오류", str(error))


def main(input_path=None):
    root = tk.Tk()
    root.title("Bond Lab · 파이썬 채권 계산기")
    root.geometry("1280x980")
    root.minsize(1050, 900)
    root.configure(background=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("맑은 고딕", 10), background=BG, foreground=INK)
    style.configure("TButton", padding=(10, 7))
    style.configure("Treeview", rowheight=27, background="white", fieldbackground="white")
    style.configure("TNotebook.Tab", padding=(14, 8))
    try:
        Calculator(root, input_path)
    except (OSError, ValueError, KeyError, TypeError) as error:
        messagebox.showerror("시작 오류", str(error))
        root.destroy()
        return
    root.mainloop()
