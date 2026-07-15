"""测试全局 fixture：算力上报默认禁用 + 网络哨兵（Phase 10 §0.2 FIX2）。

背景：默认环境（本机 .env / .env.lan.local）可能配置 COMPUTE_INTERNAL_TOKEN +
AUTO_WECHAT_9000_BASE_URL，使 ComputeUsageClient 在测试中误启用并发起真实网络请求
（目标主机不存在，URLError 被 report_usage 吞掉，测试假绿）。独立探针在代理+回访
套件测到 42 次被吞掉的上报尝试。

本 autouse fixture 在每个测试前：
1. 删除算力上报相关环境变量，确保 ComputeUsageClient().config 默认 disabled；
2. 安装网络哨兵：compute_usage_client 的 urlopen 被调用即抛 AssertionError，
   强制"零真实网络尝试"——启用态上报测试必须显式注入 config + 局部 fake_urlopen 覆盖。

窄影响：只作用于算力上报路径（compute_usage_client.urlopen + 两个环境变量），
对不涉及算力上报的测试零影响。启用态测试（test_compute_usage_client /
test_phase10_compute_metering）用局部 monkeypatch.setattr fake_urlopen 覆盖哨兵
（pytest monkeypatch LIFO，后设置生效、测试结束按序恢复）。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_compute_usage_network(monkeypatch: pytest.MonkeyPatch):
    """算力上报默认禁用 + 网络哨兵：测试零真实网络尝试。"""

    # 1. 清理算力上报环境变量，确保 ComputeUsageClient 默认 disabled
    monkeypatch.delenv("COMPUTE_INTERNAL_TOKEN", raising=False)
    monkeypatch.delenv("AUTO_WECHAT_9000_BASE_URL", raising=False)

    # 2. 网络哨兵：urlopen 被调用即失败，强制启用态测试显式注入 fake
    def _sentinel_urlopen(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError(
            "测试不得对算力上报发起真实网络请求；"
            "启用态测试须显式注入 config + 局部 fake_urlopen 覆盖哨兵"
        )

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.compute_usage_client.urllib_request.urlopen",
        _sentinel_urlopen,
    )
