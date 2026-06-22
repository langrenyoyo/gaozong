"""AI小高微信助手独立服务入口。"""

from packages.common.capability import create_capability_app

from apps.wechat_assistant.router import router
from apps.wechat_assistant.service import META


def create_app():
    """创建AI小高微信助手能力服务。"""
    return create_capability_app(META, router)


app = create_app()
