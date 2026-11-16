"""Геостатистика свойств по ДАННЫМ (а не «случайные поля»).

Процесс (по онтологии СМП/ГГДМ):
  1) интерпретация ГИС — из LAS берём ФЕС по скважинам (пористость, проницаемость,
     литология, насыщение, глинистость); МНЕМОНИКИ кривых — данные вызывающей стороны;
  2) выбор метода (MethodSelection) — кригинг / SGS / ко-кригинг / IDW по данным;
  3) построение поля свойства по методике: условное среднее (кригинг/IDW)
     + коррелированный остаток (SGS) для реализаций ансамбля.

Без numpy модуль работает, но медленнее (fallback на stdlib).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

try:                                    # numpy ускоряет поля; при отсутствии — fallback
    import numpy as _np
except Exception:                        # noqa: BLE001
    _np = None

NULL = -999.0


@dataclass
class WellSample:
    """Скважинный отсчёт ФЕС (реальные данные каротажа)."""

    name: str
    x: float
    y: float
    poro: float | None = None       # дол.ед.
    perm: float | None = None       # мД
    sw: float | None = None
    vcl: float | None = None
    facies: int | None = None       # код литологии (1 песчаник, 2 глина, ...)
    points: int = 0                 # сколько отсчётов усреднено


def read_las(path: Path) -> dict:
    """Прочитать LAS (ASCII): мнемоники кривых, NULL и таблицу данных."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"mnems": [], "data": [], "null": NULL, "uwi": "", "well": ""}
    mnems: list[str] = []
    data: list[list[float]] = []
    null = NULL
    uwi = ""
    well = ""
    section = ""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("~"):
            section = (s[1:].split() or [""])[0].upper()
            continue
        if section.startswith("W"):                       # ~Well / ~VERSION
            up = s.upper()
            if up.startswith("NULL"):
                num = re.search(r"(-?\d+\.?\d*)", s)
                if num:
                    null = float(num.group(1))
            elif up.startswith("UWI"):
                uwi = s.split(".", 1)[1].split(":")[0].strip() if "." in s else ""
            elif up.startswith("WELL"):
                well = s.split(".", 1)[1].split(":")[0].strip() if "." in s else ""
            continue
        if section.startswith("C"):                        # ~Curve
            if s.startswith("#"):
                continue
            mnem = s.split(".")[0].strip().split()[0] if s.split() else ""
            if mnem:
                mnems.append(mnem.upper())
            continue
        if section.startswith("A"):                        # ~Ascii
            parts = s.split()
            if len(parts) < 2:
                continue
            row: list[float] = []
            for token in parts:
                try:
                    row.append(float(token))
                except ValueError:
                    row = []
                    break
            if row:
                data.append(row)
    return {"mnems": mnems, "data": data, "null": null, "uwi": uwi, "well": well}


def _curve_mean(las: dict, mnem: str, *, positive: bool = False) -> float | None:
    """Среднее по кривой с фильтром NULL (и опционально > 0)."""
    if mnem not in las["mnems"]:
        return None
    idx = las["mnems"].index(mnem)
    values: list[float] = []
    for row in las["data"]:
        if idx >= len(row):
            continue
        value = row[idx]
        if abs(value - las["null"]) < 1e-3 or abs(value) > 1e28:
            continue
        if positive and value <= 0:
            continue
        values.append(value)
    return sum(values) / len(values) if values else None


def _curve_mode(las: dict, mnem: str) -> int | None:
    """Мода (наиболее частое) по дискретной кривой (литология)."""
    if mnem not in las["mnems"]:
        return None
    idx = las["mnems"].index(mnem)
    counts: dict[int, int] = {}
    for row in las["data"]:
        if idx >= len(row):
            continue
        value = row[idx]
        if abs(value - las["null"]) < 1e-3:
            continue
        code = int(round(value))
        if code > 0:
            counts[code] = counts.get(code, 0) + 1
    return max(counts, key=counts.get) if counts else None


def read_wellheads_map(path: Path) -> dict[str, tuple[float, float]]:
    """{uwi: (x, y)} из таблицы устьев (колонки uwi, X, Y — по заголовку файла)."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    if not lines:
        return {}
    header = [h.strip().lower() for h in lines[0].replace("\t", " ").split()]
    idx = {name: k for k, name in enumerate(header)}

    def col(cands: list[str], default: int) -> int:
        for c in cands:
            if c in idx:
                return idx[c]
        return default

    c_uwi = col(["uwi", "well"], 0)
    c_x = col(["x_seiscoord", "x"], 5)
    c_y = col(["y_seiscoord", "y"], 6)
    out: dict[str, tuple[float, float]] = {}
    for line in lines[1:]:
        parts = line.replace("\t", " ").split()
        if len(parts) <= max(c_uwi, c_x, c_y):
            continue
        try:
            out[parts[c_uwi]] = (float(parts[c_x].replace(",", ".")),
                                 float(parts[c_y].replace(",", ".")))
        except ValueError:
            continue
    return out


def _pick_mnem(las: dict, names: tuple) -> str | None:
    for name in names:
        if name in las["mnems"]:
            return name
    return None


def assemble_samples(wellhead_path: Path, log_paths: list[Path], *,
                     limit: int = 60,
                     curve_mnemonics: dict | None = None) -> list[WellSample]:
    """Собрать скважинные отсчёты ФЕС: LAS (пористость/проницаемость/литология) + устья.

    МНЕМОНИКИ кривых — ДАННЫЕ вызывающей стороны (`curve_mnemonics`: роль → список
    кандидатов, например из проектного графа/онтологии): в коде имён кривых нет
    (правило 1). Мнемоники не заданы → выборка не собирается (правило 6), а не
    «угадывается» по первому совпадению.

    Файлы без кривых ФЕС (например, инклинометрия) пропускаются. `limit` — сколько
    УСПЕШНЫХ скважин собрать.
    """
    mnemonics = {str(role): tuple(str(x) for x in (names or ()))
                 for role, names in (curve_mnemonics or {}).items()}
    coords = read_wellheads_map(wellhead_path) if wellhead_path else {}
    samples: list[WellSample] = []
    for path in log_paths:
        las = read_las(path)
        m_poro = _pick_mnem(las, mnemonics.get("porosity", ()))
        m_perm = _pick_mnem(las, mnemonics.get("permeability", ()))
        m_sw = _pick_mnem(las, mnemonics.get("saturation", ()))
        m_vcl = _pick_mnem(las, mnemonics.get("shale", ()))
        m_lit = _pick_mnem(las, mnemonics.get("lithology", ()))
        if not (m_poro or m_perm or m_lit):
            continue
        uwi = las.get("uwi") or Path(path).stem
        xy = coords.get(uwi) or coords.get(Path(path).stem)
        if xy is None:
            continue
        samples.append(WellSample(
            name=uwi, x=xy[0], y=xy[1],
            poro=_curve_mean(las, m_poro) if m_poro else None,
            perm=_curve_mean(las, m_perm, positive=True) if m_perm else None,
            sw=_curve_mean(las, m_sw) if m_sw else None,
            vcl=_curve_mean(las, m_vcl) if m_vcl else None,
            facies=_curve_mode(las, m_lit) if m_lit else None,
            points=len(las["data"])))
        if len(samples) >= limit:
            break
    return samples


def _samples_for(samples: list[WellSample], prop: str) -> list[tuple[float, float, float]]:
    """Точки (x, y, value) по свойству; для проницаемости — в логарифме."""
    pts: list[tuple[float, float, float]] = []
    for s in samples:
        value = {"poro": s.poro, "perm": s.perm, "sw": s.sw, "vcl": s.vcl}.get(prop)
        if value is None:
            continue
        if prop == "perm":
            value = math.log10(max(value, 1e-3))
        pts.append((s.x, s.y, float(value)))
    return pts


def idw_field(nx: int, ny: int, pts: list[tuple[float, float, float]], *,
              xmin: float, ymin: float, dx: float, dy: float,
              power: float = 2.0, default: float = 0.0) -> list[float]:
    """Поле условного среднего по методу обратных взвешенных расстояний (IDW)."""
    if not pts:
        return [default] * (nx * ny)
    if _np is not None:
        arr = _np.asarray(pts, dtype=float)
        gx = xmin + _np.arange(nx) * dx
        gy = ymin + _np.arange(ny) * dy
        X, Y = _np.meshgrid(gx, gy)
        d2 = (X[..., None] - arr[:, 0]) ** 2 + (Y[..., None] - arr[:, 1]) ** 2
        w = 1.0 / (d2 + 1e-6) ** (power / 2.0)
        grid = (w * arr[:, 2]).sum(axis=-1) / w.sum(axis=-1)
        return grid.reshape(-1).tolist()
    out: list[float] = []
    for j in range(ny):
        y = ymin + j * dy
        for i in range(nx):
            x = xmin + i * dx
            num = den = 0.0
            for px, py, pv in pts:
                d2 = (x - px) ** 2 + (y - py) ** 2
                w = 1.0 / (d2 + 1e-6) ** (power / 2.0)
                num += w * pv
                den += w
            out.append(num / den if den else default)
    return out


def _box_smooth(arr, radius: int):
    """Fallback-сглаживание (скользящее среднее) без scipy."""
    r = max(1, radius)
    ny, nx = arr.shape
    out = arr.copy()
    for j in range(ny):
        for i in range(nx):
            j0, j1 = max(0, j - r), min(ny, j + r + 1)
            i0, i1 = max(0, i - r), min(nx, i + r + 1)
            out[j, i] = arr[j0:j1, i0:i1].mean()
    return out


def correlated_noise(nx: int, ny: int, *, seed: int, range_cells: float,
                     nz: int = 1) -> list[float]:
    """Коррелированный (пространственно) остаток — для SGS и реализаций ансамбля.

    Разные seed -> разные реализации. Дальность корреляции задаётся вариограммой.
    """
    if _np is None:
        import random
        rng = random.Random(int(seed) & 0x7FFFFFFF)
        return [rng.gauss(0.0, 1.0) for _ in range(nx * ny * nz)]
    rng = _np.random.default_rng(int(seed) & 0x7FFFFFFF)
    sigma = max(0.6, float(range_cells) / 2.0)
    fields = []
    for _ in range(max(1, nz)):
        white = rng.standard_normal((ny, nx))
        try:
            from scipy.ndimage import gaussian_filter
            smooth = gaussian_filter(white, sigma=sigma, mode="reflect")
        except Exception:                    # noqa: BLE001
            smooth = _box_smooth(white, int(max(1, range_cells)))
        std = float(smooth.std()) or 1.0
        fields.append((smooth / std).reshape(-1))
    return _np.concatenate(fields).tolist()


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / (len(values) - 1)


def _linfit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """МНК-регрессия y = a*x + b (для связи Кп–Кпр)."""
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    a = sxy / sxx if sxx else 0.0
    return a, my - a * mx


def _clip(values: list[float], bounds: tuple[float, float] | None) -> list[float]:
    if not bounds:
        return values
    lo, hi = bounds
    return [min(hi, max(lo, v)) for v in values]


def _stochastic_factor(method: str, params: dict) -> float:
    """Доля стохастического остатка: у кригинга/IDW — 0, у SGS/ко-кригинга — > 0."""
    if params.get("sgs_factor") is not None:
        return float(params["sgs_factor"])
    stochastic = any(k in (method or "") for k in ("sgs", "cokriging", "nn"))
    return 0.55 if stochastic else 0.0


def build_property_field(*, nx: int, ny: int, nz: int, samples: list[WellSample],
                         prop: str, method: str = "method:idw", xmin: float, ymin: float,
                         dx: float, dy: float, seed: int = 11,
                         params: dict | None = None) -> list[float] | None:
    """Построить поле свойства ПО ДАННЫМ выбранным методом (не «случайно»)."""
    params = params or {}
    range_cells = float(params.get("range_cells", 6.0))
    fac = _stochastic_factor(method, params)
    cell = nx * ny

    # проницаемость: ко-кригинг через связь Кп–Кпр (куб логарифма проницаемости)
    if prop == "perm" and any(k in method for k in ("cokriging", "lognormal")):
        pairs = [(s.poro, s.perm) for s in samples if s.poro is not None and s.perm is not None]
        if len(pairs) >= 3:
            a, b = _linfit([p for p, _ in pairs],
                           [math.log10(max(k, 1e-3)) for _, k in pairs])
            poro_pts = _samples_for(samples, "poro")
            poro2d = idw_field(nx, ny, poro_pts, xmin=xmin, ymin=ymin, dx=dx, dy=dy)
            base2d = [a * v + b for v in poro2d]
            sd = math.sqrt(_variance(base2d))
            noise = (correlated_noise(nx, ny, seed=seed, range_cells=range_cells, nz=nz)
                     if fac > 0 else [0.0] * (cell * nz))
            logk = [base2d[i % cell] + noise[i] * sd * fac for i in range(cell * nz)]
            return _clip([10.0 ** v for v in logk], params.get("bounds"))

    pts = _samples_for(samples, prop)
    if not pts:
        return None
    base2d = idw_field(nx, ny, pts, xmin=xmin, ymin=ymin, dx=dx, dy=dy)
    sd = math.sqrt(_variance(base2d))
    noise = (correlated_noise(nx, ny, seed=seed, range_cells=range_cells, nz=nz)
             if fac > 0 else [0.0] * (cell * nz))
    value = [base2d[i % cell] + noise[i] * sd * fac for i in range(cell * nz)]
    if prop == "perm":
        value = [10.0 ** v for v in value]
    return _clip(value, params.get("bounds"))


def facies_field(*, nx: int, ny: int, samples: list[WellSample], xmin: float, ymin: float,
                 dx: float, dy: float) -> list[int] | None:
    """Лито-фациальная модель (SIS-подобно): по индикаторам литологии из ГИС."""
    codes = sorted({s.facies for s in samples if s.facies})
    if not codes:
        return None
    probs = {c: idw_field(nx, ny, [(s.x, s.y, 1.0 if s.facies == c else 0.0)
                                   for s in samples if s.facies is not None],
                          xmin=xmin, ymin=ymin, dx=dx, dy=dy) for c in codes}
    return [max(codes, key=lambda c: probs[c][i]) for i in range(nx * ny)]


def choose_methods(*, n_wells: int = 0, has_logs: bool = False, has_seismic: bool = False,
                   has_poro_perm_link: bool = False, multi_variant: bool = True) -> dict:
    """Блок выбора метода (MethodSelection): метод по имеющимся данным."""
    reasons: dict[str, str] = {}
    if has_logs and has_seismic and n_wells >= 5:
        poro = "method:poro_cokriging"
        reasons["poro"] = "есть сейсмический тренд -> ко-кригинг"
    elif multi_variant and n_wells >= 4:
        poro = "method:poro_sgs"
        reasons["poro"] = "нужен многовариантный подход -> SGS"
    elif n_wells >= 8:
        poro = "method:poro_kriging"
        reasons["poro"] = "ФЕС выдержаны, корреляция по латерали -> кригинг"
    else:
        poro = "method:idw"
        reasons["poro"] = "мало скважин -> IDW"

    if has_logs and has_poro_perm_link and n_wells >= 3:
        perm = "method:perm_lognormal"
        reasons["perm"] = "есть связь Кп-Кпр по каротажу -> куб логарифма K"
    elif multi_variant and n_wells >= 4:
        perm = "method:perm_sgs"
        reasons["perm"] = "многовариантный подход -> SGS (лог-К)"
    else:
        perm = "method:idw"
        reasons["perm"] = "IDW по лог-проницаемости"

    facies = "method:facies_sis" if has_logs else None
    if facies:
        reasons["facies"] = "литология выделена по ГИС -> SIS"
    return {"poro": poro, "perm": perm, "facies": facies, "reasons": reasons}


def samples_summary(samples: list[WellSample]) -> dict:
    """Сводка по скважинным данным (для отчёта/UI)."""
    def stat(key: str) -> dict:
        vals = [getattr(s, key) for s in samples if getattr(s, key) is not None]
        if not vals:
            return {"n": 0, "mean": None, "min": None, "max": None}
        return {"n": len(vals), "mean": sum(vals) / len(vals),
                "min": min(vals), "max": max(vals)}
    return {"wells": len(samples), "poro": stat("poro"), "perm": stat("perm"),
            "sw": stat("sw"), "vcl": stat("vcl"),
            "facies_codes": sorted({s.facies for s in samples if s.facies})}
