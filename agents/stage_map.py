"""Сопоставление этапов пайплайна агентам и гейтам.

Источники (по приоритету):
  1) поля `agent:` / `gate:` на этапе проектного YAML — точечное переопределение;
  2) секция `gates:` config.yaml (список гейтов со `stages: [номера этапов]`);
  3) ``FALLBACK_GATES`` в :mod:`agents.gates` — стандартная цепочка 0–9.

:func:`assignments` возвращает назначения и список проблем (issues): этап без
агента, агент вне BDI-профилей и т.п. Проблемы не прерывают сборку — попадают
в план/отчёт; гейт-движок решает, что делать при исполнении.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from agents.gates import GateSpec, load_gate_specs
from agents.registry import AgentRegistry

_NUM_RE = re.compile(r"^\s*(\d+)\s*[.)]")


def _stage_number(label: str, position: int) -> int:
    """Канонический номер этапа из ярлыка («7. Петрофизика» → 7); иначе позиция."""
    m = _NUM_RE.match(label or "")
    return int(m.group(1)) if m else position


@dataclass(frozen=True)
class StageAssignment:
    """Назначение этапа: кто владелец и какой гейт закрывает передачу."""

    index: int           # позиция в pipeline (порядок исполнения)
    stage_no: int        # канонический номер этапа (ярлык «N. …»); = index, если без номера
    stage_key: str
    agent_id: str
    gate_id: str
    source: str          # yaml (переопределение) | config (gates:)


def assignments(project_graph: dict | None, cfg=None,
                registry: AgentRegistry | None = None
                ) -> tuple[list[StageAssignment], list[str]]:
    """Собрать назначения этапов и проблемы (issues) для плана/отчёта."""
    specs = load_gate_specs(cfg)
    by_index: dict[int, GateSpec] = {}
    for spec in specs:
        for idx in spec.stages:
            by_index.setdefault(idx, spec)
    stages = list((project_graph or {}).get("pipeline") or [])
    out: list[StageAssignment] = []
    issues: list[str] = []
    for idx, stage in enumerate(stages):
        stage = stage if isinstance(stage, dict) else {}
        label = str(stage.get("stage", f"этап {idx}"))
        stage_no = _stage_number(label, idx)
        spec = by_index.get(stage_no)
        agent_id = str(stage.get("agent") or (spec.agent if spec else "") or "")
        gate_id = str(stage.get("gate") or (spec.id if spec else "") or "")
        source = "yaml" if (stage.get("agent") or stage.get("gate")) else "config"
        if not agent_id:
            issues.append(f"этап {idx} «{label}»: агент не назначен "
                          f"(нет gates[{stage_no}] и agent: в YAML)")
        elif registry is not None and registry.available and registry.profile(agent_id) is None:
            issues.append(f"этап {idx}: агент {agent_id} отсутствует в BDI-профилях")
        out.append(StageAssignment(index=idx, stage_no=stage_no, stage_key=label,
                                   agent_id=agent_id, gate_id=gate_id, source=source))
    return out, issues


def agent_for_stage(project_graph: dict | None, cfg=None, stage_no: int = 0,
                    registry: AgentRegistry | None = None) -> StageAssignment | None:
    """Назначение этапа по КАНОНИЧЕСКОМУ номеру (из ярлыка «N. …»)."""
    found, _ = assignments(project_graph, cfg, registry)
    return next((a for a in found if a.stage_no == stage_no), None)
