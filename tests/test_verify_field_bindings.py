"""АУДИТ ПРИВЯЗОК: хардкод, онтология и проектные файлы месторождений.

Написан верификатором (task-6/E11). Ничего в чужом коде не меняет.

Что проверяется (в дополнение к `tests/test_verify_hardcode.py`, который ищет домен
в рантайм-коде):
  1) ИМЯ ПОЛЯ в рантайм-коде: `agents/ core/ domain/ main.py api.py` не должны знать
     «Герасимовское»/имя файла проектного графа (допустимы только комментарии/docstring-и);
  2) ПРИВЯЗКИ К ПОЛЮ В ГЛОБАЛЬНЫХ ДАННЫХ: какие объектные имена поля лежат в `config.yaml`
     (а не в проектном графе) — цена добавления ВТОРОГО месторождения;
  3) ОНТОЛОГИЯ: держит ли `ontology/**` значения поля как ОБЯЗАТЕЛЬНЫЕ привязки
     (роли → аргументы — это схема; имена объектов поля — это привязка);
  4) ШАБЛОНЫ И ПРАВИЛА: чужие/демонстрационные токены (правило 7) — сколько файлов
     затронуто и что попадает в ОТРЕНДЕРЕННЫЙ воркфлоу (вне комментариев);
  5) ПУТИ: литеральные `data/`, `runs/run_`, `models/run_`, `ontology_project/` в коде;
  6) МНОГОПОЛЬНОСТЬ (эмпирика): что делает система при неизвестном имени поля
     (нет ли молчаливой подстановки чужого графа).

Запуск:  python -X utf8 tests/test_verify_field_bindings.py [--json]
Код возврата: 1 — есть привязка, требующая устранения (не в данных/не обобщена).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CODE_DIRS = ("agents", "core", "domain", "tools")
CODE_FILES = ("main.py", "api.py")
GRAPH_DIR = ROOT / "ontology_project"
TEMPLATES = ROOT / "domain" / "templates"
RULES = ROOT / "domain" / "ontology_rules"
RUN_DIR = ROOT / "runs" / "run_Герасимовское"

FAIL: list[str] = []
WARN: list[str] = []
INFO: list[str] = []


def fail(msg: str) -> None:
    FAIL.append(msg)
    print(f"[FAIL] {msg}")


def warn(msg: str) -> None:
    WARN.append(msg)
    print(f"[WARN] {msg}")


def _iter_code() -> list[Path]:
    out: list[Path] = []
    for sub in CODE_DIRS:
        base = ROOT / sub
        if base.is_dir():
            out += [p for p in sorted(base.rglob("*.py")) if "__pycache__" not in p.parts]
    out += [ROOT / f for f in CODE_FILES if (ROOT / f).is_file()]
    return out


def _code_without_comments(path: Path) -> str:
    return "\n".join(ln.split("#", 1)[0] for ln in
                     path.read_text(encoding="utf-8", errors="replace").splitlines())


def _string_literals_no_docstrings(path: Path) -> list[tuple[int, str]]:
    """Строковые литералы кода БЕЗ docstring-ов (как в официальном аудите правила 1)."""
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    docs: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and \
                    isinstance(body[0].value, ast.Constant) and \
                    isinstance(body[0].value.value, str):
                docs.add(id(body[0].value))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and \
                id(node) not in docs:
            out.append((node.lineno, node.value))
    return out


def section_field_name_in_code() -> None:
    print("=== 1. ИМЯ ПОЛЯ В РАНТАЙМ-КОДЕ (без комментариев И docstring-ов) ===")
    fields = {p.stem for p in GRAPH_DIR.glob("*.y*ml")}
    for cand in GRAPH_DIR.glob("*.y*ml"):
        try:
            import yaml
            data = yaml.safe_load(cand.read_text(encoding="utf-8")) or {}
            if data.get("field"):
                fields.add(str(data["field"]))
        except Exception:                              # noqa: BLE001
            pass
    try:
        from core.config import load_config
        cfg = load_config()
        fields.add(str(cfg.get("project.default_field") or ""))
    except Exception:                                  # noqa: BLE001
        pass
    fields = {f for f in fields if len(f) >= 3}
    print(f"  имён полей к проверке: {sorted(fields)}")
    hits = 0
    doc_only = 0
    for path in _iter_code():
        rel = path.relative_to(ROOT).as_posix()
        runtime = rel.split("/")[0] in ("agents", "core", "domain") or rel in ("main.py", "api.py")
        for lineno, value in _string_literals_no_docstrings(path):
            for name in fields:
                if value == name or name in value:
                    hits += 1
                    msg = (f"привязка к полю: {rel}:{lineno}: литерал «{value[:70]}» содержит "
                           f"«{name}» (значение поля в коде)")
                    if runtime:
                        fail(msg)
                    else:
                        warn(msg + " — не рантайм (tools/): допустимо как подпись, но лучше "
                                   "брать имя из данных")
                    break
        # docstring-и (примеры использования) — допустимо, фиксируем отдельно
        import ast
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                body = getattr(node, "body", None) or []
                if body and isinstance(body[0], ast.Expr) and \
                        isinstance(body[0].value, ast.Constant) and \
                        isinstance(body[0].value.value, str):
                    if any(n in body[0].value.value for n in fields):
                        doc_only += 1
                        print(f"  [info] docstring с именем поля (пример использования): "
                              f"{rel}:{body[0].lineno}")
    print(f"  привязок в КОДЕ (литералы вне docstring): {hits}; "
          f"упоминаний в docstring-ах (допустимо): {doc_only}")


def section_global_data_bindings() -> None:
    print("\n=== 2. ПРИВЯЗКИ К ПОЛЮ В ГЛОБАЛЬНЫХ ДАННЫХ (config.yaml) ===")
    import yaml
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    found: list[tuple[str, object]] = []

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for v in node:
                walk(v, path)
        else:
            found.append((path, node))

    walk(cfg)
    # «объектные» ключи: их значения — имена объектов/кубов/карт конкретного поля
    obj_keys = ("map_files", "map_sources", "map_kinds", "properties", "grid_name",
                "metric", "evidence", "foreign_tokens")
    rows = [(p, v) for p, v in found
            if any(k in p.split(".")[-1] or k in p for k in obj_keys)]
    for p, v in rows:
        print(f"  [info] config.yaml:{p} = {str(v)[:110]}")
    print(f"  объектных ключей в глобальном config.yaml: {len(rows)}")
    if rows:
        INFO.append(f"в config.yaml {len(rows)} ключей с именами объектов поля "
                    f"({sorted({p.split('.')[-1] for p, _ in rows})}) — при добавлении второго "
                    f"месторождения их придётся переопределять (в проектном графе таких ключей нет)")
        warn("имена объектов поля лежат в ГЛОБАЛЬНОМ config.yaml; для второго поля нужен "
             "механизм переопределения из проектного графа (или перенос секций в граф)")
    # есть ли в проектном графе аналогичные секции (переопределение)
    for g in GRAPH_DIR.glob("*.y*ml"):
        proj = yaml.safe_load(g.read_text(encoding="utf-8")) or {}
        overlap = [k for k in ("checks", "map_files", "properties", "map_kinds", "ensemble")
                   if k in proj]
        print(f"  проектный граф {g.name}: переопределяет глобальные секции {overlap or '—'}")


def section_ontology_bindings() -> None:
    print("\n=== 3. ОНТОЛОГИЯ: роль vs значение поля ===")
    import yaml
    files = sorted([*ROOT.glob("ontology/*.yaml"), *ROOT.glob("ontology/*.yml")])
    for f in files:
        data = yaml.safe_load(f.read_text(encoding="utf-8", errors="replace")) or {}
        if isinstance(data, dict):
            print(f"  [info] {f.name}: секций {len(data)}: {list(data)[:8]}")
    obr = ROOT / "ontology" / "object_binding_rules.yaml"
    if not obr.is_file():
        warn("нет ontology/object_binding_rules.yaml — привязки ролей к аргументам не описаны")
        return
    d = yaml.safe_load(obr.read_text(encoding="utf-8")) or {}
    policy = d.get("policy") or {}
    roles = d.get("roles") or {}
    no_source = []
    for role, spec in roles.items():
        if not isinstance(spec, dict) or not spec.get("source"):
            no_source.append(str(role))
    print(f"  object_binding_rules.roles: {len(roles)}; без источника данных: {len(no_source)}")
    print(f"  политика: mode={policy.get('mode')}, "
          f"replace_template_values={policy.get('replace_template_values')}, "
          f"on_unresolved_required={policy.get('on_unresolved_required')}, "
          f"on_unresolved_optional={policy.get('on_unresolved_optional')}")
    print(f"  примеры ролей: " + ", ".join(
        f"{k}→{(v or {}).get('source')}" for k, v in list(roles.items())[:5]))
    if no_source:
        fail(f"ontology/object_binding_rules.yaml: роли без источника данных (жёсткая "
             f"привязка): {no_source[:6]}")
    if str(policy.get("mode")) != "bind_from_field":
        warn(f"политика привязок не `bind_from_field` (сейчас {policy.get('mode')!r})")
    # bindings: ключи — распознаваемые значения шаблонов/демо → роль (правило 7)
    bindings = d.get("bindings") or {}
    if isinstance(bindings, dict) and bindings:
        sample = ", ".join(f"{k}→{(v or {}).get('role')}" for k, v in list(bindings.items())[:6])
        print(f"  bindings (распознаваемые значения → роль), {len(bindings)} шт.: {sample}")
        INFO.append("онтология привязок задана как «роль → путь в данных поля» "
                    "(`bind_from_field`), ключи `bindings` — распознаваемые значения "
                    "шаблонов, которые ЗАМЕНЯЮТСЯ данными поля; обобщаемо на другое поле")
    if policy.get("replace_template_values") is not True:
        warn("`replace_template_values` не True — чужие значения шаблонов могут остаться")


def section_templates_foreign() -> None:
    print("\n=== 4. ШАБЛОНЫ/ПРАВИЛА: чужие токены и что доходит до РЕНДЕРА ===")
    import yaml
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    foreign = [str(t) for t in (((cfg.get("workflow") or {}).get("foreign_tokens")) or [])]
    heur = ["C1tl", "C1bb", "S001", "Litho3D", "Res3D", "zone_id", "CS_trend",
            "paleo_Litho", "Amazonas", "2221900", "6022300", "491125", "7873501"]
    files_with = 0
    counts: dict[str, int] = {}
    for p in [*sorted(TEMPLATES.glob("*.txt")), *sorted(RULES.glob("*.rdf"))]:
        t = p.read_text(encoding="utf-8", errors="replace")
        hits = [k for k in foreign if k in t]
        if hits:
            files_with += 1
            for h in hits:
                counts[h] = counts.get(h, 0) + 1
    print(f"  файлов (шаблоны+правила) с чужими токенами из `workflow.foreign_tokens`: "
          f"{files_with}")
    print(f"  по токенам: {counts}")
    # что реально в ОТРЕНДЕРЕННОМ воркфлоу (вне комментариев)
    for d in (RUN_DIR, ROOT / "runs" / (RUN_DIR.name + "_dry")):
        wf = d / "Structure_modeling.py"
        if not wf.is_file():
            continue
        body = "\n".join(ln.split("#", 1)[0] for ln in
                         wf.read_text(encoding="utf-8", errors="replace").splitlines())
        left = [k for k in foreign if k in body]
        extra = [k for k in heur if k in body]
        print(f"  рендер {wf.relative_to(ROOT)}: foreign={left or '—'}; "
              f"эвристика вне конфига={extra or '—'}")
        if left:
            fail(f"правило 7: в рендере {wf.name} остались чужие токены {left}")
        for e in extra:
            INFO.append(f"в рендере встречается «{e}» — проверить: если это имя API "
                        f"тНава (напр. AmazonasParameters), это СХЕМА, а не чужой объект")


def _field_object_names() -> dict[str, str]:
    """Канонический список КОНКРЕТНЫХ ОБЪЕКТОВ поля: {имя: откуда взято}.

    Берём только имена объектов тНава (obj_name), имена кубов/карт/сетки/метрики —
    мнемоники LAS (LIT/PHIE/KINT) и id правил (RULE_LIT_*, QC_PERM_*) сюда НЕ попадают,
    иначе подстрочный поиск даёт ложные совпадения.
    """
    import yaml
    names: dict[str, str] = {}
    try:
        from core.config import load_config
        cfg = load_config()
        grid = str(cfg.get("project.grid_name") or "")
        if grid:
            names[grid] = "config:project.grid_name"
        for v in (cfg.get("checks.map_files") or []):
            names[str(v)] = "config:checks.map_files"
        for role, spec in (cfg.get("checks.properties") or {}).items():
            if isinstance(spec, dict) and spec.get("cube"):
                names[str(spec["cube"])] = f"config:checks.properties.{role}.cube"
        metric = str(cfg.get("ensemble.metric") or "")
        if metric:
            names[metric] = "config:ensemble.metric"
    except Exception:                                  # noqa: BLE001
        pass
    for g in GRAPH_DIR.glob("*.y*ml"):
        proj = yaml.safe_load(g.read_text(encoding="utf-8")) or {}

        def walk(node, path=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, f"{path}.{k}" if path else str(k))
            elif isinstance(node, list):
                for v in node:
                    walk(v, path)
            elif isinstance(node, str) and len(node) >= 3:
                leaf = path.split(".")[-1]
                if leaf == "obj_name":                 # имя объекта тНава — точно объект
                    names.setdefault(node, f"{g.name}:{path}")

        walk(proj)
    return names


def _object_rx(name: str) -> re.Pattern:
    """Точное совпадение имени объекта: `_` и `-` считаются частью идентификатора."""
    return re.compile(rf"(?<![\w\-]){re.escape(name)}(?![\w\-])")


def section_ontology_object_bindings() -> None:
    """Привязка к КОНКРЕТНОМУ объекту поля внутри ОНТОЛОГИИ (данные и правила).

    Классификация совпадений:
      * `value`   — имя объекта стоит ЗНАЧЕНИЕМ (роль/source/binding) → это ПРИВЯЗКА;
      * `key`     — имя объекта стоит КЛЮЧОМ (распознаваемое значение шаблона) → дизайн
                    `replace_template_values`, привязкой не является;
      * `comment` — только в комментарии/докстроке.
    Совпадения внутри составных идентификаторов (`RULE_LIT_*`, `QC_PERM_*`, `AG_FACIES`,
    `G-FACIES`, `BR_POROSITY_MODEL`) не считаются: это идентификаторы СХЕМЫ.
    """
    print("\n=== 7. ОНТОЛОГИЯ: привязка к КОНКРЕТНОМУ объекту поля ===")
    names = _field_object_names()
    rxs = {n: _object_rx(n) for n in names}
    print(f"  конкретных объектов поля к проверке: {len(names)}: {', '.join(sorted(names))}")
    targets = [*sorted((ROOT / "ontology").glob("*.yaml")),
               *sorted((ROOT / "ontology").glob("*.yml")),
               *sorted((ROOT / "ontology").glob("*.rdf")),
               *sorted(RULES.glob("*.rdf")),
               *sorted(RULES.glob("*.yaml"))]
    key_hits = val_hits = com_hits = 0
    bound: list[str] = []
    for p in targets:
        rel = p.relative_to(ROOT).as_posix()
        for i, raw in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            line = raw.strip()
            if not line:
                continue
            found = [n for n, rx in rxs.items() if rx.search(raw)]
            if not found:
                continue
            if line.startswith("#"):
                com_hits += 1
                continue
            for n in found:
                is_key = bool(re.match(rf"^\s*[\"']?{re.escape(n)}[\"']?\s*:", raw))
                if is_key:
                    key_hits += 1
                    print(f"  [info] {rel}:{i}: «{n}» — КЛЮЧ (распознаваемое значение "
                          f"шаблона → роль; дизайн `replace_template_values`): {line[:70]}")
                else:
                    val_hits += 1
                    bound.append(f"{rel}:{i}:{n}")
                    print(f"  [WARN] {rel}:{i}: «{n}» стоит ЗНАЧЕНИЕМ → привязка к "
                          f"конкретному объекту поля: {line[:80]}")
    print(f"  совпадений: значениями (привязка) — {val_hits}; ключами — {key_hits}; "
          f"в комментариях — {com_hits}")
    if val_hits:
        warn(f"в онтологии {val_hits} мест, где имя конкретного объекта поля стоит "
             f"ЗНАЧЕНИЕМ: {bound[:8]}")
    else:
        print("  ВЫВОД: привязок к конкретным объектам поля в данных онтологии НЕТ — "
              "только роли, ключи распознавания и комментарии")
    # машинный эталон — отдельная категория: это ЧУЖОЙ проект (данные эталона)
    ref = RULES / "reference_workflow.py"
    if ref.is_file():
        t = ref.read_text(encoding="utf-8", errors="replace")
        own = sorted(n for n in names if _object_rx(n).search(t))
        print(f"  машинный эталон reference_workflow.py: собственные объекты поля — "
              f"{own or 'нет'} (эталон — данные чужого проекта, правилом 2 разрешён)")
    # правила функций (RDF) — что в них вообще есть, кроме id схемы
    rdf_names = sorted({p.stem for p in RULES.glob("*.rdf")})
    print(f"  правил функций (RDF): {len(rdf_names)}; с объектами поля: "
          f"{[n for n in rdf_names if any(_object_rx(o).search((RULES / (n + '.rdf')).read_text(encoding='utf-8', errors='replace')) for o in names)] or 'нет'}")


def section_paths_in_code() -> None:
    print("\n=== 5. ЛИТЕРАЛЬНЫЕ ПУТИ ПРОЕКТА В КОДЕ (литералы вне docstring) ===")
    pats = [r'data/', r'runs/run_', r'models/run_', r'ontology_project/',
            r'data/Герасимовск', r'runs/run_Герасимовск', r'models/run_Герасимовск']
    hits = 0
    for path in _iter_code():
        rel = path.relative_to(ROOT).as_posix()
        for lineno, value in _string_literals_no_docstrings(path):
            for rx in pats:
                if re.search(rx, value):
                    hits += 1
                    kind = "FAIL" if rel.split("/")[0] in ("agents", "core", "domain") else "info"
                    msg = (f"литеральный проектный путь: {rel}:{lineno}: «{value[:80]}»")
                    if kind == "FAIL":
                        fail(msg)
                    else:
                        print(f"  [info] {msg} (не рантайм: {rel.split('/')[0]}/)")
                    break
    print(f"  литеральных проектных путей в литералах кода: {hits}")


def section_multifield() -> None:
    print("\n=== 6. МНОГОПОЛЬНОСТЬ: поведение при неизвестном поле ===")
    try:
        from core.config import load_config
        from core.coordinator import Coordinator
    except Exception as exc:                           # noqa: BLE001
        warn(f"не удалось импортировать координатор: {exc}")
        return
    c = Coordinator(load_config())
    default_field = str(c.cfg.get("project.default_field") or "")
    g_default = c.project_graph(default_field) or {}
    g_other = c.project_graph("НЕСУЩЕСТВУЮЩЕЕ_ПОЛЕ") or {}
    print(f"  {default_field!r}: стадий {len(g_default.get('pipeline') or [])}, "
          f"вариаций {len(g_default.get('variations') or [])}")
    print(f"  'НЕСУЩЕСТВУЮЩЕЕ_ПОЛЕ': field={g_other.get('field')!r}, "
          f"стадий {len(g_other.get('pipeline') or [])}, "
          f"вариаций {len(g_other.get('variations') or [])}, "
          f"dataset_root={str(g_other.get('dataset_root'))[:60]!r}")
    if g_other.get("field") == default_field:
        fail("при неизвестном поле система МОЛЧА подставила проектный граф другого поля")
    elif g_other:
        INFO.append("при неизвестном поле граф ВЫВОДИТСЯ из онтологии (не подставляется "
                    "чужой проектный YAML) — обобщаемость архитектуры подтверждена")
    else:
        warn("при неизвестном поле граф пуст — проверить сообщение об ошибке для оператора")
    try:
        nodes = c.assembler("НЕСУЩЕСТВУЮЩЕЕ_ПОЛЕ").node_genes()
        print(f"  assembler('НЕСУЩЕСТВУЮЩЕЕ_ПОЛЕ'): узлов {len(nodes)}")
    except Exception as exc:                           # noqa: BLE001
        warn(f"assembler на неизвестном поле упал: {exc}")


def main() -> int:
    print(f"АУДИТ ПРИВЯЗОК: {ROOT}\n")
    section_field_name_in_code()
    section_global_data_bindings()
    section_ontology_bindings()
    section_templates_foreign()
    section_paths_in_code()
    section_ontology_object_bindings()
    section_multifield()
    print("\n=== ИТОГ (field bindings) ===")
    print(f"FAIL: {len(FAIL)} | WARN: {len(WARN)} | INFO: {len(INFO)}")
    if "--json" in sys.argv:
        print(json.dumps({"fail": FAIL, "warn": WARN, "info": INFO},
                         ensure_ascii=False, indent=2))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
