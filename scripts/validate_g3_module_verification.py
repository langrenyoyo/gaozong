#!/usr/bin/env python3
"""G3 Seven-Module Verification 机器验收校验器（G3-SEVEN-MODULE-VERIFICATION-1）。

只读校验 docs/architecture/verification/G3_MODULE_VERIFICATION_MATRIX.yaml（唯一 SSOT），
验证任务书 §24/§35 全部硬性标准：
  1. 7 个 module_id 唯一且完整（M01~M07 全部存在）
  2. 每个模块 key_chain 非空
  3. 每个模块至少一个 machine_tests 或明确 manual protocol
  4. success_criteria / failure_criteria 非空
  5. current_result 属于合法枚举（PASS/KNOWN_FAIL/BASELINE_ONLY/ENV_CONSTRAINED）
  6. UNKNOWN_VERIFICATION = 0（无 UNKNOWN/TBD/TODO/PENDING_REVIEW/MAYBE）
  7. 所有测试路径存在（仓库内文件）
  8. 所有 CHAIN 路径存在
  9. module owner 与 G1 一致（对照 code_index.yaml 中模块代表文件 owner）
  10. known Legacy dependency 可在 G2 registry（LEGACY_REGISTER.md）找到
  11. MODULE_KEY_CHAIN_BASELINE = 7/7

用法：
  python scripts/validate_g3_module_verification.py
退出码：0 = 全部通过；1 = 存在失败项。

本脚本是治理元数据校验器，不修改任何文件。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

VALID_RESULTS = {"PASS", "KNOWN_FAIL", "BASELINE_ONLY", "ENV_CONSTRAINED"}
FORBIDDEN_RESULTS = {"UNKNOWN", "TBD", "TODO", "PENDING_REVIEW", "MAYBE"}
MODULES = [f"M0{i}" for i in range(1, 8)]


def load_yaml(path: Path) -> dict:
    """加载 YAML（优先 PyYAML，缺失时用最小解析器兜底）。"""
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        raise ValueError("YAML 根必须是 mapping")
    except ImportError:
        return _minimal_yaml(path.read_text(encoding="utf-8"))


def _minimal_yaml(text: str) -> dict:
    """极简 YAML 解析：仅支持本矩阵使用的缩进结构（无 PyYAML 时的兜底）。"""
    import json

    # 兜底方案：如果 PyYAML 不可用，用 JSON-ish 转换不可行，这里直接报错要求 PyYAML
    raise RuntimeError("需要 PyYAML：pip install pyyaml（或提供纯标准库解析）")


def load_g2_legacy_ids(registry_path: Path) -> set[str]:
    """从 G2 registry 提取 legacy_id 集合（## LEGACY-NNN）。"""
    ids: set[str] = set()
    if registry_path.exists():
        for m in re.finditer(r"^##\s+(LEGACY-\d+)", registry_path.read_text(encoding="utf-8"), re.M):
            ids.add(m.group(1))
    return ids


def load_g1_owner(code_index_path: Path) -> dict[str, tuple[str, str]]:
    """从 G1 code_index.yaml 提取 path -> (owner_type, owner_id)。"""
    owners: dict[str, tuple[str, str]] = {}
    if not code_index_path.exists():
        return owners
    cur_path: str | None = None
    cur_type: str | None = None
    cur_id: str | None = None
    for line in code_index_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        m = re.match(r'^path:\s*"([^"]+)"', s)
        if m:
            cur_path = m.group(1)
            cur_type = cur_id = None
            continue
        m = re.match(r'^owner_type:\s*"([^"]+)"', s)
        if m:
            cur_type = m.group(1)
            continue
        m = re.match(r'^owner_id:\s*"?([^"\s]+)"?', s)
        if m and m.group(1) != "null":
            cur_id = m.group(1)
            continue
        if cur_path and cur_type:
            owners.setdefault(cur_path.replace("\\", "/").lower(), (cur_type, cur_id or ""))
    return owners


def main() -> int:
    matrix_path = REPO_ROOT / "docs" / "architecture" / "verification" / "G3_MODULE_VERIFICATION_MATRIX.yaml"
    report_path = REPO_ROOT / "docs" / "architecture" / "verification" / "G3_SEVEN_MODULE_VERIFICATION_REPORT.md"
    registry_path = REPO_ROOT / "docs" / "architecture" / "LEGACY_REGISTER.md"
    code_index_path = REPO_ROOT / "docs" / "architecture" / "code-map" / "code_index.yaml"

    failures: list[str] = []

    def fail(msg: str) -> None:
        failures.append(msg)

    if not matrix_path.exists():
        print(f"FAIL: 矩阵不存在: {matrix_path}")
        return 1

    try:
        data = load_yaml(matrix_path)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: 矩阵 YAML 解析失败: {exc}")
        return 1

    modules = data.get("modules")
    if not isinstance(modules, list) or len(modules) != 7:
        fail(f"modules 必须是 7 个条目的列表，实际 {len(modules) if isinstance(modules, list) else '非列表'}")

    g2_ids = load_g2_legacy_ids(registry_path)
    g1_owners = load_g1_owner(code_index_path)

    module_ids: list[str] = []
    results: dict[str, str] = {}
    for mod in modules:
        if not isinstance(mod, dict):
            fail("模块条目必须是 mapping")
            continue
        mid = mod.get("module_id", "")
        module_ids.append(mid)

        # 1. module_id 合法且唯一
        if mid not in MODULES:
            fail(f"[{mid}] module_id 非法（必须 M01~M07）")
        if module_ids.count(mid) > 1:
            fail(f"[{mid}] module_id 重复")

        # 2. key_chain 非空
        if not str(mod.get("key_chain", "")).strip():
            fail(f"[{mid}] key_chain 为空")

        # 4. success/failure criteria 非空
        if not mod.get("success_criteria"):
            fail(f"[{mid}] success_criteria 为空")
        if not mod.get("failure_criteria"):
            fail(f"[{mid}] failure_criteria 为空")

        # 3. 至少一个 machine_tests 或明确 manual protocol
        machine_tests = mod.get("machine_tests") or []
        manual_checks = mod.get("manual_checks") or []
        if not machine_tests and not manual_checks:
            fail(f"[{mid}] 无 machine_tests 且无 manual_checks")

        # 5/6. current_result 合法且非 UNKNOWN 系
        result = str(mod.get("current_result", "")).strip().upper()
        results[mid] = result
        if result not in VALID_RESULTS:
            fail(f"[{mid}] current_result 非法: {result!r}（合法: {sorted(VALID_RESULTS)}）")
        if result in FORBIDDEN_RESULTS:
            fail(f"[{mid}] current_result 禁止值: {result!r}（UNKNOWN_VERIFICATION 必须为 0）")

        # 7. 所有测试路径存在
        for t in machine_tests:
            path = t.get("path", "") if isinstance(t, dict) else str(t)
            if path and not (REPO_ROOT / path).exists():
                fail(f"[{mid}] machine_tests 路径不存在: {path}")

        # 8. CHAIN 路径存在
        chain = mod.get("chain_path", f"docs/architecture/modules/{mid}/CHAIN.md")
        if chain and not (REPO_ROOT / chain).exists():
            fail(f"[{mid}] CHAIN 路径不存在: {chain}")

        # 9. module owner 与 G1 一致（抽查代表文件）
        rep_files = mod.get("g1_owner_check_files") or []
        for rf in rep_files:
            g1 = g1_owners.get(rf.replace("\\", "/").lower())
            if not g1:
                continue
            g1_type, g1_id = g1
            expected_owner = mod.get("owner", "")
            if g1_type == "MODULE" and g1_id == expected_owner:
                continue
            if g1_type == "PLATFORM" and expected_owner in ("PLATFORM", "PLATFORM-RELEASE"):
                continue
            fail(f"[{mid}] owner 与 G1 冲突: {rf} G1={g1_type}/{g1_id} vs 矩阵 owner={expected_owner}")

        # 10. known legacy 引用可在 G2 registry 找到
        for leg in mod.get("known_legacy_dependencies") or []:
            if leg not in g2_ids:
                fail(f"[{mid}] legacy 引用在 G2 registry 未找到: {leg}")

    # 1. 完整性：M01~M07 全部存在
    missing = [m for m in MODULES if m not in module_ids]
    if missing:
        fail(f"缺少模块: {missing}")

    # 11. key chain baseline
    baseline_modules = [m for m in module_ids if m in MODULES and m not in missing]
    baseline = f"{len(baseline_modules)}/7" if baseline_modules else "0/7"

    # ---- 输出 ----
    print(f"MODULES_TOTAL                = {len(module_ids)}")
    print(f"MODULES_WITH_BASELINE        = {len(set(module_ids) & set(MODULES))}")
    print(f"MODULE_KEY_CHAIN_BASELINE    = {baseline}")
    result_counts: dict[str, int] = {}
    for r in results.values():
        result_counts[r] = result_counts.get(r, 0) + 1
    for r in sorted(VALID_RESULTS):
        print(f"{r:<12} = {result_counts.get(r, 0)}")
    unknown_count = sum(1 for r in results.values() if r in FORBIDDEN_RESULTS)
    print(f"UNKNOWN_VERIFICATION         = {unknown_count}")

    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        print("\nG3_VALIDATION = FAIL")
        return 1

    print("\nG3_VALIDATION = PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
