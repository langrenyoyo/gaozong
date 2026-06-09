"""项目配置"""

import os

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据库路径
DATABASE_DIR = os.path.join(BASE_DIR, "data")
DATABASE_PATH = os.path.join(DATABASE_DIR, "auto_wechat.db")

# 数据库连接 URL
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# 服务端口
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 9000

# 默认检测配置
DEFAULT_CONFIGS = {
    "reply_deadline_minutes": "30",
    "check_interval_minutes": "5",
    "effective_reply_min_length": "2",
    "effective_keywords": "收到,已添加,已联系,已通过,通过了,OK,好的,正在处理",
    "invalid_keywords": "不知道,不清楚,等下再说,没空,无法处理",
}
