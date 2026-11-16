"""Контракт проверок гейта и реестр исполнения.

Каждая проверка — чистая функция ``(evidence, ctx) -> Finding | None``:
  * ``None`` — проверка НЕ ПРИМЕНИМА (нет данных): модель не штрафуется;
  * ``Finding`` — результат (passed/failed) с серьёзностью и свидетельством.

``ctx`` несёт данные конфигурации/проекта (пороги, порядок маркеров), которые
нужны проверке, но не являются «свидетельствами» этапа.

Проверки с ``gate == "*"`` (контрактные) выполняются для любого гейта.

Реестр собирается ИЗ ДАННЫХ (:meth:`CheckRegistry.from_data`), без списков в коде:

* **builtin/contract** — функции регистрируются кодом (``builtin.py``/``contract.py``);
* **package** — 652 оцифрованные проверки ``domain/qaqc/checks_table.csv``; гейт каждой
  берётся из данных ``ontology/qa_gate_map.yaml`` (блок → гейты, обратный индекс
  ``checks.package_blocks``); исполнение — через доменный движок ``domain/qaqc``;
* **csv** — новые проверки ``ontology/qa_checks/*.csv`` (колонки 1:1 как в
  ``checks_table.csv``): «Способ выполнения» = имя примитива СХЕМЫ, «Порог» = машинный
  порог (клаузы через ``;``), «Входные ключи» = ключи значений.

Принципы (правило 6 «неизвестное ≠ ложь»):

* нет каталога/CSV/пакета — реестр не падает, проверки просто не появляются
  (``unknown`` с причиной, а не ``failed``);
* нет входных ключей у проверки — ``not_applicable`` (модель не штрафуется);
* непарсибельный порог/неизвестный примитив — проверка регистрируется с
  ``unknown_reason`` и в прогон не идёт (``unknown``, не ``failed``).
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable

from agents.contracts import Finding

CheckFunc = Callable[[dict, dict], "Finding | None"]

# --- пути данных (имена файлов, не домен) ---------------------------------------
SERVICE_ROOT = Path(__file__).resolve().parents[2]
GATE_MAP_FILE = "ontology/qa_gate_map.yaml"
ONTOLOGY_CHECKS_DIR = "ontology/qa_checks"
PACKAGE_TABLE = "domain/qaqc/checks_table.csv"

# --- состояния проверки ----------------------------------------------------------
PASSED = "passed"
FAILED = "failed"
NOT_APPLICABLE = "not_applicable"
UNKNOWN = "unknown"
PENDING = "pending"
# «Результат не проверен»: свидетельства нет. Гейт не станет passed (F-19),
# но и не падает — отсутствие данных не провал модели (правило 6).
UNVERIFIED = "unverified"

STATES = (PASSED, FAILED, NOT_APPLICABLE, UNKNOWN, PENDING, UNVERIFIED)


@dataclass(frozen=True)
class CheckSpec:
    """Описание проверки: кто владелец, серьёзность, когда применима."""

    id: str
    gate: str
    severity: str              # critical | major | minor
    title: str
    func: CheckFunc
    remediation: str = ""
    runtime: bool = False      # требует реального прогона тНава (в dry-run пропускается)
    source: str = "builtin"    # builtin | contract | package | csv
    gates: tuple[str, ...] = ()       # все гейты проверки (данные qa_gate_map)
    description: str = ""
    inputs: tuple[str, ...] = ()      # ключи значений, нужные проверке (данные CSV)
    threshold: str = ""               # машинный порог как в данных
    formula: str = ""
    unknown_reason: str = ""          # непусто — проверка НЕ исполняется (unknown)
    block: str = ""                   # код блока чеклиста (первые 2 символа)
    fitness: bool = False             # участие в kq (данные «Используется критерием критика»)

    def to_dict(self) -> dict:
        return {"id": self.id, "gate": self.gate, "gates": list(self.gates),
                "severity": self.severity, "title": self.title, "source": self.source,
                "runtime": self.runtime, "inputs": list(self.inputs),
                "threshold": self.threshold, "formula": self.formula,
                "unknown_reason": self.unknown_reason, "block": self.block,
                "fitness": self.fitness, "remediation": self.remediation}


@dataclass
class CheckOutcome:
    """Результат одной проверки с состоянием и причиной (для покрытия QA/QC)."""

    id: str
    gate: str
    source: str
    state: str = UNKNOWN              # passed | failed | not_applicable | unknown | pending
    severity: str = ""
    reason: str = ""
    finding: Finding | None = None

    def to_dict(self) -> dict:
        return {"id": self.id, "gate": self.gate, "source": self.source,
                "state": self.state, "severity": self.severity, "reason": self.reason}


@dataclass
class RunReport:
    """Итог прогона проверок гейта: находки + состояния (включая неприменимые)."""

    outcomes: list[CheckOutcome] = field(default_factory=list)

    @property
    def findings(self) -> list[Finding]:
        return [o.finding for o in self.outcomes if o.finding is not None]

    def counts(self) -> dict:
        out = {s: 0 for s in STATES}
        for o in self.outcomes:
            out[o.state] = out.get(o.state, 0) + 1
        out["total"] = len(self.outcomes)
        return out

    def by_state(self, state: str) -> list[CheckOutcome]:
        return [o for o in self.outcomes if o.state == state]

    def to_dict(self) -> dict:
        return {"counts": self.counts(),
                "outcomes": [o.to_dict() for o in self.outcomes]}


# --- каталог проверок из данных ---------------------------------------------------
@dataclass(frozen=True)
class CheckCatalogRow:
    """Строка каталога оцифрованных проверок (данные, не код)."""

    id: str
    block: str
    title: str
    method: str
    threshold: str
    inputs: tuple[str, ...]
    significance: float | None
    formula: str = ""
    criterion: str = ""
    fitness: bool = False
    source: str = "package"
    malformed: str = ""        # строка битая (полей больше, чем в шапке) → unknown

    @property
    def block_code(self) -> str:
        return (self.block or "")[:2]


_COLUMN_ALIASES = {
    "id": ("id", "ид", "id проверки", "id проверки / пункта"),
    "block": ("блок", "block", "область", "обязательная область гпн / блок"),
    "title": ("название", "title", "проверка", "имя"),
    "method": ("способ выполнения", "метод", "method", "формула вычисления"),
    "threshold": ("порог", "threshold", "критерий прохождения"),
    "inputs": ("входные ключи", "входные данные", "inputs"),
    "significance": ("значимость", "вес", "вес [0…1]", "вес [0...1]"),
    "formula": ("формула", "метод / формула"),
    "criterion": ("критерий",),
    "fitness": ("используется критерием критика", "fitness", "фитнес"),
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _column_map(header: Iterable[str]) -> dict[str, str]:
    """Сопоставить колонки CSV схеме реестра (регистронезависимо, по алиасам)."""
    out: dict[str, str] = {}
    for raw in header:
        key = _norm(raw)
        for field_name, aliases in _COLUMN_ALIASES.items():
            if field_name in out:
                continue
            if any(key == _norm(a) or key.startswith(_norm(a)) for a in aliases):
                out[field_name] = raw
                break
    return out


def _split_keys(value: str) -> tuple[str, ...]:
    for sep in (";", "|"):
        value = str(value or "").replace(sep, ",")
    return tuple(tok.strip() for tok in value.split(",") if tok.strip())


def _detect_delimiter(first_line: str) -> str:
    """Разделитель по СТРОКЕ ЗАГОЛОВКА (а не по содержимому файла)."""
    return ";" if first_line.count(";") >= max(first_line.count(","), 1) else ","


def _read_catalog_file(path: Path, source: str) -> list[CheckCatalogRow]:
    """Прочитать CSV-каталог проверок; битые/чужие файлы пропускаются (не падаем).

    Файл считается каталогом ПРОВЕРОК, только если его шапка несёт схему проверки
    (``ID`` + хотя бы одно из: способ выполнения / порог / входные ключи / формула).
    Файлы-индексы (``checklist_index.csv``, легенды, справочники ключей) игнорируются:
    это данные покрытия, а не проверки.
    """
    if not path.is_file():
        return []
    rows: list[CheckCatalogRow] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            first = fh.readline()
            if not first:
                return []
            fh.seek(0)
            reader = csv.DictReader(fh, delimiter=_detect_delimiter(first),
                                    restkey="_extra_")
            cmap = _column_map(reader.fieldnames or [])
            if "id" not in cmap or not any(k in cmap for k in
                                           ("method", "threshold", "inputs", "formula")):
                return []
            for raw in reader:
                cid = str(raw.get(cmap["id"]) or "").strip()
                if not cid:
                    continue
                extra = raw.get("_extra_") or []
                malformed = ("" if not extra else
                             f"строка CSV содержит {len(extra)} лишних полей "
                             f"(неэкранированный разделитель в значении) — разбор невозможен")
                sig_raw = str(raw.get(cmap.get("significance", ""), "") or "").strip()
                try:
                    significance = float(sig_raw.replace(",", ".")) if sig_raw else None
                except ValueError:
                    significance = None
                fit_raw = _norm(raw.get(cmap.get("fitness", ""), ""))
                rows.append(CheckCatalogRow(
                    id=cid,
                    block=str(raw.get(cmap.get("block", ""), "") or "").strip(),
                    title=str(raw.get(cmap.get("title", ""), "") or "").strip(),
                    method=str(raw.get(cmap.get("method", ""), "") or "").strip(),
                    threshold=str(raw.get(cmap.get("threshold", ""), "") or "").strip(),
                    inputs=_split_keys(raw.get(cmap.get("inputs", ""), "")),
                    significance=significance,
                    formula=str(raw.get(cmap.get("formula", ""), "") or "").strip(),
                    criterion=str(raw.get(cmap.get("criterion", ""), "") or "").strip(),
                    fitness=fit_raw in ("да", "yes", "true", "1", "+"),
                    source=source,
                    malformed=malformed,
                ))
    except OSError:
        return []
    return rows


def package_fitness(check_id: str, fallback: bool) -> bool:
    """Флаг участия в kq для проверки ПАКЕТА — из доменного движка (авторитет).

    Таблица ``checks_table.csv`` и сгенерированные ``domain/qaqc`` описания могут
    расходиться; сверка идёт по тому же признаку, что и ``qaqc_adapter``
    (``fitness_function == 'да'``), чтобы kq/kc в отчёте не разъезжались.
    """
    try:
        from domain import qaqc as _qaqc
    except Exception:                              # noqa: BLE001
        return fallback
    check = (getattr(_qaqc, "CHECKS", None) or {}).get(check_id)
    if check is None:
        return fallback
    return str(getattr(check, "fitness_function", "")).strip().lower() == "да"


def load_check_catalog(root: Path, *, include_package: bool = True,
                       include_csv: bool = True) -> list[CheckCatalogRow]:
    """Каталог оцифрованных проверок: пакет ``domain/qaqc`` + ``ontology/qa_checks/*.csv``.

    Дубликаты по ID отбрасываются (первым идёт пакет) — двойного штрафа нет.
    """
    rows: list[CheckCatalogRow] = []
    if include_package:
        rows += _read_catalog_file(root / PACKAGE_TABLE, "package")
    if include_csv:
        checks_dir = root / ONTOLOGY_CHECKS_DIR
        if checks_dir.is_dir():
            for path in sorted(checks_dir.glob("*.csv")):
                rows += _read_catalog_file(path, "csv")
    seen: set[str] = set()
    out: list[CheckCatalogRow] = []
    for row in rows:
        if row.id in seen:
            continue
        seen.add(row.id)
        if row.source == "package":
            row = replace(row, fitness=package_fitness(row.id, row.fitness))
        out.append(row)
    return out


def load_gate_map(cfg=None, *, root: Path | None = None) -> dict:
    """Данные ``ontology/qa_gate_map.yaml`` (блок → гейт/агент/severity); нет файла → {}."""
    base = Path(root) if root is not None else _service_root(cfg)
    rel = GATE_MAP_FILE
    if cfg is not None and hasattr(cfg, "get"):
        rel = str(cfg.get("checks.qa_gate_map", GATE_MAP_FILE) or GATE_MAP_FILE)
    path = Path(rel)
    if not path.is_absolute():
        path = base / path
    if not path.is_file():
        return {}
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:                              # noqa: BLE001 — данные опциональны
        return {}
    return data if isinstance(data, dict) else {}


def _service_root(cfg) -> Path:
    if cfg is not None:
        src = getattr(cfg, "source_path", None)
        if src:
            return Path(src).resolve().parent
    return SERVICE_ROOT


def blocks_by_gate(gate_map: dict) -> dict[str, tuple[str, ...]]:
    """Обратный индекс «гейт → блоки» из данных карты (без списков в коде)."""
    out: dict[str, list[str]] = {}
    for code, info in (gate_map.get("blocks") or {}).items():
        for gate in (info or {}).get("gates") or []:
            out.setdefault(str(gate), []).append(str(code))
    return {g: tuple(sorted(set(b))) for g, b in out.items()}


def gates_by_block(gate_map: dict) -> dict[str, tuple[str, ...]]:
    """Индекс «блок → гейты» из данных карты."""
    return {str(code): tuple(str(g) for g in ((info or {}).get("gates") or []))
            for code, info in (gate_map.get("blocks") or {}).items()}


def severity_levels(gate_map: dict) -> tuple[float, float]:
    """Пороги значимости для severity (данные ``severity_levels``; дефолт 0.9/0.75)."""
    levels = gate_map.get("severity_levels") or {}
    try:
        return float(levels.get("critical", 0.9)), float(levels.get("major", 0.75))
    except (TypeError, ValueError):
        return 0.9, 0.75


def severity_for(significance: float | None, levels: tuple[float, float]) -> str:
    """Значимость → серьёзность (данные ``severity_levels``)."""
    if significance is None:
        return "major"
    critical, major = levels
    if significance >= critical:
        return "critical"
    if significance >= major:
        return "major"
    return "minor"


# --- парсер машинного порога (схема, не домен) -------------------------------------
_NUM = r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?"
_OP_SYMBOLS = (">=", "=>", "<=", "=<", "==", "!=", ">", "<", "=")
_SYMBOL_TO_OP = {">=": "ge", "=>": "ge", "<=": "le", "=<": "le", "==": "eq",
                 "!=": "ne", ">": "gt", "<": "lt", "=": "eq"}


def _normalize_threshold_text(text: str) -> str:
    """Unicode-операторы и разделители → ASCII (данные приходят из Excel)."""
    out = str(text or "")
    for src, dst in (("≤", "<="), ("≥", ">="), ("≠", "!="), ("−", "-"), ("–", "-"),
                     ("—", "-"), ("\u00a0", " ")):
        out = out.replace(src, dst)
    return out.strip()


def parse_threshold(text: str):
    """Строка порога → (Threshold | None, причина).

    Поддержано: ``<= 5%``, ``>= 0.7``, ``< 1``, ``= 0``, ``in [0.01, 0.50]``,
    ``bool_true``/``bool_false``, а также форма с именем метрики впереди
    (``Nugget <= 0.1``): имя игнорируется — соответствие клаузы ключу задаёт порядок
    в «Входные ключи». Не распознано → (None, причина) — это ``unknown``.
    """
    try:
        from domain.qaqc.model import Threshold
    except Exception:                              # noqa: BLE001
        return None, "движок порогов domain/qaqc недоступен"
    raw = _normalize_threshold_text(text)
    low = raw.lower()
    if not low:
        return None, "порог не задан"
    if low in ("bool_true", "true", "да"):
        return Threshold(op="bool_true", raw=raw), ""
    if low in ("bool_false", "false", "нет"):
        return Threshold(op="bool_false", raw=raw), ""
    m = re.search(rf"in\s*[\[(]\s*({_NUM})\s*[,;]\s*({_NUM})\s*[\])]", low)
    if m:
        lo = float(m.group(1).replace(",", "."))
        hi = float(m.group(2).replace(",", "."))
        return Threshold(op="between", lo=lo, hi=hi, raw=raw), ""
    m = re.search(rf"({'|'.join(re.escape(s) for s in _OP_SYMBOLS)})\s*({_NUM})\s*(%?)",
                  low)
    if not m:
        return None, f"не распознан порог: {raw!r}"
    op = _SYMBOL_TO_OP[m.group(1)]
    percent = bool(m.group(3))
    value = float(m.group(2).replace(",", "."))
    if percent:
        value = value / 100.0
    return Threshold(op=op, value=value, is_percent=percent, raw=raw), ""


def split_thresholds(text: str) -> list[str]:
    """Клаузы порога: ``"Nugget <= 0.1; Range >= 500"`` → две клаузы.

    Разделители — ``;`` и ``|``; в CSV-описании, где ``;`` разделяет КОЛОНКИ, для
    клауз следует брать ``|`` (иначе строка «съезжает» — см. ``malformed``).
    """
    return [p.strip() for p in re.split(r"[;|]", str(text or "")) if p.strip()]


# --- значения для проверок из данных -----------------------------------------------
VALUES_KEYS = ("values", "qaqc_values")


def resolve_values(ev: dict, ctx: dict) -> dict:
    """Значения для data-проверок: контейнер значений + плоские скалярные свидетельства."""
    out: dict = {}
    for src in (ctx or {}, ev or {}):
        for key in VALUES_KEYS:
            node = src.get(key)
            if isinstance(node, dict):
                out.update(node)
    for key, value in (ev or {}).items():
        if key in VALUES_KEYS or key == "handoff":
            continue
        if isinstance(value, (int, float, list, tuple)):
            out.setdefault(key, value)
    return out


def missing_keys(spec_inputs: Iterable[str], values: dict) -> list[str]:
    """Ключи, которых нет в значениях (регистр не важен)."""
    have = {str(k).lower() for k in values}
    return [k for k in spec_inputs if str(k).lower() not in have]


def _scalar(value):
    try:
        import numpy as np
        if isinstance(value, (list, tuple, np.ndarray)):
            arr = np.asarray(value, dtype=float)
            return float("nan") if arr.size == 0 else float(np.nanmean(arr))
    except Exception:                              # noqa: BLE001
        pass    # список без numpy/битые данные → скалярный фолбэк НИЖЕ (не потеря значения)
    if isinstance(value, (list, tuple)):
        return float(value[0]) if value else float("nan")
    return float(value)


def _primitive(name: str):
    """Примитив СХЕМЫ из доменного движка; None — не найден (→ unknown)."""
    try:
        from domain.qaqc.engine import PRIMITIVES
    except Exception:                              # noqa: BLE001
        return None
    return PRIMITIVES.get(str(name or "").strip())


def validate_catalog_row(row: CheckCatalogRow) -> tuple[bool, str]:
    """Проверить СХЕМУ CSV-описания проверки (до данных): (ok, причина).

    Порядок важен: неисправная схема (битая строка, неизвестный примитив,
    непарсибельный порог) — это ``unknown``, а не ``not_applicable``: отсутствие
    данных не должно маскировать дефект данных. Применяется только к
    ``source == 'csv'`` (там CSV — сама схема); у пакета схема структурирована в
    ``domain/qaqc``.
    """
    if row.malformed:
        return False, row.malformed
    method = (row.method or "direct").strip().lower()
    if method not in ("direct", "bool", "значение") and _primitive(method) is None:
        return False, (f"примитив «{row.method or '—'}» не найден в схеме движка "
                       "(колонка «Способ выполнения»)")
    clauses = split_thresholds(row.threshold)
    if not clauses:
        return False, "порог не задан (колонка «Порог» пуста) — суждение невозможно"
    for clause in clauses:
        _th, why = parse_threshold(clause)
        if _th is None:
            return False, why
    if len(clauses) not in (1, len(row.inputs)):
        return False, (f"клауз порога {len(clauses)} ≠ 1 и ≠ числу входных ключей "
                       f"{len(row.inputs)} — соответствие не определено")
    return True, ""


def evaluate_catalog_check(row: CheckCatalogRow, values: dict) -> tuple[str, str]:
    """Вычислить CSV-описанную проверку: (state, reason).

    Каждая клауза порога = отдельная метрика: при числе клауз, равном числу входных
    ключей, метрика берётся по своему ключу; одна клауза — по всем ключам примитива.
    """
    missing = missing_keys(row.inputs, values)
    if missing:
        return NOT_APPLICABLE, f"нет входных данных: {', '.join(missing)}"
    method = (row.method or "direct").strip().lower()
    if method in ("direct", "bool", "значение"):
        prim = None
    else:
        prim = _primitive(method)
        if prim is None:
            return UNKNOWN, f"примитив «{row.method}» не найден в схеме движка"
    clauses = split_thresholds(row.threshold)
    if not clauses:
        return UNKNOWN, "порог не задан — суждение невозможно"
    thresholds = []
    for clause in clauses:
        th, why = parse_threshold(clause)
        if th is None:
            return UNKNOWN, why
        thresholds.append(th)
    pairs: list[tuple[object, object]]
    if len(thresholds) == 1:
        pairs = [(_metric_value(prim, row.inputs, values), thresholds[0])]
    elif len(thresholds) == len(row.inputs):
        pairs = [(_metric_value(prim, (key,), values), th)
                 for key, th in zip(row.inputs, thresholds)]
    else:
        return UNKNOWN, (f"клауз порога {len(thresholds)} ≠ числу ключей {len(row.inputs)} "
                         "— соответствие не определено")
    failed: list[str] = []
    from domain.qaqc.engine import compare
    for value, th in pairs:
        if value is None:
            return NOT_APPLICABLE, "значение не вычислилось (нет данных)"
        try:
            ok = compare(value, th)
        except Exception as exc:                   # noqa: BLE001
            return UNKNOWN, f"ошибка сравнения: {exc}"
        if not ok:
            failed.append(f"{value:g} вне {th.describe()}")
    if failed:
        return FAILED, "; ".join(failed[:3])
    return PASSED, ""


def _metric_value(prim, keys: tuple[str, ...], values: dict):
    """Значение метрики: примитив схемы по ключам либо прямое значение ключа."""
    lookup = {str(k).lower(): v for k, v in values.items()}
    args = [lookup[str(k).lower()] for k in keys]
    try:
        if prim is None:
            if len(args) != 1:
                return None
            return _scalar(args[0])
        import numpy as np
        return float(prim(*[np.asarray(a, dtype=float) for a in args]))
    except Exception:                              # noqa: BLE001
        return None


_DESCRIBED_ONLY_CACHE: set[str] | None = None


def described_only_ids() -> set[str]:
    """ID проверок, у которых есть ОПИСАНИЕ, но нет исполнителя (данные пакета).

    ``domain/qaqc.DESCRIBED_ONLY`` — авторитетный перечень (критерий качественный,
    вычислимой метрики нет). Такие проверки обязаны быть ``unknown``, а не ``passed``:
    проверка без метрик в движке дала бы «прошло» без суждения (правило 6).
    Пакет недоступен → пусто (неудачу не кэшируем: пакет может появиться позже).
    """
    global _DESCRIBED_ONLY_CACHE
    if _DESCRIBED_ONLY_CACHE is None:
        try:
            from domain import qaqc as _qaqc
        except Exception:                          # noqa: BLE001
            return set()
        _DESCRIBED_ONLY_CACHE = set((getattr(_qaqc, "DESCRIBED_ONLY", None) or {}).keys())
    return _DESCRIBED_ONLY_CACHE


def _not_executable_reason(check_id: str) -> str:
    if check_id in described_only_ids():
        return ("описание есть, исполнимой проверки нет (domain/qaqc.DESCRIBED_ONLY) — "
                "unknown, не провал модели")
    return "проверка не реализована в движке domain/qaqc"


class _DataCheck:
    """Исполняемая data-проверка (пакет/CSV): возвращает Finding|None и помнит состояние."""

    def __init__(self, row: CheckCatalogRow, severity: str, *, engine: str) -> None:
        self.row = row
        self.severity = severity
        self.engine = engine        # package | csv
        self.reason = ""            # причина последнего состояния
        self.state = ""             # passed | failed | not_applicable | unknown

    def __call__(self, ev: dict, ctx: dict) -> Finding | None:
        self.reason = ""
        self.state = ""
        state, why = self._run(resolve_values(ev, ctx))
        self.state, self.reason = state, why
        if state in (NOT_APPLICABLE, UNKNOWN):
            return None
        return Finding(id=self.row.id, severity=self.severity, passed=(state == PASSED),
                       title=self.row.title[:160] or self.row.id,
                       message=("" if state == PASSED else why)[:200],
                       source="package" if self.engine == "package" else "csv",
                       remediation=self.row.criterion[:200],
                       evidence={"block": self.row.block[:60], "formula": self.row.formula[:200]})

    def _run(self, values: dict) -> tuple[str, str]:
        if self.row.malformed:
            return UNKNOWN, self.row.malformed
        if self.engine == "csv":
            ok, why = validate_catalog_row(self.row)
            if not ok:
                return UNKNOWN, why
            return evaluate_catalog_check(self.row, values)
        return self._run_package(values)

    def _run_package(self, values: dict) -> tuple[str, str]:
        """Исполнение проверки пакета доменным движком — решение принимает ДВИЖОК.

        Своей проверки входных ключей здесь НЕТ намеренно: иначе сводка верхнего
        уровня могла бы разойтись с ``domain/qaqc_adapter`` (тот же движок, та же
        классификация «missing data / error computing → not_applicable»).
        """
        try:
            from domain import qaqc as _qaqc
        except Exception:                          # noqa: BLE001
            return UNKNOWN, "пакет domain/qaqc недоступен"
        try:
            result = _qaqc.run_check(self.row.id, _qaqc.DataContext(**values))
        except KeyError as exc:
            if "unknown check id" in str(exc):
                return UNKNOWN, _not_executable_reason(self.row.id)
            return NOT_APPLICABLE, f"нет входных данных: {exc}"
        except Exception as exc:                   # noqa: BLE001
            return UNKNOWN, f"ошибка вычисления: {exc}"
        if result.passed:
            return PASSED, ""
        text = (result.message or "").lower()
        if "missing data" in text or "error computing" in text:
            return NOT_APPLICABLE, (result.message or "")[:160]
        return FAILED, (result.message or "критерий не выполнен")[:160]


def context_names(cfg) -> dict:
    """Имена объектов для текстов проверок — ИЗ ДАННЫХ (в коде только ключи).

    ``checks.properties`` (роль → ``{cube, mean_key}``) и ``ensemble.metric``
    попадают в контекст проверок, поэтому сообщения/заголовки не несут доменных
    значений (правило 1): нет данных — проверка использует нейтральное описание.
    """
    out: dict = {}
    if cfg is None or not hasattr(cfg, "get"):
        return out
    props = cfg.get("checks.properties")
    if isinstance(props, dict):
        out["properties"] = {str(k): dict(v) for k, v in props.items()
                             if isinstance(v, dict)}
    metric = cfg.get("ensemble.metric")
    if metric:
        out["metric_name"] = str(metric)
    return out


class CheckRegistry:
    """Выборка проверок по гейту и исполнение по свидетельствам."""

    def __init__(self, checks: list[CheckSpec] | None = None, *,
                 names: dict | None = None) -> None:
        if checks is None:
            checks = code_checks()
        self._checks = list(checks)
        self._names = dict(names or {})
        self._gate_map_cache: dict | None = None

    def _ctx(self, ctx: dict | None) -> dict:
        """Контекст проверок: имена из данных (слабый слой) + переданный ctx."""
        if not self._names:
            return dict(ctx or {})
        merged = dict(self._names)
        merged.update(ctx or {})
        return merged

    # -- серьёзность: спецификация (данные) важнее тела проверки -------------------
    @staticmethod
    def _severity(finding: Finding | None, spec: CheckSpec) -> Finding | None:
        """Привести серьёзность находки к уровню ИЗ ДАННЫХ (спецификации).

        Без этого `checks.check_severity` не влиял бы на вердикт: функция проставляет
        свой уровень при создании находки, а источники истины — данные.
        """
        if finding is None or finding.severity == spec.severity:
            return finding
        return replace(finding, severity=spec.severity)

    # -- сборка ИЗ ДАННЫХ ---------------------------------------------------------
    @classmethod
    def from_data(cls, cfg=None, *, root: Path | None = None,
                  include_package: bool = True, include_csv: bool = True,
                  gate_map: dict | None = None) -> "CheckRegistry":
        """Реестр = код (builtin/contract) + пакет (блоки из данных) + CSV-описания.

        Пустой/отсутствующий каталог или CSV — не ошибка: реестр остаётся рабочим.
        """
        base = Path(root) if root is not None else _service_root(cfg)
        data = gate_map if gate_map is not None else load_gate_map(cfg, root=base)
        return cls(build_data_checks(base, cfg=cfg, gate_map=data,
                                     include_package=include_package,
                                     include_csv=include_csv),
                   names=context_names(cfg))

    # Обратная совместимость: имя из задания.
    from_config = from_data

    def all(self) -> list[CheckSpec]:
        return list(self._checks)

    def for_gate(self, gate_id: str) -> list[CheckSpec]:
        return [c for c in self._checks
                if c.gate in (gate_id, "*") or gate_id in (c.gates or ())]

    def run(self, gate_id: str, evidence: dict, ctx: dict | None = None, *,
            include_runtime: bool = True) -> list[Finding]:
        """Исполнить применимые проверки гейта; неприменимые пропускаются."""
        out: list[Finding] = []
        ctx = self._ctx(ctx)
        for spec in self.for_gate(gate_id):
            if spec.runtime and not include_runtime:
                continue
            try:
                finding = self._severity(spec.func(evidence or {}, ctx), spec)
            except Exception as exc:      # noqa: BLE001 — проверка не роняет прогон
                finding = Finding(id=spec.id, severity=spec.severity, passed=False,
                                  title=spec.title, message=f"ошибка вычисления: {exc}",
                                  source=spec.source, remediation=spec.remediation)
            if finding is not None:
                out.append(finding)
        return out

    def run_report(self, gate_id: str, evidence: dict, ctx: dict | None = None, *,
                   include_runtime: bool = True) -> RunReport:
        """Полный итог гейта: состояния passed/failed/not_applicable/unknown/pending."""
        ctx = self._ctx(ctx)
        report = RunReport()
        for spec in self.for_gate(gate_id):
            if spec.runtime and not include_runtime:
                report.outcomes.append(CheckOutcome(
                    id=spec.id, gate=gate_id, source=spec.source, state=PENDING,
                    severity=spec.severity, reason="dry-run: runtime-проверка не выполнялась"))
                continue
            if spec.unknown_reason:
                report.outcomes.append(CheckOutcome(
                    id=spec.id, gate=gate_id, source=spec.source, state=UNKNOWN,
                    severity=spec.severity, reason=spec.unknown_reason))
                continue
            try:
                finding = self._severity(spec.func(evidence or {}, ctx), spec)
            except Exception as exc:      # noqa: BLE001
                report.outcomes.append(CheckOutcome(
                    id=spec.id, gate=gate_id, source=spec.source, state=FAILED,
                    severity=spec.severity, reason=f"ошибка вычисления: {exc}",
                    finding=Finding(id=spec.id, severity=spec.severity, passed=False,
                                    title=spec.title, source=spec.source,
                                    message=f"ошибка вычисления: {exc}")))
                continue
            reason = str(getattr(spec.func, "reason", "") or "")
            state = str(getattr(spec.func, "state", "") or "")
            if finding is None:
                report.outcomes.append(CheckOutcome(
                    id=spec.id, gate=gate_id, source=spec.source,
                    state=(state if state in (NOT_APPLICABLE, UNKNOWN) else NOT_APPLICABLE),
                    severity=spec.severity,
                    reason=reason or "нет данных для суждения"))
                continue
            report.outcomes.append(CheckOutcome(
                id=spec.id, gate=gate_id, source=spec.source,
                state=((UNVERIFIED if finding.state == UNVERIFIED else
                        PASSED if finding.passed else FAILED)),
                severity=spec.severity, reason=reason, finding=finding))
        return report

    def unknown_specs(self) -> list[CheckSpec]:
        return [c for c in self._checks if c.unknown_reason]

    def stats(self) -> dict:
        gates: dict[str, int] = {}
        sources: dict[str, int] = {}
        for c in self._checks:
            gates[c.gate] = gates.get(c.gate, 0) + 1
            sources[c.source] = sources.get(c.source, 0) + 1
        return {"total": len(self._checks), "by_gate": gates, "by_source": sources,
                "unknown": len(self.unknown_specs())}


def code_checks() -> list[CheckSpec]:
    """Проверки, регистрируемые КОДОМ (builtin + контрактные) — без данных/ctx."""
    from agents.checks.builtin import BUILTIN_CHECKS
    from agents.checks.contract import CONTRACT_CHECKS
    return list(BUILTIN_CHECKS) + list(CONTRACT_CHECKS)


def result_checks() -> list[CheckSpec]:
    """Проверки РЕЗУЛЬТАТА (F-19): включаются в реестр ИЗ ДАННЫХ, где есть ctx."""
    from agents.checks.builtin import RESULT_CHECKS
    return list(RESULT_CHECKS)


def apply_severity_overrides(spec: CheckSpec, cfg) -> CheckSpec:
    """Серьёзность проверки из ДАННЫХ (``checks.check_severity: {<id>: major}``).

    Допустимые уровни — ``critical | major | minor | note`` (``note`` —
    ИНФОРМАЦИОННЫЙ: находка видна в отчёте, но гейт по ней не падает). Любое иное
    значение игнорируется — встроенный уровень остаётся (данные не «ломают» реестр).
    """
    if cfg is None or not hasattr(cfg, "get"):
        return spec
    overrides = cfg.get("checks.check_severity")
    if not isinstance(overrides, dict):
        return spec
    value = str(overrides.get(spec.id) or "").strip().lower()
    if value in ("critical", "major", "minor", "note") and value != spec.severity:
        return replace(spec, severity=value)
    return spec


def build_data_checks(root: Path, *, cfg=None, gate_map: dict | None = None,
                      include_package: bool = True,
                      include_csv: bool = True) -> list[CheckSpec]:
    """Проверки ИЗ ДАННЫХ: пакет ``domain/qaqc`` (по блокам гейтов) + ``ontology/qa_checks/*.csv``.

    Проверки судят по ЗНАЧЕНИЯМ (данные/артефакты), а не по факту запуска тНава,
    поэтому ``runtime=False``: без входных ключей они возвращают ``not_applicable``
    (модель не штрафуется), а не «прошло» и не «провал».
    """
    data = gate_map if gate_map is not None else load_gate_map(cfg, root=root)
    by_block = gates_by_block(data)
    levels = severity_levels(data)
    specs: list[CheckSpec] = [apply_severity_overrides(s, cfg)
                              for s in code_checks() + result_checks()]
    for row in load_check_catalog(root, include_package=include_package,
                                  include_csv=include_csv):
        gates = by_block.get(row.block_code) or ()
        severity = severity_for(row.significance, levels)
        func = _DataCheck(row, severity, engine=row.source)
        common = {"id": row.id, "severity": severity, "title": row.title or row.id,
                  "func": func, "source": row.source, "inputs": row.inputs,
                  "threshold": row.threshold, "formula": row.formula,
                  "block": row.block_code, "fitness": row.fitness,
                  "description": row.method}
        if not gates:
            specs.append(CheckSpec(
                gate="", remediation=row.criterion[:200], **common,
                unknown_reason=(row.malformed
                                or "блок проверки не привязан ни к одному гейту "
                                   "(данные qa_gate_map)")))
            continue
        specs.append(CheckSpec(gate=gates[0], gates=tuple(gates),
                               remediation=row.criterion[:200], **common))
    return specs
