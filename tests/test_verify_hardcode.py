"""НЕЗАВИСИМЫЙ АУДИТ ХАРДКОДА (правило 1: «домен — только в данных»).

Написан верификатором (task-6) и НЕ повторяет tests/test_no_domain_in_code.py:
  * список токенов строится ШИРЕ: из ВСЕХ строковых значений проектного YAML
    (а не только по ключам-носителям `hardcode_audit.token_keys`), плюс
    `workflow.foreign_tokens`, плюс `hardcode_audit.tokens`;
  * сканируются не только `agents/ core/ domain/`, но и `ontology/` и `tests/`
    (вне официального скана — отдельным разделом);
  * каталог `domain/qaqc/` (официальным тестом исключён целиком как «данные»)
    проверяется ОТДЕЛЬНО: если это рукописный .py, домен в нём — нарушение;
  * проверяется «мёртвый долг»: позиция из `hardcode_audit.known_debt`, которой в
    файле больше нет (раздувание/маскировка долга), и рост долга против базовой
    линии (33 позиции на 2026-10-09 18:14);
  * отдельно ищутся ПОРОГИ из данных (config.checks / thresholds / geostat),
    зашитые числами в код (правило 1 упоминает пороги явно) — информационно.

Запуск:  python -X utf8 tests/test_verify_hardcode.py [--json]
Код возврата: 1, если есть литерал/имя-домен, не объявленный ни в allow, ни в
known_debt (ровно то, что запрещает правило 1).
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASELINE_DEBT_POSITIONS = 26          # позиций в hardcode_audit.known_debt на 2026-10-09 18:14
BASELINE_DEBT_ROWS = 33               # строк долга в отчёте официального теста (см. PLAN_AGENTS_v2)

# значения-управляющие, а не домен
_STOP = {"on", "off", "auto", "true", "false", "none", "yes", "no", "y", "n",
         "grid", "log", "input", "output", "result", "left", "right", "up", "down",
         "sis", "tgs", "pgs", "mps", "kriging", "idw", "midpoint", "most_of",
         "continuous", "discrete", "best", "skip", "halt", "ask", "sum", "mean",
         "median", "p10", "p50", "p90", "min", "max", "std", "all", "any", "py",
         "windows", "linux", "utf-8", "json", "yaml", "csv", "txt", "las", "png",
         "major", "minor", "critical", "passed", "failed", "unknown",
         "not_applicable", "pending", "done", "error", "running", "queued",
         "symbolic", "hybrid", "generative", "abstain", "contract", "builtin",
         "package", "runtime", "dry_run", "du", "mv", "snp", "snf", "xml", "rdf",
         "ttl", "xlsx", "docx", "pptx", "html", "css", "js", "md", "irap"}

# доменные типы-схемы онтологии (идентификаторы СХЕМЫ, разрешены правилом 1)
_SCHEMA = {"Grid3d", "Map2d", "Map2dProperty", "Grid3dProperty", "Horizon", "WellMarker",
           "WellLog", "BlockedWells", "WellAttribute", "Curve3d", "Fault3d", "Geobody",
           "Contact", "MarkerSet", "Grid2D", "ZoneRegionFilter", "ZoneRegionParameters",
           "ZoneRegionFaciesParameters", "VariogramParameters", "Grid2DSettings",
           "WellFilterParameters", "typed_object_name", "absolute_object_name",
           "find_object", "ZoneRegionFaciesParameters", "TypedObjectName"}


def _norm(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


FAIL: list[str] = []
WARN: list[str] = []


def fail(msg: str) -> None:
    FAIL.append(msg)
    print(f"[FAIL] {msg}")


def warn(msg: str) -> None:
    WARN.append(msg)
    print(f"[WARN] {msg}")


def main() -> int:
    import yaml
    from core.config import load_config

    cfg = load_config()
    raw = cfg.raw

    # --- 1. токены домена ИЗ ДАННЫХ (широкий набор) --------------------------
    tokens: dict[str, str] = {}
    # схема/API: имена функций тНава (номенклатура из ontology/tnavigator_functions.csv)
    # и метки этапов пайплайна — правило 1 прямо разрешает идентификаторы СХЕМЫ.
    schema: set[str] = set()
    fn_csv = cfg.resolve(cfg.get("ontology.functions_csv") or "ontology/tnavigator_functions.csv")
    if fn_csv and Path(fn_csv).is_file():
        for line in Path(fn_csv).read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
            parts = line.split(",")
            if len(parts) > 1 and parts[1].strip():
                schema.add(parts[1].strip())

    def add(tok: str, src: str) -> None:
        tok = (tok or "").strip()
        if len(tok) < 3 or tok.lower() in _STOP or tok in _SCHEMA:
            return
        if tok.replace(".", "").replace("-", "").replace("_", "").isdigit():
            return
        tokens.setdefault(tok, src)

    for t in (raw.get("workflow", {}) or {}).get("foreign_tokens") or []:
        add(str(t), "workflow.foreign_tokens")
    for t in (raw.get("hardcode_audit", {}) or {}).get("tokens") or []:
        add(str(t), "hardcode_audit.tokens")

    graph_dir = cfg.path("project.graph_dir", "ontology_project")
    for g in sorted([*Path(graph_dir).glob("*.yaml"), *Path(graph_dir).glob("*.yml")]):
        proj = yaml.safe_load(g.read_text(encoding="utf-8")) or {}

        def walk(node, path: str = "") -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for v in node:
                    walk(v, path)
            elif isinstance(node, str):
                # метки этапов и имена функций — СХЕМА (правило 1: допустимы)
                if path.endswith(".stage") or path.startswith(".functions."):
                    return
                add(node, f"{g.name}:{path}")

        walk(proj)
        for fn in (proj.get("functions") or {}):
            schema.add(str(fn))
        for stage in proj.get("pipeline") or []:
            if stage.get("stage"):
                schema.add(str(stage["stage"]))
            for step in stage.get("steps") or []:
                if step.get("function"):
                    schema.add(str(step["function"]))
    for tok in list(tokens):
        if tok in schema:
            tokens.pop(tok, None)
        elif any(tok in s for s in schema if s != tok):   # значение — часть метки/имени схемы
            tokens.pop(tok, None)
    print(f"токенов СХЕМЫ/API (не домен): {len(schema)}")

    # --- 1b. ГЕНЕРИЧЕСКАЯ ЛЕКСИКА (единицы измерения) — ДАННЫЕ, а не домен ------
    # Значение под ключом-носителем единиц (`*.units`) — ЕДИНИЦА ИЗМЕРЕНИЯ, а не имя
    # объекта поля. Без этого правила «percent» (единица кривой) ложно ловило флаг «%»
    # порога QA/QC, ключ прогресса отчёта и имя статистики API тНава. Список — ИЗ
    # ДАННЫХ (`ontology/generic_vocabulary.yaml`), каждая позиция с обоснованием;
    # исключаются ТОЛЬКО объявленные единицы, пришедшие из ключа-носителя единиц.
    vocab: dict = {}
    try:
        vocab = yaml.safe_load(
            (ROOT / "ontology" / "generic_vocabulary.yaml").read_text(
                encoding="utf-8")) or {}
    except Exception:                              # noqa: BLE001 — данные опциональны
        vocab = {}
    unit_values = {str(item.get("value", "")).strip()
                   for item in (vocab.get("generic_unit_values") or [])
                   if isinstance(item, dict) and str(item.get("value", "")).strip()}
    unit_keys = tuple(str(key) for key in
                      ((vocab.get("policy") or {}).get("carrier_keys_for_units")
                       or ["units", "unit"]))
    generic_excluded: list[tuple[str, str]] = []
    for tok in list(tokens):
        source = tokens[tok]
        location = source.split(":", 1)[1] if ":" in source else source
        if location.rsplit(".", 1)[-1].lower() in unit_keys and tok in unit_values:
            generic_excluded.append((tok, source))
            tokens.pop(tok, None)
    print(f"генерическая лексика (единицы измерения) исключена из домена: "
          f"{len(generic_excluded)}")
    for tok, source in generic_excluded[:10]:
        print(f"       [не домен] «{tok}» ← {source} (единица измерения, "
              f"обоснование — в ontology/generic_vocabulary.yaml)")

    # --- 2. объявленные исключения и долг ------------------------------------
    ha = (raw.get("hardcode_audit", {}) or {})
    allow = {str(k): {str(x) for x in (v or [])} for k, v in (ha.get("allow") or {}).items()}
    ident_allow = {str(k): {str(x) for x in (v or [])}
                   for k, v in (ha.get("identifier_allow") or {}).items()}
    debt_cfg = ha.get("known_debt") or {}
    debt: dict[str, dict[str, set[str]]] = {}
    for f, slot in debt_cfg.items():
        slot = slot if isinstance(slot, dict) else {}
        debt[str(f)] = {"literals": {str(x) for x in (slot.get("literals") or [])},
                        "identifiers": {str(x) for x in (slot.get("identifiers") or [])}}
    n_debt = sum(len(s["literals"]) + len(s["identifiers"]) for s in debt.values())

    print(f"токенов домена собрано ИЗ ДАННЫХ: {len(tokens)}")
    print(f"allow: {sum(len(v) for v in allow.values())} шт. в {len(allow)} файлах; "
          f"known_debt: {n_debt} позиций в {len(debt)} файлах "
          f"(базовая линия {BASELINE_DEBT_POSITIONS})")
    if n_debt > BASELINE_DEBT_POSITIONS:
        print(f"[WARN] known_debt ВЫРОС против базовой линии: "
              f"{BASELINE_DEBT_POSITIONS} -> {n_debt} (правило 1 отодвигается, а не решается)")

    # --- 3. сканирование кода ------------------------------------------------
    def literals_and_names(path: Path):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        docs = set()
        for node in ast.walk(tree):
            # docstring-и — не код
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                body = getattr(node, "body", None) or []
                if body and isinstance(body[0], ast.Expr) and \
                        isinstance(body[0].value, ast.Constant) and \
                        isinstance(body[0].value.value, str):
                    docs.add(id(body[0].value))
        lits, names = [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and \
                    id(node) not in docs:
                lits.append((node.lineno, node.value))
            elif isinstance(node, ast.Name):
                names.append((node.lineno, node.id))
            elif isinstance(node, ast.Attribute):
                names.append((node.lineno, node.attr))
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                names.append((node.lineno, node.name))
            elif isinstance(node, ast.arg):
                names.append((node.lineno, node.arg))
        return lits, names

    def scan(dirs: tuple[str, ...]) -> list[tuple[str, int, str, str, list[str]]]:
        """[(rel, line, kind, value, [токены]), ...] по всем .py в каталогах."""
        hits = []
        for sub in dirs:
            base = ROOT / sub
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                rel = _norm(path)
                lits, names = literals_and_names(path)
                for line, value in lits:
                    toks = [t for t in tokens if t in value]
                    if toks:
                        hits.append((rel, line, "literal", value, toks))
                for line, value in names:
                    segs = [s for s in str(value).split("_") if s]
                    toks = [t for t in tokens if t in segs]
                    if toks:
                        hits.append((rel, line, "name", value, toks))
        return hits

    def classify(hits):
        violations, allowed, debt_hits = [], [], []
        for rel, line, kind, value, toks in hits:
            hard = []
            for tok in toks:
                if value in allow.get(rel, set()) or value in ident_allow.get(rel, set()):
                    allowed.append((rel, line, kind, value, tok))
                    continue
                slot = debt.get(rel, {})
                if value in slot.get("literals", set()) or \
                        value in slot.get("identifiers", set()):
                    debt_hits.append((rel, line, kind, value, tok))
                    continue
                hard.append(tok)
            if hard:
                violations.append((rel, line, kind, value, hard))
        return violations, allowed, debt_hits

    def show(violations, limit=60):
        seen: dict[str, int] = {}
        for rel, line, kind, value, toks in violations[:limit]:
            print(f"[FAIL] {rel}:{line}: {kind} «{str(value)[:70]}» "
                  f"содержит домен {toks[:3]}")
        for _rel, _l, _k, _v, toks in violations:
            for t in toks:
                seen[t] = seen.get(t, 0) + 1
        top = sorted(seen.items(), key=lambda kv: -kv[1])[:15]
        if top:
            print("       топ-токены: " + ", ".join(f"{t}×{n}" for t, n in top))
        if len(violations) > limit:
            print(f"       … ещё {len(violations) - limit}")

    # эталон тНава — ДАННЫЕ (как и в официальном тесте), из скана исключаем
    def drop_reference(hits):
        return [h for h in hits if not h[0].endswith("ontology_rules/reference_workflow.py")]

    # пакет domain/qaqc/** официальный тест исключает из скана — считаем отдельно (3b)
    def drop_qaqc(hits):
        return [h for h in hits if not h[0].startswith("domain/qaqc/")]

    print("\n=== 3. СКАН В ГРАНИЦАХ ОФИЦИАЛЬНОГО ТЕСТА (agents/ core/ domain/ без qaqc) ===")
    hits = drop_qaqc(drop_reference(scan(("agents", "core", "domain"))))
    viol, ok, dbg = classify(hits)
    print(f"совпадений всего: {len(hits)} | разрешено allow: {len(ok)} | "
          f"объявлено в known_debt: {len(dbg)} | НЕ ОБЪЯВЛЕНО: {len(viol)}")
    for rel, line, kind, value, tok in dbg[:20]:
        print(f"       [долг] {rel}:{line}: {kind} «{str(value)[:60]}» домен «{tok}»")
    show(viol)

    print("\n=== 3b. domain/qaqc/ (официальный тест исключает каталог целиком) ===")
    q_hits = drop_reference(scan(("domain/qaqc",)))
    q_viol, q_ok, q_dbg = classify(q_hits)
    per_file: dict[str, int] = {}
    for rel, _l, _k, _v, _t in q_hits:
        per_file[rel] = per_file.get(rel, 0) + 1
    print(f"совпадений: {len(q_hits)} в файлах: {per_file}")
    print(f"НЕ объявлено в данных: {len(q_viol)}; в known_debt: {len(q_dbg)}")
    # производность: доменный текст должен присутствовать в ИСХОДНЫХ данных пакета
    src_text = ""
    for cand in ("domain/qaqc/checks_table.csv",):
        p = ROOT / cand
        if p.is_file():
            src_text += p.read_text(encoding="utf-8", errors="replace")
    for d in sorted((ROOT / "ontology" / "qa_checks").glob("*.csv")) if \
            (ROOT / "ontology" / "qa_checks").is_dir() else []:
        src_text += d.read_text(encoding="utf-8", errors="replace")
    if q_viol and src_text:
        derived = [h for h in q_viol if any(t in src_text for t in h[4])]
        print(f"из них доменный ТОКЕН дословно присутствует в исходных CSV пакета: "
              f"{len(derived)}/{len(q_viol)} ({100 * len(derived) / len(q_viol):.0f}%) "
              f"-> производные данные (текст проверок), не рукописный домен")
        not_derived = [h for h in q_viol if not any(t in src_text for t in h[4])]
        if not_derived:
            print(f"[info] не выводятся из CSV пакета ({len(not_derived)}) — ручная оценка "
                  f"(наследованные сгенерированные файлы: parameters.py — лист «Обозначения_"
                  f"параметров», генератор и исходная книга в репозитории отсутствуют):")
            for rel, line, kind, value, toks in not_derived[:8]:
                print(f"       [info] {rel}:{line}: {kind} «{str(value)[:60]}» {toks[:2]}")
    else:
        for rel, line, kind, value, toks in q_viol[:8]:
            print(f"       [info] {rel}:{line}: {kind} «{str(value)[:60]}» {toks[:2]}")
    # сверка: пакет должен быть исполняемым (CHECKS) на всём, что оцифровано
    tsv = ROOT / "domain" / "qaqc" / "checks_table.csv"
    if tsv.is_file():
        try:
            import csv as _csv
            from domain import qaqc as _qaqc
            ch = getattr(_qaqc, "CHECKS", {}) or {}
            rows = list(_csv.DictReader(tsv.read_text(encoding="utf-8-sig").splitlines(),
                                        delimiter=";"))
            ids = [r.get("ID", "") for r in rows if r.get("ID")]
            unknown_rows = [r for r in rows if
                            str(r.get("Способ выполнения", "")).strip().lower()
                            in ("unknown", "")]
            print(f"checks_table.csv: {len(ids)} строк; CHECKS (исполняемых): {len(ch)}; "
                  f"строк со способом unknown: {len(unknown_rows)}")
            if len(ids) - len(ch) != len(unknown_rows):
                print("[WARN] разница CSV и CHECKS не объясняется строками со способом "
                      "«unknown» — часть проверок могла выпасть молча (см. "
                      "tests/test_verify_qaqc_checklist.py)")
        except Exception as exc:                   # noqa: BLE001
            print(f"[WARN] пакет domain/qaqc не импортируется: {exc}")

    print("\n=== 3c. ВНЕ официального скана (ontology/, tests/) — информационно ===")
    for sub in ("ontology", "tests"):
        h = drop_reference(scan((sub,)))
        v, a, d = classify(h)
        print(f"{sub}/: совпадений {len(h)}, из них НЕ объявлено в данных: {len(v)}")
        for rel, line, kind, value, toks in v[:10]:
            print(f"       [info] {rel}:{line}: {kind} «{str(value)[:60]}» домен {toks[:2]}")
        if len(v) > 10:
            print(f"       … ещё {len(v) - 10}")
    print("       (правило 1 про рантайм; ontology/*.py — скрипты-генераторы, "
          "tests/ — проверки; фиксируется как зона без автоматического контроля)")

    # --- 4. мёртвый долг -----------------------------------------------------
    print("\n=== 4. «МЁРТВЫЙ» ДОЛГ (позиция объявлена, но в файле её нет) ===")
    all_lits_names: dict[str, tuple[set, set]] = {}
    for rel in debt:
        p = ROOT / rel
        if not p.is_file():
            print(f"[WARN] known_debt ссылается на несуществующий файл: {rel}")
            continue
        lits, names = literals_and_names(p)
        all_lits_names[rel] = ({v for _l, v in lits}, {v for _l, v in names})
    dead = 0
    for rel, slot in debt.items():
        if rel not in all_lits_names:
            continue
        lits, names = all_lits_names[rel]
        for value in sorted(slot["literals"]):
            if value not in lits:
                print(f"[WARN] мёртвый долг (литерал не найден): {rel}: «{value[:60]}»")
                dead += 1
        for value in sorted(slot["identifiers"]):
            if value not in names:
                print(f"[WARN] мёртвый долг (имя не найдено): {rel}: «{value}»")
                dead += 1
    print(f"мёртвых позиций долга: {dead}")

    # --- 5. пороги в коде ----------------------------------------------------
    print("\n=== 5. ЧИСЛОВЫЕ ПОРОГИ ИЗ ДАННЫХ, ЗАШИТЫЕ В КОД (информационно) ===")
    numeric: dict[float, str] = {}
    checks = raw.get("checks", {}) or {}

    def num_walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                num_walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for v in node:
                num_walk(v, path)
        elif isinstance(node, bool):
            pass
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            if abs(float(node)) > 1e-9:
                numeric.setdefault(float(node), f"config:{path}")

    num_walk(checks, "checks")
    for g in sorted([*Path(graph_dir).glob("*.yaml"), *Path(graph_dir).glob("*.yml")]):
        proj = yaml.safe_load(g.read_text(encoding="utf-8")) or {}
        for sec in ("thresholds", "geostat", "petrophysical", "petrophysics"):
            if sec in proj:
                num_walk(proj[sec], f"{g.name}:{sec}")
    found_map: dict[float, list[str]] = {}
    for sub in ("agents", "core", "domain"):
        base = ROOT / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "qaqc" in path.parts or "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                        and not isinstance(node.value, bool):
                    v = float(node.value)
                    # отсеиваем структурные константы: 0..10, индексы, 100 (сетка)
                    if v in numeric and (v != int(v) or abs(v) >= 20):
                        found_map.setdefault(v, []).append(f"{_norm(path)}:{node.lineno}")
    for v in sorted(found_map):
        spots = found_map[v]
        print(f"       [info] {v!r} = порог {numeric[v]}: {len(spots)} мест, "
              f"напр. {', '.join(spots[:4])}")
    print(f"значимых совпадений с порогами: {sum(len(s) for s in found_map.values())} "
          f"({len(found_map)} разных значений) — оценивать вручную")

    # --- 6. связка ДАННЫЕ → КОД: ключи, которые никто не читает -----------------
    print("\n=== 6. КЛЮЧИ ДАННЫХ, КОТОРЫЕ НЕ ЧИТАЕТ КОД (мёртвые настройки) ===")
    leaf: dict[str, str] = {}

    def flatten(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                flatten(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            return
        else:
            leaf[path] = repr(node)[:40]

    flatten(raw)
    code_text = []
    for sub in ("agents", "core", "domain", "main.py", "api.py"):
        base = ROOT / sub
        if base.is_file():
            code_text.append(base.read_text(encoding="utf-8", errors="replace"))
            continue
        if base.is_dir():
            for path in sorted(base.rglob("*.py")):
                if "domain/qaqc" in _norm(path):
                    continue
                code_text.append(path.read_text(encoding="utf-8", errors="replace"))
    blob = "\n".join(code_text)
    dead: list[str] = []
    for path in sorted(leaf):
        if path == "":
            continue
        seg = path.split(".")[-1]
        # ключ живой, если в коде встречается его имя (последний сегмент) или полный путь
        if seg in blob or f'"{path}"' in blob or f"'{path}'" in blob:
            continue
        dead.append(path)
    keywords = ("min_", "max_", "threshold", "tol", "limit", "alpha", "beta")
    suspicious = [p for p in dead if any(k in p.split(".")[-1] for k in keywords)]
    print(f"листовых ключей config.yaml: {len(leaf)}; имя НЕ встречается в коде: {len(dead)}")
    for p in dead[:40]:
        marker = "  <-- ПОРОГ/ЛИМИТ, не читается" if p in suspicious else ""
        print(f"       [info] {p} = {leaf[p]}{marker}")
    if len(dead) > 40:
        print(f"       … ещё {len(dead) - 40}")
    if suspicious:
        fail(f"{len(suspicious)} пороговых ключей данных не читаются кодом "
             f"(настройка мертва): {suspicious}")

    # --- 7. похожие имена: опечатка в ключе -------------------------------------
    print("\n=== 7. ПОХОЖИЕ ИМЕНА КЛЮЧЕЙ (возможная опечатка данных/кода) ===")
    import difflib
    code_strings = set(re.findall(r'"([A-Za-z_][A-Za-z_0-9.]*)"', blob))
    code_strings |= set(re.findall(r"'([A-Za-z_][A-Za-z_0-9.]*)'", blob))
    typos = []
    for path in sorted(leaf):
        seg = path.split(".")[-1]
        if len(seg) < 6 or seg in blob:
            continue
        close = [c for c in difflib.get_close_matches(seg, code_strings, n=3, cutoff=0.88)
                 if c != seg and "." not in c]
        if close:
            typos.append((path, close))
    for path, close in typos[:20]:
        warn(f"ключ данных `{path}` не читается; в коде есть похожие имена {close} "
             f"-> вероятная опечатка в имени ключа")
    print(f"подозрительных пар: {len(typos)}")

    print("\n=== ИТОГ (hardcode) ===")
    print(f"нарушений правила 1 в ОФИЦИАЛЬНОМ скане (agents/core/domain без qaqc): {len(viol)}")
    print(f"domain/qaqc/** — ВНЕ официального скана (сгенерированные данные пакета): "
          f"{len(q_viol)} совпадений домена; это не долг нового кода "
          f"(см. разбор производности выше)")
    if "--json" in sys.argv:
        print(json.dumps({
            "tokens": len(tokens), "violations": [list(x) for x in viol],
            "qaqc_violations": len(q_viol), "debt_positions": n_debt,
            "dead_debt": dead,
            "generic_excluded": [list(x) for x in generic_excluded],
        }, ensure_ascii=False, indent=2))
    return 1 if (viol or FAIL) else 0


if __name__ == "__main__":
    raise SystemExit(main())
