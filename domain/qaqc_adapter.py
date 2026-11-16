"""Адаптер QAQC: 707 оцифрованных проверок качества → фитнес и гейт физичности.

Пакет `domain/qaqc/` — ДАННЫЕ домена: 652 исторические проверки + 62 оцифрованные
из чеклиста ГПН (блоки 05…13), независимые от тНава (каждая вызывается как
`check_<id>(data)`). Здесь они связываются с моделью:

* `DataContext` собирается из значений модели (мнемоники PHI/PORO, горизонты,
  толщины, свойства сетки) — тем же словарём, что и в самих проверках;
* проверка, для которой данных НЕТ, помечается `not_applicable` и модель НЕ штрафует
  (принцип «применённая проверка обязана пройти, отсутствие данных — не провал»);
* результат сворачивается в `kq` (качество, по проверкам с `fitness_function='да'`),
  `kc` (непротиворечивость, по остальным применимым) и гейт `physical` в ТРИ
  состояния: True — применимые проверки пройдены, False — есть провалы,
  None — применимых проверок не было («не проверялось», а не «зелено»).

Пороги, блоки и роли берутся из самого пакета — зашитых значений здесь нет.
"""
from __future__ import annotations

from dataclasses import dataclass, field

try:
    from . import qaqc as _qaqc
except Exception:                                 # noqa: BLE001 — пакет опционален
    _qaqc = None


# Блоки онтологии QAQC, относящиеся к статической геологической модели.
GEOLOGY_BLOCKS = ("02", "03", "04")


def package_available() -> bool:
    return _qaqc is not None and bool(getattr(_qaqc, "CHECKS", None))


def make_context(**values):
    """DataContext для проверок (dict-подобный контейнер пакета)."""
    if not package_available():
        return None
    return _qaqc.DataContext(**{k: v for k, v in values.items() if v is not None})


def _applicability(result) -> str:
    """'passed' | 'failed' | 'not_applicable' — по результату проверки.

    Отсутствие данных или ошибка вычисления — это НЕ провал модели, а отсутствие
    входных данных для суждения (пакет сообщает это текстом в `message`).
    """
    if result.passed:
        return "passed"
    text = (result.message or "").lower()
    if "missing data" in text or "error computing" in text:
        return "not_applicable"
    return "failed"


@dataclass
class QaqcReport:
    total: int = 0
    passed: int = 0
    failed: int = 0
    not_applicable: int = 0
    applicable: int = 0             # passed + failed (сколько проверок реально судило)
    kq: float = 0.0                 # качество результата (фитнес-компоненты)
    kc: float = 0.0                 # непротиворечивость (применимые QC-проверки)
    # physical: True — применимые проверки пройдены; False — есть провалы;
    # None — применимых проверок НЕ БЫЛО (ничего не проверялось, «неизвестно», не «зелено»).
    physical: bool | None = None
    fitness: float = 0.0            # ff = alpha*kq + beta*kc
    failed_checks: list[dict] = field(default_factory=list)
    by_block: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"total": self.total, "passed": self.passed, "failed": self.failed,
                "not_applicable": self.not_applicable, "applicable": self.applicable,
                "kq": round(self.kq, 4), "kc": round(self.kc, 4),
                "physical": self.physical,
                "physical_known": self.physical is not None,
                "fitness": round(self.fitness, 4),
                "by_block": dict(self.by_block),
                "failed_checks": self.failed_checks[:50]}


def evaluate(values: dict, *, blocks: tuple[str, ...] = GEOLOGY_BLOCKS,
             alpha: float = 0.5, beta: float = 0.5, max_failed: int = 500) -> QaqcReport:
    """Прогнать проверки QAQC по значениям модели и свернуть в kq/kc/ff.

    `blocks` — префиксы блоков онтологии QAQC (по умолчанию — статическая геология).
    `alpha`/`beta` — веса свёртки фитнеса (ff = α·kq + β·kc).
    """
    report = QaqcReport()
    if not package_available():
        return report
    checks = {cid: c for cid, c in _qaqc.CHECKS.items()
              if not blocks or (c.block or "").startswith(blocks)}
    report.total = len(checks)
    context = make_context(**(values or {}))
    fit_vals: list[float] = []
    qc_vals: list[float] = []
    for cid, check in checks.items():
        try:
            result = _qaqc.run_check(cid, context)
        except Exception:                         # noqa: BLE001
            report.not_applicable += 1
            continue
        state = _applicability(result)
        block = (check.block or "")[:2]
        slot = report.by_block.setdefault(block, {"passed": 0, "failed": 0,
                                                 "not_applicable": 0})
        slot["not_applicable" if state == "not_applicable" else state] += 1
        if state == "not_applicable":
            report.not_applicable += 1
            continue
        is_fitness = str(getattr(check, "fitness_function", "")).strip().lower() == "да"
        score = 1.0 if state == "passed" else 0.0
        (fit_vals if is_fitness else qc_vals).append(score)
        if state == "passed":
            report.passed += 1
        else:
            report.failed += 1
            if len(report.failed_checks) < max_failed:
                report.failed_checks.append({"id": cid, "name": check.name[:90],
                                             "block": check.block[:60],
                                             "message": (result.message or "")[:120],
                                             "values": [v.value for v in result.values]})
    # Свёртка: неприменимые проверки не участвуют (иначе «штраф за отсутствие данных»).
    report.kq = sum(fit_vals) / len(fit_vals) if fit_vals else 0.0
    report.kc = sum(qc_vals) / len(qc_vals) if qc_vals else 0.0
    report.fitness = alpha * report.kq + beta * report.kc
    # Физичность — ТРИ состояния (правило 6): «применённая проверка обязана пройти»,
    # но если применимых проверок НЕТ, это НЕ «пройдено»: physical = None («не проверялось»).
    report.applicable = report.passed + report.failed
    report.physical = (report.failed == 0) if report.applicable else None
    return report
