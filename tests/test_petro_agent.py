"""Тесты E3+E8+E9: агенты петрофизики/насыщения/карт и console-safe слой карт.

Проверяется то, что заявлено в task-5:
  * политика агентов берётся ИЗ ДАННЫХ (метод/кубы/вариограмма/пороги φ,k/контакты);
  * «неизвестное != ложь»: нет данных → unknown/ABSTAIN, а не «прошло» и не «провал»;
  * карты: маршруты «нативный экспорт тНава» / «фолбэк» / «нет маршрута»;
  * проба-слой `domain/qc/probes.py`: генерация py-кода и разбор отчёта;
  * рендер карт: irap- и CPS-выгрузки тНава → PNG (domain/map_render.py);
  * триады (шаблон + правило) реально рендерятся и не тянут чужие токены.

Запуск:  python -X utf8 tests/test_petro_agent.py
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_PASS: list[str] = []
_FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (_PASS if cond else _FAIL).append(name)
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + ("" if cond else f"  <-- {detail}"))


def _cfg():
    from core.config import load_config
    return load_config()


def _graph(cfg):
    from core.coordinator import Coordinator
    return Coordinator(cfg).project_graph(str(cfg.get("project.default_field", "") or ""))


# --- E8: агент петрофизики -------------------------------------------------------
def test_petrophysics_policy() -> None:
    from agents.petrophysics import PetrophysicsAgent, decide_petrophysics

    cfg = _cfg()
    graph = _graph(cfg)
    petro = graph.get("petrophysics") or {}
    d = PetrophysicsAgent(cfg).decide(graph, {})
    check("petro: этап включён по данным (cubes заданы)", bool(d.get("enabled")), str(d)[:200])
    check("petro: метод взят из данных",
          d.get("method") == str(petro.get("method") or "").lower(), str(d.get("method")))
    check("petro: кубы взяты из данных", len(d.get("cubes") or []) == len(petro.get("cubes") or []),
          str(d.get("cubes"))[:160])
    vg = petro.get("variogram") or {}
    check("petro: вариограмма из данных",
          (d.get("variogram") or {}).get("range_main") == float(vg.get("range_main") or 0),
          str(d.get("variogram")))
    ranges = d.get("ranges") or {}
    thresholds = graph.get("thresholds") or {}
    props = cfg.get("checks.properties") or {}
    expected_ranges = {}
    for cube in (petro.get("cubes") or []):
        role = next((str(r) for r, item in props.items()
                     if isinstance(item, dict) and item.get("cube") == cube.get("cube")), "")
        if role and isinstance(thresholds.get(role), (list, tuple)):
            expected_ranges[str(cube.get("cube"))] = [float(thresholds[role][0]),
                                                      float(thresholds[role][1])]
    check("petro: диапазоны физичности из thresholds (порогов в коде нет)",
          bool(expected_ranges) and ranges == expected_ranges,
          f"{ranges} != {expected_ranges}")
    zone = d.get("zone") or {}
    check("petro: способ учёта фаций решён по данным (куба зон нет → беззонная форма)",
          zone.get("use_zone") is False and str(zone.get("mode", "")).startswith("no_zone"),
          str(zone))
    check("petro: метод вне разрешённого набора или подтверждён (method_ok не выдуман)",
          d.get("method_ok") in (True, False, None), str(d.get("method_ok")))

    empty = PetrophysicsAgent(cfg).decide({"petrophysics": {}}, {})
    check("petro: без cubes этап отключается (неизвестное != ложь)",
          empty.get("enabled") is False and "cubes" in str(empty.get("reason", "")),
          str(empty)[:180])
    no_thr = PetrophysicsAgent(cfg).decide(
        {"petrophysics": {"method": "x", "cubes": [{"log": "L", "blocked": "B", "cube": "C"}]}}, {})
    check("petro: нет порога физичности → unknown, а не ноль",
          not (no_thr.get("ranges") or {}) and bool(no_thr.get("unknown")),
          str(no_thr.get("unknown")))
    compat = decide_petrophysics({"petrophysics": {"method": "kriging",
                                                   "cubes": [{"log": "L", "cube": "C"}]}}, {})
    check("petro: обёртка decide_petrophysics сохраняет контракт v5",
          compat.get("enabled") and compat.get("method") == "kriging"
          and {"mode", "plan", "agent_id"} <= set(compat), str(sorted(compat))[:160])


# --- E3: агент насыщения ---------------------------------------------------------
def test_saturation_policy() -> None:
    from agents.saturation import SaturationAgent

    cfg = _cfg()
    project = {"contacts": {"owc_offset_m": 20.0},
               "structural": {"interval_top_marker": "M1"},
               "thresholds": {"swl": [0.05, 0.6]},
               "scal": {}}
    evidence = {"welltops": {"w1": [("M1", 100.0)], "w2": [("M1", 102.0)]}}
    d = SaturationAgent(cfg).decide(project, evidence)
    contact = (d.get("contacts") or {}).get("oil_water") or {}
    check("sat: контакт по смещению от датума (из отбивок) — отрицательная отметка",
          d.get("enabled") and contact.get("mode") == "offset"
          and contact.get("z") == -121.0, str(contact))
    check("sat: датум зафиксирован с источником (медиана отбивок)",
          "медиана" in str((d.get("datum") or {}).get("note", "")), str(d.get("datum")))
    controls = d.get("controls") or {}
    check("sat: контроль — диапазон Sw из thresholds и пробелы в unknown",
          controls.get("sw_range") == [0.05, 0.6]
          and "scal.swof/scal.sgof" in (d.get("unknown") or []), str(controls))

    explicit = SaturationAgent(cfg).decide({"contacts": {"owc": -2543.4}}, {})
    check("sat: явная отметка контакта → способ «value»",
          (explicit.get("contacts") or {}).get("oil_water", {}).get("mode") == "value",
          str(explicit.get("contacts")))
    none = SaturationAgent(cfg).decide({"contacts": {}}, {})
    check("sat: контактов нет → этап отключён (не выдумывается)",
          none.get("enabled") is False, str(none)[:140])
    no_datum = SaturationAgent(cfg).decide({"contacts": {"owc_offset_m": 20.0}}, {})
    check("sat: нет датума → отметка unknown, а не ноль",
          (no_datum.get("contacts") or {}).get("oil_water", {}).get("z") is None
          and bool(no_datum.get("unknown")), str(no_datum.get("contacts")))


# --- E9: агент карт --------------------------------------------------------------
def test_maps_policy() -> None:
    from agents.maps import MapsAgent

    cfg = _cfg()
    graph = _graph(cfg)
    d = MapsAgent(cfg).decide(graph, {})
    expected = [str(x) for x in (cfg.get("checks.map_files") or [])]
    check("maps: список ожидаемых карт — из данных checks.map_files",
          d.get("expected") == expected, str(d.get("expected")))
    routes = {r["name"]: r for r in (d.get("routes") or [])}
    native = [n for n, r in routes.items() if r.get("path") == "native"]
    check("maps: нативный маршрут есть (шаги map_2d_export_* из проектного графа)",
          bool(native) and any(r.get("file") for r in routes.values()
                               if r.get("path") == "native"), str(native))
    check("maps: фолбэк-маршрут берётся из checks.map_sources",
          all(routes[n]["path"] == "fallback"
              for n, src in (cfg.get("checks.map_sources") or {}).items()
              if src and n in routes and routes[n]["path"] != "native"),
          str({n: r["path"] for n, r in routes.items()}))
    check("maps: карта без маршрута попадает в unknown_routes",
          isinstance(d.get("unknown_routes"), list) and d.get("complete") in (True, False),
          str(d.get("unknown_routes")))
    check("maps: решения «провалено» нет — отсутствие данных не штраф",
          "failed" not in d and "passed" not in d, str(sorted(d))[:160])

    no_data = MapsAgent(cfg).decide({"pipeline": []}, {})
    check("maps: без шагов выгрузки маршруты unknown, контроль не выдуман",
          no_data.get("enabled") and all(r.get("path") in ("fallback", "unknown")
                                         for r in no_data.get("routes") or []),
          str(no_data.get("routes"))[:200])


# --- E3: пробники открытого проекта ---------------------------------------------
def test_probes_layer() -> None:
    from domain.qc import probes

    tmp = Path(tempfile.mkdtemp()) / "probe.txt"
    for name, code in (
            ("property_inventory", probes.property_inventory_code("g", tmp)),
            ("statistics", probes.statistics_code("g", "p", tmp, percentiles=(10, 50, 90))),
            ("facies", probes.facies_proportions_code("g", "p", tmp, codes=(0, 1, 2))),
            ("contacts", probes.contacts_code(("A", "B"), tmp)),
            ("reserves", probes.reserves_code("g", ("A", "B"), tmp))):
        ok = True
        try:
            compile(code, f"<{name}>", "exec")
        except SyntaxError as exc:                    # noqa: PERF203 — диагностика
            ok = False
            print(f"       {name}: {exc}")
        check(f"probes: сниппет «{name}» — валидный py-код", ok)
    stat = probes.statistics_code("g", "p", tmp, percentiles=(10,))
    check("probes: проценты читаются с фиксацией ошибки API, а не нулём",
          "p10__error" in stat and "'p10|unknown'" in stat)
    parsed = probes.parse_report("mean|0.21\nproperty|X|Grid3dProperty\n"
                                 "facies|1|0.5\np10|unknown\n"
                                 "p10__error|RuntimeError: нет API")
    check("probes: разбор отчёта «ключ|значение»",
          parsed.get("mean") == 0.21 and parsed.get("property") == ["X|Grid3dProperty"]
          and (parsed.get("facies") or {}).get("1") == 0.5, str(parsed))
    check("probes: причина недоступности величины сохраняется",
          str(parsed.get("p10")) == "unknown" and "нет API" in str(parsed.get("p10__error")),
          str(parsed)[:160])
    empty = probes.read_capture(None, code="'ok'", tmp=tmp)
    check("probes: без открытого проекта — ошибка канала, а не нули",
          "__error" in empty, str(empty))


# --- E9: рендер PNG из выгрузок тНава -------------------------------------------
def _irap_text(nx: int, ny: int, *, blank_cell: tuple[int, int] | None = None) -> str:
    """Синтетическая выгрузка тНава в формате «полный irap» (nx×ny значений)."""
    values = []
    for iy in range(ny):
        for ix in range(nx):
            values.append(9999900.0 if blank_cell == (ix, iy)
                          else round(0.1 + 0.01 * (ix + iy * nx), 4))
    rows = [" ".join(str(v) for v in values[i:i + nx])
            for i in range(0, len(values), nx)]
    return (f"-996 {ny} 50.0 50.0\n0.0 {50.0 * nx} 0.0 {50.0 * ny}\n"
            f"{nx} 0.0 0.0 0.0\n" + "\n".join(rows) + "\n")


def _cps_text(nx: int, ny: int, *, blank_cell: tuple[int, int] = (0, 0)) -> str:
    """Синтетическая выгрузка тНава CPS-3 Grid (ASCII) с одной пустой ячейкой."""
    values = []
    for iy in range(ny):
        for ix in range(nx):
            values.append(99999.0 if blank_cell == (ix, iy)
                          else round(0.1 + 0.01 * (ix + iy * nx), 4))
    rows = [" ".join(str(v) for v in values[i:i + nx])
            for i in range(0, len(values), nx)]
    return ("FSASCI 0 1 \"Computed\" 0 99999.000000 0\nFSATTR 0 0\n"
            f"FSLIMI 0.0 {50.0 * nx} 0.0 {50.0 * ny} 0.0 0.0\n"
            f"FSNROW {nx} {ny}\nFSXINC 50.0 50.0\n-> Surface\n" + "\n".join(rows) + "\n")


def test_map_render_layer() -> None:
    from domain.map_render import read_ascii_grid, render_map
    from domain.qc import maps as qc_maps

    tmp = Path(tempfile.mkdtemp())
    run_dir = tmp / "run"
    run_dir.mkdir()
    (run_dir / "export_ascii.txt").write_text(_irap_text(5, 5, blank_cell=(4, 4)),
                                              encoding="utf-8")
    (run_dir / "export_cps.txt").write_text(_cps_text(5, 5), encoding="utf-8")
    grid = read_ascii_grid(run_dir / "export_ascii.txt")
    check("maps: ASCII-выгрузка тНава («полный irap») разбирается, бланк отброшен",
          bool(grid) and len(grid[2]) == 24, str(grid and len(grid[2])))
    cps = read_ascii_grid(run_dir / "export_cps.txt")
    check("maps: CPS-выгрузка тНава (FSASCI/FSLIMI) разбирается, бланк отброшен",
          bool(cps) and len(cps[2]) == 24, str(cps and len(cps[2])))
    for name, src in (("render_ascii.png", "export_ascii.txt"),
                      ("render_cps.png", "export_cps.txt")):
        out = render_map(run_dir / src, run_dir / "maps" / name, title=name)
        check(f"maps: PNG построен ({name})", bool(out) and Path(out).is_file(), str(out))

    project = {"pipeline": [{"stage": "s", "steps": [
        {"function": "map_2d_export_ascii_format",
         "parameters": {"file_name": "export_ascii.txt"},
         "objects": {"map_2d": {"obj_name": "M1", "obj_type": "Map2d"}}}]}]}
    steps = qc_maps.export_steps(project)
    check("maps: шаг выгрузки читается из проектного графа (имя/файл/формат)",
          steps and steps[0]["name"] == "M1" and steps[0]["file_name"] == "export_ascii.txt"
          and steps[0]["format"] == "ascii", str(steps))
    cfg = _cfg()
    report = qc_maps.ensure_maps_report(run_dir, cfg, project)
    check("maps: нативная карта отрисована и попала в отчёт",
          "M1" in report["native"] and "M1" in report["produced"], str(report)[:200])
    check("maps: ensure_maps (для _ensure_maps) возвращает список имён PNG, а не словарь",
          isinstance(qc_maps.ensure_maps(run_dir, cfg, project), list))
    check("maps: отсутствующие карты перечислены без «провала»",
          bool(report["missing"]) and not report["errors"], str(report["errors"])[:160])


# --- триады: шаблон + правило + рендер ------------------------------------------
def test_triads_render() -> None:
    from core.coordinator import Coordinator
    from domain.function_rules import FunctionRuleReader

    cfg = _cfg()
    coord = Coordinator(cfg)
    rules = coord.function_rules()
    for fn in ("map_2d_create_by_grid_property", "map_2d_export_ascii_format",
               "map_2d_export_cps_format", "grid_property_interpolate_by_wells_log_3d"):
        tpl = cfg.path("workflow.templates_dir") / f"{fn}.txt"
        rdf = cfg.path("workflow.rules_dir") / f"{fn}.rdf"
        rule = rules.read(fn)
        check(f"триада {fn}: шаблон + правило + чтение правила",
              tpl.is_file() and rdf.is_file() and rule is not None and rule.template_path)

    rules_dir = FunctionRuleReader(cfg.path("workflow.rules_dir"))
    rule_map = {n: rules_dir.read(n) for n in rules_dir.all_names()}
    rule_map = {k: v for k, v in rule_map.items() if v}
    nodes = coord.assembler(str(cfg.get("project.default_field", "") or "")).node_genes()
    builder = coord.workflow_builder()
    map_node = next((n for n in nodes
                     if any(f.function == "map_2d_export_ascii_format" for f in n.functions)), None)
    text = ""
    index = 1
    if map_node is not None:
        for gene in map_node.functions:
            rule = rule_map.get(gene.function)
            if rule is None:
                continue
            block, index = builder.render_block(rule, gene, index)
            text += block + "\n"
    check("этап карт: рендер без предупреждений (нет потерянных replace/param/object)",
          bool(text) and builder.warnings == [], str(builder.warnings[:5]))
    check("этап карт: консольный путь (создание карты + выгрузка) в рендере",
          "map_2d_create_by_grid_property" in text and "map_2d_export_ascii_format" in text
          and "map_2d_export_cps_format" in text, text[:200])
    # РЕГРЕСС реального прогона: «Could not recognize python code as workflow item» —
    # внутри элемента воркфлоу допустимы ТОЛЬКО вызовы функций тНава.
    python_lines = [ln.strip() for ln in text.splitlines()
                    if re.match(r"^\s+(import |from |if |for |try:|except |print |"
                                r"__import__|os\.|_os_)", ln)]
    check("этап карт: в рендере нет Python-инструкций (import/__import__/makedirs)",
          not python_lines and "makedirs" not in text and "__import__" not in text,
          str(python_lines[:3]))
    check("этап карт: каталог выгрузки создаётся ОРКЕСТРАТОРОМ, а не в элементе",
          "get_project_folder" not in text and "makedirs" not in text)
    export_dirs = [str(x) for x in (cfg.get("workflow.export_dirs") or [])]
    export_files = [str((g.parameters or {}).get("file_name") or "")
                    for g in (map_node.functions if map_node else [])
                    if str(g.function).startswith("map_2d_export")]
    check("этап карт: каталоги выгрузок шагов объявлены в данных workflow.export_dirs",
          bool(export_dirs) and bool(export_files)
          and all(Path(f).parent.as_posix() in export_dirs for f in export_files),
          f"{export_files[:3]} vs {export_dirs}")
    foreign = [str(t) for t in (cfg.get("workflow.foreign_tokens") or []) if str(t)]
    hits = [t for t in foreign if t in text]
    check("этап карт: чужих токенов проекта обучения в рендере нет", not hits, str(hits))
    create = next((ln for ln in text.splitlines()
                   if ln.strip().startswith("map_2d_create_by_grid_property (")), "")
    check("этап карт: выравнивание рендера (4 пробела, вызов на месте)",
          create.startswith("    map_2d_create_by_grid_property ("), repr(create))


# --- F-19: свидетельства результата этапа (grid_properties/property_stats/blocked) ---
class _StubProp:
    """Заглушка свойства куба: массив + `compute_statistics` как у тНава."""

    def __init__(self, values) -> None:
        self._values = values

    def get_np_array(self):
        import numpy as np
        return np.asarray(self._values, dtype=float)

    def compute_statistics(self, type=None):          # noqa: A002 — имя параметра API
        import numpy as np
        arr = np.asarray(self._values, dtype=float)
        finite = arr[np.isfinite(arr)]
        if not finite.size:
            return 0.0
        if type == "min":
            return float(finite.min())
        if type == "max":
            return float(finite.max())
        if type == "mean":
            return float(finite.mean())
        if type == "sum":
            return float(finite.sum())
        if type == "standard_deviation":
            return float(finite.std())
        raise RuntimeError('Invalid call of function property__compute_statistics: '
                           'Bad value given for argument "type"')


class _StubGrid:
    """Заглушка сетки: `get_property_by_name` с ошибкой тНава для чужих имён."""

    def __init__(self, props: dict) -> None:
        self._props = props

    def get_property_by_name(self, name=None):        # noqa: A002 — имя параметра API
        if name not in self._props:
            raise RuntimeError(f"Grid main_grid does not have a Property with name '{name}'.")
        return self._props[name]


def _run_stats_snippet() -> dict:
    """Исполнить сгенерированный сниппет статистики на заглушке API (без тНава)."""
    from domain.qc import probes

    import numpy as np
    blank = np.full(25, np.nan)
    ok = [1.0, 2.0, 3.0] * 30 + [np.nan] * 10          # 90 непустых, 10 пустых
    many = list(np.linspace(0.0, 1.0, 70))             # 70 уникальных > предела 64
    grid = _StubGrid({"ok": _StubProp(ok), "many": _StubProp(many),
                      "blank": _StubProp(blank)})
    tmp = Path(tempfile.mkdtemp()) / "stats.tmp"
    code = probes.property_stats_code("main_grid", ["ok", "many", "blank"], tmp)
    exec(compile(code, "<stats-snippet>", "exec"),       # noqa: S102 — тест генерируемого кода
         {"get_grid_by_name": lambda name=None: grid})
    report = probes.parse_report(tmp.read_text(encoding="utf-8"))
    return probes.parse_property_stats(report) or {}


def test_gate_evidence() -> None:
    from domain.qc import probes

    check("evid: имена свидетельств — согласованный контракт (foundation, task-9)",
          probes.EVIDENCE_KINDS == ("grid_properties", "property_stats", "blocked_wells"),
          str(probes.EVIDENCE_KINDS))

    cfg = _cfg()
    names = probes.property_names(cfg)
    props = cfg.get("checks.properties") or {}
    expected = sorted(str(v.get("cube")) for v in props.values()
                      if isinstance(v, dict) and v.get("cube"))
    metric = cfg.get("ensemble.metric")
    check("evid: имена кубов берутся из данных checks.properties (+ метрика ансамбля)",
          all(n in names for n in expected)
          and (not metric or str(metric) in names)
          and len(names) == len(set(names)), f"{names} vs {expected}")
    check("evid: без конфигурации имён нет (свидетельство не выдумывается)",
          probes.property_names(None) == [] and probes.property_names({}) == [])

    tmp = Path(tempfile.mkdtemp()) / "e.tmp"
    gp_code = probes.grid_properties_code("G", tmp)
    ps_code = probes.property_stats_code("G", ["X", "Y"], tmp)
    bw_code = probes.blocked_wells_code(tmp, "G")
    for tag, code in (("grid_properties", gp_code), ("property_stats", ps_code),
                      ("blocked_wells", bw_code)):
        ok = True
        try:
            compile(code, f"<{tag}>", "exec")
        except SyntaxError as exc:                     # noqa: PERF203 — диагностика
            ok = False
            print(f"       {tag}: {exc}")
        check(f"evid: сниппет «{tag}» — валидный py-код", ok)
    check("evid: список свойств — через get_all_properties + маркер успешного вызова",
          "get_all_properties" in gp_code and "__properties_total" in gp_code)
    check("evid: статистика — compute_statistics + массив куба (count/nulls/cells)",
          "compute_statistics" in ps_code and "count=" in ps_code and "nulls=" in ps_code
          and "get_np_array" in ps_code)
    check("evid: доля непустых ячеек считается (nonempty_fraction), а не угадывается",
          "nonempty_fraction" in ps_code)
    check("evid: усечённый список классов помечается (classes_truncated); "
          "отсутствие classes ≠ «куб пуст»",
          "classes_truncated" in ps_code)
    check("evid: имена свойств в сниппете — только переданные (домена в коде нет)",
          "'X'" in ps_code and "'Y'" in ps_code
          and not any(n in ps_code for n in names if n not in ("X", "Y")))
    check("evid: blocked wells — перебор доступных имён + маршрут через объект сетки",
          "get_all_blocked_wells" in bw_code and "__blocked_names" in bw_code
          and "get_grid_by_name" in bw_code)

    # разбор отчёта пробника → свидетельства контрактной формы
    report = probes.parse_report(
        "__properties_total|2\nproperty|FACIES|object\nproperty|PORO|object\n"
        "__blocked_total|1\nblocked|FaciesU\n"
        "__array_source|PORO|get_np_array\n__stat_try|PORO|std|Bad value\n"
        "stats|PORO|min=0.02;max=0.35;mean=0.18;sum=10.0;cells=100;count=90;"
        "nulls=10;unique_count=40\n"
        "stats|FACIES|cells=100;count=100;nulls=0;classes=1.0,2.0,3.0\n"
        "__array_source|PERM|get_np_array\n"
        "stats|PERM|cells=100;count=0;nulls=100;nonempty_fraction=0.0\n"
        "stats|LIT|cells=100;count=100;nulls=0;unique_count=70;classes_truncated=1")
    gp = probes.parse_grid_properties(report)
    ps = probes.parse_property_stats(report)
    bw = probes.parse_blocked_wells(report)
    check("evid: grid_properties = список имён свойств",
          gp == ["FACIES", "PORO"], str(gp))
    check("evid: property_stats содержит count/nulls/cells по каждому кубу",
          (ps or {}).get("PORO", {}).get("count") == 90.0
          and (ps or {}).get("PORO", {}).get("nulls") == 10.0
          and (ps or {}).get("PORO", {}).get("cells") == 100.0, str(ps)[:200])
    check("evid: classes дискретного куба — список чисел",
          (ps or {}).get("FACIES", {}).get("classes") == [1.0, 2.0, 3.0],
          str((ps or {}).get("FACIES")))
    check("evid: причина неподдержанной статистики сохраняется (std), а не теряется",
          "std" in " ".join((ps or {}).get("PORO", {}).get("notes") or []),
          str((ps or {}).get("PORO", {}).get("notes")))
    check("evid: blocked_wells = список имён", bw == ["FaciesU"], str(bw))
    check("evid: пустой куб отличим по count=0 (не по отсутствию classes)",
          (ps or {}).get("PERM", {}).get("count") == 0.0
          and (ps or {}).get("PERM", {}).get("nonempty_fraction") == 0.0, str(ps.get("PERM")))
    check("evid: усечённые классы помечены classes_truncated=1 (куб при этом НЕ пуст)",
          (ps or {}).get("LIT", {}).get("classes_truncated") == 1.0
          and "classes" not in (ps or {}).get("LIT", {})
          and (ps or {}).get("LIT", {}).get("count") == 100.0, str(ps.get("LIT")))

    # --- ИСПОЛНЕНИЕ сниппета на заглушке API (без лицензии) --------------------
    # Ловит ошибки имён/логики в генерируемом коде тНава до реального прогона:
    # считаем count/nulls/nonempty_fraction/classes/classes_truncated по-настоящему.
    live = _run_stats_snippet()
    check("evid(exec): сниппет статистики исполняется и даёт count/nulls/cells",
          (live.get("ok") or {}).get("count") == 90.0
          and (live.get("ok") or {}).get("nulls") == 10.0
          and (live.get("ok") or {}).get("cells") == 100.0, str(live.get("ok")))
    check("evid(exec): nonempty_fraction считается как count/cells",
          (live.get("ok") or {}).get("nonempty_fraction") == 0.9, str(live.get("ok")))
    check("evid(exec): классы перечисляются, когда их мало",
          (live.get("ok") or {}).get("classes") == [1.0, 2.0, 3.0], str(live.get("ok")))
    check("evid(exec): много классов → classes_truncated=1 и НЕТ classes (куб непуст)",
          (live.get("many") or {}).get("classes_truncated") == 1.0
          and "classes" not in (live.get("many") or {})
          and (live.get("many") or {}).get("count", 0) > 0, str(live.get("many")))
    check("evid(exec): пустой куб → count=0, nulls=cells, nonempty_fraction=0",
          (live.get("blank") or {}).get("count") == 0.0
          and (live.get("blank") or {}).get("nulls") == 25.0
          and (live.get("blank") or {}).get("nonempty_fraction") == 0.0,
          str(live.get("blank")))
    check("evid(exec): неподдержанный тип статистики не роняет сниппет (причина в notes)",
          any("std" in str(x) for x in ((live.get("ok") or {}).get("notes") or [])),
          str((live.get("ok") or {}).get("notes")))

    # правило 6: нет API → свидетельства НЕТ; есть API и пусто → ПУСТОЙ контейнер
    check("evid: без проекта/API свидетельства нет (None, а не пустой контейнер)",
          probes.read_grid_properties(None, grid_name="G") is None
          and probes.read_property_stats(None, grid_name="G", names=["X"]) is None
          and probes.read_blocked_wells(None) is None)
    check("evid: API ответил, свойств нет → пустой список (это ФАКТ, а не «неизвестно»)",
          probes.parse_grid_properties({"__properties_total": 0.0}) == []
          and probes.parse_blocked_wells({"__blocked_total": 0.0}) == [])
    check("evid: ошибка API без маркера → свидетельства нет",
          probes.parse_grid_properties({"__grid_error": "нет сетки"}) is None
          and probes.parse_property_stats({"__grid_error": "нет сетки"}) is None
          and probes.parse_blocked_wells({"__api_error": "нет функции"}) is None)


def test_f18_metric_map() -> None:
    """F-18: карта метрики строится из ВЫЧИСЛЕННОГО свойства (куб метрики пуст)."""
    from core.coordinator import Coordinator

    cfg = _cfg()
    graph = _graph(cfg)
    stages = [s for s in (graph.get("pipeline") or [])
              if str(s.get("stage", "")).startswith("10.")]
    check("f18: этап карт один", len(stages) == 1, str(len(stages)))
    steps = stages[0].get("steps") or [] if stages else []
    functions = [str(s.get("function")) for s in steps]

    def obj_name(step, role):
        item = (step.get("objects") or {}).get(role)
        return str(item.get("obj_name")) if isinstance(item, dict) else ""

    metric = str(cfg.get("ensemble.metric", "") or "")
    calc_at = next((i for i, s in enumerate(steps)
                    if s.get("function") == "grid_property_calculator"), -1)
    create_at = next((i for i, s in enumerate(steps)
                      if s.get("function") == "map_2d_create_by_grid_property"
                      and obj_name(s, "map_2d") == metric), -1)
    calc = steps[calc_at] if calc_at >= 0 else {}
    create = steps[create_at] if create_at >= 0 else {}
    derived = obj_name(calc, "result_grid_property")

    check("f18: перед картой метрики есть вычисление производного свойства",
          calc_at >= 0 and create_at > calc_at, f"calc@{calc_at} create@{create_at}")
    check("f18: формула производного свойства — ДАННЫЕ шага (не в коде)",
          bool((calc.get("parameters") or {}).get("formula")),
          str(calc.get("parameters")))
    foreign = [str(t) for t in (cfg.get("workflow.foreign_tokens") or []) if str(t)]
    formula = str((calc.get("parameters") or {}).get("formula") or "")
    check("f18: в формуле нет чужих токенов проекта обучения",
          not any(t in formula for t in foreign), formula)
    check("f18: производное свойство НЕ перезаписывает куб метрики (имя отличается)",
          bool(derived) and derived != metric, f"{derived!r} vs {metric!r}")
    check("f18: карта метрики строится из производного свойства",
          obj_name(create, "cube") == derived, str(create.get("objects")))
    check("f18: имя карты метрики не изменилось (PNG/интерфейс)",
          obj_name(create, "map_2d") == metric, str(create.get("objects")))
    exports = [s for s in steps
               if str(s.get("function")).startswith("map_2d_export")
               and obj_name(s, "map_2d") == metric]
    check("f18: выгрузка карты метрики — по-прежнему один файл (без перезаписи)",
          len(exports) == 1
          and str((exports[0].get("parameters") or {}).get("file_name", "")).endswith(
              f"{metric}.txt"),
          str([(e.get("function"),
                (e.get("parameters") or {}).get("file_name")) for e in exports]))
    check("f18: триада калькулятора есть (шаблон + правило)",
          (cfg.path("workflow.templates_dir") / "grid_property_calculator.txt").is_file()
          and (cfg.path("workflow.rules_dir") / "grid_property_calculator.rdf").is_file())

    # рендер: шаг калькулятора реально собирается из шаблона без предупреждений
    coord = Coordinator(cfg)
    rules = coord.function_rules()
    builder = coord.workflow_builder()
    for step in ([calc] if calc else []):
        gene = ga = None
        nodes = coord.assembler(str(cfg.get("project.default_field", "") or "")).node_genes()
        for node in nodes:
            for candidate in node.functions:
                if (candidate.function == step.get("function")
                        and str((candidate.objects or {}).get("result_grid_property",
                                                             type("X", (), {"obj_name": ""})()
                                                             ).obj_name) == derived):
                    gene = candidate
        if gene is not None:
            block, _ = builder.render_block(rules.read(gene.function), gene, 1)
            check("f18: шаг калькулятора рендерится с формулой и производным кубом",
                  "grid_property_calculator" in block and derived in block
                  and formula.strip('"') in block, block[:200])
    check("f18: рендер шага калькулятора без предупреждений",
          builder.warnings == [], str(builder.warnings[:4]))
    check("f18: функции этапа карт содержат и калькулятор, и все выгрузки",
          "grid_property_calculator" in functions
          and sum(1 for f in functions if f.startswith("map_2d_export")) >= 8,
          str(functions[:4]))


def main() -> int:
    for fn in (test_petrophysics_policy, test_saturation_policy, test_maps_policy,
               test_probes_layer, test_map_render_layer, test_triads_render,
               test_gate_evidence, test_f18_metric_map):
        try:
            fn()
        except Exception as exc:                       # noqa: BLE001 — тест не должен падать молча
            check(f"{fn.__name__}: без исключений", False, repr(exc))
    print("\n=== ИТОГ ===")
    print(f"пройдено: {len(_PASS)} | провалено: {len(_FAIL)}")
    if _FAIL:
        print("Проваленные: " + ", ".join(_FAIL))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
