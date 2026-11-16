"""Совместимость: решение структурного агента (канонический код — `agents/structural.py`).

Исторический модуль v5 сохранён как ТОНКАЯ ОБЁРТКА, чтобы прежние потребители и
тесты (`StageRunner`, `tests/test_agents.py`, `tests/test_base_agent.py`) не
менялись: ключи `enabled/reason/coverage/top_marker/base_marker/mode/steps`
остаются прежними, метаданные BDI-цикла (`mode/plan/agent_id/missing/…`)
добавляет :class:`agents.base_agent.BaseAgent`.

* :data:`StructureAgent` — прежнее имя класса-агента (алиас канонического
  :class:`agents.structural.StructuralAgent`);
* :func:`decide_erosion` — модульная точка входа (тонкая обёртка).

Логика (интервал, врез, план правок, тюнинг из БЗ) — в `agents/structural.py`.
"""
from __future__ import annotations

from agents.structural import StructuralAgent

# Прежнее имя класса-агента (совместимость v5): canonical — StructuralAgent.
StructureAgent = StructuralAgent


def decide_erosion(project: dict, evidence: dict | None = None, *, cfg=None,
                   kb=None, registry=None, gate_engine=None) -> dict:
    """Тонкая обёртка (совместимость): решение :class:`StructuralAgent`.

    Необязательные `cfg`/`kb`/`registry`/`gate_engine` позволяют прогону
    подключить политику входов (режимы SYMBOLIC/HYBRID/GENERATIVE) и опыт БЗ
    (`recall`/`suggest`). Без них агент работает детерминированно по данным
    («неизвестное != ложь»): покрытие пусто → ABSTAIN, подсказок БЗ нет.
    """
    return StructuralAgent(cfg, kb=kb, registry=registry,
                           gate_engine=gate_engine).decide(project, evidence)
