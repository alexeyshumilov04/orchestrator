"""Планировщик выполнения: реестр прогонов, фоновые задачи, статусы, остановка.

Долгое и внешнее (tNavigator) исполняется в фоновом потоке: координатор не
встраивает в себя ожидание расчёта, статус узлов доступен извне (веб-интерфейс).
"""
from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class StepState:
    order: int
    op_id: str
    label: str
    stage: str
    stage_name: str
    engine: str
    iteration: int = 1
    status: str = "pending"     # pending | running | done | error | skipped | unimplemented
    started_at: str = ""
    finished_at: str = ""
    result: dict = field(default_factory=dict)
    error: str = ""


@dataclass
class RunState:
    run_id: str
    created_at: str = field(default_factory=utc_now)
    status: str = "queued"      # queued | running | done | error | stopped
    user_text: str = ""
    intent: dict = field(default_factory=dict)
    plan: dict = field(default_factory=dict)
    steps: list[StepState] = field(default_factory=list)
    ensemble: list[dict] = field(default_factory=list)
    queue: list[dict] = field(default_factory=list)
    rollup: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    error: str = ""
    run_dir: str = ""

    def add_log(self, message: str) -> None:
        self.log.append(f"[{utc_now()}] {message}")
        if len(self.log) > 2000:
            del self.log[:1000]

    def to_dict(self) -> dict:
        data = asdict(self)
        total = len(self.steps)
        done = sum(1 for s in self.steps if s.status in ("done", "skipped"))
        errored = sum(1 for s in self.steps if s.status == "error")
        blocked = sum(1 for s in self.steps if s.status == "unimplemented")
        data["progress"] = {"total": total, "done": done, "errors": errored,
                            "unimplemented": blocked,
                            "percent": round(100 * done / total, 1) if total else 0.0}
        return data

    def summary(self) -> dict:
        return {"run_id": self.run_id, "status": self.status, "created_at": self.created_at,
                "user_text": self.user_text, "steps_total": len(self.steps),
                "ensemble_size": len(self.ensemble), "run_dir": self.run_dir}


class JobRunner:
    """Реестр прогонов + фоновые потоки + кооперативная остановка."""

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def put(self, run: RunState) -> RunState:
        with self._lock:
            self._runs[run.run_id] = run
        return run

    def get(self, run_id: str) -> RunState | None:
        with self._lock:
            return self._runs.get(run_id)

    def list(self) -> list[dict]:
        with self._lock:
            runs = list(self._runs.values())
        runs.sort(key=lambda r: r.created_at, reverse=True)
        return [r.summary() for r in runs]

    def submit(self, run: RunState, worker: Callable[[RunState], None]) -> RunState:
        self.put(run)
        self._stop.clear()
        thread = threading.Thread(target=self._wrap, args=(run, worker),
                                  name=f"run-{run.run_id}", daemon=True)
        with self._lock:
            self._threads[run.run_id] = thread
        thread.start()
        return run

    def _wrap(self, run: RunState, worker: Callable[[RunState], None]) -> None:
        run.status = "running"
        try:
            worker(run)
            if run.status == "running":
                run.status = "done"
        except Exception as exc:  # noqa: BLE001
            run.status = "error"
            run.error = str(exc)
            run.add_log(f"ОШИБКА: {exc}")
        finally:
            with self._lock:
                self._threads.pop(run.run_id, None)

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def request_stop(self) -> None:
        self._stop.set()

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._threads.values() if t.is_alive())

    # -- удаление результатов ----------------------------------------------
    def delete(self, run_id: str) -> dict:
        """Убрать прогон из реестра и удалить его папку с диска."""
        import shutil
        with self._lock:
            run = self._runs.pop(run_id, None)
            self._threads.pop(run_id, None)
        removed_dir = ""
        if run and run.run_dir:
            target = Path(run.run_dir)
            if target.exists() and target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
                removed_dir = str(target)
        return {"deleted": bool(run) or bool(removed_dir), "run_id": run_id,
                "dir": removed_dir}
