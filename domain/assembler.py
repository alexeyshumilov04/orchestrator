"""Сборка генов воркфлоу из ОНТОЛОГИИ групп операций (`ontology.rdf`, GA-набор).

Онтология задаёт упорядоченную цепочку групп операций (`hasNextStep`) и их вызовы
функций (`usesOperation` → `invokesFunction` → `computational-function`). Оркестратор
превращает это в `list[NodeGene]` — по одному узлу на группу. Имена объектов и значения
параметров берутся из ПРОЕКТНОГО графа (данные), а не из кода; остальное — дефолты
шаблонов тНава.
"""
from __future__ import annotations

from pathlib import Path

from .function_rules import NS, parse_ntriples
from .workflow_model import FunctionGene, NodeGene, ObjectRef

P_HAS_STEP = NS + "hasStep"
P_NEXT = NS + "hasNextStep"
P_USES_OP = NS + "usesOperation"
P_INVOKES = NS + "invokesFunction"
P_CODE = NS + "code"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"

_GROUP = "operation-group__"
_INVOC = "function-invocation__"
_FUNC = "computational-function__"


def _local(uri: str) -> str:
    return uri.split("#", 1)[-1]


class WorkflowAssembler:
    """Онтология групп операций → NodeGene[] (гены воркфлоу)."""

    def __init__(self, ontology_rdf: Path, project: dict | None = None,
                 data_root: Path | None = None, stage_dir: Path | None = None) -> None:
        self.ontology_rdf = Path(ontology_rdf)
        self.project = project or {}
        self.data_root = Path(data_root) if data_root else None
        self.stage_dir = Path(stage_dir) if stage_dir else None
        self._store: dict | None = None

    def _expand_glob(self, pattern: str) -> list[str]:
        """Развернуть glob-паттерн: сначала `data_root`, затем папка проекта (`stage_dir`).

        Часть файлов создаётся ПОДГОТОВКОЙ ДАННЫХ прямо в папке проекта тНава
        (напр. `Wells/*.txt` — таблицы траекторий), поэтому ищем в обоих корнях.
        """
        for root in (self.data_root, self.stage_dir):
            if root is None or not root.exists():
                continue
            hits = sorted(root.glob(pattern))
            if hits:
                return [str(p.relative_to(root)).replace("\\", "/") for p in hits]
        return []

    @property
    def store(self) -> dict:
        if self._store is None:
            text = self.ontology_rdf.read_text(encoding="utf-8", errors="replace")
            self._store = parse_ntriples(text)
        return self._store

    # -- функции вызова -----------------------------------------------------
    def _invocation_function(self, inv_uri: str) -> tuple[str, str]:
        """(function_name, inv_label) для function-invocation__X."""
        node = self.store.get(inv_uri, {})
        for target in node.get(P_INVOKES, []):
            if _FUNC in target:
                fn = _local(target).split(_FUNC, 1)[-1]
                return fn, fn
        return _local(inv_uri).split(_INVOC, 1)[-1], ""

    def groups(self) -> list[dict]:
        """Упорядоченный список групп: [{code, functions:[name,...]}]."""
        groups: dict[str, dict] = {}
        nxt: dict[str, str] = {}
        for subj, preds in self.store.items():
            if _GROUP not in subj:
                continue
            groups.setdefault(subj, {"functions": []})["label"] = (
                (preds.get(RDFS_LABEL) or preds.get(P_CODE) or [_local(subj)])[0])
            for target in preds.get(P_NEXT, []):
                nxt[subj] = target
            for inv in preds.get(P_USES_OP, []):
                name, _ = self._invocation_function(inv)
                groups[subj]["functions"].append(name)

        targets = set(nxt.values())
        starts = [g for g in groups if g not in targets]
        ordered: list[dict] = []
        seen: set[str] = set()
        cur = starts[0] if starts else (next(iter(groups), None))
        while cur and cur not in seen:
            seen.add(cur)
            if cur not in groups:                 # step__start/step__end — не группа
                cur = nxt.get(cur)
                continue
            label = groups[cur].get("label", _local(cur))
            ordered.append({"code": _local(cur).split(_GROUP, 1)[-1],
                            "label": label, "functions": groups[cur]["functions"]})
            cur = nxt.get(cur)
        # группы вне цепочки — в конец (не теряем)
        for g, info in groups.items():
            if g not in seen:
                ordered.append({"code": _local(g).split(_GROUP, 1)[-1],
                                "label": info.get("label", _local(g)),
                                "functions": info["functions"]})
        return ordered

    # -- гены ---------------------------------------------------------------
    def node_genes(self) -> list[NodeGene]:
        """Гены воркфлоу: из ПРОЕКТНОГО пайплайна (если задан), иначе из ontology.rdf."""
        if self.project.get("pipeline"):
            return self._pipeline_genes()
        return self._ontology_genes()

    def _pipeline_genes(self) -> list[NodeGene]:
        """Полный пайплайн ГМ задан ДАННЫМИ в проекте: этапы → шаги (функция + объект)."""
        overrides = self.project.get("functions", {}) or {}
        nodes: list[NodeGene] = []
        for si, stage in enumerate(self.project.get("pipeline") or [], start=1):
            label = stage.get("stage", f"этап {si}")
            node = NodeGene(group=label, iteration=si, method=label, stage=label)
            for step in stage.get("steps", []) or []:
                fn = step.get("function", "")
                if not fn:
                    continue
                ov = overrides.get(fn, {}) or {}
                params = dict(ov.get("parameters") or {})
                params.update(step.get("parameters") or {})
                objs = dict(ov.get("objects") or {})
                objs.update(step.get("objects") or {})     # пошаговые важнее глобальных
                lists = dict(ov.get("lists") or {})
                lists.update(step.get("lists") or {})
                for code, pat in (step.get("glob") or {}).items():
                    lists[code] = self._expand_glob(pat)   # списки файлов данных
                replace = dict(ov.get("replace") or {})
                replace.update(step.get("replace") or {})
                node.add(FunctionGene(
                    function=fn, parameters=params, lists=lists, replace=replace,
                    objects={r: ObjectRef(**s) for r, s in objs.items()}))
            if node.functions:
                nodes.append(node)
        return nodes

    def _ontology_genes(self) -> list[NodeGene]:
        nodes: list[NodeGene] = []
        overrides = self.project.get("functions", {}) or {}
        for i, group in enumerate(self.groups(), start=1):
            node = NodeGene(group=group["code"], iteration=i, method=group["label"],
                            stage=group["label"])
            for fn in group["functions"]:
                ov = overrides.get(fn, {}) or {}
                params = dict(ov.get("parameters", {}) or {})
                objs = {role: ObjectRef(**spec) for role, spec in
                        (ov.get("objects", {}) or {}).items()}
                node.add(FunctionGene(function=fn, parameters=params, objects=objs))
            if node.functions:
                nodes.append(node)
        return nodes

