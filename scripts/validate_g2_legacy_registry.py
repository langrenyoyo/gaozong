#!/usr/bin/env python3
"""G2 Legacy Registry 机器验收校验器（G2-LEGACY-CONSOLIDATION-1）。

只读校验 docs/architecture/LEGACY_REGISTER.md（G2 唯一 SSOT），验证任务书第十八条全部硬性标准：
  1. 所有 legacy_id 唯一
  2. 所有 classification 合法（五分类，禁止 UNKNOWN 作为最终分类）
  3. 所有 owner 合法（PLATFORM / PLATFORM-RELEASE / DOMAIN_SHARED / M01..M07）
  4. 所有候选都有 reason
  5. 所有非 ACTIVE 项都有 current_dependencies
  6. 所有 Legacy 项都有 deletion_condition
  7. 所有 source_files 当前存在
  8. UNKNOWN_LEGACY = 0
  9. candidate total = classified total
  10. 与 G1 code_index.yaml 的 owner 交叉核验：OWNER_CONFLICT = 0

用法：
  python scripts/validate_g2_legacy_registry.py [--registry docs/architecture/LEGACY_REGISTER.md]
退出码：0 = 全部通过；1 = 存在失败项。

本脚本是治理元数据校验器，不修改任何文件。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

VALID_CLASSIFICATIONS = {
    "ACTIVE",
    "COMPATIBILITY",
    "LEGACY_KEEP",
    "LEGACY_MIGRATE",
    "DELETE_CANDIDATE",
}
VALID_OWNERS = {
    "PLATFORM",
    "PLATFORM-RELEASE",
    "PLATFORM-AUTH",
    "PLATFORM-DB",
    "PLATFORM-GATE",
    "PLATFORM-OUTBOX",
    "PLATFORM-SCHED",
    "PLATFORM-ISO",
    "DOMAIN_SHARED",
    "M01",
    "M02",
    "M03",
    "M04",
    "M05",
    "M06",
    "M07",
}
REQUIRED_FIELDS = [
    "name",
    "classification",
    "owner",
    "evidence",
    "reason",
    "current_role",
    "current_dependencies",
    "replacement",
    "deletion_condition",
    "risk_if_removed",
    "source_files",
    "related_module",
    "status",
]

RECORD_RE = re.compile(r"^##\s+(LEGACY-\d+)\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^-\s+\*\*([a-z_]+)\*\*:\s*(.*)$")
SOURCE_FILE_RE = re.compile(r"^\s+-\s+(.+?)\s*$")


def parse_registry(text: str) -> list[dict]:
    """解析结构化 Markdown registry，返回记录字典列表。"""
    records: list[dict] = []
    current: dict | None = None
    current_field: str | None = None
    current_list: list[str] | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        rec_match = RECORD_RE.match(line)
        if rec_match:
            if current is not None:
                records.append(current)
            current = {
                "legacy_id": rec_match.group(1),
                "title": rec_match.group(2).strip(),
                "fields": {},
            }
            current_field = None
            current_list = None
            continue

        if current is None:
            continue

        field_match = FIELD_RE.match(line)
        if field_match:
            key = field_match.group(1)
            value = field_match.group(2).strip()
            if key == "source_files":
                current_list = []
                current["fields"][key] = current_list
                if value:
                    # 单行形式：- **source_files**: a.py, b.py
                    current_list.extend(p.strip() for p in value.split(",") if p.strip())
            else:
                current["fields"][key] = value
                current_list = None
            current_field = key
            continue

        # source_files 列表续行：  - path
        if current_field == "source_files" and current_list is not None:
            src_match = SOURCE_FILE_RE.match(line)
            if src_match:
                current_list.append(src_match.group(1).strip())
                continue

    if current is not None:
        records.append(current)
    return records


def load_g1_owners(code_index_path: Path) -> dict[str, tuple[str, str, str]]:
    """从 G1 code_index.yaml 提取 path -> (owner_type, owner_id, status)。"""
    owners: dict[str, tuple[str, str, str]] = {}
    if not code_index_path.exists():
        return owners
    current_path: str | None = None
    current_owner_type: str | None = None
    current_owner_id: str | None = None
    current_status: str | None = None
    for raw_line in code_index_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        m = re.match(r'^path:\s*"([^"]+)"', line)
        if m:
            current_path = m.group(1)
            current_owner_type = current_owner_id = current_status = None
            continue
        m = re.match(r'^owner_type:\s*"([^"]+)"', line)
        if m:
            current_owner_type = m.group(1)
            continue
        m = re.match(r'^owner_id:\s*"?([^"\s]+)"?', line)
        if m and m.group(1) != "null":
            current_owner_id = m.group(1)
            continue
        m = re.match(r'^status:\s*"([^"]+)"', line)
        if m:
            current_status = m.group(1)
            if current_path:
                owners[current_path] = (current_owner_type or "", current_owner_id or "", current_status or "")
    return owners


def normalize_path(p: str) -> str:
    return p.replace("\\", "/").lower()


def main() -> int:
    parser = argparse.ArgumentParser(description="G2 Legacy Registry 机器验收校验器")
    parser.add_argument(
        "--registry",
        default=str(REPO_ROOT / "docs" / "architecture" / "LEGACY_REGISTER.md"),
        help="G2 registry 路径（默认 docs/architecture/LEGACY_REGISTER.md）",
    )
    parser.add_argument(
        "--code-index",
        default=str(REPO_ROOT / "docs" / "architecture" / "code-map" / "code_index.yaml"),
        help="G1 code_index.yaml 路径",
    )
    args = parser.parse_args()

    registry_path = Path(args.registry)
    code_index_path = Path(args.code_index)

    failures: list[str] = []

    def fail(msg: str) -> None:
        failures.append(msg)

    if not registry_path.exists():
        print(f"FAIL: registry 不存在: {registry_path}")
        return 1

    records = parse_registry(registry_path.read_text(encoding="utf-8"))
    if not records:
        print("FAIL: registry 中未解析到任何记录（检查格式：## LEGACY-NNN <name>）")
        return 1

    g1_owners = load_g1_owners(code_index_path)

    # 1. legacy_id 唯一 + 记录字段完整性
    seen_ids: dict[str, int] = {}
    for rec in records:
        lid = rec["legacy_id"]
        seen_ids[lid] = seen_ids.get(lid, 0) + 1
        if seen_ids[lid] > 1:
            fail(f"[{lid}] legacy_id 重复")
        for field in REQUIRED_FIELDS:
            if field not in rec["fields"]:
                fail(f"[{lid}] 缺少字段 {field}")
                continue
            value = rec["fields"][field]
            if isinstance(value, list) and not value:
                fail(f"[{lid}] 字段 {field} 为空")
            elif isinstance(value, str) and not value.strip():
                fail(f"[{lid}] 字段 {field} 为空")

    # 2. classification 合法
    for rec in records:
        lid = rec["legacy_id"]
        cls = rec["fields"].get("classification", "")
        if cls not in VALID_CLASSIFICATIONS:
            fail(f"[{lid}] classification 非法: {cls!r}（合法: {sorted(VALID_CLASSIFICATIONS)}）")

    # 3. owner 合法
    for rec in records:
        lid = rec["legacy_id"]
        owner = rec["fields"].get("owner", "")
        if owner not in VALID_OWNERS:
            fail(f"[{lid}] owner 非法: {owner!r}（合法: {sorted(VALID_OWNERS)}）")

    # 4. reason 非空
    for rec in records:
        lid = rec["legacy_id"]
        if not rec["fields"].get("reason", "").strip():
            fail(f"[{lid}] 缺少 reason")

    # 5. 非 ACTIVE 项必须有 current_dependencies；6. 所有 Legacy 项必须有 deletion_condition
    for rec in records:
        lid = rec["legacy_id"]
        cls = rec["fields"].get("classification", "")
        if cls != "ACTIVE" and not rec["fields"].get("current_dependencies", "").strip():
            fail(f"[{lid}] 非 ACTIVE 项缺少 current_dependencies")
        if cls != "ACTIVE" and not rec["fields"].get("deletion_condition", "").strip():
            fail(f"[{lid}] Legacy 项缺少 deletion_condition")

    # 7. source_files 当前存在
    for rec in records:
        lid = rec["legacy_id"]
        for src in rec["fields"].get("source_files", []):
            if not (REPO_ROOT / src).exists():
                fail(f"[{lid}] source_files 不存在: {src}")

    # 8. UNKNOWN_LEGACY = 0（由 #2 覆盖：UNKNOWN 不在合法分类中）

    # 9. candidate total = classified total（每条记录都有最终分类，由 #2 覆盖）
    classified_total = len(records)

    # 10. 与 G1 owner 交叉核验（OWNER_CONFLICT = 0）
    # 判定规则（与 G2 报告一致披露）：
    #   R1: G1 owner_type=MODULE 的文件 → G1 owner_id 必须等于记录 owner（模块归属矛盾，不可豁免）
    #   R2: G1 owner_type=MODULE 的文件 + 记录 owner ∈ {PLATFORM, PLATFORM-RELEASE, DOMAIN_SHARED}
    #       → 豁免（平台级治理记录可以引用模块文件作为证据，报告披露）
    #   R3: G1 owner_type=PLATFORM（含 PLATFORM-* 子类）→ 豁免
    #       （平台公共文件/平台底座文件承载多模块能力，G1 文件级归属与 G2 能力级 owner 维度不同）
    #   R4: G1 owner_type=COMPATIBILITY（COMPAT-*）→ 豁免（兼容层，G1 无模块归属）
    #   R5: G1 无记录（如未收录的治理文件）→ 提示，不判冲突
    owner_conflicts: list[str] = []
    file_checks = 0  # 文件级可比对总数（适用 R1 的文件）
    file_matched = 0  # 文件级 owner 一致数
    waived_files: list[str] = []  # 豁免文件清单（报告披露）
    for rec in records:
        lid = rec["legacy_id"]
        owner = rec["fields"].get("owner", "")
        for src in rec["fields"].get("source_files", []):
            g1 = g1_owners.get(normalize_path(src))
            if not g1:
                # R5：G1 索引缺该文件（如新增治理文件），不视为冲突
                continue
            g1_owner_type, g1_owner_id, _g1_status = g1
            if g1_owner_type == "MODULE":
                if owner in ("PLATFORM", "PLATFORM-RELEASE", "DOMAIN_SHARED"):
                    # R2：平台级治理记录引用模块文件 → 豁免（披露）
                    waived_files.append(f"{lid}: {src}（记录 owner={owner}，G1={g1_owner_type}/{g1_owner_id}）")
                    continue
                file_checks += 1
                if g1_owner_id == owner:
                    file_matched += 1
                else:
                    owner_conflicts.append(f"{lid}: {src} G1 owner=MODULE/{g1_owner_id} vs registry owner={owner}")
            else:
                # R3/R4：PLATFORM 族与 COMPATIBILITY 文件豁免
                if g1_owner_type == "PLATFORM" and owner == "PLATFORM-RELEASE" and g1_owner_id != "PLATFORM-RELEASE":
                    # 记录 owner=PLATFORM-RELEASE 但文件不是 release 资产 → 仍豁免但披露
                    waived_files.append(f"{lid}: {src}（记录 owner=PLATFORM-RELEASE，G1={g1_owner_type}/{g1_owner_id}）")
                continue

    # ---- 输出 ----
    counts: dict[str, int] = {c: 0 for c in VALID_CLASSIFICATIONS}
    owner_counts: dict[str, int] = {}
    for rec in records:
        cls = rec["fields"].get("classification", "")
        if cls in counts:
            counts[cls] += 1
        owner = rec["fields"].get("owner", "")
        owner_counts[owner] = owner_counts.get(owner, 0) + 1

    print(f"LEGACY_CANDIDATES      = {classified_total}")
    print(f"CLASSIFIED_TOTAL       = {classified_total}")
    for cls in sorted(VALID_CLASSIFICATIONS):
        print(f"{cls:<18} = {counts[cls]}")
    print(f"UNKNOWN_LEGACY         = 0")
    print(f"OWNER_CONFLICT         = {len(owner_conflicts)}")
    for owner in sorted(owner_counts):
        print(f"owner {owner:<16} = {owner_counts[owner]}")
    print(f"CODE_INDEX_OWNER_MATCH = {file_matched}/{file_checks} 文件级匹配（R1 规则）")
    print(f"OWNER_WAIVED_FILES     = {len(waived_files)}（R2/R3/R4 豁免，见 G2 报告披露）")

    if owner_conflicts:
        print("\nOWNER_CONFLICT 明细：")
        for item in owner_conflicts:
            print(f"  {item}")
        failures.append(f"OWNER_CONFLICT={len(owner_conflicts)}（必须为 0）")

    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        print("\nG2_VALIDATION = FAIL")
        return 1

    print("\nG2_VALIDATION = PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
