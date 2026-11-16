"""Сбор свидетельств этапа из данных прогона (без тНава).

`build_static()` собирает то, что доступно ЛОКАЛЬНО: отбивки скважин, порядок
маркеров, статистику структурных карт (доля бланка novalue, extent), бокс
модели, счётчики траекторий, пороги проекта. Runtime-свидетельства (сетка,
well-tie, средние свойств, запасы) добавляет StageRunner после прогонов тНава
через единый файловый канал «код → tmp → разбор».

`check_context()` — пороги проверок (из проекта и секции `checks:` конфига).
"""
from __future__ import annotations

from pathlib import Path

from domain.irap import irap_stats
from domain.trajectories import read_wellheads
from domain.welltops import read_welltops


def _project_box(project: dict) -> dict | None:
    """Бокс модели (min_x/min_y/length_x/length_y) из functions или pipeline."""
    funcs = project.get("functions") or {}
    keys = ("min_x", "min_y", "length_x", "length_y")
    for fn in ("horizon_interpolate_by_marker_idw", "grid_3d_create_by_horizons"):
        params = (funcs.get(fn) or {}).get("parameters") or {}
        if all(k in params for k in keys):
            return {k: float(params[k]) for k in keys}
    for stage in project.get("pipeline") or []:
        for step in (stage.get("steps") if isinstance(stage, dict) else None) or []:
            params = (step or {}).get("parameters") or {}
            if all(k in params for k in keys):
                return {k: float(params[k]) for k in keys}
    return None


def _project_novalue(project: dict) -> float | None:
    """Бланковое значение карт из параметров шагов pipeline (данные проекта)."""
    for stage in project.get("pipeline") or []:
        for step in (stage.get("steps") if isinstance(stage, dict) else None) or []:
            params = (step or {}).get("parameters") or {}
            if "novalue" in params:
                try:
                    return float(params["novalue"])
                except (TypeError, ValueError):
                    continue
    return None


def build_static(project: dict, run_dir: Path, *, staging: dict | None = None,
                 warnings: list[str] | None = None, cfg=None) -> dict:
    """Свидетельства, доступные без прогона тНава (данные + подготовка)."""
    run_dir = Path(run_dir)
    inputs = project.get("inputs") or {}
    ev: dict = {"warnings": list(warnings or [])}

    if inputs.get("welltop"):
        tops = read_welltops(run_dir / str(inputs["welltop"]))
        if tops:
            ev["welltops"] = tops

    # Альтитуды устьев (KB): нужны агентам насыщения/петрофизики, чтобы переводить
    # MD→отметку без двойного преобразования. Путь — ДАННЫЕ (`inputs.wellhead`);
    # нет ключа/данных → свидетельства нет (правило 6, не подменяем значением).
    wellhead_rel = inputs.get("wellhead")
    if wellhead_rel:
        heads = read_wellheads(run_dir / str(wellhead_rel))
        if heads:
            ev["wellheads"] = {str(k): {"kb": v.get("kb"), "x": v.get("x"),
                                        "y": v.get("y")}
                               for k, v in heads.items()}

    novalue = _project_novalue(project)
    blank_abs = cfg.get("checks.blank_abs") if cfg is not None else None
    maps: list[dict] = []
    for key in ("surface", "surface_std"):
        rel = inputs.get(key)
        if not rel:
            continue
        stats = irap_stats(run_dir / str(rel), novalue, blank_abs)
        if stats:
            maps.append(stats)
    if maps:
        ev["maps"] = maps

    box = _project_box(project)
    if box:
        ev["box"] = box

    if staging:
        written = staging.get("trajectories") or []
        skipped = staging.get("trajectories_skipped") or []
        ev["trajectories"] = {"written": len(written), "skipped": len(skipped)}

    thresholds = project.get("thresholds")
    if thresholds:
        ev["thresholds"] = thresholds
    return ev


def check_context(project: dict, cfg=None) -> dict:
    """Контекст проверок: пороги из проекта и секции `checks:` конфигурации."""
    markers = project.get("markers") or {}
    ctx: dict = {
        "marker_order": list(markers.get("order") or []),
        "reservoir_top": markers.get("reservoir_top") or "",
        "poro_range": (project.get("thresholds") or {}).get("poro"),
        "perm_range": (project.get("thresholds") or {}).get("perm"),
    }
    if cfg is not None:
        for key in ("map_blank_max", "map_extent_tol_m", "well_tie_median_m",
                    "well_tie_rmse_m", "grid_max_aspect_ratio", "grid_max_xy_ratio",
                    "grid_max_cells", "facies_min_classes"):
            val = cfg.get(f"checks.{key}")
            if val is not None:
                ctx[key] = float(val)
        rng = cfg.get("checks.stoiip_range")
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            ctx["stoiip_range"] = [float(rng[0]), float(rng[1])]
        ctx["map_files"] = [str(x) for x in (cfg.get("checks.map_files") or [])]
        ctx["map_sources"] = dict(cfg.get("checks.map_sources") or {})
        kinds = cfg.get("checks.map_kinds")
        if isinstance(kinds, dict):
            ctx["map_kinds"] = {str(k): [str(x) for x in (v or [])]
                                for k, v in kinds.items()}
        ctx["facies_methods"] = [str(x) for x in (cfg.get("checks.facies_methods") or [])]
        ctx["petro_methods"] = [str(x) for x in (cfg.get("checks.petro_methods") or [])]
        ctx["foreign_tokens"] = [str(t) for t in (cfg.get("workflow.foreign_tokens") or [])]
    return ctx
