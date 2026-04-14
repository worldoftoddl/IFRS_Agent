"""영속 Task 미들웨어 — task_create/update/list/get 도구 제공.

세션을 초월하는 장기 목표 관리. LangGraph state가 아닌 파일시스템(.tasks/)에
저장되므로 대화가 끊겨도 살아남는다.

Todos(EnhancedTodoMiddleware) vs Tasks(여기):
- Todos: 한 질문 내부의 실행 단계, 스레드 수명
- Tasks: 다중 세션에 걸친 프로젝트/목표, 영속
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.tools import tool

from app.task_store import TaskStore

DEFAULT_TASKS_DIR = Path("./.tasks")

_STATUS_MARKERS = {
    "pending": "[ ]",
    "in_progress": "[>]",
    "completed": "[x]",
}


def _format_list(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "No tasks."
    lines = []
    for t in tasks:
        marker = _STATUS_MARKERS.get(t["status"], "[?]")
        blocked = (
            f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
        )
        lines.append(f"{marker} #{t['id']}: {t['subject']}{blocked}")
    return "\n".join(lines)


def _as_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def _build_tools(store: TaskStore) -> list:
    """TaskStore에 바인딩된 도구 4종 생성."""

    @tool
    def task_create(
        subject: str,
        description: str = "",
        blocked_by: list[int] | None = None,
    ) -> str:
        """영속 Task를 새로 만듭니다.

        다중 세션에 걸친 프로젝트/목표를 추적할 때 사용하세요.
        단일 질문의 단계 계획은 write_todos를 사용하세요.

        Args:
            subject: Task 제목 (짧게)
            description: 상세 내용 (선택)
            blocked_by: 선행 Task ID 목록 (선택)
        """
        try:
            task = store.create(
                subject=subject,
                description=description,
                blocked_by=blocked_by,
            )
            return _as_json(task)
        except Exception as e:
            return f"Error: {e}"

    @tool
    def task_update(
        task_id: int,
        status: str | None = None,
        add_blocked_by: list[int] | None = None,
        remove_blocked_by: list[int] | None = None,
    ) -> str:
        """Task의 상태나 의존성을 변경합니다.

        status="completed"로 변경하면 다른 Task들의 blockedBy에서 자동 제거됩니다.

        Args:
            task_id: 대상 Task ID
            status: pending | in_progress | completed (선택)
            add_blocked_by: 추가할 선행 Task ID 목록 (선택)
            remove_blocked_by: 제거할 선행 Task ID 목록 (선택)
        """
        try:
            task = store.update(
                task_id=task_id,
                status=status,
                add_blocked_by=add_blocked_by,
                remove_blocked_by=remove_blocked_by,
            )
            return _as_json(task)
        except Exception as e:
            return f"Error: {e}"

    @tool
    def task_list() -> str:
        """전체 Task를 상태 마커와 함께 한 줄씩 출력합니다.

        이전 세션에서 만들어둔 Task를 복구할 때 먼저 호출하세요.
        """
        try:
            return _format_list(store.list_all())
        except Exception as e:
            return f"Error: {e}"

    @tool
    def task_get(task_id: int) -> str:
        """특정 Task의 전체 상세(설명 포함)를 JSON으로 반환합니다.

        Args:
            task_id: 조회할 Task ID
        """
        try:
            return _as_json(store.get(task_id))
        except Exception as e:
            return f"Error: {e}"

    return [task_create, task_update, task_list, task_get]


class TaskMiddleware(AgentMiddleware):
    """파일 기반 영속 Task를 도구로 노출하는 미들웨어.

    state_schema를 사용하지 않음 — 모든 상태는 tasks_dir에 JSON으로 저장.
    """

    def __init__(self, tasks_dir: Path | str = DEFAULT_TASKS_DIR) -> None:
        self.store = TaskStore(tasks_dir=Path(tasks_dir))
        self.tools = _build_tools(self.store)
