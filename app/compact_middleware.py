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
import time
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AnyMessage, ToolMessage

logger = logging.getLogger(__name__)

PLACEHOLDER_TEMPLATE = "[Previous: used {tool_name}]"
MIN_COMPACT_LENGTH = 100  # 짧은 content는 교체 이득 없음

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


class MicroCompactMiddleware(AgentMiddleware):
    """오래된 tool_result를 플레이스홀더로 교체하여 토큰 절감.

    Args:
        trigger_tokens: 이 추정 토큰 수 미만이면 no-op (캐시 보호).
        keep_recent: 최근 N개의 tool_result는 보존.
        archive_dir: 치환 전 원본을 JSONL로 append 저장할 디렉터리.
            None이면 아카이브 비활성. 기본값: ``./.transcripts``.
    """

    def __init__(
        self,
        trigger_tokens: int = 50_000,
        keep_recent: int = 3,
        archive_dir: Path | str | None = DEFAULT_ARCHIVE_DIR,
    ) -> None:
        self.trigger_tokens = trigger_tokens
        self.keep_recent = keep_recent
        self.archive_dir: Path | None = (
            Path(archive_dir) if archive_dir is not None else None
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

        updates: list[ToolMessage] = []
        originals: list[ToolMessage] = []
        for msg in old:
            if not isinstance(msg.content, str):
                continue  # list/dict content는 복잡해서 건드리지 않음
            if len(msg.content) < MIN_COMPACT_LENGTH:
                continue
            tool_name = msg.name or "unknown"
            if tool_name in PRESERVE_TOOLS:
                continue
            originals.append(msg)
            # 같은 id·tool_call_id로 교체 메시지 생성
            replacement = ToolMessage(
                content=PLACEHOLDER_TEMPLATE.format(tool_name=tool_name),
                name=tool_name,
                tool_call_id=msg.tool_call_id,
                id=msg.id,
            )
            updates.append(replacement)

        if not updates:
            return None

        # 치환 전 원본 아카이브 (best-effort, 실패해도 압축은 진행)
        if self.archive_dir is not None:
            self._archive(originals, runtime)

        return {"messages": updates}

    def _archive(
        self,
        originals: list[ToolMessage],
        runtime: Any,
    ) -> None:
        """JSONL 한 줄로 한 압축 이벤트 기록. thread별 파일 append."""
        try:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
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
