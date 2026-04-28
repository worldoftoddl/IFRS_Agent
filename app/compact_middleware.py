"""MicroCompactMiddleware — s06 Layer 1 컨텍스트 압축.

오래된 tool_result를 플레이스홀더로 교체하여 토큰 누적을 억제한다.
AnthropicPromptCachingMiddleware와의 충돌을 피하기 위해
`trigger_tokens` 초과 시에만 발동(조건부 압축).

설계 메모:
- LangGraph의 add_messages 리듀서는 동일 ID 메시지를 교체한다.
  따라서 기존 ToolMessage와 같은 id·tool_call_id로 새 ToolMessage를 만들어 반환하면
  자연스레 content만 바뀐다.
- PRESERVE_TOOLS: 재실행 비용이 높거나 답변 정합성에 치명적인 도구 결과 보존.
  - 계산 결과(verify_arithmetic 등): 재계산 오버헤드 + 일관성 리스크
  - 메타데이터(get_standard_info): 짧음 + 반복 조회 회피
  - 파일 계열(read_file): 재읽기 비싸고 Layer 2에도 있음
- Archive: 치환 **전** 원본 ToolMessage를 `.transcripts/{thread_id}_{date}.jsonl`에
  JSONL로 append. 각 줄은 압축 이벤트 1회(여러 메시지 묶음). 디버깅·감사 용도.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage

from app.context_memory import RetrievalMemoryStore, extract_structured_content

logger = logging.getLogger(__name__)

PLACEHOLDER_TEMPLATE = "[Previous: used {tool_name}]"
MIN_COMPACT_LENGTH = 100  # 짧은 content는 교체 이득 없음
DEFAULT_MAX_DIGEST_CHARS = 2400
DEFAULT_ARCHIVE_RETENTION_DAYS = 7
DEFAULT_ARCHIVE_MAX_FILE_MB = 10.0

RETRIEVAL_CONTEXT_TOOLS: set[str] = {
    "retrieval-distiller",
    "audit-retrieval-distiller",
    "retrieve_ifrs",
    "retrieve_audit_standards",
    "search_single_standard",
    "search_single_audit_standard",
    "lookup_paragraph",
    "lookup_audit_paragraph",
}

PRESERVE_TOOLS: set[str] = {
    # 회계 계산 — 재계산 비용 + 일관성 리스크
    "verify_arithmetic",
    "calculate_present_value",
    "calculate_effective_interest_rate",
    "build_amortization_schedule",
    # 메타데이터 — 짧고 자주 참조
    "get_standard_info",
    # 영속 Task 조회 결과 — 다른 계층에 없음
    "task_get",
    # 파일 참조 — 재읽기 비용
    "read_file",
    "ls",
    "grep",
    "glob",
}


def estimate_tokens(messages: list[AnyMessage]) -> int:
    """문자 수/4의 단순 추정. s06과 동일 방식."""
    if not messages:
        return 0
    total_chars = 0
    for m in messages:
        content = getattr(m, "content", "")
        if isinstance(content, str):
            total_chars += len(content)
        else:
            total_chars += len(str(content))
    return total_chars // 4


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _one_line(value: Any, limit: int = 500) -> str:
    text = str(value or "")
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3].rstrip() + "..."


def _load_structured_content(content: Any) -> Any | None:
    """ToolMessage content에서 JSON/list/dict 구조를 best-effort로 복원."""
    return extract_structured_content(content)


def _chunk_ref(chunk: dict[str, Any]) -> str:
    standard_id = chunk.get("standard_id") or chunk.get("standard") or "-"
    para = chunk.get("para_number") or chunk.get("paragraph") or "N/A"
    component = chunk.get("component") or "-"
    section = chunk.get("section_title") or chunk.get("section") or "-"
    return f"{standard_id} 문단 {para} ({component}, {section})"


def _chunk_excerpt(chunk: dict[str, Any]) -> str:
    for key in ("key_excerpt", "content_markdown", "original_text", "text"):
        value = chunk.get(key)
        if value:
            return _one_line(value, limit=260)
    return ""


def _build_chunks_digest(chunks: list[Any], max_items: int = 5) -> list[str]:
    lines: list[str] = []
    for item in chunks[:max_items]:
        if not isinstance(item, dict):
            continue
        ref = _chunk_ref(item)
        excerpt = _chunk_excerpt(item)
        reason = _one_line(item.get("why_relevant"), limit=160)
        if excerpt and reason:
            lines.append(f"- {ref}: {excerpt} / relevance: {reason}")
        elif excerpt:
            lines.append(f"- {ref}: {excerpt}")
        else:
            lines.append(f"- {ref}")
    return lines


def _build_retrieval_digest(
    tool_name: str,
    content: Any,
    max_chars: int,
) -> str | None:
    """검색 결과 원문을 다음 턴용 citation digest로 축약."""
    data = _load_structured_content(content)
    if data is None:
        return None

    lines = [f"[Previous retrieval context: {tool_name}]"]

    if isinstance(data, dict):
        synthesis = data.get("synthesis")
        if synthesis:
            lines.append(f"synthesis: {_one_line(synthesis, limit=600)}")

        chunks = data.get("chunks")
        if isinstance(chunks, list) and chunks:
            lines.append("chunks:")
            lines.extend(_build_chunks_digest(chunks))

        if "chunks" not in data:
            lines.append("chunks:")
            lines.extend(_build_chunks_digest([data], max_items=1))

        notes = data.get("notes")
        if notes:
            lines.append(f"notes: {_one_line(notes, limit=300)}")

    elif isinstance(data, list):
        chunk_lines = _build_chunks_digest(data)
        if not chunk_lines:
            return None
        lines.append("chunks:")
        lines.extend(chunk_lines)

    else:
        return None

    if len(lines) <= 1:
        return None
    return _truncate("\n".join(lines), max_chars)


def _replacement_content(
    tool_name: str,
    content: Any,
    max_digest_chars: int,
) -> str | None:
    if tool_name in RETRIEVAL_CONTEXT_TOOLS:
        digest = _build_retrieval_digest(
            tool_name=tool_name,
            content=content,
            max_chars=max_digest_chars,
        )
        if digest:
            return digest

    if isinstance(content, str) and len(content) >= MIN_COMPACT_LENGTH:
        return PLACEHOLDER_TEMPLATE.format(tool_name=tool_name)

    return None


DEFAULT_ARCHIVE_DIR = Path("./.transcripts")


def _extract_thread_id(runtime: Any) -> str:
    """Runtime.config에서 thread_id 추출. 없으면 'unknown'."""
    if runtime is None:
        return "unknown"
    try:
        config = getattr(runtime, "config", None) or {}
        configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
        thread_id = configurable.get("thread_id")
        return thread_id if thread_id else "unknown"
    except Exception:
        return "unknown"


def _tool_calls_by_id(messages: list[AnyMessage]) -> dict[str, dict[str, Any]]:
    calls: dict[str, dict[str, Any]] = {}
    for msg in messages:
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls and isinstance(msg, AIMessage):
            tool_calls = msg.tool_calls
        if not isinstance(tool_calls, list):
            continue
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            call_id = call.get("id")
            if call_id:
                calls[str(call_id)] = call
    return calls


def _tool_call_args(
    msg: ToolMessage,
    tool_calls_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    call = tool_calls_by_id.get(msg.tool_call_id or "")
    args = call.get("args") if call else None
    return args if isinstance(args, dict) else {}


def _source_tool_name(
    msg: ToolMessage,
    tool_calls_by_id: dict[str, dict[str, Any]],
) -> str:
    tool_name = msg.name or "unknown"
    if tool_name == "task":
        subagent_type = _tool_call_args(msg, tool_calls_by_id).get("subagent_type")
        if isinstance(subagent_type, str) and subagent_type:
            return subagent_type
    return tool_name


class MicroCompactMiddleware(AgentMiddleware):
    """오래된 tool_result를 플레이스홀더로 교체하여 토큰 절감.

    Args:
        trigger_tokens: 이 추정 토큰 수 미만이면 no-op (캐시 보호).
        keep_recent: 최근 N개의 tool_result는 보존.
        max_digest_chars: 검색 결과를 digest로 치환할 때 남길 최대 문자 수.
        archive_dir: 치환 전 원본을 JSONL로 append 저장할 디렉터리.
            None이면 아카이브 비활성. 기본값: ``./.transcripts``.
        archive_enabled: transcript archive 활성화 여부. None이면 환경변수 사용.
        archive_retention_days: 오래된 transcript 파일 삭제 기준(일).
        archive_max_file_mb: transcript 파일 크기 삭제 기준(MB).
        context_store: retrieval memory 저장소. None이면 memory 저장 비활성.
        memory_enabled: retrieval memory 저장 활성화 여부. None이면 환경변수 사용.
    """

    def __init__(
        self,
        trigger_tokens: int = 50_000,
        keep_recent: int = 3,
        max_digest_chars: int = DEFAULT_MAX_DIGEST_CHARS,
        archive_dir: Path | str | None = DEFAULT_ARCHIVE_DIR,
        archive_enabled: bool | None = None,
        archive_retention_days: int | None = None,
        archive_max_file_mb: float | None = None,
        context_store: RetrievalMemoryStore | None = None,
        memory_enabled: bool | None = None,
    ) -> None:
        self.trigger_tokens = trigger_tokens
        self.keep_recent = keep_recent
        self.max_digest_chars = max_digest_chars
        enabled = (
            _env_bool("TRANSCRIPT_ARCHIVE_ENABLED", True)
            if archive_enabled is None
            else archive_enabled
        )
        self.archive_dir: Path | None = (
            Path(archive_dir) if enabled and archive_dir is not None else None
        )
        self.archive_retention_days = (
            _env_int("TRANSCRIPT_RETENTION_DAYS", DEFAULT_ARCHIVE_RETENTION_DAYS)
            if archive_retention_days is None
            else archive_retention_days
        )
        self.archive_max_file_mb = (
            _env_float("TRANSCRIPT_MAX_FILE_MB", DEFAULT_ARCHIVE_MAX_FILE_MB)
            if archive_max_file_mb is None
            else archive_max_file_mb
        )
        self.context_store = context_store
        self.memory_enabled = (
            _env_bool("CONTEXT_MEMORY_ENABLED", True)
            if memory_enabled is None
            else memory_enabled
        )

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None
        if estimate_tokens(messages) < self.trigger_tokens:
            return None

        # 교체 대상 tool_result 수집 (ToolMessage만)
        tool_msgs: list[ToolMessage] = [
            m for m in messages if isinstance(m, ToolMessage)
        ]
        if len(tool_msgs) <= self.keep_recent:
            return None

        # 최근 N개 제외 → 오래된 것만 후보
        old = tool_msgs[: -self.keep_recent] if self.keep_recent > 0 else tool_msgs
        tool_calls = _tool_calls_by_id(messages)

        updates: list[ToolMessage] = []
        originals: list[ToolMessage] = []
        for msg in old:
            tool_name = _source_tool_name(msg, tool_calls)
            if tool_name in PRESERVE_TOOLS:
                continue

            replacement_content = _replacement_content(
                tool_name=tool_name,
                content=msg.content,
                max_digest_chars=self.max_digest_chars,
            )
            if replacement_content is None:
                continue

            originals.append(msg)
            # 같은 id·tool_call_id로 교체 메시지 생성
            replacement = ToolMessage(
                content=replacement_content,
                name=tool_name,
                tool_call_id=msg.tool_call_id,
                id=msg.id,
            )
            updates.append(replacement)

        if not updates:
            return None

        # 치환 전 원본 아카이브 (best-effort, 실패해도 압축은 진행)
        if self.archive_dir is not None:
            self._archive(originals, runtime, tool_calls)

        if self.context_store is not None and self.memory_enabled:
            self._save_context_memory(originals, runtime, tool_calls)

        return {"messages": updates}

    def _cleanup_archive_dir(self) -> None:
        if self.archive_dir is None or not self.archive_dir.exists():
            return

        now = time.time()
        max_age_seconds = max(self.archive_retention_days, 0) * 86400
        max_bytes = max(self.archive_max_file_mb, 0) * 1024 * 1024

        for path in self.archive_dir.glob("*.jsonl"):
            try:
                stat = path.stat()
                too_old = max_age_seconds > 0 and now - stat.st_mtime > max_age_seconds
                too_large = max_bytes > 0 and stat.st_size > max_bytes
                if too_old or too_large:
                    path.unlink()
            except OSError as exc:
                logger.warning("Transcript cleanup failed for %s: %s", path, exc)

    def _archive(
        self,
        originals: list[ToolMessage],
        runtime: Any,
        tool_calls_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """JSONL 한 줄로 한 압축 이벤트 기록. thread별 파일 append."""
        try:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            self._cleanup_archive_dir()
            thread_id = _extract_thread_id(runtime)
            date = time.strftime("%Y%m%d", time.localtime())
            path = self.archive_dir / f"{thread_id}_{date}.jsonl"
            event = {
                "timestamp": time.time(),
                "thread_id": thread_id,
                "messages": [
                    {
                        "msg_id": m.id,
                        "tool_call_id": m.tool_call_id,
                        "tool_name": m.name or "unknown",
                        "source_tool": _source_tool_name(m, tool_calls_by_id),
                        "original_content": m.content,
                    }
                    for m in originals
                ],
            }
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as exc:
            # 아카이브 실패는 무시 (압축 자체는 성공해야 함)
            logger.warning("MicroCompact archive failed: %s", exc)

    def _save_context_memory(
        self,
        originals: list[ToolMessage],
        runtime: Any,
        tool_calls_by_id: dict[str, dict[str, Any]],
    ) -> None:
        thread_id = _extract_thread_id(runtime)
        for msg in originals:
            source_tool = _source_tool_name(msg, tool_calls_by_id)
            if source_tool not in RETRIEVAL_CONTEXT_TOOLS:
                continue
            try:
                self.context_store.save_from_tool_result(
                    thread_id=thread_id,
                    source_tool=source_tool,
                    content=msg.content,
                    tool_args=_tool_call_args(msg, tool_calls_by_id),
                )
            except Exception as exc:
                logger.warning("Context memory save failed: %s", exc)
