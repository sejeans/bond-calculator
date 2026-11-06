import argparse
import sys

from .report import load_case, build_report, save_report, text_summary


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="파이썬 채권 계산기: 입력 금리는 소수(3%=0.03)")
    parser.add_argument("--input", help="채권·제로금리·시장 관측값 JSON")
    parser.add_argument("--output", help="결과 JSON 저장 경로")
    parser.add_argument("--gui", action="store_true", help="계산기 화면 열기")
    args = parser.parse_args()
    if args.gui:
        from .gui import main as gui_main
        gui_main(args.input)
        return
    try:
        report = build_report(load_case(args.input))
        print(text_summary(report))
        if args.output:
            save_report(report, args.output)
            print(f"저장: {args.output}")
    except (ValueError, KeyError, TypeError, OverflowError, OSError) as error:
        parser.exit(2, f"입력 오류: {error}\n")


if __name__ == "__main__":
    main()
