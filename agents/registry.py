"""Реестр агентов и handoff-контрактов: BDI-онтология v4.1 — ДАННЫЕ, не код.

Читает каталог BDI-знаний (путь — ключ `agents.bdi_dir` в config.yaml):
  * ``agent_profiles.csv``        — 22 профиля агентов (роли, стадии S01–S18, автономия);
  * ``handoff_contracts.csv``     — 17 контрактов передачи (S01→S02 … S17→S18);
  * ``decision_tables_v4_1.csv``  — правила решений BDI (читаются лениво).

Без cfg/каталога реестр остаётся рабочим: `available == False`, пустые списки —
агенты и гейты продолжают работать в детерминированном режиме.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from core.config import Config

PROFILES_FILE = "agent_profiles.csv"
HANDOFFS_FILE = "handoff_contracts.csv"
DECISIONS_FILE = "decision_tables_v4_1.csv"

_TRUTHY = {"1", "true", "yes", "да"}


@dataclass(frozen=True)
class AgentProfile:
    """Профиль агента (строка `agent_profiles.csv`)."""

    id: str
    name: str
    group: str
    stages: tuple[str, ...]
    autonomy: str
    runtime: str
    scope: str
    symbolic_mode: str
    hybrid_mode: str
    generative_mode: str


@dataclass(frozen=True)
class HandoffContract:
    """Контракт передачи между агентами (строка `handoff_contracts.csv`)."""

    id: str
    from_stage: str
    from_agent: str
    to_stage: str
    to_agent: str
    gate: str
    required: tuple[str, ...]
    on_reject: str


@dataclass(frozen=True)
class DecisionRule:
    """Правило таблицы решений BDI v4.1 (подмножество колонок)."""

    knowledge_base: str
    branch_id: str
    rule_id: str
    priority: int
    guard: str
    outcome: str
    requires_human_approval: bool
    knowledge_status: str
    execution_eligibility: str


def _split_ids(value: str) -> tuple[str, ...]:
    """Разбить идентификаторы (стадии: "S01,S16,S18")."""
    if not value:
        return ()
    for sep in (";", "|", ","):
        value = value.replace(sep, " ")
    return tuple(tok for tok in value.split() if tok)


def _split_parts(value: str) -> tuple[str, ...]:
    """Разбить фразовый список ("artifact revisions; lineage; …") по ';'."""
    return tuple(p.strip() for p in (value or "").split(";") if p.strip())


def _read_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(fh)]


class AgentRegistry:
    """Единая точка чтения агентного знания (CSV → dataclasses, кэш в памяти)."""

    def __init__(self, cfg: Config | None = None, *, bdi_dir: Path | None = None) -> None:
        if bdi_dir is None and cfg is not None:
            value = cfg.get("agents.bdi_dir")
            bdi_dir = cfg.resolve(value) if value else None
        self.bdi_dir: Path | None = Path(bdi_dir) if bdi_dir else None
        self._profiles: list[AgentProfile] | None = None
        self._handoffs: list[HandoffContract] | None = None
        self._decisions: list[DecisionRule] | None = None

    @property
    def available(self) -> bool:
        return bool(self.bdi_dir) and (self.bdi_dir / PROFILES_FILE).is_file()

    def _rows(self, name: str) -> list[dict]:
        return _read_rows(self.bdi_dir / name) if self.bdi_dir else []

    # -- профили --------------------------------------------------------------
    def profiles(self) -> list[AgentProfile]:
        if self._profiles is None:
            self._profiles = [
                AgentProfile(
                    id=r.get("profile_id", ""),
                    name=r.get("agent", ""),
                    group=r.get("group", ""),
                    stages=_split_ids(r.get("stages", "")),
                    autonomy=r.get("default_autonomy", ""),
                    runtime=r.get("runtime", ""),
                    scope=r.get("scope", ""),
                    symbolic_mode=r.get("symbolic_mode", ""),
                    hybrid_mode=r.get("hybrid_mode", ""),
                    generative_mode=r.get("generative_mode", ""),
                )
                for r in self._rows(PROFILES_FILE)
                if r.get("profile_id")
            ]
        return list(self._profiles)

    def profile(self, agent_id: str) -> AgentProfile | None:
        return next((p for p in self.profiles() if p.id == agent_id), None)

    def agents_for_stage(self, bdi_stage: str) -> list[AgentProfile]:
        return [p for p in self.profiles() if bdi_stage in p.stages]

    # -- handoff-контракты ------------------------------------------------------
    def handoffs(self) -> list[HandoffContract]:
        if self._handoffs is None:
            self._handoffs = [
                HandoffContract(
                    id=r.get("handoff_id", ""),
                    from_stage=r.get("from_stage", ""),
                    from_agent=r.get("from_agent", ""),
                    to_stage=r.get("to_stage", ""),
                    to_agent=r.get("to_agent", ""),
                    gate=r.get("gate", ""),
                    required=_split_parts(r.get("required", "")),
                    on_reject=r.get("on_reject", ""),
                )
                for r in self._rows(HANDOFFS_FILE)
                if r.get("handoff_id")
            ]
        return list(self._handoffs)

    def handoff(self, from_stage: str | None = None,
                to_stage: str | None = None) -> HandoffContract | None:
        for h in self.handoffs():
            if (from_stage is None or h.from_stage == from_stage) and \
               (to_stage is None or h.to_stage == to_stage):
                return h
        return None

    # -- правила решений BDI -----------------------------------------------------
    def decisions(self) -> list[DecisionRule]:
        if self._decisions is None:
            out: list[DecisionRule] = []
            for r in self._rows(DECISIONS_FILE):
                if not r.get("rule_id"):
                    continue
                try:
                    priority = int(float(r.get("priority", "0") or 0))
                except ValueError:
                    priority = 0
                out.append(DecisionRule(
                    knowledge_base=r.get("knowledge_base", ""),
                    branch_id=r.get("branch_id", ""),
                    rule_id=r.get("rule_id", ""),
                    priority=priority,
                    guard=r.get("guard", ""),
                    outcome=r.get("outcome", ""),
                    requires_human_approval=(
                        r.get("requires_human_approval", "").strip().lower() in _TRUTHY),
                    knowledge_status=r.get("knowledge_status", ""),
                    execution_eligibility=r.get("execution_eligibility", ""),
                ))
            self._decisions = out
        return list(self._decisions)

    # -- сводка -------------------------------------------------------------------
    def stats(self) -> dict:
        return {"available": self.available, "dir": str(self.bdi_dir or ""),
                "profiles": len(self.profiles()), "handoffs": len(self.handoffs()),
                "decisions": len(self.decisions())}
