"""Слой значений модели для QA/QC: DataContext из словаря значений.

Модуль ЧИСТЫЙ: он ничего не знает ни о tNavigator, ни о файлах проекта.
Значения приходят словарём от вызывающей стороны (``core/coordinator._qaqc_values``,
пробники ``domain/qc/probes.py``), а требуемые ключи берутся ИЗ ДАННЫХ —
из колонки «Входные ключи» оцифрованных проверок (``ontology/qa_checks/bNN.csv``)
и контракта ``ontology/qa_checks/model_keys.csv``.

Главный принцип (правило 6 «неизвестное ≠ ложь»):

* проверка, для которой нет хотя бы одного входного ключа, получает состояние
  ``not_applicable`` с перечнем отсутствующих ключей и модель НЕ штрафуется;
* проверка НИКОГДА не помечается пройденной «по умолчанию».

Публичный минимум::

    from domain.qc import values as val
    ctx  = val.build_context(check, model_values)      # DataContext пакета
    slot = val.evaluate(check, model_values)           # Slot(state, missing, result)
    slots = val.evaluate_all(model_values)             # по всем проверкам пакета
    need = val.required_keys(check)
    have = val.provided_keys(model_values)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

PASSED = "passed"
FAILED = "failed"
NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Slot:
    """Результат проверки в матрице применимости."""

    check_id: str
    block: str
    state: str                     # passed | failed | not_applicable
    missing: tuple[str, ...] = ()
    result: Any = None

    @property
    def applicable(self) -> bool:
        return self.state != NOT_APPLICABLE

    def to_dict(self) -> dict:
        out = {"id": self.check_id, "block": self.block, "state": self.state}
        if self.missing:
            out["missing"] = list(self.missing)
        if self.result is not None:
            out["message"] = getattr(self.result, "message", "")
        return out


def _as_mapping(values: Mapping[str, Any] | Any | None) -> Mapping[str, Any]:
    if values is None:
        return {}
    if isinstance(values, Mapping):
        return values
    if hasattr(values, "items"):
        return dict(values.items())        # DataContext/dict-подобное
    return {}


def provided_keys(values: Mapping[str, Any] | Any | None) -> set[str]:
    """Ключи, реально переданные вызывающей стороной (в верхнем регистре)."""
    return {str(k).upper() for k in _as_mapping(values)}


def _lookup(values: Mapping[str, Any], key: str) -> tuple[bool, Any]:
    """Найти значение ключа без учёта регистра; пустые значения не считаются данными."""
    if key in values:
        v = values[key]
        return (v is not None, v)
    up = key.upper()
    for k, v in values.items():
        if str(k).upper() == up:
            return (v is not None, v)
    return (False, None)


def required_keys(check: Any) -> list[str]:
    """Ключи, нужные проверке (по её метрикам), в порядке первого появления."""
    out: list[str] = []
    for spec in getattr(check, "metrics", []) or []:
        for key in spec.inputs or []:
            if key not in out:
                out.append(key)
    return out


def missing_keys(check: Any, values: Mapping[str, Any] | Any | None) -> list[str]:
    """Отсутствующие ключи проверки (пустой список — данных хватает)."""
    vals = _as_mapping(values)
    return [k for k in required_keys(check) if not _lookup(vals, k)[0]]


def build_context(check: Any, values: Mapping[str, Any] | Any | None):
    """``DataContext`` пакета ``domain/qaqc`` только с ключами этой проверки."""
    from domain.qaqc import DataContext                  # noqa: PLC0415
    vals = _as_mapping(values)
    ctx = DataContext()
    for key in required_keys(check):
        ok, value = _lookup(vals, key)
        if ok:
            ctx[key] = value
    return ctx


def evaluate(check: Any, values: Mapping[str, Any] | Any | None) -> Slot:
    """Прогнать одну проверку по значениям; нет ключей → not_applicable."""
    cid = str(getattr(check, "id", "") or "?")
    block = str(getattr(check, "block", "") or "")
    miss = tuple(missing_keys(check, values))
    if miss:
        return Slot(check_id=cid, block=block, state=NOT_APPLICABLE, missing=miss)
    from domain.qaqc import run_check                      # noqa: PLC0415
    try:
        result = run_check(cid, build_context(check, values))
    except Exception as exc:                               # noqa: BLE001
        return Slot(check_id=cid, block=block, state=NOT_APPLICABLE,
                    missing=miss, result=type("R", (), {"message": str(exc)})())
    text = (getattr(result, "message", "") or "").lower()
    if "missing data" in text or "error computing" in text:
        # ключ был передан, но не разобрался: это отсутствие данных, а не провал
        return Slot(check_id=cid, block=block, state=NOT_APPLICABLE,
                    missing=miss, result=result)
    return Slot(check_id=cid, block=block,
                state=PASSED if result.passed else FAILED, result=result)


def checks_for_blocks(blocks: Iterable[str] | None = None) -> dict[str, Any]:
    """Проверки пакета, отфильтрованные по префиксам блоков (данные из config)."""
    from domain.qaqc import CHECKS                         # noqa: PLC0415
    if not blocks:
        return dict(CHECKS)
    pref = tuple(str(b) for b in blocks)
    return {cid: c for cid, c in CHECKS.items()
            if str(getattr(c, "block", "") or "").startswith(pref)}


def evaluate_all(values: Mapping[str, Any] | Any | None,
                 blocks: Iterable[str] | None = None) -> list[Slot]:
    """Матрица применимости по всем (или выбранным по блокам) проверкам пакета."""
    return [evaluate(check, values) for check in checks_for_blocks(blocks).values()]


def summarize(slots: Iterable[Slot]) -> dict:
    """Сводка матрицы: сколько применимо/провалено/неприменимо и с какими ключами."""
    from collections import Counter                        # noqa: PLC0415
    counts: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    by_block: dict[str, Counter[str]] = {}
    ids_failed: list[str] = []
    for slot in slots:
        counts[slot.state] += 1
        block = (slot.block or "")[:2]
        by_block.setdefault(block, Counter())[slot.state] += 1
        for key in slot.missing:
            missing[key] += 1
        if slot.state == FAILED and len(ids_failed) < 50:
            ids_failed.append(slot.check_id)
    return {
        "total": sum(counts.values()),
        "passed": counts.get(PASSED, 0),
        "failed": counts.get(FAILED, 0),
        "not_applicable": counts.get(NOT_APPLICABLE, 0),
        "by_block": {b: dict(c) for b, c in sorted(by_block.items())},
        "missing_keys": dict(missing.most_common(30)),
        "failed_checks": ids_failed,
    }
