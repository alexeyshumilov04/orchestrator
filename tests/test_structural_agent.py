"""Тесты структурного агента (E5), агента сетки (E6) и триад экспорта из эталона.

Запуск:  python -X utf8 tests/test_structural_agent.py

Проверяется:
  * StructuralAgent (AG_STRUCTURAL): рабочий интервал из ДАННЫХ, решение о врезе
    (auto|on|off) по покрытию отбивками, порог из данных, план правок (`edits`),
    подсказки параметров из БЗ (`recall`/`suggest`), «неизвестное != ложь»
    (нет отбивок/опыта → `unknown`, а не ложь); совместимость `decide_erosion`
    и алиаса `StructureAgent`;
  * GridAgent (AG_GRID_VOLUMETRICS): бокс из EXTENT структурной карты, шаг,
    ожидаемые `nx/ny`, число слоёв из данных шага, политика QC ячеек (`qc`),
    решение о разломах (по умолчанию — БЕЗ разломов), толерантность к неполным
    данным (нет `step_y`/карты → не падает, а честный `unknown`);
  * триады экспорта из машинного эталона (horizon_export_cps_format,
    map_2d_export_cps_format, marker_export_well_marker_table_format,
    wells_attribute_export, polygon_create_by_map_2d_boundary): список файлов
    `template` + `.rdf` + блок шага в проектном YAML, рендер без предупреждений,
    в прогоне нет `pending_template`;
  * отчётные ключи прогона (`report.json`): `steps`, `structural.erosion`,
    `grid_policy` (бокс/шаг/разломы/QC) заполнены.

Данные в тестах — обезличенные (нейтральные имена), домен поля не используется.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_PASS: list[str] = []
_FAIL: list[str] = []

# Пять функций-триад, добавленных из машинного эталона (reference_workflow.py v26.1).
TRIADS = ("horizon_export_cps_format", "map_2d_export_cps_format",
          "marker_export_well_marker_table_format", "wells_attribute_export",
          "polygon_create_by_map_2d_boundary")


def check(name: str, cond: bool, detail: str = "") -> None:
    (_PASS if cond else _FAIL).append(name)
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + ("" if cond else f"  <-- {detail}"))


def _cfg():
    from core.config import load_config
    return load_config()


def _project(**over) -> dict:
    """Проектный граф-заготовка (нейтральные данные, не домен поля)."""
    base = {
        "structural": {"interval_top_marker": "MK_A", "interval_base_marker": "MK_B",
                       "erosion": "auto", "erosion_steps": ["fn_poly"],
                       "erosion_when_top_coverage_lt": 0.8},
        "functions": {"fn_smooth": {"parameters": {"radius": 100}},
                      "fn_poly": {"objects": {"polygon": {"obj_name": "P",
                                                          "obj_type": "Curve3d"}}}},
        "pipeline": [{"stage": "s1", "steps": [
            {"function": "fn_smooth",
             "objects": {"input_horizon": {"obj_name": "H", "obj_type": "Horizon"}}},
            {"function": "fn_poly"},
        ]}],
    }
    base.update(over)
    return base


def _grid_project(**over) -> dict:
    """Проект с шагом сетки (данные шага: бокс + объект сетки + слои)."""
    step = {"function": "fn_grid",
            "parameters": {"min_x": 100.0, "min_y": 200.0,
                           "length_x": 1000.0, "length_y": 2000.0,
                           "step_x": 50.0, "step_y": 50.0, "counts_step": 22},
            "objects": {"mesh": {"obj_name": "G", "obj_type": "Grid3d"}}}
    base = {"pipeline": [{"stage": "s4", "steps": [step]}], "inputs": {}}
    base.update(over)
    return base


def _extent(x0=100.0, x1=1100.0, y0=200.0, y1=2200.0) -> dict:
    return {"maps": [{"extent": {"x0": x0, "x1": x1, "y0": y0, "y1": y1}}]}


# -- E5: структурный агент ---------------------------------------------------------
def test_structural_erosion_modes() -> None:
    from agents.structural import StructuralAgent
    from agents.structure_policy import StructureAgent, decide_erosion

    check("structural: StructureAgent — алиас канонического StructuralAgent",
          StructureAgent is StructuralAgent and StructureAgent.agent_id == "AG_STRUCTURAL")

    base = _project()
    full = {"welltops": {"w1": [("MK_A", 1.0), ("MK_B", 2.0)],
                         "w2": [("MK_A", 3.0), ("MK_B", 4.0)]}}
    partial = {"welltops": {"w1": [("MK_A", 1.0)], "w2": [("MK_B", 2.0)]}}

    d_full = decide_erosion(base, full)
    check("structural: полное покрытие → врез не нужен",
          d_full["enabled"] is False and d_full["coverage"] == 1.0, str(d_full)[:200])
    d_part = decide_erosion(base, partial)
    check("structural: неполное покрытие → врез строится (auto)",
          d_part["enabled"] is True and d_part["coverage"] == 0.5
          and "размыт" in d_part["reason"], str(d_part)[:200])

    low = _project(structural=dict(base["structural"],
                                   erosion_when_top_coverage_lt=0.5))
    check("structural: порог 0.5 при покрытии 0.5 → врез не нужен (строгое <)",
          decide_erosion(low, partial)["enabled"] is False)

    forced_on = _project(structural=dict(base["structural"], erosion="on"))
    forced_off = _project(structural=dict(base["structural"], erosion="off"))
    check("structural: оператор принудительно включает/выключает врез",
          decide_erosion(forced_on, full)["enabled"] is True
          and decide_erosion(forced_off, full)["enabled"] is False)

    bad_th = _project(structural=dict(base["structural"],
                                      erosion_when_top_coverage_lt="нет"))
    check("structural: нечисловой порог → дефолт 1.0 (осторожно: строить)",
          decide_erosion(bad_th, partial)["enabled"] is True)


def test_structural_unknown_is_not_false() -> None:
    from agents.structural import StructuralAgent

    base = _project()
    d = StructuralAgent().decide(base, {"welltops": {}})
    check("structural: нет отбивок → врез не строится, coverage=None",
          d["enabled"] is False and d["coverage"] is None
          and "неизвестное != ложь" in d["reason"], str(d)[:200])
    check("structural: интервал пуст, но заявлен (не подменён ложью)",
          d["interval"]["wells_total"] == 0 and d["interval"]["top_coverage"] is None,
          str(d["interval"]))
    check("structural: неполный вход этапа виден в missing/unknown",
          bool(d["missing"]) or bool(d["unknown"]),
          str({"missing": d["missing"], "unknown": d["unknown"]}))

    no_section = StructuralAgent().decide({"pipeline": []},
                                          {"welltops": {"w": [("MK_A", 1.0)]}})
    check("structural: нет секции structural → врез не строится",
          no_section["enabled"] is False and no_section["top_marker"] == "",
          str(no_section)[:160])


def test_structural_interval_and_edits() -> None:
    from agents.structural import StructuralAgent

    partial = {"welltops": {"w1": [("MK_A", 1.0)], "w2": [("MK_B", 2.0)]}}
    d = StructuralAgent().decide(_project(), partial)
    check("structural: рабочий интервал посчитан по данным",
          d["interval"]["top_marker"] == "MK_A"
          and d["interval"]["base_marker"] == "MK_B"
          and d["interval"]["wells_with_top"] == 1
          and d["interval"]["wells_with_base"] == 1, str(d["interval"]))
    check("structural: план правок — шаг вреза исполняется при enabled=True",
          d["edits"] and d["edits"][0]["target"] == "fn_poly"
          and d["edits"][0]["action"] == "run"
          and d["edits"][0]["source"] == "structural.erosion_steps", str(d["edits"]))

    full = {"welltops": {"w1": [("MK_A", 1.0)], "w2": [("MK_A", 2.0)]}}
    d_off = StructuralAgent().decide(_project(), full)
    check("structural: план правок — шаг вреза пропускается при enabled=False",
          d_off["edits"] and d_off["edits"][0]["action"] == "skip", str(d_off["edits"]))
    check("structural: настраиваемые функции найдены в ДАННЫХ (пайплайн ∩ overrides)",
          d["tunable_functions"] == ["fn_smooth"], str(d["tunable_functions"]))
    check("structural: план правок при enabled — шаги вреза из данных (не выдуманы)",
          d["parameters"] == {"fn_poly": {}}, str(d["parameters"]))
    check("structural: опыта в БЗ нет → это честно в unknown",
          d["parameters"] != {"fn_smooth": {"radius": 130}}
          and any("опыт" in u for u in d["unknown"]), str(d["unknown"]))
    check("structural: при отключённом врезе план параметров пуст (нечего править)",
          d_off["parameters"] == {}, str(d_off["parameters"]))


def test_structural_tuning_from_kb() -> None:
    from agents.knowledge import KnowledgeBase
    from agents.structural import StructuralAgent

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "kb"
        root.mkdir(parents=True)
        record = {"agent": "AG_STRUCTURAL", "stage": "s1", "functions": ["fn_smooth"],
                  "parameters": {"fn_smooth": {"radius": 130.0}},
                  "outcome": "passed", "status": "approved", "ts": "2026-01-01T00:00:00Z"}
        (root / "ledger.jsonl").write_text(json.dumps(record, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
        agent = StructuralAgent(kb=KnowledgeBase(root=root))
        partial = {"welltops": {"w1": [("MK_A", 1.0)], "w2": [("MK_B", 2.0)]}}
        d = agent.decide(_project(), partial)

    check("structural-БЗ: подсказка параметров IDW/сглаживания/тренда из опыта",
          (d["parameters"] or {}).get("fn_smooth") == {"radius": 130},
          str(d["parameters"]))
    check("structural-БЗ: правка параметров попала в план правок",
          any(e.get("action") == "patch_parameters" and e.get("target") == "fn_smooth"
              for e in d["edits"]), str(d["edits"]))
    check("structural-БЗ: unknown пуст — опыт есть, домысливать нечего",
          d["unknown"] == [], str(d["unknown"]))


# -- E6: агент сетки ---------------------------------------------------------------
def test_grid_box_and_step_from_data() -> None:
    from agents.grid import GridAgent
    from agents.grid_policy import GridAgent as CompatGridAgent, decide_grid

    check("grid: GridAgent доступен и из agents.grid, и из agents.grid_policy",
          CompatGridAgent is GridAgent
          and GridAgent.agent_id == "AG_GRID_VOLUMETRICS")

    d = decide_grid(_grid_project(), _extent())
    fn = d["grid_function"]
    box = (d["parameters"] or {}).get(fn) or {}
    check("grid: бокс из extent карты (данные свидетельства)",
          d["enabled"] is True and fn == "fn_grid"
          and box["min_x"] == 100.0 and box["length_x"] == 1000.0
          and box["length_y"] == 2000.0 and box["autodetect_box"] is False,
          str(d)[:220])
    check("grid: ожидаемые nx/ny = round(length/step)",
          d["expected_nx"] == 20 and d["expected_ny"] == 40, str(d)[:220])
    check("grid: шаг взят из данных шага пайплайна",
          d["step"] == {"step_x": 50.0, "step_y": 50.0}, str(d["step"]))
    check("grid: без карты бокс НЕ навязывается (неизвестное != ложь)",
          decide_grid(_grid_project(), {})["enabled"] is False
          and decide_grid(_grid_project(), {})["box"] == {})
    check("grid: без шага сетки в данных — этап не корректируется",
          decide_grid({"pipeline": []}, _extent())["enabled"] is False
          and decide_grid({"pipeline": []}, _extent())["grid_function"] == "")


def test_grid_layers_and_qc_policy() -> None:
    from agents.grid import GridAgent

    d = GridAgent().decide(_grid_project(), _extent())
    check("grid: число слоёв из данных шага (counts_step)",
          d.get("expected_nz") == 22, str(d)[:200])
    check("grid: ожидаемое число ячеек = nx×ny×nz (политика QC ячеек)",
          d.get("expected_cells") == 20 * 40 * 22, str(d.get("expected_cells")))
    check("grid: QC-сводка для гейта отдана отдельным блоком `qc`",
          d["qc"]["expected_nx"] == 20 and d["qc"]["expected_nz"] == 22
          and d["qc"]["step"] == {"step_x": 50.0, "step_y": 50.0}, str(d["qc"]))

    proj = _grid_project()
    proj["pipeline"][0]["steps"][0]["parameters"].pop("counts_step")
    d2 = GridAgent().decide(proj, _extent())
    check("grid: слои не объявлены → nz не выводится (неизвестное != ложь)",
          "expected_nz" not in d2 and "expected_cells" not in d2
          and any("layers" in u for u in d2["unknown"]), str(d2)[:220])

    proj3 = _grid_project()
    params = proj3["pipeline"][0]["steps"][0]["parameters"]
    params.pop("counts_step")
    params["horizons_table"] = [{"counts_step": 22}, {"counts_step": 10}]
    params["use_one_layering_column"] = True
    d3 = GridAgent().decide(proj3, _extent())
    check("grid: при одноколоночном лейеринге сумма слоёв НЕ выдумывается",
          "expected_nz" not in d3, str(d3)[:200])


def test_grid_tolerates_incomplete_data() -> None:
    from agents.grid import GridAgent

    proj = _grid_project()
    step = proj["pipeline"][0]["steps"][0]
    step["parameters"].pop("step_y")                     # нет шага по Y
    step["parameters"].pop("length_y")                   # и длины бокса по Y
    d = GridAgent().decide(proj, _extent())
    check("grid: нет step_y/length_y — не падает и не выдумывает nx/ny",
          d["enabled"] is True and "expected_nx" not in d
          and "expected_ny" not in d and d["step"] == {"step_x": 50.0}, str(d)[:220])

    broken = {"maps": [{"extent": {"x0": 10.0}}, "мусор", {"extent": None}]}
    d2 = GridAgent().decide(proj, broken)
    check("grid: битый extent → бокс пуст, решение консервативно",
          d2["enabled"] is False and d2["box"] == {}, str(d2)[:200])
    check("grid: пустые свидетельства/проект не роняют агента",
          GridAgent().decide({}, {})["enabled"] is False)


def test_grid_faults_policy_default_off() -> None:
    from agents.grid import GridAgent

    fault_step = {"function": "fn_faults_import",
                  "objects": {"faults": {"obj_name": "F", "obj_type": "Fault3d"}}}
    grid_step = {"function": "fn_grid",
                 "parameters": {"min_x": 100.0, "min_y": 200.0,
                                "length_x": 1000.0, "length_y": 2000.0,
                                "step_x": 50.0, "step_y": 50.0},
                 "objects": {"mesh": {"obj_name": "G", "obj_type": "Grid3d"}}}
    # Подготовленный (НЕ включённый) шаг сетки с разломами: создаёт и сетку, и разломы.
    grid_faults = {"function": "fn_grid_faults",
                   "objects": {"mesh": {"obj_name": "G", "obj_type": "Grid3d"},
                               "faults": {"obj_name": "F", "obj_type": "Fault3d"}}}

    proj = _grid_project(inputs={"faults": "faults.irap"})
    proj["pipeline"][0]["steps"] = [fault_step, grid_step, grid_faults]

    d = GridAgent().decide(proj, _extent())
    check("grid-faults: вход разломов задан, но объект не подтверждён → БЕЗ разломов",
          d["grid_function"] == "fn_grid"
          and d["faults"]["requested"] is True and d["faults"]["enabled"] is False
          and d["faults"]["confirmed"] is None
          and d["faults"]["object"] == "F"
          and d["faults"]["function"] == "fn_grid_faults", str(d["faults"]))
    check("grid-faults: неподтверждённое включение честно в unknown",
          any("faults" in u for u in d["unknown"]), str(d["unknown"]))

    d2 = GridAgent().decide(proj, {"maps": _extent()["maps"],
                                   "faults": {"count": 3}})
    check("grid-faults: объект подтверждён свидетельством → разломы включаются",
          d2["faults"]["enabled"] is True and d2["faults"]["confirmed"] is True
          and d2["faults"]["function"] == "fn_grid_faults", str(d2["faults"]))
    check("grid-faults: подтверждённого включения нет в unknown",
          not any("faults" in u for u in d2["unknown"]), str(d2["unknown"]))

    proj_off = _grid_project()
    proj_off["pipeline"][0]["steps"] = [fault_step, grid_step, grid_faults]
    d3 = GridAgent().decide(proj_off, _extent())
    check("grid-faults: вход разломов не задан → политика молчит (по умолчанию без)",
          d3["faults"]["requested"] is False and d3["faults"]["enabled"] is False,
          str(d3["faults"]))


# -- триады экспорта из машинного эталона -------------------------------------------
def test_triads_files_and_rules() -> None:
    import yaml
    from domain.function_rules import FunctionRuleReader

    reader = FunctionRuleReader(ROOT / "domain" / "ontology_rules")
    project = yaml.safe_load(
        (ROOT / "ontology_project" / "gerasimovskoe.yaml").read_text(encoding="utf-8"))
    steps = [s for st in project.get("pipeline") or []
             for s in (st.get("steps") or [])]
    used = [str((s or {}).get("function") or "") for s in steps]

    for fn in TRIADS:
        tpl = ROOT / "domain" / "templates" / f"{fn}.txt"
        rdf = ROOT / "domain" / "ontology_rules" / f"{fn}.rdf"
        rule = reader.read(fn)
        check(f"триада {fn}: шаблон + правило + блок шага YAML",
              tpl.is_file() and rdf.is_file() and rule is not None
              and Path(rule.template_path).name == f"{fn}.txt"
              and fn in used,
              str({"template": tpl.is_file(), "rdf": rdf.is_file(),
                   "rule": rule is not None, "step": fn in used}))
    check("триада: правила содержат параметры и шаблон_кода",
          all(reader.read(fn).parameters and reader.read(fn).template_path
              for fn in TRIADS), str([fn for fn in TRIADS
                                      if not reader.read(fn).parameters]))
    check("триада: роль полигона в данных — `polygon` (в эталоне нет `boundary`)",
          "polygon" in ((project.get("functions") or {})
                        .get("polygon_create_by_map_2d_boundary", {})
                        .get("objects") or {}),
          str((project.get("functions") or {}).get("polygon_create_by_map_2d_boundary")))


def test_wrappers_accept_cfg_and_kb() -> None:
    """Обёртки принимают cfg/kb: политика входов и опыт БЗ подключаются из прогона."""
    from agents.grid_policy import decide_grid
    from agents.structure_policy import decide_erosion

    cfg = _cfg()
    full = {"welltops": {"w1": [("MK_A", 1.0), ("MK_B", 2.0)]}}
    d = decide_erosion(_project(), full, cfg=cfg)
    check("обёртка: cfg включает политику входов (structural+welltops → не ABSTAIN)",
          d["mode"] != "abstain" and bool(d["coverage_report"]["known"]),
          str(d["coverage_report"]))
    check("обёртка: сигнатура совместима (project, evidence позиционно)",
          decide_erosion(_project(), full)["enabled"] is False)
    g = decide_grid(_grid_project(), _extent(), cfg=cfg)
    check("обёртка grid: cfg принимается, решение по данным не меняется",
          g["expected_nx"] == 20 and g["expected_ny"] == 40, str(g)[:160])


def test_faults_step_prepared_but_off() -> None:
    """Разломы: триада сетки с разломами ПОДГОТОВЛЕНА, но в пайплайн НЕ включена."""
    import yaml
    from agents.grid import GridAgent
    from domain.function_rules import FunctionRuleReader

    faults_fn = "grid_3d_create_by_horizons_with_faults"
    reader = FunctionRuleReader(ROOT / "domain" / "ontology_rules")
    rule = reader.read(faults_fn)
    check("разломы: шаблон + правило сетки с разломами подготовлены (эталон GDAHM1.1)",
          rule is not None
          and (ROOT / "domain" / "templates" / f"{faults_fn}.txt").is_file(),
          str({"rule": rule is not None}))

    project = yaml.safe_load(
        (ROOT / "ontology_project" / "gerasimovskoe.yaml").read_text(encoding="utf-8"))
    used = [str((s or {}).get("function") or "")
            for st in project.get("pipeline") or []
            for s in (st.get("steps") or [])]
    check("разломы: шаг сетки с разломами НЕ включён в пайплайн по умолчанию",
          faults_fn not in used, str([fn for fn in used if fn == faults_fn]))
    d = GridAgent().decide(project, {})
    check("разломы: политика агента по умолчанию строит сетку БЕЗ разломов",
          d["faults"]["enabled"] is False, str(d["faults"]))
    check("разломы: действующая функция сетки — из данных (без разломов)",
          d["grid_function"] and d["grid_function"] != faults_fn, str(d["grid_function"]))


def test_triads_render_without_warnings() -> None:
    from core.config import load_config
    from core.coordinator import Coordinator

    coord = Coordinator(load_config())
    rules = coord.function_rules()
    rule_map = {n: rules.read(n) for n in rules.all_names()}
    nodes = coord.assembler("Герасимовское").node_genes()
    by_fn = {f.function: f for n in nodes for f in n.functions}
    check("триада: все 5 функций попали в гены пайплайна",
          all(fn in by_fn for fn in TRIADS), str([fn for fn in TRIADS
                                                  if fn not in by_fn]))
    check("триада: у всех 5 функций есть правило (не pending_template)",
          all(rule_map.get(fn) is not None for fn in TRIADS))

    builder = coord.workflow_builder()
    index = 1
    for fn in TRIADS:
        block, index = builder.render_block(rule_map[fn], by_fn[fn], index)
        check(f"триада {fn}: рендер без предупреждений",
              bool(block) and fn in block, block[:120])
    check("триада: рендер не оставил предупреждений builder",
          builder.warnings == [], str(builder.warnings))


# -- отчётные ключи прогона ---------------------------------------------------------
def test_report_keys_from_dry_run() -> None:
    from core.coordinator import Coordinator

    coord = Coordinator(_cfg(), dry_run=True)
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / "run"
        report = coord.run("Герасимовское", run_dir=run_dir, execute=False)
        progress = json.loads((run_dir / "agents" / "progress.json")
                              .read_text(encoding="utf-8"))

    steps = report.get("steps") or {}
    skipped = (steps.get("counts") or {}).get("skipped_by_policy", 0)
    check("отчёт: dry-run без ошибок и без pending_template",
          steps.get("error") == 0 and steps.get("pending_template") == 0
          and report.get("render_warnings") == [],
          str({"steps": steps, "render_warnings": report.get("render_warnings")}))
    check("отчёт: done = total − skipped_by_policy",
          steps.get("done") == steps.get("total", 0) - skipped, str(steps))
    check("отчёт: 5 экспортных шагов добавлены (total вырос ≥ 41)",
          steps.get("total", 0) >= 41, str(steps))

    erosion = (report.get("structural") or {}).get("erosion") or {}
    check("отчёт: решение структурного агента с интервалом и планом правок",
          {"enabled", "coverage", "reason", "interval", "edits"} <= set(erosion),
          str(sorted(erosion)))
    check("отчёт: интервал посчитан по отбивкам проекта",
          erosion["interval"]["wells_total"] > 0
          and erosion["interval"]["top_marker"] != "", str(erosion["interval"]))

    grid = report.get("grid_policy") or {}
    check("отчёт: решение агента сетки (бокс/шаг/nx/ny/faults/qc)",
          {"grid_function", "box", "step", "expected_nx", "expected_ny",
           "faults", "qc"} <= set(grid) and bool(grid["grid_function"])
          and bool(grid["box"]), str(sorted(grid)))
    check("отчёт: разломы по умолчанию НЕ включены",
          grid["faults"]["enabled"] is False, str(grid["faults"]))

    done_fns = {s.get("function") for s in (progress.get("steps") or {}).get("steps") or []
                if s.get("status") == "done"}
    check("отчёт: все 5 триад отрендерены (status=done) в шине шагов",
          set(TRIADS) <= done_fns, str(sorted(set(TRIADS) - done_fns)))


def main() -> int:
    for fn in (test_structural_erosion_modes, test_structural_unknown_is_not_false,
               test_structural_interval_and_edits, test_structural_tuning_from_kb,
               test_grid_box_and_step_from_data, test_grid_layers_and_qc_policy,
               test_grid_tolerates_incomplete_data, test_grid_faults_policy_default_off,
               test_wrappers_accept_cfg_and_kb, test_faults_step_prepared_but_off,
               test_triads_files_and_rules, test_triads_render_without_warnings,
               test_report_keys_from_dry_run):
        try:
            fn()
        except Exception as exc:                       # noqa: BLE001
            check(f"{fn.__name__}: без исключений", False, repr(exc))
    print("\n=== ИТОГ ===")
    print(f"всего: {len(_PASS) + len(_FAIL)} | провалено: {len(_FAIL)}")
    if _FAIL:
        print("Проваленные: " + ", ".join(_FAIL))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
