"""커스텀 Todo 미들웨어 — write_todos + update_todo.

기본 TodoListMiddleware는 write_todos(전체 교체)만 제공한다.
이 모듈은 update_todo(개별 항목 상태 변경)를 추가하여
매번 전체 목록을 재전송하는 토큰 낭비를 줄인다.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.todo import PlanningState, Todo
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command


@tool
def write_todos(
    todos: list[Todo],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command[Any]:
    """할 일 목록을 새로 작성하거나 전체 교체합니다.

    최초 계획 수립이나 계획 전면 변경 시에만 사용하세요.
    개별 항목 상태 변경에는 update_todo를 사용하세요.

    Args:
        todos: 전체 할 일 목록
    """
    return Command(
        update={
            "todos": todos,
            "messages": [
                ToolMessage(
                    f"Updated todo list to {todos}",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


@tool
def update_todo(
    index: int,
    status: Literal["pending", "in_progress", "completed"],
    runtime: ToolRuntime,
) -> Command[Any]:
    """할 일 항목 하나의 상태만 변경합니다.

    전체 목록을 다시 보내지 않으므로 토큰이 절약됩니다.
    스텝 진행/완료 시 이 도구를 사용하세요.

    Args:
        index: 변경할 항목의 인덱스 (0부터 시작)
        status: 새 상태 ("pending", "in_progress", "completed")
    """
    todos = [dict(t) for t in runtime.state.get("todos", [])]
    if not (0 <= index < len(todos)):
        msg = f"오류: index {index}는 범위 밖입니다 (0..{len(todos) - 1})"
    else:
        todos[index]["status"] = status
        label = todos[index]["content"][:40]
        msg = f"Todo [{index}] '{label}' → {status}"
    return Command(
        update={
            "todos": todos,
            "messages": [
                ToolMessage(msg, tool_call_id=runtime.tool_call_id)
            ],
        }
    )


class EnhancedTodoMiddleware(AgentMiddleware):
    """write_todos + update_todo를 제공하는 커스텀 Todo 미들웨어.

    langchain의 TodoListMiddleware를 대체한다.
    state_schema는 동일한 PlanningState를 사용하므로 호환성 유지.
    """

    state_schema = PlanningState

    def __init__(self) -> None:
        self.tools = [write_todos, update_todo]
