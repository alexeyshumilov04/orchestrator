"""Фациальная модель: список/порядок фаций из ДАННЫХ, доли, связность, тела.

Что делает модуль (подготовка фациального шага тНавигатора; сам шаг тНава
модуль НЕ вызывает — вызов делает агент/раннер):

  1. порядок классов фаций берётся ИЗ ДАННЫХ (`facies_model.order_by`: сортировка
     кодов либо явный перечень `explicit_order` поля); коды вне перечня уходят в
     конец и помечаются `unknown`;
  2. доли классов по скважинным данным — с порогом числа скважин
     (`facies_model.min_wells`); мало скважин → `unknown`, а не «доли из воздуха»;
  3. агрегаты по кубу кодов: число тел (компонент связности) на класс по
     6/18/26-соседству, крупнейшее тело и его доля, минимальный размер тела;
  4. `net_to_gross` — доля ячеек классов с ролью «коллектор»; роль приходит из
     ДАННЫХ поля (карта «код → роль»), нет карты → `unknown` (правило 6);
  5. параметры шага фаций для шаблона функции тНава: патч применяется ТОЛЬКО
     если код параметра объявлен в онтологии И присутствует в ШАБЛОНЕ функции
     (правило 8: параметры тНава не выдумываются — иначе `unknown`).

Проверки интервалов (мощность, перекрытие, литология/насыщение) перенесены из
контрактов GeoMate (`ontology/geomate_reuse_rules.yaml`) и выполняются здесь по
данным интервалов, а не по зашитым именам.
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from domain import petrofacies_data as data

STATUS_OK = "ok"
STATUS_UNKNOWN = "unknown"
STATUS_NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class FaciesClass:
    """Агрегат по одному классу (коду) фаций."""

    code: str
    order: int
    role: str = ""
    cells: int = 0
    proportion: float | None = None
    bodies: int | None = None
    largest_body_cells: int | None = None
    largest_body_share: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ── коды ─────────────────────────────────────────────────────────────────────
def normalise_code(value: Any) -> str:
    """Код фации → стабильная строка (`1.0` и `1` — один код; бланк → пусто)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if float(value).is_integer() else f"{value:g}"
    token = str(value).strip()
    return "" if token.casefold() in {"none", "nan", "null"} else token


def class_order(codes: Iterable[Any], rules: Mapping[str, Any] | None) -> dict:
    """Порядок классов из данных: `code` (сортировка) либо `explicit` (перечень)."""
    spec = data.section(rules, "facies_model")
    order_by = str(spec.get("order_by") or "")
    present = sorted({normalise_code(code) for code in codes if normalise_code(code)},
                     key=_code_sort_key)
    explicit = [normalise_code(item) for item in (spec.get("explicit_order") or [])]
    if order_by == "explicit" and explicit:
        head = [code for code in explicit if code in present]
        tail = [code for code in present if code not in head]
        return {"order": head + tail, "order_by": order_by,
                "unknown_codes": tail if bool(spec.get("unknown_codes_tail", True)) else [],
                "declared_absent": [code for code in explicit if code not in present]}
    return {"order": present, "order_by": order_by or "code",
            "unknown_codes": [], "declared_absent": []}


def _code_sort_key(code: str):
    try:
        return (0, float(code), "")
    except ValueError:
        return (1, 0.0, code)


# ── связность тел ────────────────────────────────────────────────────────────
def _offsets(ndim: int, neighbourhood: int) -> list[tuple[int, ...]]:
    """Смещения соседства: 6/18/26 → манхэттенское расстояние <= 1/2/ndim."""
    limit = {6: 1, 18: 2}.get(int(neighbourhood), ndim)
    out: list[tuple[int, ...]] = []
    for flat in range(3 ** ndim):
        vector: list[int] = []
        value = flat
        for _ in range(ndim):
            vector.append(value % 3 - 1)
            value //= 3
        if all(item == 0 for item in vector):
            continue
        if sum(abs(item) for item in vector) <= limit:
            out.append(tuple(vector))
    return out


def connectivity_stats(volume: Sequence[Any], shape: Sequence[int], *,
                       code: Any, neighbourhood: int = 6,
                       min_body_cells: int = 1) -> dict:
    """Тела класса `code` в кубе: число компонент связности и крупнейшая из них.

    Соседство — по граням/рёбрам/вершинам (`neighbourhood` = 6/18/26 для 3D).
    Тела меньше `min_body_cells` ячейками не считаются телами (шум).
    """
    dims = tuple(int(item) for item in shape)
    if not dims or any(item <= 0 for item in dims):
        raise ValueError("Геометрия куба должна содержать положительные размеры")
    total = 1
    for item in dims:
        total *= item
    if len(volume) != total:
        raise ValueError(
            f"Число ячеек ({len(volume)}) не совпадает с геометрией {dims} ({total})")
    target = normalise_code(code)
    offsets = _offsets(len(dims), neighbourhood)
    visited = bytearray(total)
    bodies = 0
    largest = 0
    cells = 0
    for start in range(total):
        if visited[start] or normalise_code(volume[start]) != target:
            continue
        visited[start] = 1
        queue = deque([start])
        size = 0
        while queue:
            flat = queue.popleft()
            size += 1
            coords = _coords(flat, dims)
            for offset in offsets:
                neighbour = _flat(coords, offset, dims)
                if neighbour is None or visited[neighbour]:
                    continue
                if normalise_code(volume[neighbour]) != target:
                    continue
                visited[neighbour] = 1
                queue.append(neighbour)
        cells += size
        if size >= max(1, int(min_body_cells)):
            bodies += 1
            largest = max(largest, size)
    return {"code": target, "cells": cells, "bodies": bodies,
            "largest_body_cells": largest,
            "largest_body_share": (largest / cells) if cells else None,
            "neighbourhood": int(neighbourhood),
            "min_body_cells": max(1, int(min_body_cells))}


def _coords(flat: int, dims: Sequence[int]) -> tuple[int, ...]:
    out: list[int] = []
    for size in reversed(dims):
        out.append(flat % size)
        flat //= size
    return tuple(reversed(out))


def _flat(coords: Sequence[int], offset: Sequence[int],
          dims: Sequence[int]) -> int | None:
    flat = 0
    for index, size in enumerate(dims):
        value = coords[index] + offset[index]
        if value < 0 or value >= size:
            return None
        flat = flat * size + value
    return flat


# ── агрегаты по кубу и по скважинам ──────────────────────────────────────────
def proportions_from_wells(well_codes: Mapping[str, Sequence[Any]],
                           rules: Mapping[str, Any] | None) -> dict:
    """Доли классов по скважинным данным; мало скважин → `unknown` (правило 6)."""
    spec = data.section(rules, "facies_model")
    min_wells_raw = spec.get("min_wells")
    min_wells = int(min_wells_raw) if isinstance(min_wells_raw, (int, float)) else None
    counts: dict[str, int] = {}
    wells = 0
    blank_cells = 0
    for _well, codes in (well_codes or {}).items():
        series = list(codes or [])
        if not series:
            continue
        wells += 1
        for code in series:
            token = normalise_code(code)
            if not token:
                blank_cells += 1
                continue
            counts[token] = counts.get(token, 0) + 1
    total = sum(counts.values())
    if wells == 0 or total == 0:
        return {"status": STATUS_NOT_APPLICABLE, "proportions": {}, "wells": wells,
                "min_wells": min_wells, "classes": [], "cells": 0,
                "unknown": ["скважинных данных фаций нет — доли не считаются"]}
    if min_wells is not None and wells < min_wells:
        return {"status": STATUS_UNKNOWN, "proportions": {}, "wells": wells,
                "min_wells": min_wells, "classes": sorted(counts), "cells": total,
                "unknown": [f"скважин с данными фаций {wells} < порога {min_wells} — "
                            f"доли не считаются"]}
    ordered = class_order(counts, rules)
    proportions = {code: counts[code] / total for code in ordered["order"]}
    unknowns = [] if not blank_cells else [f"бланковых отсчётов фаций: {blank_cells} "
                                           f"(не отнесены ни к одному классу)"]
    return {"status": STATUS_OK, "proportions": proportions, "wells": wells,
            "min_wells": min_wells, "classes": ordered["order"],
            "cells": total, "order_by": ordered["order_by"],
            "unknown": unknowns}


def aggregate_facies(*, volume: Sequence[Any] | None = None,
                     shape: Sequence[int] | None = None,
                     well_codes: Mapping[str, Sequence[Any]] | None = None,
                     roles: Mapping[Any, str] | None = None,
                     rules: Mapping[str, Any] | None,
                     with_connectivity: bool = True) -> dict:
    """Сводка по фациям: порядок, доли, NTG, связность и тела.

    Источники данных независимы: куб кодов (`volume`+`shape`) и/или скважинные
    последовательности (`well_codes`). Чего нет — то `unknown`, без подстановки.
    """
    spec = data.section(rules, "facies_model")
    unknowns: list[str] = []
    source_label = str(spec.get("source_label") or "")
    result: dict[str, Any] = {
        "status": STATUS_NOT_APPLICABLE, "classes": [], "order": [],
        "order_by": str(spec.get("order_by") or ""), "unknown_codes": [],
        "proportions": {}, "proportions_source": "", "net_to_gross": None,
        "reservoir_share": None, "connectivity": None, "wells": 0,
        "min_wells": spec.get("min_wells"), "cells": 0, "source": source_label,
        "unknown": unknowns,
    }

    class_by_code: dict[str, FaciesClass] = {}
    if volume is not None and shape is not None:
        cells_total = len(volume)
        result["cells"] = cells_total
        ordered = class_order(volume, rules)
        result["order"] = ordered["order"]
        result["order_by"] = ordered["order_by"]
        result["unknown_codes"] = ordered["unknown_codes"]
        if ordered["declared_absent"]:
            unknowns.append("коды из explicit_order отсутствуют в данных: "
                            + ", ".join(ordered["declared_absent"]))
        counts: dict[str, int] = {}
        blank_cells = 0
        for code in volume:
            token = normalise_code(code)
            if not token:
                blank_cells += 1
                continue
            counts[token] = counts.get(token, 0) + 1
        if blank_cells:
            unknowns.append(f"бланковых ячеек: {blank_cells} (не отнесены ни к "
                            f"одному классу)")
        if not cells_total:
            unknowns.append("куб кодов пуст — агрегаты не считаются")
        dims = tuple(int(item) for item in shape)
        max_cells = _connectivity_limit(rules)
        neighbourhood = _neighbourhood(rules)
        min_body = int(spec.get("min_body_cells", 1) or 1)
        do_connectivity = with_connectivity and cells_total > 0
        if do_connectivity and max_cells is not None and cells_total > max_cells:
            do_connectivity = False
            unknowns.append(f"связность не считалась: ячеек {cells_total} > предела "
                            f"{max_cells} (предел — ДАННЫЕ)")
        body_rows: list[dict] = []
        for index, code in enumerate(ordered["order"]):
            stats: dict = {}
            if do_connectivity:
                stats = connectivity_stats(volume, dims, code=code,
                                           neighbourhood=neighbourhood,
                                           min_body_cells=min_body)
                body_rows.append(stats)
            class_by_code[code] = FaciesClass(
                code=code, order=index,
                cells=counts.get(code, 0),
                proportion=(counts.get(code, 0) / cells_total) if cells_total else None,
                bodies=stats.get("bodies"),
                largest_body_cells=stats.get("largest_body_cells"),
                largest_body_share=stats.get("largest_body_share"))
        if do_connectivity:
            result["connectivity"] = {
                "neighbourhood": neighbourhood, "min_body_cells": max(1, min_body),
                "bodies_total": sum(row["bodies"] for row in body_rows),
                "largest_body_share": (
                    max((row["largest_body_share"] or 0.0) for row in body_rows)
                    if body_rows else None),
                "per_class": {row["code"]: {"bodies": row["bodies"],
                                            "largest_body_cells": row["largest_body_cells"]}
                              for row in body_rows},
                "status": STATUS_OK}
        elif with_connectivity:
            result["connectivity"] = {"status": STATUS_UNKNOWN,
                                      "reason": "объём пуст или превышен предел расчёта"}
        result["proportions"] = {code: (item.proportion or 0.0)
                                 for code, item in class_by_code.items()}
        result["proportions_source"] = source_label
        if cells_total:
            result["status"] = STATUS_OK

    wells = proportions_from_wells(well_codes or {}, rules) if well_codes else None
    if wells is not None:
        result["wells"] = wells["wells"]
        for reason in wells["unknown"]:
            unknowns.append(reason)
        if wells["status"] == STATUS_OK:
            result["proportions_from_wells"] = wells["proportions"]
            result["proportions_wells_source"] = source_label
            if not result["proportions"]:
                result["proportions"] = dict(wells["proportions"])
                result["proportions_source"] = source_label
                result["order"] = list(wells["classes"])
                result["status"] = STATUS_OK
            for code, share in wells["proportions"].items():
                if code not in class_by_code:
                    class_by_code[code] = FaciesClass(
                        code=code, order=len(class_by_code), proportion=share)

    role_map = {normalise_code(key): str(value)
                for key, value in (roles or {}).items()}
    for code, item in list(class_by_code.items()):
        if code in role_map and not item.role:
            class_by_code[code] = replace(item, role=role_map[code])

    ntg, reservoir_share, role_unknown = _roles_summary(class_by_code, roles, rules)
    result["net_to_gross"] = ntg
    result["reservoir_share"] = reservoir_share
    unknowns += role_unknown

    if class_by_code:
        result["classes"] = [class_by_code[code].to_dict()
                             for code in sorted(class_by_code,
                                                key=lambda item: class_by_code[item].order)]
    if not class_by_code:
        unknowns.append("данных фаций нет (ни куба кодов, ни скважинных серий)")
        result["status"] = STATUS_NOT_APPLICABLE
    elif result["status"] != STATUS_OK:
        result["status"] = STATUS_UNKNOWN
    return result


def _connectivity_limit(rules: Mapping[str, Any] | None) -> int | None:
    value = data.get(rules, "facies_model.connectivity_max_cells")
    return int(value) if isinstance(value, (int, float)) else None


def _neighbourhood(rules: Mapping[str, Any] | None) -> int:
    spec = data.section(rules, "facies_model")
    value = int(spec.get("neighbourhood", 6) or 6)
    options = [int(item) for item in (spec.get("neighbourhood_options") or [])
               if isinstance(item, (int, float))]
    if options and value not in options:
        raise ValueError(f"Соседство {value} не входит в допустимые данные "
                         f"{options} (ontology: facies_model.neighbourhood_options)")
    return value


def _roles_summary(classes: Mapping[str, FaciesClass],
                   roles: Mapping[Any, str] | None,
                   rules: Mapping[str, Any] | None) -> tuple[float | None, float | None, list[str]]:
    """NTG и доля коллектора по карте ролей (код → роль) из ДАННЫХ поля."""
    spec = data.section(rules, "facies_model")
    reservoir_role = str(spec.get("reservoir_role") or "")
    unknowns: list[str] = []
    if not reservoir_role:
        return None, None, ["роль коллектора не задана в онтологии — NTG = unknown"]
    role_map = {normalise_code(key): str(value) for key, value in (roles or {}).items()}
    if not role_map:
        if spec.get("roles_required", True):
            unknowns.append("карта ролей «код → коллектор/нет» не передана — "
                            "NTG = unknown (правило 6)")
        return None, None, unknowns
    known = [code for code in classes if code in role_map]
    missing = [code for code in classes if code not in role_map]
    if missing:
        unknowns.append("нет роли для кодов: " + ", ".join(sorted(missing)))
    total = sum(classes[code].cells for code in known)
    if not total:
        return None, None, unknowns
    reservoir = sum(classes[code].cells for code in known
                    if role_map[code] == reservoir_role)
    share = reservoir / total
    return (share if not missing else None), share, unknowns


# ── параметры шага фаций (только коды, подтверждённые ШАБЛОНОМ) ──────────────
def facies_step_parameters(aggregate: Mapping[str, Any],
                           rules: Mapping[str, Any] | None, *,
                           template_text: str | None = None) -> tuple[dict, list[str]]:
    """Патч параметров шага фаций: код объявлен в онтологии И есть в шаблоне.

    Правило 8: имена/коды параметров тНава не выдумываются. Если шаблона нет или
    код в нём отсутствует — патч не применяется, причина уходит в `unknown`.
    """
    spec = data.section(rules, "facies_model")
    codes = spec.get("patch_codes")
    unknowns: list[str] = []
    if not isinstance(codes, Mapping) or not codes:
        return {}, ["коды параметров шага фаций не заданы в онтологии "
                    "(заполняются только после успешной пробы тНава)"]
    patch: dict[str, Any] = {}
    for code, source in codes.items():
        value = _parameter_value(str(source), aggregate)
        if value in (None, "", {}, []):
            unknowns.append(f"значение для кода «{code}» недоступно "
                            f"(источник «{source}») — unknown")
            continue
        if template_text is None:
            unknowns.append(f"шаблон функции не передан — код «{code}» не пропатчен")
            continue
        if not re.search(r"\b" + re.escape(str(code)) + r"\s*=", template_text):
            unknowns.append(f"кода «{code}» нет в шаблоне функции — патч не применён "
                            f"(иначе рендер дал бы предупреждение)")
            continue
        patch[str(code)] = value
    return patch, unknowns


def _parameter_value(source: str, aggregate: Mapping[str, Any]) -> Any:
    """Значение параметра из результата агрегата (имена источников — схема)."""
    table = {
        "proportions": aggregate.get("proportions"),
        "classes": len(aggregate.get("classes") or []),
        "order": aggregate.get("order"),
        "net_to_gross": aggregate.get("net_to_gross"),
        "reservoir_share": aggregate.get("reservoir_share"),
        "wells": aggregate.get("wells"),
        "cells": aggregate.get("cells"),
    }
    return table.get(source)


# ── проверки интервалов (контракты GeoMate, перенесены как правила данных) ───
def validate_intervals(intervals: Sequence[Mapping[str, Any]],
                       rules: Mapping[str, Any] | None) -> dict:
    """Проверки интервалов из контрактов GeoMate: геометрия и заполненность.

    Ключи интервала (`top`/`bottom`/`lithology`/`saturation`) — ДАННЫЕ
    (`interval_fields` в онтологии). Возвращает `{checked, issues, status}`;
    пустой список → `not_applicable` (неизвестное != ложь).
    """
    key_top = str(data.get(rules, "interval_fields.top", ""))
    key_bottom = str(data.get(rules, "interval_fields.bottom", ""))
    key_lithology = str(data.get(rules, "interval_fields.lithology", ""))
    key_saturation = str(data.get(rules, "interval_fields.saturation", ""))
    if not (key_top and key_bottom):
        return {"checked": 0, "issues": [], "status": STATUS_UNKNOWN,
                "reason": "ключи интервалов не заданы в онтологии (interval_fields)"}
    issues: list[str] = []
    ordered = sorted((item for item in intervals if isinstance(item, Mapping)),
                     key=lambda item: (_number(item.get(key_top)) or 0.0,
                                       _number(item.get(key_bottom)) or 0.0))
    previous_bottom: float | None = None
    for index, item in enumerate(ordered):
        top = _number(item.get(key_top))
        bottom = _number(item.get(key_bottom))
        lithology = str(item.get(key_lithology) or "").strip() if key_lithology else ""
        saturation = str(item.get(key_saturation) or "").strip() if key_saturation else ""
        if top is None or bottom is None:
            issues.append(f"интервал #{index}: нет числовых границ "
                          f"({key_top}/{key_bottom})")
            continue
        if bottom < top:
            issues.append(f"интервал #{index}: подошва выше кровли (GeoMate: "
                          f"{key_bottom} >= {key_top})")
        elif bottom == top:
            issues.append(f"интервал #{index}: нулевая мощность")
        if previous_bottom is not None and top < previous_bottom:
            issues.append(f"интервал #{index}: перекрытие с предыдущим "
                          f"({key_top} < предыдущая подошва)")
        if key_lithology and not lithology:
            issues.append(f"интервал #{index}: не задана литология "
                          f"({key_lithology})")
        if key_saturation and not saturation:
            issues.append(f"интервал #{index}: не задано насыщение "
                          f"({key_saturation})")
        previous_bottom = bottom
    if not ordered:
        return {"checked": 0, "issues": [], "status": STATUS_NOT_APPLICABLE}
    return {"checked": len(ordered), "issues": issues,
            "status": STATUS_OK if not issues else "issues"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def load_rules(cfg: Any = None, *, root: str | Path | None = None) -> dict:
    """Правила модулей из онтологии (см. `domain/petrofacies_data.load_rules`)."""
    return data.load_rules(cfg, root=root)
