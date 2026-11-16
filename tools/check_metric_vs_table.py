#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Независимая сверка: карта метрики против табличного агрегата запасов.

Зачем (правило 6 «неизвестное != ложь»): карта метрики строится из ВЫЧИСЛЕННОГО
свойства (например, HCPV/Bo), а таблица волюметрии считает запасы со своими Sw/Bo
и зонами. Расхождение не является ни «прошло», ни «провалом» — оно должно быть
показано числами и, при выходе за допуск, помечено `unknown`.

В инструменте НЕТ доменных значений: имя метрики, допуск и признак бланка берутся
из данных (config.yaml / проектный граф / отчёт прогона).

Использование:
    python tools/check_metric_vs_table.py --field Герасимовское
    python tools/check_metric_vs_table.py --run runs/run_Герасимовское \\
        --report runs/artifacts/execute_XXXX/report_execute.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.metric_consistency import blank_from_graph as _bfg, map_sum as _ms, verdict as _vd, to_num


def _num(text: str):
    try:
        return float(text.strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def map_sum(export_file: Path, blank: float | None) -> tuple[float, int, int] | None:
    """Сумма непустых значений выгрузки карты: (сумма, непустых, всего).

    `blank` — признак бланка ИЗ ДАННЫХ (значение default_value шага выгрузки).
    Нет файла → None (свидетельства нет).
    """
    if not export_file.is_file():
        return None
    total = empty = 0
    s = 0.0
    for line in export_file.read_text(encoding="utf-8", errors="replace").splitlines():
        v = _num(line)
        if v is None:
            continue
        total += 1
        if blank is not None and abs(v - blank) < 1e-6:
            empty += 1
            continue
        s += v
    return s, total - empty, total


def blank_from_graph(graph: dict, export_file_name: str) -> float | None:
    """Признак бланка — из ДАННЫХ шага выгрузки (parameters.default_value)."""
    for stage in (graph.get("pipeline") or []):
        for step in (stage.get("steps") or []):
            params = (step or {}).get("parameters") or {}
            name = str(params.get("file_name") or "")
            if name and Path(name).name == Path(export_file_name).name:
                v = _num(str(params.get("default_value")))
                if v is not None:
                    return v
    return None


def verdict(map_val: float | None, table_val: float | None, tol: float) -> dict:
    """Вердикт сверки: passed | unknown | unverified (правило 6)."""
    if map_val is None or table_val in (None, 0):
        return {"verdict": "unverified",
                "reason": ("нет одной из величин (карта метрики или табличный "
                           "агрегат) — сравнивать нечего")}
    rel = abs(map_val - table_val) / abs(table_val)
    if rel <= tol:
        return {"verdict": "passed", "rel_diff": rel,
                "reason": f"расхождение {rel*100:.1f} % в пределах допуска {tol*100:.1f} %"}
    return {"verdict": "unknown", "rel_diff": rel,
            "reason": (f"карта метрики — производная величина (вычисленное свойство), "
                       f"таблица считает запасы с иными Sw/Bo/зонами: расхождение "
                       f"{rel*100:.1f} % против допуска {tol*100:.1f} % — требует "
                       f"согласования допуска или формулы")}


# Единый источник логики — ядро (core/metric_consistency): локальные копии ниже
# переопределяются ядром, чтобы не было двух реализаций одного правила.
map_sum = _ms
blank_from_graph = _bfg
verdict = _vd


def main() -> int:
    ap = argparse.ArgumentParser(description="сверка карты метрики с табличным агрегатом")
    ap.add_argument("--field", default=None)
    ap.add_argument("--run", default=None, help="каталог прогона (runs/run_<поле>)")
    ap.add_argument("--report", default=None, help="сохранённый отчёт execute (json)")
    args = ap.parse_args()

    from core.config import load_config
    cfg = load_config()
    field = args.field or str(cfg.get("project.default_field", "") or "")
    run_dir = Path(args.run) if args.run else cfg.path("runs.root", "runs") / f"run_{field}"
    metric = str(cfg.get("ensemble.metric", "") or "")
    tol = float(cfg.get("checks.metric_vs_table_tolerance", 0.05) or 0.05)
    export_dirs = cfg.get("workflow.export_dirs") or []
    export_name = f"{metric}.txt"

    # признак бланка — из данных проектного графа (шаг выгрузки карты метрики)
    blank = None
    try:
        from core.coordinator import Coordinator
        graph = Coordinator(cfg).project_graph(field)
        blank = blank_from_graph(graph, export_name)
    except Exception as exc:                            # noqa: BLE001 — данные опциональны
        print(f"признак бланка: не прочитан ({exc})")

    export_file = None
    for d in list(export_dirs) + ["Maps", "maps"]:
        cand = run_dir / str(d) / export_name
        if cand.is_file():
            export_file = cand
            break
    ms = map_sum(export_file, blank) if export_file else None
    map_val = ms[0] if ms else None

    # табличный агрегат — из сохранённого отчёта прогона (модель снята с проекта)
    table_val = None
    report_path = Path(args.report) if args.report else None
    if report_path is None:
        snaps = sorted((cfg.path("runs.execute_archive_dir", "runs/artifacts")).glob(
            "execute_*/report_execute.json"))
        report_path = snaps[-1] if snaps else None
    if report_path and report_path.is_file():
        rep = json.loads(report_path.read_text(encoding="utf-8"))
        table_val = _num(str(((rep.get("model") or {}).get("stoiip"))))

    res = verdict(map_val, table_val, tol)
    print(f"поле: {field}; метрика: {metric or '(не задана)'}; допуск: {tol*100:.1f} %")
    print(f"выгрузка карты: {export_file or 'не найдена'}"
          + (f" | непустых ячеек: {ms[1]} из {ms[2]}" if ms else ""))
    print(f"карта метрики (сумма): {map_val}")
    print(f"табличный агрегат:     {table_val} (из {report_path})")
    print("ВЕРДИКТ: " + json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
