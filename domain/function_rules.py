"""Чтение правил вычислительных функций тНава (`<function>.rdf`, N-Triples).

Каждый файл-правило описывает одну функцию:
    * `имеет_параметр`  → параметры (код, `тип_данных`, `возможное_значение`, `имеет_условие`);
    * `использует`      → входные объекты (`code` = роль, `тип_данных` = тип объекта);
    * `создает`         → выходные объекты;
    * `шаблон_кода`     → путь к сырому шаблону кода.

Свой минимальный N-Triples-ридер (без rdflib) — на файлах-правилах внешний парсер
падает; здесь нужны только пары subject/predicate/object.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from .workflow_model import FunctionRule, ObjectRef, ParameterSpec

NS = "https://example.org/tnav#"
P_HAS_PARAM = NS + "имеет_параметр"
P_POSSIBLE = NS + "возможное_значение"
P_TYPE = NS + "тип_данных"
P_CONDITION = NS + "имеет_условие"
P_TEMPLATE = NS + "шаблон_кода"
P_USES = NS + "использует"
P_CREATES = NS + "создает"
P_CODE = NS + "code"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"

# <subject> <predicate> <object|"literal"> .
_TRIPLE = re.compile(r"^\s*<([^>]*)>\s+<([^>]*)>\s+(.*?)\s*\.\s*$")
_ENTITY = re.compile(r"function-entity__([^_]+(?:[_][^_]+)*?)__(.+)$")


def _object_value(token: str) -> str:
    token = token.strip()
    if token.startswith("<") and token.endswith(">"):
        return token[1:-1]
    m = re.match(r'^"(.*)"(?:\^\^.*|@\w+)?$', token)
    return m.group(1) if m else token


def parse_ntriples(text: str) -> dict[str, dict[str, list[str]]]:
    """subject -> predicate -> [objects]."""
    store: dict[str, dict[str, list[str]]] = {}
    for line in text.splitlines():
        m = _TRIPLE.match(line)
        if not m:
            continue
        subj, pred, obj = m.group(1), m.group(2), _object_value(m.group(3))
        store.setdefault(subj, {}).setdefault(pred, []).append(obj)
    return store


def _entity_code(entity_uri: str) -> tuple[str, str]:
    """Из URI сущности: (function_name, code). 'input_horizon(obj_name)'."""
    local = unquote(entity_uri.split("#", 1)[-1])
    m = re.match(r"function-entity__([^_]+(?:_[^_]+)*?)__(.+)$", local)
    if not m:
        return "", local
    return m.group(1), m.group(2)


class FunctionRuleReader:
    """Читает <function>.rdf и собирает FunctionRule."""

    def __init__(self, rules_dir: Path) -> None:
        self.rules_dir = Path(rules_dir)
        self._cache: dict[str, FunctionRule] = {}

    def _path(self, name: str) -> Path | None:
        for cand in (self.rules_dir / f"{name}.rdf", self.rules_dir / f"{name}.ttl"):
            if cand.is_file():
                return cand
        return None

    def read(self, name: str) -> FunctionRule | None:
        if name in self._cache:
            return self._cache[name]
        path = self._path(name)
        if path is None:
            return None
        store = parse_ntriples(path.read_text(encoding="utf-8", errors="replace"))
        func_uri = NS + "computational-function__" + name
        node = store.get(func_uri, {})
        template = (node.get(P_TEMPLATE) or [""])[0]
        code = (node.get(P_CODE) or [name])[0]

        params: list[ParameterSpec] = []
        for p_uri in node.get(P_HAS_PARAM, []):
            params.append(self._param(store, p_uri))

        uses = tuple(self._object(store, u) for u in node.get(P_USES, []))
        creates = tuple(self._object(store, c) for c in node.get(P_CREATES, []))
        rule = FunctionRule(
            name=name, template_path=Path(template) if template else Path(f"{name}.txt"),
            parameters=tuple(params), creates=creates, uses=uses, code=code)
        self._cache[name] = rule
        return rule

    @staticmethod
    def _param(store: dict, p_uri: str) -> ParameterSpec:
        node = store.get(p_uri, {})
        _fn, code = _entity_code(p_uri)
        domain = tuple(store.get(v, {}).get(P_CODE, [v.rsplit("#", 1)[-1]])[0]
                       for v in node.get(P_POSSIBLE, []))
        conditions = tuple(store.get(c, {}).get(P_CODE, [unquote(c.rsplit("#", 1)[-1])])[0]
                           for c in node.get(P_CONDITION, []))
        label = (node.get(RDFS_LABEL) or [code])[0]
        return ParameterSpec(
            code=code, type=(node.get(P_TYPE) or ["string"])[0],
            domain=domain, condition=conditions, label=label)

    @staticmethod
    def _object(store: dict, o_uri: str) -> ObjectRef:
        node = store.get(o_uri, {})
        _fn, role = _entity_code(o_uri)
        obj_type = (node.get(P_TYPE) or [""])[0]
        return ObjectRef(obj_name=role, obj_type=obj_type)

    def all_names(self) -> list[str]:
        """Имена функций, для которых есть правила в каталоге (данные)."""
        names = []
        for p in sorted(self.rules_dir.glob("*.rdf")):
            if p.stem == "ontology":
                continue
            names.append(p.stem)
        return names
