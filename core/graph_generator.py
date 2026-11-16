"""B8 — генератор ПРОЕКТНОГО ГРАФА (черновик) по данным и шаблону.

Собирает `ontology_project/<поле>.yaml`/`.json` из:
  * ДАННЫХ набора (`core/datasets.py`) — авто-`inputs` (wellhead/welltop/surface/logs…);
  * структурной карты (`domain/irap.py`) — extent/бокс/шаг/доля бланка → `structural:`;
  * отбивок (`domain/welltops.py`) — КАНДИДАТЫ маркеров (выбор кровли — семантика);
  * ШАБЛОНА существующего графа — стадии/вариации/функции клонируются как есть;
  * семантики — помечается `__todo__` (кровля, горизонт, контакты, PVT/SCAL, пороги).

В КОДЕ НЕТ доменных значений: ключи входов и шаблон — ДАННЫЕ. Результат принимается
`main.py plan|run` без правок кода (человек/LLM дописывает только `__todo__`).
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from core.datasets import inventory

TODO = "__todo__"

# «ключ входа → тип данных» — СХЕМА (не значения поля).
_KEY_KINDS: tuple[tuple[str, str], ...] = (
    ("wellhead", "wellheads"), ("усть", "wellheads"),
    ("welltop", "welltops"), ("отбив", "welltops"),
    ("surface", "surfaces"), ("fault", "surfaces"), ("map", "surfaces"),
    ("struct", "surfaces"), ("depth", "surfaces"),
    ("log", "logs"), ("rigis", "logs"), ("las", "logs"),
    ("seismic", "seismic"), ("seism", "seismic"),
    ("core", "core"), ("керн", "core"),
    ("deck", "decks"), ("history", "production_history"),
)


def _rel(path: Path, root: Path) -> str:
    """Относительный путь (posix-разделители) или абсолютный, если вне root."""
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _kind_for_key(key: str) -> str | None:
    low = str(key).lower()
    return next((kind for token, kind in _KEY_KINDS if token in low), None)


def _best_match(files: list[str], want: str) -> str:
    """Файл, наиболее похожий на `want` (по токенам имени)."""
    if not files:
        return ""
    tokens = [t for t in Path(str(want)).stem.lower().replace("_", " ").split() if len(t) > 2]
    ranked = sorted(files, key=lambda f: -sum(t in Path(f).name.lower() for t in tokens))
    return ranked[0]


def _ontology_roles() -> dict:
    """Роли и маски распознавания входов — ИЗ ОНТОЛОГИИ (данные, не код).

    `ontology/input_recognition_rules.yaml` описывает роли (заголовки скважин, отбивки,
    кровля/подошва, инклинометрия, мнемоники, ГИС) масками имён и форматами. Это делает
    распознавание универсальным: новое поле с другим форматом (иные имена заголовков,
    отбивок, структурных поверхностей, инклинометрии) не требует правок кода.
    """
    path = Path(__file__).resolve().parents[1] / "ontology" / "input_recognition_rules.yaml"
    if not path.is_file():
        return {}
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:                                   # noqa: BLE001 — данные опциональны
        return {}
    return {str(k): dict(v or {}) for k, v in (data.get("roles") or {}).items()}


def _detect_by_ontology(data_root: Path) -> tuple[dict, list[str]]:
    """Входы по правилам онтологии: роль → файл по маске. Нет обязательной роли → TODO."""
    import re as _re
    roles = _ontology_roles()
    if not roles:
        return {}, []
    inv = inventory(Path(data_root))
    all_files = [str(f) for files in inv.values() for f in files]
    out: dict = {}
    todo: list[str] = []
    ordered = sorted(roles.items(), key=lambda kv: int((kv[1] or {}).get("priority", 100) or 100))
    for role, spec in ordered:
        spec = spec or {}
        pats = [str(p) for p in (spec.get("patterns") or [])]
        hit = ""
        for f in all_files:
            if any(_re.search(p, Path(f).name, _re.IGNORECASE) or
                   _re.search(p, f, _re.IGNORECASE) for p in pats):
                hit = f
                break
        if hit:
            # РОЛЬ ФАЙЛОВАЯ: если маска совпала с КАТАЛОГОМ, раскрываем его по `file_masks`
            # (проверено на реальном поле: в inputs попадали КАТАЛОГИ вместо файлов
            # `*.las`). Правила раскрытия — ДАННЫЕ онтологии.
            hit_path = Path(data_root) / hit
            if hit_path.is_dir() and (spec.get("file_masks") or spec.get("prefer") == "files"):
                import re as _re2
                masks = [str(m) for m in (spec.get("file_masks") or [])] or ["*"]
                inner = []
                for mask in masks:
                    inner += [str(p) for p in sorted(hit_path.rglob(mask)) if p.is_file()]
                inner = [str(Path(p).relative_to(Path(data_root))).replace("\\", "/") for p in inner]
                if inner:
                    hit = inner[0]
            out[role] = hit
            # Внутренний ключ конвейера — из ДАННЫХ онтологии (`internal_key`): роли
            # `well_tops`/`surface_top` питают ключи `welltop`/`surface`, которые
            # использует построение графа (иначе структура и маркеры не подхватываются).
            internal = str(spec.get("internal_key") or "")
            if internal:
                out[internal] = hit
        elif spec.get("required"):
            todo.append(f"inputs.{role}")
    return out, todo


def detect_inputs(data_root: Path, template_inputs: dict) -> tuple[dict, list[str]]:
    """Авто-`inputs`: (1) тот же относительный путь; (2) по типу данных; иначе — ПО ПРАВИЛАМ
    ОНТОЛОГИИ (роль → маска имени); нет обязательной роли → TODO (правило 6: нет данных ≠
    «построим как-нибудь»)."""
    data_root = Path(data_root)
    if not template_inputs:
        # Новое поле без ручного проектного графа: роли берём из онтологии.
        return _detect_by_ontology(data_root)
    inv = inventory(data_root)
    out: dict = {}
    todo: list[str] = []
    for key, tval in (template_inputs or {}).items():
        tval = str(tval or "")
        if tval and (data_root / tval).exists():
            out[key] = tval
            continue
        files = inv.get(_kind_for_key(key) or "", [])
        if files:
            out[key] = _rel(_best_match(files, tval or key), data_root)
            continue
        out[key] = tval
        todo.append(f"inputs.{key}")
    return out, todo


def detect_structural(surface_path: Path, *, blank_abs: float = 1.0e6) -> dict:
    """Extent/бокс/шаг/доля бланка из структурной карты (irap). Без карты → {}."""
    from domain.irap import read_irap
    grid = read_irap(Path(surface_path)) if surface_path else None
    if grid is None or not grid.nx or not grid.ny:
        return {}
    blanks = sum(1 for v in grid.values if grid.is_blank(v, None, blank_abs))
    step_x = (grid.x1 - grid.x0) / max(grid.nx - 1, 1)
    step_y = (grid.y1 - grid.y0) / max(grid.ny - 1, 1)
    return {
        "extent": {"x0": grid.x0, "y0": grid.y0, "x1": grid.x1, "y1": grid.y1},
        "box": {"min_x": round(grid.x0, 6), "min_y": round(grid.y0, 6),
                "length_x": round(grid.x1 - grid.x0, 6), "length_y": round(grid.y1 - grid.y0, 6)},
        "step": {"step_x": round(step_x, 6), "step_y": round(step_y, 6),
                 "counts_x": grid.nx, "counts_y": grid.ny},
        "blank_share": round(blanks / (grid.total or 1), 4),
    }


def _ontology_formats() -> dict:
    """Описания форматов файлов — ИЗ ОНТОЛОГИИ (данные, а не код под объект)."""
    path = Path(__file__).resolve().parents[1] / "ontology" / "input_recognition_rules.yaml"
    if not path.is_file():
        return {}
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:                                   # noqa: BLE001 — данные опциональны
        return {}
    return {str(k): dict(v or {}) for k, v in (data.get("formats") or {}).items()}


def _petrel_marker_candidates(path: Path, spec: dict) -> list[str]:
    """Маркеры из Petrel Well Tops ПО ОПИСАНИЮ АДАПТЕРА (данные онтологии).

    Формат (проверено на втором объекте, файл `Well_Tops`, 7668 строк):
        #Petrel Well Tops / VERSION 2 / BEGIN HEADER / X Y Z MD Type
        "Surface Name" "Well Name" Interpreter / END HEADER
        450347.24 7012401.80 -2756.49 3329.30 HORIZON "Ю1-1_TOP_S" "341_119G" ""
    Имя маркера — колонка `Surface Name`, глубина — `Z`/`MD`, скважина — `Well Name`.
    Кодировка — из данных (`encoding`), при неудаче перебираются типовые.
    """
    tokens = [str(t) for t in (spec.get("detect", {}).get("first_line_contains") or [])]
    encodings = [str(spec.get("encoding") or "auto"), "utf-8", "cp1251", "utf-16"]
    text = ""
    raw = path.read_bytes()
    for enc in encodings:
        if enc == "auto":
            continue
        try:
            text = raw.decode(enc)
            break
        except Exception:                               # noqa: BLE001
            continue
    if not text:
        text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if tokens and not any(t.lower() in (lines[0] if lines else "").lower() for t in tokens):
        return []
    marker_col = None
    names: dict[str, int] = {}
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        up = s.upper()
        if up in ("BEGIN HEADER", "END HEADER", "VERSION 2"):
            continue
        if marker_col is None:
            # внутри HEADER: имена колонок по одной в строке
            if s.upper() in ("X", "Y", "Z", "MD", "TYPE", "INTERPRETER"):
                continue
            if "SURFACE" in up and "NAME" in up:
                marker_col = "surface_name"
                continue
            if "WELL" in up and "NAME" in up:
                continue
            if marker_col is None:
                continue
        # строка данных: числа + строки в кавычках. ПЕРВАЯ кавычка строки — колонка
        # `Surface Name` (имя маркера), вторая — `Well Name` (проверено на файле поля).
        if '"' in s:
            import re as _re
            quoted = [q.strip() for q in _re.findall(r'"([^"]*)"', s)]
            if quoted:
                name = quoted[0]
                # отбрасываем пустые и «числовые» значения (координаты/глубины)
                if name and not name.replace(".", "").replace("-", "").replace(" ", "").isdigit():
                    names[name] = names.get(name, 0) + 1
    return [m for m, _n in sorted(names.items(), key=lambda kv: (-kv[1], kv[0]))]


def _ontology_marker_rule() -> dict:
    """Правило выбора кровли/подошвы — ИЗ ОНТОЛОГИИ (`markers` в input_recognition_rules).

    Возвращает `{top_suffixes: [...], base_suffixes: [...]}` (суффиксы имён маркеров).
    Нет файла/полей → пустой словарь (неизвестное != ложь).
    """
    path = Path(__file__).resolve().parents[1] / "ontology" / "input_recognition_rules.yaml"
    if not path.is_file():
        return {}
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:                                   # noqa: BLE001 — данные опциональны
        return {}
    mk = dict(data.get("markers") or {})
    return {"top_suffixes": list((mk.get("top") or {}).get("suffix_patterns") or []),
            "base_suffixes": list((mk.get("base") or {}).get("suffix_patterns") or [])}


def marker_candidates(welltop_path: Path) -> list[str]:
    """Кандидаты маркеров (distinct, по частоте) из файла отбивок.

    Формат выбирается ПО ДАННЫМ: если файл совпал с адаптером из онтологии
    (`formats.petrel_well_tops`) — читаем им; иначе — штатным читателем поля.
    """
    if not welltop_path:
        return []
    path = Path(welltop_path)
    for _fname, spec in (_ontology_formats() or {}).items():
        if not isinstance(spec, dict) or not spec.get("marker_name_from"):
            continue
        got = _petrel_marker_candidates(path, spec)
        if got:
            return got
    from domain.welltops import read_welltops
    tops = read_welltops(path)
    seen: dict[str, int] = {}
    for marks in tops.values():
        for marker, _depth in marks:
            if marker:
                seen[marker] = seen.get(marker, 0) + 1
    return [m for m, _n in sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))]


@dataclass
class GraphDraft:
    """Черновик проектного графа: итоговый словарь + авто-часть + список TODO."""

    field: str
    graph: dict = field(default_factory=dict)
    auto: dict = field(default_factory=dict)
    todo: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.graph)

    def to_yaml(self) -> str:
        import yaml
        return yaml.safe_dump(self.graph, allow_unicode=True, sort_keys=False)

    def to_json(self) -> str:
        return json.dumps(self.graph, ensure_ascii=False, indent=2)


# Семантические поля, которые генератор НЕ выводит (нужен человек/LLM).
SEMANTIC_TODO: tuple[str, ...] = (
    "markers.reservoir_top", "reservoir_horizon",
    "contacts", "pvt", "scal", "thresholds", "geostat",
)


def build_draft(field: str, data_root, template_graph: dict, *,
                dataset_root_value: str | None = None) -> GraphDraft:
    """Собрать черновик графа: данные (авто) + шаблон (клон) + TODO (семантика).

    Семантику ПОЛЯ (кровля/горизонт) переносим из шаблона ТОЛЬКО если шаблон того же
    поля; для нового поля — `__todo__` (выбор из `markers.candidates`).
    """
    data_root = Path(data_root)
    template_graph = template_graph or {}
    tpl_field = str(template_graph.get("field") or "")
    same_field = bool(tpl_field) and tpl_field == field

    graph = copy.deepcopy(template_graph)
    graph["field"] = field
    if dataset_root_value is None:
        from core.config import SERVICE_ROOT
        dataset_root_value = _rel(data_root, SERVICE_ROOT)
    graph["dataset_root"] = str(dataset_root_value)

    inputs, in_todo = detect_inputs(data_root, template_graph.get("inputs") or {})
    graph["inputs"] = inputs

    surface = data_root / str(inputs.get("surface", "")) if inputs.get("surface") else None
    struct = detect_structural(surface) if surface else {}
    if struct:
        graph["structural"] = struct

    welltop = data_root / str(inputs.get("welltop", "")) if inputs.get("welltop") else None
    cands = marker_candidates(welltop) if welltop else []
    markers = dict(graph.get("markers") or {})
    if cands:
        markers["candidates"] = cands
    # Кровля/подошва — ПО ПРАВИЛУ ИЗ ОНТОЛОГИИ (суффиксы имён маркеров, ДАННЫЕ), а не по
    # именам конкретного месторождения. Нет правила/совпадений → остаётся TODO (правило 6).
    if cands and not markers.get("reservoir_top"):
        rule = _ontology_marker_rule()

        def _pick(pats) -> str:
            for c in cands:
                up = str(c).upper()
                if any(str(p).upper() in up for p in (pats or [])):
                    return str(c)
            return ""

        top = _pick(rule.get("top_suffixes"))
        base = _pick(rule.get("base_suffixes"))
        if top:
            markers["reservoir_top"] = top
        if base:
            markers["reservoir_base"] = base
    # ЗАГЛУШКА только если кровля так и не определена (иначе разрешённое по правилу
    # онтологии значение перетиралось для любого нового поля — проверено на ТЕСТ2).
    if not markers.get("reservoir_top"):
        markers["reservoir_top"] = TODO
    graph["markers"] = markers
    if not same_field or not graph.get("reservoir_horizon"):
        graph["reservoir_horizon"] = TODO

    todo = list(dict.fromkeys(list(in_todo) + list(SEMANTIC_TODO)))
    graph["todo"] = todo

    auto = {"inputs": sorted(inputs), "markers_candidates": cands,
            "structural": bool(struct), "same_field": same_field}
    return GraphDraft(field=field, graph=graph, auto=auto, todo=todo)

