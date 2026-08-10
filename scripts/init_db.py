"""初始化数据库：创建表结构 + 插入默认配置

后端边界（DB-BL-2D prevention closure）：
  - SQLite：保留 create_all + seed DEFAULT_CONFIGS 合法行为（开发态）。
  - PostgreSQL：**拒绝** create_all——PostgreSQL schema 必须由 Alembic 创建/演进
    （MODEL A，CLAUDE.md 硬约束 #2）。本守卫与 app.main.ensure_runtime_schema() 的
    PG startup_skip_create_all 语义对齐，形成 runtime + bootstrap 工具双重拦截。

ponytail: ceiling — 本守卫只判定 backend 并在 PG 下 sys.exit(1)；不重构整个
bootstrap/seed 系统，不引入新依赖。
"""

import sys
import os

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine, Base, SessionLocal, get_database_runtime
from app.models import CheckConfig
from app.config import DEFAULT_CONFIGS


def init_db():
    runtime = get_database_runtime()

    # PostgreSQL 守卫：禁止 create_all（schema 须由 Alembic 创建/演进）
    if runtime.backend == "postgresql":
        print(
            "ERROR: 检测到 PostgreSQL 后端，init_db.py 拒绝执行 create_all。\n"
            "PostgreSQL schema must be created/evolved by Alembic.\n"
            "请改用: alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade head",
            file=sys.stderr,
        )
        sys.exit(1)

    if runtime.backend != "sqlite":
        print(f"ERROR: 不支持的数据库后端: {runtime.backend}", file=sys.stderr)
        sys.exit(1)

    # SQLite：保留 create_all + seed 合法行为
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
