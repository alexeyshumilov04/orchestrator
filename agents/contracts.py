"""Контракты агентного слоя: контекст, план, результат, вердикт, меморандум.

Поля :class:`HandoffMemo` повторяют обязательства `handoff_contracts.csv`
(artifact revisions; lineage; units/CRS; QA; assumptions; uncertainties;
evidence hash) и дополнены деградацией/байпассом: degraded, bypass_reason,
unresolved_findings, waiver.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# --- статусы гейта ------------------------------------------------------------
PASSED = "passed"
FAILED = "failed"               # исчерпание попыток в режиме halt (остановка)
BYPASSED = "bypassed"           # продолжение с лучшей ревизией (degraded)
SKIPPED = "skipped"             # пропуск этапа и зависимых шагов
WAIVED = "waived"               # ручное подтверждение оператором
PENDING = "pending_execution"   # dry-run: прогон не выполнялся
AWAITING = "awaiting_decision"  # режим ask: ожидается решение оператора
# Состояние НАХОДКИ (не вердикта): «результат не проверен — нет свидетельства».
# Гейт с такой находкой не может стать passed (правило 6: неизвестное ≠ зелёное),
# но и не «failed»: отсутствие данных не является провалом модели.
UNVERIFIED = "unverified"

# Уровни находок. `note` — ИНФОРМАЦИОННЫЙ: находка видна в отчёте, но гейт по ней
# не падает (валит только `critical`). Уровень проверки управляется данными
# (`checks.check_severity`), допустимы ровно эти четыре значения.
SEVERITIES = ("critical", "major", "minor", "note")
DEGRADING = (BYPASSED, SKIPPED, WAIVED)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    p = Path(path)
    if not p.is_file():
        return ""
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_verdict(statuses: list[str]) -> str:
    """Итоговый вердикт прогона по статусам гейтов."""
    if FAILED in statuses:
        return "halted"
    if AWAITING in statuses:
        return "awaiting_decision"
    if any(s in DEGRADING for s in statuses):
        return "passed_with_degradation"
    if PENDING in statuses:
        return "pending_execution"
    return "passed"


def severity_counts(findings: list["Finding"]) -> dict:
    """Счётчики находок по серьёзности: passed/failed.

    Находки в состоянии ``unverified`` («результат не проверен: нет свидетельства»)
    не считаются НИ пройденными, НИ проваленными — они идут отдельным списком в
    вердикте (``GateVerdict.unverified``): иначе отсутствие данных выглядело бы
    «зелёным» (правило 6).
    """
    out = {s: {"passed": 0, "failed": 0} for s in SEVERITIES}
    for f in findings or []:
        if getattr(f, "state", "") == UNVERIFIED:
            continue
        slot = out.setdefault(f.severity, {"passed": 0, "failed": 0})
        slot["passed" if f.passed else "failed"] += 1
    return out


def save_json(path: str | Path, payload) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = payload.to_dict() if hasattr(payload, "to_dict") else payload
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return p


def load_json(path: str | Path) -> dict:
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# --- модели --------------------------------------------------------------------
@dataclass
class Finding:
    """Результат одной проверки гейта."""

    id: str
    severity: str = "major"          # critical | major | minor
    passed: bool = True
    title: str = ""
    message: str = ""
    source: str = "builtin"          # builtin | package | range | contract | llm | csv
    remediation: str = ""
    evidence: dict = field(default_factory=dict)
    # "" — обычная находка (passed/failed); UNVERIFIED — «результат не проверен,
    # нет свидетельства»: гейт не может стать passed, но и не падает (правило 6).
    state: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StageContext:
    """Входные данные этапа (что агент получил на руки)."""

    field: str
    run_dir: str
    stage_key: str
    stage_label: str
    index: int
    gate_id: str
    agent_id: str
    attempt: int = 1
    project: dict = field(default_factory=dict)
    data_root: str = ""
    prior: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StagePlan:
    """План этапа: какие функции/параметры применяются и почему."""

    agent_id: str
    stage_key: str
    functions: list[str] = field(default_factory=list)
    parameters: dict = field(default_factory=dict)
    rationale: str = ""
    source: str = "deterministic"    # deterministic | llm
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateVerdict:
    """Вердикт гейта этапа (детерминированный; LLM его не отменяет)."""

    gate_id: str
    status: str = PENDING
    counts: dict = field(default_factory=dict)
    kq: float = 0.0
    kc: float = 0.0
    physical: bool | None = None     # None = физичность НЕ проверялась (нет метрик)
    findings: list[Finding] = field(default_factory=list)
    attempts: int = 0
    mode: str = ""
    decider: str = "auto"            # auto | operator
    comment: str = ""
    waiver: dict | None = None
    # Пороговые проверки kq/kc: что применено, а что пропущено и почему
    # (в dry-run метрики не посчитаны — порог НЕ применяется, «неизвестное ≠ ложь»).
    thresholds: dict = field(default_factory=dict)
    # Проверки, которые НЕ СМОГЛИ судить: нет свидетельства о результате (F-19).
    # Непустой список → гейт не может быть passed (переводится в pending_execution).
    unverified: list[str] = field(default_factory=list)
    ts: str = field(default_factory=utc_now)

    def failed_findings(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["failed"] = len(self.failed_findings())
        return data


@dataclass
class StageResult:
    """Результат исполнения этапа (артефакты + вердикт гейта)."""

    stage_key: str
    gate_id: str
    agent_id: str
    ok: bool = False
    attempts: int = 0
    artifacts: list[dict] = field(default_factory=list)   # [{path, sha256}]
    objects: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    verdict: GateVerdict | None = None
    started: str = field(default_factory=utc_now)
    finished: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HandoffMemo:
    """Меморандум передачи ответственности следующему агенту.

    Выдаётся только при статусах passed/bypassed/waived; при skipped —
    фиксируется пропуск с fallback-причинами. Несёт обязательства
    handoff-контракта: ревизии артефактов, линию происхождения, единицы/СК,
    QA-вердикт, допущения, неопределённости и хэш доказательств.
    """

    id: str
    handoff_id: str
    from_agent: str
    to_agent: str
    from_stage: str
    to_stage: str
    verdict: str
    degraded: bool = False
    bypass_reason: str = ""
    unresolved_findings: list[str] = field(default_factory=list)
    artifact_revisions: list[dict] = field(default_factory=list)
    lineage: list[str] = field(default_factory=list)
    units_crs: dict | None = None
    qa: dict = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    evidence_hash: str = ""
    waiver: dict | None = None
    ts: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path) -> Path:
        return save_json(path, self)
