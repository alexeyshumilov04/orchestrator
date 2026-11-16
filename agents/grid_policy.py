"""Совместимость: решение агента сетки (канонический код — `agents/grid.py`).

Исторический модуль v5 сохранён как ТОНКАЯ ОБЁРТКА, чтобы прежние потребители и
тесты (`StageRunner`, `tests/test_agents.py`, `tests/test_base_agent.py`) не
менялись: ключи `enabled/grid_function/box/step/expected_nx/expected_ny/parameters/
reason` остаются прежними, метаданные BDI-цикла (`mode/plan/agent_id/missing/…`)
добавляет :class:`agents.base_agent.BaseAgent`.

* :data:`_GRID_OBJ_TYPE` — идентификатор СХЕМЫ «тип объекта 3D-сетка» (реэкспорт);
* :data:`GridAgent` — класс-агент (канонический — :class:`agents.grid.GridAgent`);
* :func:`decide_grid` — модульная точка входа (тонкая обёртка).

Бокс/шаг/слои/разломы и политика QC ячеек — в `agents/grid.py`.
"""
from __future__ import annotations

from agents.grid import _GRID_OBJ_TYPE, GridAgent  # noqa: F401 — реэкспорт схемы

__all__ = ["GridAgent", "decide_grid"]


def decide_grid(project: dict, evidence: dict | None = None, *, cfg=None, kb=None,
                registry=None, gate_engine=None) -> dict:
    """Тонкая обёртка (совместимость): решение :class:`GridAgent`.

    Необязательные `cfg`/`kb`/`registry`/`gate_engine` позволяют прогону
    подключить политику входов и опыт БЗ. Без них агент работает
    детерминированно по данным («неизвестное != ложь»).
    """
    return GridAgent(cfg, kb=kb, registry=registry,
                     gate_engine=gate_engine).decide(project, evidence)
