"""MicroCompactMiddleware 단위 테스트 — s06 Layer 1 압축.

오래된 tool_result를 플레이스홀더로 교체하여 토큰 누적 억제.
캐시 무효화 리스크 관리 위해 threshold 이하에선 no-op.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.compact_middleware import (
    DEFAULT_MAX_DIGEST_CHARS,
    PLACEHOLDER_TEMPLATE,
    PRESERVE_TOOLS,
    RETRIEVAL_CONTEXT_TOOLS,
    MicroCompactMiddleware,
    estimate_tokens,
)


def _tool_msg(content: str, name: str, tool_call_id: str, msg_id: str) -> ToolMessage:
    return ToolMessage(
        content=content,
        name=name,
        tool_call_id=tool_call_id,
        id=msg_id,
    )


def _big(content_size: int = 5000, prefix: str = "x") -> str:
    return prefix * content_size


class TestStructure:
    def test_instantiable(self):
        mw = MicroCompactMiddleware()
        assert mw is not None

    def test_has_before_model(self):
        mw = MicroCompactMiddleware()
        assert callable(getattr(mw, "before_model", None))

    def test_has_no_tools(self):
        """Layer 1은 도구 노출 없음 — 백그라운드 훅만."""
        mw = MicroCompactMiddleware()
        assert not getattr(mw, "tools", [])

    def test_configurable_threshold(self):
        mw = MicroCompactMiddleware(trigger_tokens=100_000)
        assert mw.trigger_tokens == 100_000

    def test_configurable_keep_recent(self):
        mw = MicroCompactMiddleware(keep_recent=5)
        assert mw.keep_recent == 5

    def test_configurable_max_digest_chars(self):
        mw = MicroCompactMiddleware(max_digest_chars=1200)
        assert mw.max_digest_chars == 1200

    def test_default_digest_budget_exported(self):
        assert DEFAULT_MAX_DIGEST_CHARS > 0


class TestBelowThreshold:
    """threshold 이하 — no-op 유지 (캐시 보호)."""

    def test_small_messages_noop(self):
        mw = MicroCompactMiddleware(trigger_tokens=50_000)
        state = {
            "messages": [
                HumanMessage(content="짧은 질문"),
                AIMessage(content="짧은 답변"),
            ]
        }
        result = mw.before_model(state, None)
        assert result is None

    def test_empty_messages_noop(self):
        mw = MicroCompactMiddleware()
        result = mw.before_model({"messages": []}, None)
        assert result is None

    def test_no_tool_messages_noop(self):
        """ToolMessage 없으면 압축 대상 없음."""
        mw = MicroCompactMiddleware(trigger_tokens=1000)
        state = {
            "messages": [HumanMessage(content=_big(2000))] * 3
        }
        # 토큰은 높지만 ToolMessage가 없으니 no-op
        result = mw.before_model(state, None)
        assert result is None


class TestAboveThreshold:
    """threshold 초과 — tool_result 플레이스홀더 교체."""

    def _build_state_with_tool_results(self, n: int) -> dict:
        """n개의 AI+Tool 메시지 쌍을 만들어 큰 state 구성."""
        msgs = [HumanMessage(content="질문")]
        for i in range(n):
            msgs.append(
                AIMessage(
                    content="",
                    tool_calls=[{"name": "retrieve_ifrs", "args": {}, "id": f"call_{i}"}],
                )
            )
            msgs.append(
                _tool_msg(
                    content=_big(5000, f"r{i}"),
                    name="retrieve_ifrs",
                    tool_call_id=f"call_{i}",
                    msg_id=f"tool_{i}",
                )
            )
        return {"messages": msgs}

    def test_triggers_when_above_threshold(self):
        mw = MicroCompactMiddleware(trigger_tokens=10_000, keep_recent=3)
        state = self._build_state_with_tool_results(10)
        result = mw.before_model(state, None)
        assert result is not None
        assert "messages" in result

    def test_recent_n_preserved(self):
        mw = MicroCompactMiddleware(trigger_tokens=10_000, keep_recent=3)
        state = self._build_state_with_tool_results(10)
        result = mw.before_model(state, None)
        updates = {m.id: m for m in result["messages"]}
        # 최근 3개(tool_7, tool_8, tool_9)는 update 대상에 없어야 함
        assert "tool_9" not in updates
        assert "tool_8" not in updates
        assert "tool_7" not in updates

    def test_old_results_replaced_with_placeholder(self):
        mw = MicroCompactMiddleware(trigger_tokens=10_000, keep_recent=3)
        state = self._build_state_with_tool_results(10)
        result = mw.before_model(state, None)
        updates = {m.id: m for m in result["messages"]}
        # 오래된 tool_0 ~ tool_6은 플레이스홀더로 교체
        for i in range(7):
            assert f"tool_{i}" in updates
            msg = updates[f"tool_{i}"]
            assert "[Previous: used retrieve_ifrs]" in msg.content

    def test_tool_call_id_preserved(self):
        """tool_call_id 보존 — LLM이 매칭 끊기면 에러."""
        mw = MicroCompactMiddleware(trigger_tokens=10_000, keep_recent=3)
        state = self._build_state_with_tool_results(10)
        result = mw.before_model(state, None)
        for m in result["messages"]:
            original_id = m.id.replace("tool_", "call_")
            assert m.tool_call_id == original_id


class TestPreserveList:
    """PRESERVE_TOOLS 목록의 도구 결과는 오래됐어도 보존."""

    def test_verify_arithmetic_preserved(self):
        assert "verify_arithmetic" in PRESERVE_TOOLS

    def test_get_standard_info_preserved(self):
        assert "get_standard_info" in PRESERVE_TOOLS

    def test_preserved_tool_not_compacted(self):
        """오래된 verify_arithmetic 결과는 threshold 초과해도 교체 안 됨."""
        mw = MicroCompactMiddleware(trigger_tokens=10_000, keep_recent=3)
        msgs = [HumanMessage(content="질문")]
        # 앞쪽에 verify_arithmetic
        msgs.append(
            AIMessage(
                content="",
                tool_calls=[{"name": "verify_arithmetic", "args": {}, "id": "call_va"}],
            )
        )
        msgs.append(
            _tool_msg(
                content=_big(5000, "va"),
                name="verify_arithmetic",
                tool_call_id="call_va",
                msg_id="tool_va",
            )
        )
        # 그 뒤 대량의 retrieve_ifrs 호출
        for i in range(10):
            msgs.append(
                AIMessage(
                    content="",
                    tool_calls=[{"name": "retrieve_ifrs", "args": {}, "id": f"call_{i}"}],
                )
            )
            msgs.append(
                _tool_msg(
                    content=_big(5000, f"r{i}"),
                    name="retrieve_ifrs",
                    tool_call_id=f"call_{i}",
                    msg_id=f"tool_{i}",
                )
            )
        result = mw.before_model({"messages": msgs}, None)
        updates = {m.id: m for m in result["messages"]}
        # verify_arithmetic은 교체 대상에 없어야 함
        assert "tool_va" not in updates


class TestRetrievalContextDigest:
    """검색 결과는 원문 전체 대신 citation 중심 digest로 남긴다."""

    def test_retrieval_tools_are_registered(self):
        assert "retrieval-distiller" in RETRIEVAL_CONTEXT_TOOLS
        assert "audit-retrieval-distiller" in RETRIEVAL_CONTEXT_TOOLS
        assert "retrieve_ifrs" in RETRIEVAL_CONTEXT_TOOLS

    def test_distiller_json_compacted_to_digest(self):
        mw = MicroCompactMiddleware(
            trigger_tokens=1,
            keep_recent=0,
            max_digest_chars=1200,
            archive_dir=None,
        )
        full_original = "FULL_ORIGINAL_SHOULD_NOT_REMAIN " * 200
        payload = {
            "synthesis": "수익은 약속한 재화나 용역을 고객에게 이전할 때 인식한다.",
            "chunks": [
                {
                    "standard_id": "K-IFRS 1115",
                    "para_number": "31",
                    "component": "main",
                    "section_title": "수익의 인식",
                    "original_text": full_original,
                    "key_excerpt": "수행의무를 이행할 때 수익을 인식한다.",
                    "why_relevant": "수익 인식 시점을 직접 설명한다.",
                }
            ],
            "notes": "",
        }
        msgs = [
            HumanMessage(content="q"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "retrieval-distiller", "args": {}, "id": "c1"}
                ],
            ),
            ToolMessage(
                content=json.dumps(payload, ensure_ascii=False),
                name="retrieval-distiller",
                tool_call_id="c1",
                id="t1",
            ),
        ]

        result = mw.before_model({"messages": msgs}, None)
        assert result is not None
        digest = result["messages"][0].content
        assert digest.startswith("[Previous retrieval context: retrieval-distiller]")
        assert "K-IFRS 1115" in digest
        assert "문단 31" in digest
        assert "수행의무를 이행할 때" in digest
        assert "FULL_ORIGINAL_SHOULD_NOT_REMAIN" not in digest

    def test_raw_retrieval_list_compacted_to_digest(self):
        mw = MicroCompactMiddleware(
            trigger_tokens=1,
            keep_recent=0,
            max_digest_chars=1000,
            archive_dir=None,
        )
        payload = [
            {
                "standard_id": "K-IFRS 1037",
                "para_number": "14",
                "component": "main",
                "section_title": "충당부채",
                "content_markdown": (
                    "충당부채는 현재의무, 유출가능성, 신뢰성 있는 추정이 "
                    "있을 때 인식한다."
                ),
            }
        ]
        msgs = [
            HumanMessage(content="q"),
            AIMessage(
                content="",
                tool_calls=[{"name": "retrieve_ifrs", "args": {}, "id": "c1"}],
            ),
            ToolMessage(
                content=json.dumps(payload, ensure_ascii=False),
                name="retrieve_ifrs",
                tool_call_id="c1",
                id="t1",
            ),
        ]

        result = mw.before_model({"messages": msgs}, None)
        assert result is not None
        digest = result["messages"][0].content
        assert digest.startswith("[Previous retrieval context: retrieve_ifrs]")
        assert "K-IFRS 1037" in digest
        assert "문단 14" in digest
        assert "현재의무" in digest


class TestEdgeCases:
    def test_short_tool_result_skipped(self):
        """짧은 content(100자 미만)는 교체 이득 없으니 건너뜀."""
        mw = MicroCompactMiddleware(trigger_tokens=5_000, keep_recent=1)
        msgs = [HumanMessage(content="q")]
        # 짧은 tool_result 2개 + 이후 큰 tool_result로 threshold 넘김
        msgs.append(AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c1"}]))
        msgs.append(
            _tool_msg(content="짧은 결과", name="x", tool_call_id="c1", msg_id="t1")
        )
        msgs.append(
            AIMessage(
                content="",
                tool_calls=[{"name": "retrieve_ifrs", "args": {}, "id": "c2"}],
            )
        )
        msgs.append(
            _tool_msg(
                content=_big(10000, "r"),
                name="retrieve_ifrs",
                tool_call_id="c2",
                msg_id="t2",
            )
        )
        result = mw.before_model({"messages": msgs}, None)
        if result is not None:
            updates = {m.id: m for m in result["messages"]}
            # 짧은 결과 t1은 교체 대상 아님
            assert "t1" not in updates

    def test_list_content_skipped(self):
        """ToolMessage content가 list일 경우 건드리지 않음 (복잡한 블록)."""
        mw = MicroCompactMiddleware(trigger_tokens=1_000, keep_recent=1)
        msgs = [
            HumanMessage(content="q"),
            AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c1"}]),
            ToolMessage(
                content=[{"type": "text", "text": _big(10000)}],
                name="x",
                tool_call_id="c1",
                id="t1",
            ),
            AIMessage(content="", tool_calls=[{"name": "y", "args": {}, "id": "c2"}]),
            _tool_msg(content=_big(10000, "y"), name="y", tool_call_id="c2", msg_id="t2"),
            AIMessage(content="", tool_calls=[{"name": "z", "args": {}, "id": "c3"}]),
            _tool_msg(content=_big(10000, "z"), name="z", tool_call_id="c3", msg_id="t3"),
        ]
        result = mw.before_model({"messages": msgs}, None)
        updates = {m.id: m for m in (result["messages"] if result else [])}
        # t1은 list content라 제외, t2는 오래됐으니 교체
        assert "t1" not in updates

    def test_estimate_tokens_function(self):
        """토큰 추정은 문자 수/4의 단순 방식."""
        assert estimate_tokens([]) == 0
        # 문자 수에 비례
        msgs = [HumanMessage(content="a" * 400)]
        assert estimate_tokens(msgs) > 50

    def test_placeholder_template_has_tool_name(self):
        formatted = PLACEHOLDER_TEMPLATE.format(tool_name="retrieve_ifrs")
        assert "retrieve_ifrs" in formatted
        assert "Previous" in formatted


# ── Option 2: Layer 1 치환 전 원본 아카이브 ────────────────────────────

class _FakeRuntime:
    """LangGraph Runtime의 최소 stub (config만 있으면 됨)."""

    def __init__(self, thread_id: str | None = None):
        self.config = (
            {"configurable": {"thread_id": thread_id}} if thread_id else {}
        )


class TestArchiveStructure:
    def test_archive_dir_default(self):
        mw = MicroCompactMiddleware()
        assert mw.archive_dir is not None
        assert isinstance(mw.archive_dir, Path)

    def test_archive_can_be_disabled(self):
        mw = MicroCompactMiddleware(archive_dir=None)
        assert mw.archive_dir is None

    def test_custom_archive_dir(self, tmp_path: Path):
        mw = MicroCompactMiddleware(archive_dir=tmp_path / "t")
        assert mw.archive_dir == tmp_path / "t"


class TestArchiveBehavior:
    @pytest.fixture
    def mw(self, tmp_path: Path) -> MicroCompactMiddleware:
        return MicroCompactMiddleware(
            trigger_tokens=10_000,
            keep_recent=3,
            archive_dir=tmp_path / "transcripts",
        )

    def _big(self, n=5000, prefix="x"):
        return prefix * n

    def _state_with_compacting(self, n: int = 10) -> dict:
        msgs = [HumanMessage(content="q")]
        for i in range(n):
            msgs.append(
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "retrieve_ifrs", "args": {}, "id": f"c_{i}"}
                    ],
                )
            )
            msgs.append(
                ToolMessage(
                    content=self._big(5000, f"r{i}"),
                    name="retrieve_ifrs",
                    tool_call_id=f"c_{i}",
                    id=f"t_{i}",
                )
            )
        return {"messages": msgs}

    def test_no_trigger_no_archive(self, mw, tmp_path: Path):
        """threshold 이하면 아카이브 폴더도 안 만든다."""
        mw.before_model(
            {"messages": [HumanMessage(content="short")]},
            _FakeRuntime("th-1"),
        )
        assert not (tmp_path / "transcripts").exists()

    def test_archive_file_created_on_trigger(self, mw, tmp_path: Path):
        mw.before_model(self._state_with_compacting(10), _FakeRuntime("th-1"))
        files = list((tmp_path / "transcripts").glob("*.jsonl"))
        assert len(files) == 1
        assert "th-1" in files[0].name

    def test_archive_contains_original_content(self, mw, tmp_path: Path):
        mw.before_model(self._state_with_compacting(10), _FakeRuntime("th-1"))
        files = list((tmp_path / "transcripts").glob("*.jsonl"))
        lines = files[0].read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1  # 한 번의 압축 = 한 줄
        event = json.loads(lines[0])
        # 치환된 오래된 메시지 원본이 포함되어야 함
        assert "messages" in event
        assert len(event["messages"]) == 7  # 10개 중 최근 3 제외
        # 원본 content가 잘렸든 아니든 포함되어 있어야 함
        first = event["messages"][0]
        assert first["tool_name"] == "retrieve_ifrs"
        assert "r0" in first["original_content"]

    def test_archive_event_has_metadata(self, mw, tmp_path: Path):
        mw.before_model(self._state_with_compacting(10), _FakeRuntime("th-1"))
        files = list((tmp_path / "transcripts").glob("*.jsonl"))
        event = json.loads(files[0].read_text().strip().split("\n")[0])
        assert "timestamp" in event
        assert "thread_id" in event
        assert event["thread_id"] == "th-1"

    def test_multiple_events_append(self, mw, tmp_path: Path):
        mw.before_model(self._state_with_compacting(10), _FakeRuntime("th-1"))
        mw.before_model(self._state_with_compacting(12), _FakeRuntime("th-1"))
        files = list((tmp_path / "transcripts").glob("*.jsonl"))
        assert len(files) == 1  # 같은 thread_id → 같은 파일
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 2

    def test_different_threads_different_files(self, mw, tmp_path: Path):
        mw.before_model(self._state_with_compacting(10), _FakeRuntime("th-A"))
        mw.before_model(self._state_with_compacting(10), _FakeRuntime("th-B"))
        files = list((tmp_path / "transcripts").glob("*.jsonl"))
        names = sorted(f.name for f in files)
        assert len(names) == 2
        assert any("th-A" in n for n in names)
        assert any("th-B" in n for n in names)

    def test_missing_thread_id_uses_unknown(self, mw, tmp_path: Path):
        mw.before_model(self._state_with_compacting(10), _FakeRuntime(None))
        files = list((tmp_path / "transcripts").glob("*.jsonl"))
        assert len(files) == 1
        assert "unknown" in files[0].name

    def test_none_runtime_safe(self, mw):
        """runtime=None 이어도 크래시 없음."""
        # 예외 없이 동작해야 함
        mw.before_model(self._state_with_compacting(10), None)

    def test_archive_disabled_no_file(self, tmp_path: Path):
        mw = MicroCompactMiddleware(
            trigger_tokens=10_000,
            keep_recent=3,
            archive_dir=None,
        )
        result = mw.before_model(
            self._state_with_compacting(10), _FakeRuntime("th-1")
        )
        assert result is not None  # 압축은 여전히 동작
        assert not (tmp_path / "transcripts").exists()

    def test_archive_excludes_preserved_tools(self, mw, tmp_path: Path):
        """PRESERVE_TOOLS는 치환 안 되므로 아카이브에도 안 들어감."""
        msgs = [HumanMessage(content="q")]
        msgs.append(
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "verify_arithmetic", "args": {}, "id": "c_va"}
                ],
            )
        )
        msgs.append(
            ToolMessage(
                content=self._big(5000, "va"),
                name="verify_arithmetic",
                tool_call_id="c_va",
                id="t_va",
            )
        )
        for i in range(10):
            msgs.append(
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "retrieve_ifrs", "args": {}, "id": f"c_{i}"}
                    ],
                )
            )
            msgs.append(
                ToolMessage(
                    content=self._big(5000, f"r{i}"),
                    name="retrieve_ifrs",
                    tool_call_id=f"c_{i}",
                    id=f"t_{i}",
                )
            )
        mw.before_model({"messages": msgs}, _FakeRuntime("th-1"))
        files = list((tmp_path / "transcripts").glob("*.jsonl"))
        event = json.loads(files[0].read_text().strip())
        tool_names = [m["tool_name"] for m in event["messages"]]
        assert "verify_arithmetic" not in tool_names
