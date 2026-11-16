"""Контрактные проверки: полнота HandoffMemo перед передачей ответственности.

Выполняются для ЛЮБОГО гейта (``gate == "*"``) по свидетельству ``ev["handoff"]``.
Неполный меморандум — это failed-находка, передача без неё не выдаётся.
"""
from __future__ import annotations

from agents.contracts import Finding
from agents.checks.base import CheckSpec


def _mk(check_id: str, severity: str, passed: bool, title: str, *,
        message: str = "", remediation: str = "", evidence: dict | None = None) -> Finding:
    return Finding(id=check_id, severity=severity, passed=bool(passed), title=title,
                   message=message, source="contract", remediation=remediation,
                   evidence=evidence or {})


def _memo(ev: dict) -> dict | None:
    memo = ev.get("handoff")
    return memo if isinstance(memo, dict) and memo else None


def check_evidence_hash(ev: dict, ctx: dict) -> Finding | None:
    """Evidence hash заполнен (sha256, 64 hex-символа)."""
    memo = _memo(ev)
    if memo is None:
        return None
    value = str(memo.get("evidence_hash") or "")
    passed = len(value) == 64
    return _mk("contract.evidence_hash", "critical", passed, "Evidence hash меморандума",
               message=f"длина {len(value)}, ожидалось 64",
               remediation="пересоберите меморандум с хэшем артефактов",
               evidence={"length": len(value)})


def check_revisions(ev: dict, ctx: dict) -> Finding | None:
    """Ревизии артефактов перечислены (хотя бы одна)."""
    memo = _memo(ev)
    if memo is None:
        return None
    revisions = memo.get("artifact_revisions") or []
    return _mk("contract.revisions", "critical", bool(revisions),
               "Ревизии артефактов в меморандуме",
               message=f"ревизий: {len(revisions)}",
               remediation="приложите пути и sha256 переданных артефактов",
               evidence={"count": len(revisions)})


def check_qa(ev: dict, ctx: dict) -> Finding | None:
    """QA-вердикт этапа зафиксирован."""
    memo = _memo(ev)
    if memo is None:
        return None
    qa = memo.get("qa") or {}
    return _mk("contract.qa", "major", bool(qa), "QA-вердикт в меморандуме",
               message=f"полей QA: {len(qa)}",
               remediation="добавьте сводку проверок гейта (counts, kq/kc)",
               evidence={"fields": sorted(qa)[:8]})


def check_units(ev: dict, ctx: dict) -> Finding | None:
    """Единицы/СК модели зафиксированы (units/CRS)."""
    memo = _memo(ev)
    if memo is None:
        return None
    units = memo.get("units_crs")
    return _mk("contract.units", "major", bool(units), "Единицы/СК в меморандуме",
               message="units_crs пуст" if not units else "",
               remediation="укажите crs и единицы (проектный YAML: crs)",
               evidence={"units_crs": units})


def check_foreign_tokens(ev: dict, ctx: dict) -> Finding | None:
    """В рендере этапа нет чужих значений проекта (список токенов — данные config)."""
    text = str(ev.get("workflow_text") or "")
    tokens = [str(t) for t in (ctx.get("foreign_tokens") or []) if str(t)]
    if not text or not tokens:
        return None
    hits = sorted({t for t in tokens if t in text})
    return _mk("contract.foreign_tokens", "major", not hits,
               "Чужие значения проекта в рендере этапа",
               message=("найдено: " + "; ".join(hits)) if hits else "чисто",
               remediation=("замените/отключите чужие объекты через replace/parameters "
                            "в проектном YAML"),
               evidence={"tokens": hits})


CONTRACT_CHECKS: list[CheckSpec] = [
    CheckSpec("contract.evidence_hash", "*", "critical",
              "Evidence hash меморандума", check_evidence_hash,
              "пересоберите меморандум"),
    CheckSpec("contract.revisions", "*", "critical",
              "Ревизии артефактов", check_revisions,
              "приложите ревизии артефактов"),
    CheckSpec("contract.qa", "*", "major",
              "QA-вердикт", check_qa,
              "добавьте QA-сводку"),
    CheckSpec("contract.units", "*", "major",
              "Единицы/СК", check_units,
              "укажите единицы/СК"),
    CheckSpec("contract.foreign_tokens", "*", "major",
              "Чужие значения в рендере", check_foreign_tokens,
              "замените/отключите чужие объекты (project YAML: replace/parameters)"),
]
