"""Load AuditStandard parser JSON outputs into PostgreSQL/pgvector.

The source of truth is the parsed JSON produced by
``/home/shin/Project/_AuditStandard_parsing``. This loader intentionally writes
to a separate PostgreSQL schema (default: ``audit``) so K-IFRS data in
``public`` is not mixed with audit-standard data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import struct
import subprocess
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from psycopg import sql
from psycopg.types.json import Jsonb

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - only needed for --allow-api
    OpenAI = None  # type: ignore[assignment]


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_ROOT = Path("/home/shin/Project/_AuditStandard_parsing")
AUDIT_PYTHON = AUDIT_ROOT / ".venv/bin/python"
DEFAULT_JSON_DIR = AUDIT_ROOT / "output/json"
DEFAULT_CACHE_PATH = AUDIT_ROOT / ".embed_cache.sqlite"

EMBED_DIM = 4096
MODEL_PASSAGE = "embedding-passage"
ROLE_PASSAGE = "passage"
SOLAR_BASE_URL = "https://api.upstage.ai/v1"
SUMMARY_TOKEN_LIMIT = 3950
EXCLUDED_JSON = {
    "METRICS.json",
    "EMBED_METRICS.json",
    "EMBED_METRICS.idempotency.json",
    "PHASE4E_METRICS.json",
}

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
VECTOR_STRUCT = struct.Struct(f"<{EMBED_DIM}f")


@dataclass(slots=True)
class LoadStats:
    standards: int = 0
    summaries: int = 0
    chunks: int = 0
    links: int = 0
    chunk_embedding_hits: int = 0
    summary_embedding_hits: int = 0
    api_embedding_calls: int = 0
    missing_embeddings: int = 0


class EmbeddingSource:
    """Read passage vectors from the AuditStandard SQLite embedding cache."""

    def __init__(self, cache_path: Path, allow_api: bool = False) -> None:
        self.cache_path = cache_path
        self.allow_api = allow_api
        self.conn: sqlite3.Connection | None = None
        self.client: Any | None = None
        self.api_calls = 0
        if cache_path.exists():
            self.conn = sqlite3.connect(str(cache_path))

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()

    @staticmethod
    def cache_key(text: str) -> str:
        digest = hashlib.sha256(
            f"{MODEL_PASSAGE}:{ROLE_PASSAGE}:{text}".encode()
        ).hexdigest()
        return digest[:16]

    def get(self, text: str) -> list[float] | None:
        vector = self._get_from_cache(text)
        if vector is not None:
            return vector
        truncated = _truncate_summary_text(text)
        if truncated != text:
            vector = self._get_from_cache(truncated)
            if vector is not None:
                return vector
        if self.allow_api:
            return self._get_from_api(text)
        return None

    def _get_from_cache(self, text: str) -> list[float] | None:
        if self.conn is None:
            return None
        key = self.cache_key(text)
        row = self.conn.execute(
            "SELECT vector FROM embeddings WHERE cache_key = ? AND role = ? AND model = ?",
            (key, ROLE_PASSAGE, MODEL_PASSAGE),
        ).fetchone()
        if row is None:
            return None
        return list(VECTOR_STRUCT.unpack(row[0]))

    def _get_from_api(self, text: str) -> list[float]:
        if OpenAI is None:
            raise RuntimeError("openai package is required for --allow-api")
        if self.client is None:
            api_key = os.environ.get("UPSTAGE_API_KEY")
            if not api_key:
                raise RuntimeError("UPSTAGE_API_KEY is required for --allow-api")
            self.client = OpenAI(api_key=api_key, base_url=SOLAR_BASE_URL)
        response = self.client.embeddings.create(input=text, model=MODEL_PASSAGE)
        vector = response.data[0].embedding
        if len(vector) != EMBED_DIM:
            raise RuntimeError(f"embedding dim mismatch: expected {EMBED_DIM}, got {len(vector)}")
        self.api_calls += 1
        return vector


def _truncate_summary_text(text: str) -> str:
    """Match AuditStandard qdrant_writer summary truncation when tiktoken exists."""
    try:
        import tiktoken
    except ImportError:
        if AUDIT_PYTHON.exists():
            return _truncate_with_audit_python(text)
        return text
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)
    if len(tokens) <= SUMMARY_TOKEN_LIMIT:
        return text
    return encoding.decode(tokens[:SUMMARY_TOKEN_LIMIT])


def _truncate_with_audit_python(text: str) -> str:
    """Use the AuditStandard venv for tiktoken when this repo lacks it."""
    script = (
        "import sys, tiktoken; "
        "text = sys.stdin.read(); "
        "enc = tiktoken.get_encoding('cl100k_base'); "
        f"tokens = enc.encode(text); "
        f"sys.stdout.write(enc.decode(tokens[:{SUMMARY_TOKEN_LIMIT}]) "
        f"if len(tokens) > {SUMMARY_TOKEN_LIMIT} else text)"
    )
    try:
        result = subprocess.run(
            [str(AUDIT_PYTHON), "-c", script],
            input=text,
            text=True,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return text
    return result.stdout


def audit_json_files(json_dir: Path) -> list[Path]:
    return sorted(p for p in json_dir.glob("*.json") if p.name not in EXCLUDED_JSON)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compose_summary_text(data: dict[str, Any]) -> str:
    summary = data["summary"]
    parts = []
    if summary.get("scope_text"):
        parts.append(summary["scope_text"])
    if summary.get("definitions_text"):
        parts.append(summary["definitions_text"])
    if parts:
        return "\n\n".join(parts)
    standard = data["standard"]
    title = standard.get("standard_title") or ""
    return f"{standard['standard_id']} — {title}".rstrip(" —")


def component_for_chunk(chunk: dict[str, Any]) -> str:
    return chunk.get("section") or chunk.get("kind") or "unknown"


def section_title_for_chunk(chunk: dict[str, Any]) -> str | None:
    trail = chunk.get("heading_trail") or []
    if not trail:
        return None
    return " > ".join(str(x) for x in trail)


def standard_family(standard_id: str) -> str:
    return standard_id.split("-", 1)[0]


def standard_type(family: str) -> str:
    return {
        "ISA": "auditing_standard",
        "ISQM": "quality_management_standard",
        "ASSR": "assurance_standard",
        "FRMK": "framework",
    }.get(family, "audit_standard")


def metadata_without_text(obj: dict[str, Any]) -> dict[str, Any]:
    excluded = {"content_text", "content_markdown", "embedding"}
    return {k: v for k, v in obj.items() if k not in excluded}


def validate_schema_name(name: str) -> None:
    if not IDENT_RE.match(name):
        raise ValueError(f"invalid schema name: {name!r}")


def q(schema: str, table: str) -> sql.Identifier:
    return sql.Identifier(schema, table)


def create_schema(conn: psycopg.Connection, schema: str, rebuild: bool) -> None:
    validate_schema_name(schema)
    if rebuild:
        if schema == "public":
            raise ValueError("--rebuild is not allowed for schema=public")
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))

    conn.execute(
        sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {} (
                standard_id text PRIMARY KEY,
                standard_number text,
                title text NOT NULL,
                standard_type text NOT NULL,
                standard_family text NOT NULL,
                original_number text,
                base_authority smallint NOT NULL,
                last_amended_year text,
                components text[] NOT NULL,
                has_korean_additions boolean DEFAULT false,
                korean_paragraph_count integer DEFAULT 0,
                total_chunks integer DEFAULT 0,
                source_file text NOT NULL,
                metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                created_at timestamptz DEFAULT now()
            )
            """
        ).format(q(schema, "standards"))
    )
    conn.execute(
        sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {} (
                standard_id text PRIMARY KEY REFERENCES {}(standard_id) ON DELETE CASCADE,
                title text NOT NULL,
                scope_text text NOT NULL,
                scope_markdown text NOT NULL,
                definitions_text text NOT NULL,
                definitions_markdown text NOT NULL,
                embedding vector(4096),
                metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                created_at timestamptz DEFAULT now()
            )
            """
        ).format(q(schema, "standard_summaries"), q(schema, "standards"))
    )
    conn.execute(
        sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {} (
                chunk_id text PRIMARY KEY,
                standard_id text NOT NULL REFERENCES {}(standard_id) ON DELETE CASCADE,
                para_number text,
                component text NOT NULL,
                section_title text,
                authority smallint NOT NULL,
                content_text text NOT NULL,
                content_markdown text NOT NULL,
                embedding vector(4096),
                char_count integer NOT NULL,
                token_estimate integer NOT NULL,
                metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                created_at timestamptz DEFAULT now()
            )
            """
        ).format(q(schema, "chunks"), q(schema, "standards"))
    )
    conn.execute(
        sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {} (
                link_id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                standard_id text NOT NULL REFERENCES {}(standard_id) ON DELETE CASCADE,
                source_chunk_id text NOT NULL,
                source_component text NOT NULL,
                source_para text,
                target_chunk_id text NOT NULL,
                target_para_start text NOT NULL,
                target_para_end text,
                link_type text NOT NULL,
                metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                UNIQUE (source_chunk_id, target_chunk_id, link_type)
            )
            """
        ).format(q(schema, "paragraph_links"), q(schema, "standards"))
    )
    conn.execute(
        sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {} (
                footnote_id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                standard_id text NOT NULL REFERENCES {}(standard_id) ON DELETE CASCADE,
                footnote_number integer NOT NULL,
                content text NOT NULL,
                metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                UNIQUE (standard_id, footnote_number)
            )
            """
        ).format(q(schema, "footnotes"), q(schema, "standards"))
    )

    indexes = [
        ("idx_chunks_standard", "chunks", "standard_id"),
        ("idx_chunks_component", "chunks", "component"),
        ("idx_chunks_authority", "chunks", "authority"),
        ("idx_links_source_component", "paragraph_links", "standard_id, source_component"),
        ("idx_links_target", "paragraph_links", "standard_id, target_para_start"),
    ]
    for name, table, columns, *method in indexes:
        using = sql.SQL(" USING GIN") if method and method[0] == "GIN" else sql.SQL("")
        conn.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}{} ({})").format(
                sql.Identifier(f"{schema}_{name}"),
                q(schema, table),
                using,
                sql.SQL(columns),
            )
        )


def iter_batches(items: Sequence[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def collect_counts(json_files: Iterable[Path]) -> LoadStats:
    stats = LoadStats()
    for path in json_files:
        data = load_json(path)
        stats.standards += 1
        stats.summaries += 1
        stats.chunks += len(data.get("chunks", []))
        stats.links += len(data.get("paragraph_links", []))
    return stats


def inspect_embedding_coverage(
    json_files: Iterable[Path],
    embeddings: EmbeddingSource,
) -> LoadStats:
    stats = LoadStats()
    for path in json_files:
        data = load_json(path)
        stats.standards += 1
        stats.summaries += 1
        if embeddings.get(compose_summary_text(data)) is not None:
            stats.summary_embedding_hits += 1
        else:
            stats.missing_embeddings += 1
        for chunk in data.get("chunks", []):
            stats.chunks += 1
            if embeddings.get(chunk["content_text"]) is not None:
                stats.chunk_embedding_hits += 1
            else:
                stats.missing_embeddings += 1
        stats.links += len(data.get("paragraph_links", []))
    stats.api_embedding_calls = embeddings.api_calls
    return stats


def load_all(
    conn: psycopg.Connection,
    json_files: list[Path],
    schema: str,
    embeddings: EmbeddingSource,
    *,
    skip_embedding: bool,
    batch_size: int,
) -> LoadStats:
    stats = LoadStats()
    for path in json_files:
        data = load_json(path)
        load_standard(conn, data, path, schema, embeddings, skip_embedding=skip_embedding)
        load_chunks(
            conn,
            data,
            schema,
            embeddings,
            skip_embedding=skip_embedding,
            batch_size=batch_size,
        )
        load_links(conn, data, schema)
        stats.standards += 1
        stats.summaries += 1
        stats.chunks += len(data["chunks"])
        stats.links += len(data.get("paragraph_links", []))
    stats.api_embedding_calls = embeddings.api_calls
    rows = conn.execute(
        sql.SQL(
            """
            SELECT
              (SELECT count(*) FROM {}) AS standards,
              (SELECT count(*) FROM {}) AS summaries,
              (SELECT count(*) FROM {}) AS chunks,
              (SELECT count(*) FROM {}) AS links,
              (SELECT count(*) FROM {} WHERE embedding IS NULL) AS chunk_missing,
              (SELECT count(*) FROM {} WHERE embedding IS NULL) AS summary_missing
            """
        ).format(
            q(schema, "standards"),
            q(schema, "standard_summaries"),
            q(schema, "chunks"),
            q(schema, "paragraph_links"),
            q(schema, "chunks"),
            q(schema, "standard_summaries"),
        )
    ).fetchone()
    stats.missing_embeddings = int(rows[4]) + int(rows[5])
    stats.chunk_embedding_hits = int(rows[2]) - int(rows[4])
    stats.summary_embedding_hits = int(rows[1]) - int(rows[5])
    return stats


def load_standard(
    conn: psycopg.Connection,
    data: dict[str, Any],
    source_path: Path,
    schema: str,
    embeddings: EmbeddingSource,
    *,
    skip_embedding: bool,
) -> None:
    std = data["standard"]
    family = standard_family(std["standard_id"])
    components = sorted({component_for_chunk(c) for c in data["chunks"]})
    metadata = {
        "schema_version": data.get("schema_version"),
        "source_json": str(source_path),
        "standard": std,
    }
    conn.execute(
        sql.SQL(
            """
            INSERT INTO {} (
                standard_id, standard_number, title, standard_type, standard_family,
                original_number, base_authority, last_amended_year, components,
                has_korean_additions, korean_paragraph_count, total_chunks,
                source_file, metadata
            )
            VALUES (
                %(standard_id)s, %(standard_number)s, %(title)s, %(standard_type)s,
                %(standard_family)s, %(original_number)s, %(base_authority)s,
                %(last_amended_year)s, %(components)s, false, 0, %(total_chunks)s,
                %(source_file)s, %(metadata)s
            )
            ON CONFLICT (standard_id) DO UPDATE SET
                standard_number = EXCLUDED.standard_number,
                title = EXCLUDED.title,
                standard_type = EXCLUDED.standard_type,
                standard_family = EXCLUDED.standard_family,
                original_number = EXCLUDED.original_number,
                base_authority = EXCLUDED.base_authority,
                last_amended_year = EXCLUDED.last_amended_year,
                components = EXCLUDED.components,
                total_chunks = EXCLUDED.total_chunks,
                source_file = EXCLUDED.source_file,
                metadata = EXCLUDED.metadata
            """
        ).format(q(schema, "standards")),
        {
            "standard_id": std["standard_id"],
            "standard_number": std.get("standard_no"),
            "title": std.get("standard_title") or std["standard_id"],
            "standard_type": standard_type(family),
            "standard_family": family,
            "original_number": std["standard_id"],
            "base_authority": std.get("authority_base", 1),
            "last_amended_year": None,
            "components": components,
            "total_chunks": len(data["chunks"]),
            "source_file": std.get("source_file") or source_path.name,
            "metadata": Jsonb(metadata),
        },
    )

    summary = data["summary"]
    summary_text = compose_summary_text(data)
    embedding = None if skip_embedding else embeddings.get(summary_text)
    conn.execute(
        sql.SQL(
            """
            INSERT INTO {} (
                standard_id, title, scope_text, scope_markdown,
                definitions_text, definitions_markdown, embedding, metadata
            )
            VALUES (
                %(standard_id)s, %(title)s, %(scope_text)s, %(scope_markdown)s,
                %(definitions_text)s, %(definitions_markdown)s, %(embedding)s, %(metadata)s
            )
            ON CONFLICT (standard_id) DO UPDATE SET
                title = EXCLUDED.title,
                scope_text = EXCLUDED.scope_text,
                scope_markdown = EXCLUDED.scope_markdown,
                definitions_text = EXCLUDED.definitions_text,
                definitions_markdown = EXCLUDED.definitions_markdown,
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata
            """
        ).format(q(schema, "standard_summaries")),
        {
            "standard_id": std["standard_id"],
            "title": std.get("standard_title") or std["standard_id"],
            "scope_text": summary.get("scope_text") or "",
            "scope_markdown": summary.get("scope_markdown") or "",
            "definitions_text": summary.get("definitions_text") or "",
            "definitions_markdown": summary.get("definitions_markdown") or "",
            "embedding": embedding,
            "metadata": Jsonb({"summary": {k: v for k, v in summary.items() if k != "embedding"}}),
        },
    )


def load_chunks(
    conn: psycopg.Connection,
    data: dict[str, Any],
    schema: str,
    embeddings: EmbeddingSource,
    *,
    skip_embedding: bool,
    batch_size: int,
) -> None:
    std = data["standard"]
    rows: list[dict[str, Any]] = []
    for chunk in data["chunks"]:
        content_text = chunk["content_text"]
        rows.append(
            {
                "chunk_id": chunk["chunk_id"],
                "standard_id": std["standard_id"],
                "para_number": chunk.get("paragraph_id"),
                "component": component_for_chunk(chunk),
                "section_title": section_title_for_chunk(chunk),
                "authority": chunk.get("authority", std.get("authority_base", 1)),
                "content_text": content_text,
                "content_markdown": chunk["content_markdown"],
                "embedding": None if skip_embedding else embeddings.get(content_text),
                "char_count": len(content_text),
                "token_estimate": chunk.get("token_estimate") or 0,
                "metadata": Jsonb(metadata_without_text(chunk)),
            }
        )

    statement = sql.SQL(
        """
        INSERT INTO {} (
            chunk_id, standard_id, para_number, component, section_title,
            authority, content_text, content_markdown, embedding, char_count,
            token_estimate, metadata
        )
        VALUES (
            %(chunk_id)s, %(standard_id)s, %(para_number)s, %(component)s,
            %(section_title)s, %(authority)s, %(content_text)s, %(content_markdown)s,
            %(embedding)s, %(char_count)s, %(token_estimate)s, %(metadata)s
        )
        ON CONFLICT (chunk_id) DO UPDATE SET
            standard_id = EXCLUDED.standard_id,
            para_number = EXCLUDED.para_number,
            component = EXCLUDED.component,
            section_title = EXCLUDED.section_title,
            authority = EXCLUDED.authority,
            content_text = EXCLUDED.content_text,
            content_markdown = EXCLUDED.content_markdown,
            embedding = EXCLUDED.embedding,
            char_count = EXCLUDED.char_count,
            token_estimate = EXCLUDED.token_estimate,
            metadata = EXCLUDED.metadata
        """
    ).format(q(schema, "chunks"))
    with conn.cursor() as cur:
        for batch in iter_batches(rows, batch_size):
            cur.executemany(statement, batch)


def load_links(conn: psycopg.Connection, data: dict[str, Any], schema: str) -> None:
    links = data.get("paragraph_links", [])
    if not links:
        return
    chunk_by_id = {c["chunk_id"]: c for c in data["chunks"]}
    rows = []
    for link in links:
        source = chunk_by_id.get(link["source"])
        target = chunk_by_id.get(link["target"])
        rows.append(
            {
                "standard_id": data["standard"]["standard_id"],
                "source_chunk_id": link["source"],
                "source_component": component_for_chunk(source or {}),
                "source_para": (source or {}).get("paragraph_id"),
                "target_chunk_id": link["target"],
                "target_para_start": (target or {}).get("paragraph_id") or link["target"],
                "target_para_end": None,
                "link_type": link["link_type"],
                "metadata": Jsonb(link),
            }
        )
    statement = sql.SQL(
        """
        INSERT INTO {} (
            standard_id, source_chunk_id, source_component, source_para,
            target_chunk_id, target_para_start, target_para_end, link_type, metadata
        )
        VALUES (
            %(standard_id)s, %(source_chunk_id)s, %(source_component)s,
            %(source_para)s, %(target_chunk_id)s, %(target_para_start)s,
            %(target_para_end)s, %(link_type)s, %(metadata)s
        )
        ON CONFLICT (source_chunk_id, target_chunk_id, link_type) DO UPDATE SET
            standard_id = EXCLUDED.standard_id,
            source_component = EXCLUDED.source_component,
            source_para = EXCLUDED.source_para,
            target_para_start = EXCLUDED.target_para_start,
            target_para_end = EXCLUDED.target_para_end,
            metadata = EXCLUDED.metadata
        """
    ).format(q(schema, "paragraph_links"))
    with conn.cursor() as cur:
        cur.executemany(statement, rows)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-dir", type=Path, default=DEFAULT_JSON_DIR)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--schema", default="audit")
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--skip-embedding", action="store_true")
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument(
        "--allow-missing-embeddings",
        action="store_true",
        help="Load rows with NULL vectors when cache/API coverage is incomplete.",
    )
    return parser.parse_args(argv)


def print_stats(label: str, stats: LoadStats) -> None:
    print(f"{label}:")
    print(f"  standards: {stats.standards}")
    print(f"  summaries: {stats.summaries}")
    print(f"  chunks: {stats.chunks}")
    print(f"  paragraph_links: {stats.links}")
    print(f"  chunk_embedding_hits: {stats.chunk_embedding_hits}")
    print(f"  summary_embedding_hits: {stats.summary_embedding_hits}")
    print(f"  api_embedding_calls: {stats.api_embedding_calls}")
    print(f"  missing_embeddings: {stats.missing_embeddings}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    load_dotenv(PROJECT_ROOT / ".env")
    validate_schema_name(args.schema)

    json_files = audit_json_files(args.json_dir)
    if not json_files:
        raise SystemExit(f"no audit JSON files found in {args.json_dir}")

    embeddings = EmbeddingSource(args.cache_path, allow_api=args.allow_api)
    try:
        if args.dry_run:
            stats = (
                collect_counts(json_files)
                if args.skip_embedding
                else inspect_embedding_coverage(json_files, embeddings)
            )
            print_stats("dry-run", stats)
            if stats.missing_embeddings and not (
                args.skip_embedding or args.allow_api or args.allow_missing_embeddings
            ):
                print(
                    "Embedding coverage is incomplete. Use --allow-api, "
                    "--skip-embedding, or --allow-missing-embeddings.",
                    file=sys.stderr,
                )
                return 2
            return 0

        if not args.skip_embedding and not (args.allow_api or args.allow_missing_embeddings):
            coverage = inspect_embedding_coverage(json_files, embeddings)
            if coverage.missing_embeddings:
                print_stats("preflight", coverage)
                print(
                    "Embedding coverage is incomplete. Use --allow-api or "
                    "--allow-missing-embeddings.",
                    file=sys.stderr,
                )
                return 2

        db_url = args.db_url or os.environ.get("DATABASE_URL")
        if not db_url:
            raise SystemExit("DATABASE_URL is required")

        started = datetime.now(tz=UTC)
        with psycopg.connect(db_url) as conn:
            register_vector(conn)
            create_schema(conn, args.schema, rebuild=args.rebuild)
            stats = load_all(
                conn,
                json_files,
                args.schema,
                embeddings,
                skip_embedding=args.skip_embedding,
                batch_size=args.batch_size,
            )
            conn.commit()
        elapsed = (datetime.now(tz=UTC) - started).total_seconds()
        print_stats("loaded", stats)
        print(f"  schema: {args.schema}")
        print(f"  elapsed_seconds: {elapsed:.2f}")
        if stats.missing_embeddings and not args.allow_missing_embeddings:
            return 2
        return 0
    finally:
        embeddings.close()


if __name__ == "__main__":
    raise SystemExit(main())
