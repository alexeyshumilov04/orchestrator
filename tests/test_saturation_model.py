#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Тесты модуля насыщения (`domain/saturation_model.py`) и его вызовов агентами.

Проверяется БЕЗ запуска тНава:
  * правила (формула J, колонки, пороги достаточности, концевые точки, единицы
    угла) приходят ИЗ ДАННЫХ онтологии; у них есть provenance и knowledge_status;
  * J(Sw) = (Pc/(σ·cosθ))·√(k/φ) восстанавливается на синтетике (A, B, r2);
  * нет SCAL-данных → `not_applicable`; нет σ/θ, мало точек, нет k/φ →
    `insufficient`/`candidate` — ни одно число не выдумывается (правило 6);
  * концевые точки — ИЗ ДАННЫХ и не публикуются при недостатке наблюдений;
  * обращение J → Sw работает только по годной подгонке;
  * агенты (`SaturationAgent`, `PetrophysicsAgent`) ВЫЗЫВАЮТ модули, читают
    правила из онтологии и честно сообщают статус при отсутствии данных.

Запуск: python tests/test_saturation_model.py
"""
from __future__ import annotations

import copy
import csv
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_config                       # noqa: E402
from domain import petrofacies_data as pdata              # noqa: E402
from domain import saturation_model as sm                 # noqa: E402

FAILED: list[str] = []
CHECKS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f"  <-- {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def synthetic(a: float, b: float, rock: str, *, n: int = 12, sigma: float = 0.03,
              theta: float = 0.0, perm: float = 0.2, poro: float = 0.2,
              noise: float = 0.0, seed: int = 3) -> list[dict]:
    """Точки SCAL с ЗАДАННОЙ J(Sw) = a·Sw^(−b): Pc = J·σ·cosθ/√(k/φ)."""
    import random
    rng = random.Random(seed)
    rows = []
    for index in range(n):
        sw = 0.2 + 0.05 * index
        j = a * sw ** (-b) * (1.0 + (rng.uniform(-noise, noise) if noise else 0.0))
        pc = j * sigma * 1.0 / math.sqrt(perm / poro)
        rows.append({"pc": pc, "sw": sw, "sigma": sigma, "theta": theta,
                     "permeability": perm, "porosity": poro, "rock_type": rock})
    return rows


def main() -> int:
    cfg = load_config()
    rules = pdata.load_rules(cfg)

    # ── 1. правила насыщения — ИЗ ДАННЫХ, с provenance ──────────────────────
    section = pdata.section(rules, "saturation")
    check("правила: секция saturation загружена из онтологии",
          all(key in section for key in ("columns", "tables", "j_function", "fit",
                                         "end_points", "applicability")),
          str(sorted(section)))
    j_spec = pdata.section(rules, "saturation.j_function")
    check("правила: формула J и единицы угла заданы данными",
          bool(j_spec.get("formula")) and j_spec.get("theta_units") == "deg",
          str({k: j_spec.get(k) for k in ("formula", "theta_units")}))
    check("правила: у J-функции литературный источник и статус EVIDENCE_BACKED",
          j_spec.get("source_rule") == "RULE_LIT_PETRO_060"
          and j_spec.get("source_ids") == ["LIT-0625#p15"]
          and j_spec.get("knowledge_status") == "EVIDENCE_BACKED_CANDIDATE",
          str({k: j_spec.get(k) for k in ("source_rule", "source_ids",
                                          "knowledge_status")}))
    fit_spec = pdata.section(rules, "saturation.fit")
    check("правила: порог достаточности и r2 — данные",
          int(fit_spec.get("min_pairs")) == 10 and float(fit_spec.get("r2_min")) == 0.70,
          str({k: fit_spec.get(k) for k in ("min_pairs", "r2_min")}))
    check("правила: порог достаточности помечен как инженерный допуск",
          "engineering_default" in str(fit_spec.get("min_pairs_provenance") or ""),
          str(fit_spec.get("min_pairs_provenance"))[:80])
    ep_spec = pdata.section(rules, "saturation.end_points")
    check("правила: концевые точки — по керну/SCAL, provenance обязателен",
          ep_spec.get("source_rule") == "RULE_LIT_SCAL_010"
          and ep_spec.get("knowledge_status") == "REQUIRES_SOURCE"
          and "констант" in str(ep_spec.get("provenance") or ""),
          str({k: ep_spec.get(k) for k in ("source_rule", "knowledge_status")}))
    check("правила: матрицы SCAL поля → роли колонок (данные)",
          pdata.get(rules, "saturation.tables.swof")[:2] == ["sw", "krw"],
          str(pdata.get(rules, "saturation.tables.swof")))

    # ── 2. J(Sw): восстановление связи ──────────────────────────────────────
    rows = synthetic(0.5, 1.8, "A")
    result = sm.fit_from_rows(rows, rules)
    fit = result["j_fit"]["fits"][0]
    check("J(Sw): статус ok и источник scal (нормировка по k/φ)",
          result["status"] == "ok" and fit["status"] == "ok"
          and fit["source"] == "scal" and fit["normalisation"] == "sqrt_k_over_phi",
          str(fit))
    check("J(Sw): коэффициенты восстановлены (A, B)",
          abs(fit["a"] - 0.5) < 1e-9 and abs(fit["b"] - 1.8) < 1e-9, str(fit))
    check("J(Sw): r2 и число точек посчитаны",
          fit["r2"] is not None and fit["r2"] > 0.999 and fit["n_pairs"] == 12,
          str({k: fit.get(k) for k in ("r2", "n_pairs")}))
    check("J(Sw): знание помечено как EVIDENCE_BACKED (не «факт»)",
          result["j_fit"]["knowledge_status"] == "EVIDENCE_BACKED_CANDIDATE"
          and result["j_fit"]["source_rule"] == "RULE_LIT_PETRO_070",
          str(result["j_fit"]["knowledge_status"]))
    check("J(Sw): единая зависимость не строится (нужна типизация пород)",
          result["j_fit"]["pooled"] is None
          and any("единая J(Sw)" in item for item in result["j_fit"]["issues"]),
          str(result["j_fit"]["issues"]))

    two = sm.fit_from_rows(synthetic(0.5, 1.8, "A") + synthetic(2.0, 1.2, "B"), rules)
    by_rock = {item["rock_type"]: item for item in two["j_fit"]["fits"]}
    check("J(Sw): подгонка ОТДЕЛЬНО по типам породы",
          sorted(by_rock) == ["A", "B"]
          and abs(by_rock["A"]["a"] - 0.5) < 1e-9 and abs(by_rock["B"]["a"] - 2.0) < 1e-9,
          str({k: (v["a"], v["b"]) for k, v in by_rock.items()}))

    # ── 3. нет данных / нет обязательных колонок ────────────────────────────
    empty = sm.fit_from_rows([], rules)
    check("нет данных: not_applicable и причина (не число)",
          empty["status"] == "not_applicable" and empty["j_fit"]["fits"] == []
          and any("SCAL" in item for item in empty["issues"]), str(empty["status"]))
    missing = sm.fit_from_rows([{"pc": 1.0, "sw": 0.5}], rules)
    check("нет σ/θ: insufficient, J не строится",
          missing["status"] == "insufficient"
          and missing["j_fit"]["status"] == "insufficient", str(missing["status"]))
    check("нет σ/θ: причина перечисляет кандидатов колонок из онтологии",
          all(candidate in " ".join(missing["issues"])
              for candidate in pdata.get(rules, "saturation.columns.sigma")[:2]),
          str(missing["issues"][:2]))
    few = sm.fit_from_rows(synthetic(0.5, 1.8, "A", n=4), rules)
    few_fit = few["j_fit"]["fits"][0]
    check("мало точек: insufficient, коэффициенты не публикуются",
          few["status"] == "insufficient" and few_fit["status"] == "insufficient"
          and few_fit["a"] is None and few_fit["b"] is None, str(few_fit))
    check("мало точек: порог назван в причине",
          str(int(fit_spec.get("min_pairs"))) in few_fit["reason"], few_fit["reason"])
    no_normaliser = sm.fit_from_rows(
        [dict(row, permeability=None, porosity=None) for row in rows], rules)
    cand = no_normaliser["j_fit"]["fits"][0]
    check("нет k/φ: разрешён кандидат без нормировки (статус candidate, не scal)",
          no_normaliser["status"] == "ok" and cand["source"] == "candidate"
          and cand["normalisation"] == "pc_over_sigma", str(cand))
    strict = copy.deepcopy(rules)
    strict["saturation"]["j_function"]["on_missing_normaliser"] = "insufficient"
    strict_result = sm.fit_from_rows(
        [dict(row, permeability=None, porosity=None) for row in rows], strict)
    check("нет k/φ при строгом правиле: insufficient (правило — данные)",
          strict_result["status"] == "insufficient"
          and strict_result["j_fit"]["fits"] == [],
          str(strict_result["j_fit"]["status"]))
    no_units = copy.deepcopy(rules)
    no_units["saturation"]["j_function"].pop("theta_units", None)
    units_result = sm.fit_from_rows(rows, no_units)
    check("нет единиц угла в правилах: insufficient с причиной",
          units_result["status"] == "insufficient"
          and any("угла" in item for item in units_result["issues"]),
          str(units_result["issues"][:2]))
    weak = sm.fit_from_rows(synthetic(0.5, 1.8, "A", noise=0.9, seed=5), rules)
    weak_fit = weak["j_fit"]["fits"][0]
    check("слабый r2: коэффициенты есть, но статус low_r2",
          weak_fit["status"] == "low_r2" and weak_fit["a"] is not None
          and weak_fit["r2"] < 0.70, str({k: weak_fit.get(k) for k in ("status", "r2")}))

    # ── 4. бланки и мусор ───────────────────────────────────────────────────
    dirty = rows + [{"pc": 1.70141e10, "sw": 0.5, "sigma": 0.03, "theta": 0.0,
                     "permeability": 0.2, "porosity": 0.2, "rock_type": "A"},
                    {"pc": 1.0, "sw": -999.25, "sigma": 0.03, "theta": 0.0,
                     "permeability": 0.2, "porosity": 0.2, "rock_type": "A"},
                    {"pc": 1.0, "sw": 1.5, "sigma": 0.03, "theta": 0.0,
                     "permeability": 0.2, "porosity": 0.2, "rock_type": "A"}]
    dirty_result = sm.fit_from_rows(dirty, rules)
    skipped = dirty_result["skipped"]
    check("бланки и мусор: отброшены, а не приняты за ноль",
          skipped.get("blank_pc") == 1 and skipped.get("blank_sw") == 1
          and skipped.get("sw_out_of_range") == 1, str(skipped))
    check("бланки: на подгонку не влияют (те же коэффициенты)",
          abs(dirty_result["j_fit"]["fits"][0]["a"] - 0.5) < 1e-9,
          str(dirty_result["j_fit"]["fits"][0].get("a")))
    no_scales = copy.deepcopy(rules)
    no_scales["saturation"]["j_function"]["unit_scales"] = {}
    scale_result = sm.fit_from_rows(rows, no_scales)
    check("единицы без множителей: перечислены в units_assumed (не «всё сошлось»)",
          set(scale_result["units_assumed"]) == {"pc", "sigma", "permeability"},
          str(scale_result["units_assumed"]))

    # ── 5. концевые точки ───────────────────────────────────────────────────
    ends = sm.fit_from_rows(rows, rules)["end_points"]
    check("концевые точки: Sw_irr/Sw_max из данных",
          ends["status"] == "ok" and abs(ends["values"]["sw_irr"] - 0.2) < 1e-9
          and abs(ends["values"]["sw_max"] - 0.75) < 1e-9, str(ends))
    check("концевые точки: источник — правило RULE_LIT_SCAL_010",
          ends["source_rule"] == "RULE_LIT_SCAL_010"
          and ends["knowledge_status"] == "REQUIRES_SOURCE", str(ends))
    few_ends = sm.fit_from_rows(synthetic(0.5, 1.8, "A", n=3), rules)["end_points"]
    check("концевые точки: мало наблюдений → значение НЕ публикуется",
          few_ends["values"] == {} and few_ends["status"] == "insufficient",
          str(few_ends))
    no_ep_rules = copy.deepcopy(rules)
    no_ep_rules["saturation"].pop("end_points", None)
    check("концевые точки: правила не заданы → unknown без числа",
          sm.end_points(rows, no_ep_rules)["status"] == "unknown"
          and sm.end_points(rows, no_ep_rules)["values"] == {})

    # ── 6. обращение J → Sw ─────────────────────────────────────────────────
    fit_dict = result["j_fit"]["fits"][0]
    expected = (0.5 / 0.6) ** (1.0 / 1.8)
    check("обращение: Sw из J по подогнанной зависимости",
          abs(sm.sw_from_j(0.6, fit_dict, rules) - expected) < 1e-9,
          str(sm.sw_from_j(0.6, fit_dict, rules)))
    check("обращение: вне диапазона/нет коэффициентов → None",
          sm.sw_from_j(0.1, fit_dict, rules) is None
          and sm.sw_from_j(0.6, few_fit, rules) is None)
    check("обращение: нечисловой J → None", sm.sw_from_j(float("nan"), fit_dict) is None)

    # ── 7. SCAL из проектного графа (матрицы swof/sgof) ─────────────────────
    field_scal = None
    try:
        import yaml
        graph = yaml.safe_load((ROOT / "ontology_project" / "gerasimovskoe.yaml")
                               .read_text(encoding="utf-8")) or {}
        field_scal = graph.get("scal")
    except Exception:                                   # noqa: BLE001 — данных может не быть
        field_scal = None
    if isinstance(field_scal, dict):
        project_result = sm.from_project_scal(field_scal, rules)
        check("проектный SCAL: матрицы распознаны по данным онтологии",
              project_result["tables_used"] == ["swof", "sgof"],
              str(project_result["tables_used"]))
        check("проектный SCAL: J-функция честно insufficient (нет σ/θ в матрицах)",
              project_result["j_fit"]["status"] == "insufficient"
              and project_result["status"] == "insufficient",
              str(project_result["j_fit"]["status"]))
        check("проектный SCAL: концевые точки не выдуманы при 3 наблюдениях",
              project_result["end_points"]["values"] == {}
              and project_result["end_points"]["status"] == "insufficient",
              str(project_result["end_points"]["values"]))
    check("проектный SCAL: пустая секция → not_applicable",
          sm.from_project_scal({}, rules)["status"] == "not_applicable")
    no_tables = copy.deepcopy(rules)
    no_tables["saturation"]["tables"] = {}
    check("проектный SCAL: таблицы не объявлены данными → not_applicable с причиной",
          sm.from_project_scal(field_scal or {}, no_tables)["status"] == "not_applicable")

    # ── 8. агенты вызывают модули (интеграция) ──────────────────────────────
    from agents.petrophysics import PetrophysicsAgent
    from agents.saturation import SaturationAgent

    try:
        import yaml
        real_graph = yaml.safe_load((ROOT / "ontology_project" / "gerasimovskoe.yaml")
                                    .read_text(encoding="utf-8")) or {}
    except Exception:                                   # noqa: BLE001
        real_graph = {}
    sat = SaturationAgent(cfg).decide(real_graph, {})
    model = sat.get("scal_model") or {}
    check("агент насыщения: вызывает модуль и отдаёт статус SCAL",
          model.get("status") in ("ok", "insufficient", "not_applicable", "no_data",
                                  "unknown"),
          str(model)[:200])
    check("агент насыщения: статус честный — без σ/θ данные не «ok»",
          not (model.get("status") == "ok" and model.get("j_fit_status") != "ok"),
          str({k: model.get(k) for k in ("status", "j_fit_status")}))
    check("агент насыщения: источник правила и статус знания в решении",
          bool(model.get("source_rule")) and bool(model.get("knowledge_status")),
          str({k: model.get(k) for k in ("source_rule", "knowledge_status")}))
    check("агент насыщения: пробелы SCAL попали в unknown",
          any(str(item).startswith("scal:") for item in (sat.get("unknown") or []))
          or model.get("status") in ("ok", "not_applicable"),
          str((sat.get("unknown") or [])[:3]))
    empty_sat = SaturationAgent(cfg).decide({"contacts": {}}, {})
    check("агент насыщения: нет SCAL → not_applicable (не число)",
          (empty_sat.get("scal_model") or {}).get("status") == "not_applicable",
          str(empty_sat.get("scal_model", {}).get("status")))
    contract = SaturationAgent(cfg).decide(
        {"contacts": {"owc": -2500.0}, "thresholds": {"swl": [0.05, 0.6]}}, {})
    check("агент насыщения: прежний контракт решения сохранён",
          contract.get("enabled") and (contract.get("contacts") or {}).get("oil_water")
          and "controls" in contract and "mode" in contract, str(sorted(contract)))

    petro = PetrophysicsAgent(cfg).decide(real_graph, {})
    fit_info = petro.get("permeability_fit") or {}
    check("агент петрофизики: k-φ без данных керна → not_applicable с причиной",
          fit_info.get("status") == "not_applicable"
          and "core_data" in str(fit_info.get("reason")), str(fit_info)[:200])
    with tempfile.TemporaryDirectory() as tmp:
        core_path = Path(tmp) / "core.csv"
        with core_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["porosity", "permeability", "lithotype"])
            for index in range(35):
                phi = 0.15 + 0.002 * index
                writer.writerow([round(phi, 6), 10 ** (2.0 * phi + 2.0), "A"])
        loaded = PetrophysicsAgent(cfg).decide(
            {"petrophysics": {"core_data": str(core_path),
                              "cubes": [{"log": "L", "cube": "C"}]}}, {})
        loaded_fit = loaded.get("permeability_fit") or {}
        check("агент петрофизики: керн из данных → подгонка по литотипу выполнена",
              loaded_fit.get("status") == "ok"
              and abs((loaded_fit.get("fits") or [{}])[0].get("slope", 0) - 2.0) < 1e-9,
              str(loaded_fit)[:200])
        check("агент петрофизики: путь керна зафиксирован в решении",
              str(loaded_fit.get("path")) == str(core_path), str(loaded_fit.get("path")))

    print(f"\n=== ИТОГ ===\nпроверок: {CHECKS} | провалено: {len(FAILED)}")
    for item in FAILED:
        print("  -", item)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
