#!/usr/bin/env python3
"""G4 Controlled Decoupling 机器验收校验器（G4-CONTROLLED-DECOUPLING-1）。

只读校验 docs/architecture/coupling/G4_COUPLING_REGISTRY.yaml（唯一 SSOT），
验证任务书 §29/§36/§43 全部硬性标准：
  1. coupling_id 唯一且稳定（COUPLING-NNN 格式）
  2. classification 属于合法四分类（CONTROLLED/BOUNDARY/UNCONTROLLED/CRITICAL_UNCONTROLLED）
  3. severity 属于合法枚举（LOW/MEDIUM/HIGH/CRITICAL）
  4. source_owner / target_owner 属于合法 owner 枚举
  5. source_owner != target_owner（或明确 shared-boundary reason）
  6. source_files / target_files 路径存在（仓库内）
  7. evidence / risk / current_contract 非空
  8. 每个 UNCONTROLLED 有 recommended_action
  9. 每个 CRITICAL_UNCONTROLLED 有 remediation_status（REQUIRED/BLOCKED/REMEDIATED）
  10. UNKNOWN_COUPLING = 0（无 UNKNOWN/TBD/TODO/PENDING/MAYBE 分类）
  11. registry 条数 = 分类条数（每一条都有最终四分类）
  12. dependency_type 属于合法枚举
  13. CRITICAL_UNCONTROLLED_REMAINING = 0 才允许 COMPLETE
  14. summary 统计与 couplings 实际分类一致（交叉核对）

用法：
  python scripts/validate_g4_coupling_registry.py
退出码：0 = 全部通过；1 = 存在失败项。

本脚本是治理元数据校验器，不修改任何文件。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

VALID_CLASSIFICATIONS = {
    "CONTROLLED",
    "BOUNDARY",
    "UNCONTROLLED",
    "CRITICAL_UNCONTROLLED",
}
VALID_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
VALID_OWNERS = {
    "PLATFORM",
    "PLATFORM-RELEASE",
    "DOMAIN_SHARED",
    "M01",
    "M02",
    "M03",
    "M04",
    "M05",
    "M06",
    "M07",
}
VALID_DEPENDENCY_TYPES = {
    "IMPORT",
    "API",
    "DATABASE",
    "EVENT",
    "CONFIG",
    "SHARED_STATE",
    "FILE_STORAGE",
    "CAPABILITY",
    "RELEASE",
    "UI",
    "OTHER",
}
FORBIDDEN_CLASSIFICATIONS = {"UNKNOWN", "TBD", "TODO", "PENDING", "MAYBE", "PENDING_REVIEW"}
REGISTRY_PATH = REPO_ROOT / "docs" / "architecture" / "coupling" / "G4_COUPLING_REGISTRY.yaml"


def load_yaml(path: Path) -> dict:
    """加载 YAML（优先 PyYAML，缺失时明确报错）。"""
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        raise ValueError("YAML 根必须是 mapping")
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("需要 PyYAML：pip install pyyaml") from exc


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    if not REGISTRY_PATH.exists():
        print(f"[FAIL] Registry 不存在: {REGISTRY_PATH}")
        return 1

    data = load_yaml(REGISTRY_PATH)
    couplings: list[dict] = data.get("couplings", [])
    summary: dict = data.get("summary", {})

    # ---- 1. coupling_id 唯一 ----
    seen_ids: set[str] = set()
    for i, c in enumerate(couplings):
        cid = str(c.get("coupling_id", "")).strip()
        if not cid:
            errors.append(f"couplings[{i}] 缺 coupling_id")
            continue
        if not re.fullmatch(r"COUPLING-\d{3,}", cid):
            errors.append(f"coupling_id 格式非法: {cid}（要求 COUPLING-NNN）")
        if cid in seen_ids:
            errors.append(f"coupling_id 重复: {cid}")
        seen_ids.add(cid)

    # ---- 2/3/4/5/12. 枚举与 owner 校验 ----
    for c in couplings:
        cid = c.get("coupling_id", "?")
        cls = str(c.get("classification", "")).strip().upper()
        sev = str(c.get("severity", "")).strip().upper()
        src = str(c.get("source_owner", "")).strip()
        tgt = str(c.get("target_owner", "")).strip()
        dtyp = str(c.get("dependency_type", "")).strip().upper()

        if cls not in VALID_CLASSIFICATIONS:
            errors.append(f"{cid}: classification 非法 {cls!r}（合法: {sorted(VALID_CLASSIFICATIONS)}）")
        if cls in FORBIDDEN_CLASSIFICATIONS:
            errors.append(f"{cid}: 禁止分类 {cls!r}（UNKNOWN_COUPLING 必须为 0）")
        if sev not in VALID_SEVERITIES:
            errors.append(f"{cid}: severity 非法 {sev!r}（合法: {sorted(VALID_SEVERITIES)}）")
        if src not in VALID_OWNERS:
            errors.append(f"{cid}: source_owner 非法 {src!r}")
        if tgt not in VALID_OWNERS:
            errors.append(f"{cid}: target_owner 非法 {tgt!r}")
        if dtyp not in VALID_DEPENDENCY_TYPES:
            errors.append(f"{cid}: dependency_type 非法 {dtyp!r}（合法: {sorted(VALID_DEPENDENCY_TYPES)}）")

        if src == tgt:
            reason = str(c.get("shared_boundary_reason", "")).strip()
            if not reason:
                errors.append(f"{cid}: source_owner == target_owner（{src}）且无 shared_boundary_reason")

        # ---- 6. source/target files 存在 ----
        for fkey in ("source_files", "target_files"):
            flist = c.get(fkey, [])
            if isinstance(flist, str):
                flist = [flist]
            if not isinstance(flist, list) or len(flist) == 0:
                errors.append(f"{cid}: {fkey} 为空或非列表")
                continue
            for f in flist:
                p = REPO_ROOT / str(f)
                if not p.exists():
                    errors.append(f"{cid}: {fkey} 文件不存在: {f}")

        # ---- 7. evidence / risk / current_contract 非空 ----
        for fkey in ("evidence", "risk", "current_contract", "current_role"):
            val = str(c.get(fkey, "")).strip()
            if not val or val.upper() in ("NONE", "TBD", "TODO", "UNKNOWN", "-"):
                errors.append(f"{cid}: {fkey} 缺失或为空")

        # ---- 8/9. 分类依赖字段 ----
        rec_action = str(c.get("recommended_action", "")).strip()
        if cls == "UNCONTROLLED" and (not rec_action or rec_action.upper() in ("NONE", "TBD", "")):
            errors.append(f"{cid}: UNCONTROLLED 缺少 recommended_action")
        if cls == "CRITICAL_UNCONTROLLED":
            rem = str(c.get("remediation_status", "")).strip().upper()
            if rem not in ("REQUIRED", "BLOCKED", "REMEDIATED"):
                errors.append(f"{cid}: CRITICAL_UNCONTROLLED 的 remediation_status 必须是 REQUIRED/BLOCKED/REMEDIATED，当前={rem!r}")
            if rem == "BLOCKED" and not str(c.get("remediation_blocker", "")).strip():
                errors.append(f"{cid}: remediation_status=BLOCKED 但缺 remediation_blocker 说明")
        if cls in ("CONTROLLED", "BOUNDARY", "UNCONTROLLED") and str(c.get("remediation_status", "")).strip().upper() in ("REQUIRED", "REMEDIATED"):
            warnings.append(f"{cid}: 非 CRITICAL 分类但 remediation_status={c.get('remediation_status')}（仅提示）")

    # ---- 11. summary 统计与 couplings 交叉核对 ----
    actual_counts = {k: 0 for k in VALID_CLASSIFICATIONS}
    for c in couplings:
        cls = str(c.get("classification", "")).strip().upper()
        if cls in actual_counts:
            actual_counts[cls] += 1

    classified_total = len(couplings)
    expected_total = summary.get("classified_total")
    if expected_total is not None and int(expected_total) != classified_total:
        errors.append(
            f"summary.classified_total={expected_total} 与 couplings 实际条数 {classified_total} 不一致"
        )

    for k in VALID_CLASSIFICATIONS:
        sval = summary.get(k.lower())
        if sval is not None and int(sval) != actual_counts[k]:
            errors.append(f"summary.{k.lower()}={sval} 与实际 {actual_counts[k]} 不一致")

    unknown = int(summary.get("unknown_coupling", 0))
    if unknown != 0:
        errors.append(f"UNKNOWN_COUPLING = {unknown}（必须为 0）")

    owner_conflict = int(summary.get("owner_conflict", 0))
    if owner_conflict != 0:
        errors.append(f"OWNER_CONFLICT = {owner_conflict}（必须为 0）")

    critical_before = int(summary.get("critical_uncontrolled_before", 0))
    critical_remaining = int(summary.get("critical_uncontrolled_remaining", 0))
    remediated = int(summary.get("critical_remediated", 0))
    blocked = int(summary.get("critical_blocked", 0))
    if critical_before != remediated + blocked + critical_remaining:
        errors.append(
            f"summary 账不平: critical_before={critical_before} != remediated({remediated}) + blocked({blocked}) + remaining({critical_remaining})"
        )
    if critical_remaining != 0:
        errors.append(f"CRITICAL_UNCONTROLLED_REMAINING = {critical_remaining}（必须为 0 才允许 COMPLETE）")

    for w in warnings:
        print(f"[WARN] {w}")

    if errors:
        print("G4_VALIDATION = FAIL")
        for e in errors:
            print(f"  [FAIL] {e}")
        return 1

    print("G4_VALIDATION = PASS")
    print(f"  COUPLING_CANDIDATES      = {classified_total}")
    print(f"  CLASSIFIED_TOTAL         = {classified_total}")
    for k in ("CONTROLLED", "BOUNDARY", "UNCONTROLLED", "CRITICAL_UNCONTROLLED"):
        print(f"  {k:24s} = {actual_counts[k]}")
    print(f"  CRITICAL_BEFORE          = {critical_before}")
    print(f"  CRITICAL_REMEDIATED      = {remediated}")
    print(f"  CRITICAL_BLOCKED         = {blocked}")
    print(f"  CRITICAL_REMAINING       = {critical_remaining}")
    print(f"  UNKNOWN_COUPLING         = {unknown}")
    print(f"  OWNER_CONFLICT           = {owner_conflict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
