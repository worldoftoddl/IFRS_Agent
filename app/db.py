"""PostgreSQL+pgvector 커넥션 풀 관리."""

import os

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


def _get_db_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://kifrs:kifrs@localhost:5432/kifrs")


def get_pool() -> ConnectionPool:
    """싱글턴 커넥션 풀 반환."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=_get_db_url(),
            min_size=2,
            max_size=10,
            kwargs={"autocommit": True},
            open=True,
        )
    return _pool


def get_connection() -> psycopg.Connection:
    """풀에서 커넥션을 꺼내고 pgvector 타입을 등록한 뒤 반환."""
    pool = get_pool()
    conn = pool.getconn()
    register_vector(conn)
    return conn


def release_connection(conn: psycopg.Connection) -> None:
    """커넥션을 풀에 반환."""
    get_pool().putconn(conn)
