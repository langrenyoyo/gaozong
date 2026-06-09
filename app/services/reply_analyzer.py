"""回复有效性分析服务"""

from app.models import CheckConfig


def get_config_value(db, key: str, default: str = "") -> str:
    """从配置表读取值"""
    cfg = db.query(CheckConfig).filter(CheckConfig.config_key == key).first()
    return cfg.config_value if cfg else default


def analyze_reply(db, reply_content: str) -> tuple[bool, str]:
    """
    分析回复是否有效。

    返回: (is_effective, reason)
    """
    if not reply_content or not reply_content.strip():
        return False, "回复内容为空"

    # 读取配置
    min_length_str = get_config_value(db, "effective_reply_min_length", "2")
    try:
        min_length = int(min_length_str)
    except ValueError:
        min_length = 2

    effective_kw_str = get_config_value(db, "effective_keywords",
                                         "收到,已添加,已联系,已通过,通过了,OK,好的,正在处理")
    invalid_kw_str = get_config_value(db, "invalid_keywords",
                                       "不知道,不清楚,等下再说,没空,无法处理")

    effective_keywords = [k.strip() for k in effective_kw_str.split(",") if k.strip()]
    invalid_keywords = [k.strip() for k in invalid_kw_str.split(",") if k.strip()]

    content = reply_content.strip()

    # 先检查无效关键词
    for kw in invalid_keywords:
        if kw and kw in content:
            return False, f"命中无效关键词: {kw}"

    # 检查有效关键词
    for kw in effective_keywords:
        if kw and kw in content:
            # 同时检查长度
            if len(content) >= min_length:
                return True, f"命中有效关键词: {kw}，回复长度 {len(content)} >= {min_length}"
            else:
                return False, f"命中有效关键词但长度不足: {len(content)} < {min_length}"

    # 没命中任何关键词，按长度判断
    if len(content) >= min_length:
        return True, f"回复长度 {len(content)} >= {min_length}，默认有效"

    return False, f"回复长度 {len(content)} < {min_length}，未命中有效关键词"
