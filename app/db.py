"""PostgreSQL+pgvector 커넥션 풀 관리."""

import os
import threading
from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL 환경변수가 설정되지 않았습니다.")
    return url


def get_pool() -> ConnectionPool:
    """싱글턴 커넥션 풀 반환 (thread-safe)."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ConnectionPool(
                    conninfo=_get_db_url(),
                    min_size=2,
                    max_size=10,
                    kwargs={"autocommit": True},
                    open=True,
                )
    return _pool


@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    """풀에서 커넥션을 꺼내고 pgvector 타입을 등록하여 yield. 자동 반환."""
    with get_pool().connection() as conn:
        register_vector(conn)
        yield conn
