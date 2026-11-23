"""后台任务管理器：全局并发锁 + 任务状态机 + 日志广播。

对应 `plan/04` 第 1.5 节的闭环要求：
- 同一时刻只允许一个同名任务运行，重复触发返回 409。
- 关键：**占位必须在调用方线程同步完成**。`asyncio.create_task` 只是把协程排入
  事件循环，锁要等协程真正开始执行才会被 acquire；若只靠 `lock.locked()` 判断，
  两次几乎同时到达的请求会双双通过检查。因此这里额外维护 `_reserved` 集合，
  在 `spawn()` / `reserve()` 时同步占位，任务结束时在 finally 中释放。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from ..harvester.base import LOG_BUS


@dataclass
class TaskState:
    name: str
    status: str = "idle"  # idle | running | done | error
    started_at: str = ""
    finished_at: str = ""
    progress: float = 0.0
    message: str = ""
    last_result: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": round(self.progress, 1),
            "message": self.message,
            "last_result": self.last_result,
        }


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class TaskConflict(Exception):
    """任务已在运行（映射为 HTTP 409）。"""

    def __init__(self, task: str, message: str = ""):
        self.task = task
        super().__init__(message or f"任务 {task} 正在运行中")


class TaskManager:
    """三类长任务的并发闸门。"""

    NAMES = ("crawl", "parse", "build")

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {name: asyncio.Lock() for name in self.NAMES}
        self._states: dict[str, TaskState] = {name: TaskState(name) for name in self.NAMES}
        self._handles: dict[str, asyncio.Task[Any]] = {}
        self._reserved: set[str] = set()

    # ---- 状态查询 ----

    def state(self, name: str) -> dict[str, Any]:
        return self._states[name].as_dict()

    def all_states(self) -> dict[str, Any]:
        return {name: st.as_dict() for name, st in self._states.items()}

    def is_running(self, name: str) -> bool:
        """同步可信：spawn/reserve 时已占位，不依赖事件循环调度时机。"""

        return name in self._reserved or self._locks[name].locked()

    def any_running(self) -> bool:
        return any(self.is_running(n) for n in self.NAMES)

    def running_names(self) -> list[str]:
        return [n for n in self.NAMES if self.is_running(n)]

    # ---- 占位 ----

    def reserve(self, name: str, task_label: str = "") -> None:
        """同步占用任务位；已被占用则抛 TaskConflict。"""

        if self.is_running(name):
            raise TaskConflict(name, f"{task_label or name} 已在运行中，请等待完成")
        self._reserved.add(name)
        state = self._states[name]
        state.status = "running"
        state.started_at = _now()
        state.finished_at = ""
        state.progress = 0.0
        state.message = f"{task_label or name} 已启动"
        state.last_result = {}

    def release(self, name: str) -> None:
        self._reserved.discard(name)

    # ---- 执行 ----

    async def run(
        self,
        name: str,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        task_label: str = "",
    ) -> Any:
        """在锁保护下执行协程；已被占用时抛 TaskConflict。"""

        if not self.is_running(name):
            self.reserve(name, task_label)
        elif name not in self._reserved:
            # 已被其它协程通过 run() 占住
            raise TaskConflict(name, f"{task_label or name} 已在运行中，请等待完成")

        lock = self._locks[name]
        async with lock:
            state = self._states[name]
            state.status = "running"
            if not state.started_at:
                state.started_at = _now()
            state.message = f"{task_label or name} 开始"
            LOG_BUS.emit("INFO", f"▶ 任务开始：{task_label or name}", scope=name)
            try:
                result = await coro_factory()
                state.status = "done"
                state.progress = 100.0
                state.message = f"{task_label or name} 完成"
                state.last_result = to_dict(result)
                LOG_BUS.emit("INFO", f"✔ 任务完成：{task_label or name}", scope=name, progress=100)
                return result
            except asyncio.CancelledError:
                state.status = "idle"
                state.message = f"{task_label or name} 已取消"
                LOG_BUS.emit("WARN", f"任务已取消：{task_label or name}", scope=name)
                raise
            except Exception as exc:  # noqa: BLE001
                state.status = "error"
                state.message = str(exc)
                state.last_result = {"error": str(exc)}
                LOG_BUS.emit("ERROR", f"✗ 任务失败：{task_label or name} → {exc}", scope=name)
                raise
            finally:
                state.finished_at = _now()
                self.release(name)

    def spawn(self, name: str, coro_factory: Callable[[], Awaitable[Any]], *, task_label: str = "") -> asyncio.Task[Any]:
        """同步占位 + 后台异步执行（供 API 立即返回使用）。

        占位发生在当前（请求处理）线程，因此紧接着的第二次请求会稳定拿到 409。
        """

        self.reserve(name, task_label)

        async def _runner() -> Any:
            try:
                return await self.run(name, coro_factory, task_label=task_label)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                # 异常已在 run() 内记录到状态与日志总线；此处消费掉，
                # 避免 "Task exception was never retrieved" 噪音。
                return None

        try:
            task = asyncio.create_task(_runner())
        except RuntimeError:
            # 无运行中的事件循环：撤销占位，交回调用方
            self.release(name)
            raise

        self._handles[name] = task

        def _cleanup(_t: asyncio.Task[Any]) -> None:
            self._handles.pop(name, None)
            self._reserved.discard(name)

        task.add_done_callback(_cleanup)
        return task

    def cancel(self, name: str) -> bool:
        handle = self._handles.get(name)
        if handle and not handle.done():
            handle.cancel()
            LOG_BUS.emit("WARN", f"任务已请求取消：{name}", scope=name)
            return True
        return False


def to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except Exception:  # noqa: BLE001
            return {}
    return {"value": str(value)}


TASKS = TaskManager()
