"""НЕЗАВИСИМЫЙ АУДИТ ПРАВИЛА 6 («НЕИЗВЕСТНОЕ != ЛОЖЬ»).

Написан верификатором (task-6). Ничего в чужом коде не меняет.

Проверяется статически и ПОВЕДЕНЧЕСКИ:
  1) `except ...: pass|continue` — места, где ошибка глушится молча (файл:строка);
     критические каталоги (agents/checks, domain/qaqc, domain/qc) — FAIL, остальные WARN;
  2) подстановка нуля вместо отсутствующих данных (`or 0`, `else 0`, `.get(k, 0)`
     в сборке значений) — файл:строка;
  3) поведение QA/QC-пакета на ПУСТЫХ данных: `evaluate({})` не должен давать
     ни `passed`, ни `failed` (только `not_applicable`); отдельно проверяется, что
     флаг `physical` при нуле применимых проверок НЕ трактуется как «прошло»;
  4) поведение CheckRegistry на пустых свидетельствах: ни одна проверка не должна
     возвращать Finding (passed или failed) без данных;
  5) агенты в режиме «нет входов» → ABSTAIN + непустой `missing` (если классы агентов
     уже есть; иначе честно «не проверено»).

Запуск:  python -X utf8 tests/test_verify_rule6.py [--json]
Код возврата: 1 — есть нарушения правила 6.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCAN_DIRS = ("agents", "core", "domain")
CRITICAL_PREFIXES = ("agents/checks/", "domain/qaqc/", "domain/qc/")
SKIP_PREFIXES = ("domain/ontology_rules/reference_workflow.py",)

FAIL: list[str] = []
WARN: list[str] = []
INFO: list[str] = []


def fail(msg: str) -> None:
    FAIL.append(msg)
    print(f"[FAIL] {msg}")


def warn(msg: str) -> None:
    WARN.append(msg)
    print(f"[WARN] {msg}")


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def static_swallow() -> None:
    print("=== 1. МОЛЧАЛИВОЕ ГЛУШЕНИЕ ОШИБОК (except: pass/continue) ===")
    total = 0
    hidden = 0
    for sub in SCAN_DIRS:
        base = ROOT / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = _rel(path)
            if "__pycache__" in path.parts or any(rel.startswith(s) for s in SKIP_PREFIXES):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            parents: dict[int, ast.AST] = {}
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    parents[id(child)] = node
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                body = [n for n in node.body
                        if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                                and isinstance(n.value.value, str))]
                if not (len(body) == 1 and isinstance(body[0], (ast.Pass, ast.Continue))):
                    continue
                total += 1
                kind = "pass" if isinstance(body[0], ast.Pass) else "continue"
                where = f"{rel}:{node.lineno}: except → {kind}"
                critical = any(rel.startswith(p) for p in CRITICAL_PREFIXES)
                # «скрывает ошибку» = обработчик СТОИТ ПОСЛЕДНИМ в теле функции:
                # функция молча возвращает None/уходит в continue без фолбэка.
                owner = parents.get(id(node))
                last_in_owner = False
                while owner is not None and not hasattr(owner, "body"):
                    owner = parents.get(id(owner))
                if owner is not None:
                    stmts = [s for s in owner.body
                             if not (isinstance(s, ast.Expr) and
                                     isinstance(s.value, ast.Constant) and
                                     isinstance(s.value.value, str))]
                    last_in_owner = bool(stmts) and stmts[-1] is node
                if critical and last_in_owner:
                    hidden += 1
                    fail(f"правило 6: {where} — ПОСЛЕДНИЙ оператор функции: ошибка скрыта "
                         f"без фолбэка (результат молча теряется)")
                elif critical:
                    warn(f"правило 6: {where} (QA/QC-путь; далее есть продолжение/фолбэк — "
                         f"проверить, что результат не теряется)")
                else:
                    warn(f"правило 6: {where}")
    print(f"всего мест с молчаливым глушением: {total}; из них скрывают результат: {hidden}")


_ZERO_PATTERNS = (
    re.compile(r"\bor\s+0(\.0)?\b"),
    re.compile(r"\belse\s+0(\.0)?\b"),
    re.compile(r"\.get\([^)]*,\s*0(\.0)?\s*\)"),
)


def static_zero_fallback() -> None:
    print("\n=== 2. ПОДСТАНОВКА НУЛЯ ВМЕСТО ОТСУТСТВУЮЩИХ ДАННЫХ ===")
    total = 0
    for sub in SCAN_DIRS:
        base = ROOT / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = _rel(path)
            if "__pycache__" in path.parts or any(rel.startswith(s) for s in SKIP_PREFIXES):
                continue
            for i, line in enumerate(path.read_text(encoding="utf-8",
                                                    errors="replace").splitlines(), 1):
                code = line.split("#", 1)[0]
                if not code.strip() or "def " in code:
                    continue
                for rx in _ZERO_PATTERNS:
                    if rx.search(code):
                        total += 1
                        print(f"       [info] {rel}:{i}: {line.strip()[:110]}")
                        break
    print(f"совпадений `or 0 / else 0 / get(k,0)`: {total} "
          f"(оценивать: 0 может быть структурным, но в сборке значений это подмена)")


def dynamic_qaqc() -> None:
    print("\n=== 3. QA/QC-ПАКЕТ НА ПУСТЫХ ДАННЫХ ===")
    try:
        from domain.qaqc_adapter import evaluate, package_available
    except Exception as exc:                      # noqa: BLE001
        warn(f"пакет QA/QC не импортируется: {exc}")
        return
    if not package_available():
        warn("пакет QA/QC недоступен")
        return
    r = evaluate({})
    d = r.to_dict()
    print(f"evaluate({{}}) -> total={d['total']} passed={d['passed']} failed={d['failed']} "
          f"not_applicable={d['not_applicable']} physical={d['physical']} "
          f"kq={d['kq']} kc={d['kc']} fitness={d['fitness']}")
    if d["failed"] > 0:
        fail(f"правило 6: на ПУСТЫХ данных {d['failed']} проверок помечены failed "
             f"(нет данных ≠ провал): "
             + "; ".join(f"{c['id']}:{c['message'][:50]}" for c in d["failed_checks"][:5]))
    if d["passed"] > 0:
        fail(f"правило 6: на ПУСТЫХ данных {d['passed']} проверок помечены passed")
    if d["not_applicable"] != d["total"]:
        warn(f"на пустых данных применимо {d['total'] - d['not_applicable']} проверок "
             f"из {d['total']} — проверить, что входы действительно есть")
    if d["physical"] and d["not_applicable"] == d["total"]:
        warn("правило 6: `physical=True` при НУЛЕ применимых проверок — это «прошло» без "
             "данных; в отчёте верхнего уровня нужно различать not_applicable от passed "
             "(иначе гейт формально зелёный)")
    print(f"by_block: {d['by_block']}")


def dynamic_registry() -> None:
    print("\n=== 4. CheckRegistry НА ПУСТЫХ СВИДЕТЕЛЬСТВАХ ===")
    try:
        from agents.checks.base import CheckRegistry
        from core.config import load_config
    except Exception as exc:                      # noqa: BLE001
        warn(f"CheckRegistry не импортируется: {exc}")
        return
    cfg = load_config()
    gates = [str(g.get("id")) for g in (cfg.get("gates") or []) if g.get("id")]
    try:
        reg = CheckRegistry()
    except Exception as exc:                      # noqa: BLE001
        warn(f"CheckRegistry() не собрался: {exc}")
        return
    print(f"проверок в реестре: {len(reg.all())}; гейтов из данных: {len(gates)}")
    bad_passed, bad_failed = [], []
    for gid in gates:
        try:
            findings = reg.run(gid, {}, {}, include_runtime=True)
        except Exception as exc:                  # noqa: BLE001
            warn(f"реестр упал на гейте {gid}: {exc}")
            continue
        for f in findings:
            if getattr(f, "passed", None) is True:
                bad_passed.append(f"{gid}:{f.id}")
            else:
                bad_failed.append(f"{gid}:{f.id}:{str(getattr(f, 'message', ''))[:50]}")
    if bad_passed:
        fail(f"правило 6: проверки «прошли» БЕЗ данных: {bad_passed[:10]}")
    if bad_failed:
        fail(f"правило 6: проверки «провалены» БЕЗ данных (ожидалось None/not_applicable): "
             f"{bad_failed[:10]}")
    if not bad_passed and not bad_failed:
        print("на пустых свидетельствах ни одна проверка не вынесла вердикт — корректно")


def dynamic_agents() -> None:
    print("\n=== 5. АГЕНТЫ БЕЗ ВХОДОВ → ABSTAIN ===")
    try:
        from core.config import load_config
        from agents.base_agent import BaseAgent
    except Exception as exc:                      # noqa: BLE001
        warn(f"BaseAgent не импортируется: {exc}")
        return
    import importlib
    import inspect
    cfg = load_config()
    modules = ["agents.structural", "agents.grid", "agents.facies", "agents.petrophysics",
               "agents.saturation", "agents.maps"]
    seen = 0
    for mod_name in modules:
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:                  # noqa: BLE001
            INFO.append(f"{mod_name}: не импортируется ({exc})")
            continue
        for name, obj in vars(mod).items():
            if not (inspect.isclass(obj) and issubclass(obj, BaseAgent) and obj is not BaseAgent):
                continue
            seen += 1
            try:
                agent = obj(cfg)
            except Exception as exc:              # noqa: BLE001
                INFO.append(f"{name}: не создаётся без доп. аргументов ({exc})")
                continue
            try:
                decision = agent.bind({}).decide({}, {}) or {}
            except Exception as exc:              # noqa: BLE001
                fail(f"правило 6: {name}.decide() на пустых входах упал: {exc}")
                continue
            mode = decision.get("mode")
            missing = decision.get("missing") or []
            print(f"       {mod_name}.{name}: mode={mode} missing={missing[:5]} "
                  f"(входов требуется {len(agent.requirements())})")
            if agent.requirements() and mode != "abstain":
                warn(f"правило 6: {name} без входов вернул mode={mode} (ожидался abstain)")
            if agent.requirements() and not missing:
                warn(f"правило 6: {name} без входов не перечислил missing")
            if not agent.requirements():
                INFO.append(f"{name}: обязательные входы не заданы в данных "
                            f"(agents.required_inputs.{obj.agent_id}) — ABSTAIN не проверяется")
    if not seen:
        warn("классы агентов не найдены (agents/structural.py, grid.py, facies.py, "
             "petrophysics.py, saturation.py, maps.py) — проверка ABSTAIN не выполнена")


def dynamic_result_checks() -> None:
    """F-19: проверки РЕЗУЛЬТАТА (`result_checks` из данных) и семантика `unverified`.

    Независимо проверяем:
      1) каждый id из `ontology/qa_gate_map.yaml → result_checks` реально зарегистрирован
         в реестре, собранном ИЗ ДАННЫХ (`CheckRegistry.from_data`);
      2) пустое свидетельство → состояние `unverified` (НЕ passed) и гейт НЕ `passed`;
      3) отсутствие куба в списке свойств → `failed`;
      4) куб есть, но статистика пуста → `failed`.
    """
    print("\n=== 6. ПРОВЕРКИ РЕЗУЛЬТАТА (result_checks) И `unverified` ===")
    try:
        import yaml
        from agents.checks.base import CheckRegistry, UNVERIFIED
        from agents.gates import GateEngine, load_gate_specs
        from core.config import load_config
    except Exception as exc:                      # noqa: BLE001
        warn(f"не удалось импортировать реестр/гейты: {exc}")
        return
    cfg = load_config()
    gm_path = ROOT / "ontology" / "qa_gate_map.yaml"
    if not gm_path.is_file():
        warn("нет ontology/qa_gate_map.yaml — result_checks не проверить")
        return
    gm = yaml.safe_load(gm_path.read_text(encoding="utf-8")) or {}
    declared = gm.get("result_checks") or {}
    try:
        reg = CheckRegistry.from_data(cfg)
    except Exception as exc:                      # noqa: BLE001
        fail(f"CheckRegistry.from_data(cfg) упал: {exc}")
        return
    ids = {c.id for c in reg.all()}
    print(f"проверок в реестре ИЗ ДАННЫХ: {len(ids)}; в result_checks данных: "
          f"{sum(len(v) for v in declared.values())}")
    for gate, want in declared.items():
        missing = [i for i in want if i not in ids]
        if missing:
            fail(f"F-19: result_checks гейта {gate} объявлены в данных, но НЕ "
                 f"зарегистрированы в реестре: {missing}")
        else:
            print(f"  [OK ] {gate}: {want} зарегистрированы")

    # 2) пустое свидетельство → unverified, гейт не passed
    specs = {s.id: s for s in load_gate_specs(cfg)}
    engine = GateEngine(cfg, registry=reg)
    for gate in declared:
        findings = reg.run(gate, {}, {})
        states = {getattr(f, "state", ""): 0 for f in findings}
        for f in findings:
            states[getattr(f, "state", "")] = states.get(getattr(f, "state", ""), 0) + 1
        res_ids = [i for i in declared[gate]]
        res_findings = [f for f in findings if f.id in res_ids]
        # ВАЖНО: `unverified` намеренно имеет passed=True + state=UNVERIFIED
        # (agents/checks/builtin.py:36, contracts.py:113). «Настоящий» pass — только
        # когда state НЕ unverified; гейт обязан остаться pending_execution.
        bad = [f.id for f in res_findings
               if f.passed and getattr(f, "state", "") != UNVERIFIED]
        print(f"  {gate}: findings={len(findings)}, "
              f"по результату={[(f.id, getattr(f, 'state', None)) for f in res_findings]}")
        if bad:
            fail(f"F-19: без свидетельств проверки результата {bad} объявлены passed")
        if not res_findings:
            fail(f"F-19: для {gate} не сработала ни одна проверка результата "
                 f"(ожидались {res_ids})")
        spec = specs.get(gate)
        if spec is not None:
            verdict = engine.evaluate(spec, findings, metrics={})
            print(f"       вердикт: status={verdict.status} unverified="
                  f"{getattr(verdict, 'unverified', None)}")
            if verdict.status == "passed":
                fail(f"F-19: гейт {gate} стал `passed` без свидетельств о результате")
            if res_findings and not getattr(verdict, "unverified", None):
                fail(f"F-19: гейт {gate} не перечислил unverified при отсутствии данных")

    # 3) куба нет в списке свойств → failed
    absent = reg.run("G-FACIES", {"grid_properties": ["PORO", "PERM"]}, {})
    for f in absent:
        if f.id == "facies.cube_exists":
            print(f"  куба нет в grid_properties → {f.id}: passed={f.passed} "
                  f"state={getattr(f, 'state', None)}")
            if f.passed:
                fail("F-19: `facies.cube_exists` passed, хотя куба нет в grid_properties")
    # 4) куб есть, но пуст → failed
    empty = reg.run("G-FACIES", {"grid_properties": ["FACIES"],
                                 "property_stats": {"FACIES": {"count": 0}}}, {})
    for f in empty:
        if f.id == "facies.cube_nonempty":
            print(f"  куб есть, но пуст → {f.id}: passed={f.passed} "
                  f"state={getattr(f, 'state', None)}")
            if f.passed and getattr(f, "state", "") != UNVERIFIED:
                fail("F-19: `facies.cube_nonempty` passed, хотя куб пуст")

    def _nonempty(finding_id: str, stats: dict) -> tuple[bool, str]:
        res = reg.run("G-FACIES", {"grid_properties": ["FACIES"],
                                   "property_stats": {"FACIES": stats}}, {})
        f = next((x for x in res if x.id == finding_id), None)
        return ((bool(f.passed), str(getattr(f, "state", ""))) if f else (False, "НЕТ"))

    # 5) classes усечены + count>0 → НЕ failed (иначе ложный провал)
    passed, state = _nonempty("facies.cube_nonempty",
                              {"count": 100, "nulls": 900, "classes_truncated": 1,
                               "classes": []})
    print(f"  count=100/classes_truncated=1 → passed={passed} state={state}")
    if not passed:
        fail("F-19: усечённые `classes` + count>0 дали ложный провал непустоты")
    # 6) только cells без сведений о пустых → unverified (НЕ passed)
    passed, state = _nonempty("facies.cube_nonempty", {"cells": 1000})
    print(f"  только cells=1000 → passed={passed} state={state}")
    if passed and state != UNVERIFIED:
        fail("F-19: непустота подтверждена по общему `cells` без данных о пустых ячейках")
    # 7) count>0, но unique=0 (противоречие свидетельства) → unverified
    passed, state = _nonempty("facies.cube_nonempty", {"count": 10, "unique_count": 0})
    print(f"  count=10/unique=0 → passed={passed} state={state}")
    if passed and state != UNVERIFIED:
        fail("F-19: противоречивое свидетельство (count>0, unique=0) сочтено проверенным")

    # ---- 8) G-VOL: метрика проекта (имя из данных `ensemble.metric`) ----------
    metric = str(cfg.get("ensemble.metric") or "")
    print(f"\n  --- G-VOL: метрика «{metric}» (имя из данных ensemble.metric)")
    if not metric:
        warn("в данных нет ensemble.metric — проверить G-VOL нельзя")
    else:
        ctxv = {"metric_name": metric}

        def _vol(ev: dict) -> dict:
            res = reg.run("G-VOL", ev, ctxv)
            out = {f.id: (bool(f.passed), str(getattr(f, "state", ""))) for f in res}
            spec = specs.get("G-VOL")
            status = engine.evaluate(spec, res, metrics={}).status if spec else "?"
            return {"res": out, "status": status}

        miss = _vol({"grid_properties": ["PORO", "PERM"]})
        print(f"  метрики нет в grid_properties → {miss['res']} | гейт {miss['status']}")
        me = miss["res"].get("cube.metric_exists", (True, ""))
        if me[0] and me[1] != UNVERIFIED:
            fail("F-19: `cube.metric_exists` не упал, хотя метрики нет в grid_properties")
        if miss["status"] == "passed":
            fail("F-19: G-VOL прошёл, хотя метрики нет в проекте")

        zero = _vol({"grid_properties": [metric], "property_stats": {metric: {"count": 0}}})
        print(f"  метрика есть, count=0 → {zero['res']} | гейт {zero['status']}")
        mn = zero["res"].get("cube.metric_nonempty", (True, ""))
        if mn[0] and mn[1] != UNVERIFIED:
            fail("F-19: `cube.metric_nonempty` не упал при count=0")
        if zero["status"] == "passed":
            fail("F-19: G-VOL прошёл при пустой метрике")

        ok = _vol({"grid_properties": [metric], "property_stats": {metric: {"count": 1000}}})
        print(f"  метрика есть и непуста → {ok['res']} | гейт {ok['status']}")
        if ok["status"] != "passed":
            fail(f"F-19: G-VOL не passed при непустой метрике (status={ok['status']})")

        unknown = _vol({"grid_properties": [metric]})
        print(f"  нет property_stats → {unknown['res']} | гейт {unknown['status']}")
        if unknown["status"] == "passed":
            fail("F-19: G-VOL прошёл без статистики метрики (нет свидетельства)")

    # ---- 9) СЕРЬЁЗНОСТЬ ИЗ ДАННЫХ: checks.check_severity ---------------------
    print("\n  --- серьёзность находки из ДАННЫХ (checks.check_severity)")
    try:
        base_sev = dict(cfg.get("checks.check_severity") or {})
        target = "cube.metric_nonempty"
        mname = str(cfg.get("ensemble.metric") or "STOIIP")
        probe = {"grid_properties": [mname], "property_stats": {mname: {"count": 0}}}
        spec_sev = {c.id: c.severity for c in reg.all()}
        print(f"  spec severity для {target}: {spec_sev.get(target)}; "
              f"данные checks.check_severity: {base_sev or '—'}")
        base_before = cfg.get("checks.check_severity")
        cfg.raw.setdefault("checks", {})["check_severity"] = {target: "minor"}
        reg2 = CheckRegistry.from_data(cfg)
        f2 = next((x for x in reg2.run("G-VOL", probe, {"metric_name": mname})
                   if x.id == target), None)
        sev2 = getattr(f2, "severity", None)
        print(f"  с данными {{'{target}': 'minor'}} → severity находки = {sev2}")
        if sev2 != "minor":
            fail("F-19/plumbing: `checks.check_severity` из данных не влияет на уровень находки")
        spec2 = specs.get("G-VOL")
        if f2 is not None and spec2 is not None:
            st2 = engine.evaluate(spec2, [f2], metrics={}).status
            print(f"  вердикт гейта при minor-провале: {st2}")
            if st2 == "failed":
                fail("F-19/plumbing: minor-находка валит гейт (уровень из данных не учтён)")
        cfg.raw["checks"]["check_severity"] = base_before
    except Exception as exc:                       # noqa: BLE001
        warn(f"проверка checks.check_severity не выполнена: {exc}")

    # ---- 10) ГЛОБАЛЬНЫЙ ИНВАРИАНТ УРОВНЕЙ (данные ↔ реестр ↔ артефакты) -----
    print("\n  --- глобальный инвариант: level(данные) == level(находки) == "
          "level(gates/*.json)")
    import glob as _glob
    import json as _json
    # множество уровней берём ИЗ КОДА (contracts.SEVERITIES), чтобы контракт не расходился
    try:
        from agents.contracts import SEVERITIES as _SEV
        levels = {str(x) for x in _SEV}
        print(f"  уровни из кода agents.contracts.SEVERITIES: {sorted(levels)}")
    except Exception as exc:                       # noqa: BLE001
        levels = {"critical", "major", "minor", "note"}
        warn(f"не удалось прочитать SEVERITIES из кода ({exc}) — беру {sorted(levels)}")
    sev_map = dict(cfg.get("checks.check_severity") or {})
    bad_levels = {k: v for k, v in sev_map.items() if str(v) not in levels}
    if bad_levels:
        fail(f"checks.check_severity: недопустимые уровни {bad_levels} "
             f"(разрешены {sorted(levels)})")
    spec_sev = {c.id: c.severity for c in reg.all()}
    unregistered = [k for k in sev_map if k not in spec_sev]
    if unregistered:
        fail(f"checks.check_severity ссылается на незарегистрированные проверки: "
             f"{unregistered}")
    mism = {k: (v, spec_sev.get(k)) for k, v in sev_map.items()
            if k in spec_sev and spec_sev.get(k) != str(v)}
    if mism:
        fail(f"уровень в реестре не совпал с данными checks.check_severity: {mism}")
    print(f"  точек управления в данных: {len(sev_map)}; несоответствий реестра: "
          f"{len(mism)}; незарегистрированных: {len(unregistered)}")
    if not sev_map:
        print("  [info] checks.check_severity пуст — точка управления существует, "
              "значения не заданы (проверено синтетически выше)")

    # артефакты гейтов: сверяем уровень каждой находки, чей id есть в данных.
    # Артефакты СТАРШЕ правки данных не считаем расхождением (это устаревший прогон) —
    # сравниваем только то, что записано ПОСЛЕ изменения `checks.check_severity`.
    art_files = sorted(_glob.glob(str(ROOT / "runs" / "**" / "agents" / "gates" / "*.json"),
                                  recursive=True))
    try:
        data_mtime = (ROOT / "config.yaml").stat().st_mtime
    except OSError:
        data_mtime = 0.0
    checked = 0
    stale = 0
    for path in art_files:
        try:
            art_mtime = Path(path).stat().st_mtime
        except OSError:
            continue
        if art_mtime < data_mtime:
            stale += 1
            continue
        try:
            d = _json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
        except Exception:                          # noqa: BLE001
            continue
        for f in d.get("findings") or []:
            fid = str(f.get("id") or "")
            if fid in sev_map:
                checked += 1
                if str(f.get("severity")) != str(sev_map[fid]):
                    fail(f"артефакт {Path(path).name}: уровень находки {fid} = "
                         f"{f.get('severity')}, в данных {sev_map[fid]}")
    print(f"  артефактов гейтов: {len(art_files)} (старше данных: {stale}); "
          f"находок, сверенных с данными: {checked}")
    if not art_files:
        warn("не найдено runs/**/agents/gates/*.json — сверка уровней по артефактам "
             "не выполнена (запустите прогон)")

    # ---- 11) СИНТЕТИКА: каждый уровень из SEVERITIES должен применяться ---------
    print("\n  --- синтетика: все уровни из SEVERITIES применяются и не игнорируются")
    try:
        base_before2 = cfg.get("checks.check_severity")
        target2 = "cube.metric_nonempty"
        mname2 = str(cfg.get("ensemble.metric") or "STOIIP")
        probe2 = {"grid_properties": [mname2], "property_stats": {mname2: {"count": 0}}}
        spec_v = specs.get("G-VOL")
        for lvl in sorted(levels):
            cfg.raw.setdefault("checks", {})["check_severity"] = {target2: lvl}
            regx = CheckRegistry.from_data(cfg)
            fx = next((x for x in regx.run("G-VOL", probe2, {"metric_name": mname2})
                       if x.id == target2), None)
            sevx = getattr(fx, "severity", None)
            stx = engine.evaluate(spec_v, [fx], metrics={}).status if (fx and spec_v) else "?"
            print(f"    {lvl:8s} → severity находки = {sevx}, вердикт гейта = {stx}")
            if sevx != lvl:
                fail(f"уровень `{lvl}` из данных не применился (получили {sevx}) — "
                     f"игнорирование контракта")
            if lvl != "critical" and stx == "failed":
                fail(f"уровень `{lvl}` (не critical) валит гейт — семантика уровней нарушена")
        cfg.raw["checks"]["check_severity"] = base_before2
    except Exception as exc:                       # noqa: BLE001
        warn(f"синтетическая проверка уровней не выполнена: {exc}")


def main() -> int:
    static_swallow()
    static_zero_fallback()
    dynamic_qaqc()
    dynamic_registry()
    dynamic_result_checks()
    dynamic_agents()
    print("\n=== ИТОГ (rule6) ===")
    print(f"FAIL: {len(FAIL)} | WARN: {len(WARN)} | INFO: {len(INFO)}")
    if "--json" in sys.argv:
        print(json.dumps({"fail": FAIL, "warn": WARN, "info": INFO},
                         ensure_ascii=False, indent=2))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
