"""Слой ЗНАЧЕНИЙ: системная модель.

Значение адресуется тремя координатами: объект × сценарий × момент.
Сценарная ось хранит веер гипотез/реализаций (ансамбль). Провенанс — PROV-O-lite.
Значения НЕ хранятся в онтологии. Всё сериализуется в JSON под папкой прогона.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Scenario:
    id: str
    label: str
    kind: str = "base"          # "base" | "hypothesis" | "realization"
    parent: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    path: list[dict] = field(default_factory=list)


@dataclass
class ValueRecord:
    object_id: str
    scenario_id: str
    moment: str
    value: Any
    uom: str = ""
    generated_by: str = ""
    used: list[str] = field(default_factory=list)
    attributed_to: str = ""


class SystemModel:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.scenarios: dict[str, Scenario] = {}
        self.values: list[ValueRecord] = []

    def add_scenario(self, scenario: Scenario) -> Scenario:
        self.scenarios[scenario.id] = scenario
        return scenario

    def children(self, scenario_id: str) -> list[Scenario]:
        return [s for s in self.scenarios.values() if s.parent == scenario_id]

    def add_value(self, record: ValueRecord) -> ValueRecord:
        if record.scenario_id not in self.scenarios:
            raise KeyError(f"Неизвестный сценарий: {record.scenario_id}")
        self.values.append(record)
        return record

    def values_for(self, object_id: str, scenario_id: str | None = None) -> list[ValueRecord]:
        return [v for v in self.values
                if v.object_id == object_id
                and (scenario_id is None or v.scenario_id == scenario_id)]

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "scenarios": [asdict(s) for s in self.scenarios.values()],
            "values": [asdict(v) for v in self.values],
        }

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path

    @staticmethod
    def from_dict(data: dict) -> "SystemModel":
        sm = SystemModel(data.get("run_id", ""))
        for s in data.get("scenarios", []):
            sm.add_scenario(Scenario(**s))
        for v in data.get("values", []):
            sm.add_value(ValueRecord(**v))
        return sm
