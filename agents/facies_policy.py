"""Совместимость v5: решение агента фаций (канонический код — `agents/facies.py`).

Исторический модуль v5 сохранён как ТОНКАЯ ОБЁРТКА, чтобы прежние потребители и
тесты (`StageRunner`, `tests/test_agents.py`, `tests/test_base_agent.py`) не
менялись: ключи `enabled/method/n_facies/variogram/parameters/reason` остаются
прежними, а метаданные BDI-цикла (`mode/plan/agent_id/missing/…`) добавляет
:class:`agents.base_agent.BaseAgent`.

Карта «метод фаций → функция тНава», палитра, геотела и пропорции — ДАННЫЕ
(`ontology/facies_methods.yaml`); см. шапку :mod:`agents.facies`.
"""
from __future__ import annotations

from agents.facies import FaciesAgent, decide_facies

__all__ = ["FaciesAgent", "decide_facies"]
