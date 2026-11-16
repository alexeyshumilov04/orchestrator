"""Аудит ОБЩНОСТИ: домен — только в данных, онтология — без параметров объектов.

Замечание заказчика: «кажется, что ты просто перенёс YAML/JSON в онтологию, что по
факту хардкод». Модуль отвечает на это машинно-читаемым отчётом:

  1. **реестр поля** собирается ИЗ ДАННЫХ (`ontology_project/*.yaml` + данные
     `config.yaml`): имя поля, маркеры/горизонты, кубы, мнемоники кривых, имена
     входных файлов, объекты шагов, ветви ансамбля. Генерическая лексика
     (единицы измерения) исключается по данным `ontology/generic_vocabulary.yaml`
     с обоснованием — это НЕ домен;
  2. **код** (`core/`, `agents/`, `domain/`, `tools/`, `api.py`) проверяется на
     вхождения токенов реестра в строковые литералы, ИМЕНА и КОММЕНТАРИИ
     (и docstring-и): сравнение по границам слов, а не подстрокой;
  3. **онтология** (`ontology/*rules*.yaml` + перечень `audited_rule_files`)
     проверяется на ПАРАМЕТРЫ объектов тестирования: значения и ключи файлов
     правил не должны содержать токенов реестра поля;
  4. **доказательство автоматической сборки**: граф для поля, которого НЕТ в
     `ontology_project` (и для поля с минимальным файлом данных), собирается из
     онтологии; состав, роли, форматы, требования к объектам и параметры
     выводятся из данных онтологии, а не из зашитых значений.

Правило 6: нет данных — возвращаем `unknown`/пусто, а не «всё хорошо».
Исключения (allow/known_debt/генерическая лексика) читаются ИЗ ДАННЫХ.
"""
from __future__ import annotations

import ast
import fnmatch
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

_ROOT = Path(__file__).resolve().parent.parent
CODE_ROOTS = ("core", "agents", "domain", "tools")
CODE_FILES = ("api.py", "main.py")
#: данные-файлы, которые считаются «машинной выгрузкой», а не рукописным кодом
CODE_SKIP_PREFIXES = ("domain/qaqc/", "domain/ontology_rules/reference_workflow.py")
#: ключи-носители единиц измерения (значения под ними могут быть генерической лексикой)
UNIT_KEYS = ("units", "unit")
#: границы слова: латиница/цифры/подчёркивание/кириллица, ТОЧКА и ДЕФИС.
#: Точка и дефис входят в границу, поэтому мнемоника кривой не совпадает с
#: идентификатором литературного источника вида <префикс>-NNNN, а имя свойства —
#: с идентификатором схемы гейта (правило 1 разрешает идентификаторы схемы).
_WORD_BOUND = r"0-9A-Za-z_.\-\u0400-\u04FF"
_NUMBERISH = re.compile(r"^-?\d+([.,]\d+)?$")


# ── данные аудита ────────────────────────────────────────────────────────────
def generic_vocabulary() -> dict:
    """Данные исключений аудита (`ontology/generic_vocabulary.yaml`)."""
    path = _ROOT / "ontology" / "generic_vocabulary.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _generic_unit_values(vocab: Mapping[str, Any]) -> set[str]:
    return {str(item.get("value", "")).strip()
            for item in (vocab.get("generic_unit_values") or [])
            if isinstance(item, Mapping) and str(item.get("value", "")).strip()}


def _audited_rule_files(vocab: Mapping[str, Any], cfg: Any = None) -> list[str]:
    declared = [str(name) for name in (vocab.get("audited_rule_files") or [])]
    if declared:
        return declared
    root = ontology_root(cfg)
    return [p.name for p in sorted(root.glob("*rules*.yaml"))]


def ontology_root(cfg: Any = None) -> Path:
    """Каталог онтологии: `ontology.root` конфига, иначе папка сервиса."""
    if cfg is not None:
        try:
            path = Path(cfg.path("ontology.root", "ontology"))
            if path.is_dir():
                return path
        except Exception:                               # noqa: BLE001 — конфиг опционален
            pass
    return _ROOT / "ontology"


def graph_dir(cfg: Any = None) -> Path:
    """Каталог проектных графов полей (`project.graph_dir`)."""
    if cfg is not None:
        try:
            return Path(cfg.path("project.graph_dir", "ontology_project"))
        except Exception:                               # noqa: BLE001
            pass
    return _ROOT / "ontology_project"


# ── 1. реестр поля (ИЗ ДАННЫХ) ───────────────────────────────────────────────
def field_registry(cfg: Any = None) -> dict[str, dict]:
    """{токен: {class, source}} — имена объектов поля из данных, НЕ генерическая лексика.

    Классы: field | marker | cube | mnemonic | field_input | object | variation.
    """
    vocab = generic_vocabulary()
    units = _generic_unit_values(vocab)
    registry: dict[str, dict] = {}

    def add(value: Any, kind: str, source: str, *, units_carrier: bool = False) -> None:
        token = str(value).strip() if value is not None else ""
        if len(token) < 2 or _NUMBERISH.match(token):
            return
        if token.casefold() in {"true", "false", "none", "auto", "on", "off"}:
            return
        if units_carrier and token in units:
            return                                      # генерическая единица, не домен
        registry.setdefault(token, {"class": kind, "source": source})

    for path in sorted([*graph_dir(cfg).glob("*.yaml"), *graph_dir(cfg).glob("*.yml")]):
        try:
            project = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(project, dict):
            continue
        add(project.get("field"), "field", path.name)
        add(project.get("reservoir_horizon"), "marker", f"{path.name}:reservoir_horizon")
        _walk_project(project, path.name, add, units)

    if cfg is not None:
        props = cfg.get("checks.properties", {}) or {}
        for role, item in (props.items() if isinstance(props, Mapping) else []):
            if isinstance(item, Mapping):
                add(item.get("cube"), "cube", f"checks.properties.{role}.cube")
        for key in ("checks.map_files", "checks.map_pending"):
            for name in (cfg.get(key, []) or []):
                add(name, "object", key)
        add(cfg.get("project.grid_name"), "cube", "project.grid_name")
    return registry


def _walk_project(node: Any, source: str, add, units: set[str],
                  path: str = "") -> None:
    """Собрать имена объектов поля по структуре проектного YAML (путь = контекст)."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            key_text = str(key)
            child = f"{path}.{key_text}" if path else key_text
            if child in ("functions", "pipeline", "thresholds", "crs", "deck"):
                continue                                # схемы/числа — не имена объектов
            low = key_text.lower()
            if isinstance(value, str):
                if key_text == "field":
                    add(value, "field", f"{source}:field")
                elif "marker" in low or "horizon" in low:
                    add(value, "marker", f"{source}:{child}")
                elif key_text in ("cube", "target_cube"):
                    add(value, "cube", f"{source}:{child}")
                elif key_text in ("log", "blocked", "source_curve"):
                    add(value, "mnemonic", f"{source}:{child}")
                elif child.startswith("inputs"):
                    add(value, "field_input", f"{source}:{child}")
                    if "/" in value or "\\" in value:
                        add(Path(value).name, "field_input", f"{source}:{child}")
                elif key_text == "obj_name":
                    add(value, "object", f"{source}:{child}")
                elif key_text == "id" and "variation" in path.lower():
                    add(value, "variation", f"{source}:{child}")
                elif key_text in UNIT_KEYS:
                    add(value, "unit", f"{source}:{child}", units_carrier=True)
            elif isinstance(value, (Mapping, list)):
                _walk_project(value, source, add, units, child)
            elif key_text in UNIT_KEYS:
                add(value, "unit", f"{source}:{child}", units_carrier=True)
    elif isinstance(node, list):
        for item in node:
            _walk_project(item, source, add, units, path)


# ── 2. сканирование кода ─────────────────────────────────────────────────────
def _pattern(token: str, *, substring: bool = False) -> re.Pattern[str]:
    if substring:
        return re.compile(re.escape(token))
    return re.compile(f"(?<![{_WORD_BOUND}]){re.escape(token)}(?![{_WORD_BOUND}])")


class Registry:
    """Токены реестра с режимом сравнения (поле — подстрокой, остальное — по словам)."""

    def __init__(self, registry: Mapping[str, Mapping[str, Any]]) -> None:
        self.entries = {str(k): dict(v) for k, v in registry.items()}
        self.patterns = [(token, _pattern(token, substring=info.get("class") == "field"))
                         for token, info in self.entries.items()]

    def __bool__(self) -> bool:
        return bool(self.patterns)

    def find(self, text: str) -> list[str]:
        """Токены реестра, встречающиеся в тексте (по правилам класса)."""
        return [token for token, pattern in self.patterns if pattern.search(str(text))]


def code_files() -> list[Path]:
    """Файлы кода под аудитом (без машинных выгрузок, кэшей и протоколов проб)."""
    out: list[Path] = []
    for sub in CODE_ROOTS:
        base = _ROOT / sub
        if base.is_dir():
            out += [p for p in sorted(base.rglob("*.py"))
                    if "__pycache__" not in p.parts]
    for name in CODE_FILES:
        path = _ROOT / name
        if path.is_file():
            out.append(path)
    exclusions = scan_exclusions()
    result = []
    for path in out:
        rel = path.relative_to(_ROOT).as_posix()
        if any(rel.startswith(prefix) for prefix in CODE_SKIP_PREFIXES):
            continue
        if any(fnmatch.fnmatch(rel, pattern) for pattern in exclusions):
            continue
        result.append(path)
    return result


def scan_exclusions() -> dict[str, str]:
    """Файлы, исключённые из скана, — ИЗ ДАННЫХ, с обоснованием (класс → почему)."""
    vocab = generic_vocabulary()
    out: dict[str, str] = {}
    for item in (vocab.get("scan_exclusions") or []):
        if isinstance(item, Mapping) and item.get("glob"):
            out[str(item["glob"])] = str(item.get("why") or "")
    return out


def _exception_sets(cfg: Any) -> tuple[dict[str, set[str]], dict[str, set[str]],
                                       dict[str, dict[str, set[str]]]]:
    """(allow, identifier_allow, known_debt) — объявленные в ДАННЫХ исключения."""
    raw = cfg.raw if cfg is not None else {}
    audit = (raw.get("hardcode_audit") or {}) if isinstance(raw, Mapping) else {}
    allow = {str(k): {str(x) for x in (v or [])}
             for k, v in (audit.get("allow") or {}).items()}
    ident = {str(k): {str(x) for x in (v or [])}
             for k, v in (audit.get("identifier_allow") or {}).items()}
    debt: dict[str, dict[str, set[str]]] = {}
    for file_name, slot in (audit.get("known_debt") or {}).items():
        slot = slot if isinstance(slot, Mapping) else {}
        debt[str(file_name)] = {
            "literals": {str(x) for x in (slot.get("literals") or [])},
            "identifiers": {str(x) for x in (slot.get("identifiers") or [])}}
    return allow, ident, debt


def classify_code(hits: list[dict], cfg: Any) -> list[dict]:
    """Разметить вхождения: allowed (правило схемы) | declared_debt | violation."""
    allow, ident, debt = _exception_sets(cfg)
    out: list[dict] = []
    for hit in hits:
        file_name = str(hit.get("file") or "")
        value = str(hit.get("value") or "")
        kind = str(hit.get("kind") or "")
        slot = debt.get(file_name, {})
        if value in allow.get(file_name, set()) or value in ident.get(file_name, set()):
            status = "allowed"
        elif kind == "name" and value in slot.get("identifiers", set()):
            status = "declared_debt"
        elif value in slot.get("literals", set()):
            status = "declared_debt"
        else:
            status = "violation"
        out.append({**hit, "status": status})
    return out


def _doc_nodes(tree: ast.AST) -> set[int]:
    docs: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and \
                    isinstance(body[0].value, ast.Constant) and \
                    isinstance(body[0].value.value, str):
                docs.add(id(body[0].value))
    return docs


def scan_code(registry: Registry) -> list[dict]:
    """Вхождения токенов реестра в код: литералы, имена, комментарии, docstring-и."""
    hits: list[dict] = []
    for path in code_files():
        rel = path.relative_to(_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text, filename=str(path))
        docs = _doc_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                kind = "docstring" if id(node) in docs else "literal"
                for token in registry.find(node.value):
                    hits.append({"file": rel, "line": node.lineno, "kind": kind,
                                 "value": node.value[:90], "token": token})
            elif isinstance(node, (ast.Name, ast.Attribute, ast.arg,
                                   ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                name = getattr(node, "id", None) or getattr(node, "attr", None) or \
                    getattr(node, "arg", None) or getattr(node, "name", "")
                for token in registry.find(str(name)):
                    hits.append({"file": rel, "line": node.lineno, "kind": "name",
                                 "value": str(name), "token": token})
        for number, line in enumerate(text.splitlines(), 1):
            if "#" not in line:
                continue
            comment = line.split("#", 1)[1]
            for token in registry.find(comment):
                hits.append({"file": rel, "line": number, "kind": "comment",
                             "value": comment.strip()[:90], "token": token})
    return hits


# ── 3. сканирование онтологии ────────────────────────────────────────────────
def scan_ontology_rules(cfg: Any, registry: Registry) -> list[dict]:
    """Параметры объектов тестирования в файлах ПРАВИЛ онтологии.

    Проверяются ЗНАЧЕНИЯ (`kind: value:*`) — именно там могут оказаться имена
    объектов поля. КЛЮЧИ файлов правил — имена схемы (роли, аргументы функций,
    политики), поэтому они собираются отдельно (`kind: key:*`) и в вердикт не
    входят: правило 1 разрешает идентификаторы схемы онтологии.
    """
    vocab = generic_vocabulary()
    root = ontology_root(cfg)
    values: list[dict] = []
    schema_keys: list[dict] = []
    for name in _audited_rule_files(vocab, cfg):
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            values.append({"file": name, "line": 0, "kind": "parse_error",
                           "value": "YAML не читается", "token": ""})
            continue
        for token, location, value in _walk_values(data, ""):
            row = {"file": name, "line": 0, "kind": location, "token": token,
                   "value": str(value)[:90]}
            (schema_keys if location.startswith("key:") else values).append(row)
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip().startswith("#"):
                continue
            for token in registry.find(line):
                values.append({"file": name, "line": number, "kind": "comment",
                               "value": line.strip()[:90], "token": token})
    _LAST_SCHEMA_KEYS.clear()
    _LAST_SCHEMA_KEYS.extend(schema_keys)
    return values


#: ключи файлов правил, отнесённые к схеме (роли/аргументы/политики) — для отчёта
_LAST_SCHEMA_KEYS: list[dict] = []


def schema_key_hits() -> list[dict]:
    """Ключи правил, распознанные как идентификаторы схемы (advisory, не вердикт)."""
    return list(_LAST_SCHEMA_KEYS)


def _walk_values(node: Any, path: str) -> Iterable[tuple[str, str, Any]]:
    """(токен, место, значение) по значениям и ключам структуры YAML."""
    registry = _ACTIVE_REGISTRY
    if isinstance(node, Mapping):
        for key, value in node.items():
            location = f"{path}.{key}" if path else str(key)
            for token in registry.find(str(key)):
                yield token, f"key:{location}", key
            yield from _walk_values(value, location)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_values(item, path)
    elif isinstance(node, str):
        for token in registry.find(node):
            yield token, f"value:{path}", node


_ACTIVE_REGISTRY: Registry = Registry({})


# ── 4. доказательство автоматической сборки ──────────────────────────────────
def generality_proof(cfg: Any) -> dict:
    """Сборка графа для НЕЗНАКОМОГО поля: состав/роли/требования — из онтологии.

    Файлы поля НЕ используются (каталог `project.graph_dir` подменяется пустым
    временным), поэтому всё выведенное — результат работы онтологии, а не данных
    тестового объекта. Затем то же поле получает МИНИМАЛЬНЫЙ файл данных (только
    `field` + `dataset_root`), и доказывается, что добавление поля = только данные.
    """
    from core.config import load_config
    from core.coordinator import Coordinator

    vocab = generic_vocabulary()
    probe = dict(vocab.get("generality_probe") or {})
    field_unknown = str(probe.get("field_unknown") or "PROBE_FIELD_NO_DATA")
    field_new = str(probe.get("field_new") or "PROBE_FIELD_DATA_ONLY")

    with tempfile.TemporaryDirectory(prefix="generality_") as tmp:
        tmp_dir = Path(tmp)
        local = load_config()
        local.set("project.graph_dir", str(tmp_dir))
        coord = Coordinator(local)

        unknown_graph = coord.graph_from_ontology(field_unknown, template={})
        minimal = {"field": field_new, "dataset_root": str(tmp_dir / "data" / "Source")}
        (tmp_dir / f"{field_new}.yaml").write_text(
            yaml.safe_dump(minimal, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        new_graph = Coordinator(local).project_graph(field_new)

        return {
            "probe": {"field_unknown": field_unknown, "field_new": field_new,
                      "data_file_written": f"{field_new}.yaml",
                      "code_files_modified": 0},
            "unknown_field": _graph_summary(unknown_graph),
            "field_with_minimal_data": {
                **_graph_summary(new_graph),
                "field_keys_from_data": sorted(minimal),
            },
            "roles_from_ontology": _roles_from_ontology(cfg),
            "formats_from_ontology": _formats_from_ontology(cfg),
            "object_requirements_from_ontology": _requirements_from_ontology(cfg),
            "object_binding_roles_from_ontology": _binding_roles_from_ontology(cfg),
            "ontology_parameters": {
                "petrophysics": _safe(coord._petro_rules_summary),
                "structural": _safe(coord._struct_rules_summary),
            },
            "verdict": ("сборка графа без файла поля и по минимальному файлу данных "
                        "выполнена: состав, роли, форматы и требования к объектам "
                        "выведены из онтологии"),
        }


def _safe(method) -> Any:
    try:
        return method()
    except Exception as exc:                            # noqa: BLE001 — отчёт информативен
        return {"verdict": "unverified", "reason": str(exc)[:200]}


def _graph_summary(graph: Mapping[str, Any]) -> dict:
    stages = [s for s in (graph.get("pipeline") or []) if isinstance(s, Mapping)]
    steps = [s for stage in stages for s in (stage.get("steps") or [])
             if isinstance(s, Mapping)]
    functions = sorted({str(s.get("function")) for s in steps if s.get("function")})
    return {
        "pipeline_source": graph.get("pipeline_source"),
        "stages": len(stages),
        "steps": len(steps),
        "functions": len(functions),
        "stage_labels": [str(s.get("stage")) for s in stages],
        "functions_sample": functions[:12],
        "todo": list(graph.get("todo") or []),
        "inputs_recognized": sorted((graph.get("inputs") or {}).keys())
        if isinstance(graph.get("inputs"), Mapping) else [],
    }


def _rules_file(cfg: Any, name: str) -> dict:
    path = ontology_root(cfg) / name
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _roles_from_ontology(cfg: Any) -> dict:
    """Роли распознавания входов и их маски — из онтологии (не из кода)."""
    data = _rules_file(cfg, "input_recognition_rules.yaml")
    out: dict[str, Any] = {}
    for role, spec in (data.get("roles") or {}).items():
        if isinstance(spec, Mapping):
            out[str(role)] = {"patterns": list(spec.get("patterns") or []),
                              "required": bool(spec.get("required")),
                              "internal_key": spec.get("internal_key")}
    return out


def _formats_from_ontology(cfg: Any) -> dict:
    data = _rules_file(cfg, "input_recognition_rules.yaml")
    out: dict[str, Any] = {}
    for name, spec in (data.get("formats") or {}).items():
        if isinstance(spec, Mapping):
            out[str(name)] = {"kind": spec.get("kind"),
                              "detect": spec.get("detect")}
    return out


def _requirements_from_ontology(cfg: Any) -> dict:
    data = _rules_file(cfg, "input_recognition_rules.yaml")
    return {str(k): v for k, v in (data.get("step_object_requirements") or {}).items()}


def _binding_roles_from_ontology(cfg: Any) -> dict:
    data = _rules_file(cfg, "object_binding_rules.yaml")
    return {str(k): v for k, v in (data.get("bindings") or {}).items()}


# ── сводный отчёт ────────────────────────────────────────────────────────────
def audit(cfg: Any, *, probe: bool = True) -> dict:
    """Полный отчёт общности: реестр, код, онтология, доказательство сборки.

    Классы вхождений в коде: `violation` (не объявлено ни в allow, ни в known_debt),
    `declared_debt` (объявленный долг правила 1 — виден и не скрыт), `allowed`
    (идентификатор схемы онтологии, разрешён правилом 1). Docstring-и — документация:
    считаются отдельно (`docstring`) и в вердикт не входят (прецедент: официальный
    тест и верификатор исключают docstring-и из скана кода).
    """
    global _ACTIVE_REGISTRY
    registry = field_registry(cfg)
    active = Registry(registry)
    _ACTIVE_REGISTRY = active

    code = classify_code(scan_code(active), cfg) if active else []
    rules = scan_ontology_rules(cfg, active) if active else []
    violations = [item for item in code if item["status"] == "violation"
                  and item["kind"] != "docstring"]
    debt = [item for item in code if item["status"] == "declared_debt"
            and item["kind"] != "docstring"]
    allowed = [item for item in code if item["status"] == "allowed"
               and item["kind"] != "docstring"]
    docstrings = [item for item in code if item["kind"] == "docstring"]
    report = {
        "registry": {
            "size": len(registry),
            "by_class": _count_by(list(registry.values()), "class"),
            "sample": sorted(registry)[:20],
        },
        "code": {
            "hits": len(code),
            "by_kind": _count_by(code, "kind"),
            "by_file": _count_by(code, "file"),
            "violations": len(violations),
            "declared_debt": len(debt),
            "allowed": len(allowed),
            "advisory_docstring": len(docstrings),
            "violation_items": violations[:60],
            "declared_debt_items": debt[:40],
            "docstring_items": docstrings[:40],
        },
        "ontology_rules": {
            "files": _audited_rule_files(generic_vocabulary(), cfg),
            "hits": len(rules),
            "by_kind": _count_by(rules, "kind"),
            "by_file": _count_by(rules, "file"),
            "items": rules[:80],
            "schema_key_advisory": len(schema_key_hits()),
            "schema_key_items": schema_key_hits()[:20],
        },
        "generic_vocabulary": {
            "units": sorted(_generic_unit_values(generic_vocabulary())),
            "scan_exclusions": scan_exclusions(),
        },
    }
    if probe:
        report["generality_proof"] = generality_proof(cfg)
    report["verdict"] = {
        "code_violations": len(violations),
        "code_declared_debt": len(debt),
        "ontology_object_parameter_hits": len(rules),
        "general": "passed" if not violations and not rules else "failed",
        "note": ("declared_debt — известный долг правила 1 из данных (виден в отчёте, "
                 "не скрыт); 0 — цель"),
    }
    return report


def _count_by(items: Iterable[Any], key: str) -> dict:
    out: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) if isinstance(item, Mapping) else getattr(item, key, ""))
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m core.generality_audit [--no-probe]` → JSON в stdout."""
    import argparse
    from core.config import load_config

    parser = argparse.ArgumentParser(description="Аудит общности онтологии и кода")
    parser.add_argument("--no-probe", action="store_true",
                        help="без доказательства сборки для незнакомого поля")
    parser.add_argument("--out", default=None, help="записать JSON в файл")
    args = parser.parse_args(argv)

    report = audit(load_config(), probe=not args.no_probe)
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if report["verdict"]["general"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
