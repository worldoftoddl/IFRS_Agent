"""EnhancedTodoMiddleware 단위 테스트."""

from langgraph.types import Command

from app.middleware import EnhancedTodoMiddleware, update_todo, write_todos


class TestMiddlewareStructure:
    """미들웨어 구조 및 인터페이스 검증."""

    def test_has_two_tools(self):
        mw = EnhancedTodoMiddleware()
        names = {t.name for t in mw.tools}
        assert names == {"write_todos", "update_todo"}

    def test_state_schema_has_todos(self):
        mw = EnhancedTodoMiddleware()
        assert "todos" in mw.state_schema.__annotations__

    def test_tools_have_invoke(self):
        mw = EnhancedTodoMiddleware()
        for t in mw.tools:
            assert hasattr(t, "invoke")


class TestWriteTodos:
    """write_todos 도구 — 전체 목록 교체.

    InjectedToolCallId는 LangGraph 런타임에서 주입되므로,
    테스트에서는 기저 함수(.func)를 직접 호출한다.
    """

    def test_returns_command(self):
        todos = [{"content": "Step 1", "status": "pending"}]
        result = write_todos.func(todos=todos, tool_call_id="test-id")
        assert isinstance(result, Command)

    def test_command_contains_todos(self):
        todos = [{"content": "Step 1", "status": "pending"}]
        result = write_todos.func(todos=todos, tool_call_id="test-id")
        assert result.update["todos"] == todos

    def test_replaces_entire_list(self):
        new = [
            {"content": "A", "status": "pending"},
            {"content": "B", "status": "in_progress"},
        ]
        result = write_todos.func(todos=new, tool_call_id="test-id")
        assert len(result.update["todos"]) == 2
        assert result.update["todos"][0]["content"] == "A"

    def test_returns_tool_message(self):
        todos = [{"content": "X", "status": "pending"}]
        result = write_todos.func(todos=todos, tool_call_id="test-id")
        msgs = result.update["messages"]
        assert len(msgs) == 1
        assert msgs[0].tool_call_id == "test-id"

    def test_empty_list(self):
        result = write_todos.func(todos=[], tool_call_id="test-id")
        assert result.update["todos"] == []


class TestUpdateTodoSchema:
    """update_todo 도구 스키마 검증.

    ToolRuntime 주입이 필요하므로 실제 invoke는 통합 테스트에서 수행.
    여기서는 도구 메타데이터만 검증한다.
    """

    def test_tool_name(self):
        assert update_todo.name == "update_todo"

    def test_has_description(self):
        assert update_todo.description
        assert "상태" in update_todo.description

    def test_schema_has_index_and_status(self):
        """LLM에 노출되는 args에 index, status가 있어야 함."""
        args = update_todo.args
        assert "index" in args
        assert "status" in args

    def test_runtime_not_in_args(self):
        """ToolRuntime은 LLM 스키마에서 숨겨져야 함."""
        args = update_todo.args
        assert "runtime" not in args
