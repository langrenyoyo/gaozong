"""P0-3H 联系人 OCR 验证调试脚本。

脚本只验证当前已打开聊天窗口的联系人身份，不搜索、不输入、不发送。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "debug_screenshots" / "contact_verify_ocr"


def build_verify_ocr_report(
    run_id: str,
    nickname: str,
    repeat: int,
    output_dir: str | Path,
    entries: list[dict],
) -> dict:
    """构建并保存 OCR 联系人验证汇总。"""
    run_dir = Path(output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    verified_count = sum(1 for item in entries if item.get("verified"))
    partial_match_count = sum(1 for item in entries if item.get("partial_match"))
    manual_review_required_count = sum(1 for item in entries if item.get("manual_review_required"))

    report = {
        "run_id": run_id,
        "nickname": nickname,
        "repeat": repeat,
        "verified_count": verified_count,
        "partial_match_count": partial_match_count,
        "manual_review_required_count": manual_review_required_count,
        "entries": entries,
    }

    json_path = run_dir / "contact_verify_ocr_report.json"
    markdown_path = run_dir / "contact_verify_ocr_summary.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# P0-3H 联系人 OCR 验证摘要",
        "",
        f"- run_id: {run_id}",
        f"- nickname: {nickname}",
        f"- repeat: {repeat}",
        f"- verified_count: {verified_count}",
        f"- partial_match_count: {partial_match_count}",
        f"- manual_review_required_count: {manual_review_required_count}",
        "",
        "| 序号 | strategy | verified | partial_match | manual_review_required | ocr_text | confidence | failure_stage | evidence |",
        "|---:|---|---|---|---|---|---:|---|---|",
    ]
    for index, item in enumerate(entries, start=1):
        evidence = item.get("evidence") or {}
        evidence_path = evidence.get("cropped_path") or evidence.get("screenshot_path") or ""
        lines.append(
            f"| {index} | {item.get('strategy')} | {item.get('verified')} | "
            f"{item.get('partial_match')} | {item.get('manual_review_required')} | "
            f"{item.get('ocr_text') or ''} | {item.get('confidence') or 0:.4f} | "
            f"{item.get('failure_stage') or ''} | {evidence_path} |"
        )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")

    report["json_path"] = str(json_path)
    report["markdown_path"] = str(markdown_path)
    return report


def run_debug(args: argparse.Namespace) -> dict:
    """循环调用联系人验证，不执行任何发送动作。"""
    from app.wechat_ui.contact_verifier import verify_current_chat_contact

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    entries = []
    for index in range(int(args.repeat)):
        result = verify_current_chat_contact(args.nickname)
        result["index"] = index + 1
        result["engine"] = args.engine
        entries.append(result)
        if index + 1 < int(args.repeat):
            time.sleep(float(args.interval))

    return build_verify_ocr_report(
        run_id=run_id,
        nickname=args.nickname,
        repeat=int(args.repeat),
        output_dir=args.output_dir,
        entries=entries,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P0-3H 联系人 OCR 验证调试")
    parser.add_argument("--nickname", required=True, help="期望联系人昵称")
    parser.add_argument("--position", choices=["left", "right"], default="right", help="保留参数，不触发窗口恢复")
    parser.add_argument("--engine", choices=["easyocr", "paddleocr", "tesseract", "none"], default="easyocr")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser


def main() -> int:
    result = run_debug(build_parser().parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
