"""ПОДГОТОВКА ДАННЫХ: инклинометрия (LAS) + головки скважин → таблицы траекторий.

Зачем: тНав требует, чтобы объекты `Wells` (`gt_wells_entity`) и `Trajectories`
СУЩЕСТВОВАЛИ до импорта ГИС (`wells_log_import_las_format`) и маркеров
(`marker_import_txt_format`) — иначе валидация падает с
«cannot be started due to invalid input parameter (type 'Wells table', name 'Wells')».

Их создаёт `wells_import_path_deviation_format` (шаблон уже есть). Он читает одну
таблицу на скважину: `MD X Y Z` (имя скважины = имя файла).

Здесь: из LAS-инклинометрии (`DEPT/ANGLE/AZIM`) и таблицы устьев (X/Y устья +
альтитуда) считаем пространственную траекторию методом минимальной кривизны и
пишем `Wells/<well>.txt`.

Всё — данные: пути и имена колонок берутся из проектного графа (`inputs.*`).
"""
from __future__ import annotations

import math
from pathlib import Path

from .irap import read_irap_extent as _irap_extent
from .irap import read_irap_mean_z as _irap_mean_z

# Запасные индексы колонок таблицы устьев (если заголовок не распознан).
_WH_WELL, _WH_X, _WH_Y, _WH_KB = 1, 5, 6, 8


def _pick_column(header: list[str], prefer: list[str], fallback: int | None) -> int | None:
    """Индекс колонки по имени (точное совпадение, затем подстрока), иначе fallback."""
    low = [h.strip().lower() for h in header]
    for want in prefer:
        for i, h in enumerate(low):
            if h == want:
                return i
    for want in prefer:
        for i, h in enumerate(low):
            if want and want in h:
                return i
    return fallback


def wellhead_columns(path: Path) -> dict:
    """Определить колонки Wellhead.txt по ЗАГОЛОВКУ (данные, а не хардкод индексов).

    X/Y берутся из «сейсмических» координат (`X_seiscoord`/`y_seiscoord`) — именно они
    совпадают с системой структурных карт (`*.irap`); `node_x/node_y` — другая система.
    """
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    header = lines[0].split() if lines else []
    cols = {
        "well": _pick_column(header, ["well_name", "well name", "well", "name", "uwi"], _WH_WELL),
        "x": _pick_column(header, ["x_seiscoord", "x_seis", "x"], _WH_X),
        "y": _pick_column(header, ["y_seiscoord", "y_seis", "y"], _WH_Y),
        "kb": _pick_column(header, ["elevation", "kb", "z", "altitude"], _WH_KB),
        "skip_lines": 1,
    }
    return cols


def read_wellheads(path: Path) -> dict[str, dict]:
    """`Wellhead.txt` → {имя скважины: {x, y, kb, uwi}} (колонки — из заголовка)."""
    out: dict[str, dict] = {}
    path = Path(path)
    if not path.is_file():
        return out
    cols = wellhead_columns(path)
    w_i, x_i, y_i, k_i = cols["well"], cols["x"], cols["y"], cols["kb"]
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        parts = line.split()
        need = max(v for v in (w_i, x_i, y_i, k_i) if v is not None)
        if i == 0 or len(parts) <= need:
            continue
        name = parts[w_i].strip()
        if not name:
            continue
        try:
            out[name] = {"x": float(parts[x_i]), "y": float(parts[y_i]),
                         "kb": float(parts[k_i]), "uwi": parts[0]}
        except (TypeError, ValueError):
            continue
    return out


def read_inclinometry(las_path: Path) -> dict | None:
    """LAS инклинометрии → {well, uwi, stations:[(md, incl, azim)]}."""
    text = Path(las_path).read_text(encoding="utf-8", errors="replace")
    if "~Ascii" not in text:
        return None
    head, _, body = text.partition("~Ascii")
    well = uwi = ""
    for line in head.splitlines():
        mn = line.split(".", 1)[0].strip().upper()
        if mn == "WELL":
            well = line.split(":", 1)[0].split(".", 1)[-1].strip()
        elif mn == "UWI":
            uwi = line.split(":", 1)[0].split(".", 1)[-1].strip()
    stations: list[tuple[float, float, float]] = []
    for line in body.splitlines():
        vals = line.split()
        if len(vals) < 3:
            continue
        try:
            md, incl, azim = float(vals[0]), float(vals[1]), float(vals[2])
        except ValueError:
            continue
        if md >= 0:
            stations.append((md, incl, azim))
    if not stations:
        return None
    return {"well": well, "uwi": uwi, "stations": stations}


def _min_curvature(stations: list[tuple[float, float, float]],
                   x0: float, y0: float, kb: float) -> list[tuple[float, float, float, float]]:
    """Минимальная кривизна: (MD, INCL, AZIM) + устье → [(MD, X, Y, Z)] (Z — абсолютная).

    Траектория начинается в устье при MD=0. Доглег считается по КЛАССИЧЕСКОЙ формуле
    cosβ = cos(I₂−I₁) − sin I₁·sin I₂·(1 − cos ΔA): именно `sin`, а НЕ `cos`.
    Прежний `cos` давал у вертикальной скважины (I≈0) фиктивный доглег ≈ ΔA → rf = 38
    и разлёт XYZ в разы больше MD (тНав: «MD length of some trajectory segments is
    smaller than the corresponding XYZ length»). С верной формулой |ΔXYZ| ≤ ΔMD
    аналитически (|Δ| = ΔMD·(2/β)·sin(β/2) ≤ ΔMD), поэтому предупреждение исчезает.
    """
    rows: list[tuple[float, float, float, float]] = [(0.0, x0, y0, kb)]
    x, y, z = x0, y0, kb
    # виртуальная станция в устье (MD=0) с углами первой замеренной станции
    prev = (0.0, stations[0][1], stations[0][2])
    for cur in stations:
        md1, i1, a1 = prev
        md2, i2, a2 = cur
        dmd = md2 - md1
        if dmd <= 0:
            prev = cur
            continue
        r1, r2 = math.radians(i1), math.radians(i2)
        da = math.radians(a2 - a1)
        cos_dl = math.cos(r2 - r1) - math.sin(r1) * math.sin(r2) * (1.0 - math.cos(da))
        dl = math.acos(max(-1.0, min(1.0, cos_dl)))
        rf = 1.0 if abs(dl) < 1e-9 else (2.0 / dl) * math.tan(dl / 2.0)
        dn = (dmd / 2.0) * (math.sin(r1) * math.cos(math.radians(a1)) +
                            math.sin(r2) * math.cos(math.radians(a2))) * rf
        de = (dmd / 2.0) * (math.sin(r1) * math.sin(math.radians(a1)) +
                            math.sin(r2) * math.sin(math.radians(a2))) * rf
        dv = (dmd / 2.0) * (math.cos(r1) + math.cos(r2)) * rf
        # страховка: при шумной инклинометрии не даём сегменту превысить свой MD
        mag = math.sqrt(dn * dn + de * de + dv * dv)
        if mag > dmd > 0.0:
            scale = dmd / mag
            dn, de, dv = dn * scale, de * scale, dv * scale
        x += de
        y += dn
        z -= dv
        rows.append((md2, x, y, z))
        prev = cur
    return rows


def _enforce_md_ge_xyz(rows: list[tuple[float, float, float, float]],
                       margin: float = 1e-3) -> list[tuple[float, float, float, float]]:
    """Гарантировать в ЗАПИСЫВАЕМОМ файле `MD-шаг >= |ΔXYZ|` (требование тНава).

    Минимальная кривизна даёт |ΔXYZ| <= ΔMD, но округление координат при записи может
    дать микроскопическое превышение (и предупреждение «MD length ... smaller than ...
    XYZ length»). Здесь MD поднимается на величину дефицита (+ запас на округление);
    сдвиг копится, MD монотонен. Для наклонных скважин поправка нулевая, для
    субвертикальных (|ΔXYZ| ≈ ΔMD) — порядка 1e-3 м на станцию, что на порядки меньше
    методической погрешности привязки (QC допускает ~2 м).
    """
    out: list[tuple[float, float, float, float]] = [rows[0]]
    shift = 0.0
    for cur in rows[1:]:
        prev = out[-1]
        mag = math.dist(cur[1:], prev[1:])
        md = cur[0] + shift
        if md - prev[0] < mag + margin:
            md = prev[0] + mag + margin
            shift = md - cur[0]
        out.append((md, cur[1], cur[2], cur[3]))
    return out


def prepare_trajectories(wellhead_path: Path, incl_dir: Path, out_dir: Path) -> dict:
    """Сгенерировать `out_dir/<well>.txt` (MD X Y Z) для импорта траекторий.

    Возвращает сводку: {'written': [...], 'skipped': [...], 'out_dir': str}.
    """
    wellheads = read_wellheads(Path(wellhead_path))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    skipped: list[str] = []
    for las in sorted(Path(incl_dir).glob("*.las")):
        inc = read_inclinometry(las)
        if not inc:
            skipped.append(las.name)
            continue
        wh = wellheads.get(inc["well"]) or next(
            (v for v in wellheads.values() if v.get("uwi") == inc["uwi"]), None)
        if wh is None:
            skipped.append(las.name)
            continue
        rows = _min_curvature(inc["stations"], wh["x"], wh["y"], wh["kb"])
        rows = _enforce_md_ge_xyz(rows)
        safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in inc["well"])
        dst = out_dir / f"{safe}.txt"
        lines = ["MD X Y Z"]
        lines += [f"{md:.4f}\t{x:.4f}\t{y:.4f}\t{z:.4f}" for md, x, y, z in rows]
        dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(dst.name)
    return {"written": written, "skipped": skipped, "out_dir": str(out_dir)}


# -- ГРАНИЦА МОДЕЛИ из структурной карты ---------------------------------------
#
# В эталонном воркфлоу граница модели — это отдельный ПОЛИГОН, импортируемый ДО
# построения горизонтов и сетки (`polygon_import_*_format`). Он нужен как: region
# сетки, sample-object (авто-бокс) и фильтр волюметрии. ИМЯ объекта задаётся
# ДАННЫМИ поля (роль шага), а не литералом: `prepare_boundary(name=...)`.
# Здесь граница строится по НЕПУСТЫМ узлам структурной карты (ascii-irap, Surfer).


def read_irap_extent(path: Path, *, valid_only: bool = False) -> tuple[float, float, float, float] | None:
    """(Xmin, Xmax, Ymin, Ymax) карты ascii-irap (разбор — `domain.irap`).

    По умолчанию — ДЕКЛАРИРОВАННЫЙ экстент карты (2-я строка заголовка): это и есть
    область модели, и она включает все устья скважин. `valid_only=True` — bbox только
    непустых узлов (карта может быть заполнена частично, поэтому по умолчанию — заголовок).
    """
    return _irap_extent(Path(path), valid_only=valid_only)


def read_irap_mean_z(path: Path) -> float | None:
    """Средняя отметка НЕПУСТЫХ узлов карты — «середина» пласта (разбор — `domain.irap`).

    Зачем: контур модели (region сетки) тНав понимает ТРЁХМЕРНО. Пока горизонты были
    мусорными (±1e7) и пересекали Z=0, сетка строилась; с корректными горизонтами
    (−2400…−2530) плоский контур на Z=0 модель НЕ пересекает и сетка выходит пустой
    («The resulting grid has no elements!»). Берём среднюю отметку карты — значение
    из данных, гарантированно внутри интервала.
    """
    return _irap_mean_z(Path(path))


def prepare_boundary(surface_irap: Path, out_dir: Path, *, name: str = "",
                     expand: float = 0.0) -> Path | None:
    """Записать `<out_dir>/Polygons/<name>.txt` — замкнутый контур модели (`X Y`).

    ИМЯ объекта — ДАННЫЕ поля (роль шага графика/объектов проекта): не задано →
    контур НЕ пишется (правило 6: нельзя угадать имя объекта, которое ждёт
    воркфлоу), и вызывающая сторона фиксирует это как unknown.
    Соответствует шаблону `polygon_import_txt_format`, который импортируется в
    самом начале воркфлоу.
    """
    surface_name = str(name or "").strip()
    if not surface_name:
        return None
    ext = read_irap_extent(Path(surface_irap))
    if ext is None:
        return None
    x0, x1, y0, y1 = ext
    x0 -= expand
    y0 -= expand
    x1 += expand
    y1 += expand
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{surface_name}.txt"
    # контур по периметру (замкнутый), с промежуточными точками для устойчивости
    pts: list[tuple[float, float]] = []
    steps = 12
    for i in range(steps):
        pts.append((x0 + (x1 - x0) * i / steps, y0))
    for i in range(steps):
        pts.append((x1, y0 + (y1 - y0) * i / steps))
    for i in range(steps):
        pts.append((x1 - (x1 - x0) * i / steps, y1))
    for i in range(steps):
        pts.append((x0, y1 - (y1 - y0) * i / steps))
    pts.append(pts[0])
    # 3 колонки X Y Z. Z — НЕ 0: контур трёхмерный, и Z=0 при горизонтах на −2400
    # не пересекает модель (сетка выходит пустой). Берём среднюю отметку карты.
    z_level = read_irap_mean_z(Path(surface_irap))
    z_text = f"{z_level:.4f}" if z_level is not None else "0.0000"
    dst.write_text("\n".join(f"{x:.4f}\t{y:.4f}\t{z_text}" for x, y in pts) + "\n",
                   encoding="utf-8")
    return dst
