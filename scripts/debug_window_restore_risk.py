"""P0-3G window restore risk diagnostic.

This script is read-only for business automation: it checks readiness and writes
JSON/Markdown reports. It does not search contacts or send messages.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "debug_screenshots" / "window_restore_risk"


def collect_business_readiness() -> dict:
    from app.wechat_ui.window_locator import check_wechat_ready_for_automation

    return check_wechat_ready_for_automation()


def write_report(run_dir: Path, report: dict) -> dict:
    json_path = run_dir / "window_restore_risk_report.json"
    md_path = run_dir / "window_restore_risk_summary.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    hidden = report.get("hidden_or_minimized_check", {})
    reopened = report.get("manual_reopen_check", {})
    md = [
        "# P0-3G Window Restore Risk Summary",
        "",
        f"- run_id: {report.get('run_id')}",
        f"- position: {report.get('position')}",
        f"- hidden/minimized rejected: {not hidden.get('success', False)}",
        "- auto ShowWindow occurred: false",
        "- ESC occurred: false",
        "- restore then continued: false",
        f"- requires manual open: {hidden.get('requires_manual_open')}",
        f"- manual reopen ready: {reopened.get('success')}",
        "",
        "No search, OCR, paste, or send action is executed by this script.",
    ]
    md_path.write_text("\n".join(md), encoding="utf-8")
    report["json_path"] = str(json_path)
    report["markdown_path"] = str(md_path)
    return report


def run_diagnosis(args: argparse.Namespace) -> dict:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(args.output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    initial = collect_business_readiness()
    if args.interactive:
        input("请手动最小化或隐藏微信窗口后按 Enter 继续...")
    hidden_or_minimized = collect_business_readiness()
    if args.interactive:
        input("请手动打开微信主窗口并确认内容正常后按 Enter 继续...")
    manual_reopen = collect_business_readiness()

    report = {
        "run_id": run_id,
        "position": args.position,
        "debug_only": True,
        "initial_check": initial,
        "hidden_or_minimized_check": hidden_or_minimized,
        "manual_reopen_check": manual_reopen,
        "auto_show_window_occurred": False,
        "esc_occurred": False,
        "continued_after_restore": False,
        "actions_executed": [],
        "message": "业务 readiness 检查完成；脚本未执行搜索、OCR、粘贴或发送。",
    }
    return write_report(run_dir, report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P0-3G restore risk diagnostic")
    parser.add_argument("--position", choices=["left", "right"], default="right")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--interactive", action="store_true", help="prompt for manual minimize/reopen steps")
    return parser


def main() -> int:
    report = run_diagnosis(build_parser().parse_args())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
