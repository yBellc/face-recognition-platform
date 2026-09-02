"""数据库引擎 + Session 依赖"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.config import get_settings

# 检测 psycopg 是否可用
try:
    import psycopg  # noqa: F401
    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False

# SQLite fallback 路径
_SQLITE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "face_recog.db"


def new_engine(settings=None):
    settings = settings or get_settings()
    if not HAS_PSYCOPG:
        if settings.environment.lower() == "production":
            raise RuntimeError("生产环境必须安装 psycopg 并使用 PostgreSQL，禁止自动退化到 SQLite")
        # psycopg 未安装 → 退化为 SQLite，保证 API 可启动
        _SQLITE_PATH.parent.mkdir(exist_ok=True)
        url = f"sqlite:///{_SQLITE_PATH}"
        print(f"[DB] psycopg 未安装，退化为 SQLite: {url}")
        return create_engine(url, future=True, echo=False, connect_args={"check_same_thread": False})
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
        echo=False,
    )


def new_session_factory(engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


_engine = None
_session_factory = None


def _ensure():
    global _engine, _session_factory
    if _engine is None:
        _engine = new_engine()
        _session_factory = new_session_factory(_engine)
        # SQLite 模式下自动建表
        if not HAS_PSYCOPG:
            from app.db.models import Base
            Base.metadata.create_all(_engine)
            print(f"[DB] SQLite 表已自动创建")


def get_session() -> Generator[Session, None, None]:
    _ensure()
    sess: Session = _session_factory()
    try:
        yield sess
    finally:
        sess.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    _ensure()
    sess: Session = _session_factory()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()
