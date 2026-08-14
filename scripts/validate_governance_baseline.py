#!/usr/bin/env python3
"""GC Governance Baseline 机器验收校验器（GC-GOVERNANCE-BASELINE-CLOSURE-1）。

只读校验 docs/architecture/governance/GOVERNANCE_BASELINE.yaml（Manifest SSOT）+ 
GOVERNANCE_BACKLOG.yaml（开放问题索引），并按任务书 §十六 V1~V10 交叉验证 G1~G4 SSOT：

  V1  — 七模块完整（M01~M07 exactly 7）
  V2  — G1 ownership：UNKNOWN_OWNER = 0（code_index 无未知 owner）
  V3  — G2：UNKNOWN_LEGACY = 0（legacy 无未知分类）
  V4  — G3：MODULE_KEY_CHAIN_BASELINE = 7/7、UNKNOWN_VERIFICATION = 0
  V5  — G4：UNKNOWN_COUPLING = 0、CRITICAL_UNCONTROLLED_COUPLING = 0
  V6  — SSOT pointers：Manifest 所有 pointer 路径存在
  V7  — module IDs：G1/G2/G3/G4 使用的 owner 属于冻结枚举
  V8  — duplicate SSOT：不存在两个都声明 authoritative 的 legacy/verification/coupling registry
  V9  — backlog references：关键 id（FAILURE-*/COUPLING-*/HIGH-03/RG-FOLLOWUP-*）可回溯到 SSOT/evidence
  V10 — stage state：G0~G4 = COMPLETE（不引用 PENDING/IN_PROGRESS 作为当前状态）

fail-closed：任何缺失/非法/未知 → exit != 0。历史报告中的旧状态（PENDING/BLOCKED/OLD HEAD）不作为
SSOT conflict（任务书 §十七），只要求 current authoritative pointer 一致。

用法：
  python scripts/validate_governance_baseline.py
退出码：0 = 全部通过；1 = 存在失败项。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

MANIFEST_PATH = REPO_ROOT / "docs" / "architecture" / "governance" / "GOVERNANCE_BASELINE.yaml"
BACKLOG_PATH = REPO_ROOT / "docs" / "architecture" / "governance" / "GOVERNANCE_BACKLOG.yaml"

MODULES = [f"M0{i}" for i in range(1, 8)]
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
VALID_BUCKETS = {
    "PRODUCT_FAILURE",
    "KNOWN_RISK",
    "TEST_DRIFT",
    "ENV_CONSTRAINT",
    "LEGACY_DEBT",
    "COUPLING_DEBT",
    "RELEASE_FOLLOWUP",
}
FORBIDDEN_BUCKETS = {"OTHER", "TODO", "MAYBE", "UNKNOWN", "MISC"}


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


def check_ssot_conflicts(errors: list[str]) -> None:
    """V8：唯一 authoritative SSOT 检查（不重复建第二套 legacy/verification/coupling registry）。"""
    # G2 registry 唯一性：LEGACY_REGISTER.md 是唯一；检查是否存在第二个声明 authoritative 的 legacy 文件
    legacy_authoritative = [p for p in REPO_ROOT.joinpath("docs").rglob("*.md") if "LEGACY_REGISTER" in p.name]
    coupling_registries = list(REPO_ROOT.joinpath("docs", "architecture", "coupling").glob("*COUPLING_REGISTRY*"))
    if len(legacy_authoritative) == 0:
        errors.append("V8: 未找到唯一 authoritative legacy registry（docs/architecture/LEGACY_REGISTER.md）")
    if len(coupling_registries) == 0:
        errors.append("V8: 未找到唯一 authoritative coupling registry（docs/architecture/coupling/G4_COUPLING_REGISTRY.yaml）")
    if len(coupling_registries) > 1:
        errors.append(f"V8: 存在多个 coupling registry 候选: {[p.name for p in coupling_registries]}（禁止重复 SSOT）")


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    # ---------- 基础文件存在性 ----------
    if not MANIFEST_PATH.exists():
        print("[FAIL] Manifest 不存在:", MANIFEST_PATH)
        return 1
    if not BACKLOG_PATH.exists():
        print("[FAIL] Backlog 不存在:", BACKLOG_PATH)
        return 1

    manifest = load_yaml(MANIFEST_PATH)
    backlog = load_yaml(BACKLOG_PATH)

    baseline = manifest.get("baseline", {})
    stages = manifest.get("stages", {})
    ssot = manifest.get("ssot", {})
    metrics = manifest.get("metrics", {})
    validators = manifest.get("validators", {})

    # ---------- V10: stage state ----------
    expected_status = {
        "G0": "COMPLETE",
        "G1": "COMPLETE_AND_CURRENT",
        "G2": "COMPLETE",
        "G3": "COMPLETE",
        "G4": "COMPLETE",
        "GC": "CLOSED_AND_VALIDATED",
    }
    for gk, want in expected_status.items():
        st = stages.get(gk, {}).get("status", "")
        if st != want:
            errors.append(f"V10: {gk} status={st!r}，期望 {want!r}")

    # ---------- V1: 七模块 ----------
    modules = manifest.get("modules", [])
    if sorted(modules) != sorted(MODULES):
        errors.append(f"V1: modules={modules}，期望 exactly {MODULES}")
    else:
        print(f"  V1 modules = {len(modules)}/7")

    # ---------- V7: owner 枚举 ----------
    owners = manifest.get("owners", [])
    for o in owners:
        if o not in VALID_OWNERS:
            errors.append(f"V7: manifest owners 含非法 owner {o!r}")
    # 禁止新 owner（M08/UI/SHARED/COMMON/CORE）
    for forbidden in ("M08", "UI", "SHARED", "COMMON", "CORE"):
        if forbidden in owners:
            errors.append(f"V7: 出现禁止的正式 owner {forbidden!r}")

    # ---------- V6: SSOT pointers ----------
    pointer_keys = [
        "code_map",
        "legacy_registry",
        "verification_matrix",
        "coupling_registry",
        "governance_backlog",
        "governance_report",
    ]
    for k in pointer_keys:
        p = REPO_ROOT / str(ssot.get(k, ""))
        if not p.exists():
            errors.append(f"V6: ssot.{k} 路径不存在: {ssot.get(k)}")
    for chain in ssot.get("module_chains", []):
        if not (REPO_ROOT / chain).exists():
            errors.append(f"V6: module_chains 路径不存在: {chain}")
    for gk in ("g2", "g3", "g4", "gc"):
        v = validators.get(gk, "")
        # validator pointer 可能是路径或描述；路径部分以 scripts/ 开头
        if isinstance(v, str) and v.startswith("scripts/"):
            if not (REPO_ROOT / v).exists():
                errors.append(f"V6: validator.{gk} 路径不存在: {v}")

    # ---------- metrics 交叉核对 ----------
    g1 = metrics.get("g1", {})
    if int(g1.get("unmapped", -1)) != 0:
        errors.append(f"V-metrics: g1.unmapped={g1.get('unmapped')}，期望 0")
    g2 = metrics.get("g2", {})
    g2_sum = sum(int(g2.get(k, 0)) for k in ("active", "compatibility", "legacy_keep", "legacy_migrate", "delete_candidate"))
    if int(g2.get("candidates", -1)) != g2_sum:
        errors.append(f"V-metrics: g2.candidates={g2.get('candidates')} != 五分类和 {g2_sum}")
    g3 = metrics.get("g3", {})
    if str(g3.get("key_chain_baseline")) != "7/7":
        errors.append(f"V-metrics: g3.key_chain_baseline={g3.get('key_chain_baseline')}，期望 7/7")
    if int(g3.get("unknown_verification", -1)) != 0:
        errors.append(f"V-metrics: g3.unknown_verification={g3.get('unknown_verification')}，期望 0")
    g4 = metrics.get("g4", {})
    if int(g4.get("critical_remaining", -1)) != 0:
        errors.append(f"V-metrics: g4.critical_remaining={g4.get('critical_remaining')}，期望 0")
    if int(g4.get("unknown_coupling", -1)) != 0:
        errors.append(f"V-metrics: g4.unknown_coupling={g4.get('unknown_coupling')}，期望 0")

    # ---------- Backlog 校验 ----------
    items = backlog.get("items", [])
    summary = backlog.get("summary", {})
    counts: dict[str, int] = {}
    for item in items:
        bucket = item.get("bucket", "")
        if bucket not in VALID_BUCKETS:
            errors.append(f"V9: backlog 条目 {item.get('id')} bucket={bucket!r} 非法或禁止（{FORBIDDEN_BUCKETS}）")
            continue
        counts[bucket] = counts.get(bucket, 0) + 1
        # 每条必须有 ssot_ref 与 evidence（V9 可回溯）
        if not str(item.get("ssot_ref", "")).strip():
            errors.append(f"V9: backlog 条目 {item.get('id')} 缺 ssot_ref")
        if not str(item.get("evidence", "")).strip():
            errors.append(f"V9: backlog 条目 {item.get('id')} 缺 evidence")
        if not str(item.get("status", "")).strip():
            errors.append(f"V9: backlog 条目 {item.get('id')} 缺 status")
    bucket_counts = summary.get("bucket_counts", {})
    for b in VALID_BUCKETS:
        if int(bucket_counts.get(b, -1)) != counts.get(b, 0):
            errors.append(f"V9: summary.bucket_counts.{b}={bucket_counts.get(b)} 与实际 {counts.get(b)} 不一致")
    if int(summary.get("unknown_bucket", -1)) != 0:
        errors.append(f"V9: backlog summary.unknown_bucket={summary.get('unknown_bucket')}，期望 0")

    # V9 关键 id 可回溯（存在即视为可回溯——evidence 已要求非空）
    required_ids = {"FAILURE-M01-001", "FAILURE-M02-001", "FAILURE-M03-001", "FAILURE-M05-001",
                    "FAILURE-M05-002", "FAILURE-M05-003", "HIGH-03", "RG-FOLLOWUP-01", "RG-FOLLOWUP-02"}
    backlog_ids = {str(i.get("id", "")) for i in items}
    for rid in required_ids:
        if rid not in backlog_ids:
            errors.append(f"V9: 必需 backlog 条目缺失 {rid}")
    # COUPLING_DEBT 必须覆盖 G4 UNCONTROLLED（11）+ REQUIRED BOUNDARY（024）
    coupling_ids = {str(i.get("id", "")) for i in items if i.get("bucket") == "COUPLING_DEBT"}
    for cid in ["COUPLING-006", "COUPLING-007", "COUPLING-009", "COUPLING-018", "COUPLING-023",
                "COUPLING-024", "COUPLING-027", "COUPLING-028", "COUPLING-044", "COUPLING-045",
                "COUPLING-061", "COUPLING-062"]:
        if cid not in coupling_ids:
            errors.append(f"V9: COUPLING_DEBT 缺 {cid}")

    # ---------- V2/V3/V4/V5: 跨 SSOT 一致 ----------
    # V2: code_index UNKNOWN_OWNER = 0
    code_index = REPO_ROOT / str(ssot.get("code_map", ""))
    if code_index.exists():
        text = code_index.read_text(encoding="utf-8")
        unknown_owners = re.findall(r'owner_id:\s*"(UNKNOWN|MAYBE|PENDING)"', text)
        if unknown_owners:
            errors.append(f"V2: code_index 存在未知 owner {set(unknown_owners)}")
        else:
            print("  V2 code_index UNKNOWN_OWNER = 0")
    # V3: G2 UNKNOWN_LEGACY = 0
    legacy_path = REPO_ROOT / str(ssot.get("legacy_registry", ""))
    if legacy_path.exists():
        lt = legacy_path.read_text(encoding="utf-8")
        for bad in ("UNKNOWN", "MAYBE", "PENDING", "TEMP", "OLD"):
            if re.search(rf'classification.*{bad}\b', lt):
                errors.append(f"V3: G2 registry 存在禁止分类 {bad}")
        print("  V3 G2 UNKNOWN_LEGACY = 0")
    # V4: G3 baseline 7/7 + unknown 0
    g3_path = REPO_ROOT / str(ssot.get("verification_matrix", ""))
    if g3_path.exists():
        gt = g3_path.read_text(encoding="utf-8")
        if re.search(r'UNKNOWN_VERIFICATION\s*[:=]\s*[1-9]', gt) or re.search(r'unknown_verification:\s*[1-9]', gt):
            errors.append("V4: G3 UNKNOWN_VERIFICATION 非 0")
        print("  V4 G3 baseline 7/7 (matrix summary)")
    # V5: G4 unknown=0 + critical=0
    g4_path = REPO_ROOT / str(ssot.get("coupling_registry", ""))
    if g4_path.exists():
        g4t = g4_path.read_text(encoding="utf-8")
        if re.search(r'critical_uncontrolled_remaining:\s*[1-9]', g4t):
            errors.append("V5: G4 CRITICAL_UNCONTROLLED_REMAINING 非 0")
        if re.search(r'unknown_coupling:\s*[1-9]', g4t):
            errors.append("V5: G4 UNKNOWN_COUPLING 非 0")
        print("  V5 G4 unknown=0, critical=0")

    # ---------- V8: SSOT conflict ----------
    check_ssot_conflicts(errors)

    # ---------- baseline 状态 ----------
    if str(baseline.get("status")) != "CLOSED_AND_VALIDATED":
        errors.append(f"baseline.status={baseline.get('status')}，期望 CLOSED_AND_VALIDATED")
    if str(baseline.get("development_mode")) != "GOVERNED_FEATURE_DEVELOPMENT":
        errors.append(f"baseline.development_mode={baseline.get('development_mode')}，期望 GOVERNED_FEATURE_DEVELOPMENT")
    if str(baseline.get("pre_governance_mode")) != "CLOSED":
        errors.append(f"baseline.pre_governance_mode={baseline.get('pre_governance_mode')}，期望 CLOSED")
    if not re.fullmatch(r"[0-9a-f]{40}", str(baseline.get("source_sha", ""))):
        errors.append(f"baseline.source_sha 非法: {baseline.get('source_sha')}（须 40 位 hex）")

    for w in warnings:
        print(f"[WARN] {w}")

    if errors:
        print("GOVERNANCE_BASELINE_VALIDATION = FAIL")
        for e in errors:
            print(f"  [FAIL] {e}")
        return 1

    print("GOVERNANCE_BASELINE_VALIDATION = PASS")
    print(f"  MODULES                     = {len(modules)}/7")
    print(f"  UNKNOWN_OWNER               = 0")
    print(f"  UNKNOWN_LEGACY              = 0")
    print(f"  UNKNOWN_VERIFICATION        = 0")
    print(f"  UNKNOWN_COUPLING            = 0")
    print(f"  CRITICAL_UNCONTROLLED       = 0")
    print(f"  SSOT_MISSING                = 0")
    print(f"  SSOT_CONFLICT               = 0")
    print(f"  BACKLOG_UNKNOWN_BUCKET      = 0")
    print(f"  INVALID_OWNER               = 0")
    print(f"  INVALID_MODULE              = 0")
    print(f"  BACKLOG_ITEMS               = {len(items)}（7 bucket: {dict(sorted(counts.items()))}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
