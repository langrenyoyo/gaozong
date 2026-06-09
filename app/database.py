"""数据库连接和会话管理"""

import os
import logging

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import DATABASE_URL, DATABASE_DIR

logger = logging.getLogger(__name__)

# 确保 data 目录存在
os.makedirs(DATABASE_DIR, exist_ok=True)

# SQLite 多线程安全配置：
# - check_same_thread=False：允许跨线程使用连接
# - timeout=30：写锁等待 30 秒而非立即 SQLITE_BUSY
# - WAL 模式：允许并发读写（读者不阻塞写者，写者不阻塞读者）
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": 30,
    },
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """连接创建时设置 WAL 模式"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 依赖注入：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
