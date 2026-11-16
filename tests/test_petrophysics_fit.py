#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Тесты модуля `domain/petrophysics_fit.py` (подгонка k = f(φ) и cut-off).

Проверяется БЕЗ запуска тНава:
  * правила (бланки, порог достаточности, r2_min, transform) приходят ИЗ ДАННЫХ
    онтологии, а не из кода;
  * бланк (в т.ч. LEGACY_NO_VALUE GeoMate) → None, НЕ ноль (правило 6);
  * подгонка идёт ОТДЕЛЬНО по литотипам, единая k-φ не строится (ограничение
    из онтологии), коэффициенты при недостатке пар НЕ подставляются;
  * cut-off выводится из МЕЧЕНОГО керна, нет меток → unknown без числа;
  * ни одного доменного значения в коде модуля нет (отдельная проверка —
    tests/test_no_domain_in_code.py).

Запуск: python tests/test_petrophysics_fit.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain import petrofacies_data as pdata          # noqa: E402
from domain import petrophysics_fit as pf             # noqa: E402
from core.config import load_config                   # noqa: E402

FAILED: list[str] = []
CHECKS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f"  <-- {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def synthetic(slope: float, intercept: float, lithotype: str, *,
              n: int = 40, phi0: float = 0.12, step: float = 0.002,
              noise: float = 0.0, seed: int = 1) -> list[dict]:
    """Пары керна с ЗАДАННОЙ связью log10(k) = slope·φ + intercept."""
    import math
    import random
    rng = random.Random(seed)
    rows = []
    for index in range(n):
        phi = phi0 + step * index
        log_k = slope * phi + intercept + (rng.uniform(-noise, noise) if noise else 0.0)
        rows.append({"porosity": round(phi, 6), "permeability": 10.0 ** log_k,
                     "lithotype": lithotype})
    return rows


def main() -> int:
    cfg = load_config()
    rules = pdata.load_rules(cfg)

    # ── 1. правила — ИЗ ДАННЫХ ───────────────────────────────────────────────
    check("правила: файлы онтологии прочитаны",
          "petrophysics_rules.yaml" in pdata.loaded_sources(rules)
          and "geomate_reuse_rules.yaml" in pdata.loaded_sources(rules),
          str(pdata.loaded_sources(rules)))
    check("правила: объявленные файлы доступны", not pdata.missing_sources(rules),
          str(pdata.missing_sources(rules)))
    check("правила: порог достаточности приходит из petrophysics_rules",
          pdata.min_pairs(rules) == 30, str(pdata.min_pairs(rules)))
    new_file = pdata.read_yaml(pdata.ontology_dir(cfg) / "petrofacies_methods.yaml")
    check("правила: порог не дублируется в новом файле данных",
          "core_data_contract" not in new_file,
          "min_pairs обязан жить в одном месте (petrophysics_rules.yaml)")
    check("правила: transform и r2_min — данные",
          pf.data.get(rules, "permeability_fit.transform") == "log10"
          and float(pf.data.get(rules, "permeability_fit.r2_min")) == 0.70,
          str(pf.data.get(rules, "permeability_fit.r2_min")))
    check("правила: лестница источников core → literature → unknown",
          [step.get("id") for step in pdata.source_ladder(rules)][:3]
          == ["core", "literature", "unknown"],
          str([step.get("id") for step in pdata.source_ladder(rules)]))

    # ── 2. бланки: нет данных != ноль ────────────────────────────────────────
    blanks = pdata.blank_values(rules)
    check("бланки: LEGACY_NO_VALUE GeoMate собран из данных",
          any(abs(value - 1.70141e10) < 1.0 for value in blanks), str(blanks))
    check("бланки: sentinel → None (не ноль)",
          pdata.is_blank(1.70141e10, rules) and pdata.clean_number(1.70141e10, rules) is None)
    check("бланки: LAS-бланк → None",
          pdata.clean_number(-999.25, rules) is None)
    check("бланки: обычный ноль — НЕ бланк",
          pdata.clean_number(0.0, rules) == 0.0 and not pdata.is_blank(0.0, rules))
    check("бланки: нечисло → None, не исключение",
          pdata.clean_number("нет данных", rules) is None)

    # ── 3. точное восстановление связи по литотипам ──────────────────────────
    rows = synthetic(2.5, 2.0, "A") + synthetic(1.2, 0.5, "B", phi0=0.10, step=0.003)
    result = pf.fit_from_rows(rows, rules)
    check("подгонка: статус ok", result["status"] == "ok", str(result["status"]))
    check("подгонка: два литотипа — две отдельные зависимости",
          sorted(result["lithotypes"]) == ["A", "B"], str(result["lithotypes"]))
    by_lith = {item["lithotype"]: item for item in result["fits"]}
    check("подгонка: коэффициенты восстановлены (A)",
          abs(by_lith["A"]["slope"] - 2.5) < 1e-6
          and abs(by_lith["A"]["intercept"] - 2.0) < 1e-6,
          str(by_lith.get("A")))
    check("подгонка: коэффициенты восстановлены (B)",
          abs(by_lith["B"]["slope"] - 1.2) < 1e-6
          and abs(by_lith["B"]["intercept"] - 0.5) < 1e-6,
          str(by_lith.get("B")))
    check("подгонка: r2 посчитан и высокий",
          all(item["r2"] is not None and item["r2"] > 0.99 for item in result["fits"]),
          str([item.get("r2") for item in result["fits"]]))
    check("подгонка: n_pairs по каждому литотипу",
          all(item["n_pairs"] == 40 for item in result["fits"]),
          str([item["n_pairs"] for item in result["fits"]]))
    check("подгонка: источник = core (эксперимент)",
          all(item["source"] == pf.SOURCE_CORE for item in result["fits"]))
    check("подгонка: единая k-φ НЕ строится (ограничение онтологии)",
          result["pooled"] is None and not result["pooled_allowed"], str(result["pooled"]))
    check("подгонка: причина отказа ссылается на правило из данных",
          any(str(item) for item in pdata.constraints(rules))
          and all(item in " ".join(result["issues"]) for item in pdata.constraints(rules)),
          str(result["issues"]))

    # ── 4. недостаток пар: коэффициенты НЕ выдумываются (правило 6) ──────────
    small = pf.fit_from_rows(rows[:5], rules)
    fit_small = small["fits"][0]
    check("недостаток пар: статус insufficient",
          fit_small["status"] == pf.STATUS_INSUFFICIENT, str(fit_small["status"]))
    check("недостаток пар: источник = literature (лестница из данных)",
          fit_small["source"] == pf.SOURCE_LITERATURE, str(fit_small["source"]))
    check("недостаток пар: коэффициенты НЕ подставлены",
          fit_small["slope"] is None and fit_small["intercept"] is None
          and fit_small["usable"] is False, str(fit_small))
    check("недостаток пар: порог назван в причине",
          str(small["min_pairs"]) in fit_small["reason"], fit_small["reason"])

    # порог — ДАННЫЕ: ослабляем его в копии правил → та же выборка подгоняется
    relaxed = copy.deepcopy(rules)
    relaxed["core_data_contract"]["min_pairs"] = 3
    small_ok = pf.fit_from_rows(rows[:5], relaxed)
    check("порог достаточности берётся из данных (ослабили → подгонка возможна)",
          small_ok["fits"][0]["status"] == pf.STATUS_OK
          and small_ok["fits"][0]["usable"], str(small_ok["fits"][0]))

    # ── 5. слабая связь: коэффициенты есть, но под флагом низкого r2 ─────────
    noisy = synthetic(2.5, 2.0, "A", noise=3.0, seed=7)
    strong = copy.deepcopy(rules)
    strong["core_data_contract"]["min_pairs"] = 5
    noisy_result = pf.fit_from_rows(noisy, strong)
    noisy_fit = noisy_result["fits"][0]
    check("слабый r2: статус low_r2 при коэффициентах ИЗ КЕРНА",
          noisy_fit["status"] == pf.STATUS_LOW_R2 and noisy_fit["usable"],
          str(noisy_fit["status"]))
    check("слабый r2: порог r2 взят из данных",
          noisy_fit["r2_min"] == 0.70, str(noisy_fit.get("r2_min")))
    check("слабый r2: причина называет порог",
          "0.7" in noisy_fit["reason"], noisy_fit["reason"])

    # ── 6. вырожденная выборка (одно значение φ) ─────────────────────────────
    degenerate = [{"porosity": 0.2, "permeability": 10 ** (0.2 * index),
                   "lithotype": "A"} for index in range(1, 32)]
    deg_fit = pf.fit_from_rows(degenerate, rules)["fits"][0]
    check("вырожденная выборка: статус degenerate, коэффициентов нет",
          deg_fit["status"] == pf.STATUS_DEGENERATE and deg_fit["slope"] is None,
          str(deg_fit["status"]))

    # ── 7. роли колонок и масштаб — из ДАННЫХ ────────────────────────────────
    alternate = [{"poro": row["porosity"], "perm": row["permeability"],
                  "lithology": row["lithotype"]} for row in rows]
    alt = pf.fit_from_rows(alternate, rules)
    check("колонки: альтернативные имена найдены по данным онтологии",
          alt["status"] == "ok" and sorted(alt["lithotypes"]) == ["A", "B"],
          str(alt["status"]))
    unknown_columns = pf.fit_from_rows([{"x": 1, "y": 2}], rules)
    check("колонки: неизвестные имена → not_applicable (не выдумываем)",
          unknown_columns["status"] == pf.STATUS_NOT_APPLICABLE
          and unknown_columns["fits"] == [], str(unknown_columns["status"]))
    check("колонки: причина перечисляет кандидатов из данных",
          all(candidate in " ".join(unknown_columns["issues"])
              for candidate in pdata.column_candidates(rules, "porosity")),
          str(unknown_columns["issues"]))

    percent = [{"porosity": 100 * row["porosity"], "permeability": row["permeability"],
                "lithotype": row["lithotype"]} for row in rows]
    scaled = pf.fit_from_rows(percent, rules)
    check("масштаб: проценты приведены к долям по данным",
          scaled["status"] == "ok" and scaled["fits"][0]["phi_max"]
          == by_lith["A"]["phi_max"], str(scaled["fits"][0].get("phi_max")))
    check("масштаб: пояснение зафиксировано в issues",
          any("дол" in item for item in scaled["issues"]), str(scaled["issues"]))

    with_blank = rows[:10] + [{"porosity": 0.2, "permeability": 1.70141e10,
                               "lithotype": "A"} for _ in range(30)]
    blanked = pf.fit_from_rows(with_blank, rules)
    check("бланки в керне: исключены, а не приняты за ноль",
          blanked["skipped"]["blank_permeability"] == 30
          and blanked["fits"][0]["n_pairs"] == 10, str(blanked["skipped"]))
    nonpositive = rows[:10] + [{"porosity": 0.2, "permeability": -5.0,
                                "lithotype": "A"} for _ in range(30)]
    check("неположительная проницаемость: не логируется и не считается",
          pf.fit_from_rows(nonpositive, rules)["skipped"]["nonpositive_permeability"] == 30)

    # ── 8. применение зависимости (подготовка куба K) ────────────────────────
    applied = pf.apply_fit(by_lith["A"], [0.2, 0.25, None, -999.25], rules)
    check("применение: log10(k) по каждой ячейке",
          abs(applied["values"][0] - (2.5 * 0.2 + 2.0)) < 1e-9
          and abs(applied["values"][1] - (2.5 * 0.25 + 2.0)) < 1e-9,
          str(applied["values"]))
    check("применение: бланк и None → None",
          applied["values"][2] is None and applied["values"][3] is None)
    check("применение: статус и источник переносятся",
          applied["status"] == pf.STATUS_OK and applied["source"] == pf.SOURCE_CORE)
    not_usable = pf.apply_fit(pf.fit_from_rows(rows[:5], rules)["fits"][0],
                              [0.2, 0.3], rules)
    check("применение: без керна коэффициенты НЕ подставляются",
          not_usable["values"] == [None, None] and not not_usable["usable"],
          str(not_usable))
    guard = pf.apply_fit(by_lith["A"], [0.9], rules)
    check("применение: экстраполяция вне диапазона керна под флагом",
          guard["outside_range"] == 1
          and any("вне диапазона" in item for item in guard["issues"]),
          str(guard))

    # ── 9. cut-off по МЕЧЕНОМУ керну ─────────────────────────────────────────
    labelled = [dict(row, reservoir=1 if row["permeability"] > 10 else 0) for row in rows]
    cut = pf.cutoff_from_labelled_core(labelled, rules)
    check("cut-off: статус ok и порог в мД (не константа)",
          cut["status"] == pf.STATUS_OK and cut["value"] is not None
          and cut["value"] > 0, str(cut.get("value")))
    check("cut-off: метод и происхождение — из данных",
          cut["method"] == str(pdata.get(rules, "cutoff.method"))
          and bool(cut["provenance"]), str(cut["method"]))
    check("cut-off: сбалансированная точность разделения",
          cut["balanced_accuracy"] is not None and cut["balanced_accuracy"] >= 0.9,
          str(cut.get("balanced_accuracy")))
    few = pf.cutoff_from_labelled_core(
        [dict(row, reservoir=1 if index < 2 else 0) for index, row in enumerate(rows[:20])],
        rules)
    check("cut-off: мало наблюдений в классе → unknown без числа",
          few["status"] == pf.STATUS_INSUFFICIENT and few["value"] is None,
          str(few["status"]))
    check("cut-off: нет меток → not_applicable без числа",
          pf.cutoff_from_labelled_core(rows, rules)["status"] == pf.STATUS_NOT_APPLICABLE)
    check("cut-off: метка вне словарей данных → unknown-класс исключён",
          pf.cutoff_from_labelled_core([dict(row, reservoir="???") for row in rows],
                                       rules)["skipped"]["unknown_label"] == len(rows))
    check("cut-off: ни одного доменного значения в коде настройки",
          bool(pdata.get(rules, "cutoff.provenance")))

    # ── 10. пустые данные: not_applicable/unknown, не ноль ───────────────────
    empty = pf.fit_from_rows([], rules)
    check("нет данных: fit not_applicable, fits пустой",
          empty["status"] == pf.STATUS_NOT_APPLICABLE and empty["fits"] == []
          and empty["n_pairs_total"] == 0, str(empty["status"]))
    check("нет данных: причины зафиксированы, числа не выдуманы",
          empty["pooled"] is None and empty["min_pairs"] == pdata.min_pairs(rules))

    print(f"\n=== ИТОГ ===\nпроверок: {CHECKS} | провалено: {len(FAILED)}")
    for item in FAILED:
        print("  -", item)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
