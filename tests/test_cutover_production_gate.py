"""production cutover apply 放行机制测试。

P3-E-9100-PRODUCTION-RELEASE-PACKAGE-1 / §9。
APP_ENV=production 时 --apply 需 PROD_CUTOVER_APPROVER/OPERATOR/TICKET 三变量齐全
+ 审批人 ≠ 执行人；禁止修改 APP_ENV=development 绕过。9000/9100 同款逻辑参数化。
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(script_name: str):
    script = ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(script.stem, script)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # dataclass 类型解析依赖 sys.modules 注册（同 test_cutover_sqlite_to_postgres_migration 模式）
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCRIPTS = [
    "migrate_9000_sqlite_to_postgres_cutover.py",
    "migrate_9100_sqlite_to_postgres_cutover.py",
]


def _make_args(module, apply=True):
    """构造合法 Namespace（tables 用脚本第一张表确保 parse_tables 通过）。"""
    return argparse.Namespace(apply=apply, yes=apply, tables=module.CUTOVER_TABLES[0])


def _smoke_url(module):
    """合法 SMOKE_DATABASE_URL：host=localhost（在 ALLOWED_APPLY_HOSTS）+ 库名=TARGET。"""
    return f"postgresql+psycopg://u:p@localhost/{module.TARGET_DATABASE_NAME}"


@pytest.mark.parametrize("script_name", SCRIPTS)
def test_production_apply_rejected_without_approval_vars(script_name):
    """APP_ENV=production + apply 缺三变量 → 拒绝（提示 PROD_CUTOVER_*）。"""
    module = _load(script_name)
    with pytest.raises(module.MigrationConfigurationError, match="PROD_CUTOVER"):
        module.validate_args(_make_args(module), env={"APP_ENV": "production"})


@pytest.mark.parametrize("script_name", SCRIPTS)
def test_production_apply_rejected_when_approver_equals_operator(script_name):
    """APP_ENV=production + 审批人=执行人 → 拒绝（职责分离）。"""
    module = _load(script_name)
    env = {
        "APP_ENV": "production",
        "PROD_CUTOVER_APPROVER": "Waston",
        "PROD_CUTOVER_OPERATOR": "Waston",
        "PROD_CUTOVER_TICKET": "T-001",
    }
    with pytest.raises(module.MigrationConfigurationError, match="审批人不得与执行人相同"):
        module.validate_args(_make_args(module), env=env)


@pytest.mark.parametrize("script_name", SCRIPTS)
def test_production_apply_passes_with_three_vars_and_split_roles(script_name):
    """APP_ENV=production + 三变量齐全 + 审批≠执行 → 放行（production 门 + 库名/host 校验都过）。"""
    module = _load(script_name)
    env = {
        "APP_ENV": "production",
        "PROD_CUTOVER_APPROVER": "Waston",
        "PROD_CUTOVER_OPERATOR": "VHwwsf",
        "PROD_CUTOVER_TICKET": "P3-E-9100-PROD-001",
        "SMOKE_DATABASE_URL": _smoke_url(module),
    }
    # 不 raise 即完整放行（production 门 + validate_apply_target 库名/host 校验）
    module.validate_args(_make_args(module), env=env)


@pytest.mark.parametrize("script_name", SCRIPTS)
def test_development_apply_not_blocked_by_production_gate(script_name):
    """APP_ENV=development → 不走 production 门（缺 PROD_CUTOVER_* 不拒绝）。"""
    module = _load(script_name)
    env = {
        "APP_ENV": "development",
        "SMOKE_DATABASE_URL": _smoke_url(module),
    }
    # development 不调 _require_production_cutover_approval，其他校验通过即可
    module.validate_args(_make_args(module), env=env)


def test_production_gate_helper_directly():
    """直接测 helper：三变量齐全 + 审批≠执行 → 不 raise。"""
    module = _load("migrate_9000_sqlite_to_postgres_cutover.py")
    # 缺变量
    with pytest.raises(module.MigrationConfigurationError):
        module._require_production_cutover_approval({})
    # 审批=执行
    with pytest.raises(module.MigrationConfigurationError):
        module._require_production_cutover_approval({
            "PROD_CUTOVER_APPROVER": "X", "PROD_CUTOVER_OPERATOR": "X", "PROD_CUTOVER_TICKET": "T",
        })
    # 合法放行（不 raise）
    module._require_production_cutover_approval({
        "PROD_CUTOVER_APPROVER": "Waston", "PROD_CUTOVER_OPERATOR": "VHwwsf", "PROD_CUTOVER_TICKET": "T",
    })
