"""Сценарная ось и ансамбль (пул моделей).

Неединственность ГГДМ: одну геологию описывают разные модели. Поэтому:
  * базовая модель = сценарий "base";
  * каждая реализация = дочерний сценарий (изолирован);
  * все ветки сохраняются (их пул и есть ансамбль);
  * ветки различаются ПО ОСЯМ и по РАЗНЫМ осям (round-robin), а не только
    по первой оси — иначе ансамбль вырождается в «почти одинаковые» ветви.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .ontology import RealizationAxis
from .system_model import Scenario, SystemModel


@dataclass
class EnsembleMember:
    scenario_id: str
    label: str
    kind: str
    parent: str | None
    parameters: dict = field(default_factory=dict)
    path: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    score: float | None = None

    def to_dict(self) -> dict:
        return {"scenario_id": self.scenario_id, "label": self.label, "kind": self.kind,
                "parent": self.parent, "score": self.score,
                "parameters": dict(self.parameters), "path": list(self.path),
                "metrics": dict(self.metrics)}

    @property
    def path_text(self) -> str:
        if not self.path:
            return "без вариаций"
        return "; ".join(
            f"{item['label']}: {item['parameter']} = {item['value']}{item.get('uom', '')}"
            for item in self.path)


def _base_parameters(axes: list[RealizationAxis]) -> dict:
    return {axis.parameter: axis.base for axis in axes}


def _variant_deltas(axes: list[RealizationAxis], count: int, *,
                    strategy: str = "combined") -> list[list[tuple]]:
    """Упорядоченный список вариаций.

    combined: сначала однофакторные «змейкой» по осям (по уровню на каждую ось —
    ветви различаются РАЗНЫМИ осями), затем двухфакторные комбинации.
    single_axis: однофакторные по порядку осей (как раньше).
    """
    variants: list[list[tuple]] = []
    if strategy == "single_axis":
        for axis in axes:
            for level in axis.levels:
                variants.append([(axis, level)])
        return variants[:count]

    max_levels = max((len(a.levels) for a in axes), default=0)
    for li in range(max_levels):                    # однофакторные, змейкой по осям
        for axis in axes:
            if li < len(axis.levels):
                variants.append([(axis, axis.levels[li])])
                if len(variants) >= count:
                    return variants
    for i, first in enumerate(axes):                # затем двухфакторные
        for level_a in first.levels:
            for second in axes[i + 1:]:
                for level_b in second.levels:
                    variants.append([(first, level_a), (second, level_b)])
                    if len(variants) >= count:
                        return variants
    return variants[:count]


def _make_member(scenario_id: str, base_id: str, base_label: str,
                 deltas: list[tuple], axes: list[RealizationAxis]) -> EnsembleMember:
    parameters = _base_parameters(axes)
    path: list[dict] = []
    for axis, value in deltas:
        parameters[axis.parameter] = value
        path.append({"axis": axis.id, "label": axis.label, "parameter": axis.parameter,
                     "base": axis.base, "value": value, "uom": axis.uom,
                     "realizes": axis.realizes})
    if not path:
        return EnsembleMember(scenario_id, base_label, "base", None, parameters, [])
    kind = "; ".join(axis.label for axis, _ in deltas)
    text = "; ".join(f"{axis.label}: {axis.parameter} = {value}{axis.uom}"
                     for axis, value in deltas)
    return EnsembleMember(scenario_id, f"{scenario_id} — {text}", kind, base_id,
                          parameters, path)


def build_ensemble(sm: SystemModel, size: int, *, axes: list[RealizationAxis] | None = None,
                   base_label: str = "", base_id: str = "", strategy: str = "combined"
                   ) -> list[EnsembleMember]:
    """Пул из `size` моделей: базовая + (size-1) вариаций по осям.

    Идентификатор и метка базовой ветки — ДАННЫЕ (`ensemble.default_variant` в
    config.yaml или вариации проектного графа): не заданы → пул пуст, и это честный
    «нет данных», а не ветка с придуманным именем (правило 1 и правило 6).
    Если осей нет — варьировать нечем, пул вырождается в одну базовую модель.
    """
    size = max(1, int(size))
    axes = list(axes or [])
    if not base_id:
        return []
    base_params = _base_parameters(axes)
    base = sm.add_scenario(Scenario(id=base_id, label=base_label, kind="base",
                                    parameters=base_params, path=[]))
    members = [EnsembleMember(base.id, base.label, base.kind, base.parent,
                              dict(base.parameters), [])]
    if size == 1 or not axes:
        return members
    for index, deltas in enumerate(
            _variant_deltas(axes, size - 1, strategy=strategy), start=2):
        sid = f"S{index:03d}"
        candidate = _make_member(sid, base.id, base_label, deltas, axes)
        scenario = sm.add_scenario(Scenario(
            id=candidate.scenario_id, label=candidate.label, kind="realization",
            parent=base.id, parameters=dict(candidate.parameters),
            path=list(candidate.path)))
        members.append(EnsembleMember(scenario.id, scenario.label, candidate.kind,
                                      base.id, dict(scenario.parameters),
                                      list(scenario.path)))
    return members
