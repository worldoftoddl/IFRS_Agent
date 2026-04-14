"""파일 기반 영속 Task 저장소.

LangGraph state 외부에 저장되므로 대화 압축/스레드 교체/프로세스 재시작에도
살아남는다. s07_task_system.py의 TaskManager 패턴을 개선:
- 원자적 쓰기 (tmp → os.replace)
- 타임스탬프 (created_at, updated_at)
- 상태 필터링 list_all

단일 프로세스(langgraph dev) 가정. 멀티 프로세스 동시 쓰기는 지원하지 않음.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

VALID_STATUSES = ("pending", "in_progress", "completed")


class TaskStore:
    def __init__(self, tasks_dir: Path):
        self.dir = Path(tasks_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._next_id = self._max_id() + 1

    def _max_id(self) -> int:
        ids = [int(f.stem.split("_")[1]) for f in self.dir.glob("task_*.json")]
        return max(ids) if ids else 0

    def _path(self, task_id: int) -> Path:
        return self.dir / f"task_{task_id}.json"

    def _load(self, task_id: int) -> dict[str, Any]:
        path = self._path(task_id)
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, task: dict[str, Any]) -> None:
        """원자적 쓰기 — tmp 파일에 기록 후 rename."""
        path = self._path(task["id"])
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(task, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)

    @staticmethod
    def _now() -> float:
        return time.time()

    def create(
        self,
        subject: str,
        description: str = "",
        blocked_by: list[int] | None = None,
    ) -> dict[str, Any]:
        now = self._now()
        task = {
            "id": self._next_id,
            "subject": subject,
            "description": description,
            "status": "pending",
            "blockedBy": list(blocked_by) if blocked_by else [],
            "created_at": now,
            "updated_at": now,
        }
        self._save(task)
        self._next_id += 1
        return task

    def get(self, task_id: int) -> dict[str, Any]:
        return self._load(task_id)

    def update(
        self,
        task_id: int,
        status: str | None = None,
        add_blocked_by: list[int] | None = None,
        remove_blocked_by: list[int] | None = None,
    ) -> dict[str, Any]:
        task = self._load(task_id)
        if status is not None:
            if status not in VALID_STATUSES:
                raise ValueError(
                    f"Invalid status: {status} (must be one of {VALID_STATUSES})"
                )
            task["status"] = status
        if add_blocked_by:
            task["blockedBy"] = sorted(set(task["blockedBy"]) | set(add_blocked_by))
        if remove_blocked_by:
            task["blockedBy"] = [
                x for x in task["blockedBy"] if x not in remove_blocked_by
            ]
        task["updated_at"] = self._now()
        self._save(task)
        if status == "completed":
            self._clear_dependency(task_id)
        return task

    def _clear_dependency(self, completed_id: int) -> None:
        """완료된 task를 다른 task들의 blockedBy에서 제거."""
        for f in self.dir.glob("task_*.json"):
            t = json.loads(f.read_text(encoding="utf-8"))
            if completed_id in t.get("blockedBy", []):
                t["blockedBy"] = [x for x in t["blockedBy"] if x != completed_id]
                t["updated_at"] = self._now()
                self._save(t)

    def list_all(
        self,
        status_filter: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        files = sorted(
            self.dir.glob("task_*.json"),
            key=lambda f: int(f.stem.split("_")[1]),
        )
        tasks = [json.loads(f.read_text(encoding="utf-8")) for f in files]
        if status_filter:
            tasks = [t for t in tasks if t["status"] in status_filter]
        return tasks
