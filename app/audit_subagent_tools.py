"""Audit-standard retrieval tools for the audit-retrieval-distiller subagent.

The audit pipeline uses dense summary search, dense passage search, and
Cohere reranker to sort the final evidence set.
"""

import os
import re
from dataclasses import dataclass

from langchain_core.tools import tool
from psycopg import sql

from app.db import get_connection
from app.embedder import embed_query

_AUDIT_SCHEMA_ENV = "AUDIT_SCHEMA"
_DEFAULT_AUDIT_SCHEMA = "audit"
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_AUDIT_STANDARD_ID_RE = re.compile(r"^(ASSR|FRMK|ISA|ISQM)-\d+$")
_SIMILARITY_THRESHOLD = 0.2
_CANDIDATE_STANDARDS = 5
_PASSAGE_POOL_SIZE = 20
_RERANK_TOP_N = 10


@dataclass(frozen=True)
class _AuditRow:
    chunk_id: str
    standard_id: str
    title: str
    para_number: str | None
    component: str
    section_title: str | None
    content_markdown: str
    score: float


def _audit_schema() -> str:
    schema = os.environ.get(_AUDIT_SCHEMA_ENV, _DEFAULT_AUDIT_SCHEMA)
    if not _IDENT_RE.match(schema):
        raise RuntimeError(f"{_AUDIT_SCHEMA_ENV} 값이 유효한 PostgreSQL 스키마명이 아닙니다.")
    return schema


def _table(name: str) -> sql.Identifier:
    return sql.Identifier(_audit_schema(), name)


def _valid_audit_standard_id(standard_id: str) -> bool:
    return bool(_AUDIT_STANDARD_ID_RE.match(standard_id))


def _row_to_dict(row: _AuditRow) -> dict:
    return {
        "chunk_id": row.chunk_id,
        "standard_id": row.standard_id,
        "title": row.title,
        "para_number": row.para_number,
        "component": row.component,
        "section_title": row.section_title,
        "content_markdown": row.content_markdown,
        "score": row.score,
    }


def _paragraph_candidates(para_number: str) -> list[str]:
    stripped = para_number.strip()
    if not stripped:
        return []
    candidates = [stripped]
    without_dot = stripped.rstrip(".")
    if without_dot and without_dot not in candidates:
        candidates.append(without_dot)
    with_dot = f"{without_dot}."
    if without_dot and with_dot not in candidates:
        candidates.append(with_dot)
    return candidates


def _identify_audit_standards(
    query_emb: list[float],
    top_k: int = _CANDIDATE_STANDARDS,
) -> list[tuple]:
    with get_connection() as conn:
        return conn.execute(
            sql.SQL(
                """
                SELECT standard_id, title,
                       1 - (embedding <=> %(emb)s::vector) AS similarity
                FROM {}
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %(emb)s::vector
                LIMIT %(top_k)s
                """
            ).format(_table("standard_summaries")),
            {"emb": query_emb, "top_k": top_k},
        ).fetchall()


def _search_audit_dense(
    query_emb: list[float],
    standard_ids: list[str],
    *,
    top_k: int = _PASSAGE_POOL_SIZE,
) -> list[_AuditRow]:
    if not standard_ids:
        return []

    with get_connection() as conn:
        rows = conn.execute(
            sql.SQL(
                """
                SELECT c.chunk_id, c.standard_id, s.title, c.para_number,
                       c.component, c.section_title, c.content_markdown,
                       1 - (c.embedding <=> %(emb)s::vector) AS similarity
                FROM {} c
                JOIN {} s ON s.standard_id = c.standard_id
                WHERE c.standard_id = ANY(%(standard_ids)s)
                  AND c.embedding IS NOT NULL
                ORDER BY c.embedding <=> %(emb)s::vector
                LIMIT %(top_k)s
                """
            ).format(_table("chunks"), _table("standards")),
            {"emb": query_emb, "standard_ids": standard_ids, "top_k": top_k},
        ).fetchall()

    return [_AuditRow(*row[:7], float(row[7])) for row in rows]


def _lookup_audit_rows(standard_id: str, para_number: str) -> list[_AuditRow]:
    if not _valid_audit_standard_id(standard_id):
        return []

    candidates = _paragraph_candidates(para_number)
    if not candidates:
        return []

    with get_connection() as conn:
        rows = conn.execute(
            sql.SQL(
                """
                SELECT c.chunk_id, c.standard_id, s.title, c.para_number,
                       c.component, c.section_title, c.content_markdown,
                       1.0 AS score
                FROM {} c
                JOIN {} s ON s.standard_id = c.standard_id
                WHERE c.standard_id = %(standard_id)s
                  AND c.para_number = ANY(%(para_numbers)s)
                ORDER BY c.authority, c.chunk_id
                LIMIT 5
                """
            ).format(_table("chunks"), _table("standards")),
            {"standard_id": standard_id, "para_numbers": candidates},
        ).fetchall()

    return [_AuditRow(*row[:7], float(row[7])) for row in rows]


@tool
def retrieve_audit_standards(query: str) -> list[dict]:
    """감사기준에서 관련 문단을 Dense 검색 + Reranker로 검색합니다.

    감사기준 질문에서는 이 도구를 가장 먼저 1회만 호출하세요.

    Args:
        query: 검색할 감사기준 질문
    """
    query_emb = embed_query(query)
    standards = _identify_audit_standards(query_emb)
    if not standards or standards[0][2] < _SIMILARITY_THRESHOLD:
        return []

    standard_ids = [row[0] for row in standards if row[2] >= _SIMILARITY_THRESHOLD]
    rows = _search_audit_dense(query_emb, standard_ids, top_k=_PASSAGE_POOL_SIZE)
    if not rows:
        return []

    from app.reranker import rerank

    docs = [row.content_markdown for row in rows]
    reranked_indices = rerank(query, docs, top_n=_RERANK_TOP_N)
    return [_row_to_dict(rows[index]) for index in reranked_indices]


@tool
def lookup_audit_paragraph(standard_id: str, para_number: str) -> list[dict]:
    """특정 감사기준의 특정 문단을 직접 조회합니다.

    이미 확인된 문단 번호의 원문을 정확히 가져올 때 사용합니다.

    Args:
        standard_id: 감사기준 ID (예: "ISA-320", "ISQM-1")
        para_number: 문단 번호 (예: "9", "9.", "A13.")
    """
    return [_row_to_dict(row) for row in _lookup_audit_rows(standard_id, para_number)]


@tool
def search_single_audit_standard(query: str, standard_id: str) -> list[dict]:
    """단일 감사기준 내에서 Dense 벡터 검색만 수행합니다.

    이미 기준서가 확정된 뒤 보강 문단을 찾을 때 사용합니다. reranker는 사용하지 않습니다.

    Args:
        query: 검색 질문
        standard_id: 대상 감사기준 ID (예: "ISA-320")
    """
    if not _valid_audit_standard_id(standard_id):
        return []

    query_emb = embed_query(query)
    rows = _search_audit_dense(query_emb, [standard_id], top_k=10)
    return [_row_to_dict(row) for row in rows]
