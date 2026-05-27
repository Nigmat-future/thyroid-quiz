"""SQLAlchemy 引擎、Session、Base。整个应用通过这里拿数据库连接。"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


def _build_engine():
    """根据 DATABASE_URL 构造 engine；SQLite 需要 check_same_thread=False。"""
    url = settings.database_url
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(
        url,
        connect_args=connect_args,
        echo=False,
        future=True,
    )


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型继承此基类。"""


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每次请求拿一个 Session，结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
