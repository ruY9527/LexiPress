"""LexiPress 本地管理后台包。"""

from __future__ import annotations

from .tasks import TASKS, TaskConflict, TaskManager

__all__ = ["TASKS", "TaskConflict", "TaskManager"]
