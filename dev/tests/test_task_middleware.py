"""TaskMiddleware 단위 테스트 — task_create/update/list/get 도구."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.task_middleware import TaskMiddleware


@pytest.fixture
def mw(tmp_path: Path, monkeypatch) -> TaskMiddleware:
    """격리된 임시 디렉터리 위에 미들웨어 생성."""
    return TaskMiddleware(tasks_dir=tmp_path / "tasks")


class TestMiddlewareStructure:
    def test_has_four_tools(self, mw: TaskMiddleware):
        names = {t.name for t in mw.tools}
        assert names == {"task_create", "task_update", "task_list", "task_get"}

    def test_tools_have_invoke(self, mw: TaskMiddleware):
        for t in mw.tools:
            assert hasattr(t, "invoke")


class TestTaskCreate:
    def test_creates_and_returns_json(self, mw: TaskMiddleware):
        tool = {t.name: t for t in mw.tools}["task_create"]
        result = tool.func(subject="연결재무제표 프로젝트")
        assert "id" in result
        assert "연결재무제표" in result

    def test_with_description_and_blocked_by(self, mw: TaskMiddleware):
        tools = {t.name: t for t in mw.tools}
        tools["task_create"].func(subject="first")
        result = tools["task_create"].func(
            subject="second",
            description="상세",
            blocked_by=[1],
        )
        assert "blockedBy" in result
        assert "1" in result


class TestTaskUpdate:
    def test_status_change(self, mw: TaskMiddleware):
        tools = {t.name: t for t in mw.tools}
        tools["task_create"].func(subject="a")
        result = tools["task_update"].func(task_id=1, status="in_progress")
        assert "in_progress" in result

    def test_completing_unblocks(self, mw: TaskMiddleware):
        tools = {t.name: t for t in mw.tools}
        tools["task_create"].func(subject="first")
        tools["task_create"].func(subject="second", blocked_by=[1])
        tools["task_update"].func(task_id=1, status="completed")
        t2 = tools["task_get"].func(task_id=2)
        assert '"blockedBy": []' in t2

    def test_invalid_id_returns_error_string(self, mw: TaskMiddleware):
        tools = {t.name: t for t in mw.tools}
        result = tools["task_update"].func(task_id=999, status="completed")
        assert "not found" in result.lower() or "error" in result.lower()


class TestTaskList:
    def test_empty(self, mw: TaskMiddleware):
        tools = {t.name: t for t in mw.tools}
        result = tools["task_list"].func()
        assert "no tasks" in result.lower() or result.strip() == ""

    def test_formatted_output(self, mw: TaskMiddleware):
        tools = {t.name: t for t in mw.tools}
        tools["task_create"].func(subject="alpha")
        tools["task_create"].func(subject="beta")
        tools["task_update"].func(task_id=1, status="completed")
        result = tools["task_list"].func()
        assert "alpha" in result
        assert "beta" in result
        assert "[x]" in result  # completed marker
        assert "[ ]" in result  # pending marker

    def test_blocked_display(self, mw: TaskMiddleware):
        tools = {t.name: t for t in mw.tools}
        tools["task_create"].func(subject="first")
        tools["task_create"].func(subject="second", blocked_by=[1])
        result = tools["task_list"].func()
        assert "blocked" in result.lower() or "[1]" in result


class TestTaskGet:
    def test_returns_json(self, mw: TaskMiddleware):
        tools = {t.name: t for t in mw.tools}
        tools["task_create"].func(subject="detail test")
        result = tools["task_get"].func(task_id=1)
        assert "detail test" in result
        assert '"status"' in result

    def test_unknown_id_returns_error(self, mw: TaskMiddleware):
        tools = {t.name: t for t in mw.tools}
        result = tools["task_get"].func(task_id=999)
        assert "not found" in result.lower() or "error" in result.lower()
