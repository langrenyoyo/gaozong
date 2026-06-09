"""初始化数据库：创建表结构 + 插入默认配置"""

import sys
import os

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine, Base, SessionLocal
from app.models import CheckConfig
from app.config import DEFAULT_CONFIGS


def init_db():
    # 创建所有表
    Base.metadata.create_all(bind=engine)
    print("数据库表创建完成")

    # 插入默认配置
    db = SessionLocal()
    try:
        for key, value in DEFAULT_CONFIGS.items():
            existing = db.query(CheckConfig).filter(CheckConfig.config_key == key).first()
            if not existing:
                cfg = CheckConfig(
                    config_key=key,
                    config_value=value,
                    description=f"默认配置: {key}",
                )
                db.add(cfg)
                print(f"  插入配置: {key} = {value}")
        db.commit()
        print("默认配置插入完成")
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
    print("\n数据库初始化完成！")
