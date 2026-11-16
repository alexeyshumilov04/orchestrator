"""Насыщение из SCAL/керна: J-функция, подгонка J(Sw) и концевые точки.

Что делает модуль (дополняет тНавигатор: SCAL → параметры насыщения):

  1. строит J-функцию по данным капиллярометрии/SCAL:

         J(Sw) = (Pc / (σ·cosθ)) · √(k/φ)

     (Лeverett-подобная нормировка по межфазному натяжению, краевому углу и
     отношению проницаемость/пористость; формула и источники — ДАННЫЕ онтологии);
  2. подгоняет по ТИПАМ ПОРОДЫ лог-линейную зависимость `J = A·Sw^(−B)`
     (`log10 J = log10 A − B·log10 Sw`) с `r2`, `n` и порогом достаточности;
  3. отдаёт КОНЦЕВЫЕ ТОЧКИ (Sw_irr, Sw_max) по данным, а не константой;
  4. умеет обращать зависимость: `sw_from_j(j, fit)` → Sw (для модели по высоте);
  5. принимает как таблицу-словари, так и МАТРИЦЫ SCAL поля (`swof`/`sgof`) —
     соответствие «матрица → роли колонок» задано ДАННЫМИ.

Правило 6: нет SCAL-данных → `not_applicable`; мало точек/нет σ·θ/нет k·φ →
`insufficient` (или `candidate_without_kphi`, если так разрешено данными); ни одно
число не выдумывается. Правило 1: мнемоники колонок, пороги и происхождение —
только из онтологии (`ontology/petrofacies_methods.yaml: saturation`).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from domain import petrofacies_data as data

STATUS_OK = "ok"
STATUS_LOW_R2 = "low_r2"
STATUS_INSUFFICIENT = "insufficient"
STATUS_DEGENERATE = "degenerate"
STATUS_NO_DATA = "no_data"
STATUS_NOT_APPLICABLE = "not_applicable"
STATUS_UNKNOWN_STATUS = "unknown"

SOURCE_SCAL = "scal"
SOURCE_CORE = "core"
SOURCE_LITERATURE = "literature"
SOURCE_UNKNOWN = "unknown"
SOURCE_CANDIDATE = "candidate"


@dataclass(frozen=True)
class JFit:
    """Подгонка J = A·Sw^(−B) по одному типу породы."""

    rock_type: str
    status: str
    source: str
    normalisation: str
    a: float | None = None
    b: float | None = None
    r2: float | None = None
    n_pairs: int = 0
    r2_min: float | None = None
    sw_min: float | None = None
    sw_max: float | None = None
    knowledge_status: str = ""
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.a is not None and self.b is not None

    def to_dict(self) -> dict:
        out = asdict(self)
        out["usable"] = self.usable
        return out


# ── формулы (источник — ДАННЫЕ) ──────────────────────────────────────────────
def _theta_cos(theta: float, rules: Mapping[str, Any] | None) -> float | None:
    """cos θ: единицы угла — ДАННЫЕ правила (`theta_units`: deg|rad)."""
    units = str(data.get(rules, "saturation.j_function.theta_units", "") or "").lower()
    if units in ("deg", "degree", "degrees", "град", "°"):
        return math.cos(math.radians(theta))
    if units in ("rad", "radian", "radians", "рад"):
        return math.cos(theta)
    return None


def _scale(rules: Mapping[str, Any] | None, role: str) -> float | None:
    """Множитель единиц для роли: нет ключа → 1.0 и признак «единицы приняты»."""
    value = data.get(rules, f"saturation.j_function.unit_scales.{role}")
    if value is None:
        return 1.0
    try:
        factor = float(value)
    except (TypeError, ValueError):
        return None
    return factor if factor > 0 else None


def j_value(pc: float, sigma: float, theta_cos: float, *,
            permeability: float | None = None, porosity: float | None = None,
            rules: Mapping[str, Any] | None = None) -> tuple[float | None, str]:
    """J(Sw) и вид нормировки: `sqrt_k_over_phi` либо `pc_over_sigma`.

    Числа приводятся к согласованным единицам множителями ДАННЫХ (нет множителя —
    1.0). Если k/φ недоступны, форма выбирается по правилу
    `saturation.j_function.on_missing_normaliser` (candidate_without_kphi|insufficient).
    """
    pc_scale = _scale(rules, "pc")
    sigma_scale = _scale(rules, "sigma")
    perm_scale = _scale(rules, "permeability")
    if pc_scale is None or sigma_scale is None:
        return None, "единицы Pc/σ не заданы корректно в данных"
    if not all(math.isfinite(v) for v in (pc, sigma, theta_cos)):
        return None, "нечисловые входы J-функции"
    denominator = sigma * sigma_scale * theta_cos
    if denominator == 0:
        return None, "σ·cosθ = 0 — J не определена"
    base = (pc * pc_scale) / denominator
    have_normaliser = (permeability is not None and porosity is not None
                       and permeability > 0 and porosity > 0)
    if have_normaliser:
        if perm_scale is None:
            return None, "единицы проницаемости не заданы корректно в данных"
        value = base * math.sqrt((permeability * perm_scale) / porosity)
        return value, "sqrt_k_over_phi"
    mode = str(data.get(rules, "saturation.j_function.on_missing_normaliser",
                        "insufficient") or "")
    if mode == "candidate_without_kphi":
        return base, "pc_over_sigma"
    return None, ("нет k/φ для нормировки (нужны роли permeability и porosity) — "
                  "J не строится")


# ── сбор точек J(Sw) ─────────────────────────────────────────────────────────
def build_j_rows(rows: Iterable[Mapping[str, Any]],
                 rules: Mapping[str, Any] | None) -> dict:
    """Точки (Sw, J, тип породы) из строк SCAL/керна + честная статистика отбраковки."""
    materialised = [row for row in rows if isinstance(row, Mapping)]
    keys: set[str] = set()
    for row in materialised:
        keys |= {str(k) for k in row.keys()}
    columns = {role: _pick_role_column(keys, role, rules)
               for role in ("pc", "sw", "sigma", "theta", "permeability",
                            "porosity", "rock_type")}
    required_missing = [role for role in ("pc", "sw", "sigma", "theta")
                        if not columns[role]]
    issues: list[str] = []
    if required_missing:
        for role in required_missing:
            issues.append(
                f"колонка роли «{role}» не найдена; кандидаты из онтологии: "
                f"{', '.join(_role_candidates(rules, role)) or '—'}")
        return {"rows": [], "columns": columns, "skipped": {}, "issues": issues,
                "n_input": len(materialised),
                "units_assumed": _units_assumed(rules)}

    points: list[dict] = []
    skipped = {"blank_pc": 0, "blank_sw": 0, "no_theta_cos": 0, "no_j": 0,
               "sw_out_of_range": 0}
    for row in materialised:
        pc = data.clean_number(_row_value(row, "pc", rules), rules)
        sw = data.clean_number(_row_value(row, "sw", rules), rules)
        sigma = data.clean_number(_row_value(row, "sigma", rules), rules)
        theta = data.clean_number(_row_value(row, "theta", rules), rules)
        if pc is None:
            skipped["blank_pc"] += 1
            continue
        if sw is None:
            skipped["blank_sw"] += 1
            continue
        if sw <= 0 or sw >= 1:
            skipped["sw_out_of_range"] += 1
            continue
        if sigma is None or theta is None:
            skipped["no_theta_cos"] += 1
            continue
        theta_cos = _theta_cos(theta, rules)
        if theta_cos is None:
            issues.append("единицы угла (θ) не заданы в онтологии "
                          "(`saturation.j_function.theta_units`) — J не строится")
            return {"rows": [], "columns": columns, "skipped": skipped,
                    "issues": issues, "n_input": len(materialised),
                    "units_assumed": _units_assumed(rules)}
        perm = data.clean_number(_row_value(row, "permeability", rules), rules)
        poro = data.clean_number(_row_value(row, "porosity", rules), rules)
        value, note = j_value(pc, sigma, theta_cos, permeability=perm, porosity=poro,
                              rules=rules)
        if value is None:
            skipped["no_j"] += 1
            if note not in issues:
                issues.append(note)
            continue
        rock = _row_value(row, "rock_type", rules)
        rock = str(rock).strip() if rock is not None else ""
        if not rock:
            rock = str(data.get(rules, "rock_typing.pooled_label", "") or "")
        points.append({"sw": float(sw), "j": float(value), "rock_type": rock,
                       "normalisation": note})
    if not points:
        issues.append("ни одной точки J(Sw): проверьте Pc/Sw/σ/θ в данных SCAL")
    return {"rows": points, "columns": columns, "skipped": skipped,
            "issues": issues, "n_input": len(materialised),
            "units_assumed": _units_assumed(rules)}


def _role_candidates(rules: Mapping[str, Any] | None, role: str) -> tuple[str, ...]:
    """Кандидаты колонок роли: сначала секция saturation, затем общая columns."""
    value = data.get(rules, f"saturation.columns.{role}")
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return data.column_candidates(rules, role)


def _pick_role_column(keys: Iterable[str], role: str,
                      rules: Mapping[str, Any] | None) -> str:
    """Первая подходящая колонка роли: saturation.columns → общие columns."""
    present = {str(k) for k in keys}
    lowered = {k.lower(): k for k in present}
    for candidate in _role_candidates(rules, role):
        if candidate in present:
            return candidate
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return ""


def _row_value(row: Mapping[str, Any], role: str,
               rules: Mapping[str, Any] | None) -> Any:
    """Значение роли из строки SCAL (колонки — из данных онтологии)."""
    column = _pick_role_column(row.keys(), role, rules)
    return row.get(column) if column else None


def _units_assumed(rules: Mapping[str, Any] | None) -> list[str]:
    """Роли, для которых множитель единиц НЕ задан (принят 1.0) — для отчёта."""
    out: list[str] = []
    for role in ("pc", "sigma", "permeability"):
        if data.get(rules, f"saturation.j_function.unit_scales.{role}") is None:
            out.append(role)
    return out


# ── подгонка J = A·Sw^(−B) ───────────────────────────────────────────────────
def _fit_one(points: Sequence[Mapping[str, Any]], *, rock_type: str,
             rules: Mapping[str, Any] | None, min_pairs: int | None,
             r2_min: float | None) -> JFit:
    spec = data.section(rules, "saturation")
    j_spec = spec.get("j_function") if isinstance(spec.get("j_function"), dict) else {}
    norm = str((points[0].get("normalisation") if points else "")
               or j_spec.get("normalisation") or "")
    n = len(points)
    lit_step = data.ladder_step(rules, SOURCE_LITERATURE)
    if n == 0:
        return JFit(rock_type, STATUS_NO_DATA, SOURCE_UNKNOWN, norm, n_pairs=0,
                    r2_min=r2_min,
                    reason=f"точек J(Sw) для типа «{rock_type}» нет")
    threshold = min_pairs or 0
    if n < threshold:
        return JFit(rock_type, STATUS_INSUFFICIENT, SOURCE_LITERATURE, norm,
                    n_pairs=n, r2_min=r2_min,
                    sw_min=min(p["sw"] for p in points),
                    sw_max=max(p["sw"] for p in points),
                    knowledge_status=str(j_spec.get("knowledge_status") or ""),
                    reason=(f"точек {n} < порога достаточности {threshold} — "
                            f"коэффициенты J(Sw) не публикуются; форма — из литературы: "
                            f"{str(lit_step.get('method') or 'не задана')}"))
    xs = [math.log10(float(p["sw"])) for p in points]
    pairs = [(math.log10(float(p["sw"])), math.log10(float(p["j"])))
             for p in points if float(p["j"]) > 0]
    if len(pairs) != n:
        xs = [item[0] for item in pairs]
        ys = [item[1] for item in pairs]
        n = len(pairs)
        if n < threshold:
            return JFit(rock_type, STATUS_INSUFFICIENT, SOURCE_LITERATURE, norm,
                        n_pairs=n, r2_min=r2_min,
                        reason="неположительные J отброшены — точек меньше порога")
    else:
        ys = [item[1] for item in pairs]
    if len({round(x, 12) for x in xs}) < 2:
        return JFit(rock_type, STATUS_DEGENERATE, SOURCE_SCAL, norm, n_pairs=n,
                    r2_min=r2_min, sw_min=min(p["sw"] for p in points),
                    sw_max=max(p["sw"] for p in points),
                    reason="одно уникальное значение Sw — подгонка не определена")
    slope, intercept, r2 = _least_squares(xs, ys)
    if slope is None:
        return JFit(rock_type, STATUS_DEGENERATE, SOURCE_SCAL, norm, n_pairs=n,
                    r2_min=r2_min, reason="нулевая дисперсия log10 Sw")
    # log10 J = log10 A − B·log10 Sw  →  log10 A = intercept, B = −slope
    a = 10.0 ** intercept
    b = -slope
    status = STATUS_OK
    reason = f"J = {a:.4g}·Sw^(−{b:.4g}) по {n} точкам"
    if r2 is None:
        status = STATUS_DEGENERATE
        reason += "; r2 не определён"
    elif r2_min is not None and r2 < r2_min:
        status = STATUS_LOW_R2
        reason += f"; r2={r2:.3f} < порога {r2_min:g} (связь слабая, под флагом)"
    else:
        reason += f"; r2={r2:.3f}"
    source = SOURCE_SCAL if str(norm) == "sqrt_k_over_phi" else SOURCE_CANDIDATE
    return JFit(rock_type, status, source, str(norm), a=a, b=b, r2=r2, n_pairs=n,
                r2_min=r2_min, sw_min=min(p["sw"] for p in points),
                sw_max=max(p["sw"] for p in points),
                knowledge_status=str(j_spec.get("knowledge_status") or ""),
                reason=reason)


def _least_squares(xs: Sequence[float], ys: Sequence[float]
                   ) -> tuple[float | None, float | None, float | None]:
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


def fit_j_sw(points: Iterable[Mapping[str, Any]],
             rules: Mapping[str, Any] | None) -> dict:
    """Подгонка J(Sw) по типам породы (или единая — если данные это разрешают)."""
    spec = data.section(rules, "saturation")
    fit_spec = spec.get("fit") if isinstance(spec.get("fit"), dict) else {}
    min_pairs_raw = fit_spec.get("min_pairs")
    min_pairs = int(min_pairs_raw) if isinstance(min_pairs_raw, (int, float)) else None
    r2_min_raw = fit_spec.get("r2_min")
    r2_min = float(r2_min_raw) if isinstance(r2_min_raw, (int, float)) else None
    grouped: dict[str, list[dict]] = {}
    for point in points:
        grouped.setdefault(str(point.get("rock_type") or ""), []).append(dict(point))
    fits = [_fit_one(grouped[rock], rock_type=rock, rules=rules,
                     min_pairs=min_pairs, r2_min=r2_min)
            for rock in sorted(grouped)]
    issues: list[str] = []
    pooled_fit: JFit | None = None
    if bool(fit_spec.get("pooled_allowed")):
        flat = [point for group in grouped.values() for point in group]
        pooled_fit = _fit_one(flat, rock_type=str(
            data.get("rock_typing.pooled_label", "") or "all"), rules=rules,
            min_pairs=min_pairs, r2_min=r2_min)
    else:
        issues.append("единая J(Sw) не строится (нужна типизация пород): "
                      + (", ".join(data.constraints(rules)) or "—"))
    usable = [fit for fit in fits if fit.usable]
    if usable:
        overall = STATUS_OK
    elif not grouped:
        overall = STATUS_NOT_APPLICABLE
    elif any(fit.status == STATUS_INSUFFICIENT for fit in fits):
        overall = STATUS_INSUFFICIENT
    elif any(fit.status == STATUS_NO_DATA for fit in fits):
        overall = STATUS_NO_DATA
    else:
        overall = STATUS_UNKNOWN_STATUS
    return {
        "status": overall,
        "fits": [fit.to_dict() for fit in fits],
        "pooled": pooled_fit.to_dict() if pooled_fit else None,
        "min_pairs": min_pairs, "r2_min": r2_min,
        "transform": str(fit_spec.get("transform") or ""),
        "form": str(fit_spec.get("form") or ""),
        "knowledge_status": str(fit_spec.get("knowledge_status") or ""),
        "source_rule": str(fit_spec.get("source_rule") or ""),
        "source_ids": list(fit_spec.get("source_ids") or []),
        "rock_types": sorted(grouped),
        "n_points": sum(len(group) for group in grouped.values()),
        "issues": issues,
    }


# ── концевые точки ───────────────────────────────────────────────────────────
def end_points(rows: Iterable[Mapping[str, Any]],
               rules: Mapping[str, Any] | None) -> dict:
    """Sw_irr/Sw_max по данным SCAL/керна (статистики и порог — ДАННЫЕ)."""
    spec = data.section(rules, "saturation")
    ep = spec.get("end_points") if isinstance(spec.get("end_points"), dict) else {}
    out: dict = {"source_rule": str(ep.get("source_rule") or ""),
                 "knowledge_status": str(ep.get("knowledge_status") or ""),
                 "provenance": str(ep.get("provenance") or ""), "values": {},
                 "status": STATUS_NOT_APPLICABLE, "issues": []}
    if not ep:
        out["issues"].append("правила концевых точек не заданы в онтологии")
        out["status"] = STATUS_UNKNOWN_STATUS
        return out
    values: dict[str, float] = {}
    for name, key in (("sw_irr", "min"), ("sw_max", "max")):
        rule = ep.get(name) if isinstance(ep.get(name), dict) else {}
        if not rule:
            out["issues"].append(f"правило концевой точки «{name}» не задано")
            continue
        numbers: list[float] = []
        for row in rows:
            sw = data.clean_number(_row_value(row, "sw", rules), rules)
            if sw is not None:
                numbers.append(sw)
        need = rule.get("min_samples")
        need = int(need) if isinstance(need, (int, float)) else 0
        if len(numbers) < max(need, 1):
            out["issues"].append(f"{name}: наблюдений {len(numbers)} < {max(need, 1)} — "
                                 f"значение не публикуется")
            continue
        statistic = str(rule.get("statistic") or "")
        if statistic == "min":
            values[name] = min(numbers)
        elif statistic == "max":
            values[name] = max(numbers)
        else:
            out["issues"].append(f"{name}: статистика «{statistic}» не поддержана данными")
    out["values"] = values
    if values:
        out["status"] = STATUS_OK
    elif out["issues"]:
        out["status"] = STATUS_INSUFFICIENT
    return out


# ── главная точка входа ──────────────────────────────────────────────────────
def fit_from_rows(rows: Iterable[Mapping[str, Any]] | None,
                  rules: Mapping[str, Any] | None) -> dict:
    """J(Sw) + концевые точки по таблице SCAL/керна (роли колонок — из данных)."""
    materialised = [row for row in (rows or []) if isinstance(row, Mapping)]
    built = build_j_rows(materialised, rules)
    fit = fit_j_sw(built["rows"], rules)
    if materialised and not built["rows"] and fit["status"] == STATUS_NOT_APPLICABLE:
        # Данные ЕСТЬ, но контракт J-функции не выполнен (нет Pc/Sw/σ/θ) — это
        # insufficient с перечнем недостающих ролей, а не «данных нет».
        fit["status"] = STATUS_INSUFFICIENT
    points = end_points(materialised, rules)
    issues = list(built["issues"]) + list(fit["issues"]) + list(points["issues"])
    if not materialised:
        status = STATUS_NOT_APPLICABLE
        issues.append("данных SCAL/керна нет — насыщение по J-функции не считается "
                      "(правило 6)")
    elif fit["status"] == STATUS_OK:
        status = STATUS_OK
    elif built["rows"]:
        status = fit["status"]
    else:
        status = STATUS_INSUFFICIENT
    return {
        "status": status,
        "j_fit": fit,
        "end_points": points,
        "n_rows": len(materialised),
        "n_points": len(built["rows"]),
        "columns": built["columns"],
        "skipped": built["skipped"],
        "units_assumed": built["units_assumed"],
        "issues": issues,
        "sources": data.loaded_sources(rules),
        "sources_missing": data.missing_sources(rules),
    }


def from_project_scal(scal_section: Mapping[str, Any] | None,
                      rules: Mapping[str, Any] | None) -> dict:
    """SCAL из ПРОЕКТНОГО ГРАФА (матрицы `swof`/`sgof`) → J(Sw) и концевые точки.

    Соответствие «матрица → роли колонок» — ДАННЫЕ (`saturation.tables`). Матрицы в
    графе обычно без Pc/σ/θ (только Kr/Pc), поэтому J-подгонка честно уходит в
    `insufficient` с перечнем недостающих ролей, а концевые точки считаются по Sw.
    """
    section = scal_section if isinstance(scal_section, Mapping) else {}
    spec = data.section(rules, "saturation")
    tables = spec.get("tables") if isinstance(spec.get("tables"), dict) else {}
    rows: list[dict] = []
    used: list[str] = []
    for name, roles in (tables.items() if isinstance(tables, Mapping) else []):
        matrix = section.get(str(name))
        if not isinstance(matrix, (list, tuple)):
            continue
        columns = [str(role) for role in (roles or [])]
        for entry in matrix:
            if not isinstance(entry, (list, tuple)):
                continue
            rows.append({columns[index]: value
                         for index, value in enumerate(entry)
                         if index < len(columns)})
        used.append(str(name))
    result = fit_from_rows(rows, rules)
    result["tables_used"] = used
    result["declared_tables"] = sorted(str(k) for k in (tables or {}))
    if not used:
        result["issues"] = list(result["issues"]) + [
            "в данных поля нет SCAL-матриц из `saturation.tables` ("
            + ", ".join(result["declared_tables"]) + ") — not_applicable"]
        result["status"] = STATUS_NOT_APPLICABLE
    return result


# ── обращение зависимости (модель по высоте) ─────────────────────────────────
def sw_from_j(j: float, fit: Mapping[str, Any] | JFit,
              rules: Mapping[str, Any] | None = None) -> float | None:
    """Sw из J по подогнанной зависимости: Sw = (A/J)^(1/B). Нет коэффициентов → None."""
    obj = fit if isinstance(fit, JFit) else _as_fit(fit)
    if not obj.usable or j is None or not math.isfinite(float(j)) or float(j) <= 0:
        return None
    b = float(obj.b)
    if b == 0:
        return None
    sw = (float(obj.a) / float(j)) ** (1.0 / b)
    return sw if 0.0 <= sw <= 1.0 else None


def _as_fit(payload: Mapping[str, Any]) -> JFit:
    fields = {name: payload.get(name) for name in
              ("rock_type", "status", "source", "normalisation", "a", "b", "r2",
               "n_pairs", "r2_min", "sw_min", "sw_max", "knowledge_status", "reason")}
    fields["rock_type"] = str(fields.get("rock_type") or "")
    fields["status"] = str(fields.get("status") or STATUS_UNKNOWN_STATUS)
    fields["source"] = str(fields.get("source") or SOURCE_UNKNOWN)
    fields["normalisation"] = str(fields.get("normalisation") or "")
    return JFit(**fields)                       # type: ignore[arg-type]


def load_rules(cfg: Any = None, *, root: str | None = None) -> dict:
    """Правила модулей из онтологии (см. `domain/petrofacies_data.load_rules`)."""
    return data.load_rules(cfg, root=root)
