"""Реестр ИСПОЛНИТЕЛЕЙ пайплайна: ядро не импортирует верхние слои напрямую.

Ядро (`core/`) не должно знать про агентный слой (`agents/`). Исполнитель
(например, «staged» — этапы агентами и гейтами) регистрируется в этом реестре
КОМПОЗИЦИОННЫМ КОРНЕМ (`wire.py`) и берётся координатором по имени.

Направление зависимостей:  core ← execution(registry) ← wire → agents.

Без регистрации координатор деградирует в монолитный контур (безопасный fallback).
"""
from __future__ import annotations

from typing import Any, Callable, Protocol


class StageExecutor(Protocol):
    """Контракт исполнителя этапов (реализуется агентым слоем)."""

    def run_staged(self, field, run_dir, *, execute: bool = False, on_event=None,
                   on_log=None, staging: dict | None = None,
                   on_phase=None) -> dict: ...


ExecutorFactory = Callable[..., StageExecutor]

_EXECUTORS: dict[str, ExecutorFactory] = {}


def register_executor(name: str, factory: ExecutorFactory) -> None:
    """Зарегистрировать фабрику исполнителя по имени (идемпотентно)."""
    _EXECUTORS[str(name)] = factory


def get_executor(name: str, *args: Any, **kwargs: Any) -> StageExecutor | None:
    """Создать исполнителя по имени; нет регистрации → ``None`` (fallback)."""
    factory = _EXECUTORS.get(str(name))
    if factory is None:
        return None
    return factory(*args, **kwargs)


def available() -> list[str]:
    """Имена зарегистрированных исполнителей."""
    return sorted(_EXECUTORS)


def clear() -> None:
    """Очистить реестр (для тестов)."""
    _EXECUTORS.clear()
