"""Движок гейтов передачи: вердикты, политики исчерпания, байпасс и waiver.

Политики `on_exhausted` (данные `gates:` в config.yaml; переключаются из UI):
  * best — принять лучшую ревизию и продолжить с деградацией (bypassed);
  * skip — пропустить этап и зависимые шаги (skipped);
  * halt — остановить прогон (failed);
  * ask  — пауза до решения оператора (awaiting_decision).

Глобальный выключатель `execution.gate_bypass: false` приводит любую политику
к `halt` (жёсткий режим). Решения оператора применяются :meth:`apply_decision`.
Вердикт детерминированный: LLM не может отменить failed-проверки.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from agents.contracts import (AWAITING, BYPASSED, FAILED, PASSED, PENDING,
                              UNVERIFIED, Finding, GateVerdict, SKIPPED, WAIVED,
                              severity_counts)

ON_EXHAUSTED_MODES = ("best", "skip", "halt", "ask")
DECISION_ACTIONS = ("best", "skip", "halt", "waiver")
DEFAULT_MAX_ATTEMPTS = 3

# Стандартная цепочка этапов 0–10 — используется, если `gates:` в config пуст.
# Значения — ДАННЫЕ (переопределяются секцией `gates:`), здесь только fallback.
FALLBACK_GATES: list[dict] = [
    {"id": "G-DATA", "agent": "AG_DATA_STEWARD", "stages": [0], "on_exhausted": "best"},
    {"id": "G-STRUCT", "agent": "AG_STRUCTURAL", "stages": [1, 2, 3], "on_exhausted": "best"},
    {"id": "G-GRID", "agent": "AG_GRID_VOLUMETRICS", "stages": [4, 5], "on_exhausted": "best"},
    {"id": "G-FACIES", "agent": "AG_FACIES", "stages": [6], "on_exhausted": "skip"},
    {"id": "G-PETRO", "agent": "AG_PETROPHYSICS", "stages": [7], "on_exhausted": "best"},
    {"id": "G-SAT", "agent": "AG_PVT_SCAL", "stages": [8], "on_exhausted": "best"},
    {"id": "G-VOL", "agent": "AG_GRID_VOLUMETRICS", "stages": [9], "on_exhausted": "best"},
    {"id": "G-MAPS", "agent": "AG_GRID_VOLUMETRICS", "stages": [10], "on_exhausted": "best"},
]


@dataclass(frozen=True)
class GateSpec:
    """Описание гейта: владелец, этапы, политика (данные)."""

    id: str
    agent: str
    stages: tuple[int, ...]
    on_exhausted: str = "halt"
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    require_physical: bool = True
    min_kq: float | None = None
    min_kc: float | None = None
    # Порог применяется только при достаточном числе ПРИМЕНИМЫХ проверок
    # (в dry-run метрик нет — порог пропускается, гейт остаётся pending_execution).
    min_applicable: int | None = None
    evidence: tuple[dict, ...] = ()   # [{kind: well_tie|grid|stoiip|property_mean, ...}]


def _spec_from_dict(item: dict) -> GateSpec | None:
    if not isinstance(item, dict) or not item.get("id"):
        return None
    mode = str(item.get("on_exhausted", "halt")).strip().lower()
    try:
        stages = tuple(int(s) for s in (item.get("stages") or []))
    except (TypeError, ValueError):
        stages = ()
    try:
        attempts = int(item.get("max_attempts", DEFAULT_MAX_ATTEMPTS) or DEFAULT_MAX_ATTEMPTS)
    except (TypeError, ValueError):
        attempts = DEFAULT_MAX_ATTEMPTS
    evidence = tuple(e for e in (item.get("evidence") or [])
                     if isinstance(e, dict) and e.get("kind"))
    return GateSpec(
        id=str(item["id"]),
        agent=str(item.get("agent", "")),
        stages=stages,
        on_exhausted=mode if mode in ON_EXHAUSTED_MODES else "halt",
        max_attempts=max(1, attempts),
        require_physical=bool(item.get("require_physical", True)),
        min_kq=item.get("min_kq"),
        min_kc=item.get("min_kc"),
        min_applicable=item.get("min_applicable"),
        evidence=evidence,
    )


def _as_float(value) -> float:
    """Привести метрику к float; отсутствие/мусор → 0.0 (признак «не посчитано» — None)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _apply_overrides(cfg, items: list[dict]) -> list[dict]:
    """Наложить `gates_override` (переключения из интерфейса; config.local.yaml)."""
    overrides = cfg.get("gates_override") if cfg is not None else None
    if not isinstance(overrides, dict):
        return items
    merged: list[dict] = []
    for item in items:
        upd = overrides.get(str(item.get("id")))
        if isinstance(upd, dict):
            merged_item = dict(item)
            merged_item.update(upd)
            merged.append(merged_item)
        else:
            merged.append(item)
    return merged


def load_gate_specs(cfg) -> list[GateSpec]:
    """Гейты из config (`gates:` + `gates_override`); пусто → FALLBACK_GATES (данные)."""
    raw = cfg.get("gates") if cfg is not None else None
    items = [dict(i) for i in raw] if isinstance(raw, list) else []
    if items:
        items = _apply_overrides(cfg, items)
    specs = [s for s in (_spec_from_dict(i) for i in items) if s is not None]
    if not specs and not items:
        specs = [s for s in (_spec_from_dict(i) for i in FALLBACK_GATES) if s is not None]
    return specs


def policies(cfg) -> dict:
    """Снимок политик для интерфейса (GET /api/gates)."""
    return {"bypass_enabled": bypass_enabled(cfg),
            "gates": [{"id": s.id, "agent": s.agent, "stages": list(s.stages),
                       "on_exhausted": s.on_exhausted, "max_attempts": s.max_attempts,
                       "min_kq": s.min_kq, "min_kc": s.min_kc,
                       "min_applicable": s.min_applicable,
                       "evidence": [dict(e) for e in s.evidence]}
                      for s in load_gate_specs(cfg)]}


def update_policies(cfg, payload: dict, *, save: bool = False) -> dict:
    """Политики из интерфейса (PUT /api/gates): валидные значения → gates_override.

    Персистентность — config.local.yaml (базовый config.yaml не трогается);
    недопустимые значения игнорируются.
    """
    if cfg is None:
        return policies(cfg)
    if isinstance(payload, dict) and payload.get("gate_bypass") is not None:
        cfg.set("execution.gate_bypass", bool(payload["gate_bypass"]))
    known = {s.id for s in load_gate_specs(cfg)}
    for gid, upd in ((payload or {}).get("gates") or {}).items():
        if gid not in known or not isinstance(upd, dict):
            continue
        mode = str(upd.get("on_exhausted") or "").strip().lower()
        if mode in ON_EXHAUSTED_MODES:
            cfg.set(f"gates_override.{gid}.on_exhausted", mode)
        attempts = upd.get("max_attempts")
        if isinstance(attempts, int) and attempts >= 1:
            cfg.set(f"gates_override.{gid}.max_attempts", attempts)
    if save:
        cfg.save()
    return policies(cfg)


def bypass_enabled(cfg) -> bool:
    """Глобальный тумблер байпасса (переключается из UI; прототип — включён)."""
    if cfg is None:
        return True
    return bool(cfg.get("execution.gate_bypass", True))


class GateEngine:
    """Вердикты и политики гейтов (конкретные проверки подключает реестр checks)."""

    def __init__(self, cfg=None, registry=None) -> None:
        self.cfg = cfg
        self.registry = registry
        self._specs: list[GateSpec] | None = None

    # -- описания ---------------------------------------------------------------
    def specs(self) -> list[GateSpec]:
        if self._specs is None:
            self._specs = load_gate_specs(self.cfg)
        return list(self._specs)

    def spec(self, gate_id: str) -> GateSpec | None:
        return next((s for s in self.specs() if s.id == gate_id), None)

    def spec_for_stage(self, index: int) -> GateSpec | None:
        return next((s for s in self.specs() if index in s.stages), None)

    def to_dict(self) -> list[dict]:
        return [{"id": s.id, "agent": s.agent, "stages": list(s.stages),
                 "on_exhausted": s.on_exhausted, "max_attempts": s.max_attempts,
                 "min_kq": s.min_kq, "min_kc": s.min_kc,
                 "min_applicable": s.min_applicable,
                 "evidence": [dict(e) for e in s.evidence],
                 "bypass_enabled": bypass_enabled(self.cfg)} for s in self.specs()]

    # -- вердикт ------------------------------------------------------------------
    def applicable_requirement(self, spec: GateSpec) -> int:
        """Сколько ПРИМЕНИМЫХ проверок нужно, чтобы порог kq/kc имел силу (данные).

        Приоритет данных: ``min_applicable`` гейта (конкретное) → глобальный
        ``checks.min_applicable_checks`` (config); нет ни того, ни другого → 1
        (порог действует, как только метрики посчитаны).
        """
        raw = spec.min_applicable
        if raw is None and self.cfg is not None:
            raw = self.cfg.get("checks.min_applicable_checks")
        try:
            need = int(raw)
        except (TypeError, ValueError):
            need = 1
        return max(1, need)

    def evaluate(self, spec: GateSpec, findings: list[Finding], *,
                 metrics: dict | None = None, attempts: int = 0) -> GateVerdict:
        """Детерминированный вердикт: critical-проверки + пороги kq/kc + физичность.

        Порог kq/kc применяется ТОЛЬКО когда метрики реально посчитаны (есть ключ
        ``kq``/``kc``) И применимых проверок не меньше требуемого числа. В dry-run
        метрик нет → порог пропускается, гейт остаётся ``pending_execution``:
        отсутствие данных не подменяется нулём и не штрафует модель (правило 6).
        """
        metrics = metrics or {}
        kq_raw, kc_raw = metrics.get("kq"), metrics.get("kc")
        kq = _as_float(kq_raw)
        kc = _as_float(kc_raw)
        applicable = metrics.get("applicable")
        try:
            applicable_n = int(applicable) if applicable is not None else (
                1 if (kq_raw is not None or kc_raw is not None) else 0)
        except (TypeError, ValueError):
            applicable_n = 0
        need = self.applicable_requirement(spec)
        threshold_ready = applicable_n >= need and (kq_raw is not None or kc_raw is not None)
        skipped: list[str] = []
        for name, raw in (("min_kq", kq_raw), ("min_kc", kc_raw)):
            if getattr(spec, name) is not None and (not threshold_ready or raw is None):
                skipped.append(name)
        below = False
        if spec.min_kq is not None and threshold_ready and kq_raw is not None:
            below = below or kq < float(spec.min_kq)
        if spec.min_kc is not None and threshold_ready and kc_raw is not None:
            below = below or kc < float(spec.min_kc)
        physical = metrics.get("physical")      # None = не проверялось (нет метрик)
        failed_critical = any(f.severity == "critical" and not f.passed for f in findings)
        phys_fail = spec.require_physical and metrics.get("physical") is False
        # F-19: проверка результата, не нашедшая свидетельства, помечает находку
        # `unverified`. Гейт тогда НЕ может стать passed (нельзя «зелено» без
        # результата), но и не failed: отсутствие данных — не провал модели (правило 6).
        unverified = [f.id for f in findings if getattr(f, "state", "") == UNVERIFIED]
        status = (FAILED if (failed_critical or below or phys_fail)
                  else PENDING if unverified else PASSED)
        thresholds = {"min_kq": spec.min_kq, "min_kc": spec.min_kc,
                      "applicable": applicable_n, "required_applicable": need,
                      "applied": threshold_ready and (spec.min_kq is not None
                                                      or spec.min_kc is not None),
                      "skipped": skipped,
                      "unverified": unverified,
                      "reason": ("метрики kq/kc не посчитаны (нет применимых проверок) — "
                                 "порог не применяется" if skipped else
                                 (f"результат не подтверждён: нет свидетельства для "
                                  f"{', '.join(unverified)}" if unverified else ""))}
        verdict = GateVerdict(gate_id=spec.id, status=status, counts=severity_counts(findings),
                              kq=kq, kc=kc, physical=physical, findings=list(findings),
                              attempts=attempts, mode=spec.on_exhausted,
                              thresholds=thresholds, unverified=unverified)
        if unverified and status == PENDING:
            verdict.comment = (f"не проверено: нет свидетельства о результате для "
                               f"{', '.join(unverified)}")
        return verdict

    # -- политика исчерпания ---------------------------------------------------------
    def exhaust(self, spec: GateSpec, verdict: GateVerdict, *,
                override_mode: str | None = None) -> tuple[str, str]:
        """(status, reason) после исчерпания попыток; учитывает глобальный тумблер."""
        mode = str(override_mode or spec.on_exhausted or "halt").strip().lower()
        if not bypass_enabled(self.cfg):
            mode = "halt"
        if mode not in ON_EXHAUSTED_MODES:
            mode = "halt"
        if mode == "best":
            return BYPASSED, "исчерпаны попытки: принята лучшая ревизия (degraded)"
        if mode == "skip":
            return SKIPPED, "исчерпаны попытки: этап и зависимые шаги пропущены"
        if mode == "ask":
            return AWAITING, "исчерпаны попытки: ожидается решение оператора"
        return FAILED, "исчерпаны попытки: остановка (halt)"

    def resolve(self, verdict: GateVerdict, status: str, *, reason: str = "",
                decider: str = "auto", comment: str = "",
                waiver: dict | None = None) -> GateVerdict:
        return replace(verdict, status=status, decider=decider,
                       comment=comment or reason, waiver=waiver)

    # -- решение оператора (API resolve, переключатели из UI) --------------------------
    def apply_decision(self, verdict: GateVerdict, action: str, *,
                       author: str = "", comment: str = "") -> GateVerdict:
        """Применить решение оператора: best|skip|halt|waiver (с аудитом)."""
        action = (action or "").strip().lower()
        if action not in DECISION_ACTIONS:
            raise ValueError(f"неизвестное действие: {action!r}; допустимо {DECISION_ACTIONS}")
        mapping = {"best": BYPASSED, "skip": SKIPPED, "halt": FAILED, "waiver": WAIVED}
        waiver = ({"author": author, "comment": comment, "ts": verdict.ts}
                  if action == "waiver" else None)
        return self.resolve(verdict, mapping[action], decider="operator",
                            comment=comment, waiver=waiver)
