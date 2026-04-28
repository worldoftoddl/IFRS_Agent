"""Context memory tools for reusing prior retrieval results."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from app.context_memory import DEFAULT_CONTEXT_DIR, RetrievalMemoryStore

logger = logging.getLogger(__name__)

RETRIEVAL_MEMORY_SOURCE_TOOLS: set[str] = {
    "retrieval-distiller",
    "audit-retrieval-distiller",
    "retrieve_ifrs",
    "retrieve_audit_standards",
    "search_single_standard",
    "search_single_audit_standard",
    "lookup_paragraph",
    "lookup_audit_paragraph",
}


def _extract_thread_id(runtime: Any) -> str:
    try:
        config = getattr(runtime, "config", None) or {}
        configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
        return configurable.get("thread_id") or "unknown"
    except Exception:
        return "unknown"


def _as_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _normalize_domain(domain: str | None) -> str | None:
    if domain is None:
        return None
    value = domain.strip().lower()
    return value if value in {"ifrs", "audit"} else None


def _source_tool_name(tool_call: dict[str, Any]) -> str:
    name = str(tool_call.get("name") or "unknown")
    args = tool_call.get("args")
    if name == "task" and isinstance(args, dict):
        subagent_type = args.get("subagent_type")
        if isinstance(subagent_type, str) and subagent_type:
            return subagent_type
    return name


def _tool_args(tool_call: dict[str, Any]) -> dict[str, Any]:
    args = tool_call.get("args")
    return args if isinstance(args, dict) else {}


def _build_tools(store: RetrievalMemoryStore) -> list:
    @tool
    def context_search(
        query: str,
        runtime: ToolRuntime,
        domain: str | None = None,
        limit: int = 5,
    ) -> str:
        """이전 검색 메모리에서 후속 질문과 관련된 근거를 찾습니다.

        "방금", "위 문단", "그 기준"처럼 이전 검색 결과를 이어받는 질문이면
        새 검색을 하기 전에 사용하세요. 결과에는 원문 전체가 아니라 재사용 가능한
        요약, 기준서 ID, 문단 번호, 짧은 발췌가 포함됩니다.

        Args:
            query: 현재 후속 질문 또는 찾을 키워드
            domain: ifrs | audit 중 선택. 모르면 생략합니다.
            limit: 반환할 최대 메모리 수
        """
        thread_id = _extract_thread_id(runtime)
        results = store.search(
            thread_id=thread_id,
            query=query,
            domain=_normalize_domain(domain),
            limit=limit,
            include_original=False,
        )
        if not results:
            return "No context memory found."
        return _as_json({"results": results})

    @tool
    def context_get(memory_id: str, runtime: ToolRuntime) -> str:
        """특정 retrieval memory의 상세 내용을 조회합니다.

        context_search/context_list가 반환한 id를 사용하세요. 정확한 원문이 memory에
        보관되어 있으면 original_text도 함께 반환됩니다. 그래도 공식 원문 재인용이
        필요하면 lookup_paragraph 또는 lookup_audit_paragraph로 DB를 다시 조회하세요.

        Args:
            memory_id: context_search/context_list 결과의 id
        """
        thread_id = _extract_thread_id(runtime)
        entry = store.get(thread_id=thread_id, memory_id=memory_id, include_original=True)
        if entry is None:
            return f"Context memory not found: {memory_id}"
        return _as_json(entry)

    @tool
    def context_list(
        runtime: ToolRuntime,
        domain: str | None = None,
        limit: int = 5,
    ) -> str:
        """현재 thread의 최근 retrieval memory 목록을 조회합니다.

        후속 질문이 무엇을 가리키는지 애매할 때 먼저 목록을 확인하세요.

        Args:
            domain: ifrs | audit 중 선택. 모르면 생략합니다.
            limit: 반환할 최대 메모리 수
        """
        thread_id = _extract_thread_id(runtime)
        results = store.list_recent(
            thread_id=thread_id,
            domain=_normalize_domain(domain),
            limit=limit,
            include_original=False,
        )
        if not results:
            return "No context memory found."
        return _as_json({"results": results})

    return [context_search, context_get, context_list]


class ContextMemoryMiddleware(AgentMiddleware):
    """Expose thread-scoped retrieval memory as tools."""

    def __init__(
        self,
        store: RetrievalMemoryStore | None = None,
        context_dir: Path | str = DEFAULT_CONTEXT_DIR,
        max_entries: int = 20,
    ) -> None:
        self.store = store or RetrievalMemoryStore(
            root_dir=Path(context_dir),
            max_entries=max_entries,
        )
        self.tools = _build_tools(self.store)

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        result = handler(request)
        if isinstance(result, ToolMessage):
            self._save_tool_result(request, result)
        return result

    def _save_tool_result(self, request: Any, result: ToolMessage) -> None:
        tool_call = getattr(request, "tool_call", {}) or {}
        if not isinstance(tool_call, dict):
            return
        source_tool = _source_tool_name(tool_call)
        if source_tool not in RETRIEVAL_MEMORY_SOURCE_TOOLS:
            return
        try:
            self.store.save_from_tool_result(
                thread_id=_extract_thread_id(getattr(request, "runtime", None)),
                source_tool=source_tool,
                content=result.content,
                tool_args=_tool_args(tool_call),
            )
        except Exception as exc:
            logger.warning("Context memory save failed: %s", exc)
