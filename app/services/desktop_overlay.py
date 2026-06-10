"""桌面提示浮层

P8-4：使用 tkinter 创建置顶小窗口，显示自动化运行状态。

显示逻辑：
  - 正常运行：「🤖 自动化运行中 — 按 Alt+Q 紧急停止」
  - 已停止：  「⛔ 自动化已停止 — 请在前端点击恢复」
  - 动作执行中（P0-2）：「⏳ 正在执行微信自动化，请勿移动鼠标 — Alt+Q 停止」

位置：屏幕顶部居中，宽 360px 高 36px，半透明背景。
仅 Windows + tkinter 可用时启用。
"""

import logging
import platform
import threading

logger = logging.getLogger(__name__)

_is_windows = platform.system() == "Windows"
_overlay_window = None
_overlay_thread = None


def start_desktop_overlay():
    """启动桌面提示浮层（仅 Windows + tkinter 可用时）"""
    global _overlay_thread

    if not _is_windows:
        logger.info("非 Windows 系统，跳过桌面提示")
        return

    try:
        import tkinter as _tk
    except ImportError:
        logger.warning("tkinter 不可用，跳过桌面提示")
        return

    def _run_overlay():
        """在独立线程中运行 tkinter 主循环"""
        global _overlay_window
        try:
            import tkinter as tk

            root = tk.Tk()
            root.title("AutoWeChat Status")
            root.overrideredirect(True)  # 无边框

            # 居中在屏幕顶部
            width = 360
            height = 36
            screen_w = root.winfo_screenwidth()
            pos_x = (screen_w - width) // 2
            pos_y = 4

            root.geometry(f"{width}x{height}+{pos_x}+{pos_y}")
            root.attributes("-topmost", True)
            # 半透明（Windows only）
            try:
                root.attributes("-alpha", 0.85)
            except Exception:
                pass

            label = tk.Label(
                root,
                text="🤖 自动化运行中 — 按 Alt+Q 紧急停止",
                fg="white",
                bg="#1e40af",  # 深蓝色
                font=("Microsoft YaHei UI", 10, "bold"),
                anchor="center",
            )
            label.pack(fill="both", expand=True)

            _overlay_window = root

            # 定时刷新状态（每 3 秒）
            def _refresh():
                if not root.winfo_exists():
                    return
                try:
                    from app.services.automation_control import get_automation_status
                    status = get_automation_status()
                    if status.get("emergency_stopped"):
                        label.config(
                            text="⛔ 自动化已停止 — 请在前端点击恢复",
                            bg="#dc2626",  # 红色
                        )
                        root.attributes("-alpha", 0.95)
                    elif status.get("action_in_progress"):
                        label.config(
                            text="⏳ 正在执行微信自动化，请勿移动鼠标 — Alt+Q 停止",
                            bg="#d97706",  # 琥珀色
                        )
                        root.attributes("-alpha", 0.95)
                    else:
                        label.config(
                            text="🤖 自动化运行中 — 按 Alt+Q 紧急停止",
                            bg="#1e40af",
                        )
                        root.attributes("-alpha", 0.85)
                except Exception:
                    pass
                root.after(3000, _refresh)

            root.after(1000, _refresh)
            root.mainloop()

        except Exception as e:
            logger.error("桌面提示浮层异常: %s", e)

    _overlay_thread = threading.Thread(
        target=_run_overlay,
        daemon=True,
        name="desktop-overlay",
    )
    _overlay_thread.start()
    logger.info("桌面提示浮层已启动")


def stop_desktop_overlay():
    """关闭桌面提示浮层"""
    global _overlay_window

    if _overlay_window is not None:
        try:
            _overlay_window.destroy()
        except Exception:
            pass
        _overlay_window = None
    logger.info("桌面提示浮层已关闭")
