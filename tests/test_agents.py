"""Тесты агентного слоя (Срез A): реестр BDI, контракты, карта этапов, политики гейтов.

Запуск: python tests/test_agents.py (из папки orchestrator/).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from agents.checks import CheckRegistry  # noqa: E402
from agents.contracts import (AWAITING, BYPASSED, FAILED, PASSED, PENDING, SKIPPED,  # noqa: E402
                              WAIVED, Finding, GateVerdict, HandoffMemo, load_json,
                              run_verdict, save_json, sha256_file, sha256_text)
from agents.evidence import build_static, check_context  # noqa: E402
from agents.gates import GateEngine, ON_EXHAUSTED_MODES  # noqa: E402
from agents.registry import AgentRegistry  # noqa: E402
from agents.stage_map import assignments  # noqa: E402
from core.config import load_config  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    cond = bool(cond)
    results.append((name, cond, detail))
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" +
          (f" — {detail}" if detail and not cond else ""))


# -- реестр BDI ---------------------------------------------------------------
def test_registry() -> None:
    reg = AgentRegistry(load_config())
    check("registry: BDI доступен", reg.available, str(reg.bdi_dir))
    profiles = reg.profiles()
    check("registry: >=22 профиля", len(profiles) >= 22, f"профилей {len(profiles)}")
    structural = reg.profile("AG_STRUCTURAL")
    check("registry: AG_STRUCTURAL со стадией S07",
          structural is not None and "S07" in structural.stages)
    handoffs = reg.handoffs()
    check("registry: >=17 handoff-контрактов", len(handoffs) >= 17,
          f"контрактов {len(handoffs)}")
    h = reg.handoff("S07", "S08")
    check("registry: S07→S08 ведёт к AG_PETROPHYSICS",
          h is not None and h.to_agent == "AG_PETROPHYSICS")
    check("registry: обязательства контракта читаются",
          h is not None and any("evidence hash" in r for r in h.required))
    check("registry: решения BDI читаются (>0)", len(reg.decisions()) > 0)


def test_registry_degraded() -> None:
    reg = AgentRegistry(bdi_dir=Path("no") / "such" / "dir")
    check("registry: деградация без каталога", (not reg.available) and reg.profiles() == [])
    reg_none = AgentRegistry()
    check("registry: без cfg/каталога — деградация", not reg_none.available,
          str(reg_none.stats()))


# -- контракты ----------------------------------------------------------------
def test_contracts() -> None:
    memo = HandoffMemo(id="H1", handoff_id="HANDOFF_S07_S08", from_agent="AG_STRUCTURAL",
                       to_agent="AG_PETROPHYSICS", from_stage="S07", to_stage="S08",
                       verdict=PASSED,
                       artifact_revisions=[{"path": "wf.py", "sha256": "ab"}],
                       lineage=["S07"], qa={"passed": 10}, evidence_hash=sha256_text("wf"))
    payload = memo.to_dict()
    check("contracts: HandoffMemo сериализуется",
          payload["verdict"] == PASSED and payload["to_agent"] == "AG_PETROPHYSICS")
    check("contracts: evidence hash детерминирован",
          sha256_text("x") == sha256_text("x") and len(sha256_text("x")) == 64)
    check("contracts: degraded-поля присутствуют",
          payload["degraded"] is False and payload["bypass_reason"] == ""
          and payload["unresolved_findings"] == [])
    check("contracts: итоговый вердикт прогона",
          run_verdict([PASSED]) == "passed"
          and run_verdict([PASSED, BYPASSED]) == "passed_with_degradation"
          and run_verdict([FAILED]) == "halted"
          and run_verdict([AWAITING]) == "awaiting_decision"
          and run_verdict([PENDING]) == "pending_execution")


# -- карта этапов ----------------------------------------------------------------
def test_stage_map() -> None:
    cfg = load_config()
    reg = AgentRegistry(cfg)
    graph = yaml.safe_load((ROOT / "ontology_project" / "gerasimovskoe.yaml")
                           .read_text(encoding="utf-8"))
    asg, issues = assignments(graph, cfg, reg)
    check("stage_map: 12 этапов (0…10 + 6.1 геотела, фации включены)", len(asg) == 12,
          f"назначено {len(asg)}")
    by_gate = {a.gate_id: a for a in asg}
    check("stage_map: гейты проекта — все 8 (включая G-FACIES)",
          set(by_gate) == {"G-DATA", "G-STRUCT", "G-GRID", "G-FACIES",
                           "G-PETRO", "G-SAT", "G-VOL", "G-MAPS"},
          str(sorted(by_gate)))
    facies = by_gate.get("G-FACIES")
    check("stage_map: фации (номер 6) → AG_FACIES",
          facies is not None and facies.agent_id == "AG_FACIES"
          and facies.stage_no == 6, str(facies))
    struct = [a for a in asg if a.gate_id == "G-STRUCT"]
    check("stage_map: этапы 1–3 → AG_STRUCTURAL",
          len(struct) == 3 and {a.stage_no for a in struct} == {1, 2, 3}
          and all(a.agent_id == "AG_STRUCTURAL" for a in struct),
          str([(a.stage_no, a.agent_id) for a in struct]))
    check("stage_map: петрофизика (номер 7) → AG_PETROPHYSICS",
          by_gate["G-PETRO"].agent_id == "AG_PETROPHYSICS" and by_gate["G-PETRO"].stage_no == 7)
    check("stage_map: все этапы с агентом, issues пусты", not issues, "; ".join(issues))

    g2 = {"pipeline": [{"stage": "0. X", "agent": "AG_DATA_STEWARD"}, {"stage": "1. Y"}]}
    asg2, _ = assignments(g2, cfg, reg)
    check("stage_map: agent: в YAML переопределяет (source=yaml)",
          asg2[0].source == "yaml" and asg2[0].agent_id == "AG_DATA_STEWARD")

    g3 = {"pipeline": [{"stage": f"{i}. s"} for i in range(12)]}
    _, issues3 = assignments(g3, cfg, reg)
    check("stage_map: этап вне карты → issue",
          any("этап 11" in i for i in issues3), "; ".join(issues3))


# -- гейты ---------------------------------------------------------------------
def test_gates() -> None:
    cfg = load_config()
    eng = GateEngine(cfg)
    specs = eng.specs()
    check("gates: 8 гейтов из config", len(specs) == 8, f"гейтов {len(specs)}")
    spec = eng.spec("G-STRUCT")
    check("gates: G-STRUCT покрывает этапы 1–3",
          spec is not None and spec.stages == (1, 2, 3))
    check("gates: evidence из данных (well_tie)",
          bool(spec.evidence) and spec.evidence[0].get("kind") == "well_tie",
          str(spec.evidence))
    check("gates: fallback-цепочка без config", len(GateEngine(None).specs()) == 8)

    ok = eng.evaluate(spec, [Finding("s1", "critical", True, title="посадка")])
    check("gates: все проверки пройдены → passed", ok.status == PASSED)
    bad = eng.evaluate(spec, [Finding("s1", "critical", False, title="посадка")])
    check("gates: critical fail → failed", bad.status == FAILED)
    minor = eng.evaluate(spec, [Finding("s2", "minor", False, title="мелочь")])
    check("gates: minor не валит вердикт", minor.status == PASSED)
    phys = eng.evaluate(spec, [Finding("s3", "major", True)], metrics={"physical": False})
    check("gates: физичность обязательна", phys.status == FAILED)

    status, _ = eng.exhaust(spec, bad)
    check("gates: исчерпание best → bypassed", status == BYPASSED)
    status_f, _ = eng.exhaust(eng.spec("G-FACIES"), bad)
    check("gates: исчерпание фаций skip → skipped", status_f == SKIPPED)
    status_ask, _ = eng.exhaust(spec, bad, override_mode="ask")
    check("gates: режим ask → awaiting_decision", status_ask == AWAITING)

    cfg_off = load_config()
    cfg_off.set("execution.gate_bypass", False)
    status_h, _ = GateEngine(cfg_off).exhaust(spec, bad)
    check("gates: тумблер gate_bypass=false → halt", status_h == FAILED)

    waived = eng.apply_decision(bad, "waiver", author="test", comment="принято")
    check("gates: waiver оператора", waived.status == WAIVED and waived.decider == "operator")
    skipped = eng.apply_decision(bad, "skip", author="test", comment="")
    check("gates: решение оператора skip", skipped.status == SKIPPED)
    check("gates: режимы ограничены",
          set(ON_EXHAUSTED_MODES) == {"best", "skip", "halt", "ask"})


# -- проверки и свидетельства -----------------------------------------------------
def test_checks_and_evidence() -> None:
    cfg = load_config()
    project = yaml.safe_load((ROOT / "ontology_project" / "gerasimovskoe.yaml")
                             .read_text(encoding="utf-8"))
    src = ROOT / "data" / "Герасимовское" / "Source"
    ev = build_static(project, src, cfg=cfg)
    ctx = check_context(project, cfg)
    reg = CheckRegistry()

    # Число проверок — НЕ константа: реестр расширяется (F-19 и оцифровка чеклиста).
    # Проверяем состав: реестр собран, счётчик согласован, оба источника на месте.
    stats = reg.stats()
    check("checks: реестр собран и счётчик согласован",
          stats["total"] >= 21 and stats["total"] == len(reg.all())
          and stats.get("by_source", {}).get("builtin", 0) > 0,
          str(stats))
    check("checks: свидетельства из данных",
          bool(ev.get("welltops")) and bool(ev.get("maps")) and bool(ev.get("box")))

    g_data = reg.run("G-DATA", ev, ctx)
    check("checks: G-DATA без критических провалов",
          all(f.passed for f in g_data if f.severity == "critical"),
          "; ".join(f.id for f in g_data if not f.passed))
    check("checks: G-DATA выполнились (>=3)", len(g_data) >= 3, str([f.id for f in g_data]))

    bad_blank = [f for f in reg.run(
        "G-DATA", {"maps": [{"path": "m.irap", "total": 100, "blank": 99}]},
        {"map_blank_max": 0.95}) if f.id == "data.map_blank"]
    check("checks: бланк 99% ловится", bool(bad_blank) and not bad_blank[0].passed)
    skipped = reg.run("G-DATA", {"maps": [{"path": "m.irap", "total": 100, "blank": 99}]}, {})
    check("checks: без порога — not_applicable (не штрафует)",
          not any(f.id == "data.map_blank" for f in skipped))

    bad_order = [f for f in reg.run(
        "G-DATA", {"welltops": {"1": [("A", 100.0), ("B", 50.0)]}},
        {"marker_order": ["A", "B"]}) if f.id == "data.markers_order"]
    check("checks: инверсия маркеров ловится", bool(bad_order) and not bad_order[0].passed)

    tie_ok = [f for f in reg.run(
        "G-STRUCT", {"well_tie": [(0.0, 4.0), (0.0, 5.0), (0.0, 3.0)]},
        {"well_tie_median_m": 10.0}) if f.id == "struct.well_tie"]
    check("checks: well-tie в допуске", bool(tie_ok) and tie_ok[0].passed)
    tie_bad = [f for f in reg.run(
        "G-STRUCT", {"well_tie": [(0.0, 50.0)]},
        {"well_tie_median_m": 10.0}) if f.id == "struct.well_tie"]
    check("checks: well-tie вне допуска ловится", bool(tie_bad) and not tie_bad[0].passed)

    rmse_ok = [f for f in reg.run(
        "G-STRUCT", {"well_tie": [(0.0, 4.0), (0.0, 3.0)]},
        {"well_tie_rmse_m": 10.0}) if f.id == "struct.well_tie_rmse"]
    check("checks: RMSE сходимости в допуске",
          bool(rmse_ok) and rmse_ok[0].passed
          and abs(rmse_ok[0].evidence["rmse_m"] - 3.5355339059327378) < 1e-6,
          str(rmse_ok[0].evidence if rmse_ok else {}))
    rmse_bad = [f for f in reg.run(
        "G-STRUCT", {"well_tie": [(0.0, 50.0), (0.0, 30.0)]},
        {"well_tie_rmse_m": 10.0}) if f.id == "struct.well_tie_rmse"]
    check("checks: RMSE вне допуска ловится", bool(rmse_bad) and not rmse_bad[0].passed,
          str(rmse_bad[0].evidence if rmse_bad else {}))
    rmse_na = reg.run("G-STRUCT", {"well_tie": [(0.0, 4.0)]}, {"well_tie_median_m": 10.0})
    check("checks: RMSE без порога — не штрафует",
          not any(f.id == "struct.well_tie_rmse" for f in rmse_na))

    grid_ok = [f for f in reg.run(
        "G-GRID", {"grid": {"nx": 250, "ny": 311, "nz": 22,
                              "min_z": -2529.8, "max_z": -2360.3}})
        if f.id == "grid.geometry"]
    check("checks: геометрия сетки проходит", bool(grid_ok) and grid_ok[0].passed)
    grid_bad = [f for f in reg.run(
        "G-GRID", {"grid": {"nx": 250, "ny": 311, "nz": 22,
                               "min_z": 0.0, "max_z": 9.0e6}})
        if f.id == "grid.geometry"]
    check("checks: вырожденный Z ловится", bool(grid_bad) and not grid_bad[0].passed)

    facies_ok = [f for f in reg.run(
        "G-FACIES", {"facies_policy": {"n_facies": 3, "method": "sis"}},
        {"facies_methods": ["sis"]}) if f.id == "facies.policy"]
    check("checks: политика фаций в допуске → passed",
          bool(facies_ok) and facies_ok[0].passed,
          str(facies_ok[0].message if facies_ok else "нет находки"))
    facies_bad = [f for f in reg.run(
        "G-FACIES", {"facies_policy": {"n_facies": 0, "method": "kriging"}},
        {"facies_methods": ["sis"]}) if f.id == "facies.policy"]
    check("checks: политика фаций вне набора → failed",
          bool(facies_bad) and not facies_bad[0].passed)
    check("checks: политика фаций без данных → not_applicable",
          not any(f.id == "facies.policy" for f in reg.run("G-FACIES", {}, {})))

    # качество сетки (G-GRID): физичность ячеек и сверка числа ячеек с боксом/шагом
    geom_q = {"nx": 250, "ny": 311, "nz": 22, "min_x": 0.0, "max_x": 12500.0,
              "min_y": 0.0, "max_y": 15550.0, "min_z": -2529.8, "max_z": -2360.3}
    lim_q = {"grid_max_aspect_ratio": 200.0, "grid_max_xy_ratio": 20.0,
             "grid_max_cells": 20000000}
    gq_ok = [f for f in reg.run("G-GRID", {"grid": geom_q}, lim_q)
             if f.id == "grid.quality"]
    check("checks: качество сетки в норме → passed",
          bool(gq_ok) and gq_ok[0].passed, str(gq_ok[0].message if gq_ok else "нет"))
    geom_blin = dict(geom_q, min_z=-2529.8, max_z=-2527.6)   # dz≈0.1 м → «блин»
    gq_bad = [f for f in reg.run("G-GRID", {"grid": geom_blin}, lim_q)
              if f.id == "grid.quality"]
    check("checks: ячейка-«блин» ловится (aspect ratio)",
          bool(gq_bad) and not gq_bad[0].passed, str(gq_bad[0].message if gq_bad else "нет"))
    gq_exp = [f for f in reg.run(
        "G-GRID", {"grid": geom_q, "grid_policy": {"expected_nx": 300, "expected_ny": 311}},
        {"grid_count_tol_cells": 2}) if f.id == "grid.quality"]
    check("checks: nx ≠ ожидаемого из бокса/шага ловится",
          bool(gq_exp) and not gq_exp[0].passed and "nx" in gq_exp[0].message,
          str(gq_exp[0].message if gq_exp else "нет"))
    check("checks: качество сетки без порогов/данных → not_applicable",
          reg.run("G-GRID", {"grid": geom_q}, {}) == []
          or not any(f.id == "grid.quality" for f in reg.run("G-GRID", {"grid": geom_q}, {})))

    # фации со структурой (G-FACIES): вариограмма vs сетка
    fs_ev = {"facies_policy": {"n_facies": 3,
                               "variogram": {"range_m": 3500.0, "nugget": 0.15,
                                             "anisotropy": 0.1}},
             "grid_policy": {"step": {"step_x": 50.0, "step_y": 50.0}}}
    fs_ok = [f for f in reg.run("G-FACIES", fs_ev, {"facies_min_classes": 2})
             if f.id == "facies.structure"]
    check("checks: фации согласованы со структурой → passed",
          bool(fs_ok) and fs_ok[0].passed, str(fs_ok[0].message if fs_ok else "нет"))
    fs_bad = [f for f in reg.run(
        "G-FACIES", {"facies_policy": {"n_facies": 1,
                                       "variogram": {"range_m": 30.0, "nugget": 1.5,
                                                     "anisotropy": 2.0}},
                     "grid_policy": {"step": {"step_x": 50.0, "step_y": 50.0}}},
        {"facies_min_classes": 2}) if f.id == "facies.structure"]
    check("checks: несогласованная вариограмма фаций ловится",
          bool(fs_bad) and not fs_bad[0].passed, str(fs_bad[0].message if fs_bad else "нет"))
    check("checks: фации без данных → not_applicable",
          not any(f.id == "facies.structure" for f in reg.run("G-FACIES", {}, {})))

    memo_bad = reg.run("G-STRUCT", {"handoff": {"evidence_hash": "",
                                                  "artifact_revisions": [],
                                                  "qa": {}, "units_crs": None}})
    failed = {f.id for f in memo_bad if not f.passed}
    check("checks: контракт ловит неполный меморандум",
          {"contract.evidence_hash", "contract.revisions",
           "contract.qa", "contract.units"} <= failed, str(sorted(failed)))

    only_static = reg.run("G-VOL", {"stoiip": -5.0}, include_runtime=False)
    check("checks: dry-run пропускает runtime",
          not any(f.id == "vol.stoiip" for f in only_static))

    foreign = [f for f in reg.run("G-STRUCT", {"workflow_text": "x Litho3D y"},
                                  {"foreign_tokens": ["Litho3D", "zone_id"]})
               if f.id == "contract.foreign_tokens"]
    check("checks: чужой токен в рендере ловится",
          bool(foreign) and not foreign[0].passed)


# -- адаптеры пакета QA/QC и диапазонов --------------------------------------------
def test_package_adapter() -> None:
    import agents.checks.adapters as ad
    from agents.checks.adapters import package_evaluate
    from domain.qaqc_adapter import package_available

    crafted = {"values": [1.0, 2.0, 3.0, 4.0, 5.0], "X": [1, 2, 3, 4, 5],
               "observed": [0.0, 1.0, 2.0], "model": [0.0, 1.0, 3.0],
               "D_bottom": [200.0, 300.0], "D_top": [150.0, 190.0],
               "D_mod": [1.0], "D_calc": [1.0],
               "H_well": [10.0, 12.0], "H_topo": [10.5, 11.0]}
    saved = ad._qaqc_evaluate
    try:
        ad._qaqc_evaluate = None                 # деградация: пакет недоступен
        f0, m0 = package_evaluate(["02"], crafted)
        check("adapter: без пакета — деградация (не штрафует)", f0 == [] and m0 == {})
    finally:
        ad._qaqc_evaluate = saved
    if not package_available():
        return
    findings, metrics = package_evaluate(["02"], crafted)
    failed = [f for f in findings if not f.passed]
    check("adapter: пакет применяется (findings + metrics)",
          len(findings) >= 2 and metrics.get("physical") is False
          and metrics.get("kc", 0) > 0, str(metrics))
    check("adapter: серьёзность из значимости пакета",
          any(f.severity == "critical" for f in failed)
          and any(f.severity == "major" for f in failed))
    check("adapter: агрегат по блоку", any(f.id.startswith("package.") for f in findings))
    empty, m2 = package_evaluate(["02"], {})
    check("adapter: нет значений → не применяется", empty == [] and m2 == {})


def test_range_adapter() -> None:
    from agents.checks.adapters import range_findings
    from core.ontology import ParamSpec
    from domain.metacritic import MetaCritic

    spec = ParamSpec(code="PORO", name="Пористость", data_type="float", unit="д.ед.",
                     typical_range="0.02..0.35", typical_error="0.03", level="",
                     domain="", stage="", equipment="", node="")
    critic = MetaCritic([], [spec])
    bad = range_findings(critic, {"PORO": 0.99})
    good = range_findings(critic, {"PORO": 0.2})
    check("range: вне диапазона ловится", len(bad) == 1 and not bad[0].passed, str(bad))
    check("range: в диапазоне — тихо", good == [])


def test_remediation_candidates() -> None:
    from core.coordinator import Coordinator
    from agents.runner import StageRunner

    coord = Coordinator(load_config(), dry_run=True)
    graph = coord.project_graph("Герасимовское")
    nodes = coord.assembler("Герасимовское").node_genes()
    node = next((n for n in nodes if "Структурные поверхности" in str(n.stage)), None)
    runner = StageRunner(coord)
    spec = runner.engine.spec("G-STRUCT")
    cands = runner._remediation_candidates(graph, node, spec)
    check("rework: кандидаты из variations (структурный этап)",
          bool(cands) and any("horizon_smooth" in c for c in cands), str(cands[:2]))
    check("rework: без узла — пусто",
          runner._remediation_candidates(graph, None, spec) == [])


def test_advisor_offline() -> None:
    from agents.advisor import StageAdvisor

    cfg = load_config()
    cfg.set("llm.api_key", "")
    cfg.set("llm.enabled", False)
    advisor = StageAdvisor(cfg)
    note = advisor.explain(agent_id="AG_STRUCTURAL", stage_key="стр", gate_id="G-STRUCT",
                           status="failed", findings=[Finding("x", "critical", False)])
    check("advisor: без ключа молчит (без сети)", (not advisor.enabled) and note == "")


# -- staged-прогон (dry-run) --------------------------------------------------------
def test_staged_runner_dry_run() -> None:
    import tempfile

    from core.coordinator import Coordinator

    coord = Coordinator(load_config(), dry_run=True)
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / "run"
        report = coord.run("Герасимовское", run_dir=run_dir, execute=False)
        agents = report.get("agents") or {}
        stages = agents.get("stages") or []
        stage_files = sorted((run_dir / "agents" / "stages").glob("*.py"))
        gate_files = sorted((run_dir / "agents" / "gates").glob("*.json"))
        handoff_files = sorted((run_dir / "agents" / "handoffs").glob("*.json"))
        progress = load_json(run_dir / "agents" / "progress.json")
        memo1 = load_json(run_dir / "agents" / "handoffs" / "01_G-STRUCT.json")
    check("staged: 12 этапов обработано", len(stages) == 12, str(len(stages)))
    check("staged: G-DATA passed, runtime-гейты pending",
          any(s["gate"] == "G-DATA" and s["status"] == "passed" for s in stages)
          and any(s["status"] == "pending_execution" for s in stages),
          str([(s["gate"], s["status"]) for s in stages]))
    check("staged: passed не маскирует незакрытые находки",
          all(s["status"] != "passed" or not s["findings"] for s in stages),
          str([(s["gate"], s["status"], [f["id"] for f in s["findings"]])
               for s in stages if s["status"] == "passed" and s["findings"]]))
    check("staged: файлы этапов созданы", len(stage_files) == 12, str(len(stage_files)))
    check("staged: вердикты и меморандумы записаны",
          len(gate_files) == 8 and len(handoff_files) == 12,
          f"gates={len(gate_files)} handoffs={len(handoff_files)}")
    check("staged: итоговый вердикт прогона",
          agents.get("verdict") == "pending_execution", str(agents.get("verdict")))
    check("staged: steps сохранены", report["steps"]["total"] > 0, str(report["steps"]))
    check("staged: прогресс хранит назначения/гейты/меморандумы",
          len((progress.get("agents") or {}).get("assignments") or []) == 12
          and len((progress.get("agents") or {}).get("gates") or []) == 8
          and len(progress.get("handoffs") or []) == 12,
          str({k: len((progress.get("agents") or {}).get(k) or [])
               for k in ("assignments", "gates")}))
    check("staged: меморандум несёт знания о передаче",
          bool(memo1.get("from_agent")) and bool(memo1.get("to_agent"))
          and str(memo1.get("handoff_id") or "").startswith("HANDOFF")
          and len(str(memo1.get("evidence_hash") or "")) == 64
          and bool(memo1.get("artifact_revisions")), str(sorted(memo1)))
    check("staged: решение структурного агента в отчёте",
          bool((report.get("structural") or {}).get("erosion")),
          str(report.get("structural")))
    check("staged: решения агентов сетки и фаций в отчёте",
          bool((report.get("grid_policy") or {}).get("grid_function"))
          and (report.get("facies_policy") or {}).get("enabled") is True,
          str({"grid": report.get("grid_policy"), "facies": report.get("facies_policy")}))


def test_structure_policy() -> None:
    """Структурный агент сам решает, на каком пласте работает и нужен ли «врез».

    Решение детерминированное (без LLM): покрытие кровли отбивками против порога;
    оператор может принудительно включить/выключить; нет данных — врез не строится.
    """
    from agents.structure_policy import decide_erosion

    base = {"structural": {
        "interval_top_marker": "BAJ", "interval_base_marker": "J2",
        "erosion": "auto",
        "erosion_steps": ["map_2d_calculator", "polygon_create_by_map_intersection"],
        "erosion_when_top_coverage_lt": 1.0}}
    full = {"welltops": {"w1": [("BAJ", 100.0), ("J2", 120.0)],
                         "w2": [("BAJ", 105.0), ("J1(1+2)", 112.0)]}}
    d = decide_erosion(base, full)
    check("policy: полное покрытие → врез не нужен",
          d["enabled"] is False and d["coverage"] == 1.0, str(d))
    check("policy: рабочий интервал определён по данным",
          d["top_marker"] == "BAJ" and d["base_marker"] == "J2"
          and d["steps"] == ["map_2d_calculator", "polygon_create_by_map_intersection"])
    partial = {"welltops": {"w1": [("BAJ", 100.0)],
                            "w2": [("J1(1+2)", 112.0)]}}
    d2 = decide_erosion(base, partial)
    check("policy: неполное покрытие → врез строится",
          d2["enabled"] is True and d2["coverage"] == 0.5
          and "размыт" in d2["reason"], str(d2))
    lo_th = dict(base)
    lo_th["structural"] = dict(base["structural"], erosion_when_top_coverage_lt=0.5)
    check("policy: порог 0.5 при покрытии 0.5 → врез не нужен",
          decide_erosion(lo_th, partial)["enabled"] is False)
    forced_on = dict(base)
    forced_on["structural"] = dict(base["structural"], erosion="on")
    forced_off = dict(base)
    forced_off["structural"] = dict(base["structural"], erosion="off")
    check("policy: оператор принудительно включает/выключает врез",
          decide_erosion(forced_on, full)["enabled"] is True
          and decide_erosion(forced_off, full)["enabled"] is False)
    d4 = decide_erosion(base, {"welltops": {}})
    check("policy: нет отбивок → врез не строится (неизвестное != ложь)",
          d4["enabled"] is False and d4["coverage"] is None, str(d4))
    check("policy: нет секции structural → врез не строится",
          decide_erosion({}, full)["enabled"] is False)
    check("policy: неправильный порог → дефолт 1.0 (осторожно: строить)",
          (lambda p: p["enabled"] is True and "50%" in p["reason"])(
              decide_erosion(dict(base, structural=dict(
                  base["structural"], erosion_when_top_coverage_lt="нет")), partial)))


def test_policy_agents() -> None:
    """Базовый класс агентов и доменные агенты сетки/фаций (решения по данным)."""
    from agents.base_agent import BaseAgent
    from agents.facies_policy import FaciesAgent, decide_facies
    from agents.grid_policy import GridAgent, decide_grid
    from agents.structure_policy import StructureAgent

    for cls in (StructureAgent, GridAgent, FaciesAgent):
        check(f"agents: {cls.__name__} — наследник BaseAgent с agent_id",
              issubclass(cls, BaseAgent) and bool(cls.agent_id))

    raised = False
    try:
        BaseAgent().decision({}, {})
    except NotImplementedError:
        raised = True
    check("agents: BaseAgent.decision абстрактен", raised)
    check("agents: StructureAgent.agent_id — из онтологии",
          StructureAgent.agent_id == "AG_STRUCTURAL"
          and GridAgent.agent_id == "AG_GRID_VOLUMETRICS"
          and FaciesAgent.agent_id == "AG_FACIES")

    project = yaml.safe_load((ROOT / "ontology_project" / "gerasimovskoe.yaml")
                             .read_text(encoding="utf-8"))

    # сетка: бокс выводится из EXTENT структурной карты (данные свидетельства)
    extent_ev = {"maps": [{"extent": {"x0": 100.0, "x1": 1100.0,
                                      "y0": 200.0, "y1": 2200.0}}]}
    gd = decide_grid(project, extent_ev)
    fn = gd.get("grid_function")
    box = (gd.get("parameters") or {}).get(fn) or {}
    check("grid: бокс из extent карты (данные)",
          gd["enabled"] is True and fn == "grid_3d_create_by_horizons"
          and box.get("min_x") == 100.0 and box.get("length_x") == 1000.0
          and box.get("length_y") == 2000.0, str(gd))
    nodata = decide_grid(project, {})
    check("grid: без карты бокс не навязывается (неизвестное != ложь)",
          nodata["enabled"] is False and not nodata["box"], str(nodata))
    check("grid: агент находит шаг сетки по объекту Grid3d",
          fn == "grid_3d_create_by_horizons")
    check("grid: ожидаемые nx/ny = round(length/step) из бокса и шага",
          gd.get("expected_nx") == 20 and gd.get("expected_ny") == 40, str(gd))
    check("grid: без бокса ожидаемые nx/ny не выводятся",
          "expected_nx" not in nodata and "expected_ny" not in nodata, str(nodata))

    # фации: метод/классы/вариограмма — из секции geostat (данные)
    fd = decide_facies(project, {})
    check("facies: метод и число классов из данных",
          fd["enabled"] is True and fd["n_facies"] == 3
          and fd["method"] == "sis", str(fd))
    check("facies: вариограмма из данных проекта",
          fd["variogram"]["range_m"] == 3500.0
          and fd["variogram"]["nugget"] == 0.15, str(fd["variogram"]))
    check("facies: нет n_facies → стадия отключается",
          decide_facies({"geostat": {}}, {})["enabled"] is False)



def test_staged_skip_erosion_steps() -> None:
    """Шаги вреза пропускаются решением агента (skipped_by_policy) и не рендерятся."""
    import tempfile

    import agents.runner as runner_mod
    from core.coordinator import Coordinator

    coord = Coordinator(load_config(), dry_run=True)
    disabled = {"enabled": False, "reason": "тест: врез не требуется (покрытие >= порога)",
                "coverage": 1.0, "top_marker": "BAJ", "base_marker": "J2",
                "mode": "auto",
                "steps": ["polygon_create_by_map_intersection"]}
    original = runner_mod.decide_erosion
    runner_mod.decide_erosion = lambda graph, ev: dict(disabled)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            report = coord.run("Герасимовское", run_dir=run_dir, execute=False)
            progress = load_json(run_dir / "agents" / "progress.json")
            steps = (progress.get("steps") or {}).get("steps") or []
            skipped = [s for s in steps if s.get("status") == "skipped_by_policy"]
            wf01 = (run_dir / "agents" / "stages" / "01_G_STRUCT.py").read_text(
                encoding="utf-8", errors="replace")
            wf02 = (run_dir / "agents" / "stages" / "02_G_STRUCT.py").read_text(
                encoding="utf-8", errors="replace")
            wf03 = (run_dir / "agents" / "stages" / "03_G_STRUCT.py").read_text(
                encoding="utf-8", errors="replace")
    finally:
        runner_mod.decide_erosion = original

    check("staged-skip: решение агента в отчёте прогона",
          ((report.get("structural") or {}).get("erosion") or {}).get("enabled") is False,
          str(report.get("structural")))
    # Пропусков может быть БОЛЬШЕ одного: кроме вреза, данные могут объявить
    # неподтверждённые пробой шаги (workflow.unconfirmed_steps) и шаги с
    # отсутствующим объектом-предпосылкой (requires_object) — это правило 6/8.
    skipped_fns = {s.get("function") for s in skipped}
    check("staged-skip: шаг вреза пропущен по решению агента",
          "polygon_create_by_map_intersection" in skipped_fns,
          str(sorted(skipped_fns)))
    check("staged-skip: у каждого пропуска есть причина в шине",
          bool(skipped) and all(str(s.get("message") or "").strip() for s in skipped),
          str([(s.get("function"), s.get("message")) for s in skipped]))
    # После переупорядочивания: index 1 = структурные поверхности, 2 = толщины, 3 = полигон.
    check("staged-skip: структурные поверхности отрендерены",
          "horizon_interpolate_by_marker_idw" in wf01 and "horizon_smooth" in wf01)
    check("staged-skip: толщина отрендерена (Tl_thick в wf02)",
          "Tl_thick" in wf02)
    check("staged-skip: полигон вреза не рендерится",
          "polygon_create_by_map_intersection" not in wf03)
    check("staged-skip: прочие шаги этапов отрендерены (толщина из горизонтов)",
          "map_2d_calculator" in wf02)


# -- решения оператора и политики гейтов ---------------------------------------
def test_decision_broker() -> None:
    import threading
    import time as _time

    from agents.decisions import DecisionBroker

    broker = DecisionBroker(timeout_sec=2.0)
    out: dict = {}

    def waiter() -> None:
        out["decision"] = broker.request("run1", "G-STRUCT", {"status": "failed"})

    thread = threading.Thread(target=waiter)
    thread.start()
    deadline = _time.time() + 2.0
    while not broker.pending() and _time.time() < deadline:
        _time.sleep(0.01)
    check("broker: запрос виден в pending", bool(broker.pending()))
    ok = broker.resolve("run1", "G-STRUCT", "best", author="tester", comment="ок")
    thread.join(timeout=2.0)
    check("broker: решение доставлено",
          ok and (out.get("decision") or {}).get("action") == "best")
    check("broker: журнал решений", any(d.get("author") == "tester" for d in broker.log()))
    check("broker: повторное решение отклонено",
          broker.resolve("run1", "G-STRUCT", "halt") is False)

    timeout_broker = DecisionBroker(timeout_sec=0.05)
    started = _time.time()
    res = timeout_broker.request("run2", "G-STRUCT", {})
    check("broker: таймаут без решения", res is None and (_time.time() - started) < 2.0)


def test_gate_policies() -> None:
    from agents.gates import policies, update_policies

    cfg = load_config()
    snap0 = policies(cfg)
    check("policies: снимок для интерфейса",
          snap0["bypass_enabled"] is True and len(snap0["gates"]) == 8)
    update_policies(cfg, {"gate_bypass": False,
                          "gates": {"G-FACIES": {"on_exhausted": "ask",
                                                 "max_attempts": 2}}}, save=False)
    snap1 = policies(cfg)
    facies = next(g for g in snap1["gates"] if g["id"] == "G-FACIES")
    check("policies: переключение из интерфейса (данные)",
          snap1["bypass_enabled"] is False and facies["on_exhausted"] == "ask"
          and facies["max_attempts"] == 2)
    bad = update_policies(cfg, {"gates": {"G-FACIES": {"on_exhausted": "smash"},
                                          "UNKNOWN": {"on_exhausted": "ask"}}}, save=False)
    facies2 = next(g for g in bad["gates"] if g["id"] == "G-FACIES")
    check("policies: недопустимые значения игнорируются",
          facies2["on_exhausted"] == "ask" and len(bad["gates"]) == 8)


# -- функциональность: rework-луп, исчерпание, пробники, рендер ----------------------
def test_runner_rework_exhaust() -> None:
    """Форс-провал G-STRUCT: rework по кандидатам → исчерпание → bypassed (degraded)."""
    import tempfile
    from types import SimpleNamespace

    import agents.checks.base as check_base
    from agents.runner import StageRunner
    from core.coordinator import Coordinator

    coord = Coordinator(load_config(), dry_run=True)

    class FakeTnav:
        """Заглушка клиента тНава: сеть/лицензия не нужны (execute-контур офлайн)."""

        def __init__(self, cfg) -> None:
            self.cfg = cfg
            self.dry_run = True

        def set_log(self, _fn) -> None:
            pass

        def open(self, **_kw):
            return self

        def run_workflow(self, _path, save=True):
            return SimpleNamespace(ok=True, error="", kind="workflow")

        def save_project(self) -> bool:
            return True

        def close(self) -> None:
            pass

    fake_client = FakeTnav(coord.cfg)
    coord.tnav = lambda: fake_client
    coord._read_well_tie = lambda *a, **k: None
    coord._read_grid_geometry = lambda *a, **k: None
    coord._read_stoiip = lambda *a, **k: None
    coord._read_py_capture = lambda *a, **k: None

    original_run = check_base.CheckRegistry.run
    original_cands = StageRunner._remediation_candidates

    def failing_run(self, gate_id, evidence, ctx=None, *, include_runtime=True):
        findings = original_run(self, gate_id, evidence, ctx, include_runtime=include_runtime)
        # форс-провал только для ПЕРВИЧНОЙ оценки этапа (не для контрактного вызова)
        if gate_id == "G-STRUCT" and "handoff" not in (evidence or {}):
            findings = list(findings) + [Finding("test.forced", "critical", False,
                                                  title="форс-провал",
                                                  message="имитация дефекта (тест)")]
        return findings

    cfg_before: dict = {}
    try:
        check_base.CheckRegistry.run = failing_run
        StageRunner._remediation_candidates = (
            lambda self, graph, node, spec: [{"horizon_smooth": {"radius": 100}},
                                             {"horizon_smooth": {"radius": 50}}]
            if spec.id == "G-STRUCT" else [])
        with tempfile.TemporaryDirectory() as tmp:
            # F-31: тестовый execute НЕ должен писать в ОБЩИЕ каталоги. Прогон с
            # `execute=True` (а) кладёт снапшот в runs/artifacts и (б) пересобирает
            # ветки в models/<vid>, а `_build_ensemble` перед каждой веткой делает
            # rmtree. С фейковым клиентом ветки остаются пустыми — то есть КАЖДЫЙ
            # прогон батареи стирал РЕАЛЬНЫЕ модели веток и засорял архив приёмки
            # (сотни снапшотов с run_dir в %TEMP%). Пути — данные, поэтому на время
            # теста подменяем их на каталоги внутри tmp.
            cfg_keys = ("project.models_dir", "runs.execute_archive_dir", "runs.root")
            cfg_before = {k: coord.cfg.get(k) for k in cfg_keys}
            coord.cfg.set("project.models_dir", str(Path(tmp) / "models"))
            coord.cfg.set("runs.execute_archive_dir", str(Path(tmp) / "artifacts"))
            coord.cfg.set("runs.root", str(Path(tmp) / "runs"))
            run_dir = Path(tmp) / "run"
            report = coord.run("Герасимовское", run_dir=run_dir, execute=True)
            stages = (report.get("agents") or {}).get("stages") or []
            progress = load_json(run_dir / "agents" / "progress.json")
            attempts = sorted((run_dir / "agents" / "gates").glob("G-STRUCT.attempt*.json"))
            memo = load_json(run_dir / "agents" / "handoffs" / "01_G-STRUCT.json")
            wf_file = run_dir / "agents" / "stages" / "01_G_STRUCT.py"
            memo_sha = ((memo.get("artifact_revisions") or [{}])[0]).get("sha256", "")
            wf_sha = sha256_file(wf_file)
            for _k, _v in cfg_before.items():
                coord.cfg.set(_k, _v)
    finally:
        for _k, _v in cfg_before.items():
            coord.cfg.set(_k, _v)
        check_base.CheckRegistry.run = original_run
        StageRunner._remediation_candidates = original_cands

    struct = [s for s in stages if s["gate"] == "G-STRUCT"]
    check("rework: структурные этапы исчерпали попытки (3)",
          bool(struct) and all(s["attempts"] == 3 for s in struct),
          str([(s["gate"], s["attempts"], s["status"]) for s in struct]))
    check("rework: исчерпание best → bypassed",
          all(s["status"] == "bypassed" for s in struct),
          str([(s["gate"], s["status"]) for s in struct]))
    check("rework: сохранены файлы отклонённых попыток",
          len(attempts) >= 2 and all("G-STRUCT.attempt" in p.name for p in attempts),
          str([p.name for p in attempts]))
    check("rework: меморандум деградации с причиной",
          memo.get("degraded") is True and bool(memo.get("bypass_reason"))
          and any("test.forced" in s for s in (memo.get("unresolved_findings") or [])),
          str(memo.get("bypass_reason")))
    check("rework: артефакт меморандума — хеш файла воркфлоу",
          bool(memo_sha) and memo_sha == wf_sha)
    check("rework: прогон не остановлен (degraded-продолжение)",
          (report.get("agents") or {}).get("verdict") == "passed_with_degradation"
          and progress.get("halted") is False,
          str((report.get("agents") or {}).get("verdict")))
    check("rework: G-DATA не затронут форсом",
          any(s["gate"] == "G-DATA" and s["status"] == "passed" for s in stages))


def test_runner_runtime_evidence() -> None:
    """Runtime-пробники этапа: свидетельства попадают в данные, ошибки не роняют."""
    from agents.gates import GateSpec
    from agents.runner import StageRunner
    from core.coordinator import Coordinator

    coord = Coordinator(load_config(), dry_run=True)
    coord.cfg.set("project.grid_name", "main_grid")
    runner = StageRunner(coord)
    graph = {"reservoir_horizon": "BAJ"}

    coord._read_well_tie = lambda client, run_dir, horizon: [{"well": "1", "delta": 3.0}]
    coord._read_grid_geometry = lambda client: {"nx": 250, "ny": 311, "nz": 22}
    coord._read_stoiip = lambda client: 1.78e9
    coord._read_py_capture = lambda client, code, tmp, keys: {"value": 0.23}

    ev = {}
    runner._attach_runtime_evidence(ev, object(), Path("."), graph,
                                    runner.engine.spec("G-STRUCT"))
    check("probes: сшивка скважин в свидетельствах", len(ev.get("well_tie") or []) == 1)
    ev_grid = {}
    runner._attach_runtime_evidence(ev_grid, object(), Path("."), graph,
                                    runner.engine.spec("G-GRID"))
    check("probes: геометрия сетки в свидетельствах",
          (ev_grid.get("grid") or {}).get("nx") == 250)
    ev_vol = {}
    runner._attach_runtime_evidence(ev_vol, object(), Path("."), graph,
                                    runner.engine.spec("G-VOL"))
    check("probes: STOIIP в свидетельствах", ev_vol.get("stoiip") == 1.78e9)
    spec_prop = GateSpec(id="G-PETRO", agent="AG_PETROPHYSICS", stages=(7,),
                         evidence=(
                             {"kind": "property_mean", "name": "PORO", "as": "poro_mean"},))
    ev_prop = {}
    runner._attach_runtime_evidence(ev_prop, object(), Path("."), graph, spec_prop)
    check("probes: property_mean по имени гейта", ev_prop.get("poro_mean") == 0.23)

    def boom(client):
        raise RuntimeError("проба упала")

    coord._read_grid_geometry = boom
    ev_err = {}
    runner._attach_runtime_evidence(ev_err, object(), Path("."), graph,
                                    runner.engine.spec("G-GRID"))
    check("probes: ошибка пробника не роняет этап", ev_err.get("grid") is None)

    coord._read_py_capture = lambda client, code, tmp, keys: None
    check("probes: нет данных → None (не штраф)",
          runner._probe_property_mean(object(), "g", "PORO") is None)


def test_render_stage() -> None:
    """Рендер этапа: блоки/объекты/индекс, патч параметров rework, без шаблона."""
    from dataclasses import replace
    from types import SimpleNamespace

    from agents.runner import StageRunner
    from core.coordinator import Coordinator

    coord = Coordinator(load_config(), dry_run=True)
    runner = StageRunner(coord)
    nodes = coord.assembler("Герасимовское").node_genes()
    rules = coord.function_rules()
    rule_map = {name: r for name, r in ((n, rules.read(n)) for n in rules.all_names())
                if r is not None}
    node = next((n for n in nodes if "Структурные поверхности" in str(n.stage)), None)
    asg = SimpleNamespace(stage_key="2. Горизонты", agent_id="AG_STRUCTURAL")
    spec = runner.engine.spec("G-STRUCT")

    blocks, index, objs = runner._render_stage(node, rule_map, 1, None, asg, spec)
    check("render_stage: блоки отрендерены", bool(blocks) and index > 1,
          f"блоков {len(blocks)}, индекс {index}")
    patched, _, _ = runner._render_stage(node, rule_map, 1, None, asg, spec,
                                         params={"horizon_smooth": {"radius": 4567}})
    check("render_stage: патч rework попадает в код",
          "4567" in "\n".join(patched) and "4567" not in "\n".join(blocks))
    fake = SimpleNamespace(functions=[replace(node.functions[0], function="no_such_function")])
    b2, i2, o2 = runner._render_stage(fake, rule_map, 1, None, asg, spec)
    check("render_stage: нет шаблона — без падения и без кода", b2 == [] and i2 == 1,
          f"блоков {len(b2)}, индекс {i2}")


# -- функциональность: решения оператора (изоляция гейтов) --------------------------
def test_decision_broker_parallel() -> None:
    import threading
    import time as _time

    from agents.decisions import DecisionBroker

    hooks: list[tuple] = []
    broker = DecisionBroker(timeout_sec=3.0,
                            on_request=lambda r, g, c: hooks.append((r, g, c)))
    out: dict = {}
    t1 = threading.Thread(target=lambda: out.__setitem__(
        "a", broker.request("runA", "G-STRUCT", {"status": "failed"})))
    t2 = threading.Thread(target=lambda: out.__setitem__(
        "b", broker.request("runA", "G-VOL", {"status": "failed"})))
    t1.start()
    t2.start()
    deadline = _time.time() + 3.0
    while len(broker.pending()) < 2 and _time.time() < deadline:
        _time.sleep(0.01)
    check("broker: два гейта ждут решения", len(broker.pending()) == 2, str(broker.pending()))
    check("broker: хук on_request получает контекст гейта",
          len(hooks) == 2 and any(h[2].get("status") == "failed" for h in hooks))
    ok1 = broker.resolve("runA", "G-STRUCT", "best", author="t1")
    t1.join(timeout=2.0)
    check("broker: resolve первого не трогает второй",
          ok1 and len(broker.pending()) == 1
          and (out.get("a") or {}).get("action") == "best", str(broker.pending()))
    check("broker: решение по неожидающему гейту отклонено",
          broker.resolve("runB", "G-STRUCT", "halt") is False)
    ok2 = broker.resolve("runA", "G-VOL", "skip", author="t2", comment="нет данных")
    t2.join(timeout=2.0)
    check("broker: второе решение доставлено",
          ok2 and (out.get("b") or {}).get("action") == "skip")
    check("broker: журнал хранит автора и комментарий",
          any(d["author"] == "t2" and d["comment"] == "нет данных" for d in broker.log()))


# -- функциональность: артефакты контрактов -----------------------------------------
def test_contracts_artifacts() -> None:
    import tempfile

    finding = Finding("data.map_blank", "critical", False, title="бланк", message="99%")
    payload = finding.to_dict()
    check("contracts: Finding сериализуется с серьёзностью",
          payload["severity"] == "critical" and payload["passed"] is False
          and payload["evidence"] == {})
    verdict = GateVerdict(gate_id="G-STRUCT", status=FAILED, attempts=2,
                          findings=[finding, Finding("ok", "major", True)])
    data = verdict.to_dict()
    check("contracts: GateVerdict считает провалы и попытки",
          data["failed"] == 1 and data["attempts"] == 2 and len(data["findings"]) == 2)
    with tempfile.TemporaryDirectory() as tmp:
        path = save_json(Path(tmp) / "gates" / "G-STRUCT.json", verdict)
        back = load_json(path)
        check("contracts: вердикт сохраняется и читается",
              back.get("gate_id") == "G-STRUCT" and back.get("failed") == 1)
        wf = Path(tmp) / "wf.py"
        wf.write_bytes(b"x = 1\n")
        check("contracts: sha256 файла совпадает с хешем текста",
              sha256_file(wf) == sha256_text("x = 1\n"))
        check("contracts: нет файла — пустой хеш", sha256_file(Path(tmp) / "нет.py") == "")


def test_range_adapter_multi() -> None:
    from agents.checks.adapters import range_findings
    from core.ontology import ParamSpec
    from domain.metacritic import MetaCritic

    def make_spec(code: str, rng: str) -> ParamSpec:
        return ParamSpec(code=code, name=code, data_type="float", unit="д.ед.",
                         typical_range=rng, typical_error="0.01", level="", domain="",
                         stage="", equipment="", node="")

    critic = MetaCritic([], [make_spec("PORO", "0.02..0.35"), make_spec("PERMX", "1..5000"),
                             make_spec("NTG", "")])
    out = range_findings(critic, {"PORO": 0.99, "PERMX": 10.0, "NTG": 5.0})
    check("range: несколько параметров — только провалы",
          len(out) == 1 and out[0].source == "range" and not out[0].passed, str(out))
    check("range: параметр без диапазона не штрафуется",
          range_findings(critic, {"NTG": 5.0}) == [])
    check("range: пустые значения — тихо", range_findings(critic, {}) == [])


# -- размышления: советник LLM (фейковый шлюз, без сети) -----------------------------
def test_advisor_reasoning() -> None:
    from agents.advisor import StageAdvisor

    class FakeGateway:
        configured = True

        def __init__(self, answer: str = "Шаги: 1) проверить бланк 2) перестроить горизонт",
                     fail: bool = False) -> None:
            self.answer, self.fail = answer, fail
            self.calls: list[tuple[str, str]] = []

        def _chat(self, system: str, user: str) -> tuple[str, str]:
            self.calls.append((system, user))
            if self.fail:
                raise RuntimeError("сеть недоступна")
            return self.answer, "cot"

    cfg = load_config()
    cfg.set("execution.agent_llm", True)
    prompt_path = ROOT / "agents" / "prompts" / "verify.md"
    check("advisor: промпт-файл существует", prompt_path.is_file())
    prompt_text = prompt_path.read_text(encoding="utf-8").strip() if prompt_path.is_file() else ""
    check("advisor: промпт запрещает отменять вердикт",
          "вердикт" in prompt_text.lower() and "не отмен" in prompt_text.lower(),
          prompt_text[:120])

    gw = FakeGateway()
    advisor = StageAdvisor(cfg, gateway=gw)
    check("advisor: включён при agent_llm и готовом шлюзе", advisor.enabled)
    findings = [Finding("struct.well_tie", "major", False, message="медиана 37 м"),
                Finding("data.map_blank", "major", True, message="в допуске")]
    note = advisor.explain(agent_id="AG_STRUCTURAL", stage_key="2. Горизонты",
                           gate_id="G-STRUCT", status="failed", findings=findings)
    check("advisor: пояснение получено", bool(note) and note.startswith("Шаги"))
    system, user = gw.calls[-1]
    check("advisor: системный промпт — из файла данных", system == prompt_text)
    check("advisor: запрос содержит агента/этап/гейт/вердикт",
          "AG_STRUCTURAL" in user and "G-STRUCT" in user
          and "2. Горизонты" in user and "failed" in user)
    check("advisor: в запрос идут только проваленные находки",
          "struct.well_tie" in user and "data.map_blank" not in user)
    check("advisor: без провалов молчит",
          advisor.explain(agent_id="a", stage_key="s", gate_id="g",
                          status=PENDING, findings=[Finding("x", "major", True)]) == "")
    short = StageAdvisor(cfg, gateway=FakeGateway(answer="я" * 100)).explain(
        agent_id="a", stage_key="s", gate_id="g", status=FAILED,
        findings=[Finding("x", "major", False)], limit=10)
    check("advisor: обрезка по limit", len(short) == 10, str(len(short)))
    check("advisor: ошибка шлюза не роняет прогон",
          StageAdvisor(cfg, gateway=FakeGateway(fail=True)).explain(
              agent_id="a", stage_key="s", gate_id="g", status=FAILED,
              findings=[Finding("x", "major", False)]) == "")
    check("advisor: пустой ответ модели",
          StageAdvisor(cfg, gateway=FakeGateway(answer="")).explain(
              agent_id="a", stage_key="s", gate_id="g", status=FAILED,
              findings=[Finding("x", "major", False)]) == "")


def test_llm_gateway_offline() -> None:
    """Рассуждения шлюза офлайн: разбор намерения, JSON, fallback (без сети)."""
    from core.llm_gateway import (LLMUnavailable, _extract_json, _fallback_intent,
                                  parse_ensemble_from_text)

    check("llm: число реализаций из текста",
          parse_ensemble_from_text("собери 8 моделей") == 8
          and parse_ensemble_from_text("5 ветвей") == 5
          and parse_ensemble_from_text("три модели") is None
          and parse_ensemble_from_text("64 реализации") is None)
    payload = _extract_json('текст\n```json\n{"mode": "build", "ensemble_size": 4}\n```')
    check("llm: JSON извлекается из ответа модели",
          payload.get("mode") == "build" and payload.get("ensemble_size") == 4)
    raised = False
    try:
        _extract_json("в ответе нет json")
    except LLMUnavailable:
        raised = True
    check("llm: без JSON — LLMUnavailable (не выдумывает)", raised)
    intent = _fallback_intent("построй только гидродинамическую модель",
                              default_ensemble=3, default_exclude=["op1"],
                              field="Герасимовское")
    check("llm: fallback определяет цель и поле",
          intent.goal == "gdm" and intent.field_name == "Герасимовское"
          and intent.source == "fallback")
    intent2 = _fallback_intent("адаптация модели, 6 моделей", default_ensemble=3,
                               default_exclude=["op1"], field=None)
    check("llm: fallback адаптации и числа реализаций",
          intent2.adaptation and intent2.ensemble_size == 6
          and intent2.exclude_operations == [])


# -- хранение знаний: реестр BDI и персистентность политик ---------------------------
def test_registry_knowledge() -> None:
    reg = AgentRegistry(load_config())
    stats = reg.stats()
    check("registry: сводка знаний полная",
          set(stats) == {"available", "dir", "profiles", "handoffs", "decisions"}
          and stats["profiles"] >= 22 and stats["handoffs"] >= 17,
          str(stats))
    rules = reg.decisions()
    check("registry: правила решений с охраной и действием",
          sum(1 for r in rules if r.guard and r.outcome) >= 10,
          f"правил {len(rules)}")
    check("registry: приоритеты — целые", all(isinstance(r.priority, int) for r in rules))
    profiles = reg.profiles()
    check("registry: профили несут знания о режимах",
          any(p.scope for p in profiles) and any(p.hybrid_mode for p in profiles)
          and any(p.symbolic_mode for p in profiles))
    check("registry: контракты передачи с обязательствами",
          sum(1 for h in reg.handoffs() if h.required) >= 10
          and any(h.on_reject for h in reg.handoffs()))


def test_policies_persistence() -> None:
    """Знания политик переживают перезапуск: config.local.yaml (tmp-копия, не боевая)."""
    import tempfile

    from agents.gates import load_gate_specs, policies, update_policies

    base = load_config()
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.yaml"
        cfg_path.write_text(yaml.safe_dump(base.raw, allow_unicode=True, sort_keys=False),
                            encoding="utf-8")
        cfg = load_config(cfg_path)
        update_policies(cfg, {"gate_bypass": False,
                              "gates": {"G-FACIES": {"on_exhausted": "ask",
                                                     "max_attempts": 2}}}, save=True)
        local_path = Path(tmp) / "config.local.yaml"
        check("policies: персистентность в config.local.yaml", local_path.is_file())
        local_data = yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}
        check("policies: сохраняются только переопределения",
              (local_data.get("execution") or {}).get("gate_bypass") is False
              and ((local_data.get("gates_override") or {}).get("G-FACIES") or {}
                   ).get("on_exhausted") == "ask",
              str(sorted(local_data)))
        cfg2 = load_config(cfg_path)
        snap = policies(cfg2)
        facies = next(g for g in snap["gates"] if g["id"] == "G-FACIES")
        check("policies: перезапуск видит переопределения",
              snap["bypass_enabled"] is False and facies["on_exhausted"] == "ask"
              and facies["max_attempts"] == 2)
        specs = {s.id: s for s in load_gate_specs(cfg2)}
        check("policies: gates_override действует в спецификациях",
              specs["G-FACIES"].on_exhausted == "ask"
              and specs["G-STRUCT"].on_exhausted == "best")


# -- новые сущности: API-прогресс, карты, таймаут тНава, детерминизм чата -------------
def test_maps_check() -> None:
    """Проверка карт (G-MAPS): ожидаемые PNG из данных конфига."""
    from agents.checks.builtin import check_maps_files

    ctx = {"map_files": ["C1tl_top", "PORO"]}
    ok = check_maps_files({"map_files": [{"name": "C1tl_top"}, {"name": "PORO"}]}, ctx)
    check("maps: все карты на месте → passed", ok is not None and ok.passed)
    bad = check_maps_files({"map_files": [{"name": "C1tl_top"}]}, ctx)
    check("maps: отсутствующая карта → failed с перечнем",
          bad is not None and not bad.passed and "PORO" in bad.message, bad.message)
    check("maps: список карт не задан → not_applicable", check_maps_files({}, {}) is None)
    check("maps: нет данных прогона → failed (карты не собраны)",
          (lambda f: f is not None and not f.passed)(check_maps_files({}, ctx)))


def test_well_tie_nan_filter() -> None:
    """Бланк поверхности (nan) в точке скважины не ломает медиану/RMSE (неизвестное != ложь)."""
    import math

    from agents.checks.builtin import check_well_tie, check_well_tie_rmse

    tie = [(0.0, 4.0), (0.0, 5.0), (0.0, float("nan")), (0.0, 3.0)]
    f = check_well_tie({"well_tie": tie}, {"well_tie_median_m": 10.0})
    check("well_tie: nan-модель отброшена (медиана/RMSE конечны, count=3)",
          f is not None and f.passed and math.isfinite(f.evidence["rmse_m"])
          and f.evidence["count"] == 3, str(f.evidence if f else None))
    fr = check_well_tie_rmse({"well_tie": tie}, {"well_tie_rmse_m": 10.0})
    check("well_tie_rmse: RMSE конечен при nan-паре",
          fr is not None and math.isfinite(fr.evidence["rmse_m"]),
          str(fr.evidence if fr else None))
    only_nan = check_well_tie({"well_tie": [(0.0, float("nan"))]},
                              {"well_tie_median_m": 10.0})
    check("well_tie: только nan-пары → проверка не выполняется (не штраф)", only_nan is None)


def test_irap_parser() -> None:
    """Единый разбор irap: «полный» (tNavigator/RMS) и «простой» форматы."""
    import tempfile

    from domain import map_render
    from domain.irap import (irap_stats, read_irap, read_irap_extent,
                             read_irap_mean_z, read_irap_text)

    src = ROOT / "data" / "Герасимовское" / "Source" / "struct" / "depth_u1.irap"
    grid = read_irap(src)
    check("irap: «полный» формат — nx/ny из заголовка (251×312, не |-996|)",
          grid is not None and grid.nx == 251 and grid.ny == 312,
          str((grid.nx, grid.ny) if grid else None))
    check("irap: ячеек ровно nx*ny (ведущий артефакт экспортёра срезан)",
          grid is not None and grid.total == 251 * 312 and len(grid.values) == grid.total,
          str(grid and len(grid.values)))
    check("irap: экстент — объявленный (локальная СК)",
          read_irap_extent(src) == (63754.458879, 76254.458879,
                                    304597.452304, 320147.452304),
          str(read_irap_extent(src)))
    mz = read_irap_mean_z(src)
    check("irap: средняя отметка в физичном диапазоне",
          mz is not None and -2500.0 < mz < -2300.0, str(mz))

    xs, ys, zs = map_render.read_ascii_grid(src, novalue=9999900, blank_abs=1e6)
    check("irap: карта непустых узлов собрана (план, а не «разрез»)",
          len(zs) > 1000 and min(zs) < -2300 and max(zs) < 0
          and len(xs) == len(ys) == len(zs), f"точек {len(zs)}")
    stats = irap_stats(src, 9999900, 1e6)
    check("irap: статистика согласована с картой (total = valid + blank)",
          stats is not None and stats["total"] == len(zs) + stats["blank"],
          str(stats and {k: stats[k] for k in ("ncols", "nrows", "total", "blank")}))

    simple = read_irap_text("3 2\n0 2 0 1\n1 2 3 4 5 6\n")
    check("irap: «простой» формат читается",
          simple is not None and simple.nx == 3 and simple.ny == 2
          and tuple(simple.values) == (1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
          str(simple))

    with tempfile.TemporaryDirectory() as tmp:
        xyz = Path(tmp) / "pts.xyz"
        xyz.write_text("1 2 3\n4 5 6\n7 8 9\n", encoding="utf-8")
        check("irap: XYZ-таблица — не сетка (read_irap → None)", read_irap(xyz) is None)
        pts = map_render.read_ascii_grid(xyz)
        check("irap: XYZ-таблица — фолбэк в точки",
              bool(pts) and len(pts[0]) == 3, str(pts))


def test_pipeline_order_structural_first() -> None:
    """Порядок этапов: структурные поверхности СТРОЯТСЯ ДО карт толщин."""
    graph = yaml.safe_load((ROOT / "ontology_project" / "gerasimovskoe.yaml")
                           .read_text(encoding="utf-8"))
    stages = graph.get("pipeline") or []
    labels = [s.get("stage", "") for s in stages]
    check("pipeline: этап 1 — структурные поверхности",
          labels[1].startswith("1.") and "Структурн" in labels[1], labels[1])
    check("pipeline: этап 2 — толщины",
          labels[2].startswith("2.") and "Толщин" in labels[2], labels[2])
    s1 = [st.get("function") for st in stages[1].get("steps", [])]
    s2 = [st.get("function") for st in stages[2].get("steps", [])]
    check("pipeline: толщина считается ПОСЛЕ поверхностей (карта из горизонтов)",
          "map_2d_calculator" in s2 and "map_2d_calculator" not in s1, str((s1, s2)))
    # Подошва U1_bot строится НЕЗАВИСИМО по маркеру J2 (этап 1); толщина этапа 2 =
    # U1_top − U1_bot (кровля − подошва), а не по отбивкам BAJ−J2.
    bot = [st for st in stages[1].get("steps", [])
           if (st.get("objects") or {}).get("result_horizon", {}).get("obj_name") == "U1_bot"]
    check("pipeline: U1_bot (подошва Ю1) — строится по маркеру J2 на этапе 1",
          bool(bot) and (bot[0].get("objects") or {}).get("well_marker", {}).get("obj_name") == "J2",
          str(bot))
    thick = [st for st in stages[2].get("steps", [])
             if st.get("function") == "map_2d_calculator"
             and (st.get("objects") or {}).get("result_map_2d", {}).get("obj_name") == "Tl_thick"]
    check("pipeline: толщина Tl_thick = U1_top − U1_bot (кровля − подошва), этап 2",
          bool(thick) and "horizon" in str(thick[0].get("parameters", {}).get("formula", "")),
          str(thick))
    top = [st for st in stages[1].get("steps", [])
           if (st.get("objects") or {}).get("result_horizon", {}).get("obj_name") == "U1_top"]
    check("pipeline: U1_top (кровля Ю1) — с сейсмическим трендом + residual IDW",
          bool(top)
          and top[0].get("parameters", {}).get("use_trend_horizon") is True
          and top[0].get("parameters", {}).get("use_residual_idw") is True,
          str(top))
    check("pipeline: единый объект Ю1 — нет устаревших имён C1bb/C1tl в объектах этапов 1–2",
          not any("C1bb" in str(st.get("objects") or {})
                  or "C1tl" in str(st.get("objects") or {})
                  for s in (stages[1], stages[2]) for st in s.get("steps", [])))
    check("pipeline: убран шаг marker_create_by_horyzon (маркер по C1bb_top)",
          "marker_create_by_horyzon" not in s1)


def test_tnav_connection_options() -> None:
    """Совместимость API тНава: 26.2 (без аргументов), 26.1 (kwargs), tnav://."""
    import tempfile
    from types import SimpleNamespace

    from domain.tnav_client import TnavClient

    class OptsNoArgs:
        def __init__(self) -> None:
            pass

    class OptsKw:
        def __init__(self, **kw) -> None:
            self.kw = dict(kw)

    t262 = SimpleNamespace(ConnectionOptions=OptsNoArgs)
    t261 = SimpleNamespace(ConnectionOptions=OptsKw)
    cfg = load_config()
    cfg.set("tnavigator.license.url", "http://lic-server:4085")
    with tempfile.TemporaryDirectory() as tmp:
        lic_ini = str(Path(tmp) / "lic.ini")
        cfg.set("tnavigator.license_settings_file", lic_ini)
        client = TnavClient(cfg)
        opts26 = client._connection_options(t262)
        check("tnav: 26.2 ConnectionOptions без аргументов — поля атрибутами",
              isinstance(opts26, OptsNoArgs)
              and getattr(opts26, "license_settings", "") == lic_ini
              and getattr(opts26, "license_type", "") == "network",
              str(getattr(opts26, "__dict__", {})))
        opts = client._connection_options(t261)
        check("tnav: 26.1 ConnectionOptions с настройками лицензии",
              isinstance(opts, OptsKw) and bool(opts.kw.get("license_settings"))
              and opts.kw.get("license_type") == "network", str(getattr(opts, "kw", {})))

    cfg_tnav = load_config()                  # tnav:// из config.local.yaml
    check("tnav: tnav:// — лицензия из %APPDATA% (без опций)",
          TnavClient(cfg_tnav)._connection_options(t261) is None
          and TnavClient(cfg_tnav)._connection_options(t262) is None)
    cfg2 = load_config()
    cfg2.set("tnavigator.license.url", "")
    check("tnav: без url лицензии → None",
          TnavClient(cfg2)._connection_options(t261) is None)

    class OptsFrozen:
        """Ни kwargs, ни атрибуты: остаётся деградация до локального ini."""
        __slots__ = ()

        def __init__(self, *args, **kwargs):
            raise TypeError("takes no arguments")

    tfrozen = SimpleNamespace(ConnectionOptions=OptsFrozen)
    check("tnav: опции не выставить — деградация None",
          TnavClient(cfg)._connection_options(tfrozen) is None)


def test_api_progress_and_routes() -> None:
    import tempfile

    try:
        import api
    except ImportError as exc:                 # окружение без fastapi — не штрафуем
        check("api: тесты пропущены (нет fastapi в этом окружении)", True, str(exc))
        return

    paths = {(getattr(r, "path", ""), tuple(sorted(getattr(r, "methods", []) or [])))
             for r in api.app.routes}
    # Состояние веб-слоя — во ВРЕМЕННЫЙ файл: тест не должен затирать рабочий
    # runs/_web_state.json, иначе прогоны пользователя исчезают из интерфейса.
    state_file_before = api._STATE_FILE
    api._STATE_FILE = Path(tempfile.mkdtemp(prefix="web_state_test_")) / "_web_state.json"
    check("api: POST /api/runs зарегистрирован",
          ("/api/runs", ("POST",)) in paths,
          str(sorted(p for p, _ in paths if "runs" in p)))
    check("api: POST /api/reset зарегистрирован",
          ("/api/reset", ("POST",)) in paths,
          str(sorted(p for p, _ in paths if "reset" in p)))
    check("api: эндпоинты карт зарегистрированы",
          any(p.endswith("/maps") for p, _ in paths)
          and any("/maps/" in p for p, _ in paths))
    check("api: эндпоинты карт по версиям зарегистрированы",
          ("/api/runs/{run_id}/mapset", ("GET",)) in paths
          and ("/api/runs/{run_id}/mapset/{version}/{file_name}", ("GET",)) in paths,
          str(sorted(p for p, _ in paths if "mapset" in p)))
    check("api: вопрос ансамбля детерминирован",
          "Сколько реализаций" in api.ENSEMBLE_QUESTION)

    rec = api.RunRecord(run_id="r1", field="F")
    rec.set_phase("stage", "2/9", stage="2. Горизонты", index=2, total=9)
    check("api: прогресс хранит фазу/этап/проценты",
          rec.progress["phase"] == "stage" and rec.progress["percent"] == 22
          and rec.progress["stage"] == "2. Горизонты", str(rec.progress))
    rec.set_phase("done", "готово")
    check("api: завершение — 100%", rec.progress["percent"] == 100)

    with tempfile.TemporaryDirectory() as tmp:
        maps_dir = Path(tmp) / "maps"
        maps_dir.mkdir()
        (maps_dir / "U1_top.png").write_bytes(b"\x89PNG")
        (maps_dir / "Tl_thick.png").write_bytes(b"\x89PNG")
        found = api._collect_maps(tmp)
    check("api: список карт прогона собирается",
          [m["name"] for m in found] == ["Tl_thick", "U1_top"], str(found))
    check("api: без каталога карт — пусто", api._collect_maps(None) == [])

    with tempfile.TemporaryDirectory() as tmp:
        base_maps = Path(tmp) / "maps"
        base_maps.mkdir()
        (base_maps / "U1_top.png").write_bytes(b"\x89PNG")
        (base_maps / "FACIES.png").write_bytes(b"\x89PNG")
        branch = Path(tmp) / "models" / "S001"
        (branch / "maps").mkdir(parents=True)
        (branch / "S001.snp").write_bytes(b"")
        (branch / "maps" / "U1_top.png").write_bytes(b"\x89PNG")
        result = {"ensemble": {"branches": [
            {"id": "S001", "label": "врез", "path": str(branch / "S001.snp")}]}}
        ms = api._collect_version_maps(tmp, result)
    ver_ids = [v["id"] for v in ms["versions"]]
    kinds = {m["kind"] for v in ms["versions"] for m in v["maps"]}
    check("api: карты по версиям — base + ветки (данные)", ver_ids == ["base", "S001"],
          str(ver_ids))
    check("api: виды карт классифицированы (structural/facies)",
          kinds == {"structural", "facies"}, str(kinds))
    check("api: без каталога карт по версиям — пусто",
          api._collect_version_maps(None, {})["versions"] == [])

    # полный сброс (запуск с нуля): очищает сообщения и прогоны, сохраняет состояние
    runs_before = dict(api._RUNS)
    chat_before = list(api._CHAT)
    pending_before = dict(api._PENDING)
    try:
        api._RUNS["reset-test"] = api.RunRecord(run_id="reset-test", field="F")
        api._CHAT.append({"role": "user", "text": "тест сброса", "ts": ""})
        api._PENDING["await_ensemble"] = True
        out = api.reset_all()
        cleared = (not api._RUNS and not api._CHAT and not api._PENDING)
    finally:
        api._RUNS.update(runs_before)
        api._CHAT[:] = chat_before
        api._PENDING.clear()
        api._PENDING.update(pending_before)
    check("api: сброс очищает сообщения и прогоны (запуск с нуля)",
          out.get("ok") is True and cleared, str(out))
    api._STATE_FILE = state_file_before          # вернуть рабочий путь состояния


def test_chat_clarify_no_false_run() -> None:
    """Ансамбль без числа: известное поле → прогон, неизвестное → честный вопрос.

    Контракт task-13: если поле задано, число реализаций ЕСТЬ в данных проекта
    (`execution.ensemble_size`), поэтому прогон обязан стартовать, а ответ — не
    содержать ложного «Принято» от LLM. Уточнение допустимо только там, где
    данных действительно нет (поле не задано), и обязано быть записано в состоянии.
    """
    from types import SimpleNamespace
    import tempfile

    try:
        import api
    except ImportError as exc:                 # окружение без fastapi — не штрафуем
        check("chat: тесты пропущены (нет fastapi в этом окружении)", True, str(exc))
        return

    original_converse, original_llm, original_submit = api.converse, api._llm, api._submit
    original_state = api._STATE_FILE
    api._STATE_FILE = Path(tempfile.mkdtemp(prefix="web_state_chat_")) / "_web_state.json"
    api._ATTEMPTS.clear()
    try:
        api._llm = lambda: object()
        api.converse = lambda *a, **k: SimpleNamespace(
            mode="clarify", reasoning="нужно число реализаций",
            reply="Принято: собираю ансамбль из 4 моделей.", source="llm")

        def fake_submit(field, message, execute, **kw):     # без запуска конвейера
            rec = api.RunRecord(run_id="chat-test-run", field=field, message=message,
                                execute=execute, ensemble_size=kw.get("ensemble_size", 0))
            rec.set_phase("plan", "тест ветки принятия решения")
            api._RUNS[rec.run_id] = rec
            return rec

        api._submit = fake_submit
        runs_before = len(api._RUNS)
        out = api.chat(api.ChatRequest(message="Собери ансамбль из нескольких моделей",
                                       field="Герасимовское", execute=False))
        attempt_build = (api._ATTEMPTS or [{}])[-1]
        runs_after_build = len(api._RUNS)
        api._ATTEMPTS.clear()
        out_clar = api.chat(api.ChatRequest(message="построй модель", field="Герасимовское",
                                            execute=False))
        attempt_clar = (api._ATTEMPTS or [{}])[-1]
        runs_after_clar = len(api._RUNS)
    finally:
        api.converse, api._llm, api._submit = original_converse, original_llm, original_submit
        api._STATE_FILE = original_state
    check("chat: ансамбль без числа + известное поле → прогон СОЗДАН без ложного «Принято»",
          out["mode"] == "build" and bool(out.get("run_id"))
          and runs_after_build == runs_before + 1
          and "Принято" not in (out.get("reply") or "")
          and attempt_build.get("run_id") == out.get("run_id"),
          str(out))
    check("chat: уточнение (когда данных правда нет) → прогона нет, попытка записана",
          out_clar["mode"] == "clarify" and runs_after_clar == runs_after_build
          and out_clar.get("run_id") is None
          and attempt_clar.get("mode") == "clarify" and attempt_clar.get("run_id") is None
          and bool(attempt_clar.get("reason")), str(attempt_clar))


def test_tnav_workflow_timeout() -> None:
    """Таймаут и ошибки воркфлоу тНава не блокируют прогон (мок проекта)."""
    import tempfile
    import time as _time

    from domain.tnav_client import TnavClient

    client = TnavClient(load_config())
    client.dry_run = False

    class SlowProject:
        def run_py_code(self, code=None, save=True):     # noqa: ARG002
            _time.sleep(0.5)

    class BadProject:
        def run_py_code(self, code=None, save=True):     # noqa: ARG002
            raise RuntimeError("тНав отказал")

    class FastProject:
        def run_py_code(self, code=None, save=True):     # noqa: ARG002
            return None

    with tempfile.TemporaryDirectory() as tmp:
        wf = Path(tmp) / "wf.py"
        wf.write_text("x = 1\n", encoding="utf-8")
        client._project = SlowProject()
        slow = client.run_workflow(wf, timeout_sec=0.05)
        client._project = BadProject()
        bad = client.run_workflow(wf, timeout_sec=5)
        client._project = FastProject()
        fast = client.run_workflow(wf, timeout_sec=5)
        client._project = None
        client.dry_run = True
        dry = client.run_workflow(wf)
    check("tnav: таймаут воркфлоу не блокирует", (not slow.ok) and "таймаут" in slow.error,
          slow.error)
    check("tnav: ошибка воркфлоу → ok=False с текстом", (not bad.ok) and "отказал" in bad.error)
    check("tnav: успешный воркфлоу", fast.ok and fast.kind == "workflow")
    check("tnav: dry-run не исполняет тНав", dry.ok and dry.kind == "dry_run")


def main() -> int:
    test_registry()
    test_registry_degraded()
    test_contracts()
    test_stage_map()
    test_gates()
    test_checks_and_evidence()
    test_staged_runner_dry_run()
    test_structure_policy()
    test_policy_agents()
    test_staged_skip_erosion_steps()
    test_decision_broker()
    test_gate_policies()
    test_package_adapter()
    test_range_adapter()
    test_remediation_candidates()
    test_advisor_offline()
    test_runner_rework_exhaust()
    test_runner_runtime_evidence()
    test_render_stage()
    test_decision_broker_parallel()
    test_contracts_artifacts()
    test_range_adapter_multi()
    test_advisor_reasoning()
    test_llm_gateway_offline()
    test_registry_knowledge()
    test_policies_persistence()
    test_api_progress_and_routes()
    test_maps_check()
    test_well_tie_nan_filter()
    test_irap_parser()
    test_pipeline_order_structural_first()
    test_chat_clarify_no_false_run()
    test_tnav_workflow_timeout()
    test_tnav_connection_options()
    failed = [r for r in results if not r[1]]
    print(f"\n=== ИТОГ ===\nвсего: {len(results)} | провалено: {len(failed)}")
    for name, _ok, detail in failed:
        print(f"  - {name}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
