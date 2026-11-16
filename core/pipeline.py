"""B — ШИНА ШАГОВ пайплайна: этап → операция → функция → объект + статус.

Каждый шаг = один блок воркфлоу (`begin_wf_item`/`end_wf_item`) = один вызов функции
тНава. Шаги пишутся по мере сборки воркфлоу, стримятся в UI (WebSocket) и сохраняются
в `runs/<id>/steps.json`. Так видно, «что пишется» на каждом шаге построения ГМ.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .runner import utc_now

# статусы шага
QUEUED = "queued"            # в очереди
RUNNING = "running"          # пишется/исполняется
DONE = "done"               # готов
ERROR = "error"             # ошибка
PENDING_TEMPLATE = "pending_template"   # нет шаблона функции (шаг объявлен, но не рендерится)


@dataclass
class StepEvent:
    index: int
    stage: str
    stage_label: str
    operation: str
    function: str
    object: str = ""
    status: str = QUEUED
    message: str = ""
    ts: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return asdict(self)


class Pipeline:
    """Поток шагов одного прогона. on_event — колбэк для стрима (WS)."""

    def __init__(self, on_event: Callable[[StepEvent], None] | None = None) -> None:
        self.steps: list[StepEvent] = []
        self._cb = on_event

    def _emit(self, ev: StepEvent) -> StepEvent:
        if callable(self._cb):
            try:
                self._cb(ev)
            except Exception:                 # noqa: BLE001 — колбэк не должен ронять прогон
                pass
        return ev

    def add(self, *, stage: str, stage_label: str, operation: str, function: str,
            object: str = "", status: str = QUEUED, message: str = "") -> StepEvent:
        ev = StepEvent(index=len(self.steps) + 1, stage=stage, stage_label=stage_label,
                       operation=operation, function=function, object=object,
                       status=status, message=message)
        self.steps.append(ev)
        return self._emit(ev)

    def update(self, ev: StepEvent, status: str, message: str = "") -> StepEvent:
        ev.status = status
        ev.message = message
        ev.ts = utc_now()
        return self._emit(ev)

    def summary(self) -> dict:
        counts = {QUEUED: 0, RUNNING: 0, DONE: 0, ERROR: 0, PENDING_TEMPLATE: 0}
        for s in self.steps:
            counts[s.status] = counts.get(s.status, 0) + 1
        total = len(self.steps)
        done = counts[DONE]
        return {"total": total, "done": done, "error": counts[ERROR],
                "pending_template": counts[PENDING_TEMPLATE],
                "percent": round(100 * done / total, 1) if total else 0.0, "counts": counts}

    def to_dict(self) -> dict:
        return {"steps": [s.to_dict() for s in self.steps], "summary": self.summary()}

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2,
                                   default=str), encoding="utf-8")
        return path
