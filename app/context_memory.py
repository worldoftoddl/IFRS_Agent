"""Thread-scoped retrieval memory for reused IFRS/audit context.

This store is separate from `.transcripts`.
- `.transcripts`: debug/archive log for compacted raw tool outputs.
- `.context`: structured retrieval memory the agent can search in later turns.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

DEFAULT_CONTEXT_DIR = Path("./.context")
DEFAULT_MAX_ENTRIES = 20
DEFAULT_MAX_CHUNKS = 5
DEFAULT_EXCERPT_CHARS = 500
DEFAULT_ORIGINAL_CHARS = 4000

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣][0-9A-Za-z가-힣_.:-]*")


def _safe_thread_id(thread_id: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_.-]+", "_", thread_id or "unknown").strip("._")
    if cleaned:
        return cleaned[:120]
    digest = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:16]
    return f"thread_{digest}"


def _one_line(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content or "")


def _parse_structured(text: str) -> Any | None:
    stripped = text.strip()
    candidates: list[str] = []
    if stripped and stripped[0] in "[{":
        candidates.append(stripped)
    candidates.extend(match.group(1).strip() for match in _JSON_BLOCK_RE.finditer(text))

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        try:
            return ast.literal_eval(candidate)
        except (SyntaxError, ValueError):
            pass
    return None


def extract_structured_content(content: Any) -> Any | None:
    """Best-effort extraction of JSON/list/dict retrieval payloads."""
    if isinstance(content, (dict, list)):
        return content
    return _parse_structured(_content_to_text(content))


def infer_domain(source_tool: str, chunks: list[dict[str, Any]]) -> str:
    source = source_tool.lower()
    if "audit" in source:
        return "audit"
    for chunk in chunks:
        standard_id = str(chunk.get("standard_id", "")).upper()
        if standard_id.startswith(("ISA-", "ISQM-", "ASSR-", "FRMK-")):
            return "audit"
    return "ifrs"


def _chunk_ref(chunk: dict[str, Any]) -> str:
    para = chunk.get("para_number") or "N/A"
    return f"{chunk.get('standard_id') or '-'}:{para}"


def _extract_excerpt(chunk: dict[str, Any]) -> str:
    for key in ("key_excerpt", "content_markdown", "original_text", "text"):
        if chunk.get(key):
            return _one_line(chunk[key], DEFAULT_EXCERPT_CHARS)
    return ""


def _extract_original(chunk: dict[str, Any]) -> str:
    for key in ("original_text", "content_markdown", "text"):
        if chunk.get(key):
            return _one_line(chunk[key], DEFAULT_ORIGINAL_CHARS)
    return ""


def normalize_retrieval_payload(
    source_tool: str,
    content: Any,
    tool_args: dict[str, Any] | None = None,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
) -> dict[str, Any] | None:
    """Return a structured retrieval memory entry body, or None if not parseable."""
    data = extract_structured_content(content)
    if data is None:
        return None

    synthesis = ""
    notes = ""
    raw_chunks: list[Any] = []

    if isinstance(data, dict):
        synthesis = str(data.get("synthesis") or "")
        notes = str(data.get("notes") or "")
        if isinstance(data.get("chunks"), list):
            raw_chunks = data["chunks"]
        else:
            raw_chunks = [data]
    elif isinstance(data, list):
        raw_chunks = data
    else:
        return None

    chunks: list[dict[str, Any]] = []
    for raw in raw_chunks[:max_chunks]:
        if not isinstance(raw, dict):
            continue
        standard_id = raw.get("standard_id") or raw.get("standard")
        para_number = raw.get("para_number") or raw.get("paragraph")
        excerpt = _extract_excerpt(raw)
        original = _extract_original(raw)
        if not (standard_id or para_number or excerpt or original):
            continue
        chunk = {
            "standard_id": standard_id,
            "para_number": para_number,
            "component": raw.get("component"),
            "section_title": raw.get("section_title") or raw.get("section"),
            "excerpt": excerpt,
            "original_text": original,
            "why_relevant": _one_line(raw.get("why_relevant"), 300),
        }
        chunk["ref"] = _chunk_ref(chunk)
        chunks.append(chunk)

    if not chunks and not synthesis and not notes:
        return None

    args = tool_args or {}
    query = str(args.get("description") or args.get("query") or "")
    return {
        "source_tool": source_tool,
        "domain": infer_domain(source_tool, chunks),
        "query": _one_line(query, 1000),
        "synthesis": _one_line(synthesis, 1200),
        "notes": _one_line(notes, 500),
        "chunks": chunks,
    }


def _entry_signature(body: dict[str, Any]) -> str:
    refs = ",".join(chunk.get("ref", "") for chunk in body.get("chunks", []))
    raw = "|".join(
        [
            str(body.get("source_tool", "")),
            str(body.get("domain", "")),
            str(body.get("query", "")),
            refs,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text)}


def _entry_haystack(entry: dict[str, Any]) -> str:
    parts = [
        entry.get("query", ""),
        entry.get("synthesis", ""),
        entry.get("notes", ""),
        entry.get("source_tool", ""),
        entry.get("domain", ""),
    ]
    for chunk in entry.get("chunks", []):
        parts.extend(
            [
                chunk.get("standard_id", ""),
                chunk.get("para_number", ""),
                chunk.get("section_title", ""),
                chunk.get("excerpt", ""),
                chunk.get("why_relevant", ""),
            ]
        )
    return " ".join(str(part or "") for part in parts)


def _without_originals(entry: dict[str, Any]) -> dict[str, Any]:
    result = dict(entry)
    result["chunks"] = [
        {k: v for k, v in chunk.items() if k != "original_text"}
        for chunk in entry.get("chunks", [])
    ]
    return result


class RetrievalMemoryStore:
    """Small JSON-file store for thread-scoped retrieval memory."""

    def __init__(
        self,
        root_dir: Path | str = DEFAULT_CONTEXT_DIR,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.max_entries = max_entries

    def _path(self, thread_id: str) -> Path:
        return self.root_dir / f"{_safe_thread_id(thread_id)}.json"

    def _read_doc(self, thread_id: str) -> dict[str, Any]:
        path = self._path(thread_id)
        if not path.exists():
            return {"version": 1, "thread_id": thread_id, "entries": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"version": 1, "thread_id": thread_id, "entries": []}
        entries = data.get("entries")
        if not isinstance(entries, list):
            entries = []
        return {"version": 1, "thread_id": thread_id, "entries": entries}

    def _write_doc(self, thread_id: str, doc: dict[str, Any]) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(thread_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def save_from_tool_result(
        self,
        thread_id: str,
        source_tool: str,
        content: Any,
        tool_args: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        body = normalize_retrieval_payload(
            source_tool=source_tool,
            content=content,
            tool_args=tool_args,
        )
        if body is None:
            return None

        now = time.time()
        entry_id = _entry_signature(body)
        doc = self._read_doc(thread_id)
        entries = [e for e in doc["entries"] if e.get("id") != entry_id]

        previous = next((e for e in doc["entries"] if e.get("id") == entry_id), None)
        entry = {
            "id": entry_id,
            "thread_id": thread_id,
            "created_at": previous.get("created_at", now) if previous else now,
            "last_used_at": now,
            **body,
        }
        entries.append(entry)
        entries = sorted(entries, key=lambda e: e.get("last_used_at", 0), reverse=True)
        doc["entries"] = entries[: self.max_entries]
        self._write_doc(thread_id, doc)
        return entry

    def list_recent(
        self,
        thread_id: str,
        domain: str | None = None,
        limit: int = 5,
        include_original: bool = False,
    ) -> list[dict[str, Any]]:
        entries = self._read_doc(thread_id)["entries"]
        if domain:
            entries = [e for e in entries if e.get("domain") == domain]
        entries = sorted(entries, key=lambda e: e.get("last_used_at", 0), reverse=True)
        selected = entries[: max(limit, 0)]
        return selected if include_original else [_without_originals(e) for e in selected]

    def get(
        self,
        thread_id: str,
        memory_id: str,
        include_original: bool = True,
    ) -> dict[str, Any] | None:
        doc = self._read_doc(thread_id)
        for entry in doc["entries"]:
            if entry.get("id") == memory_id:
                entry["last_used_at"] = time.time()
                self._write_doc(thread_id, doc)
                return entry if include_original else _without_originals(entry)
        return None

    def search(
        self,
        thread_id: str,
        query: str,
        domain: str | None = None,
        limit: int = 5,
        include_original: bool = False,
    ) -> list[dict[str, Any]]:
        doc = self._read_doc(thread_id)
        query_text = str(query or "").lower()
        query_tokens = _tokenize(query_text)
        scored: list[tuple[float, dict[str, Any]]] = []

        for entry in doc["entries"]:
            if domain and entry.get("domain") != domain:
                continue
            haystack = _entry_haystack(entry).lower()
            hay_tokens = _tokenize(haystack)
            score = 0.0
            if query_text and query_text in haystack:
                score += 5.0
            score += len(query_tokens & hay_tokens)
            if not query_tokens:
                score += 0.1
            if score <= 0:
                continue
            score += min(entry.get("last_used_at", 0), entry.get("created_at", 0)) / 1e12
            scored.append((score, entry))

        scored.sort(key=lambda item: item[0], reverse=True)
        selected = [entry for _, entry in scored[: max(limit, 0)]]
        if selected:
            now = time.time()
            selected_ids = {entry["id"] for entry in selected}
            for entry in doc["entries"]:
                if entry.get("id") in selected_ids:
                    entry["last_used_at"] = now
            self._write_doc(thread_id, doc)

        return selected if include_original else [_without_originals(e) for e in selected]
