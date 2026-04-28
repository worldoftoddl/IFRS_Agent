"""Audit standard retrieval tools backed by the PostgreSQL ``audit`` schema."""

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
_SIMILARITY_THRESHOLD = 0.2
_CANDIDATE_STANDARDS = 5
_CONTENT_MAX_CHARS = 1200


@dataclass(frozen=True)
class _AuditCandidate:
    standard_id: str
    title: str
    similarity: float


@dataclass(frozen=True)
class _AuditChunk:
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


def _identify_audit_standards(query_emb: list[float]) -> list[_AuditCandidate]:
    with get_connection() as conn:
        rows = conn.execute(
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
            {"emb": query_emb, "top_k": _CANDIDATE_STANDARDS},
        ).fetchall()

    return [_AuditCandidate(row[0], row[1], float(row[2])) for row in rows]


def _search_audit_chunks(
    query_emb: list[float],
    query: str,
    standard_ids: list[str],
    *,
    top_k: int,
) -> list[_AuditChunk]:
    if not standard_ids:
        return []

    pool_size = max(20, top_k * 10)
    with get_connection() as conn:
        rows = conn.execute(
            sql.SQL(
                """
                WITH dense AS (
                    SELECT c.chunk_id, c.standard_id, s.title, c.para_number,
                           c.component, c.section_title, c.content_markdown,
                           ROW_NUMBER() OVER (
                               ORDER BY c.embedding <=> %(emb)s::vector
                           ) AS rank_dense
                    FROM {} c
                    JOIN {} s ON s.standard_id = c.standard_id
                    WHERE c.standard_id = ANY(%(standard_ids)s)
                      AND c.embedding IS NOT NULL
                    ORDER BY c.embedding <=> %(emb)s::vector
                    LIMIT %(pool_size)s
                ),
                bm25 AS (
                    SELECT c.chunk_id, c.standard_id, s.title, c.para_number,
                           c.component, c.section_title, c.content_markdown,
                           ROW_NUMBER() OVER (ORDER BY ts_rank(c.content_tsv, q) DESC) AS rank_bm25
                    FROM {} c
                    JOIN {} s ON s.standard_id = c.standard_id,
                         plainto_tsquery('simple', %(query)s) q
                    WHERE c.standard_id = ANY(%(standard_ids)s)
                      AND c.content_tsv @@ q
                    ORDER BY ts_rank(c.content_tsv, q) DESC
                    LIMIT %(pool_size)s
                )
                SELECT COALESCE(d.chunk_id, b.chunk_id) AS chunk_id,
                       COALESCE(d.standard_id, b.standard_id) AS standard_id,
                       COALESCE(d.title, b.title) AS title,
                       COALESCE(d.para_number, b.para_number) AS para_number,
                       COALESCE(d.component, b.component) AS component,
                       COALESCE(d.section_title, b.section_title) AS section_title,
                       COALESCE(d.content_markdown, b.content_markdown) AS content_markdown,
                       1.0 / (60 + COALESCE(d.rank_dense, 1000))
                         + 1.0 / (60 + COALESCE(b.rank_bm25, 1000)) AS score
                FROM dense d
                FULL OUTER JOIN bm25 b ON d.chunk_id = b.chunk_id
                ORDER BY score DESC
                LIMIT %(top_k)s
                """
            ).format(
                _table("chunks"),
                _table("standards"),
                _table("chunks"),
                _table("standards"),
            ),
            {
                "emb": query_emb,
                "query": query,
                "standard_ids": standard_ids,
                "pool_size": pool_size,
                "top_k": top_k,
            },
        ).fetchall()

    return [
        _AuditChunk(
            chunk_id=row[0],
            standard_id=row[1],
            title=row[2],
            para_number=row[3],
            component=row[4],
            section_title=row[5],
            content_markdown=row[6],
            score=float(row[7]),
        )
        for row in rows
    ]


def _format_audit_results(
    query: str,
    top_k: int,
    candidates: list[_AuditCandidate],
    chunks: list[_AuditChunk],
) -> str:
    if not candidates or candidates[0].similarity < _SIMILARITY_THRESHOLD:
        return "관련 감사기준을 찾을 수 없습니다. 감사기준 관련 질문을 입력해 주세요."
    if not chunks:
        return "관련 감사기준 문단을 찾을 수 없습니다."

    lines = [
        f"# 감사기준 검색 결과 (k={top_k})",
        f"사용자 질문: {query}",
        "",
        "## 기준서 후보",
    ]
    for item in candidates:
        lines.append(f"- {item.standard_id} {item.title} (유사도: {item.similarity:.3f})")

    lines.extend(["", "## 관련 문단"])
    for item in chunks:
        para = item.para_number or "N/A"
        section = item.section_title or "-"
        lines.append(
            f"\n**[{item.standard_id}] 문단 {para}** "
            f"({item.component}, {section}, score: {item.score:.4f})"
        )
        lines.append(f"chunk_id: {item.chunk_id}")
        lines.append(item.content_markdown[:_CONTENT_MAX_CHARS])

    return "\n".join(lines)


def _search_audit_standards(query: str, *, top_k: int) -> str:
    query_emb = embed_query(query)
    candidates = _identify_audit_standards(query_emb)
    if not candidates or candidates[0].similarity < _SIMILARITY_THRESHOLD:
        return _format_audit_results(query, top_k, candidates, [])

    standard_ids = [
        candidate.standard_id
        for candidate in candidates
        if candidate.similarity >= _SIMILARITY_THRESHOLD
    ]
    chunks = _search_audit_chunks(query_emb, query, standard_ids, top_k=top_k)
    return _format_audit_results(query, top_k, candidates, chunks)


@tool
def search_audit_standards_k1(query: str) -> str:
    """감사기준 PostgreSQL DB에서 관련 문단 1개를 검색합니다.

    가장 짧은 근거 확인이나 smoke test에 사용하세요.

    Args:
        query: 검색할 감사기준 질문
    """
    return _search_audit_standards(query, top_k=1)


@tool
def search_audit_standards_k3(query: str) -> str:
    """감사기준 PostgreSQL DB에서 관련 문단 3개를 검색합니다.

    일반적인 감사기준 질의응답에서 기본 검색 도구로 사용하세요.

    Args:
        query: 검색할 감사기준 질문
    """
    return _search_audit_standards(query, top_k=3)


@tool
def search_audit_standards_k5(query: str) -> str:
    """감사기준 PostgreSQL DB에서 관련 문단 5개를 검색합니다.

    근거 문단을 넓게 확인해야 하는 감사기준 질문에 사용하세요.

    Args:
        query: 검색할 감사기준 질문
    """
    return _search_audit_standards(query, top_k=5)
