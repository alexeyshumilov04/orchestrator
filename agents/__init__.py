"""Агентный слой v5: агенты этапов, гейты передачи и байпасс.

Состав пакета:
  * :mod:`agents.base_agent`      — базовый класс агента-политики (BaseAgent);
  * :mod:`agents.structure_policy`— структурный агент (интервал и «врез»);
  * :mod:`agents.grid_policy`     — агент сетки (бокс/шаг corner-point);
  * :mod:`agents.facies_policy`   — агент фаций (SIS: классы и вариограмма);
  * :mod:`agents.petrophysics_policy` — агент петрофизики (кубы PORO/PERM из ГИС);
  * :mod:`agents.registry`   — BDI-профили и handoff-контракты (данные онтологии v4.1);
  * :mod:`agents.contracts`  — контракты этапа: контекст, план, результат, вердикт, меморандум;
  * :mod:`agents.stage_map`  — сопоставление этапов пайплайна агентам и гейтам;
  * :mod:`agents.gates`      — движок гейтов: политики critical/major/minor,
    on_exhausted (best|skip|halt|ask), байпасс и waiver.

Направление зависимостей: agents → core/domain (из core пакет не импортируется).
"""
from __future__ import annotations

from agents.base_agent import BaseAgent
from agents.facies_policy import FaciesAgent, decide_facies
from agents.grid_policy import GridAgent, decide_grid
from agents.petrophysics_policy import PetrophysicsAgent, decide_petrophysics
from agents.structure_policy import StructureAgent, decide_erosion

__all__ = ["base_agent", "structure_policy", "grid_policy", "facies_policy",
           "petrophysics_policy", "registry", "contracts", "stage_map", "gates",
           "BaseAgent", "StructureAgent", "GridAgent", "FaciesAgent",
           "PetrophysicsAgent",
           "decide_erosion", "decide_grid", "decide_facies", "decide_petrophysics"]

