"""微信 UI 自动化异常定义"""


class WechatUIError(Exception):
    """微信 UI 操作基础异常"""
    pass


class WechatNotFoundError(WechatUIError):
    """微信窗口未找到或未启动"""
    pass


class ChatWindowNotFoundError(WechatUIError):
    """没有打开的聊天窗口或消息列表不可读"""
    pass


class MessageReadError(WechatUIError):
    """消息读取失败"""
    pass


class WechatTimeoutError(WechatUIError):
    """UI 操作超时"""
    pass
