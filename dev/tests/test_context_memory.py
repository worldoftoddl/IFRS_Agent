"""RetrievalMemoryStore and ContextMemoryMiddleware tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage

from app.context_memory import RetrievalMemoryStore, normalize_retrieval_payload
from app.context_memory_middleware import ContextMemoryMiddleware


class _FakeRuntime:
    def __init__(self, thread_id: str = "thread-1") -> None:
        self.config = {"configurable": {"thread_id": thread_id}}


class _FakeToolRequest:
    def __init__(self, tool_call: dict, thread_id: str = "thread-1") -> None:
        self.tool_call = tool_call
        self.runtime = _FakeRuntime(thread_id)


@pytest.fixture
def store(tmp_path: Path) -> RetrievalMemoryStore:
    return RetrievalMemoryStore(root_dir=tmp_path / "context", max_entries=20)


def _distiller_content() -> str:
    payload = {
        "synthesis": "충당부채는 보고기간 말 최선의 추정치로 조정한다.",
        "chunks": [
            {
                "standard_id": "K-IFRS 1037",
                "para_number": "59",
                "component": "main",
                "section_title": "충당부채의 변동",
                "original_text": "59\t보고기간 말마다 충당부채의 잔액을 검토하고 조정한다.",
                "why_relevant": "후속 측정과 환입을 직접 설명한다.",
                "key_excerpt": "보고기간 말마다 충당부채의 잔액을 검토",
            }
        ],
        "notes": "",
    }
    return "검색 완료\n\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


class TestNormalizeRetrievalPayload:
    def test_extracts_json_code_block(self):
        result = normalize_retrieval_payload(
            source_tool="retrieval-distiller",
            content=_distiller_content(),
            tool_args={"description": "충당부채 후속 측정"},
        )
        assert result is not None
        assert result["domain"] == "ifrs"
        assert result["query"] == "충당부채 후속 측정"
        assert result["chunks"][0]["standard_id"] == "K-IFRS 1037"

    def test_infers_audit_domain(self):
        payload = {
            "chunks": [
                {
                    "standard_id": "ISA-320",
                    "para_number": "A13.",
                    "content_markdown": "수행중요성은 전문가적 판단이 수반된다.",
                }
            ]
        }
        result = normalize_retrieval_payload(
            source_tool="audit-retrieval-distiller",
            content=json.dumps(payload, ensure_ascii=False),
        )
        assert result is not None
        assert result["domain"] == "audit"

    def test_unstructured_markdown_returns_none(self):
        result = normalize_retrieval_payload(
            source_tool="retrieval-distiller",
            content="# 검색 결과\n문단 몇 개",
        )
        assert result is None


class TestRetrievalMemoryStore:
    def test_save_and_search_without_originals(self, store: RetrievalMemoryStore):
        entry = store.save_from_tool_result(
            thread_id="thread-1",
            source_tool="retrieval-distiller",
            content=_distiller_content(),
            tool_args={"description": "충당부채 후속 측정"},
        )
        assert entry is not None

        results = store.search(thread_id="thread-1", query="충당부채 환입")
        assert len(results) == 1
        assert results[0]["id"] == entry["id"]
        assert "original_text" not in results[0]["chunks"][0]

    def test_get_includes_original_text(self, store: RetrievalMemoryStore):
        entry = store.save_from_tool_result(
            thread_id="thread-1",
            source_tool="retrieval-distiller",
            content=_distiller_content(),
        )
        assert entry is not None
        detail = store.get("thread-1", entry["id"], include_original=True)
        assert detail is not None
        assert "original_text" in detail["chunks"][0]
        assert "보고기간 말마다" in detail["chunks"][0]["original_text"]

    def test_upserts_same_retrieval_signature(self, store: RetrievalMemoryStore):
        first = store.save_from_tool_result(
            thread_id="thread-1",
            source_tool="retrieval-distiller",
            content=_distiller_content(),
            tool_args={"description": "충당부채 후속 측정"},
        )
        second = store.save_from_tool_result(
            thread_id="thread-1",
            source_tool="retrieval-distiller",
            content=_distiller_content(),
            tool_args={"description": "충당부채 후속 측정"},
        )
        assert first is not None and second is not None
        assert first["id"] == second["id"]
        assert len(store.list_recent("thread-1")) == 1

    def test_retention_limits_entries(self, tmp_path: Path):
        store = RetrievalMemoryStore(root_dir=tmp_path / "context", max_entries=2)
        for i in range(3):
            payload = {
                "chunks": [
                    {
                        "standard_id": f"K-IFRS 10{i}",
                        "para_number": str(i),
                        "content_markdown": f"내용 {i}",
                    }
                ]
            }
            store.save_from_tool_result(
                thread_id="thread-1",
                source_tool="retrieve_ifrs",
                content=json.dumps(payload, ensure_ascii=False),
                tool_args={"query": f"질문 {i}"},
            )

        assert len(store.list_recent("thread-1", limit=10)) == 2


class TestContextMemoryMiddleware:
    def test_exposes_context_tools(self, store: RetrievalMemoryStore):
        mw = ContextMemoryMiddleware(store=store)
        names = {tool.name for tool in mw.tools}
        assert names == {"context_search", "context_get", "context_list"}

    def test_context_search_tool_returns_json(self, store: RetrievalMemoryStore):
        entry = store.save_from_tool_result(
            thread_id="thread-1",
            source_tool="retrieval-distiller",
            content=_distiller_content(),
            tool_args={"description": "충당부채 후속 측정"},
        )
        assert entry is not None

        tools = {tool.name: tool for tool in ContextMemoryMiddleware(store=store).tools}
        result = tools["context_search"].func(
            query="충당부채",
            runtime=_FakeRuntime("thread-1"),
            domain="ifrs",
        )
        assert "K-IFRS 1037" in result
        assert "original_text" not in result

    def test_context_get_tool_returns_detail(self, store: RetrievalMemoryStore):
        entry = store.save_from_tool_result(
            thread_id="thread-1",
            source_tool="retrieval-distiller",
            content=_distiller_content(),
        )
        assert entry is not None

        tools = {tool.name: tool for tool in ContextMemoryMiddleware(store=store).tools}
        result = tools["context_get"].func(
            memory_id=entry["id"],
            runtime=_FakeRuntime("thread-1"),
        )
        assert "original_text" in result
        assert "K-IFRS 1037" in result

    def test_wrap_tool_call_saves_retrieval_result(self, store: RetrievalMemoryStore):
        mw = ContextMemoryMiddleware(store=store)
        request = _FakeToolRequest(
            {
                "name": "task",
                "args": {
                    "subagent_type": "retrieval-distiller",
                    "description": "충당부채 후속 측정",
                },
                "id": "call-1",
            }
        )

        def handler(_request):
            return ToolMessage(
                content=_distiller_content(),
                name="task",
                tool_call_id="call-1",
                id="tool-1",
            )

        result = mw.wrap_tool_call(request, handler)
        assert isinstance(result, ToolMessage)
        memories = store.search(thread_id="thread-1", query="충당부채")
        assert len(memories) == 1
        assert memories[0]["source_tool"] == "retrieval-distiller"
