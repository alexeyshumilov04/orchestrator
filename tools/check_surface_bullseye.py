#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Проверка «бычьих глаз» на поверхности (локальная подсадка структуры на скважины).

Замечание заказчика: подошва пласта получилась с «бычьими глазами» — поверхность
жёстко подсажена на каждую скважину, вместо единой структуры получились локальные
«куполки». Инструмент измеряет это числом: для каждой скважины сравнивает значение
поверхности в её ячейке с медианой кольца ячеек радиуса R и считает локальным
экстремумом (bull's eye) те скважины, где отклонение превышает порог И значение
является максимумом/минимумом внутри кольца.

Все параметры — ДАННЫЕ (правило 1): пути, радиус и порог берутся из аргументов или
`checks.surface_bullseye.*` конфигурации; в коде доменных имён нет.

Использование:
    python tools/check_surface_bullseye.py --surface runs/run_Герасимовское/U1_bot_cps.txt
    python tools/check_surface_bullseye.py --compare U1_top U1_bot --run runs/run_Герасимовское
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def read_surface(path: Path) -> tuple[list[list[float | None]], dict]:
    """Читает поверхность (ASCII/CPS): строки чисел, бланк — по заголовку/большим значениям."""
    head: dict = {}
    rows: list[list[float | None]] = []
    blank = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        low = line.strip().lower()
        if not low:
            continue
        if not low[0].isdigit() and not low[0] in "+-.":
            # заголовок IRAP/CPS: ищем признак бланка
            for key in ("novalue", "null", "blank", "undefined"):
                if key in low:
                    parts = line.replace(",", " ").split()
                    for p in parts:
                        try:
                            blank = float(p)
                        except ValueError:
                            continue
            continue
        vals: list[float | None] = []
        for tok in line.replace(",", " ").split():
            try:
                v = float(tok)
            except ValueError:
                vals.append(None)
                continue
            vals.append(None if (blank is not None and abs(v - blank) < 1e-6) else v)
        if vals:
            rows.append(vals)
    return rows, {"blank": blank, "rows": len(rows),
                  "cols": max((len(r) for r in rows), default=0)}


def read_wells(path: Path) -> list[tuple[str, float, float]]:
    """Скважины из таблицы (имя, X, Y) — колонки определяются по заголовку/позиции."""
    out: list[tuple[str, float, float]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        toks = line.replace(",", " ").replace("\t", " ").split()
        if len(toks) < 3:
            continue
        nums = []
        for t in toks[1:]:
            try:
                nums.append(float(t))
            except ValueError:
                nums.append(None)
        xy = [n for n in nums if n is not None]
        if len(xy) >= 2:
            out.append((toks[0], xy[0], xy[1]))
    return out


def grid_xy(rows: list[list[float | None]], nx: int, ny: int) -> tuple[list[list[float | None]], float, float]:
    """Приводит поверхность к регулярной сетке и возвращает шаг по X/Y (условный)."""
    grid = [[None] * nx for _ in range(ny)]
    for j, r in enumerate(rows[:ny]):
        for i, v in enumerate(r[:nx]):
            grid[j][i] = v
    vals = [v for r in grid for v in r if v is not None]
    k = max(1, int(math.sqrt(len(vals))))
    return grid, k, k


def bullseyes(surface: Path, wells: Path, radius_cells: int, threshold: float) -> dict:
    rows, meta = read_surface(surface)
    nx, ny = meta["cols"], meta["rows"]
    grid, _, _ = grid_xy(rows, nx, ny)
    wl = read_wells(wells)
    # координаты скважин нормируем в индексы сетки по min/max из данных скважин
    if not wl:
        return {"verdict": "unverified", "reason": "нет данных о скважинах"}
    xs = [x for _, x, _ in wl]
    ys = [y for _, _, y in wl]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    found: list[dict] = []
    checked = 0
    for name, x, y in wl:
        i = int((x - x0) / (x1 - x0 + 1e-9) * (nx - 1))
        j = int((y - y0) / (y1 - y0 + 1e-9) * (ny - 1))
        v = grid[j][i]
        if v is None:
            continue
        ring = []
        for dj in range(-radius_cells, radius_cells + 1):
            for di in range(-radius_cells, radius_cells + 1):
                if di == 0 and dj == 0:
                    continue
                if abs(di) != radius_cells and abs(dj) != radius_cells:
                    continue                      # только КОЛЬЦО, не весь квадрат
                jj, ii = j + dj, i + di
                if 0 <= jj < ny and 0 <= ii < nx and grid[jj][ii] is not None:
                    ring.append(grid[jj][ii])
        if len(ring) < 8:
            continue
        checked += 1
        ring.sort()
        med = ring[len(ring) // 2]
        dev = v - med
        if abs(dev) >= threshold and (v >= ring[-1] or v <= ring[0]):
            found.append({"well": name, "value": round(v, 3), "ring_median": round(med, 3),
                          "dev": round(dev, 3),
                          "type": "максимум" if dev > 0 else "минимум"})
    if not checked:
        return {"verdict": "unverified", "reason": "не удалось сопоставить скважины с сеткой"}
    share = len(found) / checked
    verdict = "failed" if share >= 0.2 else "passed"
    return {"verdict": verdict, "checked_wells": checked, "bullseyes": len(found),
            "share": round(share, 3), "threshold": threshold, "radius_cells": radius_cells,
            "worst": sorted(found, key=lambda d: -abs(d["dev"]))[:5],
            "reason": (f"локальная подсадка на скважины: {len(found)} из {checked} "
                       f"(порог {threshold} м, кольцо {radius_cells} ячеек)")}


def bullseyes_geo(surface: Path, wells: Path, radius_cells: int, threshold: float) -> dict:
    """Проверка по ГЕОМЕТРИИ ЗАГОЛОВКА поверхности (CPS/IRAP): FSLIMI/FSNROW/FSXINC.

    Скважины привязываются к ячейкам по координатам из заголовка (а не по их bbox —
    прежний вариант «промахивался»). Колонки X/Y берутся по именам заголовка таблицы.
    """
    xmin = xmax = ymin = ymax = None
    dx = dy = 50.0
    nrow = ncol = None
    blank = None
    vals: list[float | None] = []
    for line in surface.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        up = s.upper()
        if up.startswith("FSLIMI"):
            p = s.split()
            xmin, xmax, ymin, ymax = (float(p[1]), float(p[2]), float(p[3]), float(p[4]))
            continue
        if up.startswith("FSNROW"):
            p = s.split()
            nrow, ncol = int(p[1]), int(p[2])
            continue
        if up.startswith("FSXINC"):
            p = s.split()
            dx, dy = float(p[1]), float(p[2])
            continue
        if up.startswith("FSASCI"):
            p = s.split()
            try:
                blank = float(p[5])
            except (IndexError, ValueError):
                blank = None
            continue
        if not s or not (s[0].isdigit() or s[0] in "+-.") or up.startswith("->"):
            continue
        for tok in s.split():
            try:
                v = float(tok)
            except ValueError:
                vals.append(None)
                continue
            vals.append(None if (blank is not None and abs(v - blank) < 1e-6) else v)
    if not (xmin is not None and nrow and ncol):
        return {"verdict": "unverified", "reason": "в заголовке нет геометрии (FSLIMI/FSNROW)"}

    def cell(i: int, j: int):
        k = j * ncol + i
        return vals[k] if 0 <= k < len(vals) else None

    # колонки скважин — по именам заголовка таблицы
    head = None
    wl: list[tuple[str, float, float]] = []
    for line in wells.read_text(encoding="utf-8", errors="replace").splitlines():
        toks = line.replace(",", " ").replace("\t", " ").split()
        if not toks:
            continue
        if head is None and any(t.lower().startswith("x_") or t.lower() == "x" for t in toks):
            head = [t.strip().lower() for t in toks]
            continue
        if head is None or len(toks) < len(head):
            continue
        row = dict(zip(head, toks))
        xk = next((k for k in ("x_seiscoord", "x", "node_x") if k in row), None)
        yk = next((k for k in ("y_seiscoord", "y", "node_y") if k in row), None)
        if not xk or not yk:
            continue
        try:
            wl.append((row.get("well_name") or row.get("uwi") or "?", float(row[xk]), float(row[yk])))
        except ValueError:
            continue
    if not wl:
        return {"verdict": "unverified", "reason": "не прочитаны координаты скважин"}

    found, checked = [], 0
    for name, x, y in wl:
        i = int(round((x - xmin) / dx))
        j = int(round((ymax - y) / dy))          # первая строка CPS — верх (ymax)
        if not (0 <= i < ncol and 0 <= j < nrow):
            continue
        v = cell(i, j)
        if v is None:
            continue
        ring = [cell(i + di, j + dj)
                for dj in range(-radius_cells, radius_cells + 1)
                for di in range(-radius_cells, radius_cells + 1)
                if (abs(di) == radius_cells or abs(dj) == radius_cells)
                and 0 <= i + di < ncol and 0 <= j + dj < nrow]
        ring = [r for r in ring if r is not None]
        if len(ring) < 8:
            continue
        checked += 1
        ring.sort()
        med = ring[len(ring) // 2]
        dev = v - med
        if abs(dev) >= threshold and (v >= ring[-1] or v <= ring[0]):
            found.append({"well": name, "value": round(v, 3), "ring_median": round(med, 3),
                          "dev": round(dev, 3), "type": "максимум" if dev > 0 else "минимум"})
    if not checked:
        return {"verdict": "unverified", "reason": "ни одна скважина не попала в поверхность"}
    share = len(found) / checked
    return {"verdict": "failed" if share >= 0.2 else "passed",
            "checked_wells": checked, "bullseyes": len(found), "share": round(share, 3),
            "threshold": threshold, "radius_cells": radius_cells,
            "worst": sorted(found, key=lambda d: -abs(d["dev"]))[:5],
            "reason": (f"локальная подсадка на скважины: {len(found)} из {checked} "
                       f"(порог {threshold} м, кольцо {radius_cells} ячеек)")}


def _wellhead_in_run(run_dir: Path) -> Path | None:
    """Таблица устьев в каталоге прогона — по ролям/маскам ДАННЫХ (`core.datasets`)."""
    try:
        from core.datasets import resolve_inputs
        found = resolve_inputs(Path(run_dir)).get("wellheads")
        return Path(found) if found else None
    except Exception:                                   # noqa: BLE001 — данных может не быть
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="поиск «бычьих глаз» на поверхности")
    ap.add_argument("--surface", default=None)
    ap.add_argument("--run", default=None)
    ap.add_argument("--compare", nargs="*", default=None, help="имена поверхностей из каталога прогона")
    ap.add_argument("--wells", default=None)
    ap.add_argument("--radius", type=int, default=None)
    ap.add_argument("--threshold", type=float, default=None)
    args = ap.parse_args()

    from core.config import load_config
    cfg = load_config()
    radius = args.radius if args.radius is not None else int(
        cfg.get("checks.surface_bullseye.radius_cells", 3) or 3)
    thr = args.threshold if args.threshold is not None else float(
        cfg.get("checks.surface_bullseye.threshold", 10.0) or 10.0)
    run_dir = Path(args.run) if args.run else cfg.path("runs.root", "runs") / \
        f"run_{cfg.get('project.default_field', '')}"
    # Таблица устьев — ИЗ ДАННЫХ прогона (роль `wellheads` по маскам онтологии),
    # а не литерал имени файла: имя файла поля в коде не живёт (правило 1).
    wells = Path(args.wells) if args.wells else _wellhead_in_run(run_dir)
    if wells is None:
        print(f"таблица устьев в прогоне не найдена ({run_dir}) — укажите --wells")
        return 2

    targets: list[Path] = []
    if args.surface:
        targets = [Path(args.surface)]
    elif args.compare:
        for nm in args.compare:
            for cand in run_dir.glob(f"{nm}*.txt"):
                targets.append(cand)
    if not targets:
        print("нечего проверять: задайте --surface или --compare")
        return 2
    print(f"скважины: {wells} | радиус (ячеек): {radius} | порог: {thr} м")
    for t in targets:
        res = bullseyes_geo(t, wells, radius, thr)
        print(f"{t.name}: " + json.dumps(res, ensure_ascii=False)[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
