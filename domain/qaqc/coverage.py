"""Матрица покрытия чеклиста ГПН: 6065 пунктов → implemented | not_applicable | unknown.

Смысл статусов (правило 6 «неизвестное ≠ ложь»):

``implemented``
    пункт формализован в пакете ``domain/qaqc`` И метрика вычислима: есть примитив,
    работающий по значениям модели, либо входной ключ объявлен в контракте
    ``ontology/qa_checks/model_keys.csv`` (в отличие от «слага», собранного из текста
    формулы). Статус НЕ означает «проверка пройдена».
``not_applicable`` + причина
    пункт формализован, но вычислимых входов нет: все метрики — ``direct``/``bool``
    по слагам (418 проверок пакета). Такая проверка во время прогона даёт
    ``not_applicable`` и модель НЕ штрафует.
``unknown`` + причина
    пункт не формализован: нет проверки в пакете (в том числе 7 шаблонов QC_* с
    качественным критерием, для которых вычислимая метрика не выдумывается).

Данные: ``ontology/qa_checks/checklist_index.csv`` (все 6065 пунктов),
``block_legend.csv`` (имена блоков), ``model_keys.csv`` (контракт ключей),
``domain/qaqc/checks.py`` (пакет) и ``checks_table.csv`` (оцифрованные проверки).

Если передан словарь значений модели, дополнительно считается РАНГ применимости
«здесь и сейчас» (через :mod:`domain.qc.values`) — отдельным ключом ``runtime``,
чтобы не смешивать формализацию с наличием данных.
"""
from __future__ import annotations

import collections
import csv
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
QA_DIR = ROOT / "ontology" / "qa_checks"
INDEX_CSV = QA_DIR / "checklist_index.csv"
LEGEND_CSV = QA_DIR / "block_legend.csv"
KEYS_CSV = QA_DIR / "model_keys.csv"
TABLE_CSV = ROOT / "domain" / "qaqc" / "checks_table.csv"
CONFIG_YAML = ROOT / "config.yaml"

STATUS_IMPLEMENTED = "implemented"
STATUS_NOT_APPLICABLE = "not_applicable"
STATUS_UNKNOWN = "unknown"

# статус БЛОКА выводится ИЗ ДАННЫХ (никогда не противоречит числам implemented/unknown)
BLOCK_IMPLEMENTED = "implemented"        # все пункты блока формализованы
BLOCK_PARTIAL = "partial"                # часть пунктов формализована
BLOCK_NOT_IMPLEMENTED = "not_implemented"  # ни один пункт не формализован

OUTSIDE_BLOCKS_REASON = ("вне 13 блоков ГПН (укрупнённый пункт / функция ТПУ / "
                         "историческое НИОКР / метакритик): построчного сопоставления "
                         "с проверками нет — экспертная проверка, требует сопоставления")

R_IMPLEMENTED = "R0"
R_SLUG = "R1"
R_UNFORMALIZED = "R2"
R_QUALITATIVE = "R3"
R_OUT_OF_SCOPE = "R4"

REASONS = {
    R_IMPLEMENTED: "формализовано: вычислимая метрика и объявленные входные ключи",
    R_SLUG: ("формализовано, но все метрики — direct/bool по слагу из формулы: "
             "вычислимых входов нет (прогон → not_applicable, модель не штрафуется)"),
    R_UNFORMALIZED: "не формализовано в коде/данных: проверки для пункта в пакете нет",
    R_QUALITATIVE: ("критерий не формализован в вычислимую метрику "
                    "(Способ выполнения = unknown); порог не выдумывается"),
    R_OUT_OF_SCOPE: ("вне согласованных блоков статической ГМ "
                     "(оценка неопределённостей / ГДМ / сейсмика / без блока)"),
}
# блоки чеклиста, входящие в согласованную область (fallback, если config недоступен)
DEFAULT_SCOPE = ("01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "13")


def _norm(text: str) -> str:
    return " ".join(str(text).replace("\xa0", " ").replace("ё", "е").split()).strip().lower()


def load_index() -> list[dict[str, str]]:
    with open(INDEX_CSV, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f, delimiter=";") if r.get("ID")]


def load_legend() -> dict[str, str]:
    with open(LEGEND_CSV, encoding="utf-8-sig", newline="") as f:
        return {r["Код"]: r["Полное имя блока чеклиста"]
                for r in csv.DictReader(f, delimiter=";") if r.get("Код")}


def load_model_keys() -> dict[str, dict[str, str]]:
    with open(KEYS_CSV, encoding="utf-8-sig", newline="") as f:
        return {r["Ключ"]: r for r in csv.DictReader(f, delimiter=";") if r.get("Ключ")}


def scope_blocks() -> tuple[str, ...]:
    """Блоки чеклиста из ДАННЫХ ``config.yaml → checks.package_blocks``."""
    try:
        import yaml  # noqa: PLC0415
        cfg = yaml.safe_load(CONFIG_YAML.read_text(encoding="utf-8")) or {}
        blocks = (cfg.get("checks") or {}).get("package_blocks") or {}
        out = sorted({str(b) for group in blocks.values() for b in (group or [])})
        return tuple(out) or DEFAULT_SCOPE
    except Exception:                                     # noqa: BLE001
        return DEFAULT_SCOPE


def package_checks() -> dict[str, Any]:
    from .checks import CHECKS                            # noqa: PLC0415
    return CHECKS


def described_only() -> dict[str, Any]:
    """Проверки с качественным критерием: в пакете описаны, вычислимой метрики нет."""
    try:
        from .checks import DESCRIBED_ONLY                # noqa: PLC0415
        return dict(DESCRIBED_ONLY)
    except ImportError:
        return {}


def block_status(slot: Mapping[str, Any]) -> str:
    """Статус блока ИЗ ЧИСЕЛ его пунктов (не противоречит им никогда)."""
    total = int(slot.get("total") or 0)
    impl = int(slot.get(STATUS_IMPLEMENTED) or 0)
    if total == 0 or impl == 0:
        return BLOCK_NOT_IMPLEMENTED
    if impl == total:
        return BLOCK_IMPLEMENTED
    return BLOCK_PARTIAL


def block_status_note(slot: Mapping[str, Any]) -> str:
    """Человекочитаемая причина статуса блока — согласована с числами."""
    total = int(slot.get("total") or 0)
    impl = int(slot.get(STATUS_IMPLEMENTED) or 0)
    na = int(slot.get(STATUS_NOT_APPLICABLE) or 0)
    unk = int(slot.get(STATUS_UNKNOWN) or 0)
    status = block_status(slot)
    head = {
        BLOCK_NOT_IMPLEMENTED: "нет ни одного пункта с вычислимой формализацией",
        BLOCK_IMPLEMENTED: "все пункты блока формализованы вычислимо",
        BLOCK_PARTIAL: "часть пунктов формализована вычислимо",
    }[status]
    return (f"{head}: implemented={impl} из {total} пунктов "
            f"(not_applicable={na}, unknown={unk})")


def is_computable(check: Any, declared: Mapping[str, Any], *, authored: bool = False) -> bool:
    """Есть ли метрика, вычислимая по значениям модели (не слаг).

    Для исторических 652 проверок признак — примитив, отличный от ``direct``/``bool``:
    их входные ключи собраны ИЗ ТЕКСТА формулы, поэтому совпадение имени ключа с
    контрактом ``model_keys.csv`` может быть случайным (B02-0163/SW, B04-0061/SILL,
    B04-0587/PERM) и «вычислимостью» не является. Для проверок, оцифрованных в
    ``ontology/qa_checks``, ключи авторские — они и есть контракт слоя значений.
    """
    for spec in getattr(check, "metrics", []) or []:
        if spec.kind not in ("direct", "bool"):
            return True
        if authored and spec.inputs and spec.inputs[0] in declared:
            return True
    return False


def _table_rows() -> list[dict[str, str]]:
    with open(TABLE_CSV, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f, delimiter=";") if r.get("ID")]


def _extra_id_map() -> dict[str, str]:
    """ID оцифрованных проверок, которых нет в чеклисте, → ID пункта чеклиста.

    Соответствие — ДАННЫЕ ``digitized_map.csv`` (собрано сопоставлением «Название»
    оцифрованной проверки с «Проверка» чеклиста; основание указано в каждой строке).
    Неоднозначные/несопоставленные остаются видны в отчёте (``extra_unmapped``).
    """
    path = QA_DIR / "digitized_map.csv"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["ID оцифрованной проверки"]: r["Пункт чеклиста"]
                for r in csv.DictReader(f, delimiter=";")
                if r.get("ID оцифрованной проверки")}


def build(values: Mapping[str, Any] | None = None, *,
          only_blocks: Iterable[str] | None = None) -> dict[str, Any]:
    """Собрать матрицу покрытия по всем пунктам чеклиста."""
    index = load_index()
    legend = load_legend()
    declared = load_model_keys()
    checks = package_checks()
    table = _table_rows()
    scope = tuple(only_blocks) if only_blocks else scope_blocks()
    authored = _ontology_ids()
    extra_map = _extra_id_map()
    point_to_check = {v: k for k, v in extra_map.items()}
    extra_unmapped = sorted({r["ID"] for r in table} - {r["ID"] for r in index}
                            - set(extra_map))

    # состояние каждой оцифрованной проверки: implemented / not_applicable
    check_state: dict[str, tuple[str, str]] = {}
    for cid, check in checks.items():
        if is_computable(check, declared, authored=cid in authored):
            check_state[cid] = (STATUS_IMPLEMENTED, R_IMPLEMENTED)
        else:
            check_state[cid] = (STATUS_NOT_APPLICABLE, R_SLUG)
    # QC_*-строки, оставшиеся неизвестными (критерий не формализован)
    described = described_only()
    qualitative = set(described) or {cid for cid in authored if cid not in checks}

    points: list[list[str]] = []
    by_block: dict[str, dict[str, Any]] = {}
    reason_count: collections.Counter[str] = collections.Counter()
    reason_examples: dict[str, list[str]] = collections.defaultdict(list)

    for row in index:
        cid, block = row["ID"], (row.get("Блок") or "").strip()
        code = block[:2] if re.match(r"^\d\d", block) else block
        if cid in check_state:
            status, reason = check_state[cid]
        else:
            mapped = point_to_check.get(cid)
            if mapped in check_state:
                status, reason = check_state[mapped]
            elif mapped:
                status, reason = STATUS_UNKNOWN, R_UNFORMALIZED
            elif code in scope:
                status, reason = STATUS_UNKNOWN, R_UNFORMALIZED
            else:
                status, reason = STATUS_UNKNOWN, R_OUT_OF_SCOPE
        if cid in qualitative:
            status, reason = STATUS_UNKNOWN, R_QUALITATIVE
        points.append([cid, code, status, reason])
        reason_count[reason] += 1
        if len(reason_examples[reason]) < 5:
            reason_examples[reason].append(cid)

    counts = collections.Counter(p[2] for p in points)
    for p in points:
        slot = by_block.setdefault(p[1], {"total": 0, STATUS_IMPLEMENTED: 0,
                                          STATUS_NOT_APPLICABLE: 0, STATUS_UNKNOWN: 0})
        slot["total"] += 1
        slot[p[2]] += 1
    for code, slot in by_block.items():
        slot["name"] = legend.get(code, code)
        slot["in_scope"] = code in scope
        slot["status"] = block_status(slot)
        slot["status_note"] = block_status_note(slot)

    outside = [p for p in points if p[1] not in legend]
    type_by_id = {r["ID"]: (r.get("Тип записи") or "").strip() for r in index}
    outside_by_type: collections.Counter[str] = collections.Counter(
        type_by_id.get(p[0], "") for p in outside)

    report: dict[str, Any] = {
        "schema": 2,
        "source": ("QAQC/QA_QC_чеклист.xlsx → ontology/qa_checks/checklist_index.csv, "
                   "ontology/qa_checks/bNN.csv, domain/qaqc/checks_table.csv"),
        "total": len(points),
        "scope_blocks": list(scope),
        "by_status": {k: counts.get(k, 0) for k in
                      (STATUS_IMPLEMENTED, STATUS_NOT_APPLICABLE, STATUS_UNKNOWN)},
        "by_block": {k: by_block[k] for k in sorted(by_block)},
        "reasons": [{"code": code, "text": REASONS[code], "count": reason_count.get(code, 0),
                     "examples": reason_examples.get(code, [])}
                    for code in (R_IMPLEMENTED, R_SLUG, R_QUALITATIVE,
                                 R_UNFORMALIZED, R_OUT_OF_SCOPE)],
        "packages": {
            "checks_total": len(checks),
            "checks_implemented": sum(1 for v in check_state.values()
                                      if v[0] == STATUS_IMPLEMENTED),
            "checks_not_applicable": sum(1 for v in check_state.values()
                                         if v[0] == STATUS_NOT_APPLICABLE),
            "checks_from_ontology_csv": len(authored),
            "checks_from_ontology_unknown": len(qualitative),
            "checks_described_only": sorted(qualitative),
            "digitized_rows": len(table),
            "extra_unmapped": extra_unmapped,
        },
        "notes": [
            "by_block — атрибуция ПУНКТОВ по блоку чеклиста (не по гейту).",
            "QC_PHYS_001/002/003/005/006 в чеклисте лежат в блоке 11 "
            "(оценка неопределённостей), а в пакет отнесены к блоку 13 "
            "(G-PETRO, config.yaml → checks.package_blocks): в by_block они видны "
            "в блоке 11, в файле ontology/qa_checks/b13.csv — как проверки блока 13.",
            "Статус implemented означает ФОРМАЛИЗАЦИЮ (вычислимая метрика и "
            "объявленные ключи), а не пройденную проверку: ранга применимости "
            "«здесь и сейчас» считается отдельно (runtime) и требует данных модели.",
        ],
        "keys_contract": {
            "declared": len(declared),
            "by_state": dict(collections.Counter(
                str(v.get("Состояние") or "?") for v in declared.values())),
        },
        "meta": {
            "block_status_rule": ("статус блока считается ИЗ ДАННЫХ: implemented == 0 → "
                                  "not_implemented; implemented == total → implemented; "
                                  "иначе partial. Числа implemented/not_applicable/unknown "
                                  "в блоке всегда согласованы со статусом"),
            "summary_rule": ("by_status — только implemented/not_applicable/unknown, "
                             "сумма = total (6065). Статуса «passed»/«failed» у пункта "
                             "чеклиста нет: implemented = формализовано, не «пройдено»"),
            "items_outside_blocks": {
                "total": len(outside),
                "status": STATUS_UNKNOWN,
                "reason_code": R_OUT_OF_SCOPE,
                "reason": OUTSIDE_BLOCKS_REASON,
                "by_type": dict(outside_by_type),
                "columns": ["ID", "Статус", "Причина"],
                "items": [[p[0], p[2], p[3]] for p in outside],
            },
        },
        "point_columns": ["ID", "Блок", "Статус", "Причина"],
        "points": points,
    }
    if values is not None:
        report["runtime"] = runtime_rank(values)
    return report


def _ontology_ids() -> set[str]:
    ids: set[str] = set()
    for path in sorted(QA_DIR.glob("b[0-9][0-9].csv")):
        with open(path, encoding="utf-8-sig", newline="") as f:
            ids |= {r["ID"] for r in csv.DictReader(f, delimiter=";") if r.get("ID")}
    return ids


def runtime_rank(values: Mapping[str, Any]) -> dict[str, Any]:
    """Ранг применимости «здесь и сейчас» по фактическим значениям модели."""
    from domain.qc import values as val                   # noqa: PLC0415
    slots = val.evaluate_all(values)
    counted = collections.Counter(s.state for s in slots)
    return {
        "provided_keys": sorted(val.provided_keys(values)),
        "checks_total": len(slots),
        "by_state": dict(counted),
        "not_applicable_checks": [s.check_id for s in slots
                                  if s.state == val.NOT_APPLICABLE][:50],
    }


def write(path: Path | str | None = None,
          values: Mapping[str, Any] | None = None) -> Path:
    """Записать матрицу покрытия в JSON (по умолчанию ``domain/qaqc/qaqc_coverage.json``)."""
    import json                                           # noqa: PLC0415
    out = Path(path) if path else ROOT / "domain" / "qaqc" / "qaqc_coverage.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(values), ensure_ascii=False, indent=1), encoding="utf-8")
    return out
