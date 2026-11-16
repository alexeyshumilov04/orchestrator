"""Контракт узла: что узел требует (входные данные), что производит и чем исполняется.

Capability заполняется доменом (`domain/`), ядро лишь использует метаданные.
Так домен подключается регистрацией и не проникает в `core/`.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NodeCapability:
    """Реализуемая операция: движок, требуемые типы данных, выходные артефакты."""

    op_id: str
    label: str
    stage: str
    engine: str = "python"
    order: int = 0
    requires: tuple = ()          # требуемые ТИПЫ ДАННЫХ набора (core.datasets.DATA_KINDS)
    optional: tuple = ()          # желательные ТИПЫ ДАННЫХ (не блокируют узел)
    needs: tuple = ()             # АРТЕФАКТЫ от других узлов (для рёбер/зависимостей)
    produces: tuple = ()          # имена артефактов на выходе
    descr: str = ""


@dataclass
class PlanStep:
    order: int
    op_id: str
    label: str
    stage: str
    stage_name: str
    stage_order: int
    engine: str
    requires: tuple = ()
    optional: tuple = ()
    needs: tuple = ()
    produces: tuple = ()
    status: str = "ready"          # ready | needs_data | unimplemented
    missing: tuple = ()
    optional_missing: tuple = ()   # желательные типы, которых нет в наборе (не блокирует)
    depends_on: list[str] = field(default_factory=list)
    iterative_group: int | None = None

    def to_dict(self) -> dict:
        return {
            "order": self.order, "op_id": self.op_id, "label": self.label,
            "stage": self.stage, "stage_name": self.stage_name,
            "stage_order": self.stage_order, "engine": self.engine,
            "requires": list(self.requires), "optional": list(self.optional),
            "needs": list(self.needs),
            "produces": list(self.produces),
            "status": self.status, "missing": list(self.missing),
            "optional_missing": list(self.optional_missing),
            "depends_on": list(self.depends_on),
            "iterative_group": self.iterative_group,
        }


@dataclass
class WorkflowPlan:
    steps: list[PlanStep]
    declared: list[dict]          # операции онтологии без реализации (unimplemented)
    skipped: list[dict]           # реализуемые операции без входных данных (needs_data)
    edges: list[tuple[str, str]]
    stages_used: list[str]
    plan_mode: str = "by_data"
    available_kinds: tuple = ()

    def to_dict(self) -> dict:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "declared": [dict(d) for d in self.declared],
            "skipped": [dict(s) for s in self.skipped],
            "edges": [list(e) for e in self.edges],
            "stages_used": self.stages_used,
            "steps_total": len(self.steps),
            "declared_total": len(self.declared),
            "skipped_total": len(self.skipped),
            "plan_mode": self.plan_mode,
            "available_kinds": list(self.available_kinds),
        }
