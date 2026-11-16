"""Брокер решений оператора для гейтов с режимом `ask`.

Прогон исполняется в отдельном потоке (API): при исчерпании попыток и режиме
`ask` StageRunner вызывает :meth:`DecisionBroker.request` и ждёт решение из
интерфейса (`POST /api/runs/{id}/gates/{gid}/resolve`). Решения и их авторы
фиксируются в журнале (аудит). Таймаут — `ui.decision_timeout_sec`
(0 = ждать без таймаута); при истечении возвращается None (гейт остаётся awaiting).
"""
from __future__ import annotations

import threading

from agents.contracts import utc_now


class DecisionBroker:
    """Ожидание решений оператора по гейтам (потокобезопасно)."""

    def __init__(self, timeout_sec: float = 0.0, on_request=None) -> None:
        self.timeout_sec = float(timeout_sec or 0.0)
        self.on_request = on_request
        self._lock = threading.Lock()
        self._events: dict[tuple[str, str], threading.Event] = {}
        self._decisions: dict[tuple[str, str], dict] = {}
        self._log: list[dict] = []

    def request(self, run_id: str, gate_id: str, context: dict | None = None) -> dict | None:
        """Встать на паузу до решения оператора; None — решение не получено."""
        key = (str(run_id), str(gate_id))
        event = threading.Event()
        with self._lock:
            self._events[key] = event
            self._decisions.pop(key, None)
        if callable(self.on_request):
            try:
                self.on_request(key[0], key[1], context or {})
            except Exception:                          # noqa: BLE001 — хук не роняет прогон
                pass
        timeout = self.timeout_sec if self.timeout_sec > 0 else None
        event.wait(timeout=timeout)
        with self._lock:
            decision = self._decisions.pop(key, None)
            self._events.pop(key, None)
        return decision

    def resolve(self, run_id: str, gate_id: str, action: str, *,
                author: str = "", comment: str = "") -> bool:
        """Передать решение ожидающему прогону; False — гейт не ждёт решения."""
        key = (str(run_id), str(gate_id))
        with self._lock:
            event = self._events.get(key)
            if event is None:
                return False
            decision = {"action": str(action), "author": str(author),
                        "comment": str(comment), "ts": utc_now()}
            self._decisions[key] = decision
            self._log.append({"run_id": key[0], "gate": key[1], **decision})
            event.set()
        return True

    def pending(self) -> list[dict]:
        """Гейты, ожидающие решения (для интерфейса/диагностики)."""
        with self._lock:
            return [{"run_id": k[0], "gate": k[1]}
                    for k, ev in self._events.items() if not ev.is_set()]

    def log(self) -> list[dict]:
        with self._lock:
            return list(self._log)
