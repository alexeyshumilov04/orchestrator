"""Адаптеры пакета QA/QC и диапазонов параметров к находкам гейтов.

Пакет `domain/qaqc/` (652 исторические + 62 оцифрованные проверки) применяется по
блокам, заданным ДАННЫМИ (`checks.package_blocks` в config.yaml). Принцип «неизвестное ≠
ложь»: если применимых проверок нет — адаптер возвращает пусто (не штрафует).

Серьёзность находки берётся из значимости проверки в пакете (поле significance):
>= 0.9 — critical, >= 0.75 — major, иначе minor — то есть данные пакета, не код.

Дополнительно (E4):

* ``applicability_matrix(blocks, values)`` — матрица применимости по слою значений
  (`domain/qc/values.py`): какие проверки применимы ЗДЕСЬ И СЕЙЧАС, каких ключей не
  хватает. Неприменимая проверка в находки не попадает;
* ``package_evaluate(..., alpha=, beta=)`` — веса свёртки фитнеса из данных
  (`checks.fitness_alpha/fitness_beta`), по умолчанию — как было (0.5/0.5).
"""
from __future__ import annotations

from agents.contracts import Finding

try:                                     # пакет опционален — деградация без него
    from domain.qaqc import CHECKS as _CHECKS
except Exception:                        # noqa: BLE001
    _CHECKS = {}

try:
    from domain.qaqc_adapter import evaluate as _qaqc_evaluate
except Exception:                        # noqa: BLE001
    _qaqc_evaluate = None

try:                                     # слой значений — чистый, без тНава
    from domain.qc import values as _values
except Exception:                        # noqa: BLE001
    _values = None


def _severity(significance: float | None) -> str:
    try:
        sig = float(significance)        # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "major"
    if sig >= 0.9:
        return "critical"
    if sig >= 0.75:
        return "major"
    return "minor"


def _significance(check_id: str) -> float | None:
    check = _CHECKS.get(check_id) if _CHECKS else None
    return getattr(check, "significance", None) if check is not None else None


def package_evaluate(blocks, values: dict, *, alpha: float | None = None,
                     beta: float | None = None) -> tuple[list[Finding], dict]:
    """Проверки пакета QA/QC по блокам гейта: (находки, метрики kq/kc/physical).

    ``alpha``/``beta`` — веса свёртки фитнеса из ДАННЫХ (``checks.fitness_alpha``,
    ``checks.fitness_beta``); не переданы — поведение прежнее (0.5/0.5).
    """
    if not blocks or not values or _qaqc_evaluate is None:
        return [], {}
    kwargs: dict = {}
    if alpha is not None:
        kwargs["alpha"] = float(alpha)
    if beta is not None:
        kwargs["beta"] = float(beta)
    report = _qaqc_evaluate(values, blocks=tuple(str(b) for b in blocks), **kwargs)
    applied = report.passed + report.failed
    if applied == 0:
        return [], {}
    label = ", ".join(str(b) for b in blocks)
    worst = max((_severity(_significance(str(item.get("id") or ""))) for item in
                 report.failed_checks), key={"minor": 0, "major": 1, "critical": 2}.get,
                default="major")
    findings: list[Finding] = [Finding(
        id=f"package.{label}", severity=worst,
        passed=(report.physical is True and report.failed == 0),
        title=f"Пакет QA/QC (блоки {label})",
        message=(f"применимо {applied}: пройдено {report.passed}, "
                 f"провалено {report.failed}; kq={report.kq:.3f} kc={report.kc:.3f}"
                 + ("" if report.physical is not None else "; физичность неизвестна")),
        source="package",
        remediation="разберите проваленные проверки пакета (failed_checks)",
        evidence={"kq": report.kq, "kc": report.kc, "passed": report.passed,
                  "failed": report.failed, "not_applicable": report.not_applicable,
                  "physical": report.physical, "fitness": report.fitness})]
    for item in report.failed_checks[:20]:
        cid = str(item.get("id") or "package.check")
        findings.append(Finding(
            id=cid, severity=_severity(_significance(cid)), passed=False,
            title=str(item.get("name") or "")[:120],
            message=str(item.get("message") or "")[:200],
            source="package", evidence={"block": str(item.get("block") or "")[:60]}))
    metrics = {"kq": report.kq, "kc": report.kc, "physical": report.physical,
               "physical_known": report.physical is not None,
               "fitness": report.fitness, "not_applicable": report.not_applicable,
               "applicable": report.applicable}
    return findings, metrics


def applicability_matrix(blocks, values: dict) -> dict:
    """Матрица применимости проверок пакета по значениям модели (без находок).

    Ответ на вопрос «что применимо ЗДЕСЬ И СЕЙЧАС»: сколько проверок получают
    данные, сколько остаются ``not_applicable`` и каких ключей не хватает.
    Отсутствие данных НЕ создаёт находок (правило 6).
    """
    if _values is None or not values:
        return {"total": 0, "not_applicable": 0, "missing_keys": {},
                "note": "слой значений недоступен или данных нет"}
    slots = _values.evaluate_all(values, blocks=blocks or None)
    summary = _values.summarize(slots)
    summary["note"] = ("not_applicable — это отсутствие входных данных; "
                       "модель по таким проверкам не штрафуется")
    return summary


def not_applicable_report(values: dict) -> list[dict]:
    """Диагностика «почему проверки не применимы» — данные отчёта, НЕ находки.

    Возвращаются только проверки, которым не хватает ключей, с перечнем ключей.
    Это не ``Finding``: отсутствие входных данных не является претензией к модели.
    """
    if _values is None or not values:
        return []
    out: list[dict] = []
    for slot in _values.evaluate_all(values):
        if slot.state != _values.NOT_APPLICABLE or not slot.missing:
            continue
        out.append({"id": slot.check_id, "block": (slot.block or "")[:60],
                    "missing": list(slot.missing)})
    return out


def range_findings(metacritic, values: dict) -> list[Finding]:
    """Диапазонные проверки онтологии (MetaCritic) по значениям этапа.

    В находки попадают только ПРОВАЛЕННЫЕ проверки (unknown/absent — не штраф).
    """
    if not values or metacritic is None:
        return []
    try:
        report = metacritic.evaluate(values)
    except Exception:                    # noqa: BLE001
        return []
    out: list[Finding] = []
    for check in report.checks:
        verdict = getattr(getattr(check, "verdict", None), "value", "")
        if verdict == "failed":
            out.append(Finding(id=f"range.{check.rule_id}", severity="major", passed=False,
                               title="Диапазон параметра (онтология)",
                               message=str(check.note or "")[:200], source="range"))
    return out
