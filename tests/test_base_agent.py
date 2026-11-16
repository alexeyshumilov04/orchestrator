"""Тесты фундамента агентного слоя: BaseAgent v2, БЗ (KnowledgeBase), контракты.

Запуск:  python -X utf8 tests/test_base_agent.py

Проверяется:
  * BDI-цикл: bind → observe → coverage → decide → plan → validate → verify → remember;
  * режимы решения SYMBOLIC/HYBRID/GENERATIVE/ABSTAIN по полноте входов (данные);
  * «неизвестное != ложь»: нет входов → missing/unknown, а не ложь; проверка без
    данных не штрафует; нечисловой параметр → находка, а не тихий пропуск;
  * БЗ: запись/чтение/близость/подсказка (медиана)/продвижение знания;
  * обратная совместимость: наследники (Structure/Grid/Facies/Petrophysics) работают
    через decide() и не теряют прежние ключи решения.
"""
from __future__ import annotations

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


def test_modes() -> None:
    from agents.base_agent import ABSTAIN, GENERATIVE, HYBRID, SYMBOLIC, BaseAgent

    class Probe(BaseAgent):
        agent_id = "AG_STRUCTURAL"
        label = "проба"

        def decision(self, project, evidence=None):
            return {"enabled": True, "reason": "проба", "parameters": {"fn": {"k": 1}}}

    cfg = _cfg()
    agent = Probe(cfg)
    cov = agent.coverage()
    check("base: нет входов → ABSTAIN (не ложь)",
          cov.mode == ABSTAIN and not cov.known, str(cov.to_dict()))
    agent.decide({}, {"welltops": {"w": [("m", 1.0)]}})
    check("base: покрытие 1/2 → GENERATIVE",
          agent.coverage().mode == GENERATIVE, str(agent.coverage().to_dict()))
    agent.decide({"structural": {"erosion": "auto"}}, {"welltops": {}})
    cov3 = agent.coverage()
    check("base: пустой вход → unknown, режим не SYMBOLIC",
          "welltops" in cov3.unknown and cov3.mode != SYMBOLIC, str(cov3.to_dict()))
    agent.decide({"structural": {"erosion": "auto"}},
                 {"welltops": {"w": [("m", 1.0)]}})
    check("base: полное покрытие → SYMBOLIC",
          agent.coverage().mode == SYMBOLIC, str(agent.coverage().to_dict()))
    check("base: пороги режимов — из данных",
          agent.policy() == {"symbolic_threshold": 1.0, "hybrid_threshold": 0.6},
          str(agent.policy()))
    check("base: HYBRID достижим при пороге 0.6 (2/3)",
          _hybrid_modes(cfg), "не удалось получить гибридный режим")


def _hybrid_modes(cfg) -> bool:
    """Проверка арифметики режимов на конфиге-заглушке (без подмены боевого файла)."""
    from agents.base_agent import CoverageReport
    report = CoverageReport(known=["a", "b"], missing=["c"], unknown=[],
                            ratio=2 / 3, symbolic_threshold=1.0,
                            hybrid_threshold=0.6)
    return report.mode == "hybrid"


def test_plan_and_validate() -> None:
    from agents.base_agent import BaseAgent

    class Probe(BaseAgent):
        agent_id = "AG_STRUCTURAL"
        label = "проба"

        def decision(self, project, evidence=None):
            return {"enabled": True, "reason": "ок",
                    "parameters": {"fn": {"k": 1, "bad": float("nan")}}}

    agent = Probe(_cfg()).bind({"structural": {}, "welltops": {}})
    decision = agent.decide({"structural": {}, "welltops": {"w": []}}, {})
    check("base: decide возвращает план/режим/покрытие",
          decision.get("agent_id") == "AG_STRUCTURAL" and "coverage_report" in decision
          and "mode" in decision, str(sorted(decision))[:200])
    plan = agent.plan()
    check("base: plan() — PlanIR с функциями плана",
          plan is not None and plan.functions == ["fn"], str(plan.to_dict() if plan else None))
    findings = agent.validate()
    check("base: NaN-параметр → находка (не тихий пропуск)",
          any(not f.passed and "finite" in f.id for f in findings),
          str([f.id for f in findings]))

    class Empty(Probe):
        def decision(self, project, evidence=None):
            return {"enabled": True, "reason": "пусто", "parameters": {}}

    empty = Empty(_cfg()).bind({"structural": {}, "welltops": {}})
    empty.decide({"structural": {}, "welltops": {"w": []}}, {})
    check("base: включённый этап с пустым планом → critical-находка",
          any(f.severity == "critical" for f in empty.validate()),
          str([f.to_dict() for f in empty.validate()]))

    class Off(Probe):
        def decision(self, project, evidence=None):
            return {"enabled": False, "reason": "отключено по данным", "parameters": {}}

    off = Off(_cfg()).bind({"structural": {}})
    off.decide({"structural": {}}, {})
    check("base: выключенный этап не штрафуется (нет предмета проверки)",
          off.validate() == [], str(off.validate()))


def test_verify_and_state() -> None:
    from agents.contracts import Finding
    from agents.base_agent import BaseAgent

    class Probe(BaseAgent):
        agent_id = "AG_FACIES"
        label = "проба"

        def decision(self, project, evidence=None):
            return {"enabled": True, "reason": "ок", "parameters": {"fn": {"k": 1}}}

    cfg = _cfg()
    agent = Probe(cfg).bind({"geostat": {"n_facies": 3}})
    agent.decide({"geostat": {"n_facies": 3}}, {})
    ok = agent.verify([Finding(id="c1", severity="minor", passed=True)], {"kq": 1.0})
    check("base: verify без критичных провалов → не failed",
          ok.get("status") != "failed", str(ok)[:160])
    bad = agent.verify([Finding(id="c2", severity="critical", passed=False,
                                message="вырожденная геометрия")], {})
    check("base: verify с critical-провалом → failed", bad.get("status") == "failed",
          str(bad)[:160])
    state = agent.state()
    check("base: state() пригоден для отчёта",
          {"agent_id", "coverage_report", "decision", "plan"} <= set(state),
          str(sorted(state)))
    caps = agent.capabilities()
    check("base: capabilities без данных онтологии — пусто, без вымысла",
          caps == [], str([c.to_dict() for c in caps]))


def test_knowledge_base() -> None:
    from agents.knowledge import APPROVED, CANDIDATE, ExperienceRecord, KnowledgeBase

    cfg = _cfg()
    with tempfile.TemporaryDirectory() as tmp:
        kb = KnowledgeBase(cfg, root=Path(tmp))
        for run in range(3):
            kb.remember(ExperienceRecord(
                agent="AG_FACIES", stage="6. Фации", gate="G-FACIES", field_name="f",
                mode="symbolic", verdict="passed", outcome="passed",
                functions=["fn"], parameters={"fn": {"range": 3000 + run * 500}},
                metrics={"kq": 1.0}))
        kb.remember(ExperienceRecord(
            agent="AG_FACIES", stage="6. Фации", gate="G-FACIES", field_name="f",
            mode="symbolic", verdict="failed", outcome="failed",
            functions=["fn"], parameters={"fn": {"range": 99999}}))
        check("kb: записи сохранены", len(kb.history(agent="AG_FACIES")) == 4,
              str(kb.stats()))
        recalled = kb.recall(agent="AG_FACIES", stage="6. Фации",
                             functions=["fn"], parameters={"range": 3100},
                             k=2, min_status="")
        check("kb: recall отбирает удачный опыт", bool(recalled)
              and recalled[0].get("outcome") == "passed", str(recalled)[:200])
        suggest = kb.suggest(agent="AG_FACIES", stage="6. Фации",
                             functions=["fn"], parameters={"range": 3100}, k=3)
        check("kb: suggest — медиана удачных наблюдений (3000/3500/4000 → 3500)",
              suggest.get("fn", {}).get("range") == 3500, str(suggest))
        promoted = kb.promote()
        statuses = {row.get("status") for row in kb.history(agent="AG_FACIES")}
        check("kb: продвижение знания candidate→repeatable→approved",
              APPROVED in statuses and promoted.get("changed", 0) > 0,
              f"{promoted} statuses={statuses}")
        failed_rows = [r for r in kb.history(agent="AG_FACIES")
                       if r.get("outcome") == "failed"]
        check("kb: провальный опыт остаётся CANDIDATE (не влияет на план)",
              failed_rows and failed_rows[0].get("status") == CANDIDATE,
              str(failed_rows)[:160])
        empty = KnowledgeBase(cfg, root=Path(tmp) / "empty")
        check("kb: пустая БЗ → пустые подсказки (неизвестное != ложь)",
              empty.recall(agent="AG_FACIES") == [] and empty.suggest(
                  agent="AG_FACIES", functions=["fn"]) == {}, str(empty.stats()))


def test_agent_memory_cycle() -> None:
    """Сквозной цикл: решение → валидация → вердикт → запись опыта → подсказка."""
    from agents.base_agent import BaseAgent
    from agents.knowledge import KnowledgeBase

    cfg = _cfg()

    class Probe(BaseAgent):
        agent_id = "AG_PETROPHYSICS"
        label = "проба"

        def decision(self, project, evidence=None):
            return {"enabled": True, "reason": "ок",
                    "parameters": {"grid_fn": {"range_main": 3500.0}}}

    with tempfile.TemporaryDirectory() as tmp:
        kb = KnowledgeBase(cfg, root=Path(tmp))
        agent = Probe(cfg, kb=kb).bind({"petrophysics": {}})
        agent.decide({"field": "f", "petrophysics": {}}, {})
        agent.remember({"verdict": "passed", "gate": "G-PETRO", "attempts": 1},
                       metrics={"kq": 0.8})
        rows = kb.history(agent="AG_PETROPHYSICS")
        check("base: remember() пишет опыт решения в БЗ", len(rows) == 1, str(rows))
        check("base: в опыте есть функции/параметры/метрики",
              rows and rows[0].get("functions") == ["grid_fn"]
              and rows[0].get("metrics", {}).get("kq") == 0.8, str(rows)[:200])
        hint = agent.suggest(functions=["grid_fn"])
        check("base: suggest() читает свой же опыт",
              hint.get("grid_fn", {}).get("range_main") == 3500.0, str(hint))
        none = agent.reconsider([])
        check("base: reconsider без провалов → none", none.get("action") == "none",
              str(none))
        escalated = BaseAgent(cfg, kb=KnowledgeBase(cfg, root=Path(tmp) / "e"))
        check("base: reconsider без опыта → escalate (не выдумывает правку)",
              escalated.reconsider([__import__("agents.contracts", fromlist=["Finding"])
                                    .Finding(id="x", severity="major", passed=False,
                                             message="m")])["action"] == "escalate")


def test_static_knowledge() -> None:
    from agents.knowledge import StaticKnowledge

    cfg = _cfg()
    static = StaticKnowledge(cfg.path("agents.bdi_dir", "ontology/bdi_knowledge/"
                                                 "neurosymbolic_agents"))
    stats = static.stats()
    check("static-kb: онтология BDI доступна", stats["available"], str(stats))
    check("static-kb: таблицы решений прочитаны", stats["decisions"] > 0, str(stats))
    check("static-kb: правила литературы прочитаны",
          stats["literature_rules"] > 0, str(stats))
    rules = static.rules_for(branch_id="BR_NS_COVERAGE_MODE")
    check("static-kb: правила развилки выбираются по данным",
          bool(rules) and all(r.get("branch_id") == "BR_NS_COVERAGE_MODE"
                              for r in rules), str(len(rules)))
    empty = StaticKnowledge(None)
    check("static-kb: без каталога — пусто, без падения",
          not empty.available and empty.decisions() == [], str(empty.stats()))


def test_backward_compat() -> None:
    """Наследники v5 продолжают работать, старые ключи решения сохранены."""
    from agents.facies_policy import decide_facies
    from agents.grid_policy import decide_grid
    from agents.petrophysics_policy import decide_petrophysics
    from agents.structure_policy import decide_erosion

    base = {"structural": {"interval_top_marker": "M1", "interval_base_marker": "M2",
                           "erosion": "auto", "erosion_steps": ["s1"],
                           "erosion_when_top_coverage_lt": 0.8}}
    full = {"welltops": {"w1": [("M1", 1.0)], "w2": [("M1", 2.0)]}}
    d = decide_erosion(base, full)
    check("compat: structure_policy сохраняет enabled/coverage/reason",
          d["enabled"] is False and d["coverage"] == 1.0 and bool(d["reason"]),
          str(d)[:200])
    check("compat: structure_policy добавляет поля v2 (mode/plan/agent_id)",
          {"mode", "plan", "agent_id", "missing"} <= set(d), str(sorted(d)))
    partial = {"welltops": {"w1": [("M1", 1.0)], "w2": [("M2", 2.0)]}}
    check("compat: врез строится при покрытии ниже порога",
          decide_erosion(base, partial)["enabled"] is True,
          str(decide_erosion(base, partial))[:160])
    gd = decide_grid({"pipeline": [{"steps": [{"function": "grid_fn",
                                               "parameters": {"min_x": 0, "length_x": 10,
                                                              "step_x": 5, "step_y": 5},
                                               "objects": {"mesh": {"obj_type": "Grid3d"}}}]}]},
                     {"maps": [{"extent": {"x0": 0, "x1": 100, "y0": 0, "y1": 50}}]})
    check("compat: grid_policy считает бокс/шаг из данных",
          gd["enabled"] and gd["box"]["length_x"] == 100.0 and gd["expected_nx"] == 20,
          str(gd)[:200])
    fd = decide_facies({"geostat": {"n_facies": 3, "facies_method": "sis"}}, {})
    check("compat: facies_policy читает метод/классы из данных",
          fd["method"] == "sis" and fd["n_facies"] == 3
          and isinstance(fd.get("enabled"), bool), str(fd)[:200])
    check("compat: facies_policy без данных о кубе/сетке не включает этап (неизвестное != ложь)",
          fd["enabled"] is False, str(fd)[:200])
    import yaml
    graph = yaml.safe_load((ROOT / "ontology_project" / "gerasimovskoe.yaml")
                           .read_text(encoding="utf-8")) or {}
    fd_full = decide_facies(graph, {})
    check("compat: facies_policy на полном проектном графе включает этап",
          fd_full["enabled"] is True and fd_full["n_facies"] == 3, str(fd_full)[:200])
    pd_ = decide_petrophysics({"petrophysics": {"method": "kriging",
                                                "cubes": [{"log": "L", "cube": "C"}]}}, {})
    check("compat: petrophysics_policy читает кубы из данных",
          pd_["enabled"] and pd_["method"] == "kriging", str(pd_)[:160])


def main() -> int:
    for fn in (test_modes, test_plan_and_validate, test_verify_and_state,
               test_knowledge_base, test_agent_memory_cycle, test_static_knowledge,
               test_backward_compat):
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
