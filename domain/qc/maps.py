"""Карты свойств/фаций: нативная выгрузка тНава → PNG (console-safe путь, E9).

Цепочка (подтверждена пробой на живой лицензии 26.2, `tools/probe_maps.py`):

    1) воркфлоу тНава: `map_2d_create_by_grid_property` создаёт объект 2D-карты
       (Map2d) из куба свойств сетки — карта видна в дереве проекта;
    2) воркфлоу тНава: `map_2d_export_ascii_format` / `map_2d_export_cps_format`
       выгружает карту файлом в каталог проекта (каталог создаётся шагом);
    3) локально: `domain.map_render` читает файл (`domain.irap` для «полного irap»
       или CPS-разбор) и рисует PNG в `runs/<id>/maps/`.

Здесь — шаг 3 и разрешение имён файлов; шаги 1–2 живут в проектном YAML
(триады шаблон+правило+блок этапа). Имена объектов/карт/путей — ДАННЫЕ: они
берутся из шагов проектного графа, а имена PNG — из `checks.map_files`.

Правило 6: карта без источника не подменяется пустышкой — она попадает в
`missing` с причиной; ошибки чтения файлов копятся в `errors`, а не глушатся.
"""
from __future__ import annotations

from pathlib import Path

from domain.map_render import MIN_RENDER_POINTS, count_points, render_map

_EXPORT_PREFIX = "map_2d_export"
_FORMATS = {"cps_format": "cps", "ascii_format": "ascii"}


def project_graph(cfg) -> dict:
    """Проектный граф (ДАННЫЕ `project.graph_dir` + `project.default_field`)."""
    if cfg is None:
        return {}
    import yaml
    graph_dir = cfg.path("project.graph_dir", "ontology_project")
    field = str(cfg.get("project.default_field", "") or "")
    cands = [graph_dir / f"{field}.yaml", graph_dir / f"{field}.yml"]
    cands += sorted([*graph_dir.glob("*.y*ml")])
    for cand in cands:
        if not cand.is_file():
            continue
        try:
            data = yaml.safe_load(cand.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(data, dict) and data:
            if not field or str(data.get("field", "")) == field:
                return data
    return {}


def expected(cfg) -> list[str]:
    """Ожидаемые карты (ДАННЫЕ `checks.map_files`)."""
    if cfg is None:
        return []
    return [str(x) for x in (cfg.get("checks.map_files") or []) if str(x)]


def map_sources(cfg) -> dict:
    """Фолбэк-источники (ДАННЫЕ `checks.map_sources`)."""
    if cfg is None:
        return {}
    value = cfg.get("checks.map_sources") or {}
    return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}


def export_steps(project: dict) -> list[dict]:
    """Шаги выгрузки карт из проектного графа: имя карты, файл, формат.

    Имя карты берётся из роли объекта (`map_2d`) или из подстановки `__MAP__`;
    файл — из `parameters.file_name` (или подстановки `file_name`); формат — из
    имени функции тНава (схема, а не домен).
    """
    out: list[dict] = []
    for stage in (project or {}).get("pipeline") or []:
        for step in (stage or {}).get("steps") or []:
            fn = str((step or {}).get("function") or "")
            if not fn.startswith(_EXPORT_PREFIX):
                continue
            name = ""
            for role, obj in (step.get("objects") or {}).items():
                if isinstance(obj, dict) and obj.get("obj_name"):
                    name = str(obj["obj_name"])
                    break
            file_name = str((step.get("parameters") or {}).get("file_name") or "")
            for old, new in (step.get("replace") or {}).items():
                if "__MAP__" in str(old):
                    name = str(new)
                if "file_name" in str(old):
                    file_name = str(new)
            fmt = "unknown"
            for suffix, value in _FORMATS.items():
                if fn.endswith(suffix):
                    fmt = value
            out.append({"function": fn, "name": name, "file_name": file_name,
                        "format": fmt})
    return out


def native_candidates(project: dict) -> dict:
    """«Имя карты → упорядоченный список файлов выгрузки» из проектного графа.

    Одну и ту же карту могут выгружать НЕСКОЛЬКО шагов (например, CPS из этапа
    структур и ASCII из этапа карт). Формат ASCII («полный irap») ставится первым:
    он канонический для `domain/map_render`, но если файла нет — берётся следующий
    существующий (порядок объявления шагов сохраняется).
    """
    ascii_files: dict[str, list[str]] = {}
    other_files: dict[str, list[str]] = {}
    for step in export_steps(project):
        name, file_name = str(step.get("name") or ""), str(step.get("file_name") or "")
        if not name or not file_name:
            continue
        bucket = ascii_files if step.get("format") == "ascii" else other_files
        bucket.setdefault(name, [])
        if file_name not in bucket[name]:
            bucket[name].append(file_name)
    return {name: ascii_files.get(name, []) + other_files.get(name, [])
            for name in {*ascii_files, *other_files}}


def native_sources(project: dict) -> dict:
    """Маршрут «имя карты → предпочтительный файл выгрузки» (первый существующий)."""
    return {name: files[0] for name, files in native_candidates(project).items() if files}


def render_native(run_dir: Path, project: dict, *, novalue: float | None = None,
                  blank_abs: float | None = None, names: list[str] | None = None
                  ) -> tuple[list[str], list[str], list[str], list[str]]:
    """Нарисовать PNG по нативным выгрузкам.

    Возвращает ``(готовые, отсутствующие, пустые, ошибки)``. «Пустая» карта —
    отдельная категория (реальный случай F-18: выгрузка карты из тНава содержит
    ТОЛЬКО бланковое значение, рисовать нечего) — это не ошибка чтения файла,
    поэтому причина формулируется точно: сколько непустых ячеек найдено.
    """
    run_dir = Path(run_dir)
    maps_dir = run_dir / "maps"
    candidates = native_candidates(project)
    want = [str(n) for n in (names if names is not None else sorted(candidates))]
    done: list[str] = []
    missing: list[str] = []
    empty: list[str] = []
    errors: list[str] = []
    for name in want:
        files = candidates.get(name) or []
        if not files:
            missing.append(f"{name}: нет шага выгрузки в проектных данных")
            continue
        rel = next((f for f in files if (run_dir / f).is_file()), "")
        if not rel:
            missing.append(f"{name}: файлы выгрузки не найдены ({', '.join(files)})")
            continue
        points = count_points(run_dir / rel, novalue=novalue, blank_abs=blank_abs)
        if points == 0:
            empty.append(f"{name}: карта пустая — 0 непустых ячеек в {rel} "
                         f"(все значения = бланк)")
            continue
        if points < MIN_RENDER_POINTS:
            empty.append(f"{name}: мало данных для изолиний — {points} непустых "
                         f"ячеек в {rel} (нужно >= {MIN_RENDER_POINTS})")
            continue
        out = render_map(run_dir / rel, maps_dir / f"{name}.png", novalue=novalue,
                         blank_abs=blank_abs, title=name)
        if out is None:
            errors.append(f"{name}: файл {rel} не разобран/не отрисован")
        else:
            done.append(name)
    return done, missing, empty, errors


def ensure_maps(run_dir: Path, cfg, project: dict | None = None, *,
                names: list[str] | None = None) -> list[str]:
    """Контур карт, совместимый с `StageRunner._ensure_maps` → список имён PNG.

    Возвращаются ВСЕ карты, которые есть в `runs/<id>/maps/` после прохода
    (нарисованные сейчас и уже существующие) — это и есть критерий полноты.
    Подробный отчёт (что нативно, что фолбэком, что отсутствует и почему) —
    :func:`ensure_maps_report`.
    """
    return ensure_maps_report(run_dir, cfg, project, names=names)["present"]


def ensure_maps_report(run_dir: Path, cfg, project: dict | None = None, *,
                       names: list[str] | None = None) -> dict:
    """Полный контур карт: нативные выгрузки, затем фолбэк по `checks.map_sources`.

    Возвращает отчёт: `{produced, present, native, fallback, missing, errors,
    sources, expected}` — годится и для лога, и для свидетельства гейта.
    """
    run_dir = Path(run_dir)
    project = project if project is not None else project_graph(cfg)
    want = [str(n) for n in (names if names is not None else expected(cfg))]
    novalue = novalue_from_project(project)
    blank_abs = cfg.get("checks.blank_abs") if cfg is not None else None

    native_done: list[str] = []
    missing: list[str] = []
    empty: list[str] = []
    errors: list[str] = []
    if project:
        # Сначала ВСЕ объявленные шаги выгрузки (набор карт может быть шире
        # ожидаемого списка PNG), затем — фолбэк только по ожидаемым именам.
        native_done, missing, empty, errors = render_native(
            run_dir, project, novalue=novalue, blank_abs=blank_abs, names=None)

    fallback_done: list[str] = []
    sources = map_sources(cfg)
    maps_dir = run_dir / "maps"
    for name in want:
        if name in native_done or (maps_dir / f"{name}.png").is_file():
            continue
        rel = sources.get(name) or ""
        if not rel:
            if not any(m.startswith(f"{name}:") for m in missing):
                missing.append(f"{name}: нет ни нативной выгрузки, ни источника")
            continue
        if not (run_dir / rel).is_file():
            if not any(m.startswith(f"{name}:") for m in missing):
                missing.append(f"{name}: файл-источник не найден ({rel})")
            continue
        points = count_points(run_dir / rel, novalue=novalue, blank_abs=blank_abs)
        if points < MIN_RENDER_POINTS:
            empty.append(f"{name}: источник {rel} без данных для изолиний "
                         f"({points} непустых ячеек)")
            continue
        out = render_map(run_dir / rel, maps_dir / f"{name}.png", novalue=novalue,
                         blank_abs=blank_abs, title=name)
        if out is None:
            errors.append(f"{name}: источник {rel} не разобран/не отрисован")
        else:
            fallback_done.append(name)

    produced = sorted({*native_done, *fallback_done})
    present = (sorted(p.stem for p in maps_dir.glob("*.png"))
               if maps_dir.is_dir() else [])
    return {"produced": produced, "present": present,
            "native": sorted(native_done), "fallback": sorted(fallback_done),
            "missing": sorted(missing), "empty": sorted(empty),
            "errors": sorted(errors),
            "sources": native_sources(project), "expected": want}


def novalue_from_project(project: dict) -> float | None:
    """Бланковое значение карт из параметров шагов проектного графа (данные)."""
    for stage in (project or {}).get("pipeline") or []:
        for step in (stage or {}).get("steps") or []:
            params = (step or {}).get("parameters") or {}
            if "novalue" in params:
                try:
                    return float(params["novalue"])
                except (TypeError, ValueError):
                    continue
    return None
