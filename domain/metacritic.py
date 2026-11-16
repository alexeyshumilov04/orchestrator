"""C8 — МЕТАКРИТИК: QA/QC как ДАННЫЕ (правила из онтологии v4, не из кода).

Единый вердикт: passed | failed | unknown. `UNKNOWN` НЕ трактуется как `false`
(неизвестное правило/значение сохраняется в отчёте). Правила читаются из
`qaqc_rules.csv`; числовые границы берутся из `data_parameter_catalog.csv`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.ontology import ParamSpec, QaRule


class Verdict(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class CheckResult:
    rule_id: str
    verdict: Verdict
    note: str = ""

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "verdict": self.verdict.value, "note": self.note}


@dataclass
class CriticReport:
    verdict: Verdict = Verdict.UNKNOWN
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def counts(self) -> dict:
        out = {"passed": 0, "failed": 0, "unknown": 0}
        for c in self.checks:
            out[c.verdict.value] += 1
        return out

    def to_dict(self) -> dict:
        return {"verdict": self.verdict.value, "counts": self.counts,
                "checks": [c.to_dict() for c in self.checks]}


def _ranges(spec: ParamSpec) -> tuple[float, float] | None:
    """Разобрать typical_range вида '1e2..1e7' или '0.15-0.35' -> (lo, hi)."""
    text = (spec.typical_range or "").replace(" ", "")
    for sep in ("..", "-", "…"):
        if sep in text:
            lo_s, _, hi_s = text.partition(sep)
            try:
                return float(lo_s), float(hi_s)
            except ValueError:
                return None
    return None


class MetaCritic:
    """Прогоняет правила QA/QC по артефактам ветви. Единый вердикт + UNKNOWN."""

    def __init__(self, rules: list[QaRule], params: list[ParamSpec] | None = None) -> None:
        self.rules = list(rules)
        self.params = {p.code: p for p in (params or [])}

    def evaluate(self, artifacts: dict) -> CriticReport:
        """artifacts — словарь выходов узлов: {code: value} (напр. PORO, PERMX, GRID...)."""
        report = CriticReport()
        # 1) диапазонная проверка по каталогу параметров (executable, данные)
        for code, value in (artifacts or {}).items():
            spec = self.params.get(code)
            if spec is None or not isinstance(value, (int, float)):
                continue
            rng = _ranges(spec)
            if rng is None:
                continue
            lo, hi = rng
            ok = lo <= float(value) <= hi
            report.checks.append(CheckResult(
                rule_id=f"range:{code}", verdict=Verdict.PASSED if ok else Verdict.FAILED,
                note=f"{value} in [{lo}, {hi}] ({spec.unit})"))
        # 2) правила из qaqc_rules.csv: формализованные — как проверки, иначе UNKNOWN
        for rule in self.rules:
            if rule.formalized:
                report.checks.append(CheckResult(
                    rule_id=rule.id, verdict=Verdict.UNKNOWN,
                    note=f"правило формализовано, но нет привязки к артефакту: {rule.condition[:80]}"))
            else:
                report.checks.append(CheckResult(
                    rule_id=rule.id, verdict=Verdict.UNKNOWN,
                    note="правило не формализовано (сохранён UNKNOWN)"))
        report.verdict = self._verdict(report.checks)
        return report

    @staticmethod
    def _verdict(checks: list[CheckResult]) -> Verdict:
        if any(c.verdict is Verdict.FAILED for c in checks):
            return Verdict.FAILED
        if checks and all(c.verdict is Verdict.PASSED for c in checks):
            return Verdict.PASSED
        return Verdict.UNKNOWN
