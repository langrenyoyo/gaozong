"""前端 Local Agent 地址三层优先级测试。

P3-CONFIG-ENV-DETAILED-CHINESE-DOCUMENTATION-1：
VITE_LOCAL_WECHAT_AGENT_BASE_URL 必须被前端真实读取，不能只是部署约定值。

前端无 vitest/jest 框架，沿用项目既有模式：用 Python 静态读取前端源码，
断言三层优先级的代码结构与顺序正确。

优先级（高 → 低）：
  1. localStorage.local_wechat_agent_url（销售在页面手动设置）
  2. import.meta.env.VITE_LOCAL_WECHAT_AGENT_BASE_URL（Vite 环境变量）
  3. DEFAULT_LOCAL_AGENT_BASE_URL（硬编码 http://127.0.0.1:19000）
"""

from __future__ import annotations

from pathlib import Path

SOURCE = Path("frontend/src/api/localWechatAgent.ts")


def _read() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_vite_variable_is_actually_read():
    """VITE_LOCAL_WECHAT_AGENT_BASE_URL 必须在 localWechatAgent.ts 中被真实读取。"""
    source = _read()
    assert "import.meta.env.VITE_LOCAL_WECHAT_AGENT_BASE_URL" in source, (
        "localWechatAgent.ts 必须读取 import.meta.env.VITE_LOCAL_WECHAT_AGENT_BASE_URL，"
        "否则该模板变量不生效，会误导部署人员"
    )


def test_priority_chain_order():
    """三层优先级顺序：localStorage > VITE 变量 > 硬编码默认值。"""
    source = _read()

    # 定位 LOCAL_AGENT_BASE_URL 定义块
    decl_pos = source.find("export const LOCAL_AGENT_BASE_URL")
    assert decl_pos != -1, "缺 LOCAL_AGENT_BASE_URL 定义"

    block = source[decl_pos:]
    # 取定义块（到下一个分号结束）
    semi = block.find(";")
    assert semi != -1, "LOCAL_AGENT_BASE_URL 定义缺分号结尾"
    block = block[: semi + 1]

    ls_pos = block.find('localStorage.getItem("local_wechat_agent_url")')
    vite_pos = block.find("import.meta.env.VITE_LOCAL_WECHAT_AGENT_BASE_URL")
    default_pos = block.find("DEFAULT_LOCAL_AGENT_BASE_URL")

    assert ls_pos != -1, "缺 localStorage 读取（最高优先级）"
    assert vite_pos != -1, "缺 VITE 变量读取（第二优先级）"
    assert default_pos != -1, "缺 DEFAULT 常量（兜底）"

    # 顺序断言：localStorage 在 VITE 前，VITE 在 DEFAULT 前
    assert ls_pos < vite_pos, (
        "localStorage 必须优先于 VITE 变量：页面手动设置应覆盖环境变量"
    )
    assert vite_pos < default_pos, (
        "VITE 变量必须优先于硬编码默认值：环境变量未配置才回退 127.0.0.1:19000"
    )


def test_priority_chain_uses_or_operator():
    """三层优先级必须用 || 短路连接（前者为空才取后者）。"""
    source = _read()
    decl_pos = source.find("export const LOCAL_AGENT_BASE_URL")
    block = source[decl_pos : source.find(";", decl_pos) + 1]

    # localStorage || VITE || DEFAULT 的 || 出现次数应为 2
    assert block.count("||") >= 2, (
        f"三层优先级应用 || 短路连接，实际 || 次数={block.count('||')}"
    )
