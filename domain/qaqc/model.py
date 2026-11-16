"""Core data model: dataclasses and the data container for the QAQC framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict


@dataclass(frozen=True)
class Threshold:
    op: str = "le"                 # le, lt, ge, gt, eq, ne, between, bool_true, bool_false
    value: Optional[float] = None
    lo: Optional[float] = None
    hi: Optional[float] = None
    unit: str = ""
    is_percent: bool = False
    raw: str = ""

    def describe(self) -> str:
        if self.op == "between":
            return (f"in [{self.lo}, {self.hi}] {self.unit}").strip()
        if self.op in ("bool_true", "bool_false"):
            return self.raw or self.op
        sym = {"le": "<=", "lt": "<", "ge": ">=", "gt": ">", "eq": "==", "ne": "!="}[self.op]
        v = self.value
        if self.is_percent:
            return f"{sym} {round(v * 100, 3)}%"
        return (f"{sym} {v} {self.unit}").strip()


@dataclass
class MetricSpec:
    kind: str = "direct"            # primitive name, 'direct', or 'bool'
    inputs: List[str] = field(default_factory=list)
    log_inputs: List[str] = field(default_factory=list)
    agg: str = "identity"           # identity, mean, max, min, std, abs_max, abs_mean, fraction, count
    params: Dict[str, float] = field(default_factory=dict)
    threshold: Optional[Threshold] = None
    note: str = ""


@dataclass
class Check:
    id: str
    number: int
    block: str
    group: str
    name: str
    comment: str
    formula: str
    criterion: str
    significance: float
    error_source: str
    status: str
    complexity: str
    expert_comment: str
    fitness_function: str
    fitness_component: str
    flag_justification: str
    metrics: List[MetricSpec] = field(default_factory=list)
    parameters_used: List[str] = field(default_factory=list)


@dataclass
class Parameter:
    mnemonic: str
    description: str
    unit: str
    source: str
    synonyms: str
    check_count: str
    where_used: str
    note: str


@dataclass
class MetricValue:
    key: str
    value: Optional[float]
    passed: bool
    threshold: Optional[Threshold]
    message: str = ""


@dataclass
class CheckResult:
    check_id: str
    name: str
    passed: bool
    values: List[MetricValue] = field(default_factory=list)
    message: str = ""
    check: Optional[Check] = None

    def __bool__(self) -> bool:
        return self.passed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "metrics": [
                {
                    "key": v.key,
                    "value": v.value,
                    "passed": v.passed,
                    "threshold": v.threshold.describe() if v.threshold else None,
                    "message": v.message,
                }
                for v in self.values
            ],
        }

    def __repr__(self) -> str:
        return f"<CheckResult {self.check_id} passed={self.passed}>"


class DataContext(dict):
    """Dictionary-like container holding everything a check needs at runtime.

    Example:
        data = DataContext(PHI=phie_array, PERM=perm_array)
        data["KRG"] = krg_array
        data.require("PHI", "PERM")
    """

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def get(self, key: str, default: Any = None) -> Any:
        return dict.get(self, key, default)

    def require(self, *keys: str) -> List[Any]:
        missing = [k for k in keys if k not in self]
        if missing:
            raise KeyError(f"Missing required data keys: {missing}")
        return [self[k] for k in keys]

    def add(self, **kwargs) -> "DataContext":
        self.update(kwargs)
        return self