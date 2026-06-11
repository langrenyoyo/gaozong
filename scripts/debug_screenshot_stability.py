"""P0-3F 微信截图稳定性诊断脚本。

只做截图采集和报告输出，不执行搜索、不发送消息。
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

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "debug_screenshots" / "screenshot_stability"


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"无法解析布尔值: {value}")


def get_wechat_rect(position: str) -> dict:
    """确保微信窗口位于指定位置并返回窗口矩形。"""
    from app.wechat_ui.window_locator import activate_wechat_window

    result = activate_wechat_window(position=position)
    if not result.get("success"):
        raise RuntimeError(result.get("message") or "微信窗口激活失败")
    rect = result.get("actual_rect")
    if not rect:
        raise RuntimeError("无法读取微信窗口位置")
    return rect


def calculate_center_region(rect: dict) -> tuple[int, int, int, int]:
    """计算微信客户区中心区域。"""
    width = int(rect["right"] - rect["left"])
    height = int(rect["bottom"] - rect["top"])
    return (
        int(rect["left"] + width * 0.20),
        int(rect["top"] + height * 0.18),
        int(rect["right"] - width * 0.10),
        int(rect["bottom"] - height * 0.12),
    )


def capture_once(mode: str, bbox: tuple[int, int, int, int], output_path: Path) -> dict:
    """执行一次截图并返回记录。"""
    from app.wechat_ui.screenshot_debug import capture_screen_result

    result = capture_screen_result(bbox=bbox, path=output_path)
    return {
        "mode": mode,
        "success": result["success"],
        "path": result["path"],
        "error": result["error"],
        "stage": result["stage"],
        "elapsed_ms": result["elapsed_ms"],
    }


def build_stability_report(
    run_id: str,
    repeat: int,
    output_dir: Path,
    entries: list[dict],
) -> dict:
    """生成并写入 JSON + Markdown 汇总。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(entries)
    success_count = sum(1 for item in entries if item.get("success"))
    failure_count = total - success_count
    report = {
        "run_id": run_id,
        "repeat": repeat,
        "total": total,
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate": round(success_count / total, 4) if total else 0,
        "entries": entries,
    }

    json_path = output_dir / "screenshot_stability_report.json"
    md_path = output_dir / "screenshot_stability_summary.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# P0-3F 截图稳定性诊断摘要",
        "",
        f"- run_id: `{run_id}`",
        f"- repeat: `{repeat}`",
        f"- total: `{total}`",
        f"- success_count: `{success_count}`",
        f"- failure_count: `{failure_count}`",
        f"- success_rate: `{report['success_rate']}`",
        "",
        "| index | mode | success | elapsed_ms | stage | error |",
        "|---:|---|---:|---:|---|---|",
    ]
    for index, item in enumerate(entries, start=1):
        lines.append(
            "| {idx} | {mode} | {success} | {elapsed} | {stage} | {error} |".format(
                idx=index,
                mode=item.get("mode"),
                success=item.get("success"),
                elapsed=item.get("elapsed_ms"),
                stage=item.get("stage") or "",
                error=(item.get("error") or "").replace("|", "/")[:120],
            )
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    report["json_path"] = str(json_path)
    report["markdown_path"] = str(md_path)
    return report


def run_diagnosis(args: argparse.Namespace) -> dict:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(args.output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    rect = get_wechat_rect(args.position)
    full_bbox = (
        int(rect["left"]), int(rect["top"]),
        int(rect["right"]), int(rect["bottom"]),
    )
    center_bbox = calculate_center_region(rect)
    entries = []

    for index in range(1, args.repeat + 1):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        entries.append(capture_once(
            "full_window",
            full_bbox,
            run_dir / f"{ts}_{index:03d}_full_window.png",
        ))
        time.sleep(args.interval)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        entries.append(capture_once(
            "center_region",
            center_bbox,
            run_dir / f"{ts}_{index:03d}_center_region.png",
        ))
        time.sleep(args.interval)

    return build_stability_report(run_id, args.repeat, run_dir, entries)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P0-3F 微信截图稳定性诊断")
    parser.add_argument("--repeat", type=int, default=50, help="每类截图重复次数")
    parser.add_argument("--position", choices=["left", "right"], default="right", help="微信窗口位置")
    parser.add_argument("--interval", type=float, default=0.05, help="每次截图间隔秒数")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_diagnosis(args)
    print(json.dumps({
        "run_id": report["run_id"],
        "total": report["total"],
        "success_count": report["success_count"],
        "failure_count": report["failure_count"],
        "success_rate": report["success_rate"],
        "json_path": report["json_path"],
        "markdown_path": report["markdown_path"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
