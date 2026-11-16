"""Юнит-тесты orchestrator-v5 (чистый Python + yaml/rdflib из окружения).

Запуск:  python tests/test_v5.py

Проверяется ключевое:
  * загрузка онтологии v4 как ДАННЫХ (CVS-каталоги: операции/стадии/QA/параметры);
  * сборка генов из онтологии групп (assembler);
  * рендер tNavigator-воркфлоу (declare_workflow + begin_wf_item/end_wf_item);
  * QA/QC: passed / failed / UNKNOWN.
"""
from __future__ import annotations

import math
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


def test_ontology() -> None:
    from core.config import load_config
    from core.ontology import OntologyService

    svc = OntologyService(load_config())
    stats = svc.stats()
    check("ontology: operations>0", stats["operations"] > 0, str(stats))
    check("ontology: stages>0", stats["stages"] > 0, str(stats))
    check("ontology: params>0", stats["params"] > 0, str(stats))
    check("ontology: rdf lazy (csv-only)", "csv-only" in stats["rdf"], stats["rdf"])
    op = svc.operations()[0]
    check("ontology: операция имеет id/stage", bool(op.id and op.stage), op.id)


def test_assembler() -> None:
    from core.config import load_config
    from core.coordinator import Coordinator

    coord = Coordinator(load_config())
    nodes = coord.assembler("Герасимовское").node_genes()
    check("assembler: узлы собраны", len(nodes) > 0, str(len(nodes)))
    rules = coord.function_rules()
    funcs = [f.function for n in nodes for f in n.functions]
    with_rule = [f for f in funcs if rules.read(f) is not None]
    check("assembler: есть функции с шаблонами", len(with_rule) > 0, str(len(with_rule)))
    # pending_template функции допустимы (дорожная карта), но должны быть в онтологии
    check("assembler: полный пайплайн > 10 функций", len(funcs) > 10, str(len(funcs)))


def _renderable(coord):
    """Узлы/функции, для которых есть шаблоны (для рендера без pending)."""
    from copy import deepcopy
    rules = coord.function_rules()
    rule_map = {n: rules.read(n) for n in rules.all_names()}
    rule_map = {k: v for k, v in rule_map.items() if v}
    nodes = deepcopy(coord.assembler("Герасимовское").node_genes())
    for n in nodes:
        n.functions = [f for f in n.functions if rule_map.get(f.function)]
    nodes = [n for n in nodes if n.functions]
    return nodes, rule_map


def test_renderer() -> None:
    from core.config import load_config
    from core.coordinator import Coordinator

    coord = Coordinator(load_config())
    nodes, rule_map = _renderable(coord)
    text = coord.workflow_builder().build(nodes, rule_map)
    check("renderer: declare_workflow", "declare_workflow" in text)
    check("renderer: begin/end_wf_item", "begin_wf_item" in text and "end_wf_item" in text)
    check("renderer: api_version", "api_version=v0_0_300a" in text)
    check("renderer: есть вызов функции", "horizon_smooth" in text or "map_2d" in text)
    line = next((ln for ln in text.splitlines() if "begin_wf_item" in ln), "")
    check("renderer: отступ = 4", line.startswith("    begin_wf_item"), repr(line))


def test_metacritic() -> None:
    from domain.metacritic import MetaCritic, Verdict
    from core.ontology import ParamSpec, QaRule

    params = [ParamSpec(code="PORO", name="Пористость", data_type="float", unit="fraction",
                        typical_range="0.02..0.35", typical_error="", level="", domain="",
                        stage="", equipment="", node="")]
    rules = [QaRule(node="n", id="R1", rule_type="QAQCRule", stage="S1", condition="cond",
                    action="act", target="t", state="Не формализовано", source_row="1")]
    critic = MetaCritic(rules, params)
    ok = critic.evaluate({"PORO": 0.2})
    check("metacritic: UNKNOWN сохранён (правило)", ok.counts["unknown"] >= 1, str(ok.counts))
    check("metacritic: диапазон passed", ok.counts["passed"] == 1, str(ok.counts))
    bad = critic.evaluate({"PORO": 0.9})
    check("metacritic: диапазон failed", bad.verdict is Verdict.FAILED, bad.verdict.value)


def test_pipeline_and_project() -> None:
    from core.config import load_config
    from core.coordinator import Coordinator
    import tempfile

    coord = Coordinator(load_config())
    with tempfile.TemporaryDirectory() as tmp:
        report = coord.run("Герасимовское", run_dir=Path(tmp), execute=False)
    check("pipeline: шаги собраны", report["steps"]["total"] > 0, str(report["steps"]))
    check("pipeline: есть выполненные", report["steps"]["done"] > 0, str(report["steps"]))
    check("project: есть вариации", report["project"]["variants_total"] > 0,
          str(report["project"]["variants_total"]))
    check("project: есть объекты", len(report["objects"]) > 0, str(report["objects"]))


def test_grid_geometry_guard() -> None:
    """Контроль геометрии сетки: ловит вырождение Z (бланк карты irap → «иголка»)."""
    from core.coordinator import _GEOM_CALLS, check_grid_geometry

    good = {"nx": 250, "ny": 311, "nz": 22, "min_x": 63754.4589, "max_x": 76204.4589,
            "min_y": 304647.4523, "max_y": 319897.4523, "min_z": -2600.0, "max_z": -2100.0}
    check("geometry: корректная сетка без предупреждений",
          check_grid_geometry(good) is None, str(check_grid_geometry(good)))
    # фактический дефект из проекта: бланк карты (9999900) ушёл в Z горизонта
    bad = dict(good, min_z=-8620827.466, max_z=9871516.950)
    msg = check_grid_geometry(bad)
    check("geometry: вырожденный Z пойман", bool(msg) and "бланк" in (msg or ""), str(msg))
    thick = dict(good, min_z=-7000.0, max_z=-1000.0)
    check("geometry: нереальная мощность поймана", bool(check_grid_geometry(thick)),
          str(check_grid_geometry(thick)))
    check("geometry: пустая геометрия не падает", check_grid_geometry(None) is None, "None")
    check("geometry: методы API заданы (9 шт.)", len(_GEOM_CALLS) == 9, str(_GEOM_CALLS))


def test_trajectory_dogleg_fix() -> None:
    """Минимальная кривизна: шум азимута у вертикальной скважины не раздувает XYZ.

    Прежняя формула с `cos I₁·cos I₂` давала фиктивный доглег ≈ ΔA (азимут при I≈0
    произволен) и разлёт XYZ в десятки раз больше MD — тНав отвечал предупреждением
    «MD length of some trajectory segments is smaller than the corresponding XYZ
    length», а маркеры уезжали по глубине.
    """
    from domain.trajectories import _enforce_md_ge_xyz, _min_curvature

    # Вертикальная скважина с «скачущим» азимутом (типовой шум инклинометрии).
    stations = [(0.0, 0.1, 251.7), (10.0, 0.2, 69.8), (20.0, 0.1, 180.0)]
    rows = _min_curvature(stations, 70000.0, 310000.0, 114.5)
    dz = rows[0][3] - rows[-1][3]              # у вертикали |ΔZ| ≈ MD
    check("trajectory: вертикаль не разлетается по Z", abs(dz - 20.0) < 0.05,
          f"dz={dz:.2f} (ожидалось ~20)")

    # Инвариант тНава на ЗАПИСЫВАЕМЫХ (округлённых) значениях: MD-шаг >= |ΔXYZ|.
    rows = _enforce_md_ge_xyz(_min_curvature(stations, 70000.0, 310000.0, 114.5))
    rounded = [(round(r[0], 4), round(r[1], 4), round(r[2], 4), round(r[3], 4)) for r in rows]
    worst = 0.0
    for a, b in zip(rounded, rounded[1:]):
        dmd = b[0] - a[0]
        if dmd > 0:
            worst = max(worst, math.dist(b[1:], a[1:]) / dmd)
    check("trajectory: MD >= |ΔXYZ| после округления", worst <= 1.0001, f"worst={worst:.6f}")
    check("trajectory: MD монотонен и начинается с 0",
          rounded[0][0] == 0.0 and all(b[0] > a[0] for a, b in zip(rounded, rounded[1:])),
          str(rounded[:2]))


def test_marker_well_normalization() -> None:
    """Отбивки: имена скважин приводятся к именам проекта (регистр), сироты отброшены."""
    from domain.welltops import normalize_marker_wells

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Welltop.txt"
        path.write_text("10g\tBAJ\t2500.0\n10G\tJ2\t2600.0\nNOPE\tBAJ\t100.0\n",
                        encoding="utf-8")
        res = normalize_marker_wells(path, {"10G", "11G"})
        text = path.read_text(encoding="utf-8")
    check("markers: регистр приведён к имени проекта", "10G\tBAJ" in text, text)
    check("markers: чужая скважина отброшена", "NOPE" not in text, text)
    check("markers: осиротевшие перечислены", res["unknown_wells"] == ["NOPE"], str(res))
    check("markers: сохранились обе строки своей скважины", res["kept"] == 2, str(res))


def main() -> int:
    for fn in (test_ontology, test_assembler, test_renderer, test_metacritic,
               test_pipeline_and_project, test_grid_geometry_guard,
               test_trajectory_dogleg_fix, test_marker_well_normalization):
        try:
            fn()
        except Exception as exc:              # noqa: BLE001
            check(f"{fn.__name__}: без исключений", False, repr(exc))
    print("\n=== ИТОГ ===")
    print(f"пройдено: {len(_PASS)} | провалено: {len(_FAIL)}")
    if _FAIL:
        print("Проваленные:", ", ".join(_FAIL))
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
