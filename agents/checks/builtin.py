"""Builtin-проверки гейтов: считаются по свидетельствам этапа без тНава.

Полный набор — по мере подключения пробников (см. `domain/tnav_probes.py`).
Каждая функция возвращает ``Finding`` или ``None`` (не применима — нет данных).

Отдельный класс — проверки РЕЗУЛЬТАТА (F-19): «объект существует и непуст». Их
свидетельства (``grid_properties``, ``property_stats``, ``blocked_wells``) готовит
пробник по проекту. Если свидетельства НЕТ, находка помечается ``UNVERIFIED``:
гейт не может стать ``passed`` (нельзя «зелено» без результата), но и не падает —
отсутствие данных не является провалом модели (правило 6). Имена объектов берутся
ТОЛЬКО из данных (``checks.properties`` / ``ensemble.metric``).

Пороговые значения — из `ctx` (собирает `agents.evidence.check_context`;
переопределяются секцией `checks:` конфигурации) и данные проекта.
"""
from __future__ import annotations

import math

from pathlib import Path

from agents.contracts import UNVERIFIED, Finding
from agents.checks.base import CheckSpec


def _mk(check_id: str, severity: str, passed: bool, title: str, *,
        message: str = "", remediation: str = "", evidence: dict | None = None) -> Finding:
    return Finding(id=check_id, severity=severity, passed=bool(passed), title=title,
                   message=message, source="builtin", remediation=remediation,
                   evidence=evidence or {})


def _unverified(check_id: str, severity: str, title: str, why: str, *,
                remediation: str = "", evidence: dict | None = None) -> Finding:
    """«Результат не проверен»: нет свидетельства. Гейт не станет passed (F-19)."""
    return Finding(id=check_id, severity=severity, passed=True, state=UNVERIFIED,
                   title=title, message=f"не проверено: {why}", source="builtin",
                   remediation=remediation, evidence=evidence or {})


def _data_name(ctx: dict, role: str, fallback: str) -> str:
    """Имя объекта модели ИЗ ДАННЫХ: ``checks.properties.<role>.cube`` (ключи данных).

    В коде остаются только КЛЮЧИ (``properties``/``cube``), значения приходят из
    config.yaml через контекст проверок; нет данных → нейтральное описание ключа.
    """
    props = ctx.get("properties")
    node = props.get(role) if isinstance(props, dict) else None
    cube = node.get("cube") if isinstance(node, dict) else None
    return str(cube) if cube else fallback


def _data_cube(ctx: dict, role: str) -> str:
    """Имя куба/свойства роли ИЗ ДАННЫХ или '' (нет данных — судить нельзя).

    Роль ``metric`` берёт имя из ``ensemble.metric`` (метрика проекта), остальные —
    из ``checks.properties.<роль>.cube``. В коде — только КЛЮЧИ данных.
    """
    if role == "metric":
        value = ctx.get("metric_name")
        return str(value) if value else ""
    props = ctx.get("properties")
    node = props.get(role) if isinstance(props, dict) else None
    cube = node.get("cube") if isinstance(node, dict) else None
    return str(cube) if cube else ""


# Роли проверок результата: id/название/ключ данных. Имена объектов — ДАННЫЕ.
_ROLES: dict[str, dict] = {
    "facies": {"exists": "facies.cube_exists", "nonempty": "facies.cube_nonempty",
               "title": "Куб фаций (дискретный)", "key": "checks.properties.facies.cube"},
    "poro": {"exists": "cube.poro_exists", "nonempty": "cube.poro_nonempty",
             "title": "Куб свойства-пористости", "key": "checks.properties.poro.cube"},
    "perm": {"exists": "cube.perm_exists", "nonempty": "cube.perm_nonempty",
             "title": "Куб свойства-проницаемости", "key": "checks.properties.perm.cube"},
    "metric": {"exists": "cube.metric_exists", "nonempty": "cube.metric_nonempty",
               "title": "Свойство-метрика проекта", "key": "ensemble.metric"},
}


def _role_meta(role: str) -> dict:
    return _ROLES.get(role, {"exists": f"cube.{role}_exists",
                             "nonempty": f"cube.{role}_nonempty",
                             "title": f"Свойство роли {role}",
                             "key": f"checks.properties.{role}.cube"})


# -- проверки РЕЗУЛЬТАТА: объект существует и непуст (F-19) -------------------------
def grid_property_names(ev: dict) -> list[str] | None:
    """Имена свойств сетки из свидетельства пробника; нет свидетельства → None.

    Принимаются формы: ``["A","B"]``, ``{"properties": [...]}``,
    ``[{"name": "A", ...}]`` — пробник может отдать любую.
    """
    raw = ev.get("grid_properties")
    if raw is None:
        return None
    items = raw
    if isinstance(raw, dict):
        nested = raw.get("properties")
        items = nested if isinstance(nested, list) else list(raw.keys())
    names: list[str] = []
    for item in items or []:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
        elif isinstance(item, dict):
            value = item.get("name") or item.get("property") or item.get("cube")
            if value:
                names.append(str(value).strip())
    return names


def _min_fraction(ctx: dict, role: str):
    """Порог доли непустых ячеек роли — ИЗ ДАННЫХ (`checks.properties.<роль>.min_fraction`).

    Нет ключа → порога нет (поведение прежнее: `count > 0`). Порог в коде не задаётся
    (правило 1); F-27: без порога «непустота» формально зелена при почти пустом кубе.
    """
    props = ctx.get("properties")
    node = props.get(role) if isinstance(props, dict) else None
    value = node.get("min_fraction") if isinstance(node, dict) else None
    return float(value) if isinstance(value, (int, float)) else None


def _stats_for(ev: dict, cube: str) -> dict | None:
    """Статистика куба из свидетельства (регистр имени не важен); нет — None."""
    stats = ev.get("property_stats")
    if not isinstance(stats, dict) or not cube:
        return None
    node = stats.get(cube)
    if node is None:
        node = next((v for k, v in stats.items()
                     if str(k).upper() == cube.upper() and isinstance(v, dict)), None)
    return node if isinstance(node, dict) else None


def _cell_count(node: dict) -> float | None:
    """Число НЕПУСТЫХ ячеек куба — синонимы ключей пробника (данные, не догадки).

    Приоритет: явное число непустых (``count``/``non_null*``) → ``cells − nulls``;
    если есть только общее число ячеек без сведений о пустых — вернуть None
    («судить нельзя»): иначе полностью пустой куб выглядел бы непустым.
    """
    for key in ("count", "non_null", "non_null_count", "nn", "non_null_cells"):
        value = node.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    total = None
    for key in ("cells", "n_cells", "total_cells", "total"):
        value = node.get(key)
        if isinstance(value, (int, float)):
            total = float(value)
            break
    nulls = node.get("nulls")
    if total is not None and isinstance(nulls, (int, float)):
        return max(total - float(nulls), 0.0)
    return None


def check_cube_exists(ev: dict, ctx: dict, role: str = "facies") -> Finding | None:
    """Свойство-куб роли ПРИСУТСТВУЕТ в сетке (данные: ``checks.properties.<role>``).

    * нет свидетельства ``grid_properties`` (или не задано имя куба) → ``unverified``;
    * свидетельство есть, куба в нём нет → ``failed`` (critical) с явным сообщением;
    * куб есть → ``passed``.
    """
    cube = _data_cube(ctx, role)
    meta = _role_meta(role)
    check_id, key = meta["exists"], meta["key"]
    title = f"{meta['title']}: наличие в сетке"
    if not cube:
        return _unverified(check_id, "critical", title,
                           f"в данных не задано имя свойства ({key})",
                           remediation=f"задайте {key} в config.yaml",
                           evidence={"role": role})
    names = grid_property_names(ev)
    if names is None:
        blocked = ev.get("blocked_wells")
        hint = ""
        if isinstance(blocked, dict) and blocked.get("count") is not None:
            hint = f"; блокировано скважин: {blocked.get('count')}"
        elif isinstance(blocked, (list, tuple)):
            hint = f"; блокировано скважин: {len(blocked)}"
        return _unverified(check_id, "critical", title,
                           f"пробник не отдал список свойств сетки (grid_properties){hint}",
                           remediation="включите пробник свойств сетки "
                                       "(get_all_properties) в свидетельства этапа",
                           evidence={"cube": cube, "role": role, "blocked_wells": blocked})
    inside = any(n.upper() == cube.upper() for n in names)
    message = (f"куб {cube} есть среди свойств сетки ({len(names)} свойств)"
               if inside else
               f"куба {cube} НЕТ среди свойств сетки: {', '.join(names[:12])}"
               + (" …" if len(names) > 12 else ""))
    return _mk(check_id, "critical", inside, title, message=message,
               remediation="проверьте стадию построения куба: операция могла пройти "
                           "формально, не создав свойство",
               evidence={"cube": cube, "role": role, "properties": names[:50]})


def check_cube_nonempty(ev: dict, ctx: dict, role: str = "facies") -> Finding | None:
    """Куб роли НЕПУСТ: доля ячеек с данными > 0 (свидетельство — статистика куба).

    * нет статистики по кубу → ``unverified`` (не «passed» и не «failed»);
    * есть: ``count > 0`` (для дискретного — ещё и классы непусты) → ``passed``;
    * ``count == 0``/пустые классы → ``failed``.
    """
    cube = _data_cube(ctx, role)
    meta = _role_meta(role)
    check_id, key = meta["nonempty"], meta["key"]
    title = f"{meta['title']}: непустота"
    if not cube:
        return _unverified(check_id, "major", title,
                           f"в данных не задано имя свойства ({key})",
                           remediation=f"задайте {key} в config.yaml",
                           evidence={"role": role})
    node = _stats_for(ev, cube)
    if node is None:
        return _unverified(check_id, "major", title,
                           f"нет статистики по кубу {cube} (property_stats)",
                           remediation="включите статистику свойств сетки в свидетельства",
                           evidence={"cube": cube, "role": role})
    count = _cell_count(node)
    fraction = node.get("nonempty_fraction")
    fraction = float(fraction) if isinstance(fraction, (int, float)) else None
    if count is None and fraction is None:
        return _unverified(check_id, "major", title,
                           f"в статистике по кубу {cube} нет числа непустых ячеек "
                           f"(count/non_null, либо cells − nulls, либо nonempty_fraction): "
                           f"{sorted(node)[:8]}",
                           evidence={"cube": cube, "role": role, "stats": node})
    # Критерий непустоты — НЕПУСТЫЕ ячейки (данные пробника). Список `classes`
    # НИКОГДА не решает вопрос: он может отсутствовать (классов больше предела
    # вывода — `classes_truncated`) или быть пустым в чужой записи; при count == 0
    # пробник классы не выводит вовсе (согласовано с petro, live 26.2).
    unique = node.get("unique_count")
    unique = float(unique) if isinstance(unique, (int, float)) else None
    if count is not None and count > 0 and unique == 0:
        return _unverified(check_id, "major", title,
                           f"противоречие свидетельства по кубу {cube}: непустых ячеек "
                           f"{count:g}, но unique_count=0",
                           evidence={"cube": cube, "role": role, "stats": node})
    # F-27: порог доли непустых ячеек. Задаётся ДАННЫМИ; нет порога — прежний критерий.
    limit = _min_fraction(ctx, role)
    # F-27: порог доли непустых ячеек из ДАННЫХ (checks.properties.<роль>.min_fraction).
    # Применяется ТОЛЬКО когда свидетельство само даёт долю (nonempty_fraction): иначе для
    # вывода доли пришлось бы догадываться о знаменателе, а F-19 требует не объявлять
    # непустой куб непроверенным. Нет порога или нет доли → прежний критерий (count > 0).
    limit = _min_fraction(ctx, role)
    if limit is not None and fraction is not None and fraction < limit:
        return _mk(check_id, "major", False, title,
                   message=(f"куб {cube}: доля непустых ячеек {fraction:.4%} ниже порога "
                            f"{limit:.2%}" + (f" (непустых {count:g})" if count is not None else "")),
                   remediation="проверьте распространение свойства: куб создан, но почти пуст",
                   evidence={"cube": cube, "role": role, "count": count,
                             "nonempty_fraction": fraction, "min_fraction": limit})
    nonempty = (count > 0) if count is not None else (fraction > 0)
    classes = node.get("classes")
    if not isinstance(classes, (list, tuple)):
        classes = node.get("facies_classes")
    classes_listed = isinstance(classes, (list, tuple)) and len(classes) > 0
    truncated = bool(node.get("classes_truncated"))
    extra = []
    if count is not None:
        extra.append(f"ячеек с данными {count:g}")
    else:
        extra.append(f"доля непустых {fraction:g}")
    if node.get("nulls") is not None:
        extra.append(f"пустых {node.get('nulls')}")
    if classes_listed:
        extra.append(f"классов {len(classes)}")
    elif truncated:
        extra.append(f"классы не перечислены (превышен предел вывода"
                     + (f", уникальных {unique:g}" if unique is not None else "") + ")")
    elif unique is not None:
        extra.append(f"уникальных {unique:g}")
    message = (f"куб {cube}: " + ", ".join(extra)) if nonempty else (
        f"куб {cube} пуст: " + ", ".join(extra))
    if not nonempty and isinstance(classes, (list, tuple)) and len(classes) == 0:
        message += " (список классов пуст)"
    evidence = {"cube": cube, "role": role, "count": count, "nulls": node.get("nulls"),
                "nonempty_fraction": fraction, "unique_count": unique,
                "classes_truncated": truncated,
                "classes": list(classes) if isinstance(classes, (list, tuple)) else None}
    if isinstance(classes, (list, tuple)) and len(classes) == 0 and nonempty:
        # чужой/битый разбор классов не должен делать куб «пустым» — решает count
        evidence["classes_note"] = ("пустой список классов при непустом кубе — "
                                    "противоречие данных, решение принято по count")
    return _mk(check_id, "major", nonempty, title, message=message,
               remediation="проверьте распространение свойства: операция могла создать "
                           "свойство без значений",
               evidence=evidence)


# -- G-DATA: данные и подготовка -------------------------------------------------
def check_markers_order(ev: dict, ctx: dict) -> Finding | None:
    """Стратиграфический порядок маркеров в скважинах (сверху вниз по MD)."""
    tops = ev.get("welltops") or {}
    order = [str(m) for m in (ctx.get("marker_order") or [])]
    if not tops or len(order) < 2:
        return None
    bad: list[str] = []
    evaluated = 0
    for well, marks in tops.items():
        by = {str(m).upper(): float(v) for m, v in marks}
        seq = [(m, by[m.upper()]) for m in order if m.upper() in by]
        for (m1, d1), (m2, d2) in zip(seq, seq[1:]):
            evaluated += 1
            if not d1 < d2:
                bad.append(f"{well}: {m1}@{d1:g} ≥ {m2}@{d2:g}")
    if not evaluated:
        return None
    return _mk("data.markers_order", "critical", not bad, "Порядок маркеров в скважинах",
               message="; ".join(bad[:5]) or f"проверено пар: {evaluated}",
               remediation="проверьте порядок маркеров (project YAML: markers.order) "
                           "в файле отбивок (inputs.welltop)",
               evidence={"evaluated": evaluated, "violations": len(bad)})


def check_reservoir_marker(ev: dict, ctx: dict) -> Finding | None:
    """Маркер резервуара присутствует хотя бы в одной скважине."""
    tops = ev.get("welltops") or {}
    marker = str(ctx.get("reservoir_top") or "").upper()
    if not tops or not marker:
        return None
    wells = [w for w, marks in tops.items()
             if any(str(m).upper().startswith(marker) for m, _ in marks)]
    return _mk("data.reservoir_marker", "critical", bool(wells),
               f"Маркер резервуара {marker} в отбивках",
               message=f"скважин с маркером: {len(wells)} из {len(tops)}",
               remediation="сверьте markers.reservoir_top в проектном YAML и файл отбивок "
                           "(inputs.welltop)",
               evidence={"with_marker": len(wells), "total": len(tops)})


def check_map_blank(ev: dict, ctx: dict) -> Finding | None:
    """Доля бланка (novalue) в структурных картах — не выше допуска."""
    maps = ev.get("maps") or []
    if not maps:
        return None
    limit = ctx.get("map_blank_max")
    if limit is None:
        return None
    limit = float(limit)
    bad = []
    for m in maps:
        total = int(m.get("total") or 0)
        if total <= 0:
            continue
        share = int(m.get("blank") or 0) / total
        if share > limit:
            bad.append(f"{Path(m['path']).name}: бланк {share:.0%} (>{limit:.0%})")
    return _mk("data.map_blank", "major", not bad, "Доля бланка структурной карты",
               message="; ".join(bad) or "в пределах допуска",
               remediation="проверьте novalue при импорте irap / выберите корректную карту",
               evidence={"maps": len(maps), "limit": limit})


def check_map_extent(ev: dict, ctx: dict) -> Finding | None:
    """Extent карты совпадает с боксом модели (допуск — метры)."""
    maps = ev.get("maps") or []
    box = ev.get("box") or {}
    if not maps or not box:
        return None
    tol = ctx.get("map_extent_tol_m")
    if tol is None:
        return None
    tol = float(tol)
    bad: list[str] = []
    checked = 0
    for m in maps:
        ext = m.get("extent") or {}
        if ext.get("x0") is None:
            continue
        checked += 1
        worst = max(
            abs(float(ext["x0"]) - float(box["min_x"])),
            abs(float(ext["y0"]) - float(box["min_y"])),
            abs(float(ext["x1"]) - (float(box["min_x"]) + float(box["length_x"]))),
            abs(float(ext["y1"]) - (float(box["min_y"]) + float(box["length_y"]))),
        )
        if worst > tol:
            bad.append(f"{Path(m['path']).name}: расхождение {worst:.0f} м > {tol:.0f}")
    if not checked:
        return None
    return _mk("data.map_extent", "major", not bad, "Extent карты vs бокс модели",
               message="; ".join(bad) or f"проверено карт: {checked}",
               remediation="сверьте бокс в functions.*.parameters с областью карты",
               evidence={"checked": checked, "tolerance_m": tol})


def check_trajectories(ev: dict, ctx: dict) -> Finding | None:
    """Траектории скважин подготовлены без пропусков."""
    tr = ev.get("trajectories")
    if tr is None:
        return None
    written = int(tr.get("written") or 0)
    skipped = int(tr.get("skipped") or 0)
    passed = written > 0 and skipped == 0
    return _mk("data.trajectories", "major", passed, "Подготовка траекторий скважин",
               message=f"траекторий: {written}, пропущено: {skipped}",
               remediation="проверьте инклинометрию/устья (prepare_trajectories)",
               evidence=tr)


# -- G-STRUCT: структурные поверхности --------------------------------------------
def _tie_devs(tie) -> list[float]:
    """Отклонения |наблюдение − модель| ТОЛЬКО по конечным парам (бланк = nan).

    Пустая/бланковая модель в точке скважины даёт nan-отклонение, которое ломает
    RMSE (сумма квадратов → nan) при ещё валидной медиане. Такие пары отбрасываем:
    «неизвестное ≠ ложь» — сравнение просто не проводится.
    """
    out: list[float] = []
    for obs, model in tie:
        try:
            dev = abs(float(obs) - float(model))
        except (TypeError, ValueError):
            continue
        if math.isfinite(dev):
            out.append(dev)
    return sorted(out)


def check_well_tie(ev: dict, ctx: dict) -> Finding | None:
    """Посадка структурной поверхности на скважины (медиана |наблюдение − модель|)."""
    tie = ev.get("well_tie")
    if not tie:
        return None
    devs = _tie_devs(tie)
    if not devs:
        return None
    med = devs[len(devs) // 2]
    limit = ctx.get("well_tie_median_m")
    if limit is None:
        return None
    limit = float(limit)
    rmse = (sum(d * d for d in devs) / len(devs)) ** 0.5
    return _mk("struct.well_tie", "critical", med <= limit,
               "Посадка структурной поверхности на скважины",
               message=f"медиана |ΔZ| = {med:.2f} м (допуск {limit} м), скважин {len(devs)}",
               remediation="уточните маркеры/тренд/параметры IDW",
               evidence={"median_m": med, "rmse_m": rmse, "limit_m": limit,
                         "count": len(devs)})


def check_well_tie_rmse(ev: dict, ctx: dict) -> Finding | None:
    """RMSE сходимости структурной поверхности с отбивками в точках скважин."""
    tie = ev.get("well_tie")
    if not tie:
        return None
    devs = _tie_devs(tie)
    if not devs:
        return None
    rmse = (sum(d * d for d in devs) / len(devs)) ** 0.5
    limit = ctx.get("well_tie_rmse_m")
    if limit is None:
        return None
    limit = float(limit)
    return _mk("struct.well_tie_rmse", "major", rmse <= limit,
               "RMSE сходимости поверхности с отбивками",
               message=f"RMSE = {rmse:.2f} м (допуск {limit} м), скважин {len(devs)}",
               remediation="проверьте посадку тренда на отбивки: residual IDW "
                           "(use_residual_idw) и согласованность сейсмики со скважинами",
               evidence={"rmse_m": rmse, "limit_m": limit, "count": len(devs)})


# -- G-GRID: геометрия сетки ---------------------------------------------------------
def check_grid_geometry(ev: dict, ctx: dict) -> Finding | None:
    """Геометрия 3D-сетки: непустая, без бланков novalue в Z (обёртка guard-а)."""
    geom = ev.get("grid")
    if not geom:
        return None
    from core.coordinator import check_grid_geometry as guard   # ленивый импорт (циклы)
    warn = guard(geom)
    return _mk("grid.geometry", "critical", warn is None, "Геометрия 3D-сетки",
               message=warn or (f"nx×ny×nz = {geom.get('nx')}×{geom.get('ny')}×{geom.get('nz')}, "
                                f"Z = {geom.get('min_z')}..{geom.get('max_z')}"),
               remediation="проверьте novalue карты и параметры grid_3d_create_by_horizons",
               evidence={k: geom.get(k) for k in ("nx", "ny", "nz", "min_z", "max_z")})


def check_grid_quality(ev: dict, ctx: dict) -> Finding | None:
    """Качество 3D-сетки: положительные размеры ячеек, соотношение сторон, число ячеек.

    В corner-point-сетке вырождение ячейки (≤6 граней) у эрозионных поверхностей и
    разломов — НОРМА (не дефект), поэтому проверяем ФИЗИЧНОСТЬ: размеры ячейки
    строго положительны, план/вертикаль не «сплющены» (``grid_max_aspect_ratio``),
    вытянутость в плане умеренна (``grid_max_xy_ratio``) и общее число ячеек не
    выходит за предел (``grid_max_cells``). Ожидаемые ``nx``/``ny`` (решение агента
    сетки) сверяются, если задан допуск ``grid_count_tol_cells``.

    Пороги — данные (``checks.*``); без порогов и без данных → not applicable.
    """
    geom = ev.get("grid")
    if not isinstance(geom, dict):
        return None
    try:
        nx, ny, nz = int(geom["nx"]), int(geom["ny"]), int(geom["nz"])
        span_x = float(geom["max_x"]) - float(geom["min_x"])
        span_y = float(geom["max_y"]) - float(geom["min_y"])
        span_z = float(geom["max_z"]) - float(geom["min_z"])
    except (KeyError, TypeError, ValueError):
        return None
    dx, dy, dz = span_x / nx, span_y / ny, span_z / nz
    cells = nx * ny * nz

    limits = {k: ctx.get(k) for k in ("grid_max_aspect_ratio", "grid_max_xy_ratio",
                                      "grid_max_cells", "grid_count_tol_cells")}
    if all(v is None for v in limits.values()):
        return None

    bad: list[str] = []
    if nx < 1 or ny < 1 or nz < 1 or dx <= 0 or dy <= 0 or dz <= 0:
        bad.append(f"неположительные размеры ячейки: dx={dx:g}, dy={dy:g}, dz={dz:g}")
    if limits["grid_max_aspect_ratio"] is not None and dx > 0 and dy > 0 and dz > 0:
        ar = max(dx, dy) / dz
        if ar > float(limits["grid_max_aspect_ratio"]):
            bad.append(f"max(dx,dy)/dz = {ar:.0f} > {float(limits['grid_max_aspect_ratio']):.0f}")
    if limits["grid_max_xy_ratio"] is not None and dx > 0 and dy > 0:
        xy = max(dx, dy) / min(dx, dy)
        if xy > float(limits["grid_max_xy_ratio"]):
            bad.append(f"dx/dy = {xy:.0f} > {float(limits['grid_max_xy_ratio']):.0f}")
    if limits["grid_max_cells"] is not None and cells > int(limits["grid_max_cells"]):
        bad.append(f"ячеек {cells} > {int(limits['grid_max_cells'])}")

    tol = limits["grid_count_tol_cells"]
    gp = ev.get("grid_policy") or {}
    exp_nx, exp_ny = gp.get("expected_nx"), gp.get("expected_ny")
    if tol is not None and exp_nx is not None and abs(nx - int(exp_nx)) > float(tol):
        bad.append(f"nx {nx} ≠ ожидаемых {int(exp_nx)} (±{float(tol):.0f})")
    if tol is not None and exp_ny is not None and abs(ny - int(exp_ny)) > float(tol):
        bad.append(f"ny {ny} ≠ ожидаемых {int(exp_ny)} (±{float(tol):.0f})")

    return _mk("grid.quality", "major", not bad, "Качество 3D-сетки",
               message="; ".join(bad) or
                       (f"ячеек {nx}×{ny}×{nz} = {cells}, размер "
                        f"{dx:.1f}×{dy:.1f}×{dz:.1f} м"),
               remediation="проверьте бокс/шаг сетки, число слоёв и novalue карты",
               evidence={"nx": nx, "ny": ny, "nz": nz, "cells": cells,
                         "dx": dx, "dy": dy, "dz": dz})


# -- G-PETRO: свойства -----------------------------------------------------------------
def check_poro_range(ev: dict, ctx: dict) -> Finding | None:
    """Среднее свойства-пористости в физическом диапазоне проекта (thresholds.poro)."""
    val = ev.get("poro_mean")
    rng = ctx.get("poro_range")
    if val is None or not rng or len(rng) != 2:
        return None
    lo, hi = float(rng[0]), float(rng[1])
    inside = lo <= float(val) <= hi
    name = _data_name(ctx, "poro", "свойство (checks.properties.poro)")
    return _mk("petro.poro_range", "major", inside, f"Диапазон свойства: {name}",
               message=f"{name} mean = {float(val):.3f} "
                       + (f"в [{lo}, {hi}]" if inside else f"вне [{lo}, {hi}]"),
               remediation="проверьте формулу/интерполяцию петрофизики",
               evidence={"value": float(val), "range": [lo, hi]})


def check_perm_range(ev: dict, ctx: dict) -> Finding | None:
    """Среднее свойства-проницаемости в диапазоне проекта (``thresholds.perm``)."""
    val = ev.get("perm_mean")
    rng = ctx.get("perm_range")
    if val is None or not rng or len(rng) != 2:
        return None
    lo, hi = float(rng[0]), float(rng[1])
    inside = lo <= float(val) <= hi
    name = _data_name(ctx, "perm", "свойство (checks.properties.perm)")
    return _mk("petro.perm_range", "major", inside, f"Диапазон свойства: {name}",
               message=f"{name} mean = {float(val):.4g} "
                       + (f"в [{lo}, {hi}]" if inside else f"вне [{lo}, {hi}]"),
               remediation="проверьте лог-преобразование/интерполяцию петрофизики",
               evidence={"value": float(val), "range": [lo, hi]})


def check_petro_policy(ev: dict, ctx: dict) -> Finding | None:
    """Политика петрофизики: кубы PORO/PERM заданы и метод из разрешённого набора.

    Значения — данные решения агента петрофизики (``ev['petro_policy']``), которое
    читает секцию ``petrophysics:`` проектного YAML. Без данных → not applicable
    («неизвестное != ложь»). Стадия выключена (нет кубов ни метода) — не применимо.
    """
    pol = ev.get("petro_policy")
    if not isinstance(pol, dict):
        return None
    cubes = pol.get("cubes") or []
    method = str(pol.get("method") or "").lower()
    allowed = [str(x).lower() for x in (ctx.get("petro_methods") or [])]
    if not cubes and not method:
        return None                       # стадия петрофизики отключена
    bad: list[str] = []
    if not cubes:
        bad.append("не заданы кубы петрофизики (petrophysics.cubes)")
    for c in cubes:
        if not (c.get("log") and c.get("cube")):
            bad.append(f"куб без log/cube: {c}")
    if allowed and method and method not in allowed:
        bad.append(f"метод «{method}» вне {allowed}")
    names = ", ".join(f"{c.get('log')}→{c.get('cube')}" for c in cubes)
    return _mk("petro.cubes", "major", not bad, "Политика петрофизики (кубы свойств)",
               message="; ".join(bad) or f"кубы [{names}], метод «{method or '—'}»",
               remediation="проверьте petrophysics.cubes/method в проектном YAML",
               evidence={"cubes": cubes, "method": method, "allowed": allowed})


# -- G-VOL: запасы ---------------------------------------------------------------------
def check_stoiip(ev: dict, ctx: dict) -> Finding | None:
    """STOIIP положителен и (если задан диапазон) в ожидаемых границах."""
    val = ev.get("stoiip")
    if val is None:
        return None
    v = float(val)
    rng = ctx.get("stoiip_range")
    inside = v > 0 and (not rng or (float(rng[0]) <= v <= float(rng[1])))
    metric = str(ctx.get("metric_name") or "метрика проекта (ensemble.metric)")
    return _mk("vol.stoiip", "critical", inside, f"Запасы: {metric}",
               message=f"{metric} = {v:.4g}" + ("" if inside
                                                else " — вне ожидаемого диапазона"),
               remediation="проверьте волюметрию: контакты, свойства, сетка",
               evidence={"value": v, "range": rng})


# -- G-MAPS: карты для интерфейса --------------------------------------------------
def check_maps_files(ev: dict, ctx: dict) -> Finding | None:
    """Ожидаемые карты (`checks.map_files`) существуют как PNG после прогона тНава."""
    expected = [str(x) for x in (ctx.get("map_files") or []) if str(x).strip()]
    if not expected:
        return None
    actual = {str(m.get("name")) for m in (ev.get("map_files") or [])}
    missing = [name for name in expected if name not in actual]
    return _mk("maps.files", "major", not missing, "Карты прогона (PNG с изолиниями)",
               message=("нет файлов: " + ", ".join(missing)) if missing
                       else f"карт собрано: {len(actual)} из {len(expected)}",
               remediation="проверьте стадию «10. Экспорт карт» (create_screenshot) "
                           "или фолбэк domain/map_render.py",
               evidence={"expected": expected, "actual": sorted(actual)})


# -- G-FACIES: фации (SIS) ---------------------------------------------------------
def check_facies_policy(ev: dict, ctx: dict) -> Finding | None:
    """Политика фаций: число классов > 0 и метод из разрешённого набора (данные).

    Значения — из решения агента фаций (`agents/facies_policy.py`, свидетельство
    `ev["facies_policy"]`); допустимые методы — данные `checks.facies_methods`.
    """
    pol = ev.get("facies_policy")
    if not isinstance(pol, dict):
        return None
    n_facies = int(pol.get("n_facies") or 0)
    method = str(pol.get("method") or "").lower()
    if not n_facies and not method:
        return None
    allowed = [str(x).lower() for x in (ctx.get("facies_methods") or [])]
    ok = n_facies > 0 and bool(method) and (not allowed or method in allowed)
    message = (f"метод «{method or '—'}», классов {n_facies}" if ok else
               f"метод «{method or 'не задан'}» (допустимо: "
               f"{', '.join(allowed) or '—'}), классов {n_facies}")
    return _mk("facies.policy", "major", ok, "Политика фаций (SIS)", message=message,
               remediation="проверьте geostat.n_facies и geostat.facies_method "
                           "в проектном YAML",
               evidence={"n_facies": n_facies, "method": method, "allowed": allowed})


def check_facies_structure(ev: dict, ctx: dict) -> Finding | None:
    """Согласованность распространения фаций со структурой (вариограмма vs сетка).

    Фации (SIS) распространяются на ТОЙ ЖЕ структурной corner-point-сетке, поэтому
    корректный результат требует: (1) число классов ≥ ``facies_min_classes``,
    (2) радиус корреляции ``hole_range_m`` ≥ шага сетки (иначе фации = шум сетки),
    (3) ``nugget ∈ [0, 1]``, (4) вертикальная анизотропия ∈ (0, 1] (уважает
    слоистость — вертикальная корреляция короче горизонтальной). Значения — данные
    решений агентов фаций и сетки; без данных → not applicable («неизвестное != ложь»).
    """
    pol = ev.get("facies_policy")
    if not isinstance(pol, dict):
        return None
    n = int(pol.get("n_facies") or 0)
    var = pol.get("variogram") or {}
    rng = float(var.get("range_m") or 0.0)
    nug = float(var.get("nugget") or 0.0)
    ani = float(var.get("anisotropy") or 0.0)
    if n <= 0 and not any((rng, nug, ani)):
        return None                       # стадия фаций выключена — не применимо
    bad: list[str] = []
    min_cls = ctx.get("facies_min_classes")
    if min_cls is not None and n < int(min_cls):
        bad.append(f"классов фаций {n} < {int(min_cls)}")
    if any((rng, nug, ani)):
        if not 0.0 <= nug <= 1.0:
            bad.append(f"nugget {nug:g} вне [0, 1]")
        if ani and not 0.0 < ani <= 1.0:
            bad.append(f"анизотропия {ani:g} вне (0, 1]")
    step = (ev.get("grid_policy") or {}).get("step") or {}
    cell = max(float(step.get("step_x") or 0.0), float(step.get("step_y") or 0.0))
    if rng > 0 and cell > 0 and rng < cell:
        bad.append(f"радиус корреляции {rng:g} м < шага сетки {cell:g} м")
    msg = ("; ".join(bad) or
           (f"классов {n}, range={rng:g} м, nugget={nug:g}, анизотропия={ani:g}"))
    return _mk("facies.structure", "major", not bad,
               "Согласованность фаций со структурой", message=msg,
               remediation="проверьте geostat.hole_range_m/anisotropy/nugget "
                           "и шаг сетки (фации наследуют структурную сетку)",
               evidence={"n_facies": n, "range_m": rng, "nugget": nug,
                         "anisotropy": ani, "cell_m": cell})


def check_metric_exists(ev: dict, ctx: dict) -> Finding | None:
    """Свойство-МЕТРИКА проекта (``ensemble.metric``) присутствует в сетке.

    Тонкая обёртка над общей проверкой роли ``metric`` (имя — ИЗ ДАННЫХ).
    """
    return check_cube_exists(ev, ctx, "metric")


def _role_check(func, role: str):
    """Обёртка проверки роли: роль — СХЕМА, имя куба приходит из данных."""
    def _wrapped(ev: dict, ctx: dict) -> Finding | None:
        return func(ev, ctx, role)
    _wrapped.__name__ = f"{func.__name__}_{role}"
    return _wrapped


BUILTIN_CHECKS: list[CheckSpec] = [
    CheckSpec("data.markers_order", "G-DATA", "critical",
              "Порядок маркеров в скважинах", check_markers_order,
              "проверьте порядок маркеров (project YAML: markers.order) в файле "
              "отбивок (inputs.welltop)"),
    CheckSpec("data.reservoir_marker", "G-DATA", "critical",
              "Маркер резервуара в отбивках", check_reservoir_marker,
              "сверьте markers.reservoir_top и файл отбивок (inputs.welltop)"),
    CheckSpec("data.map_blank", "G-DATA", "major",
              "Доля бланка структурной карты", check_map_blank,
              "проверьте novalue при импорте irap"),
    CheckSpec("data.map_extent", "G-DATA", "major",
              "Extent карты vs бокс модели", check_map_extent,
              "сверьте бокс модели с областью карты"),
    CheckSpec("data.trajectories", "G-DATA", "major",
              "Подготовка траекторий скважин", check_trajectories,
              "проверьте инклинометрию/устья"),
    CheckSpec("struct.well_tie", "G-STRUCT", "critical",
              "Посадка поверхности на скважины", check_well_tie,
              "уточните маркеры/тренд/IDW", runtime=True),
    CheckSpec("struct.well_tie_rmse", "G-STRUCT", "major",
              "RMSE сходимости поверхности с отбивками", check_well_tie_rmse,
              "включите residual IDW (use_residual_idw) или сверьте тренд с отбивками",
              runtime=True),
    CheckSpec("grid.geometry", "G-GRID", "critical",
              "Геометрия 3D-сетки", check_grid_geometry,
              "проверьте novalue и параметры сетки", runtime=True),
    CheckSpec("grid.quality", "G-GRID", "major",
              "Качество 3D-сетки (размеры/соотношение сторон/число ячеек)",
              check_grid_quality,
              "проверьте бокс/шаг сетки, число слоёв и novalue карты", runtime=True),
    CheckSpec("petro.poro_range", "G-PETRO", "major",
              "Диапазон свойства (checks.properties.poro)", check_poro_range,
              "проверьте формулу петрофизики", runtime=True),
    CheckSpec("petro.perm_range", "G-PETRO", "major",
              "Диапазон свойства (checks.properties.perm)", check_perm_range,
              "проверьте лог-преобразование/интерполяцию петрофизики", runtime=True),
    CheckSpec("petro.cubes", "G-PETRO", "major",
              "Политика петрофизики (кубы свойств)", check_petro_policy,
              "проверьте petrophysics.cubes/method в проектном YAML"),
    CheckSpec("vol.stoiip", "G-VOL", "critical",
              "Запасы (метрика проекта: ensemble.metric)", check_stoiip,
              "проверьте волюметрию", runtime=True),
    CheckSpec("maps.files", "G-MAPS", "major",
              "Карты прогона (PNG с изолиниями)", check_maps_files,
              "стадия «10. Экспорт карт»: create_screenshot или фолбэк map_render",
              runtime=True),
    CheckSpec("facies.policy", "G-FACIES", "major",
              "Политика фаций (SIS)", check_facies_policy,
              "проверьте geostat.n_facies/facies_method в проектном YAML"),
    CheckSpec("facies.structure", "G-FACIES", "major",
              "Согласованность фаций со структурой (вариограмма vs сетка)",
              check_facies_structure,
              "проверьте geostat.hole_range_m/anisotropy/nugget и шаг сетки"),
]

# -- F-19: проверки РЕЗУЛЬТАТА («объект существует и непуст») ------------------------
# Регистрируются в реестре ИЗ ДАННЫХ (`CheckRegistry.from_config`) — там доступен ctx
# с именами кубов (`checks.properties`) и метрикой (`ensemble.metric`). Минимальный
# `CheckRegistry()` остаётся набором кода без данных (обратная совместимость).
RESULT_CHECKS: list[CheckSpec] = [
    CheckSpec("facies.cube_exists", "G-FACIES", "critical",
              "Куб фаций: наличие в сетке (checks.properties.facies)",
              _role_check(check_cube_exists, "facies"),
              "проверьте стадию построения куба фаций: операция могла пройти формально",
              runtime=True),
    CheckSpec("facies.cube_nonempty", "G-FACIES", "major",
              "Куб фаций: непустота", _role_check(check_cube_nonempty, "facies"),
              "проверьте распространение фаций (свойство без значений)", runtime=True),
    CheckSpec("cube.poro_exists", "G-PETRO", "critical",
              "Куб пористости: наличие в сетке (checks.properties.poro)",
              _role_check(check_cube_exists, "poro"),
              "проверьте стадию интерполяции петрофизики", runtime=True),
    CheckSpec("cube.poro_nonempty", "G-PETRO", "major",
              "Куб пористости: непустота", _role_check(check_cube_nonempty, "poro"),
              "проверьте распространение пористости", runtime=True),
    CheckSpec("cube.perm_exists", "G-PETRO", "critical",
              "Куб проницаемости: наличие в сетке (checks.properties.perm)",
              _role_check(check_cube_exists, "perm"),
              "проверьте стадию интерполяции петрофизики", runtime=True),
    CheckSpec("cube.perm_nonempty", "G-PETRO", "major",
              "Куб проницаемости: непустота", _role_check(check_cube_nonempty, "perm"),
              "проверьте распространение проницаемости", runtime=True),
    CheckSpec("cube.metric_exists", "G-VOL", "critical",
              "Свойство-метрика проекта: наличие в сетке", check_metric_exists,
              "проверьте стадию волюметрии", runtime=True),
    # Непустота метрики — critical: у G-VOL это ЕДИНСТВЕННЫЙ результат, и «свойство
    # есть, но пусто/не читается» обязано валить гейт, а не оставаться major-находкой.
    CheckSpec("cube.metric_nonempty", "G-VOL", "critical",
              "Свойство-метрика проекта: непустота",
              _role_check(check_cube_nonempty, "metric"),
              "проверьте волюметрию: свойство-метрика создано без значений",
              runtime=True),
]


def result_checks() -> list[CheckSpec]:
    """Проверки результата F-19 (объект существует и непуст) — данные/ctx обязателен."""
    return list(RESULT_CHECKS)
