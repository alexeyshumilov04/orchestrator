#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Сверка карты метрики с табличным агрегатом запасов (правило 6).

Логика — чистая и тестируемая: карта метрики может строиться из ПРОИЗВОДНОГО
свойства (например, `HCPV / Bo`), тогда как таблица волюметрии считает запасы со
своими Sw/Bo и зонами. Расхождение не является ни «прошло», ни «провалом»: при
выходе за допуск из данных оно помечается `unknown` (неизвестное != ложь).

Доменных значений здесь нет: имя метрики, допуск и признак бланка приходят из
данных (config.yaml, проектный граф, отчёт прогона).
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["to_num", "map_sum", "blank_from_graph", "verdict"]


def to_num(text) -> float | None:
    """Число из строки выгрузки/отчёта; не число → None (не подставляем ноль)."""
    try:
        return float(str(text).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def map_sum(export_file: Path | str | None, blank: float | None) -> tuple[float, int, int] | None:
    """Сумма непустых значений выгрузки карты: (сумма, непустых, всего).

    `blank` — признак бланка ИЗ ДАННЫХ (значение `default_value` шага выгрузки).
    Файла нет → None (свидетельства нет).
    """
    path = Path(export_file) if export_file else None
    if path is None or not path.is_file():
        return None
    total = empty = 0
    total_sum = 0.0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        v = to_num(line)
        if v is None:
            continue
        total += 1
        if blank is not None and abs(v - blank) < 1e-6:
            empty += 1
            continue
        total_sum += v
    return total_sum, total - empty, total


def blank_from_graph(graph: dict, export_file_name: str) -> float | None:
    """Признак бланка — из ДАННЫХ шага выгрузки (`parameters.default_value`)."""
    for stage in (graph.get("pipeline") or []):
        for step in (stage.get("steps") or []):
            params = (step or {}).get("parameters") or {}
            name = str(params.get("file_name") or "")
            if name and Path(name).name == Path(export_file_name).name:
                v = to_num(params.get("default_value"))
                if v is not None:
                    return v
    return None


def verdict(map_val: float | None, table_val: float | None, tol: float) -> dict:
    """Вердикт сверки: `passed` | `unknown` | `unverified` (правило 6)."""
    if map_val is None or table_val in (None, 0):
        return {"verdict": "unverified",
                "reason": ("нет одной из величин (карта метрики или табличный агрегат) — "
                           "сравнивать нечего")}
    rel = abs(map_val - table_val) / abs(table_val)
    if rel <= tol:
        return {"verdict": "passed", "rel_diff": rel,
                "reason": f"расхождение {rel * 100:.1f} % в пределах допуска {tol * 100:.1f} %"}
    return {"verdict": "unknown", "rel_diff": rel,
            "reason": (f"карта метрики — производная величина (вычисленное свойство), "
                       f"таблица считает запасы с иными Sw/Bo/зонами: расхождение "
                       f"{rel * 100:.1f} % против допуска {tol * 100:.1f} % — требует "
                       f"согласования допуска или формулы")}
