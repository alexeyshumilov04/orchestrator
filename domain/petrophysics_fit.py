"""Подгонка k = f(φ) по КЕРНУ РАЗДЕЛЬНО ПО ЛИТОТИПАМ + обоснование cut-off.

Что делает модуль (дополняет тНавигатор: связь керн → параметры куба K):

  1. читает пары «пористость–проницаемость» из таблицы керна; имена колонок
     берутся ИЗ ДАННЫХ (`ontology/petrofacies_methods.yaml: columns`), бланки
     (в т.ч. LEGACY_NO_VALUE GeoMate) → `None`, НЕ ноль;
  2. подгоняет лог-линейную регрессию `log10(k) = a·φ + b` ОТДЕЛЬНО по каждому
     литотипу с `r2` и `n_pairs`; единая (неразделённая) зависимость запрещена
     правилом `RULE_LIT_PETRO_110` — она возвращается только если данные это
     явно разрешают (`rock_typing.pooled_allowed`);
  3. определяет СТАТУС ИСТОЧНИКА по лестнице из онтологии:
     `core` → `literature` → `unknown`. При недостатке пар коэффициенты НЕ
     подставляются (правило 6): статус `insufficient`, источник `literature`;
  4. применяет зависимость к значениям пористости (подготовка куба K) с учётом
     экстраполяции и статуса источника;
  5. ищет cut-off коллектора по МЕЧЕНОМУ керну (коллектор/не коллектор), а не
     константой (правило `RULE_LIT_PETRO_080`); нет меток/мало данных → `unknown`.

Все пороги (min_pairs, r2_min, min_per_class, transform, бланки, метки) — ДАННЫЕ
онтологии. В коде нет ни одной доменной мнемоники/имени поля.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from domain import petrofacies_data as data

#: статусы результата (имена схемы, не значения поля)
STATUS_OK = "ok"
STATUS_LOW_R2 = "low_r2"
STATUS_INSUFFICIENT = "insufficient"
STATUS_DEGENERATE = "degenerate"
STATUS_NO_DATA = "no_data"
STATUS_UNKNOWN = "unknown"
STATUS_NOT_APPLICABLE = "not_applicable"

SOURCE_CORE = "core"
SOURCE_LITERATURE = "literature"
SOURCE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class FitResult:
    """Результат подгонки по ОДНОМУ литотипу (или общей — если разрешена данными)."""

    lithotype: str
    status: str
    source: str
    transform: str
    slope: float | None = None
    intercept: float | None = None
    r2: float | None = None
    n_pairs: int = 0
    r2_min: float | None = None
    phi_min: float | None = None
    phi_max: float | None = None
    knowledge_status: str = ""
    reason: str = ""

    @property
    def usable(self) -> bool:
        """Годна ли зависимость к применению (коэффициенты ИЗ КЕРНА)."""
        return self.slope is not None and self.intercept is not None

    def predict_log10_k(self, porosity: float) -> float | None:
        """log10(k) по подогнанной зависимости; нет коэффициентов → `None`."""
        if not self.usable:
            return None
        return float(self.slope) * float(porosity) + float(self.intercept)

    def to_dict(self) -> dict:
        out = asdict(self)
        out["usable"] = self.usable
        return out


def _fit_one(pairs: Sequence[tuple[float, float]], *, lithotype: str,
             rules: Mapping[str, Any] | None, min_pairs_value: int | None,
             r2_min: float | None, transform: str,
             lod: str = "") -> FitResult:
    """Подогнать одну группу пар (φ, k) с честным статусом и источником."""
    n = len(pairs)
    unknown_step = data.ladder_step(rules, SOURCE_UNKNOWN)
    lit_step = data.ladder_step(rules, SOURCE_LITERATURE)
    if n == 0:
        return FitResult(lithotype, STATUS_NO_DATA, SOURCE_UNKNOWN, transform,
                         n_pairs=0, r2_min=r2_min,
                         knowledge_status=str(unknown_step.get("knowledge_status") or ""),
                         reason=f"пар керна для литотипа «{lithotype}» нет")
    threshold = min_pairs_value if min_pairs_value is not None else 0
    if n < threshold:
        return FitResult(
            lithotype, STATUS_INSUFFICIENT, SOURCE_LITERATURE, transform,
            n_pairs=n, r2_min=r2_min,
            knowledge_status=str(lit_step.get("knowledge_status") or ""),
            reason=(f"пар {n} < порога достаточности {threshold} — коэффициенты "
                    f"НЕ подставляются; форма зависимости — из литературы: "
                    f"{str(lit_step.get('method') or lod or 'не задана')}"))
    distinct = len({round(float(phi), 12) for phi, _ in pairs})
    min_distinct = int(data.get(rules, "permeability_fit.min_distinct_porosity", 2) or 2)
    if distinct < min_distinct:
        return FitResult(lithotype, STATUS_DEGENERATE, SOURCE_CORE, transform,
                         n_pairs=n, r2_min=r2_min,
                         phi_min=min(p[0] for p in pairs),
                         phi_max=max(p[0] for p in pairs),
                         reason=(f"уникальных значений пористости {distinct} < "
                                 f"{min_distinct} — регрессия не определена"))
    xs = [float(phi) for phi, _ in pairs]
    ys = [math.log10(float(k)) for _, k in pairs]
    slope, intercept, r2 = _least_squares(xs, ys)
    if slope is None:
        return FitResult(lithotype, STATUS_DEGENERATE, SOURCE_CORE, transform,
                         n_pairs=n, r2_min=r2_min, reason="дисперсия φ нулевая")
    status = STATUS_OK
    reason = f"лог-линейная регрессия по керну: n_pairs={n}"
    if r2 is None:
        status = STATUS_DEGENERATE
        reason += "; r2 не определён (нулевая дисперсия лог-k)"
    elif r2_min is not None and r2 < r2_min:
        status = STATUS_LOW_R2
        reason += (f"; r2={r2:.3f} < порога {r2_min:g} — связь слабая "
                   f"(коэффициенты ИЗ КЕРНА, но применение под флагом)")
    else:
        reason += f"; r2={r2:.3f}"
    return FitResult(lithotype, status, SOURCE_CORE, transform,
                     slope=slope, intercept=intercept, r2=r2, n_pairs=n,
                     r2_min=r2_min, phi_min=min(xs), phi_max=max(xs),
                     knowledge_status="EVIDENCE_BACKED", reason=reason)


def _least_squares(xs: Sequence[float], ys: Sequence[float]
                   ) -> tuple[float | None, float | None, float | None]:
    """МНК y = a·x + b и коэффициент детерминации r2 (None — не определён)."""
    n = len(xs)
    if n < 2:
        return None, None, None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None, None, None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    residual = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    total = sum((y - my) ** 2 for y in ys)
    r2 = None if total == 0 else max(0.0, 1.0 - residual / total)
    return float(slope), float(intercept), (None if r2 is None else float(r2))


# ── извлечение пар из таблицы керна (роли колонок — ДАННЫЕ) ──────────────────
def extract_core_pairs(rows: Iterable[Mapping[str, Any]],
                       rules: Mapping[str, Any] | None) -> dict:
    """Пары (φ, k, литотип) из строк керна + честная статистика отбраковки."""
    materialised = [row for row in rows if isinstance(row, Mapping)]
    keys: set[str] = set()
    for row in materialised:
        keys |= {str(k) for k in row.keys()}
    columns = {role: data.pick_column(keys, role, rules)
               for role in ("porosity", "permeability", "lithotype")}
    missing = [role for role, column in columns.items()
               if not column and role != "lithotype"]
    issues: list[str] = []
    if missing:
        for role in missing:
            issues.append(
                f"колонка роли «{role}» не найдена; кандидаты из онтологии: "
                f"{', '.join(data.column_candidates(rules, role)) or '—'}")
        return {"pairs": [], "classified": [], "unclassified": 0,
                "columns": columns, "missing": missing, "rows": len(materialised),
                "skipped": {}, "issues": issues, "scale_note": ""}

    raw: list[tuple[float, float, str]] = []
    skipped = {"blank_porosity": 0, "blank_permeability": 0,
               "nonpositive_permeability": 0}
    lithotypes_pooled = str(data.get(rules, "rock_typing.pooled_label", ""))
    for row in materialised:
        phi = data.clean_number(data.row_value(row, "porosity", rules), rules)
        if phi is None:
            skipped["blank_porosity"] += 1
            continue
        perm = data.clean_number(data.row_value(row, "permeability", rules), rules)
        if perm is None:
            skipped["blank_permeability"] += 1
            continue
        if perm <= 0:
            skipped["nonpositive_permeability"] += 1
            continue
        lith = data.row_value(row, "lithotype", rules)
        lith = str(lith).strip() if lith is not None else ""
        if not lith:
            lith = lithotypes_pooled
        raw.append((phi, perm, lith))

    phis, note = data.scale_porosity([phi for phi, _, _ in raw], rules)
    pairs = [(phis[i], raw[i][1], raw[i][2]) for i in range(len(raw))]
    unclassified = sum(1 for _, _, lith in pairs if lith == lithotypes_pooled)
    mode = str(data.get(rules, "rock_typing.on_missing_lithotype", "unknown"))
    require = bool(data.get(rules, "rock_typing.require_lithotype", False))
    if unclassified and require and mode == "unknown":
        issues.append(f"проб без литотипа: {unclassified} — исключены из подгонки "
                      f"(единая зависимость недопустима)")
        pairs = [item for item in pairs if item[2] != lithotypes_pooled]
    if note:
        issues.append(note)
    return {"pairs": pairs, "classified": pairs, "unclassified": unclassified,
            "columns": columns, "missing": [], "skipped": skipped,
            "rows": len(materialised), "issues": issues, "scale_note": note}


def fit_pairs(pairs: Iterable[Sequence[Any]], rules: Mapping[str, Any] | None,
              *, pooled: bool | None = None) -> dict:
    """Подгонка по парам (φ, k, литотип): отдельно по литотипам + статус источника."""
    grouped: dict[str, list[tuple[float, float]]] = {}
    for item in pairs:
        phi, perm, lith = float(item[0]), float(item[1]), str(item[2]).strip()
        grouped.setdefault(lith, []).append((phi, perm))

    min_pairs_value = data.min_pairs(rules)
    r2_min_raw = data.get(rules, "permeability_fit.r2_min")
    r2_min = float(r2_min_raw) if isinstance(r2_min_raw, (int, float)) else None
    transform = str(data.get(rules, "permeability_fit.transform", ""))
    lod = str(data.ladder_step(rules, SOURCE_LITERATURE).get("output") or "")

    fits = [_fit_one(grouped[lith], lithotype=lith, rules=rules,
                     min_pairs_value=min_pairs_value, r2_min=r2_min,
                     transform=transform, lod=lod)
            for lith in sorted(grouped)]
    issues: list[str] = []
    allowed_pooled = bool(data.get(rules, "rock_typing.pooled_allowed", False))
    if pooled is None:
        pooled = allowed_pooled
    pooled_fit: FitResult | None = None
    if pooled:
        flat = [pair for group in grouped.values() for pair in group]
        pooled_fit = _fit_one(flat, lithotype=str(
            data.get(rules, "rock_typing.pooled_label", "") or "all"),
            rules=rules, min_pairs_value=min_pairs_value, r2_min=r2_min,
            transform=transform)
    else:
        rules_ids = ", ".join(data.constraints(rules)) or "—"
        issues.append("единая (неразделённая) зависимость k-φ не строится: "
                      f"ограничения из онтологии: {rules_ids}")

    usable = [fit for fit in fits if fit.status in (STATUS_OK, STATUS_LOW_R2)]
    if not grouped:
        status = STATUS_NOT_APPLICABLE
    elif usable:
        status = STATUS_OK
    else:
        status = STATUS_UNKNOWN
    return {
        "status": status,
        "fits": [fit.to_dict() for fit in fits],
        "pooled": pooled_fit.to_dict() if pooled_fit else None,
        "pooled_allowed": allowed_pooled,
        "min_pairs": min_pairs_value,
        "r2_min": r2_min,
        "transform": transform,
        "lithotypes": sorted(grouped),
        "n_pairs_total": sum(len(group) for group in grouped.values()),
        "n_usable": len(usable),
        "constraints": list(data.constraints(rules)),
        "issues": issues,
        "sources": data.loaded_sources(rules),
        "sources_missing": data.missing_sources(rules),
        "source": SOURCE_CORE if usable else (
            SOURCE_UNKNOWN if not grouped else SOURCE_LITERATURE),
    }


def fit_from_rows(rows: Iterable[Mapping[str, Any]], rules: Mapping[str, Any] | None,
                  *, pooled: bool | None = None) -> dict:
    """Подгонка прямо по таблице керна (роли колонок — из данных онтологии)."""
    extracted = extract_core_pairs(rows, rules)
    result = fit_pairs(extracted["pairs"], rules, pooled=pooled)
    result["issues"] = list(extracted["issues"]) + list(result["issues"])
    result["columns"] = extracted["columns"]
    result["skipped"] = extracted["skipped"]
    result["n_unclassified"] = extracted["unclassified"]
    result["rows"] = extracted["rows"]
    return result


# ── применение зависимости (подготовка куба K) ───────────────────────────────
def apply_fit(fit: Mapping[str, Any] | FitResult, porosities: Sequence[Any],
              rules: Mapping[str, Any] | None) -> dict:
    """Применить зависимость к пористости: log10(k) по ячейкам + статус источника.

    Нет коэффициентов (источник literature/unknown) → значения `None`
    (правило 6: подстановка «формы из литературы» без керна запрещена).
    """
    obj = fit if isinstance(fit, FitResult) else _as_fit(fit)
    guard = bool(data.get(rules, "permeability_fit.extrapolation_guard", False))
    values: list[float | None] = []
    outside = 0
    for raw in porosities:
        phi = data.clean_number(raw, rules)
        if phi is None or not obj.usable:
            values.append(None)
            continue
        if guard and ((obj.phi_min is not None and phi < obj.phi_min) or
                      (obj.phi_max is not None and phi > obj.phi_max)):
            outside += 1
        values.append(obj.predict_log10_k(phi))
    issues: list[str] = []
    if not obj.usable:
        issues.append(f"коэффициенты не подставлены: статус «{obj.status}», "
                      f"источник «{obj.source}»")
    if outside and guard:
        issues.append(f"вне диапазона керна φ [{obj.phi_min}, {obj.phi_max}]: "
                      f"{outside} значений (экстраполяция под флагом)")
    return {"values": values, "status": obj.status, "source": obj.source,
            "lithotype": obj.lithotype, "transform": obj.transform,
            "outside_range": outside, "issues": issues,
            "usable": obj.usable}


def _as_fit(payload: Mapping[str, Any]) -> FitResult:
    """Собрать FitResult из словаря (результат `to_dict`)."""
    fields = {name: payload.get(name) for name in
              ("lithotype", "status", "source", "transform", "slope", "intercept",
               "r2", "n_pairs", "r2_min", "phi_min", "phi_max",
               "knowledge_status", "reason")}
    fields["lithotype"] = str(fields.get("lithotype") or "")
    fields["status"] = str(fields.get("status") or STATUS_UNKNOWN)
    fields["source"] = str(fields.get("source") or SOURCE_UNKNOWN)
    fields["transform"] = str(fields.get("transform") or "")
    return FitResult(**fields)                       # type: ignore[arg-type]


# ── cut-off коллектора по МЕЧЕНОМУ керну (не константа) ──────────────────────
def _label_kind(value: Any, rules: Mapping[str, Any] | None) -> int:
    """1 — коллектор, 0 — нет, -1 — метка неизвестна (списки — ДАННЫЕ)."""
    positive = {str(item).strip().casefold()
                for item in data.get(rules, "cutoff.positive_values", []) or []}
    negative = {str(item).strip().casefold()
                for item in data.get(rules, "cutoff.negative_values", []) or []}
    token = str(value).strip().casefold()
    if token in positive:
        return 1
    if token in negative:
        return 0
    return -1


def cutoff_from_labelled_core(rows: Iterable[Mapping[str, Any]],
                              rules: Mapping[str, Any] | None) -> dict:
    """Порог проницаемости по меченому керну (коллектор/не коллектор).

    Ищется порог в лог-проницаемости, максимизирующий сбалансированную точность
    (метод и минимум наблюдений в классе — ДАННЫЕ). Нет меток/мало данных →
    `unknown` без числа (правило 6).
    """
    spec = data.section(rules, "cutoff")
    method = str(spec.get("method") or "")
    min_per_class_raw = spec.get("min_per_class")
    min_per_class = int(min_per_class_raw) if isinstance(min_per_class_raw, (int, float)) \
        else None
    base = {"method": method, "parameter": str(spec.get("parameter") or ""),
            "provenance": str(spec.get("provenance") or ""),
            "min_per_class": min_per_class, "source": SOURCE_CORE}
    if not method:
        return {**base, "status": STATUS_UNKNOWN, "value": None,
                "reason": "метод cut-off не задан в онтологии"}
    materialised = [row for row in rows if isinstance(row, Mapping)]
    samples: list[tuple[float, int]] = []
    skipped = {"blank_permeability": 0, "unknown_label": 0,
               "nonpositive_permeability": 0}
    for row in materialised:
        perm = data.clean_number(data.row_value(row, "permeability", rules), rules)
        if perm is None:
            skipped["blank_permeability"] += 1
            continue
        if perm <= 0:
            skipped["nonpositive_permeability"] += 1
            continue
        kind = _label_kind(data.row_value(row, "reservoir_label", rules), rules)
        if kind < 0:
            skipped["unknown_label"] += 1
            continue
        samples.append((math.log10(perm), kind))
    positives = sum(1 for _, kind in samples if kind == 1)
    negatives = len(samples) - positives
    if not samples:
        return {**base, "status": STATUS_NOT_APPLICABLE, "value": None,
                "n_pairs": 0, "n_reservoir": 0, "n_non_reservoir": 0,
                "skipped": skipped,
                "reason": "меченого керна нет — cut-off не выводится (не константа)"}
    if min_per_class is not None and (positives < min_per_class or negatives < min_per_class):
        return {**base, "status": STATUS_INSUFFICIENT, "value": None,
                "n_pairs": len(samples), "n_reservoir": positives,
                "n_non_reservoir": negatives, "skipped": skipped,
                "reason": (f"в классе коллектора {positives}, в классе неколлектора "
                           f"{negatives}; нужно >= {min_per_class} в каждом — "
                           f"cut-off не выводится")}
    threshold, score = _best_threshold([x for x, _ in samples],
                                       [kind for _, kind in samples])
    if threshold is None:
        return {**base, "status": STATUS_DEGENERATE, "value": None,
                "n_pairs": len(samples), "n_reservoir": positives,
                "n_non_reservoir": negatives, "skipped": skipped,
                "reason": "порог не разделяет классы (все значения совпадают)"}
    return {**base, "status": STATUS_OK, "threshold_log10": threshold,
            "value": 10.0 ** threshold, "balanced_accuracy": score,
            "n_pairs": len(samples), "n_reservoir": positives,
            "n_non_reservoir": negatives, "skipped": skipped,
            "reason": (f"порог по меченому керну: log10(k) >= {threshold:.4f} → "
                       f"коллектор; сбалансированная точность {score:.3f}")}


def _best_threshold(xs: Sequence[float], kinds: Sequence[int]
                    ) -> tuple[float | None, float | None]:
    """Порог по x, максимизирующий сбалансированную точность; детерминированный."""
    if not xs:
        return None, None
    order = sorted(range(len(xs)), key=lambda i: (xs[i], kinds[i]))
    values = [xs[i] for i in order]
    candidates = sorted({(values[i] + values[i + 1]) / 2.0
                         for i in range(len(values) - 1)})
    if not candidates:
        return None, None
    total = len(xs)
    positives = sum(1 for kind in kinds if kind == 1)
    negatives = total - positives
    if positives == 0 or negatives == 0:
        return None, None
    best: tuple[float, float] | None = None
    for threshold in candidates:
        true_positive = sum(1 for x, kind in zip(xs, kinds)
                            if kind == 1 and x >= threshold)
        true_negative = sum(1 for x, kind in zip(xs, kinds)
                            if kind == 0 and x < threshold)
        sensitivity = true_positive / positives
        specificity = true_negative / negatives
        score = (sensitivity + specificity) / 2.0
        if best is None or score > best[1] + 1e-12:
            best = (threshold, score)
    return best
