"""KernelMode 枚举与 KernelRuntimeSettings（P0-B）。

9100 统一配置加载、统一校验，lifespan 与运行时使用同一设置来源。
非法组合启动失败（raise），不静默自动关闭。
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from enum import Enum


class KernelMode(str, Enum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    ENABLED = "enabled"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, str(default)).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, str(default)).strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise RuntimeError(f"config_invalid: {name}={raw!r} 不是有效数字")
    if math.isnan(value) or math.isinf(value):
        raise RuntimeError(f"config_invalid: {name}={raw!r} 必须是有限数")
    return value


@dataclass(frozen=True)
class KernelRuntimeSettings:
    """统一运行时配置。"""

    mode: KernelMode
    contact_request_policy_enabled: bool
    shadow_sample_rate: float
    shadow_hmac_secret: str  # SHADOW 模式必填非空，其他模式可为空


def load_kernel_runtime_settings() -> KernelRuntimeSettings:
    """解析 env 为 KernelRuntimeSettings，非法组合 raise。

    解析规则：
    - kernel=false, shadow=false → LEGACY
    - kernel=true,  shadow=true  → SHADOW
    - kernel=true,  shadow=false → ENABLED
    - kernel=false, shadow=true  → 启动失败
    - contact_request_policy=true（P0-B）→ 启动失败
    - SHADOW 模式 shadow_hmac_secret 为空 → 启动失败
    """
    kernel_enabled = _env_bool("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", False)
    shadow = _env_bool("DOUYIN_REPLY_KERNEL_SHADOW", False)
    contact_request_policy = _env_bool("DOUYIN_CONTACT_REQUEST_POLICY_ENABLED", False)
    sample_rate = _env_float("DOUYIN_REPLY_KERNEL_SHADOW_SAMPLE_RATE", 0.1)
    shadow_hmac_secret = os.environ.get("DOUYIN_REPLY_KERNEL_SHADOW_HMAC_SECRET", "").strip()

    # 采样率范围校验
    if sample_rate < 0.0 or sample_rate > 1.0:
        raise RuntimeError(
            f"config_invalid: DOUYIN_REPLY_KERNEL_SHADOW_SAMPLE_RATE={sample_rate} 越界，需 [0.0, 1.0]"
        )

    # 非法组合：kernel=false + shadow=true
    if not kernel_enabled and shadow:
        raise RuntimeError(
            "config_invalid: DOUYIN_REPLY_KERNEL_SHADOW=true 需要 DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED=true"
        )

    # P0-B：contact_request_policy 强制关闭
    if contact_request_policy:
        raise RuntimeError(
            "config_invalid: DOUYIN_CONTACT_REQUEST_POLICY_ENABLED=true 在 P0-B 阶段不允许启用"
        )

    # 解析模式
    if not kernel_enabled and not shadow:
        mode = KernelMode.LEGACY
    elif kernel_enabled and shadow:
        mode = KernelMode.SHADOW
    elif kernel_enabled and not shadow:
        mode = KernelMode.ENABLED
    else:
        # 逻辑上不可达（前面已拦截 kernel=false + shadow=true）
        raise RuntimeError("config_invalid: 不可达的 KernelMode 组合")

    # SHADOW 模式必须有专用 HMAC 密钥（不复用 LLM API Key，不用固定默认，不静默生成随机）
    if mode == KernelMode.SHADOW and not shadow_hmac_secret:
        raise RuntimeError(
            "config_invalid: DOUYIN_REPLY_KERNEL_SHADOW_HMAC_SECRET 在 SHADOW 模式必须为非空有效字符串"
        )

    return KernelRuntimeSettings(
        mode=mode,
        contact_request_policy_enabled=contact_request_policy,
        shadow_sample_rate=sample_rate,
        shadow_hmac_secret=shadow_hmac_secret,
    )


# 模块级缓存（启动时加载一次，运行时复用同一设置来源）
_cached_settings: KernelRuntimeSettings | None = None


def get_kernel_runtime_settings() -> KernelRuntimeSettings:
    """获取缓存的运行时配置（启动时加载，运行时复用）。"""
    global _cached_settings
    if _cached_settings is None:
        _cached_settings = load_kernel_runtime_settings()
    return _cached_settings


def reset_kernel_runtime_settings() -> None:
    """重置缓存（测试用，允许重新读取 env）。"""
    global _cached_settings
    _cached_settings = None
