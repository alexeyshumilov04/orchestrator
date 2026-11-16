#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Тесты вкладки «Граф моделирования»: эндпоинт, сборка узлов/рёбер, frontend.

Проверяется БЕЗ запуска тНава и БЕЗ сети:
  * маршрут `GET /api/runs/{run_id}/graph` зарегистрирован, а функция-обработчик
    отдаёт 404/409 с причиной вместо пустого графа (правило 6);
  * `build_model_graph` собирает узлы/рёбра ТОЛЬКО из артефактов прогона
    (report.json, steps.json, agents/gates/*.json, agents/handoffs/*.json);
  * структура ответа: типы узлов, связность рёбер, tone-статусы, caps выдачи,
    работа БЕЗ ансамбля (ветвей нет — это не ошибка);
  * frontend не содержит НИ ОДНОГО зашитого названия этапа/шага/гейта/проверки:
    чёрный список формируется ИЗ ДАННЫХ реального отчёта (data-driven тест);
  * реальный прогон: этапы/шаги/ветви/лучшая ветвь/сетка попадают в граф.

Запуск: python tests/test_graph_tab.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FAILED: list[str] = []
CHECKS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f"  <-- {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def synthetic_run(root: Path, *, with_ensemble: bool = True,
                  findings: int = 2) -> Path:
    """Прогон-фикстура: нейтральные имена (никакого домена тестового поля)."""
    run_dir = Path(root)
    write_json(run_dir / "steps.json", {"steps": [
        {"index": 1, "stage": "S-ONE", "stage_label": "S-ONE",
         "operation": "G-A · AG-A", "function": "fn_a", "object": "", "status": "done",
         "message": "ok", "ts": "t1"},
        {"index": 2, "stage": "S-ONE", "operation": "G-A · AG-A", "function": "fn_b",
         "status": "skipped_by_policy", "message": "нет привязки", "ts": "t2"},
        {"index": 3, "stage": "S-TWO", "operation": "G-B · AG-B", "function": "fn_c",
         "status": "done", "message": "ok", "ts": "t3"},
    ], "summary": {"total": 3, "done": 2}})
    report = {
        "field": "FIELD-X",
        "steps": {"total": 3, "done": 2, "error": 0, "pending_template": 0},
        "agents": {
            "verdict": "passed",
            "stages": [
                {"index": 0, "stage": "S-ONE", "gate": "G-A", "agent": "AG-A",
                 "attempts": 1, "status": "passed", "degraded": False, "mode": "best",
                 "counts": {"major": {"passed": 1, "failed": 0}}, "findings": [],
                 "workflow": "stages/00.py", "skipped_steps": [2]},
                {"index": 1, "stage": "S-TWO", "gate": "G-B", "agent": "AG-B",
                 "attempts": 2, "status": "pending_execution", "degraded": True,
                 "mode": "best", "counts": {"major": {"passed": 1, "failed": 1}},
                 "findings": [], "workflow": "stages/01.py", "skipped_steps": []},
            ],
        },
        "critic": {"verdict": "unknown",
                   "counts": {"passed": 1, "failed": 0, "unknown": 2},
                   "checks": [{"rule_id": "R-1", "verdict": "passed", "note": "n1"},
                              {"rule_id": "R-2", "verdict": "unknown", "note": "n2"}]},
        "qaqc": {"total": 5, "passed": 2, "failed": 1, "not_applicable": 2,
                 "unknown": 0, "kq": 0.5, "kc": 0.4, "fitness": 0.45,
                 "physical": True},
        "model": {"grid_geometry": {"nx": 10, "ny": 20, "nz": 3}, "stoiip": 1.0},
        "tnav": {"ok": True},
        "model_artifacts": {"verdict": "saved", "manifest": "m.json", "files": 2,
                            "bytes": 10, "sha256": {"a": "b"}},
    }
    if with_ensemble:
        report["project"] = {
            "variants_total": 2,
            "ensemble": {"root": "GRP-X", "models_dir": "models", "metric_name": "METRIC",
                         "best": "B2", "scored": 2, "invalid_variations": [],
                         "branches": [
                             {"id": "B1", "label": "base", "parameters": {},
                              "path": "models/B1/x.snp", "workflow": "wf1"},
                             {"id": "B2", "label": "smooth", "parameters": {"p": 1},
                              "path": "models/B2/x.snp", "workflow": "wf2"},
                         ]},
        }
    write_json(run_dir / "report.json", report)
    gate_findings = []
    for index in range(findings):
        gate_findings.append({
            "id": f"chk.{index}", "severity": "major" if index % 2 else "critical",
            "passed": index != 0, "title": f"проверка {index}",
            "message": "message", "source": "builtin",
            "remediation": f"исправить {index}" if index == 0 else "",
            "evidence": {"n": index}, "state": ""})
    write_json(run_dir / "agents" / "gates" / "G-A.json",
               {"gate_id": "G-A", "status": "passed", "kq": 1.0, "kc": 0.9,
                "physical": True, "counts": {"critical": {"passed": 1, "failed": 0}},
                "findings": gate_findings, "failed": 0, "unverified": [],
                "decider": "auto", "mode": "best", "attempts": 1})
    write_json(run_dir / "agents" / "gates" / "G-B.json",
               {"gate_id": "G-B", "status": "failed", "kq": 0.2, "kc": 0.1,
                "physical": False, "counts": {"major": {"passed": 0, "failed": 1}},
                "findings": [{"id": "chk.fail", "severity": "critical", "passed": False,
                              "title": "провал", "message": "m", "source": "builtin",
                              "remediation": "исправить", "evidence": {}, "state": ""}],
                "failed": 1, "unverified": ["u"], "decider": "auto", "mode": "best",
                "attempts": 2})
    write_json(run_dir / "agents" / "handoffs" / "01_G-A.json",
               {"id": "G-A:1", "handoff_id": "H-1", "from_agent": "AG-A",
                "to_agent": "AG-B", "from_stage": "S-ONE", "to_stage": "S-TWO",
                "verdict": "passed", "degraded": False, "bypass_reason": "",
                "unresolved_findings": [], "uncertainties": ["u1"],
                "assumptions": {}, "evidence_hash": "abc",
                "lineage": ["S-ONE", "S-TWO"],
                "artifact_revisions": [{"path": "stages/00.py", "sha256": "deadbeef"}],
                "units_crs": {"crs": "x"}, "qa": {"status": "passed"}, "waiver": ""})
    write_json(run_dir / "agents" / "handoffs" / "02_G-B.json",
               {"id": "G-B:2", "from_agent": "AG-B", "from_stage": "S-TWO",
                "to_stage": "S-TWO", "verdict": "pending_execution", "lineage": []})
    return run_dir


def main() -> int:
    try:
        import api
    except ImportError as exc:                      # окружение без fastapi
        print(f"[OK ] api: тесты пропущены (нет fastapi): {exc}")
        print("\n=== ИТОГ ===\nпроверок: 0 | провалено: 0")
        return 0

    # ── 1. маршрут и изоляция состояния ─────────────────────────────────────
    state_before = api._STATE_FILE
    api._STATE_FILE = Path(tempfile.mkdtemp(prefix="graph_state_")) / "_web_state.json"
    paths = {(getattr(r, "path", ""), tuple(sorted(getattr(r, "methods", []) or [])))
             for r in api.app.routes}
    check("api: GET /api/runs/{run_id}/graph зарегистрирован",
          ("/api/runs/{run_id}/graph", ("GET",)) in paths,
          str(sorted(p for p, _ in paths if "graph" in p)))
    check("api: прежние маршруты прогонов не потеряны",
          ("/api/runs", ("GET",)) in paths and ("/api/runs/{run_id}", ("GET",)) in paths
          and ("/api/runs/{run_id}/maps", ("GET",)) in paths)

    # ── 2. сборка графа на фикстуре (нейтральные имена) ─────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = synthetic_run(Path(tmp) / "run")
        graph = api.build_model_graph(run_dir, run_id="r1", field="FIELD-X",
                                      run_status="done")
        check("граф: available и узлы/рёбра собраны",
              graph.get("available") and len(graph["nodes"]) > 10
              and len(graph["edges"]) > 10, str(len(graph.get("nodes") or [])))
        types = {n["type"] for n in graph["nodes"]}
        check("граф: типы узлов (этап/шаг/агент/гейт/проверка/Метакритик/ветвь/манифест)",
              {"stage", "step", "agent", "gate", "check", "critic", "ensemble",
               "branch", "artifact"} <= types, str(sorted(types)))
        ids = {n["id"] for n in graph["nodes"]}
        dangling = [e for e in graph["edges"] if e["from"] not in ids or e["to"] not in ids]
        check("граф: рёбра связывают существующие узлы", not dangling, str(dangling[:3]))
        kinds = {e["type"] for e in graph["edges"]}
        check("граф: типы рёбер (содержит/далее/агент/гейт/проверки/ветвь/lineage)",
              {"contains", "next", "agent", "gate", "checks", "branch",
               "lineage"} <= kinds, str(sorted(kinds)))
        check("граф: у каждого узла есть id/тип/подпись/тон/позиция",
              all({"id", "type", "label", "tone", "col", "row"} <= set(n)
                  for n in graph["nodes"]))
        check("граф: статусы окрашены данными (tone из отчёта)",
              graph["legend"]["tones"] and
              any(n["tone"] == "bad" for n in graph["nodes"])
              and any(n["tone"] == "ok" for n in graph["nodes"]),
              str(graph["legend"]))
        gate_a = next(n for n in graph["nodes"] if n["id"] == "gate:G-A")
        gate_b = next(n for n in graph["nodes"] if n["id"] == "gate:G-B")
        check("граф: тон гейта из его статуса (passed/failed)",
              gate_a["tone"] == "ok" and gate_b["tone"] == "bad",
              f"{gate_a['tone']}/{gate_b['tone']}")
        failed_check = next(n for n in graph["nodes"] if n["id"] == "check:G-A:chk.0")
        check("граф: проверка с remediation и свидетельством",
              failed_check["tone"] == "bad"
              and failed_check["attrs"]["remediation"]
              and failed_check["attrs"]["evidence"] is not None,
              str(failed_check["attrs"])[:160])
        agent = next(n for n in graph["nodes"] if n["id"] == "agent:0")
        check("граф: решение агента содержит свидетельства и lineage",
              agent["attrs"].get("evidence_hash") and agent["attrs"].get("lineage")
              and agent["attrs"].get("from_agent") == "AG-A",
              str(agent["attrs"])[:160])
        best = next(n for n in graph["nodes"] if n["id"] == "branch:B2")
        check("граф: лучшая ветвь помечена, параметры ветви в атрибутах",
              best["attrs"]["best"] and best["tone"] == "ok"
              and best["attrs"]["parameters"] == {"p": 1}, str(best["attrs"])[:160])
        critic = next(n for n in graph["nodes"] if n["id"] == "critic")
        check("граф: Метакритик — сводка + выборка правил",
              critic["attrs"]["rules_total"] == 2
              and len(critic["attrs"]["rules_sample"]) == 1
              and critic["attrs"]["qaqc"]["fitness"] == 0.45,
              str(critic["attrs"])[:160])
        summary = graph["summary"]
        check("граф: сводка (этапы/шаги/гейты/ветви/сетка/Метакритик)",
              summary["stages_total"] == 2 and summary["steps_total"] == 3
              and summary["gates_total"] == 2 and summary["branches_total"] == 2
              and summary["best_branch"] == "B2"
              and summary["grid"] == {"nx": 10, "ny": 20, "nz": 3},
              json.dumps(summary, ensure_ascii=False)[:200])
        check("граф: источники — файлы артефактов",
              str(graph["sources"]["report"]).endswith("report.json")
              and graph["sources"]["gates_dir"] and graph["sources"]["handoffs_dir"],
              str(graph["sources"]))
        dry = api.build_model_graph(run_dir, run_id="r1", source="dry")
        check("граф: выбор источника отчёта (source=dry) и список доступных",
              dry["available"] and dry["sources"]["report_kind"] == "dry"
              and any(item["kind"] == "dry" for item in dry["sources"]["available"]),
              str(dry["sources"])[:160])

        # ── согласованность артефактов (каталог прогона переиспользуется) ────
        check("артефакты: время записи каждого источника в ответе",
              {item["role"] for item in graph["sources"]["artifacts"]}
              == {"report", "steps", "gates", "handoffs"}
              and all(item.get("mtime") and item.get("ts")
                      for item in graph["sources"]["artifacts"]),
              str(graph["sources"]["artifacts"])[:160])
        check("артефакты: согласованный прогон → True, без предупреждения",
              graph["summary"]["artifacts_consistent"] is True
              and not any("РАЗНЫХ прогонов" in w for w in graph["warnings"]),
              f'{graph["summary"]["artifacts_consistent"]} {graph["warnings"]}')
        stale = synthetic_run(Path(tmp) / "run-stale")
        old = (stale / "report.json").stat().st_mtime
        os.utime(stale / "steps.json", (old + 3600, old + 3600))     # шаги «позже»
        mixed = api.build_model_graph(stale, run_id="r1b")
        check("артефакты: разные прогоны → видимое предупреждение (не маскируем)",
              mixed["summary"]["artifacts_consistent"] is False
              and any("РАЗНЫХ прогонов" in w for w in mixed["warnings"]),
              str(mixed["warnings"])[:170])
        only = Path(tmp) / "run-only-report"
        only.mkdir(parents=True, exist_ok=True)
        write_json(only / "report.json", {"field": "FIELD-X", "agents": {"stages": []}})
        lonely = api.build_model_graph(only, run_id="r1c")
        check("артефакты: сравнивать нечего → None (неизвестное != ложь)",
              lonely["summary"]["artifacts_consistent"] is None,
              str(lonely["summary"]["artifacts_consistent"]))

    # ── 3. прогон БЕЗ ансамбля и прогон без отчёта ──────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = synthetic_run(Path(tmp) / "run", with_ensemble=False)
        graph = api.build_model_graph(run_dir, run_id="r2")
        check("граф без ансамбля: узлы есть, ветвей нет — это не ошибка",
              graph["available"] and not any(n["type"] == "ensemble"
                                             for n in graph["nodes"])
              and any("ансамбль" in w for w in graph["warnings"]),
              str(graph["warnings"])[:120])
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "empty"
        empty.mkdir(parents=True, exist_ok=True)
        graph = api.build_model_graph(empty, run_id="r3")
        check("граф без отчёта: available=False и причина (не пустой граф)",
              graph["available"] is False and not graph["nodes"]
              and "report.json" in str(graph.get("reason")), str(graph.get("reason")))

    # ── 4. caps выдачи проверок ─────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = synthetic_run(Path(tmp) / "run",
                                findings=api._GRAPH_MAX_CHECKS_PER_GATE + 5)
        graph = api.build_model_graph(run_dir, run_id="r4")
        checks = [n for n in graph["nodes"] if n["type"] == "check"]
        check("граф: предел выдачи проверок соблюдён и виден в warnings",
              len([n for n in checks if n["id"].startswith("check:G-A:")])
              <= api._GRAPH_MAX_CHECKS_PER_GATE
              and any("предел" in w for w in graph["warnings"]),
              str(graph["warnings"])[:140])

    # ── 5. обработчик эндпоинта: 404/409/200 (без сети) ─────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = synthetic_run(Path(tmp) / "run")
        api._RUNS["graph-test"] = api.RunRecord(run_id="graph-test", field="FIELD-X",
                                               status="done",
                                               result={"run_dir": str(run_dir)})
        try:
            payload = api.run_graph("graph-test")
            check("эндпоинт: отдаёт граф и run_id", payload.get("available")
                  and payload.get("run_id") == "graph-test")
        except Exception as exc:                    # noqa: BLE001
            check("эндпоинт: отдаёт граф и run_id", False, str(exc))
        api._RUNS["graph-no-report"] = api.RunRecord(
            run_id="graph-no-report", field="F", 
            result={"run_dir": str(Path(tmp) / "other")})
        try:
            api.run_graph("graph-no-report")
            check("эндпоинт: прогон без отчёта → 409 с причиной", False, "исключения нет")
        except Exception as exc:                    # noqa: BLE001
            status = getattr(exc, "status_code", None)
            check("эндпоинт: прогон без отчёта → 409 с причиной",
                  status == 409 and "отчёт" in str(getattr(exc, "detail", exc)),
                  f"{status} {getattr(exc, 'detail', exc)}")
        try:
            api.run_graph("нет-такого-прогона")
            check("эндпоинт: неизвестный прогон → 404", False, "исключения нет")
        except Exception as exc:                    # noqa: BLE001
            check("эндпоинт: неизвестный прогон → 404",
                  getattr(exc, "status_code", None) == 404, str(exc))
        try:
            api.run_graph("graph-test", source="нет-такого-источника")
            check("эндпоинт: неизвестный источник отчёта → 400", False,
                  "исключения нет")
        except Exception as exc:                    # noqa: BLE001
            check("эндпоинт: неизвестный источник отчёта → 400",
                  getattr(exc, "status_code", None) == 400
                  and "auto" in str(getattr(exc, "detail", exc)),
                  f"{getattr(exc, 'status_code', None)} {getattr(exc, 'detail', exc)}")
        source_exc = None
        try:
            api.run_graph("graph-test", source="execute")
            check("эндпоинт: source=execute доступен", True)
        except Exception as exc:                    # noqa: BLE001
            source_exc = exc
            check("эндпоинт: source=execute доступен", False, str(exc))
        finally:
            api._RUNS.pop("graph-test", None)
            api._RUNS.pop("graph-no-report", None)

    # ── 6. frontend: НИ ОДНОГО зашитого домена (чёрный список ИЗ ДАННЫХ) ─────
    app_js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    index_html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    check("frontend: запрашивает эндпоинт графа", "/graph" in app_js)
    check("frontend: вкладка «Граф моделирования» есть в HTML",
          'data-view="model-graph"' in index_html and "viewGraph" in index_html)
    check("frontend: подписи узлов берутся из payload",
          "n.label" in app_js and "n.subtitle" in app_js
          and ("n.attrs" in app_js or "node.attrs" in app_js))
    domain_blacklist: set[str] = set()
    real_report = ROOT / "runs" / "run_Герасимовское" / "report_execute.json"
    if real_report.is_file():
        try:
            data = json.loads(real_report.read_text(encoding="utf-8"))
            for stage in ((data.get("agents") or {}).get("stages") or []):
                value = str(stage.get("stage") or "").strip()
                if len(value) >= 4:
                    domain_blacklist.add(value)
            for stage in ((data.get("agents") or {}).get("stages") or []):
                value = str(stage.get("gate") or "").strip()
                if len(value) >= 3:
                    domain_blacklist.add(value)
            for branch in (((data.get("project") or {}).get("ensemble") or {})
                           .get("branches") or []):
                if branch.get("id"):
                    domain_blacklist.add(str(branch["id"]))
        except (OSError, ValueError):
            domain_blacklist = set()
    check("frontend: чёрный список собран ИЗ ДАННЫХ реального отчёта",
          len(domain_blacklist) >= 5, str(sorted(domain_blacklist)[:5]))
    leaked = sorted(name for name in domain_blacklist
                    if name in app_js or name in index_html)
    check("frontend: доменных названий нет (данные приходят из API)", not leaked,
          str(leaked[:5]))

    # ── 7. реальный прогон (если артефакт на месте) ─────────────────────────
    if real_report.is_file():
        graph = api.build_model_graph(ROOT / "runs" / "run_Герасимовское",
                                      run_id="real", run_status="done", execute=True)
        summary = graph["summary"]
        check("реальный прогон: этапы/шаги/ветви/лучшая/сетка в графе",
              summary["stages_total"] >= 10 and summary["steps_total"] >= 40
              and summary["branches_total"] == 5 and summary["best_branch"] == "S002"
              and (summary["grid"] or {}).get("nz") == 22,
              json.dumps(summary, ensure_ascii=False)[:220])
        check("реальный прогон: проверки гейтов попали в узлы",
              len([n for n in graph["nodes"] if n["type"] == "check"]) >= 10,
              str(len([n for n in graph["nodes"] if n["type"] == "check"])))
        check("реальный прогон: решения агентов с lineage",
              any(n["type"] == "agent" and (n["attrs"].get("lineage"))
                  for n in graph["nodes"]))
        auto = api.build_model_graph(ROOT / "runs" / "run_Герасимовское",
                                     run_id="real-auto", run_status="done")
        check("выбор отчёта без подсказки: предпочитается отчёт с данными выполнения",
              (auto["summary"] or {}).get("branches_total") == 5,
              str((auto["summary"] or {}).get("branches_total")))
        exec_graph = api.build_model_graph(ROOT / "runs" / "run_Герасимовское",
                                           run_id="real-exec", source="execute")
        check("source=execute: граф реального прогона (5 ветвей, best, сетка 22)",
              exec_graph["sources"]["report_kind"] == "execute"
              and exec_graph["summary"]["branches_total"] == 5,
              str(exec_graph["summary"].get("branches_total")))
        check("источники: в каталоге видны оба отчёта (для выбора в интерфейсе)",
              {item["kind"] for item in exec_graph["sources"]["available"]}
              == {"execute", "dry"},
              str(exec_graph["sources"]["available"]))
    else:
        print("[info] real report отсутствует — проверки реального прогона пропущены")

    api._STATE_FILE = state_before
    print(f"\n=== ИТОГ ===\nпроверок: {CHECKS} | провалено: {len(FAILED)}")
    for item in FAILED:
        print("  -", item)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
