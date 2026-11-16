"""BaseAgent v2 — ЕДИНЫЙ контракт агента этапа: BDI-цикл, детерминированный.

Агент отвечает на вопрос «как исполнить МОЙ этап» по ДАННЫМ (проектный граф +
свидетельства этапа + БЗ) и НЕ содержит ни одного доменного значения (имя
объекта/маркера/куба, порог, путь, координата) — только КЛЮЧИ данных.

Цикл (соответствует `BDI_AGENT_DIVISION_AND_AUTONOMY_AUDIT.md`, но исполним
детерминированно, без LLM в числах):

    StageContext ─► observe(evidence) ─► beliefs ─► coverage() ─► mode
        │                                                            │
        └──► decide() ─► AgentDecision{plan, patches, unknown, rationale}
                     │
                     ├─► plan()      StagePlan (PlanIR: функции/параметры/объекты)
                     ├─► validate()  формальные находки (Finding)
                     ├─► verify()    вердикт гейта (GateVerdict, движок гейтов)
                     ├─► remember()  запись опыта в БЗ (KnowledgeBase)
                     ├─► recall()/suggest()/reconsider()  — опыт прошлых прогонов
                     └─► capabilities()  что агент умеет (данные онтологии)

Режимы решения (`CoverageReport.mode`), пороги — ДАННЫЕ (`agents.policy`):
  * SYMBOLIC   — покрытие >= symbolic_threshold: план целиком из утверждённых правил;
  * HYBRID     — покрытие >= hybrid_threshold: детерминированный каркас, LLM — только
                 по явно найденному пробелу (решение LLM всё равно проходит гейт);
  * GENERATIVE — покрытие ниже: черновики плана, исполнение после гейта человека;
  * ABSTAIN    — входов нет: «неизвестное != ложь» — этап не отключается молча,
                 фиксируется unknown с перечнем недостающих входов.

Иерархия реализаций (все — наследники, только данные + политика):
  StructureAgent · GridAgent · FaciesAgent · PetrophysicsAgent · SaturationAgent ·
  VolumetricsAgent · MapsAgent · QaRemediationAgent.

Совместимость: `decide(project, evidence)` сохранён — возвращает надмножество
прежнего словаря решения (старые ключи `enabled/reason/coverage/parameters` не
меняются, добавляются `mode/coverage_report/plan/unknown/missing/agent_id/label`).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from agents.contracts import Finding, StageContext, StagePlan

# --- режимы решения (идентификаторы схемы, не домен) --------------------------
SYMBOLIC, HYBRID, GENERATIVE, ABSTAIN = "symbolic", "hybrid", "generative", "abstain"
MODES = (SYMBOLIC, HYBRID, GENERATIVE, ABSTAIN)

_SEVERITY_PENALTY = {"critical": 1.0, "major": 0.5, "minor": 0.2}


@dataclass
class CoverageReport:
    """Полнота входов агента: чем он реально располагает, а чего не хватает."""

    known: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    ratio: float = 0.0
    symbolic_threshold: float = 1.0
    hybrid_threshold: float = 0.0

    @property
    def mode(self) -> str:
        """Режим решения по полноте входов (пороги — данные).

        Нет ни одного известного входа → ABSTAIN: решать не на чем, план не
        выдумывается («неизвестное != ложь»).
        """
        if not self.known:
            return ABSTAIN
        if self.ratio >= self.symbolic_threshold:
            return SYMBOLIC
        if self.ratio >= self.hybrid_threshold:
            return HYBRID
        return GENERATIVE

    def to_dict(self) -> dict:
        data = asdict(self)
        data["mode"] = self.mode
        return data


@dataclass
class Capability:
    """Способность агента (из онтологии/данных); `verified` — только по данным."""

    id: str
    kind: str = "function"            # function | check | evidence | method
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    verified: bool = False
    source: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AgentDecision:
    """Решение агента: план + обоснование + честные пробелы."""

    agent_id: str = ""
    label: str = ""
    stage_key: str = ""
    mode: str = ABSTAIN
    enabled: bool = False
    plan: dict = field(default_factory=dict)
    patches: dict = field(default_factory=dict)
    rationale: str = ""
    unknown: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence_refs: list[str] = field(default_factory=list)
    recalled: list[dict] = field(default_factory=list)
    coverage_report: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class BaseAgent:
    """Общий контракт агента-политики этапа (без доменных значений в коде)."""

    agent_id: str = ""           # имя BDI-профиля из онтологии v4.1 (данные)
    label: str = ""              # человекочитаемое имя (для отчётов)

    def __init__(self, cfg=None, *, kb=None, registry=None, gate_engine=None,
                 static: Any = None) -> None:
        self.cfg = cfg
        self.kb = kb
        self.registry = registry
        self.gate_engine = gate_engine
        self._static = static
        self._ctx: StageContext | None = None
        self._project: dict = {}
        self._evidence: dict = {}
        self._beliefs: dict = {}
        self._decision: AgentDecision | None = None
        self._plan: StagePlan | None = None

    # ================= фазы BDI ================================================
    def bind(self, ctx: StageContext | dict | None) -> "BaseAgent":
        """Привязать этап: контекст (StageContext) и проектный граф."""
        if isinstance(ctx, StageContext):
            self._ctx = ctx
            self._project = dict(ctx.project or {})
        elif isinstance(ctx, dict):
            self._project = dict(ctx)
        return self

    def policy(self) -> dict:
        """Пороги режима решения (ДАННЫЕ `agents.policy`)."""
        if self.cfg is None:
            return {"symbolic_threshold": 1.0, "hybrid_threshold": 0.0}
        return {"symbolic_threshold": float(
                    self.cfg.get("agents.policy.symbolic_threshold", 1.0) or 1.0),
                "hybrid_threshold": float(
                    self.cfg.get("agents.policy.hybrid_threshold", 0.0) or 0.0)}

    def observe(self, evidence: dict | None) -> dict:
        """Обновить убеждения фактами этапа (ключи — данные, значения — как есть)."""
        ev = evidence if isinstance(evidence, dict) else {}
        self._evidence = dict(ev)
        self._beliefs.update(ev)
        self._beliefs["observed"] = sorted(str(k) for k in ev)
        return self._beliefs

    def requirements(self) -> list[str]:
        """Обязательные входы агента (ДАННЫЕ `agents.required_inputs.<agent_id>`)."""
        if self.cfg is None or not self.agent_id:
            return []
        value = self.cfg.get(f"agents.required_inputs.{self.agent_id}", [])
        return [str(x) for x in (value or [])]

    def coverage(self) -> CoverageReport:
        """Полнота входов: ключ есть и непуст → known; пуст → unknown; нет → missing."""
        limits = self.policy()
        view = {**self._project, **self._evidence}
        known: list[str] = []
        missing: list[str] = []
        unknown: list[str] = []
        for key in self.requirements():
            if key not in view:
                missing.append(key)
            elif view.get(key) in (None, "", [], {}):
                unknown.append(key)
            else:
                known.append(key)
        total = len(known) + len(missing) + len(unknown)
        ratio = (len(known) / total) if total else 0.0
        return CoverageReport(known=known, missing=missing, unknown=unknown,
                              ratio=round(ratio, 4), **limits)

    def capabilities(self) -> list[Capability]:
        """Способности агента из ДАННЫХ (онтология/конфигурация), с флагом verify."""
        if self.cfg is None:
            return []
        declared = self.cfg.get(f"agents.capabilities.{self.agent_id}", []) or []
        verified = {str(x) for x in
                    (self.cfg.get("agents.policy.verified_capabilities") or [])}
        out: list[Capability] = []
        for item in declared:
            item = item if isinstance(item, dict) else {"id": str(item)}
            cap_id = str(item.get("id") or "")
            if not cap_id:
                continue
            out.append(Capability(
                id=cap_id,
                kind=str(item.get("kind") or "function"),
                requires=tuple(str(x) for x in (item.get("requires") or [])),
                produces=tuple(str(x) for x in (item.get("produces") or [])),
                verified=cap_id in verified or bool(item.get("verified")),
                source=str(item.get("source") or "")))
        return out

    # ================= решение ==================================================
    def decision(self, project: dict, evidence: dict | None = None) -> dict:
        """Решение агента по данным проекта/свидетельствам. Реализуется наследником."""
        raise NotImplementedError

    def decide(self, project: dict | None = None, evidence: dict | None = None) -> dict:
        """Публичная точка входа: полное решение (надмножество прежнего контракта).

        Возвращается СЛИЯНИЕ: сначала все ключи решения наследника (`enabled`,
        `reason`, `coverage`, `parameters`, доменные поля), затем метаданные цикла
        (`mode`, `coverage_report`, `plan`, `unknown`, `missing`, …). Так прежние
        потребители (`StageRunner`, `decide_*`) не ломаются.
        """
        project = project if isinstance(project, dict) else self._project
        self._project = dict(project or {})
        self.observe(evidence if evidence is not None else self._evidence)
        raw = self.decision(self._project, self._evidence) or {}
        self._decision = self._compose(raw)
        self._plan = self._build_plan(self._decision)
        return {**(raw if isinstance(raw, dict) else {}), **self._decision.to_dict()}

    def _compose(self, raw: dict) -> AgentDecision:
        """Собрать AgentDecision: слово наследника + метаданные цикла."""
        cov = self.coverage()
        patches = raw.get("parameters") if isinstance(raw.get("parameters"), dict) else {}
        recalled = self.recall(self._project)
        refs = sorted(str(k) for k in self._evidence)
        unknown = list(raw.get("unknown") or []) + cov.unknown
        missing = list(raw.get("missing") or []) + cov.missing
        rationale = str(raw.get("reason") or raw.get("rationale") or "")
        if cov.mode in (GENERATIVE, ABSTAIN) and missing:
            rationale = (rationale + " | не хватает входов: " + ", ".join(missing)).strip(" |")
        return AgentDecision(
            agent_id=self.agent_id, label=self.label,
            stage_key=(self._ctx.stage_key if self._ctx else str(raw.get("stage") or "")),
            mode=cov.mode, enabled=bool(raw.get("enabled", False)),
            plan={k: raw[k] for k in ("grid_function", "method", "cubes", "n_facies",
                                      "variogram", "steps", "top_marker", "base_marker")
                  if k in raw},
            patches=dict(patches), rationale=rationale,
            unknown=sorted(set(unknown)), missing=sorted(set(missing)),
            confidence=round(cov.ratio, 4), evidence_refs=refs, recalled=recalled,
            coverage_report=cov.to_dict())

    def __call__(self, project: dict, evidence: dict | None = None) -> dict:
        """Позволяет использовать агента как функцию: ``agent(graph, ev)``."""
        return self.decide(project, evidence)

    # ================= PlanIR, валидация, вердикт ================================
    def plan(self) -> StagePlan | None:
        """PlanIR последнего решения (None — решения ещё не было)."""
        return self._plan

    def _build_plan(self, decision: AgentDecision) -> StagePlan:
        """Собрать StagePlan: функции/параметры + предупреждения из режима."""
        warnings: list[str] = []
        if decision.missing:
            warnings.append("нет входов: " + ", ".join(decision.missing))
        if decision.mode in (GENERATIVE, ABSTAIN):
            warnings.append(f"режим {decision.mode}: исполнение только после гейта")
        return StagePlan(
            agent_id=self.agent_id,
            stage_key=decision.stage_key,
            functions=sorted(decision.patches),
            parameters=decision.patches,
            rationale=decision.rationale,
            source=("llm" if decision.mode == HYBRID else "deterministic"),
            warnings=warnings)

    def validate(self, plan: StagePlan | dict | None = None) -> list[Finding]:
        """Формальные находки по плану: пустой план, нечисловые параметры, глубина.

        Возвращает [] , если проверять нечего («неизвестное != ложь»): выключенный
        этап и отсутствие параметров — это не провал, а отсутствие предмета проверки.
        """
        if plan is None:
            plan = self._plan
        data = plan.to_dict() if isinstance(plan, StagePlan) else (plan or {})
        if self._decision is None or not self._decision.enabled:
            return []
        patches = data.get("parameters") or {}
        findings: list[Finding] = []
        if not data.get("functions") and not patches:
            findings.append(Finding(
                id=f"plan.{self.agent_id or 'agent'}.empty", severity="critical",
                passed=False, title="План агента пуст",
                message="этап включён, но план не содержит ни одной функции/параметра",
                source="contract",
                remediation="задайте parameters/objects в проектном графе"))
            return findings
        for fn, params in patches.items():
            if not isinstance(params, dict):
                findings.append(Finding(
                    id=f"plan.{fn}.shape", severity="major", passed=False,
                    title="Форма параметров функции",
                    message=f"{fn}: параметры должны быть словарём «код → значение»",
                    source="contract"))
                continue
            for code, value in params.items():
                if isinstance(value, float) and not math.isfinite(value):
                    findings.append(Finding(
                        id=f"plan.{fn}.{code}.finite", severity="major", passed=False,
                        title="Нечисловое значение параметра",
                        message=f"{fn}.{code} = {value!r}", source="contract"))
                if isinstance(value, dict) and any(isinstance(v, (dict, list))
                                                   for v in value.values()):
                    findings.append(Finding(
                        id=f"plan.{fn}.{code}.depth", severity="minor", passed=False,
                        title="Слишком глубокая вложенность параметра",
                        message=f"{fn}.{code}: вложенность > 2 уровней",
                        source="contract"))
        return findings

    def verify(self, findings: list[Finding] | None = None,
               metrics: dict | None = None) -> dict:
        """Вердикт по находкам: движок гейтов (если дали), иначе сводка.

        LLM вердикт не меняет: он детерминированный (critical → failed).
        """
        rows = list(findings or [])
        failed = [f for f in rows if not f.passed]
        engine = self.gate_engine
        spec = None
        if engine is not None and self._ctx is not None:
            try:
                spec = (engine.spec(self._ctx.gate_id)
                        or engine.spec_for_stage(self._ctx.index))
            except Exception:                     # noqa: BLE001 — движок опционален
                spec = None
        if spec is not None:
            verdict = engine.evaluate(spec, rows, metrics=metrics or None)
            return verdict.to_dict()
        penalty = sum(_SEVERITY_PENALTY.get(f.severity, 0.3) for f in failed)
        return {"gate_id": (self._ctx.gate_id if self._ctx else ""),
                "status": "failed" if any(f.severity == "critical" for f in failed)
                          else ("rework" if failed else "passed"),
                "checks": len(rows), "failed": len(failed),
                "penalty": round(penalty, 4),
                "findings": [f.to_dict() for f in failed]}

    # ================= память (БЗ) ==============================================
    def remember(self, memo: dict | None = None, *, metrics: dict | None = None) -> str:
        """Записать опыт этого решения в БЗ (`KnowledgeBase.remember`)."""
        if self.kb is None or self._decision is None:
            return ""
        from agents.knowledge import ExperienceRecord
        memo = memo or {}
        verdict = str(memo.get("verdict") or memo.get("status") or "")
        outcome = ("passed" if verdict in ("passed", "pending_execution") else
                   "degraded" if verdict in ("bypassed", "skipped", "waived") else
                   "failed" if verdict else "")
        record = ExperienceRecord(
            agent=self.agent_id,
            stage=self._decision.stage_key,
            gate=str(memo.get("gate") or memo.get("handoff_id") or ""),
            field_name=str((self._project or {}).get("field") or ""),
            mode=self._decision.mode,
            verdict=verdict, attempts=int(memo.get("attempts") or 1),
            degraded=bool(memo.get("degraded")),
            outcome=outcome,
            functions=sorted(self._decision.patches),
            parameters=self._decision.patches,
            plan_hash=str(memo.get("evidence_hash") or ""),
            evidence_hash=str(memo.get("evidence_hash") or ""),
            metrics=dict(metrics or {}),
            provenance=str(memo.get("id") or ""))
        return self.kb.remember(record)

    def recall(self, situation: dict | None = None, *,
               functions: list[str] | None = None, parameters: dict | None = None,
               k: int | None = None) -> list[dict]:
        """Похожий опыт прошлых прогонов (детерминированно, без LLM)."""
        if self.kb is None:
            return []
        patches = parameters if parameters is not None else \
            ((self._decision.patches if self._decision else {}) or {})
        flat: dict = {}
        for _fn, params in (patches or {}).items():
            if isinstance(params, dict):
                flat.update(params)
        stage = (self._decision.stage_key if self._decision else
                 (self._ctx.stage_key if self._ctx else None))
        try:
            return self.kb.recall(agent=self.agent_id, stage=stage or None,
                                  functions=functions or sorted(patches or {}),
                                  parameters=flat, k=k)
        except Exception:                             # noqa: BLE001 — БЗ не роняет прогон
            return []

    def suggest(self, *, functions: list[str] | None = None,
                parameters: dict | None = None, k: int | None = None) -> dict:
        """Рекомендация параметров из опыта (пусто — опыта нет)."""
        if self.kb is None:
            return {}
        try:
            return self.kb.suggest(agent=self.agent_id,
                                   stage=(self._ctx.stage_key if self._ctx else None),
                                   functions=functions, parameters=parameters, k=k)
        except Exception:                             # noqa: BLE001
            return {}

    def reconsider(self, findings: list[Finding] | None = None) -> dict:
        """Предложение правки после провала: опыт БЗ → `variations` проекта → эскалация."""
        failed = [f for f in (findings or []) if not f.passed]
        if not failed:
            return {"action": "none", "patches": {}, "reason": "провалов нет"}
        patched = self.suggest()
        if patched:
            return {"action": "rework", "patches": patched, "source": "kb",
                    "reason": "параметры подобраны по похожему удачному опыту (БЗ)"}
        reason = "; ".join(f"{f.id}: {f.message}"[:120] for f in failed[:3])
        return {"action": "escalate", "patches": {}, "source": "none",
                "reason": f"опыта в БЗ нет, правка не выведена: {reason}"}

    # ================= состояние для отчёта =====================================
    def state(self) -> dict:
        """Снимок агента для отчёта прогона (данные, пригодные к JSON)."""
        return {"agent_id": self.agent_id, "label": self.label,
                "requirements": self.requirements(),
                "policy": self.policy(),
                "capabilities": [c.to_dict() for c in self.capabilities()],
                "coverage_report": self.coverage().to_dict(),
                "decision": self._decision.to_dict() if self._decision else None,
                "plan": self._plan.to_dict() if self._plan else None}

    # -- утилиты (без домена) -----------------------------------------------------
    @staticmethod
    def _num(value, default: float) -> float:
        """Привести значение к float; нечисловое → default («неизвестное != ложь»)."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _section(project: dict, key: str) -> dict:
        """Секция проектного YAML; отсутствие/не-словарь → {} (данные, не код)."""
        value = (project or {}).get(key)
        return value if isinstance(value, dict) else {}
