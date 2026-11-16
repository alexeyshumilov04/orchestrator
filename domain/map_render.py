"""Фолбэк отрисовки карт, когда нативный PNG тНава не получен.

Источники — ДАННЫЕ (`checks.map_sources` в config.yaml) ИЛИ нативная выгрузка
карты, сделанная воркфлоу тНава (шаг `map_2d_export_ascii_format` /
`map_2d_export_cps_format` → файл в каталоге проекта, см. `domain/qc/maps.py`).

Поддерживаются оба формата выгрузки тНава (подтверждено пробой на 26.2):
  * 2D-Карты ASCII — «полный irap» (`-996 nx dx dy`), разбирается `domain.irap`;
  * CPS-3 Grid (ASCII) — `FSASCI/FSATTR/FSLIMI/FSNROW/FSXINC` + значения
    (:func:`read_cps_points`).

Картинка — PNG с изолиниями (`contour`) в каталоге `maps/` рядом с прогоном.
Библиотеки опциональны: без `numpy` или `matplotlib` модуль молча возвращает
`None` (карта просто не появится — «неизвестное ≠ ложь», прогон не штрафуется
за отсутствие библиотеки).

Имена карт и их источники в коде НЕ зашиты: списки приходят из конфигурации.
"""
from __future__ import annotations

from pathlib import Path

from .irap import IrapGrid, read_irap

try:                                        # опциональные зависимости
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")                   # headless: без GUI-окна
    import matplotlib.pyplot as plt
except Exception:                           # noqa: BLE001 — деградация без библиотек
    np = None
    plt = None


def available() -> bool:
    return np is not None and plt is not None


def read_cps_points(path: Path, *, novalue: float | None = None,
                    blank_abs: float | None = None
                    ) -> tuple[list, list, list] | None:
    """Разобрать CPS-3 Grid (ASCII) из выгрузки тНава → (xs, ys, zs).

    Формат (подтверждён файлом выгрузки `map_2d_export_cps_format`, tNav 26.2)::

        FSASCI 0 1 "Computed" 0 99999.000000 0      ← 6-е поле: значение «нет данных»
        FSATTR 0 0
        FSLIMI x0 x1 y0 y1 z0 z1                    ← экстент сетки
        FSNROW nx ny                                ← размеры
        FSXINC dx dy                                ← шаги
        -> Surface                                  ← далее значения (nx на строку)
    """
    path = Path(path)
    if not path.is_file():
        return None
    try:
        lines = [ln.strip() for ln in
                 path.read_text(encoding="utf-8", errors="replace").splitlines()]
    except OSError:
        return None
    nx = ny = 0
    extent: list[float] = []
    header_blank: float | None = None
    data_start = -1
    for i, ln in enumerate(lines):
        if ln.startswith("FSASCI"):
            parts = ln.split()
            if len(parts) >= 6:
                try:
                    header_blank = float(parts[5])
                except ValueError:
                    header_blank = None
        elif ln.startswith("FSLIMI"):
            try:
                extent = [float(x) for x in ln.split()[1:5]]
            except ValueError:
                extent = []
        elif ln.startswith("FSNROW"):
            try:
                nx, ny = int(float(ln.split()[1])), int(float(ln.split()[2]))
            except (IndexError, ValueError):
                return None
        elif ln.startswith("->"):
            data_start = i + 1
            break
    if data_start < 0 or nx <= 0 or ny <= 0 or len(extent) < 4:
        return None
    values: list[float] = []
    for ln in lines[data_start:]:
        for tok in ln.replace(",", " ").split():
            if _is_number(tok):
                values.append(float(tok))
    if len(values) < nx * ny:
        return None
    if len(values) > nx * ny:
        values = values[len(values) - nx * ny:]
    grid = IrapGrid(nx=nx, ny=ny, x0=extent[0], x1=extent[1], y0=extent[2],
                    y1=extent[3], values=tuple(values))
    known = novalue if novalue is not None else header_blank
    return grid.points(novalue=known, blank_abs=blank_abs)


def read_ascii_grid(path: Path, *, novalue: float | None = None,
                    blank_abs: float | None = None) -> tuple[list, list, list] | None:
    """Прочитать ascii-сетку (irap / CPS-выгрузка тНава / XYZ) → (xs, ys, zs).

    Формат irap (И «полный», И «простой») разбирает ``domain.irap.read_irap``;
    формат CPS-3 Grid — :func:`read_cps_points`. Если это не сетка (например,
    XYZ-таблица точек) — используется построчный разбор колонок X Y Z.
    """
    path = Path(path)
    if not path.is_file():
        return None
    grid = read_irap(path)
    if grid is not None:
        xs, ys, zs = grid.points(novalue=novalue, blank_abs=blank_abs)
        # Формат распознан: если непустых узлов нет — это ПУСТАЯ карта,
        # а не XYZ-таблица (иначе заголовок был бы разобран как точки).
        return (xs, ys, zs) if zs else None
    cps = read_cps_points(path, novalue=novalue, blank_abs=blank_abs)
    if cps is not None:
        return cps if cps[2] else None
    # XYZ-таблица (точки X Y Z) — только если сетка не распознана вовсе
    lines = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if ln.strip()]
    xs, ys, zs = [], [], []
    for ln in lines:
        parts = ln.replace(",", " ").split()
        if len(parts) < 3 or not all(_is_number(p) for p in parts[:3]):
            continue
        xs.append(float(parts[0]))
        ys.append(float(parts[1]))
        zs.append(float(parts[2]))
    return (xs, ys, zs) if len(zs) >= 3 else None


# Минимум непустых узлов, при котором изолинии вообще строятся (не домен —
# ограничение отрисовки; ниже — карта считается ПУСТОЙ, а не «нарисованной»).
MIN_RENDER_POINTS = 10


def count_points(source: Path, *, novalue: float | None = None,
                 blank_abs: float | None = None) -> int:
    """Число НЕпустых узлов карты (0 — карта пустая/не разобрана) — для диагностики.

    Нужно, чтобы отличать «файл не разобран» от «карта пустая: все значения —
    бланк» (реальный случай F-18: выгрузка STOIIP из тНава целиком бланковая).
    """
    grid = read_ascii_grid(source, novalue=novalue, blank_abs=blank_abs)
    return len(grid[2]) if grid else 0


def render_map(source: Path, out_png: Path, *, novalue: float | None = None,
               blank_abs: float | None = None, title: str = "",
               levels: int = 12) -> Path | None:
    """Отрисовать карту с изолиниями → PNG. None — если нет данных/библиотек."""
    if not available():
        return None
    grid = read_ascii_grid(source, novalue=novalue, blank_abs=blank_abs)
    if not grid or len(grid[2]) < MIN_RENDER_POINTS:
        return None
    xs, ys, zs = grid
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 6), dpi=120)
    try:
        cf = ax.tricontourf(xs, ys, zs, levels=levels, cmap="terrain")
        ax.tricontour(xs, ys, zs, levels=levels, colors="black", linewidths=0.5)
        fig.colorbar(cf, ax=ax, shrink=0.85)
        ax.set_title(title or out_png.stem)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel("X, м")
        ax.set_ylabel("Y, м")
        fig.tight_layout()
        fig.savefig(out_png)
        return out_png
    except Exception:                       # noqa: BLE001 — карта не критична
        return None
    finally:
        plt.close(fig)


def render_missing(run_dir: Path, names: list[str], sources: dict, *,
                   novalue: float | None = None, blank_abs: float | None = None,
                   extra_sources: dict | None = None) -> list[str]:
    """Дорисовать отсутствующие карты по источникам из данных → список имён PNG.

    Источники: `sources` (ДАННЫЕ `checks.map_sources`) и `extra_sources` —
    например, нативные выгрузки карт, снятые с проектного графа
    (`domain.qc.maps.native_sources`). Первое найденное имя файла выигрывает.
    """
    run_dir = Path(run_dir)
    maps_dir = run_dir / "maps"
    done: list[str] = []
    extra = {str(k): str(v) for k, v in (extra_sources or {}).items()}
    for name in names:
        name = str(name)
        if (maps_dir / f"{name}.png").is_file():
            continue
        rel = str((sources or {}).get(name) or "") or extra.get(name, "")
        if not rel:
            continue
        out = render_map(run_dir / rel, maps_dir / f"{name}.png",
                         novalue=novalue, blank_abs=blank_abs, title=name)
        if out is not None:
            done.append(name)
    return done


def _is_number(token: str) -> bool:
    try:
        float(token)
        return True
    except (TypeError, ValueError):
        return False
