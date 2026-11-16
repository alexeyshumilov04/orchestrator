"""Построение плана: от требований И от фактических данных.

Ключевое отличие от «шаблона по онтологии»: план зависит от набора данных.
Операция, для которой нет входных данных, помечается `needs_data` (и в режиме
`by_data` исключается из исполнительного плана). Операция без реализации в
домене помечается `unimplemented` и попадает в `declared` (видна, но не бежит).
"""
from __future__ import annotations

from typing import Iterable, Sequence

from .node_contract import NodeCapability, PlanStep, WorkflowPlan
from .ontology import OperationInfo


def _stage_order(stage: str, stage_orders: dict[str, int]) -> int:
    return stage_orders.get(stage, 999)


def build_workflow(operations: Sequence[OperationInfo], *,
                   capabilities: Iterable[NodeCapability],
                   available_kinds: Iterable[str],
                   stage_names: dict[str, str] | None = None,
                   stage_orders: dict[str, int] | None = None,
                   plan_mode: str = "by_data") -> WorkflowPlan:
    """Собрать план из реализуемых операций с фильтром по данным."""
    stage_names = stage_names or {}
    stage_orders = stage_orders or {}
    available = set(available_kinds)
    op_by_id = {op.id: op for op in operations}
    caps = list(capabilities)

    steps: list[PlanStep] = []
    skipped: list[dict] = []
    picked: list[tuple[NodeCapability, list[str], list[str]]] = []

    for cap in caps:
        missing = [k for k in cap.requires if k not in available]
        optional = list(getattr(cap, "optional", ()) or ())
        optional_missing = [k for k in optional if k not in available]
        if missing:
            if plan_mode == "by_data":
                skipped.append({
                    "op_id": cap.op_id, "label": cap.label, "stage": cap.stage,
                    "status": "needs_data", "missing": missing,
                    "optional_missing": optional_missing})
                continue
            picked.append((cap, missing, optional_missing))
        else:
            picked.append((cap, [], optional_missing))

    picked.sort(key=lambda t: (_stage_order(t[0].stage, stage_orders),
                               t[0].order, t[0].op_id))

    for i, (cap, missing, optional_missing) in enumerate(picked):
        steps.append(PlanStep(
            order=i, op_id=cap.op_id, label=cap.label, stage=cap.stage,
            stage_name=stage_names.get(cap.stage, cap.stage.split(":")[-1]),
            stage_order=_stage_order(cap.stage, stage_orders), engine=cap.engine,
            requires=tuple(cap.requires), optional=tuple(getattr(cap, "optional", ()) or ()),
            needs=tuple(cap.needs), produces=tuple(cap.produces),
            status="needs_data" if missing else "ready", missing=tuple(missing),
            optional_missing=tuple(optional_missing)))

    # объявленные, но не реализованные операции онтологии
    declared: list[dict] = []
    cap_ids = {c.op_id for c in caps}
    for op in operations:
        if op.id not in cap_ids:
            declared.append({
                "op_id": op.id, "label": op.label, "stage": op.stage,
                "stage_name": stage_names.get(op.stage, op.stage.split(":")[-1]),
                "stage_order": _stage_order(op.stage, stage_orders),
                "status": "unimplemented", "engine": op.engine})

    # рёбра: A -> B, если B требует артефакт (needs), который производит A
    edges: list[tuple[str, str]] = []
    for step in steps:
        for other in steps:
            if other is step:
                continue
            if set(other.produces) & set(step.needs):
                edges.append((other.op_id, step.op_id))
                step.depends_on.append(other.op_id)
    for step in steps:
        step.depends_on = sorted(set(step.depends_on))

    stages_used: list[str] = []
    for step in steps:
        if step.stage not in stages_used:
            stages_used.append(step.stage)

    return WorkflowPlan(steps=steps, declared=declared, skipped=skipped, edges=edges,
                        stages_used=stages_used, plan_mode=plan_mode,
                        available_kinds=tuple(sorted(available)))
