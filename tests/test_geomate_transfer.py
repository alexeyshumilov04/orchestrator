#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Тесты ПЕРЕНОСА наработок GeoMate и полноты данных онтологии (task-14).

Проверяется без запуска тНава:
  * файл-реестр переноса `ontology/petrofacies_methods.yaml` существует, парсится,
    а все файлы из его секции `sources` реально лежат в онтологии;
  * КАЖДАЯ позиция `geomate_reuse_rules.yaml:missing_to_implement` либо закрыта
    нашим модулем (`transfer.adopted`/`reworked`), либо честно отнесена к
    `transfer.remaining` с причиной (`blocked_by`) — «дыр» в реестре нет;
  * ссылки `where` на файлы существуют (перенос не «на словах»);
  * модули импортируются и НЕ зависят от тНава (чистые расчёты по данным);
  * правило 6 на границах модулей: пустые данные → unknown/not_applicable,
    ни одного выдуманного числа;
  * коды параметров тНава не выдуманы (`patch_codes` пуст до успешной пробы);
  * данные, перенесённые «просто данными» (веса индекса изученности), сохранены.

Запуск: python tests/test_geomate_transfer.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_config                        # noqa: E402
from domain import facies_model as fm                      # noqa: E402
from domain import petrofacies_data as pdata               # noqa: E402
from domain import petrophysics_fit as pf                  # noqa: E402

FAILED: list[str] = []
CHECKS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f"  <-- {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def _paths_from(text: str) -> list[str]:
    """Пути файлов, упомянутые в ссылке вида `path.yaml:key` или `path.py`."""
    out: list[str] = []
    for token in str(text).split(","):
        for piece in token.split():
            candidate = piece.strip().strip(";")
            if "/" in candidate and candidate.endswith((".yaml", ".yml", ".py")):
                out.append(candidate.split(":")[0])
    return out


def main() -> int:
    cfg = load_config()
    ontology = pdata.ontology_dir(cfg)
    glue = pdata.read_yaml(ontology / pdata.RULES_FILE)
    reuse = pdata.read_yaml(ontology / "geomate_reuse_rules.yaml")
    rules = pdata.load_rules(cfg)

    # ── 1. реестр переноса и сшивка данных ───────────────────────────────────
    check("реестр: файл переноса существует и парсится", bool(glue),
          str(ontology / pdata.RULES_FILE))
    sources = glue.get("sources") or []
    check("реестр: объявлены файлы-источники правил", len(sources) >= 3, str(sources))
    check("реестр: все объявленные файлы есть в онтологии",
          all((ontology / str(name)).is_file() for name in sources),
          str([name for name in sources if not (ontology / str(name)).is_file()]))
    check("реестр: набор правил собран без пропусков",
          not pdata.missing_sources(rules) and len(pdata.loaded_sources(rules)) == len(sources),
          f"loaded={pdata.loaded_sources(rules)} missing={pdata.missing_sources(rules)}")
    check("реестр: служебные ключи не мешают чтению секций",
          bool(pdata.section(rules, "facies_model"))
          and bool(pdata.section(rules, "permeability_fit")))

    transfer = glue.get("transfer") or {}
    adopted = transfer.get("adopted") or []
    reworked = transfer.get("reworked") or []
    remaining = transfer.get("remaining") or []
    check("реестр: секции adopted/reworked/remaining заполнены",
          bool(adopted) and bool(reworked) and bool(remaining),
          f"{len(adopted)}/{len(reworked)}/{len(remaining)}")
    check("реестр: у adopted указано «что» и «где»",
          all(item.get("id") and item.get("what") and item.get("where")
              for item in adopted),
          str([item.get("id") for item in adopted
               if not (item.get("what") and item.get("where"))]))
    check("реестр: у reworked указано «было/стало/где/почему»",
          all(item.get("id") and item.get("was") and item.get("now")
              and item.get("where") and item.get("why") for item in reworked),
          str([item.get("id") for item in reworked
               if not (item.get("was") and item.get("now") and item.get("where"))]))
    check("реестр: у remaining указана причина (чем заблокировано)",
          all(item.get("id") and item.get("need") and item.get("blocked_by")
              for item in remaining),
          str([item.get("id") for item in remaining if not item.get("blocked_by")]))

    # ── 2. ссылки на файлы существруют ──────────────────────────────────────
    bad_links: list[str] = []
    for group in (adopted, reworked):
        for item in group:
            for rel in _paths_from(item.get("where") or ""):
                if not (ROOT / rel).is_file() and not (ontology / Path(rel).name).is_file():
                    bad_links.append(f"{item.get('id')} → {rel}")
    check("реестр: ссылки «where» ведут на существующие файлы", not bad_links,
          "; ".join(bad_links))

    # ── 3. покрытие missing_to_implement (дыр быть не должно) ───────────────
    missing = [str(item.get("id")) for item in (reuse.get("missing_to_implement") or [])
               if item.get("id")]
    ledger: dict[str, str] = {}
    for group_name, group in (("adopted", adopted), ("reworked", reworked),
                              ("remaining", remaining)):
        for item in group:
            ledger.setdefault(str(item.get("id")), group_name)
    check("реестр GeoMate: список пробелов прочитан", len(missing) >= 6, str(missing))
    uncovered = [item for item in missing if item not in ledger]
    check("реестр: каждый пробел GeoMate классифицирован (закрыт/остался)",
          not uncovered, str(uncovered))
    closed = [item for item in missing if ledger.get(item) in ("adopted", "reworked")]
    check("реестр: часть пробелов закрыта своими модулями", len(closed) >= 3,
          str(sorted(closed)))
    check("реестр: оставшиеся пробелы имеют причину в данных",
          all(any(str(item.get("id")) == gap for item in remaining) for gap in missing
              if gap not in closed),
          str([gap for gap in missing if not any(str(item.get("id")) == gap
                                                 for item in remaining)
               and gap not in closed]))

    # ── 4. модули: импорт, отсутствие зависимости от тНава ──────────────────
    modules = {"petrofacies_data": pdata, "petrophysics_fit": pf, "facies_model": fm}
    check("модули: импортируются", all(mod is not None for mod in modules.values()))
    for name, module in modules.items():
        source = (ROOT / "domain" / f"{name}.py").read_text(encoding="utf-8")
        check(f"модуль {name}: не зависит от клиента тНава",
              "tnav" not in source.lower() and "subprocess" not in source,
              "модуль обязан быть чистым расчётом по данным")
    entry_points = {"petrofacies_data": "load_rules",
                    "petrophysics_fit": "fit_from_rows",
                    "facies_model": "aggregate_facies"}
    check("модули: точки входа доступны без тНава и конфигурации",
          all(callable(getattr(modules[name], function, None))
              for name, function in entry_points.items()),
          str(entry_points))

    # ── 5. правило 6 на границах модулей: пустые данные ─────────────────────
    empty_fit = pf.fit_from_rows([], rules)
    check("правило 6: пустой керн → not_applicable, коэффициентов нет",
          empty_fit["status"] == pf.STATUS_NOT_APPLICABLE
          and all(item["slope"] is None for item in empty_fit["fits"]),
          str(empty_fit["status"]))
    empty_cut = pf.cutoff_from_labelled_core([], rules)
    check("правило 6: пустой cut-off → нет числа",
          empty_cut["status"] in (pf.STATUS_NOT_APPLICABLE, pf.STATUS_INSUFFICIENT)
          and empty_cut["value"] is None, str(empty_cut))
    empty_facies = fm.aggregate_facies(rules=rules)
    check("правило 6: пустые фации → not_applicable, NTG = None",
          empty_facies["status"] == fm.STATUS_NOT_APPLICABLE
          and empty_facies["net_to_gross"] is None, str(empty_facies["status"]))
    empty_wells = fm.proportions_from_wells({}, rules)
    check("правило 6: пустые скважины → доли не выдуманы",
          empty_wells["status"] == fm.STATUS_NOT_APPLICABLE
          and empty_wells["proportions"] == {}, str(empty_wells["status"]))
    blank_only = pf.fit_from_rows(
        [{"porosity": 0.2, "permeability": 1.70141e10, "lithotype": "A"}
         for _ in range(40)], rules)
    check("правило 6: только бланки → ни одной пары, статус not_applicable",
          blank_only["n_pairs_total"] == 0
          and blank_only["status"] == pf.STATUS_NOT_APPLICABLE,
          str(blank_only["status"]))

    # ── 6. параметры тНава не выдуманы ──────────────────────────────────────
    check("правило 8: коды параметров шага фаций пусты (до пробы)",
          pdata.get(rules, "facies_model.patch_codes") == {},
          str(pdata.get(rules, "facies_model.patch_codes")))
    check("правило 8: при пустых кодах патч не применяется и есть unknown",
          fm.facies_step_parameters({"proportions": {"1": 1.0}}, rules,
                                    template_text="x = 1")[0] == {})
    check("правило 8: мануал/источники функций фаций не подменяются этим модулем",
          "grid_property_facies_modeling" not in
          (ROOT / "domain" / "facies_model.py").read_text(encoding="utf-8"),
          "имя функции тНава живёт в ontology/facies_methods.yaml")

    # ── 7. данные, перенесённые «просто данными» ────────────────────────────
    weights = pdata.section(rules, "study_sufficiency").get("weights") or {}
    check("данные: веса индекса изученности перенесены из GeoMate",
          bool(weights) and all(isinstance(value, (int, float))
                                for value in weights.values()),
          str(weights))
    check("данные: веса не зашиты в код (модули их не содержат)",
          all("study_sufficiency" not in
              (ROOT / "domain" / f"{name}.py").read_text(encoding="utf-8")
              for name in modules))
    facies_methods = pdata.read_yaml(ontology / "facies_methods.yaml")
    check("данные: порог скважин согласован с facies_methods.yaml",
          pdata.get(rules, "facies_model.min_wells")
          == pdata.get(facies_methods, "proportions.min_wells"),
          f"{pdata.get(rules, 'facies_model.min_wells')} vs "
          f"{pdata.get(facies_methods, 'proportions.min_wells')}")
    check("данные: проверки модулей объявлены в онтологии",
          {str(item.get("id")) for item in (glue.get("checks") or [])}
          >= {"geomate.phi_perm_fit_source", "geomate.facies_aggregates"},
          str(glue.get("checks")))
    check("данные: происхождение значений помечено (provenance)",
          all(pdata.get(rules, dotted)
              for dotted in ("cutoff.provenance", "rock_typing.provenance",
                             "permeability_fit.provenance", "facies_model.provenance")),
          "часть provenance пуста")

    print(f"\n=== ИТОГ ===\nпроверок: {CHECKS} | провалено: {len(FAILED)}")
    for item in FAILED:
        print("  -", item)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
