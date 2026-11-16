"""Единый разбор ASCII-сеток структурных карт (IRAP/RMS ``*.irap``) и XYZ-точек.

Раньше разбор irap был продублирован в трёх местах (`domain/map_render.py`,
`agents/evidence.py`, `domain/trajectories.py`) и предполагал ТОЛЬКО «простой»
формат (`nx ny` / экстент / данные). Экспорт tNavigator/RMS — «полный» формат,
из-за чего `nx` читался как модуль магического числа (`|-996| = 996` вместо 251),
а строка поворота попадала в данные → карта рисовалась мусором («странный разрез»).

Форматы:
  * «полный» (IRAP/RMS): 1-е число 1-й строки — отрицательное магическое (``-996``):
        -996 <ny> <xinc> <yinc>
        <xmin> <xmax> <ymin> <ymax>
        <nx> <rotation> <x0> <y0>
        <значения: nx на строку, ny строк; строки могут переноситься>
  * «простой»:
        <nx> <ny>
        <x0> <x1> <y0> <y1>
        <значения>

Данные читаются как ПЛОСКИЙ поток токенов после заголовка; лишние ведущие
токены (артефакт экспортёра — несколько нулей перед сеткой) отбрасываются,
чтобы выровнять поток на ровно ``nx*ny`` ячеек. Сетка row-major: строка =
постоянный Y (индекс строки растёт вместе с Y: строка 0 → ``y0``).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BLANK_ABS_DEFAULT = 1.0e6            # |значение| >= 1e6 → «нет данных» (9999900 и т.п.)


@dataclass(frozen=True)
class IrapGrid:
    """Прямоугольная ASCII-сетка: заголовок + плоские значения ``nx*ny`` (row-major)."""

    nx: int
    ny: int
    x0: float
    x1: float
    y0: float
    y1: float
    values: tuple[float, ...]
    rotation: float = 0.0

    @property
    def total(self) -> int:
        return self.nx * self.ny

    def cell_xy(self, iy: int, ix: int) -> tuple[float, float]:
        """Координаты узла (ix, iy); строка 0 → ``y0``, столбец 0 → ``x0``."""
        x = self.x0 + (self.x1 - self.x0) * ix / max(self.nx - 1, 1)
        y = self.y0 + (self.y1 - self.y0) * iy / max(self.ny - 1, 1)
        return x, y

    def is_blank(self, value: float, novalue: float | None,
                 blank_abs: float | None) -> bool:
        if novalue is not None and abs(value - novalue) < 1.0:
            return True
        thr = BLANK_ABS_DEFAULT if blank_abs is None else float(blank_abs)
        return abs(value) >= thr

    def points(self, *, novalue: float | None = None, blank_abs: float | None = None
               ) -> tuple[list[float], list[float], list[float]]:
        """(xs, ys, zs) только по НЕпустым узлам — для отрисовки/bbox."""
        xs: list[float] = []
        ys: list[float] = []
        zs: list[float] = []
        for iy in range(self.ny):
            for ix in range(self.nx):
                val = self.values[iy * self.nx + ix]
                if self.is_blank(val, novalue, blank_abs):
                    continue
                x, y = self.cell_xy(iy, ix)
                xs.append(x)
                ys.append(y)
                zs.append(val)
        return xs, ys, zs


def _is_number(token: str) -> bool:
    try:
        float(token)
        return True
    except (TypeError, ValueError):
        return False


def _header(lines: list[str]) -> tuple[int, int, float, float, float, float,
                                       float, int] | None:
    """(nx, ny, x0, x1, y0, y1, rotation, data_start) или None.

    Распознаёт «полный» (магическое отрицательное число) и «простой» форматы.
    """
    if len(lines) < 3:
        return None
    h0 = lines[0].split()
    h1 = lines[1].split()
    if len(h0) < 2 or len(h1) < 4:
        return None
    try:
        first = float(h0[0])
        ny = int(float(h0[1]))
        if not _is_number(h1[0]):
            return None
        x0, x1, y0, y1 = (float(h1[0]), float(h1[1]), float(h1[2]), float(h1[3]))
        if first < 0 and len(lines) >= 4:          # «полный» irap: nx в 3-й строке
            h2 = lines[2].split()
            nx = abs(int(float(h2[0])))
            rotation = float(h2[1]) if len(h2) > 1 else 0.0
            data_start = 3
        else:                                      # «простой»: nx в 1-й строке
            nx = abs(int(first))
            rotation = 0.0
            data_start = 2
    except (IndexError, ValueError):
        return None
    if nx <= 0 or ny <= 0:
        return None
    return nx, ny, x0, x1, y0, y1, rotation, data_start


def read_irap_text(text: str) -> IrapGrid | None:
    """Разобрать содержимое irap-файла → :class:`IrapGrid` (или None)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    head = _header(lines)
    if head is None:
        return None
    nx, ny, x0, x1, y0, y1, rotation, data_start = head
    values: list[float] = []
    for ln in lines[data_start:]:
        for tok in ln.split():
            if _is_number(tok):
                values.append(float(tok))
    total = nx * ny
    if len(values) < total:
        return None
    if len(values) > total:                        # артефакт экспортёра: лишние ведущие
        values = values[len(values) - total:]
    return IrapGrid(nx=nx, ny=ny, x0=x0, x1=x1, y0=y0, y1=y1,
                    values=tuple(values), rotation=rotation)


def read_irap(path: Path) -> IrapGrid | None:
    """Прочитать irap-файл → :class:`IrapGrid` (или None, если это не сетка)."""
    path = Path(path)
    if not path.is_file():
        return None
    return read_irap_text(path.read_text(encoding="utf-8", errors="replace"))


def read_irap_extent(path: Path, *, valid_only: bool = False,
                     novalue: float | None = None,
                     blank_abs: float | None = None
                     ) -> tuple[float, float, float, float] | None:
    """(Xmin, Xmax, Ymin, Ymax) карты irap.

    По умолчанию — ДЕКЛАРИРОВАННЫЙ экстент (2-я строка заголовка): это область
    модели, она включает все устья скважин. ``valid_only=True`` — bbox только
    НЕпустых узлов (карта может быть заполнена частично).
    """
    grid = read_irap(path)
    if grid is None:
        return None
    decl = (min(grid.x0, grid.x1), max(grid.x0, grid.x1),
            min(grid.y0, grid.y1), max(grid.y0, grid.y1))
    if not valid_only:
        return decl
    xs, ys, _ = grid.points(novalue=novalue, blank_abs=blank_abs)
    if len(xs) < 3:
        return decl
    return (min(xs), max(xs), min(ys), max(ys))


def read_irap_mean_z(path: Path, *, novalue: float | None = None,
                     blank_abs: float | None = None) -> float | None:
    """Средняя отметка НЕпустых узлов карты — «середина» пласта для region сетки."""
    grid = read_irap(path)
    if grid is None:
        return None
    _, _, zs = grid.points(novalue=novalue, blank_abs=blank_abs)
    return sum(zs) / len(zs) if zs else None


def irap_stats(path: Path, novalue: float | None = None,
               blank_abs: float | None = None) -> dict | None:
    """Статистика irap: ячейки, бланк, extent (единый разбор с остальными)."""
    grid = read_irap(path)
    if grid is None:
        return None
    blank = sum(1 for val in grid.values if grid.is_blank(val, novalue, blank_abs))
    extent = read_irap_extent(path)
    return {
        "path": str(path),
        "ncols": grid.nx,
        "nrows": grid.ny,
        "total": grid.total,
        "parsed": grid.total,
        "blank": blank,
        "extent": ({"x0": extent[0], "x1": extent[1], "y0": extent[2], "y1": extent[3]}
                   if extent else {}),
    }

