"""НЕЗАВИСИМЫЙ АУДИТ ТРИАД (правило 2) и ПРОИСХОЖДЕНИЯ ШАБЛОНОВ (правило 8).

Написан верификатором (task-6), НЕ авторами кода. Ничего в чужом коде не меняет.

Что проверяется:
  A. Для каждой функции тНава, объявленной в `ontology_project/*.yaml` (pipeline или
     секция `functions:`), есть ли ВСЕ ТРИ части триады:
        1) domain/templates/<fn>.txt         — сырой шаблон;
        2) domain/ontology_rules/<fn>.rdf    — правило (label/code/шаблон_кода);
        3) блок шага в проектном YAML        — stage → function → objects/parameters/replace.
     Плюс обратная проверка: шаблон без правила и правило без шаблона.
  B. Источник шаблона (правило 8): вызов функции ищется
        1) в МАШИННОМ ЭТАЛОНЕ `domain/ontology_rules/reference_workflow.py` (разбор AST);
        2) во ВСЕХ *.md/*.py протоколов прогонов v7 (docs/tasks, tools, README);
        3) в README/docs самого v8;
     иначе — «источник не подтверждён».
  C. Шаблоны, ПОЯВИВШИЕСЯ ПОСЛЕ базовой линии (сверка с docs/VERIFY_baseline_manifest.md),
     обязаны иметь подтверждённый источник: новый шаблон без источника — FAIL правила 8.
     Старые (базовые) шаблоны без источника — INFO (долг доработки, не регресс).
  D. Ложная ссылка на эталон: если комментарий шаблона/правила утверждает, что вызов
     взят ИЗ эталона v26.1, а функции в эталоне нет — FAIL правила 8.
     Формулировки «не из эталона / проверить на лицензии» считаются честными (WARN).
  E. Аргументы шаблона сверяются с вызовом той же функции в эталоне (AST):
      * аргументы шаблона, которых нет в эталоне -> WARN «требует внешнего источника»;
      * аргументы YAML-блока, которых нет в шаблоне (ни на одном уровне вложенности)
        -> FAIL: значение шага молча не подставится / render_warning.
  F. Функции эталона, для которых триады НЕТ (task-3 требует их добавить) — список.

Запуск:  python -X utf8 tests/test_verify_triads.py [--json] [--verbose]
Код возврата: 0 — нарушений нет; 1 — есть находки уровня FAIL.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEMPLATES = ROOT / "domain" / "templates"
RULES = ROOT / "domain" / "ontology_rules"
GRAPH_DIR = ROOT / "ontology_project"
REFERENCE = RULES / "reference_workflow.py"
MANIFEST = ROOT / "docs" / "VERIFY_baseline_manifest.md"
V7_ROOT = ROOT.parent / "orchestrator_v7"
V8_DOC_HINTS = [ROOT / "README.md", ROOT / "docs", ROOT / "README_legacy.md",
                ROOT / "tools"]
# ещё один машинный источник: воркфлоу, СГЕНЕРИРОВАННЫЕ самим тНавом (туториалы 26.2)
TNAV_TUTORIALS = Path(r"C:\Program Files\tNavigator\26.2\tutorials")
# отчёты дешёвых проб на живой лицензии (root: _probe_*.txt)
PROBE_REPORTS = sorted(ROOT.glob("_probe_*.txt"))

_FAIL_RE: list[str] = []
FAIL: list[str] = []
WARN: list[str] = []
_CITED = re.compile(r"[A-Za-z0-9_./\\-]+\.(?:py|txt|md|csv|xlsx|pdf)\b")
_QUOTED = re.compile(r"[«\"']([^»\"']{12,200})[»\"']")

# имена, которые в эталоне являются объектами-ролями/конструкторами, а не функциями тНава
_NON_TNAV = {"typed_object_name", "absolute_object_name", "find_object",
             "declare_workflow", "check_launch_method", "begin_user_imports",
             "end_user_imports", "begin_wf_item", "end_wf_item", "print", "open",
             "datetime", "timedelta", "getattr", "setattr", "len", "range", "list",
             "dict", "str", "int", "float", "bool", "Comparator", "ColorDataContinuous"}


def _is_helper_class(fn: str) -> bool:
    """Классы-параметры API (Grid2DSettings, VariogramParameters...) — не функции тНава."""
    return fn.endswith(("Parameters", "Settings", "Data", "Parameters_"))


def fail(msg: str) -> None:
    FAIL.append(msg)
    print(f"[FAIL] {msg}")


def warn(msg: str) -> None:
    WARN.append(msg)
    print(f"[WARN] {msg}")


# --- AST-разбор эталона -------------------------------------------------------
def reference_calls() -> dict[str, list[set[str]]]:
    """{fn: [набор аргументов каждого вызова]} по AST reference_workflow.py.

    Аргументы собираются на ВСЕХ уровнях вложенности вызова (чтобы сравнение с
    текстовым разбором шаблона было честным: там regex тоже видит вложенные ключи).
    """
    tree = ast.parse(REFERENCE.read_text(encoding="utf-8", errors="replace"))
    out: dict[str, list[set[str]]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = node.func.id
            if fn in _NON_TNAV or fn.startswith("_") or _is_helper_class(fn):
                continue
            kwargs: set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.keyword) and sub.arg:
                    kwargs.add(sub.arg)
            out.setdefault(fn, []).append(kwargs)
    return out


# --- текстовый разбор шаблона -------------------------------------------------
_CALL = r"(?<![\w.]){fn}\s*\("


def _call_spans(text: str, fn: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for m in re.finditer(_CALL.format(fn=re.escape(fn)), text):
        i = text.find("(", m.start())
        depth = 0
        quote = ""
        j = i
        while j < len(text):
            ch = text[j]
            if quote:
                if ch == "\\":
                    j += 2
                    continue
                if ch == quote:
                    quote = ""
            elif ch in "\"'":
                quote = ch
            elif ch == "#":
                nl = text.find("\n", j)
                j = len(text) if nl < 0 else nl
                continue
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    out.append((m.start(), j + 1))
                    break
            j += 1
    return out


_KW = re.compile(r"(?<![\w.])([A-Za-z_][A-Za-z_0-9]*)[\"']?\s*[:=]")


def template_kwargs(text: str, fn: str) -> tuple[set[str], list[int]]:
    """Аргументы, реально встречающиеся в вызовах fn(...) шаблона (любой уровень)."""
    names: set[str] = set()
    lines: list[int] = []
    for start, end in _call_spans(text, fn):
        body = text[start:end]
        lines.append(text.count("\n", 0, start) + 1)
        for m in _KW.finditer(body):
            names.add(m.group(1))
    return names, lines


# --- источник -----------------------------------------------------------------
def load_v7_corpus() -> dict[str, str]:
    corpus: dict[str, str] = {}
    for ext in ("*.md", "*.py", "*.txt"):
        for f in V7_ROOT.rglob(ext):
            if "__pycache__" in f.parts:
                continue
            try:
                if f.stat().st_size > 4_000_000:
                    continue
                corpus[str(f)] = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    for hint in V8_DOC_HINTS:
        files = [hint] if hint.is_file() else (sorted(hint.rglob("*.md")) +
                                               sorted(hint.rglob("*.py")) +
                                               sorted(hint.rglob("*.txt"))
                                               if hint.is_dir() else [])
        for f in files:
            try:
                if f.is_file() and f.stat().st_size < 4_000_000:
                    corpus[str(f)] = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    for f in PROBE_REPORTS:                        # отчёты проб на лицензии
        try:
            corpus[str(f)] = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    if TNAV_TUTORIALS.is_dir():                    # воркфлоу, сгенерированные тНавом
        for f in TNAV_TUTORIALS.rglob("*.py"):
            try:
                if f.stat().st_size < 4_000_000:
                    corpus[str(f)] = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return corpus


def _short(path: str) -> str:
    for base, tag in ((str(TNAV_TUTORIALS), "tNav-tutorials"),
                      (str(ROOT.parent), ""), (str(ROOT), "")):
        if path.startswith(base):
            rel = path[len(base):].lstrip("\\/")
            return f"{tag}/{rel}" if tag else rel
    return path


def source_of(fn: str, ref_calls: dict, corpus: dict[str, str]) -> tuple[str, str]:
    if fn in ref_calls:
        return "reference", "domain/ontology_rules/reference_workflow.py"
    rx = re.compile(_CALL.format(fn=re.escape(fn)))
    for path, text in corpus.items():
        if rx.search(text):
            return "doc", _short(path)
    return "none", ""


def cited_evidence(path: Path, corpus: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    """По комментариям шаблона: (существующие ссылки, несуществующие, неподтверждённые цитаты)."""
    if not path.is_file():
        return [], [], []
    text = path.read_text(encoding="utf-8", errors="replace")
    comments = "\n".join(ln for ln in text.splitlines() if ln.lstrip().startswith("#"))
    exist, missing = [], []
    for m in _CITED.finditer(comments):
        raw = m.group(0).replace("\\", "/")
        cands = [ROOT / raw, ROOT.parent / raw, Path(raw),
                 TNAV_TUTORIALS / raw.lstrip("./")]
        hit = next((c for c in cands if c.exists()), None)
        (exist if hit else missing).append(raw)
    unverified = []
    for m in _QUOTED.finditer(comments):
        frag = m.group(1).strip()
        if len(frag) < 15 or "." not in frag:
            continue
        if not any(frag in t for t in corpus.values()):
            unverified.append(frag[:60])
    return sorted(set(exist)), sorted(set(missing)), unverified


_POSITIVE = re.compile(
    r"(источник|взят|взято|шаблон\s+из|стр\.|строк[аи]|line|reference_workflow|эталон)",
    re.IGNORECASE)
# ссылка именно на МАШИННЫЙ эталон v26.1 (reference_workflow.py), а не на туториал/мануал
_MACHINE_REF = re.compile(r"(reference_workflow|машинн\w*\s+эталон|v26\.1)", re.IGNORECASE)
_NEGATIVE = re.compile(
    r"(не\s+из\s+(?:\w+\s+)?эталон|нет\s+(?:его\s+)?в\s+(?:\w+\s+)?эталон|"
    r"отсутствует\s+в\s+(?:\w+\s+)?эталон|не\s+подтвержд|проверить|подобрана|"
    r"не\s+найден|сигнатура\s+функции\s+не\s+из)", re.IGNORECASE)
# коды туториалов/мануалов тНава: CLOUD1.2, GD2.2, COMMON1.7, ZAV1.1 …
_TUTORIAL = re.compile(r"\b([A-Z]{2,}[A-Za-z]*\d+\.\d+)\b")


def source_claims(path: Path) -> tuple[bool, bool, str, list[str]]:
    """(ссылается_на_машинный_эталон, оговаривает_что_не_из_эталона,
        заявленный_источник_строкой, коды_туториалов)."""
    if not path.is_file():
        return False, False, "", []
    claims = neg = False
    claimed = ""
    tutorials: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.lstrip().startswith("#"):
            continue
        if _MACHINE_REF.search(line):
            if _NEGATIVE.search(line):
                neg = True
            else:
                claims = True
        if not claimed and "эталон" in line.lower():
            claimed = line.lstrip("# ").strip()
        tutorials += _TUTORIAL.findall(line)
    return claims, neg, claimed, sorted(set(tutorials))


def baseline_templates() -> set[str]:
    """Имена шаблонов, существовавших на базовой линии (из манифеста верификатора)."""
    if not MANIFEST.is_file():
        return set()
    out = set()
    for line in MANIFEST.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.search(r"domain/templates/([A-Za-z0-9_]+)\.txt$", line.strip())
        if m:
            out.add(m.group(1))
    return out


def main() -> int:
    import yaml

    verbose = "--verbose" in sys.argv
    if not REFERENCE.is_file():
        fail(f"нет машинного эталона {REFERENCE}")
        return 1
    ref_calls = reference_calls()
    ref_functions = sorted(ref_calls)
    print(f"эталон (AST): {len(ref_functions)} функций: {', '.join(ref_functions)}")

    graphs = sorted([*GRAPH_DIR.glob("*.yaml"), *GRAPH_DIR.glob("*.yml")])
    if not graphs:
        fail("в ontology_project/ нет проектного YAML")
        return 1

    declared: dict[str, list[str]] = {}
    steps_by_fn: dict[str, int] = {}
    yaml_blocks: dict[str, list[dict]] = {}
    for g in graphs:
        proj = yaml.safe_load(g.read_text(encoding="utf-8")) or {}
        for ov_fn, ov in (proj.get("functions") or {}).items():
            yaml_blocks.setdefault(ov_fn, []).append(ov or {})
            declared.setdefault(ov_fn, []).append(f"{g.name}:functions")
        for si, stage in enumerate(proj.get("pipeline") or [], start=1):
            label = str(stage.get("stage", f"этап {si}"))
            for step in stage.get("steps") or []:
                fn = step.get("function")
                if not fn:
                    continue
                declared.setdefault(fn, []).append(f"{g.name}:{label}")
                steps_by_fn[fn] = steps_by_fn.get(fn, 0) + 1
                if any(k in step for k in ("parameters", "objects", "replace", "lists", "glob")):
                    yaml_blocks.setdefault(fn, []).append(step)

    # ---- A: триады -----------------------------------------------------------
    print(f"\n=== A. ТРИАДЫ (правило 2): объявлено функций {len(declared)} ===")
    defaults_only: list[str] = []
    for fn in sorted(declared):
        tpl = TEMPLATES / f"{fn}.txt"
        rdf = RULES / f"{fn}.rdf"
        have_t = tpl.is_file() and tpl.stat().st_size > 20
        have_r = rdf.is_file() and rdf.stat().st_size > 20
        # третий элемент триады: блок «этап → функция» (со своими parameters/objects/
        # replace ИЛИ с дефолтами шаблона, если шаг объявлен без них)
        have_step = steps_by_fn.get(fn, 0) > 0
        have_global = any(src.endswith(":functions") for src in declared[fn])
        have_b = have_step or have_global
        if have_step and fn not in yaml_blocks:
            defaults_only.append(fn)
        mark = "OK  " if (have_t and have_r and have_b) else "FAIL"
        print(f"[{mark}] {fn:<48} template={have_t} rdf={have_r} yaml_block={have_b} "
              f"шагов={steps_by_fn.get(fn, 0)} где={declared[fn][0]}")
        if not have_t:
            fail(f"правило 2: нет шаблона domain/templates/{fn}.txt (объявлен в {declared[fn]})")
        if not have_r:
            fail(f"правило 2: нет правила domain/ontology_rules/{fn}.rdf (объявлен в {declared[fn]})")
        if not have_b:
            fail(f"правило 2: функция {fn} объявлена, но блока «этап → функция» нет")
    if defaults_only:
        print(f"[info] шаги без явных parameters/objects/replace (дефолты шаблона): "
              f"{', '.join(defaults_only)}")

    tpl_names = {p.stem for p in TEMPLATES.glob("*.txt")} - {"template_wf"}
    rdf_names = {p.stem for p in RULES.glob("*.rdf")} - {"ontology"}
    for fn in sorted(rdf_names - tpl_names):
        fail(f"правило 2: есть правило {fn}.rdf, но нет шаблона {fn}.txt (неполная триада)")
    for fn in sorted(tpl_names - rdf_names):
        fail(f"правило 2: есть шаблон {fn}.txt, но нет правила {fn}.rdf (неполная триада)")

    # ---- B/C/D/E: источник и аргументы --------------------------------------
    print("\n=== B/C/D/E. ИСТОЧНИК ШАБЛОНА и АРГУМЕНТЫ (правило 8) ===")
    corpus = load_v7_corpus()
    print(f"корпус источников v7/v8: {len(corpus)} файлов")
    base_tpl = baseline_templates()
    print(f"базовых шаблонов по манифесту: {len(base_tpl)}; текущих: {len(tpl_names)}")
    new_tpl = sorted(tpl_names - base_tpl)
    print(f"НОВЫХ шаблонов: {len(new_tpl)}: {', '.join(new_tpl) if new_tpl else '-'}")

    unconfirmed: list[str] = []
    new_unconfirmed: list[str] = []
    for fn in sorted(tpl_names):
        tpl = TEMPLATES / f"{fn}.txt"
        rdf = RULES / f"{fn}.rdf"
        cls, where = source_of(fn, ref_calls, corpus)
        tpl_text = tpl.read_text(encoding="utf-8", errors="replace")
        is_new = fn not in base_tpl
        claims_ref, honest_neg, claimed, tutorials = source_claims(tpl)
        claimed_tut: list[str] = []
        if rdf.is_file():
            r_pos, r_neg, r_claimed, r_tut = source_claims(rdf)
            claims_ref = claims_ref or r_pos
            honest_neg = honest_neg or r_neg
            claimed = claimed or r_claimed
            claimed_tut = r_tut

        note = ""
        cit_exist, cit_missing, cit_unverified = cited_evidence(tpl, corpus)
        if cls == "reference":
            ref_kw: set[str] = set()
            for s in ref_calls[fn]:
                ref_kw |= s
            tpl_kw, _lines = template_kwargs(tpl_text, fn)
            invented = sorted(tpl_kw - ref_kw)
            lost = sorted(ref_kw - tpl_kw)
            note = f"эталон, аргументов {len(ref_kw)}/{len(tpl_kw)}"
            if invented:
                warn(f"правило 8: {fn}: аргументы шаблона отсутствуют в эталоне: {invented}"
                     + (" [НОВЫЙ шаблон]" if is_new else " [базовый]"))
                note += f", лишние={invented}"
            if lost:
                warn(f"правило 8: {fn}: аргументы эталона пропущены в шаблоне: {lost}")
        elif cls == "doc":
            note = f"документ: {where}"
        else:
            note = "ИСТОЧНИК НЕ ПОДТВЕРЖДЁН"
            if claimed:
                note += f" | заявлено: «{claimed[:90]}»"
            if claimed_tut:                    # коды туториалов/мануалов — трассируемы?
                traced = []
                for code in claimed_tut:
                    hit = next((p for p, t in corpus.items() if code in t), "")
                    traced.append(f"{code}{'✓' if hit else '✗'}")
                note += f" | туториалы: {', '.join(traced)}"
            if cit_exist:
                note += f" | цитируемые файлы есть: {cit_exist[:3]}"
            if cit_missing:
                fail(f"правило 8: {fn}: шаблон ссылается на НЕ существующий источник: "
                     f"{cit_missing[:3]}")
            unconfirmed.append(fn)
            if is_new:
                new_unconfirmed.append(fn)
                fail(f"правило 8: НОВЫЙ шаблон {fn}.txt без подтверждённого источника "
                     f"(нет вызова в reference_workflow.py, нет в корпусе docs/probe v7/v8)")
        if cit_unverified:
            warn(f"правило 8: {fn}: цитата из комментария не найдена ни в одном источнике — "
                 f"проверить вручную: {cit_unverified[:2]}")

        if claims_ref and fn not in ref_calls:
            msg = (f"правило 8: {fn}: комментарий ссылается на МАШИННЫЙ эталон v26.1, "
                   f"но вызова {fn}() в reference_workflow.py НЕТ")
            if honest_neg:
                warn(msg + " (в комментарии есть оговорка «не из эталона/проверить»)")
            else:
                fail(msg)
        if cls != "none" or verbose:
            print(f"[{'OK  ' if cls != 'none' else 'WARN'}] {fn:<48} {note}")

        # E2: ключи YAML-блока должны присутствовать в шаблоне (любой уровень)
        keys: set[str] = set()
        for b in yaml_blocks.get(fn, []):
            keys |= set((b.get("objects") or {}).keys())
            keys |= set((b.get("parameters") or {}).keys())
            keys |= set((b.get("lists") or {}).keys())
            keys |= set((b.get("glob") or {}).keys())
        if keys:
            tpl_all, _ = template_kwargs(tpl_text, fn)
            if not tpl_all:                      # шаблон без вызова fn() — не с чем сверять
                missing = sorted(keys)
            else:
                missing = sorted(k for k in keys
                                 if k.split("(")[0].strip() not in tpl_all)
            if missing:
                fail(f"правило 2/8: {fn}: YAML-блок задаёт {missing}, которых нет в шаблоне "
                     f"-> значение шага не подставится (render_warning)")
            else:
                print(f"       └ ключи YAML ({len(keys)}) все найдены в шаблоне")

    if unconfirmed:
        print(f"\nшаблоны без подтверждённого источника ({len(unconfirmed)}):")
        for fn in unconfirmed:
            print(f"   - {fn}{'   <-- НОВЫЙ' if fn in new_unconfirmed else '   (был на базовой линии)'}")

    # ---- F: функции эталона без триады --------------------------------------
    print("\n=== F. ФУНКЦИИ ЭТАЛОНА БЕЗ ТРИАДЫ ===")
    no_triad = [fn for fn in ref_functions if fn not in tpl_names]
    for fn in no_triad:
        warn(f"эталон содержит {fn}(), но триады в v8 нет (шаг не рендерится)")
    if not no_triad:
        print("   все функции эталона покрыты триадами")
    not_declared = [fn for fn in ref_functions if fn not in declared]
    if not_declared:
        print(f"   при этом в пайплайн НЕ включены: {', '.join(not_declared)}")

    # ---- G: правило 4 (модель в отметках, горизонты bottom-first) -------------
    print("\n=== G. ПРАВИЛО 4: ПОРЯДОК ГОРИЗОНТОВ В СЕТКЕ (bottom-first) ===")
    for g in graphs:
        proj = yaml.safe_load(g.read_text(encoding="utf-8")) or {}
        struct = proj.get("structural") or {}
        top_marker = str(struct.get("interval_top_marker") or "")
        base_marker = str(struct.get("interval_base_marker") or "")
        if not (top_marker and base_marker):
            continue
        # какой горизонт построен по кровле/подошве интервала (данные пайплайна)
        built: dict[str, str] = {}
        grid_steps: list[dict] = []
        for stage in proj.get("pipeline") or []:
            for step in stage.get("steps") or []:
                fn = str(step.get("function") or "")
                if fn == "horizon_interpolate_by_marker_idw":
                    marker = str(((step.get("objects") or {}).get("well_marker")
                                  or {}).get("obj_name") or "")
                    res = str(((step.get("objects") or {}).get("result_horizon")
                               or {}).get("obj_name") or "")
                    if marker and res:
                        built[marker] = res
                if fn.startswith("grid_3d_create_by_horizons"):
                    grid_steps.append(step)
        top_h, base_h = built.get(top_marker, ""), built.get(base_marker, "")
        print(f"маркеры: кровля {top_marker} -> {top_h or '?'}; подошва {base_marker} -> "
              f"{base_h or '?'}; шагов сетки: {len(grid_steps)}")
        if not (top_h and base_h):
            warn("правило 4: не удалось определить горизонты кровли/подошвы по данным — "
                 "проверить вручную")
            continue
        for step in grid_steps:
            fn = str(step.get("function"))
            tpl = TEMPLATES / f"{fn}.txt"
            if not tpl.is_file():
                continue
            text = tpl.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"horizons_table\s*=\s*\[", text)
            if not m:
                warn(f"правило 4: {fn}: в шаблоне нет horizons_table — проверить вручную")
                continue
            tail = text[m.end():]
            end = tail.find("]")
            rows = re.findall(r'"horizon"\s*:\s*(?:find_object|typed_object_name)\s*\(name="([^"]*)"',
                              tail[:end if end > 0 else len(tail)])
            repl = step.get("replace") or {}
            order = []
            for row in rows:
                target = repl.get(f'name="{row}"', f'name="{row}"')
                order.append(str(target).replace('name=', "").strip('"'))
            print(f"  {fn}: строки horizons_table {rows} -> после replace {order}")
            if len(order) < 2:
                warn(f"правило 4: {fn}: в horizons_table меньше двух горизонтов")
                continue
            if order[0] != base_h or order[-1] != top_h:
                fail(f"правило 4: {fn}: горизонты в horizons_table идут {order}, а для модели "
                     f"в отметках нужно СНИЗУ ВВЕРХ: первой — подошва {base_h}, последней — "
                     f"кровля {top_h}")
            else:
                print(f"  [OK ] правило 4: {fn}: снизу вверх ({base_h} … {top_h})")

    # ---- H: вариации ансамбля адресуют функции ИЗ ПАЙПЛАЙНА ------------------
    print("\n=== H. ВАРИАЦИИ АНСАМБЛЯ: функция вариации должна быть в пайплайне (E10) ===")
    for g in graphs:
        proj = yaml.safe_load(g.read_text(encoding="utf-8")) or {}
        used = set()
        for stage in proj.get("pipeline") or []:
            for step in stage.get("steps") or []:
                if step.get("function"):
                    used.add(str(step["function"]))
        for var in proj.get("variations") or []:
            vid = str(var.get("id") or "?")
            params = var.get("parameters") or {}
            for fn, prm in params.items():
                if str(fn) in used:
                    print(f"  [OK ] {vid}: {fn} в пайплайне, параметры {prm}")
                else:
                    fail(f"E10: вариация {vid} адресует функцию «{fn}», которой НЕТ в пайплайне "
                         f"-> ветка вырождена (параметры {prm} не применяются)")

    print("\n=== ИТОГ (triads) ===")
    print(f"FAIL: {len(FAIL)} | WARN: {len(WARN)} | функций в YAML: {len(declared)} | "
          f"шаблонов: {len(tpl_names)} | правил: {len(rdf_names)} | новых шаблонов: {len(new_tpl)}")
    if "--json" in sys.argv:
        print(json.dumps({"fail": FAIL, "warn": WARN, "new_templates": new_tpl,
                          "new_without_source": new_unconfirmed,
                          "reference_functions_without_triad": no_triad},
                         ensure_ascii=False, indent=2))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
