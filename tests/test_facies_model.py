#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Тесты модуля `domain/facies_model.py` (фации: порядок, доли, связность, тела).

Проверяется БЕЗ запуска тНава:
  * порядок классов и настройки расчёта (соседство, порог скважин, минимальный
    размер тела, предел объёма) приходят ИЗ ДАННЫХ онтологии;
  * нет данных → `unknown`/`not_applicable`, а не нули и не «доли из воздуха»
    (правило 6);
  * связность/число тел считаются по кубу кодов и зависят от данных (6/18/26);
  * NTG считается только при карте ролей «код → коллектор/нет» из данных;
  * параметры шага фаций патчатся ТОЛЬКО для кода, объявленного в онтологии И
    присутствующего в ШАБЛОНЕ функции (правило 8 — тНав не выдумываем);
  * проверки интервалов работают по ключам контракта из онтологии.

Запуск: python tests/test_facies_model.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain import facies_model as fm            # noqa: E402
from domain import petrofacies_data as pdata     # noqa: E402
from core.config import load_config              # noqa: E402

FAILED: list[str] = []
CHECKS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f"  <-- {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def volume_with_blobs(shape: tuple[int, int, int], code: int,
                      blocks: list[tuple[slice, slice, slice]],
                      fill: int = 0) -> list[int]:
    """Куб кодов с заданными блоками-телами (индексы — x, y, z)."""
    nx, ny, nz = shape
    volume = [fill] * (nx * ny * nz)
    for bx, by, bz in blocks:
        for x in range(*bx.indices(nx)):
            for y in range(*by.indices(ny)):
                for z in range(*bz.indices(nz)):
                    volume[(y * nx + x) * nz + z] = code
    return volume


def main() -> int:
    cfg = load_config()
    rules = pdata.load_rules(cfg)
    spec = pdata.section(rules, "facies_model")

    # ── 1. настройки — ИЗ ДАННЫХ ─────────────────────────────────────────────
    check("правила: секция facies_model прочитана из онтологии", bool(spec), str(list(spec)[:6]))
    check("правила: порядок/соседство/порог скважин заданы данными",
          all(key in spec for key in ("order_by", "neighbourhood", "min_wells",
                                      "min_body_cells", "roles_required")),
          str(sorted(spec)))
    check("правила: допустимые соседства — данные",
          spec.get("neighbourhood_options") == [6, 18, 26],
          str(spec.get("neighbourhood_options")))
    check("правила: коды параметров тНава НЕ выдуманы (пусто до пробы)",
          spec.get("patch_codes") == {},
          str(spec.get("patch_codes")))

    # ── 2. коды и порядок ────────────────────────────────────────────────────
    check("коды: 1 и 1.0 — один класс",
          fm.normalise_code(1) == fm.normalise_code(1.0) == "1")
    check("коды: None/бланк → пусто (не класс)",
          fm.normalise_code(None) == "" and fm.normalise_code("nan") == "")
    order = fm.class_order([8, 1, 2, "1", 0], rules)
    check("порядок: по умолчанию сортировка кодов (данные)",
          order["order"] == ["0", "1", "2", "8"] and order["order_by"] == "code",
          str(order))
    explicit = copy.deepcopy(rules)
    explicit["facies_model"]["order_by"] = "explicit"
    explicit["facies_model"]["explicit_order"] = [2, 1, 8]
    order2 = fm.class_order([1, 2, 3, 8], explicit)
    check("порядок: явный перечень из данных соблюдён",
          order2["order"][:3] == ["2", "1", "8"], str(order2["order"]))
    check("порядок: коды вне перечня — в конец и помечены unknown",
          order2["order"][-1] == "3" and order2["unknown_codes"] == ["3"],
          str(order2))
    check("порядок: объявленные, но отсутствующие коды видны отдельно",
          fm.class_order([1], explicit)["declared_absent"] == ["2", "8"],
          str(fm.class_order([1], explicit)))

    # ── 3. связность и тела ──────────────────────────────────────────────────
    shape = (4, 4, 2)
    two_blobs = volume_with_blobs(shape, 1, [
        (slice(0, 2), slice(0, 2), slice(0, 2)),
        (slice(2, 4), slice(2, 4), slice(0, 2)),
    ], fill=2)
    stats = fm.connectivity_stats(two_blobs, shape, code=1, neighbourhood=6)
    check("тела: два раздельных тела найдены",
          stats["bodies"] == 2 and stats["cells"] == 16, str(stats))
    check("тела: крупнейшее тело и его доля",
          stats["largest_body_cells"] == 8 and stats["largest_body_share"] == 0.5,
          str(stats))
    whole = fm.connectivity_stats(two_blobs, shape, code=2, neighbourhood=6)
    check("тела: фоновый класс посчитан отдельно", whole["cells"] == 16, str(whole))

    diagonal = [1, 0, 0, 0, 0, 0, 0, 1]
    cube_shape = (2, 2, 2)
    six = fm.connectivity_stats(diagonal, cube_shape, code=1, neighbourhood=6)
    twenty_six = fm.connectivity_stats(diagonal, cube_shape, code=1, neighbourhood=26)
    check("соседство: 6 vs 26 меняет число тел (параметр — ДАННЫЕ)",
          six["bodies"] == 2 and twenty_six["bodies"] == 1,
          f"6:{six['bodies']} 26:{twenty_six['bodies']}")
    speck = [1, 1, 0, 1]
    coarse = copy.deepcopy(rules)
    coarse["facies_model"]["min_body_cells"] = 2
    speck_stats = fm.connectivity_stats(speck, (4, 1, 1), code=1, neighbourhood=6,
                                        min_body_cells=2)
    check("минимальный размер тела: одиночная ячейка не считается телом",
          speck_stats["bodies"] == 1 and speck_stats["largest_body_cells"] == 2
          and speck_stats["cells"] == 3, str(speck_stats))
    check("минимальный размер тела: с порогом 1 тел два",
          fm.connectivity_stats(speck, (4, 1, 1), code=1, neighbourhood=6,
                                min_body_cells=1)["bodies"] == 2)
    capped_bodies = fm.aggregate_facies(volume=speck, shape=(4, 1, 1),
                                        rules=coarse)
    check("минимальный размер тела: порог применяется из данных",
          capped_bodies["connectivity"]["per_class"]["1"]["bodies"] == 1,
          str(capped_bodies["connectivity"]))
    bad = copy.deepcopy(rules)
    bad["facies_model"]["neighbourhood"] = 4
    try:
        fm.connectivity_stats(diagonal, cube_shape, code=1, neighbourhood=4)
        fm.aggregate_facies(volume=diagonal, shape=cube_shape, rules=bad)
        check("соседство: недопустимое значение из данных → понятная ошибка", False,
              "ValueError не поднят")
    except ValueError as error:
        check("соседство: недопустимое значение из данных → понятная ошибка",
              "6" in str(error) and "26" in str(error), str(error))
    try:
        fm.connectivity_stats([1, 2, 3], (2, 2, 2), code=1)
        check("геометрия: несоответствие числа ячеек → ошибка", False)
    except ValueError as error:
        check("геометрия: несоответствие числа ячеек → ошибка", True, str(error))

    # ── 4. агрегаты по кубу ──────────────────────────────────────────────────
    out = fm.aggregate_facies(volume=two_blobs, shape=shape, rules=rules,
                              roles={1: "reservoir", 2: "barrier"})
    check("агрегат: статус ok, ячейки посчитаны",
          out["status"] == "ok" and out["cells"] == 32, str(out["status"]))
    check("агрегат: доли классов суммируются в единицу",
          abs(sum(out["proportions"].values()) - 1.0) < 1e-12, str(out["proportions"]))
    check("агрегат: связность и тела по классам",
          out["connectivity"]["per_class"]["1"]["bodies"] == 2
          and out["connectivity"]["neighbourhood"] == 6, str(out["connectivity"]))
    check("агрегат: роли классов перенесены из данных",
          {item["code"]: item["role"] for item in out["classes"]}
          == {"1": "reservoir", "2": "barrier"}, str(out["classes"]))
    check("агрегат: NTG по карте ролей",
          out["net_to_gross"] == 0.5 and out["reservoir_share"] == 0.5,
          str(out.get("net_to_gross")))
    no_roles = fm.aggregate_facies(volume=two_blobs, shape=shape, rules=rules)
    check("агрегат: без карты ролей NTG = unknown (не ноль)",
          no_roles["net_to_gross"] is None
          and any("карта ролей" in item for item in no_roles["unknown"]),
          str(no_roles["unknown"]))
    partial = fm.aggregate_facies(volume=two_blobs, shape=shape, rules=rules,
                                  roles={1: "reservoir"})
    check("агрегат: неполная карта ролей → NTG unknown с причиной",
          partial["net_to_gross"] is None
          and any("нет роли для кодов" in item for item in partial["unknown"]),
          str(partial["unknown"]))

    # предел объёма расчёта связности — ДАННЫЕ
    limited = copy.deepcopy(rules)
    limited["facies_model"]["connectivity_max_cells"] = 8
    capped = fm.aggregate_facies(volume=two_blobs, shape=shape, rules=limited)
    check("предел объёма: связность честно unknown, классы посчитаны",
          capped["status"] == "ok" and capped["connectivity"]["status"] == "unknown"
          and any("предел" in item for item in capped["unknown"]),
          str(capped["unknown"]))

    # ── 5. доли по скважинам ─────────────────────────────────────────────────
    wells = {"w1": [1, 1, 2], "w2": [1, 2, 2], "w3": [1, 1, 1]}
    props = fm.proportions_from_wells(wells, rules)
    check("скважины: доли посчитаны и нормированы",
          props["status"] == "ok" and abs(sum(props["proportions"].values()) - 1.0) < 1e-12,
          str(props["proportions"]))
    check("скважины: классы упорядочены по данным",
          props["classes"] == ["1", "2"], str(props["classes"]))
    few_wells = fm.proportions_from_wells({"w1": [1, 2], "w2": [1]}, rules)
    check("скважины: меньше порога → unknown без долей",
          few_wells["status"] == "unknown" and few_wells["proportions"] == {}
          and few_wells["min_wells"] == spec.get("min_wells"), str(few_wells))
    check("скважины: данных нет → not_applicable",
          fm.proportions_from_wells({}, rules)["status"] == "not_applicable")
    blank_codes = {"w1": [1, None, 2], "w2": [1, 2, 2], "w3": [1, 1, 1]}
    blank_props = fm.proportions_from_wells(blank_codes, rules)
    check("скважины: бланковый отсчёт не отнесён к классу (не ноль-класс)",
          "0" not in blank_props["proportions"]
          and any("бланковых" in item for item in blank_props["unknown"]),
          str(blank_props))

    # ── 6. куб + скважины вместе ─────────────────────────────────────────────
    both = fm.aggregate_facies(volume=two_blobs, shape=shape, well_codes=wells,
                               roles={1: "reservoir", 2: "barrier"}, rules=rules)
    check("куб+скважины: оба источника зафиксированы",
          both["wells"] == 3 and "proportions_from_wells" in both, str(list(both)))
    check("куб+скважины: доли куба не подменяются скважинными",
          abs(both["proportions"]["1"] - 0.5) < 1e-12, str(both["proportions"]))

    # ── 7. пустые данные ─────────────────────────────────────────────────────
    nothing = fm.aggregate_facies(rules=rules)
    check("нет данных: not_applicable и причина",
          nothing["status"] == "not_applicable" and nothing["classes"] == []
          and any("данных фаций нет" in item for item in nothing["unknown"]),
          str(nothing["unknown"]))
    empty_volume = fm.aggregate_facies(volume=[], shape=(0, 0, 0), rules=rules)
    check("пустой куб: not_applicable, связность не выдумывается",
          empty_volume["status"] == "not_applicable"
          and empty_volume["proportions"] == {}, str(empty_volume["status"]))
    blanks = fm.aggregate_facies(volume=[None, None], shape=(2, 1, 1), rules=rules)
    check("бланковые ячейки: не класс, зафиксированы в unknown",
          blanks["classes"] == [] and any("бланковых ячеек" in item
                                          for item in blanks["unknown"]),
          str(blanks["unknown"]))

    # ── 8. параметры шага фаций (правило 8) ──────────────────────────────────
    aggregate = {"proportions": {"1": 0.6, "2": 0.4}, "classes": [{"code": "1"}],
                 "order": ["1", "2"], "net_to_gross": 0.6, "reservoir_share": 0.6,
                 "wells": 3, "cells": 100}
    with_codes = copy.deepcopy(rules)
    with_codes["facies_model"]["patch_codes"] = {"code_a": "proportions",
                                                 "code_b": "net_to_gross",
                                                 "code_c": "wells"}
    template = "step = call(code_a=X, code_b=Y)\n"
    patch, unknown = fm.facies_step_parameters(aggregate, with_codes,
                                               template_text=template)
    check("параметры: код в шаблоне → патч применён",
          patch == {"code_a": aggregate["proportions"],
                    "code_b": aggregate["net_to_gross"]}, str(patch))
    check("параметры: кода нет в шаблоне → unknown, патч не применён",
          "code_c" not in patch
          and any("code_c" in item and "нет в шаблоне" in item for item in unknown),
          str(unknown))
    patch_no_template, unknown_no_template = fm.facies_step_parameters(
        aggregate, with_codes)
    check("параметры: шаблон не передан → патч не применён, unknown",
          patch_no_template == {} and len(unknown_no_template) == 3,
          str(unknown_no_template))
    empty_value, unknown_value = fm.facies_step_parameters(
        {"proportions": {}, "net_to_gross": None, "classes": []}, with_codes,
        template_text=template)
    check("параметры: нет значения → unknown, а не ноль",
          empty_value == {} and len(unknown_value) == 3, str(unknown_value))
    no_codes, no_codes_unknown = fm.facies_step_parameters(aggregate, rules,
                                                           template_text=template)
    check("параметры: коды не объявлены в данных → патча нет (тНав не выдумываем)",
          no_codes == {} and any("не заданы в онтологии" in item
                                 for item in no_codes_unknown), str(no_codes_unknown))

    # ── 9. проверки интервалов по ключам из данных ───────────────────────────
    intervals = [
        {"top": 10.0, "bottom": 12.0, "lithology": "a", "saturation": "b"},
        {"top": 11.5, "bottom": 13.0, "lithology": "", "saturation": "b"},
        {"top": 14.0, "bottom": 14.0, "lithology": "a", "saturation": "b"},
    ]
    validation = fm.validate_intervals(intervals, rules)
    check("интервалы: перекрытие/нулевая мощность/пустая литология найдены",
          validation["status"] == "issues" and len(validation["issues"]) == 3,
          str(validation["issues"]))
    check("интервалы: нет данных → not_applicable",
          fm.validate_intervals([], rules)["status"] == "not_applicable")
    renamed = copy.deepcopy(rules)
    renamed["interval_fields"] = {"top": "md_from", "bottom": "md_to",
                                  "lithology": "rock", "saturation": "fluid"}
    renamed_validation = fm.validate_intervals(
        [{"md_from": 5.0, "md_to": 4.0, "rock": "a", "fluid": "b"}], renamed)
    check("интервалы: ключи берутся из данных онтологии",
          renamed_validation["status"] == "issues"
          and any("подошва выше кровли" in item for item in renamed_validation["issues"]),
          str(renamed_validation))
    missing_keys = copy.deepcopy(rules)
    missing_keys["interval_fields"] = {}
    check("интервалы: ключей нет в данных → unknown (не «всё хорошо»)",
          fm.validate_intervals(intervals, missing_keys)["status"] == "unknown")

    print(f"\n=== ИТОГ ===\nпроверок: {CHECKS} | провалено: {len(FAILED)}")
    for item in FAILED:
        print("  -", item)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
