"""全局热键监听模块

P8-4：注册 Windows 全局快捷键 Alt+Q，按下后触发紧急停止。

实现方式：
  - 使用 ctypes 调用 RegisterHotKey / UnregisterHotKey
  - 后台线程 GetMessageW 循环等待热键消息
  - 收到后调用 automation_control.request_emergency_stop()
  - 无新增第三方依赖

线程安全：
  - 防重入：_registered 标志
  - daemon 线程，应用退出时自动终止
  - shutdown 时主动 UnregisterHotKey

仅 Windows 启用，Linux/Mac 跳过。
"""

import logging
import platform
import threading

logger = logging.getLogger(__name__)

# Windows 专用
_is_windows = platform.system() == "Windows"

# 模块状态
_registered = False
_hotkey_thread = None


def start_hotkey_listener():
    """启动 Alt+Q 热键监听（仅 Windows）"""
    global _registered, _hotkey_thread

    if not _is_windows:
        logger.info("非 Windows 系统，跳过热键注册")
        return

    if _registered:
        logger.info("热键已注册，跳过重复启动")
        return

    try:
        import ctypes
        import ctypes.wintypes

        # 注册 Alt+Q
        MOD_ALT = 0x0001
        VK_Q = 0x51
        HOTKEY_ID = 0x0001

        result = ctypes.windll.user32.RegisterHotKey(
            None,  # 任何窗口
            HOTKEY_ID,
            MOD_ALT,
            VK_Q,
        )

        if not result:
            logger.warning("RegisterHotKey Alt+Q 失败（可能被其他程序占用），退化为仅 API 停止")
            return

        _registered = True
        logger.info("✅ Alt+Q 全局热键已注册")

        def _listener():
            """后台线程：等待热键消息"""
            import ctypes
            msg = ctypes.wintypes.MSG()
            while _registered:
                # GetMessageW 阻塞等待
                ret = ctypes.windll.user32.GetMessageW(
                    ctypes.byref(msg), None, 0x0312, 0x0312  # WM_HOTKEY = 0x0312
                )
                if ret == 0 or ret == -1:
                    break
                if msg.message == 0x0312 and msg.wParam == HOTKEY_ID:
                    logger.warning("⚠️ Alt+Q 被按下，触发紧急停止")
                    from app.services.automation_control import request_emergency_stop
                    request_emergency_stop("Alt+Q pressed")

        _hotkey_thread = threading.Thread(
            target=_listener,
            daemon=True,
            name="hotkey-listener",
        )
        _hotkey_thread.start()

    except Exception as e:
        logger.error("热键注册异常: %s", e)


def stop_hotkey_listener():
    """停止热键监听，释放注册"""
    global _registered

    if not _registered:
        return

    _registered = False

    if not _is_windows:
        return

    try:
        import ctypes
        HOTKEY_ID = 0x0001
        ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
        logger.info("Alt+Q 热键已释放")
    except Exception as e:
        logger.error("热键释放异常: %s", e)
