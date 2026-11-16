"""StageRunner: поэтапное исполнение пайплайна агентами с гейтами передачи.

Режим staged (`execution.stage_mode: staged`):
  * каждый этап pipeline рендерится в ОТДЕЛЬНЫЙ файл `agents/stages/NN_<gate>.py`;
  * проект тНава открывается ОДИН раз, этапы исполняются последовательно (execute);
  * после этапа собираются свидетельства (static + runtime-пробники), гейт
    выносит вердикт; при провале — политика исчерпания (best|skip|halt|ask);
  * передача — HandoffMemo при passed/bypassed/waived, в dry-run — pending_execution
    (runtime-проверки не выполнялись);
  * артефакты: `agents/progress.json`, `agents/gates/<gate>.json`, `agents/handoffs/*.json`.

Fallback: если пайплайн не сопоставился с этапами, возвращаем {"mode": "monolithic"} —
координатор продолжает прежним контуром. Монолитный режим остаётся рабочим.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path

from agents import stage_map
from agents.advisor import StageAdvisor
from agents.checks import CheckRegistry
from agents.checks.adapters import package_evaluate, range_findings
from agents.contracts import (AWAITING, BYPASSED, DEGRADING, FAILED, PASSED, PENDING,  # noqa: F401
                              SKIPPED, HandoffMemo, run_verdict, save_json, sha256_file,
                              sha256_text)
from agents.evidence import build_static, check_context
from agents.facies_policy import decide_facies
from agents.gates import GateEngine, GateSpec
from agents.grid_policy import decide_grid
from agents.knowledge import ExperienceRecord, KnowledgeBase
from agents.petrophysics_policy import decide_petrophysics
from agents.registry import AgentRegistry
from agents.structure_policy import decide_erosion
from core.pipeline import DONE, ERROR, PENDING_TEMPLATE, RUNNING, Pipeline
from domain.tnav_probes import property_mean_code


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(text))[:40].strip("_") or "stage"


class StageRunner:
    """Поэтапный прогон с гейтами; использует координатор как исполнительную среду."""

    def __init__(self, coord, *, registry: AgentRegistry | None = None,
                 checks: CheckRegistry | None = None,
                 decisions=None, run_id: str = "") -> None:
        self.coord = coord
        self.cfg = coord.cfg
        self.registry = registry if registry is not None else AgentRegistry(self.cfg)
        # Реестр проверок — ИЗ ДАННЫХ: builtin/контракт (код) + пакет domain/qaqc по блокам
        # из checks.package_blocks + проверки ontology/qa_checks/*.csv. Data-проверки
        # помечены runtime (судят по значениям модели) — в dry-run пропускаются.
        self.checks = (checks if checks is not None
                       else CheckRegistry.from_config(self.cfg))
        self.engine = GateEngine(self.cfg, self.registry)
        self.builder = coord.workflow_builder()
        self.decisions = decisions      # DecisionBroker в API-прогоне (режим ask)
        self.run_id = str(run_id or "")
        self.advisor = StageAdvisor(self.cfg)   # LLM-пояснения (fail-safe; вердикт не меняет)

    # -- публичный вход ----------------------------------------------------------
    def run_staged(self, field: str, run_dir: Path, *, execute: bool = False,
                   on_event=None, on_log=None, staging: dict | None = None,
                   on_phase=None) -> dict:
        run_dir = Path(run_dir)
        graph = self.coord.project_graph(field)
        asg, issues = stage_map.assignments(graph, self.cfg, self.registry)
        nodes = self.coord.assembler(field, stage_dir=run_dir).node_genes()
        by_label = {str(n.stage or ""): n for n in nodes}
        # Шаги проектного графа по этапам — нужны для ЗАВИСИМОГО ПРОПУСКА
        # (`requires_object` у шага): объект-предпосылка отсутствует → шаг
        # помечается skipped_by_policy, а не падает в тНаве. Ключ и свидетельство
        # доступных объектов — ДАННЫЕ (workflow.requires_object_key /
        # workflow.available_objects_evidence); нет свидетельства → не пропускаем
        # («неизвестное != ложь»).
        steps_by_stage: dict[str, list[dict]] = {}
        for _stage in (graph.get("pipeline") or []):
            if isinstance(_stage, dict):
                steps_by_stage[str(_stage.get("stage") or "")] = [
                    s for s in (_stage.get("steps") or []) if isinstance(s, dict)]
        require_key = str(self.cfg.get("workflow.requires_object_key",
                                      "requires_object") or "requires_object")
        available_evidence = str(self.cfg.get("workflow.available_objects_evidence",
                                              "grid_properties") or "grid_properties")
        available_objects: set[str] = set()
        if not any(a.stage_key in by_label for a in asg):
            return {"mode": "monolithic"}
        rules = self.coord.function_rules()
        rule_map = {name: r for name, r in
                    ((n, rules.read(n)) for n in rules.all_names()) if r is not None}

        log = on_log if callable(on_log) else (lambda _m: None)

        def phase(name: str, detail: str = "", **extra) -> None:
            """Событие прогресса (не критично: ошибки колбэка глотаются)."""
            if callable(on_phase):
                try:
                    on_phase(name, detail, extra)
                except Exception:                  # noqa: BLE001
                    pass

        pipe = Pipeline(on_event=on_event)
        ctx = check_context(graph, self.cfg)
        static_ev = build_static(graph, run_dir, staging=staging)

        # ---- РЕШЕНИЯ АГЕНТОВ ЭТАПА (данные + БАЗА ЗНАНИЙ) ----------------------
        # Агенты вызываются с cfg/kb (политика полноты входов и опыт прошлых
        # прогонов); старый двухаргументный контракт поддержан tolerant-вызовом.
        kb = KnowledgeBase(self.cfg, run_dir=run_dir)
        agent_kw = {"cfg": self.cfg, "kb": kb, "registry": self.registry,
                    "gate_engine": self.engine}

        def _policy(fn, graph_data: dict, evidence: dict, label: str) -> dict:
            """Вызвать политику этапа: с cfg/kb, иначе — по старому контракту."""
            try:
                return fn(graph_data, evidence, **agent_kw) or {}
            except TypeError:
                log(f"{label}: политика без cfg/kb (совместимость старого контракта)")
                return fn(graph_data, evidence) or {}

        # СТРУКТУРНЫЙ АГЕНТ: рабочий интервал и «врез» (шаги пропускаются при disabled).
        erosion = _policy(decide_erosion, graph, static_ev, "структурный агент")
        skip_functions = (set(erosion.get("steps") or [])
                          if not erosion.get("enabled") else set())
        # НЕПОДТВЕРЖДЁННЫЕ ПРОБОЙ шаги (правило 8): не рендерятся и не исполняются,
        # иначе падает воркфлоу и гибнут все ветви ансамбля. Список — ДАННЫЕ
        # (workflow.unconfirmed_steps); причина видна в шине шагов и в отчёте.
        unconfirmed = [str(x) for x in (self.cfg.get("workflow.unconfirmed_steps") or [])]
        if unconfirmed:
            skip_functions |= set(unconfirmed)
            log("не подтверждены пробой — шаги пропускаются: " + ", ".join(unconfirmed))
        # Причина пропуска — СВОЯ для каждого шага (F-23).
        skip_reasons: dict[str, str] = {
            str(fn): ("сигнатура не подтверждена пробой на живой лицензии "
                      "(workflow.unconfirmed_steps, правило 8)")
            for fn in unconfirmed}
        if not erosion.get("enabled"):
            for fn in (erosion.get("steps") or []):
                skip_reasons.setdefault(str(fn), str(erosion.get("reason") or ""))
        if skip_functions:
            log(f"структурный агент: {erosion.get('reason', 'врез не требуется')}")

        # АГЕНТЫ СЕТКИ / ФАЦИЙ / ПЕТРОФИЗИКИ: политика из данных проекта.
        # Патчи параметров накладываются на этапы (как вариация) через `_variant_gene`.
        grid_dec = _policy(decide_grid, graph, static_ev, "агент сетки")
        facies_dec = _policy(decide_facies, graph, static_ev, "агент фаций")
        petro_dec = _policy(decide_petrophysics, graph, static_ev, "агент петрофизики")
        static_ev["grid_policy"] = grid_dec
        static_ev["facies_policy"] = facies_dec
        static_ev["petro_policy"] = petro_dec
        decisions_by_gate: dict[str, dict] = {"G-STRUCT": erosion, "G-GRID": grid_dec,
                                              "G-FACIES": facies_dec,
                                              "G-PETRO": petro_dec}
        policy_patches = {"G-GRID": grid_dec.get("parameters") or {},
                          "G-FACIES": facies_dec.get("parameters") or {},
                          "G-PETRO": petro_dec.get("parameters") or {}}
        for gate_id, dec in decisions_by_gate.items():
            cov = dec.get("coverage_report") or {}
            log(f"{gate_id}: режим {dec.get('mode', '—')} "
                f"(входы: {len(cov.get('known') or [])} ok, "
                f"{len(dec.get('missing') or [])} нет) — "
                f"{dec.get('reason') or dec.get('rationale') or ''}")

        stages_dir = run_dir / "agents" / "stages"
        gates_dir = run_dir / "agents" / "gates"
        handoffs_dir = run_dir / "agents" / "handoffs"
        blocks: list[str] = []
        index = 1
        stage_reports: list[dict] = []
        handoffs: list[dict] = []
        objects: set[str] = set()
        statuses: list[str] = []
        halted = awaiting = False
        tnav_ok, tnav_error = True, ""
        model_info: dict = {}
        agg_values: dict = {}       # значения модели для QA/QC (копится по этапам)

        client = None
        base_snp = run_dir / f"{field}.snp"
        if execute:
            client = self.coord.tnav()
            if callable(on_log):
                client.set_log(on_log)
            client.cfg.set("tnavigator.dry_run", False)
            client.dry_run = False
            for stale in (base_snp, base_snp.with_suffix(".snf")):
                try:
                    if stale.is_dir():
                        shutil.rmtree(stale, ignore_errors=True)
                    elif stale.exists():
                        stale.unlink()
                except OSError:
                    pass
            client.open(project_path=base_snp, create=True)
            # Папка проекта: у реального клиента — project_path(), у тестового
            # двойника может отсутствовать → берём каталог прогона (не падаем).
            project_path = getattr(client, "project_path", None)
            project_dir = None
            if callable(project_path):
                try:
                    project_dir = Path(str(project_path() or "")).parent
                except Exception:                       # noqa: BLE001 — папка не критична
                    project_dir = None
            self._ensure_export_dirs(project_dir or run_dir, log)
        try:
            qaqc_meta = None
            try:
                qaqc_meta = self.coord.metacritic()
            except Exception:                           # noqa: BLE001 — диапазоны опциональны
                qaqc_meta = None
            for a in asg:
                node = by_label.get(a.stage_key)
                spec = self.engine.spec(a.gate_id) or GateSpec(
                    id=a.gate_id or f"G-{a.stage_no}", agent=a.agent_id, stages=(a.stage_no,),
                    on_exhausted="halt")
                candidates = (self._remediation_candidates(graph, node, spec)
                              if execute else [])
                block_selection = tuple(str(x) for x in
                                        ((self.cfg.get("checks.package_blocks") or {})
                                         .get(spec.id) or []))
                start_index = index
                attempt, patch = 0, dict(policy_patches.get(spec.id) or {})
                phase("stage", f"{a.index + 1}/{len(asg)}: {a.stage_key}",
                      stage=a.stage_key, index=a.index + 1, total=len(asg))
                stage_blocks: list[str] = []
                wf_path = stages_dir / f"{a.index:02d}_{_slug(spec.id)}.py"
                wf_path.parent.mkdir(parents=True, exist_ok=True)
                wf_text = ""
                verdict = None
                metrics: dict = {}
                while True:
                    attempt += 1
                    index = start_index
                    # АГЕНТНАЯ СЕЛЕКЦИЯ ШАГОВ ОНТОЛОГИЧЕСКОГО ВЫВОДА (критерии в/г):
                    # стадия «доп. шаги онтологии» исполняется только теми шагами,
                    # чей агент-владелец ВКЛЮЧЁН в своём решении (правила — ДАННЫЕ
                    # ontology_extra_rules.yaml). Иначе шаг пропускается с причиной.
                    stage_skip, stage_reasons = skip_functions, skip_reasons
                    _extra_label = str(self.cfg.get("workflow.extra_stage_label",
                                                    "доп. шаги онтологии") or "")
                    if str(a.stage_key) == _extra_label:
                        for _fn in (graph.get("ontology_extra_steps") or []):
                            _rule = (graph.get("ontology_extra_rules") or {}).get(str(_fn)) or {}
                            _gate = str(_rule.get("gate") or "")
                            _key = str(_rule.get("decision_key") or "enabled")
                            _dec = decisions_by_gate.get(_gate) or {}
                            # Нет правила → шаг НЕ включается (неизвестное != ложь).
                            # `verified: false` → привязки объектов не подтверждены
                            # (например, ссылка на отсутствующий объект «Top»),
                            # поэтому шаг тоже не исполняется.
                            if (not _rule) or _rule.get("verified", True) is False \
                                    or _dec.get(_key) is not True:
                                stage_skip = set(stage_skip) | {str(_fn)}
                                stage_reasons = dict(stage_reasons)
                                if not _rule:
                                    _why = "нет правила применимости (ontology_extra_rules)"
                                elif _rule.get("verified", True) is False:
                                    _why = (f"привязки объектов не подтверждены: "
                                            f"{_rule.get('reason') or 'проверка пробой не пройдена'}")
                                else:
                                    _why = (f"агент {_gate or '—'} не включён "
                                            f"({_key} != true)")
                                stage_reasons[str(_fn)] = ("шаг онтологического вывода: "
                                                           + _why + " — пропущен по данным")
                    skipped_objects: list[dict] = []
                    stage_blocks, index, stage_objs = self._render_stage(
                        node, rule_map, index, pipe if attempt == 1 else None, a, spec,
                        params=patch or None, skip_functions=stage_skip,
                        skip_reason=str(erosion.get("reason") or ""),
                        skip_reasons=stage_reasons,
                        steps=steps_by_stage.get(a.stage_key) or [],
                        available=available_objects, require_key=require_key,
                        skipped_out=skipped_objects)
                    if attempt == 1:
                        objects.update(stage_objs)
                    wf_text = self.builder.assemble(stage_blocks) if stage_blocks else ""
                    wf_path.write_text(wf_text, encoding="utf-8")

                    # исполнение попытки (execute): отдельный файл на открытом проекте
                    if execute and client is not None and stage_blocks:
                        phase("execute", f"тНав: {a.stage_key} ({spec.id}), попытка {attempt}",
                              stage=a.stage_key, index=a.index + 1, total=len(asg))
                        try:
                            res = client.run_workflow(wf_path, save=True)
                            if not getattr(res, "ok", True):
                                tnav_ok = False
                                tnav_error = (getattr(res, "error", "")
                                              or "stage workflow failed")
                        except Exception as exc:            # noqa: BLE001
                            tnav_ok = False
                            tnav_error = str(exc)

                    # свидетельства и вердикт гейта
                    ev = dict(static_ev)
                    ev["stage"] = a.stage_key
                    if execute and client is not None:
                        # Свидетельство о КАРТАХ собирается ПОСЛЕ их отрисовки:
                        # иначе гейт проверяет файлы до появления PNG (F-19).
                        if any(str((it or {}).get("kind") or "") == "maps"
                               for it in spec.evidence):
                            self._ensure_maps(run_dir, log)
                        self._attach_runtime_evidence(ev, client, run_dir, graph, spec)
                    # Доступные объекты для зависимого пропуска (свидетельство из данных):
                    # нет свидетельства → множество пусто и пропусков по данным НЕТ.
                    new_objects = ev.get(available_evidence)
                    if isinstance(new_objects, (list, tuple, set)):
                        available_objects.update(str(x) for x in new_objects if str(x))
                    elif isinstance(new_objects, dict):
                        available_objects.update(str(x) for x in new_objects)
                    try:
                        qaqc_values = self.coord._qaqc_values(
                            field, ev.get("grid"), ev.get("well_tie") or [])
                    except Exception:                       # noqa: BLE001
                        qaqc_values = {}
                    if qaqc_values:
                        agg_values.update({k: v for k, v in qaqc_values.items()
                                           if v is not None})
                    gate_checks = self.checks.for_gate(spec.id)
                    has_static = any((not c.runtime and c.gate != "*")
                                     for c in gate_checks)
                    # Консервативная семантика dry-run: если гейт опирается на
                    # runtime-проверки (они в dry-run не исполняются), вердикт НЕ
                    # может быть `passed` — он остаётся pending_execution.
                    runtime_only = any(c.runtime for c in gate_checks)
                    findings = self.checks.run(spec.id, ev, ctx, include_runtime=execute)
                    metrics = {}
                    pkg_findings, pkg_metrics = package_evaluate(block_selection,
                                                                 qaqc_values)
                    findings += pkg_findings
                    metrics.update(pkg_metrics)
                    if qaqc_meta is not None:
                        # КОД параметра каталога и ключ свидетельства — ДАННЫЕ
                        # (`checks.properties.<роль>.{cube, mean_key}`), не литералы.
                        range_vals = {}
                        props = self.cfg.get("checks.properties", {}) or {}
                        for _role, item in (props.items() if isinstance(props, dict) else []):
                            if not isinstance(item, dict):
                                continue
                            code = str(item.get("cube") or "")
                            mean_key = str(item.get("mean_key") or "")
                            if code and mean_key and ev.get(mean_key) is not None:
                                range_vals[code] = ev[mean_key]
                        findings += range_findings(qaqc_meta, range_vals)
                    verdict = self.engine.evaluate(spec, findings,
                                                   metrics=metrics or None, attempts=attempt)
                    subst_ids = {c.id for c in gate_checks if c.gate != "*"}
                    executed = any(f.id in subst_ids for f in findings)

                    def _dry_adjust(v: GateVerdict, applied: bool) -> GateVerdict:
                        """Dry-run не выдумывает passed: нет данных — pending_execution."""
                        if execute or v.status != PASSED:
                            return v
                        if runtime_only or not has_static:
                            return self.engine.resolve(
                                v, PENDING,
                                reason="dry-run: runtime-проверки не выполнялись")
                        if not applied:
                            return self.engine.resolve(
                                v, PENDING,
                                reason="нет применённых проверок: данных этапа нет")
                        return v

                    verdict = _dry_adjust(verdict, executed or bool(pkg_findings))
                    if verdict.status != FAILED:
                        break

                    # провал: rework по данным-кандидатам, затем политика исчерпания
                    if attempt < spec.max_attempts and candidates:
                        save_json(gates_dir / f"{spec.id}.attempt{attempt}.json", verdict)
                        next_patch = candidates.pop(0)
                        for fn, pv in next_patch.items():
                            patch.setdefault(fn, {}).update(pv)
                        log(f"этап {a.index} [{spec.id}]: попытка {attempt} не прошла — "
                            f"rework (попытка {attempt + 1}/{spec.max_attempts})")
                        continue
                    status, reason = self.engine.exhaust(spec, verdict)
                    if (status == AWAITING and self.decisions is not None
                            and self.run_id):
                        decision = self.decisions.request(self.run_id, spec.id,
                                                          verdict.to_dict())
                        if decision:
                            try:
                                verdict = self.engine.apply_decision(
                                    verdict, str(decision.get("action") or ""),
                                    author=str(decision.get("author") or ""),
                                    comment=str(decision.get("comment") or ""))
                                status = verdict.status
                                reason = f"оператор: {decision.get('action')}"
                            except ValueError:
                                pass
                        else:
                            reason = "решение не получено (таймаут/остановка сервиса)"
                    verdict = self.engine.resolve(verdict, status, reason=reason)
                    break

                # контракт и меморандум финального вердикта
                phase("gate", f"{spec.id}: {verdict.status}",
                      stage=a.stage_key, index=a.index + 1, total=len(asg))
                nxt = next((x for x in asg if x.index == a.index + 1), None)
                lineage = [s["stage"] for s in stage_reports] + [a.stage_key]
                memo = self._build_memo(graph, a, nxt, spec, verdict, wf_path, lineage)
                contract = self.checks.run(spec.id,
                                           {"handoff": memo.to_dict(),
                                            "workflow_text": wf_text},
                                           ctx, include_runtime=False)
                if any(not f.passed for f in contract):
                    verdict = self.engine.evaluate(spec, list(verdict.findings) + contract,
                                                   metrics=metrics or None, attempts=attempt)
                    verdict = _dry_adjust(verdict, executed or bool(pkg_findings))
                    if verdict.status == FAILED:
                        status, reason = self.engine.exhaust(spec, verdict)
                        verdict = self.engine.resolve(verdict, status, reason=reason)
                elif contract:
                    verdict = replace(verdict, findings=list(verdict.findings) + contract)
                memo = self._build_memo(graph, a, nxt, spec, verdict, wf_path, lineage)
                note = ""
                if verdict.status in (FAILED, BYPASSED, SKIPPED):
                    note = self.advisor.explain(agent_id=a.agent_id, stage_key=a.stage_key,
                                                gate_id=spec.id, status=verdict.status,
                                                findings=verdict.findings)
                blocks.extend(stage_blocks)
                if memo:
                    memo.save(handoffs_dir / f"{a.index:02d}_{spec.id}.json")
                save_json(gates_dir / f"{spec.id}.json", verdict)
                # ОПЫТ АГЕНТА → БАЗА ЗНАНИЙ (накопительный и внутрипрогонный журналы).
                self._remember_experience(kb, graph, a, spec, memo, verdict,
                                          decisions_by_gate.get(spec.id) or {},
                                          metrics, log)
                handoffs.append(memo.to_dict() if memo else {})
                statuses.append(verdict.status)
                stage_reports.append({
                    "index": a.index, "stage": a.stage_key, "gate": spec.id,
                    "agent": a.agent_id, "attempts": attempt, "status": verdict.status,
                    "degraded": verdict.status in DEGRADING,
                    "counts": verdict.counts, "mode": verdict.mode,
                    "agent_mode": (decisions_by_gate.get(spec.id) or {}).get("mode", ""),
                    "skipped_steps": list(skipped_objects),
                    "comment": verdict.comment, "llm_note": note,
                    "findings": [f.to_dict() for f in verdict.findings if not f.passed],
                    "workflow": str(wf_path)})
                log(f"этап {a.index} [{spec.id}/{a.agent_id}]: {verdict.status}"
                    + (f" (попыток: {attempt})" if attempt > 1 else "")
                    + (f" — {verdict.comment}" if verdict.comment else ""))
                if verdict.status in (FAILED, AWAITING):
                    halted = verdict.status == FAILED
                    awaiting = verdict.status == AWAITING
                    break
            if execute and client is not None:
                # СНЯТИЕ ЗНАЧЕНИЙ МОДЕЛИ С ОТКРЫТОГО ПРОЕКТА — независимо от того,
                # деградировала ли ОТДЕЛЬНАЯ стадия: иначе `grid_geometry` и метрики
                # теряются при любом сбое шага, хотя модель построена (F-21).
                try:
                    model_info = {
                        "grid_geometry": self.coord._read_grid_geometry(client),
                        "stoiip": self.coord._read_stoiip(client),
                    }
                    log("значения модели сняты с открытого проекта: "
                        + ", ".join(f"{k}={'есть' if v else 'нет'}"
                                    for k, v in model_info.items()))
                except Exception as exc:                # noqa: BLE001 — не роняем прогон
                    model_info = {"error": str(exc)}
                    log(f"чтение модели: не удалось — {exc}")
                try:
                    # Путь сохранения — ДАННЫЕ (project.save_path); по умолчанию
                    # сохраняем в каталог прогона, чтобы проект можно было ОТКРЫТЬ
                    # в GUI (нужно, например, для снимка диалогов тНава).
                    save_path = str(self.cfg.get("project.save_path", "") or "") or None
                    dest = None
                    if save_path:
                        dest = Path(save_path)
                    else:
                        dest = Path(run_dir) / f"{field}.snp"
                    try:
                        client.save_project(str(dest))
                    except TypeError:                   # API без аргумента пути
                        client.save_project()
                    ok_saved = dest.is_file()
                    log(f"проект сохранён: {dest} ({'есть' if ok_saved else 'файл не появился'})")
                except Exception as exc:                # noqa: BLE001 — не роняем прогон
                    log(f"сохранение проекта не удалось: {exc}")
            if execute:
                self._ensure_maps(run_dir, log)
        finally:
            if execute and client is not None:
                try:
                    client.close()
                except Exception:                       # noqa: BLE001
                    pass

        try:
            agg_values.update({k: v for k, v in
                               (self.coord._qaqc_values(field, None, []) or {}).items()
                               if v is not None})
        except Exception:                               # noqa: BLE001 — сводка не критична
            pass
        qaqc_block = self._qaqc_report(agg_values, run_dir, log)

        stages_summary = {
            "mode": "staged", "field": field,
            "workflow_text": self.builder.assemble(blocks),
            "steps": pipe.to_dict(),
            "objects": sorted(objects),
            # Доступные объекты, подтверждённые свидетельством (для зависимого
            # пропуска шагов в ветвях ансамбля — единый критерий с базовым контуром).
            "available_objects": sorted(available_objects),
            "issues": issues,
            "stages": stage_reports,
            "handoffs": handoffs,
            "structural": {"erosion": erosion},
            "grid_policy": grid_dec,
            "facies_policy": facies_dec,
            "petro_policy": petro_dec,
            "qaqc": qaqc_block,
            # Значения модели, снятые с ОТКРЫТОГО проекта до закрытия (F-21):
            # доступны даже при деградировавшей отдельной стадии.
            "model": model_info,
            "verdict": run_verdict(statuses),
            "tnav_ok": tnav_ok, "tnav_error": tnav_error,
            "halted": halted, "awaiting": awaiting,
        }
        stages_summary["agents"] = {
            "assignments": [asdict(a) for a in asg],
            "gates": self.engine.to_dict(),
            "issues": issues,
            "verdict": stages_summary["verdict"],
            "stages": stage_reports,
        }
        save_json(run_dir / "agents" / "progress.json", stages_summary)
        steps_path = run_dir / "steps.json"
        steps_path.write_text(json.dumps(stages_summary["steps"], ensure_ascii=False,
                                         indent=2, default=str), encoding="utf-8")
        return stages_summary

    # -- каталоги выгрузок в папке проекта ---------------------------------------------
    def _ensure_export_dirs(self, project_dir: Path | str | None, log=None) -> list[str]:
        """Создать каталоги выгрузок в папке проекта (имена — данные `workflow.export_dirs`).

        Причина в коде оркестратора, а не в шаблоне: внутри элемента воркфлоу
        инструкции Python недопустимы («Could not recognize python code as workflow
        item»), а тНав каталогов не создаёт («Can't open file …»). Нет данных/папки —
        ничего не делаем (неизвестное != ложь), причина уходит в лог.
        """
        rels = [str(x) for x in (self.cfg.get("workflow.export_dirs") or [])]
        if not rels or not project_dir:
            return []
        base = Path(project_dir)
        if not base.is_dir():
            return []
        made: list[str] = []
        for rel in rels:
            try:
                (base / rel).mkdir(parents=True, exist_ok=True)
                made.append(rel)
            except OSError as exc:
                if callable(log):
                    log(f"каталог выгрузки «{rel}» не создан — {exc}")
        if made and callable(log):
            log(f"каталоги выгрузок: {', '.join(made)} в {base}")
        return made

    # -- память агента: запись опыта этапа в БЗ ----------------------------------------
    def _remember_experience(self, kb, graph: dict, a, spec: GateSpec, memo,
                             verdict, decision: dict, metrics: dict, log) -> None:
        """Записать опыт этапа в БЗ: решение агента + вердикт гейта + метрики.

        Пишутся только ФАКТЫ прогона (никаких «ожидаемых» значений): если запись
        не удалась, причина попадает в лог — молчаливой потери опыта нет.
        """
        if kb is None:
            return
        try:
            patches = decision.get("parameters") if isinstance(
                decision.get("parameters"), dict) else {}
            status = str(getattr(verdict, "status", "") or "")
            outcome = ("passed" if status in (PASSED, PENDING) else
                       "degraded" if status in DEGRADING else
                       "failed" if status else "")
            memo_dict = memo.to_dict() if memo is not None else {}
            kb.remember(ExperienceRecord(
                agent=str(getattr(a, "agent_id", "") or ""),
                stage=str(getattr(a, "stage_key", "") or ""),
                gate=str(spec.id or ""),
                field_name=str((graph or {}).get("field") or ""),
                mode=str(decision.get("mode") or ""),
                verdict=status,
                attempts=int(getattr(verdict, "attempts", 0) or 0),
                degraded=status in DEGRADING,
                outcome=outcome,
                functions=sorted(patches),
                parameters=patches,
                evidence_hash=str(memo_dict.get("evidence_hash") or ""),
                metrics={k: float(v) for k, v in (metrics or {}).items()
                         if isinstance(v, (int, float))},
                provenance=str(memo_dict.get("id") or "")))
        except Exception as exc:                        # noqa: BLE001 — БЗ не роняет прогон
            log(f"БЗ: опыт этапа {spec.id} не записан — {exc}")

    # -- карты прогона ---------------------------------------------------------------
    def _qaqc_report(self, values: dict, run_dir: Path, log=None) -> dict:
        """QA/QC верхнего уровня: сводка проверок + покрытие чеклиста (данные, не код).

        Собирается ``agents.checks.report``: блоки — из ``checks.package_blocks``,
        веса — из ``checks.fitness_alpha/fitness_beta``, проверки — из каталога
        (пакет + ``ontology/qa_checks/*.csv``). Пишет ``qaqc.json`` и
        ``qaqc_coverage.json`` в каталог прогона. Не роняет прогон: при сбое
        отдаёт честное «неизвестно» с причиной (правило 6).
        """
        try:
            from agents.checks.report import build_qaqc_artifacts
            block = build_qaqc_artifacts(self.cfg, values or {}, run_dir)
            if callable(log):
                log(f"QA/QC: проверок {block.get('total')}, применимо "
                    f"{block.get('applicable')}, провалено {block.get('failed')}, "
                    f"not_applicable {block.get('not_applicable')}, unknown "
                    f"{block.get('unknown')}; kq={block.get('kq')} kc={block.get('kc')} "
                    f"ff={block.get('fitness')} физично={block.get('physical')}")
            return block
        except Exception as exc:                        # noqa: BLE001 — сводка опциональна
            if callable(log):
                log(f"QA/QC: сводка не собрана — {exc}")
            return {"units": "checks", "total": None, "passed": None, "failed": None,
                    "not_applicable": None, "unknown": None, "by_block": {},
                    "kq": None, "kc": None, "fitness": None, "physical": None,
                    "failed_checks": [], "error": str(exc),
                    "reason": "QA/QC-сводка не собрана (см. error): неизвестное ≠ ложь"}

    def _ensure_maps(self, run_dir: Path, log=None) -> None:
        """Карты прогона: нативные выгрузки из проекта + фолбэк (данные config).

        Приоритет — `domain.qc.maps.ensure_maps` (рисует ВСЕ объявленные карты:
        нативные выгрузки свойства/карты из проекта + фолбэк по `checks.map_sources`).
        Если модуль недоступен — прежний фолбэк `domain.map_render.render_missing`
        (неизвестное != ложь: карты не выдумываются, отсутствие фиксируется проверкой).
        """
        names = [str(x) for x in (self.cfg.get("checks.map_files") or [])]
        sources = dict(self.cfg.get("checks.map_sources") or {})
        if not names:
            return
        try:
            from domain.qc.maps import ensure_maps
        except Exception as exc:                        # noqa: BLE001 — модуль опционален
            ensure_maps = None
            if callable(log):
                log(f"карты: domain.qc.maps недоступен ({exc}) — фолбэк")
        if ensure_maps is not None:
            try:
                done = ensure_maps(run_dir, self.cfg, self.coord.project_graph())
            except Exception as exc:                    # noqa: BLE001
                if callable(log):
                    log(f"карты: ensure_maps не отработал — {exc}")
                done = []
            if done:
                if callable(log):
                    log(f"карты: подготовлено {len(done)} ({', '.join(done)})")
                return
        if not sources:
            return
        try:
            from domain.map_render import render_missing
            done = render_missing(run_dir, names, sources,
                                  novalue=self._project_novalue(),
                                  blank_abs=self.cfg.get("checks.blank_abs"))
        except Exception as exc:                        # noqa: BLE001
            if callable(log):
                log(f"карты: фолбэк не отработал — {exc}")
            return
        if done and callable(log):
            log(f"карты: фолбэк нарисовал {len(done)} ({', '.join(done)})")

    def _project_novalue(self) -> float | None:
        """Бланковое значение карт из проектного YAML (данные)."""
        for stage in (self.coord.project_graph() or {}).get("pipeline") or []:
            for step in (stage or {}).get("steps") or []:
                params = (step or {}).get("parameters") or {}
                if "novalue" in params:
                    try:
                        return float(params["novalue"])
                    except (TypeError, ValueError):
                        continue
        return None

    # -- свидетельства этапа ---------------------------------------------------------
    def _attach_runtime_evidence(self, ev: dict, client, run_dir: Path, graph: dict,
                                 spec: GateSpec) -> None:
        """Runtime-свидетельства по данным гейта (`evidence:` в config): kind → пробник.

        Активные kinds используют только ПОДТВЕРЖДЁННЫЕ вызовы (well-tie/геометрия —
        get_* методы; STOIIP — compute_statistics(type='sum'), эталон v26.1).
        property_mean включается в данных только после верификации сигнатуры на 26.1.
        """
        try:
            from domain.qc import probes
        except Exception:                               # noqa: BLE001 — пробники опциональны
            probes = None
        for item in spec.evidence:
            kind = str((item or {}).get("kind") or "")
            try:
                if kind == "well_tie":
                    horizon = str(graph.get("reservoir_horizon") or "")
                    tie = self.coord._read_well_tie(client, run_dir, horizon)
                    if tie:
                        ev["well_tie"] = tie
                elif kind == "grid":
                    geom = self.coord._read_grid_geometry(client)
                    if geom:
                        ev["grid"] = geom
                elif kind == "stoiip":
                    val = self.coord._read_stoiip(client)
                    if val is not None:
                        ev["stoiip"] = val
                elif kind == "property_mean":
                    name = str((item or {}).get("name") or "")
                    grid_name = str(self.cfg.get("project.grid_name", "") or "")
                    key = str((item or {}).get("as") or f"{name.lower()}_mean")
                    if name and grid_name:
                        val = self._probe_property_mean(client, grid_name, name)
                        if val is not None:
                            ev[key] = val
                elif kind == "maps":
                    maps_dir = Path(run_dir) / "maps"
                    ev["map_files"] = ([{"name": p.stem, "file": p.name}
                                        for p in sorted(maps_dir.glob("*.png"))]
                                       if maps_dir.is_dir() else [])
                elif kind in ("grid_properties", "property_stats", "blocked_wells") \
                        and probes is not None:
                    # Свидетельства РЕЗУЛЬТАТА (F-19): список свойств сетки, их
                    # статистики и блокированные логи. Нет ответа → свидетельства нет
                    # (неизвестное != ложь), гейт остаётся pending_execution.
                    grid_name = str(self.cfg.get("project.grid_name", "") or "")
                    if kind == "grid_properties":
                        names = probes.read_grid_properties(
                            client, grid_name=grid_name, run_dir=Path(run_dir))
                        if names is not None:
                            ev["grid_properties"] = list(names)
                    elif kind == "property_stats":
                        stats = probes.read_property_stats(
                            client, grid_name=grid_name, cfg=self.cfg,
                            run_dir=Path(run_dir))
                        if stats is not None:
                            ev["property_stats"] = dict(stats)
                    else:
                        names = probes.read_blocked_wells(
                            client, grid_name=grid_name, run_dir=Path(run_dir))
                        if names is not None:
                            ev["blocked_wells"] = list(names)
            except Exception:                           # noqa: BLE001 — свидетельство опционально
                pass

    # -- рендер этапа и кандидаты rework ----------------------------------------------
    def _render_stage(self, node, rule_map, index, pipe, a, spec: GateSpec, params=None,
                      skip_functions: set[str] | None = None, skip_reason: str = "",
                      skip_reasons: dict | None = None,
                      steps: list[dict] | None = None, available: set[str] | None = None,
                      require_key: str = "requires_object",
                      skipped_out: list[dict] | None = None):
        """Отрендерить блоки этапа; при `params` — гены с патчем (rework-попытка).

        Пропуски по данным (оба — БЕЗ падения воркфлоу, правило 6):
          * `skip_functions` — решение агента (напр. врез не требуется);
          * `requires_object` у шага — объект-предпосылка отсутствует в уже
            созданных (свидетельство `available`, например `grid_properties`).
            Нет свидетельства (`available` пуст) → НЕ пропускаем: «неизвестное != ложь».
        """
        stage_blocks: list[str] = []
        objs: list[str] = []
        if node is None:
            return stage_blocks, index, objs
        step_list = list(steps or [])
        pos = 0
        for fg in node.functions:
            rule = rule_map.get(fg.function)
            obj = self.coord._step_object(fg, rule)
            step = step_list[pos] if pos < len(step_list) else {}
            pos += 1
            required = str(step.get(require_key) or "")
            if (required and available and required not in available):
                kind = str(step.get("requires_kind") or "")
                reason = (f"нет объекта-предпосылки «{required}»"
                          + (f" ({kind})" if kind else "") + ": шаг пропущен по данным")
                mode = str(step.get("on_missing") or "skip").strip().lower()
                if skipped_out is not None:
                    skipped_out.append({"function": fg.function,
                                        "requires_object": required, "reason": reason})
                if mode == "halt":
                    raise RuntimeError(reason)
                if pipe is not None:
                    pipe.add(stage=a.stage_key, stage_label=a.stage_key,
                             operation=f"{spec.id} · {a.agent_id}",
                             function=fg.function, object=obj,
                             status="skipped_by_policy", message=reason)
                continue
            if skip_functions and fg.function in skip_functions:
                # Причина — СВОЯ для каждого шага (F-23): иначе пропуск
                # неподтверждённого шага объяснялся бы решением о врезе.
                own_reason = (skip_reasons or {}).get(fg.function) or skip_reason \
                    or "пропущено решением агента"
                if pipe is not None:
                    pipe.add(stage=a.stage_key, stage_label=a.stage_key,
                             operation=f"{spec.id} · {a.agent_id}",
                             function=fg.function, object=obj,
                             status="skipped_by_policy",
                             message=own_reason)
                if skipped_out is not None:
                    skipped_out.append({"function": fg.function,
                                        "requires_object": "",
                                        "reason": own_reason})
                continue
            if obj:
                objs.append(obj)
            step_ev = None
            if pipe is not None:
                step_ev = pipe.add(stage=a.stage_key, stage_label=a.stage_key,
                                   operation=f"{spec.id} · {a.agent_id}",
                                   function=fg.function, object=obj, status=RUNNING)
            if rule is None:
                if step_ev is not None:
                    pipe.update(step_ev, PENDING_TEMPLATE, "нет шаблона функции в наборе")
                continue
            try:
                gene = self.coord._variant_gene(fg, rule, params) if params else fg
                block, index = self.builder.render_block(rule, gene, index)
                stage_blocks.append(block)
                if step_ev is not None:
                    pipe.update(step_ev, DONE, f"{len(block.splitlines())} строк кода")
            except Exception as exc:                    # noqa: BLE001
                if step_ev is not None:
                    pipe.update(step_ev, ERROR, str(exc))
        return stage_blocks, index, objs

    def _remediation_candidates(self, graph: dict, node, spec: GateSpec) -> list[dict]:
        """Кандидаты параметров для rework — из проектных `variations` (данные)."""
        if node is None:
            return []
        fns = {fg.function for fg in node.functions}
        out: list[dict] = []
        for var in graph.get("variations") or []:
            params = var.get("parameters") or {}
            patch = {fn: dict(p) for fn, p in params.items()
                     if fn in fns and isinstance(p, dict)}
            if patch:
                out.append(patch)
        return out

    def _probe_property_mean(self, client, grid_name: str, prop_name: str) -> float | None:
        tmp = Path(__file__).resolve().parents[1] / ".probe_property.tmp"
        res = self.coord._read_py_capture(
            client, code=property_mean_code(grid_name, prop_name, tmp), tmp=tmp,
            keys=("value",))
        if not res:
            return None
        val = res.get("value")
        return float(val) if isinstance(val, (int, float)) else None

    # -- меморандум передачи ------------------------------------------------------------
    def _match_contract(self, from_agent: str, to_agent: str):
        if not to_agent:
            return None
        return next((h for h in self.registry.handoffs()
                     if h.from_agent == from_agent and h.to_agent == to_agent), None)

    def _build_memo(self, graph: dict, a, nxt, spec: GateSpec, verdict,
                    wf_path: Path, lineage: list[str]) -> HandoffMemo:
        artifacts = [{"path": str(wf_path), "sha256": sha256_file(wf_path)}]
        payload = {"gate": spec.id, "status": verdict.status, "counts": verdict.counts,
                   "failed": [f.id for f in verdict.findings if not f.passed],
                   "workflow_sha": artifacts[0]["sha256"]}
        evidence_hash = sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        contract = self._match_contract(a.agent_id, nxt.agent_id if nxt else "")
        assumptions = []
        if verdict.status == PENDING:
            assumptions.append("dry-run: runtime-проверки не выполнялись (pending_execution)")
        return HandoffMemo(
            id=f"{spec.id}:{a.index}",
            handoff_id=contract.id if contract else f"HANDOFF_{spec.id}",
            from_agent=a.agent_id, to_agent=nxt.agent_id if nxt else "",
            from_stage=a.stage_key, to_stage=nxt.stage_key if nxt else "",
            verdict=verdict.status,
            degraded=verdict.status in DEGRADING,
            bypass_reason=(verdict.comment if verdict.status in (BYPASSED, SKIPPED) else ""),
            unresolved_findings=[f"{f.id}: {f.message}"
                                 for f in verdict.findings if not f.passed],
            artifact_revisions=artifacts,
            lineage=list(lineage),
            units_crs={"crs": graph.get("crs")} if graph.get("crs") else {"crs": "unknown"},
            qa={"status": verdict.status, "counts": verdict.counts,
                "kq": verdict.kq, "kc": verdict.kc, "physical": verdict.physical},
            assumptions=assumptions, uncertainties=[],
            evidence_hash=evidence_hash, waiver=verdict.waiver)
