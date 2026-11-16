"""Совместимость v5: решение агента петрофизики.

Реализация переехала в :mod:`agents.petrophysics` (E8): расширенное решение
(диапазоны физичности из `thresholds`, способ учёта фаций из данных, проверка
метода по `checks.petro_methods`). Здесь остаётся ТОЛЬКО реэкспорт — прежние
импорты (`from agents.petrophysics_policy import decide_petrophysics`,
`PetrophysicsAgent`) продолжают работать без изменений.
"""
from __future__ import annotations

from agents.petrophysics import PetrophysicsAgent, decide_petrophysics

__all__ = ["PetrophysicsAgent", "decide_petrophysics"]
