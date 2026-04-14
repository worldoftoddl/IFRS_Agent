"""TaskStore 단위 테스트 — 파일 기반 영속 Task 저장소.

세션 경계를 넘는 장기 목표 관리 계층. LangGraph state 외부에 저장되므로
대화가 압축되거나 프로세스가 재시작되어도 살아남는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.task_store import TaskStore


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    """격리된 임시 디렉터리 위에 TaskStore 생성."""
    return TaskStore(tasks_dir=tmp_path / "tasks")


class TestInit:
    """초기화 — 디렉터리 자동 생성, ID 카운터 복구."""

    def test_creates_directory(self, tmp_path: Path):
        target = tmp_path / "tasks"
        assert not target.exists()
        TaskStore(tasks_dir=target)
        assert target.is_dir()

    def test_next_id_starts_at_1_when_empty(self, store: TaskStore):
        task = store.create("first")
        assert task["id"] == 1

    def test_next_id_resumes_after_restart(self, tmp_path: Path):
        s1 = TaskStore(tasks_dir=tmp_path / "tasks")
        s1.create("a")
        s1.create("b")
        s2 = TaskStore(tasks_dir=tmp_path / "tasks")  # 재시작
        task = s2.create("c")
        assert task["id"] == 3


class TestCreate:
    """Task 생성."""

    def test_returns_dict_with_id(self, store: TaskStore):
        task = store.create("subject only")
        assert isinstance(task, dict)
        assert task["id"] == 1
        assert task["subject"] == "subject only"

    def test_defaults(self, store: TaskStore):
        task = store.create("test")
        assert task["status"] == "pending"
        assert task["description"] == ""
        assert task["blockedBy"] == []

    def test_with_description(self, store: TaskStore):
        task = store.create("s", description="자세한 설명")
        assert task["description"] == "자세한 설명"

    def test_with_blocked_by(self, store: TaskStore):
        store.create("first")
        task = store.create("second", blocked_by=[1])
        assert task["blockedBy"] == [1]

    def test_persists_to_disk(self, store: TaskStore):
        task = store.create("persist me")
        path = store.dir / f"task_{task['id']}.json"
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["subject"] == "persist me"

    def test_has_timestamps(self, store: TaskStore):
        task = store.create("ts")
        assert "created_at" in task
        assert "updated_at" in task
        assert task["created_at"] == task["updated_at"]


class TestGet:
    """Task 조회."""

    def test_returns_saved_task(self, store: TaskStore):
        store.create("a")
        t = store.get(1)
        assert t["subject"] == "a"

    def test_unknown_id_raises(self, store: TaskStore):
        with pytest.raises(ValueError, match="not found"):
            store.get(999)


class TestUpdateStatus:
    """상태 변경."""

    def test_set_in_progress(self, store: TaskStore):
        store.create("a")
        t = store.update(1, status="in_progress")
        assert t["status"] == "in_progress"

    def test_invalid_status_raises(self, store: TaskStore):
        store.create("a")
        with pytest.raises(ValueError, match="Invalid status"):
            store.update(1, status="wrong")

    def test_updated_at_changes(self, store: TaskStore):
        created = store.create("a")
        import time
        time.sleep(0.01)
        updated = store.update(1, status="in_progress")
        assert updated["updated_at"] > created["updated_at"]

    def test_created_at_immutable(self, store: TaskStore):
        created = store.create("a")
        updated = store.update(1, status="in_progress")
        assert updated["created_at"] == created["created_at"]


class TestDependencyResolution:
    """의존성 그래프 — completed 시 자동 해제."""

    def test_completing_removes_from_blocked_by(self, store: TaskStore):
        store.create("first")
        store.create("second", blocked_by=[1])
        store.update(1, status="completed")
        t2 = store.get(2)
        assert t2["blockedBy"] == []

    def test_completing_preserves_other_dependencies(self, store: TaskStore):
        store.create("a")
        store.create("b")
        store.create("c", blocked_by=[1, 2])
        store.update(1, status="completed")
        t3 = store.get(3)
        assert t3["blockedBy"] == [2]

    def test_add_blocked_by(self, store: TaskStore):
        store.create("a")
        store.create("b")
        store.update(2, add_blocked_by=[1])
        assert store.get(2)["blockedBy"] == [1]

    def test_add_blocked_by_dedupes(self, store: TaskStore):
        store.create("a")
        store.create("b", blocked_by=[1])
        store.update(2, add_blocked_by=[1])
        assert store.get(2)["blockedBy"] == [1]

    def test_remove_blocked_by(self, store: TaskStore):
        store.create("a")
        store.create("b")
        store.create("c", blocked_by=[1, 2])
        store.update(3, remove_blocked_by=[1])
        assert store.get(3)["blockedBy"] == [2]


class TestList:
    """목록 조회."""

    def test_empty(self, store: TaskStore):
        assert store.list_all() == []

    def test_sorted_by_id(self, store: TaskStore):
        store.create("c")
        store.create("a")
        store.create("b")
        ids = [t["id"] for t in store.list_all()]
        assert ids == [1, 2, 3]

    def test_status_filter(self, store: TaskStore):
        store.create("a")
        store.create("b")
        store.create("c")
        store.update(1, status="completed")
        store.update(2, status="in_progress")
        active = store.list_all(status_filter=["pending", "in_progress"])
        subjects = {t["subject"] for t in active}
        assert subjects == {"b", "c"}


class TestAtomicWrite:
    """원자적 쓰기 — 중단돼도 손상된 JSON 잔류 없음."""

    def test_no_tmp_file_after_create(self, store: TaskStore):
        store.create("a")
        tmp_files = list(store.dir.glob("*.tmp"))
        assert tmp_files == []

    def test_no_tmp_file_after_update(self, store: TaskStore):
        store.create("a")
        store.update(1, status="completed")
        tmp_files = list(store.dir.glob("*.tmp"))
        assert tmp_files == []
