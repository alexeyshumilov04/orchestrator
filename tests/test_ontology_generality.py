#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Тесты ОБЩНОСТИ: онтология без параметров объектов, домен — только в данных.

Проверяется без запуска тНава (`core/generality_audit.py`):
  * реестр поля собирается ИЗ ДАННЫХ (`ontology_project/*.yaml` + config), а
    генерическая лексика (единицы измерения) исключается по
    `ontology/generic_vocabulary.yaml` с обоснованием;
  * в рантайм-коде нет НИ ОДНОГО нарушения правила 1: ни литералов, ни имён, ни
    комментариев (docstring-и — документация, считаются отдельно);
  * в файлах ПРАВИЛ онтологии нет параметров объектов тестирования (значений);
    ключи правил — имена схемы (роли/аргументы), они допустимы;
  * ДОКАЗАТЕЛЬСТВО автоматической сборки: граф для поля, которого НЕТ в
    `ontology_project`, и для поля с МИНИМАЛЬНЫМ файлом данных собирается из
    онтологии — состав, роли, форматы, требования к объектам берутся из данных
    онтологии, код при этом не меняется.

Запуск: python tests/test_ontology_generality.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_config                      # noqa: E402
from core import generality_audit as ga                  # noqa: E402

FAILED: list[str] = []
CHECKS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f"  <-- {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def main() -> int:
    cfg = load_config()
    vocab = ga.generic_vocabulary()
    registry = ga.field_registry(cfg)

    # ── 1. реестр поля собирается ИЗ ДАННЫХ ─────────────────────────────────
    check("реестр: собран из данных поля (не пуст)", len(registry) >= 10,
          str(len(registry)))
    classes = {info.get("class") for info in registry.values()}
    check("реестр: различает классы объектов (поле/маркер/куб/мнемоника/вход)",
          {"field", "marker", "cube"}.issubset(classes), str(sorted(classes)))
    check("реестр: у каждого токена есть источник в данных",
          all(str(info.get("source") or "") for info in registry.values()))
    units = ga._generic_unit_values(vocab)
    check("реестр: генерические единицы измерения НЕ считаются доменом",
          units and not (units & set(registry)),
          f"units={sorted(units)} пересечение={sorted(units & set(registry))}")
    check("генерическая лексика: у каждой позиции есть обоснование why",
          bool(vocab.get("generic_unit_values")) and all(
              str(item.get("why") or "").strip()
              for item in (vocab.get("generic_unit_values") or [])),
          str(vocab.get("generic_unit_values")))

    # ── 2. онтология: файлы правил объявлены данными и существуют ───────────
    root = ga.ontology_root(cfg)
    rule_files = ga._audited_rule_files(vocab, cfg)
    check("онтология: перечень файлов правил — ДАННЫЕ", len(rule_files) >= 8,
          str(len(rule_files)))
    absent = [name for name in rule_files if not (root / name).is_file()]
    check("онтология: все объявленные файлы правил существуют", not absent,
          str(absent))

    # ── 3. код: ни одного нарушения правила 1 ───────────────────────────────
    report = ga.audit(cfg, probe=False)
    check("код: нарушений правила 1 (литералы/имена/комментарии) НЕТ",
          report["verdict"]["code_violations"] == 0,
          str(report["code"]["violation_items"][:5]))
    check("код: объявленный долг правила 1 отсутствует (0 позиций)",
          report["verdict"]["code_declared_debt"] == 0,
          str(report["code"]["declared_debt_items"][:5]))
    check("код: docstring-и считаются отдельно (документация, не вердикт)",
          report["code"]["advisory_docstring"] >= 0
          and report["verdict"]["code_violations"] == 0)
    check("код: реестр инструмента не пуст (аудит осмыслен)",
          report["registry"]["size"] >= 10, str(report["registry"]["size"]))

    # ── 4. онтология: нет ПАРАМЕТРОВ объектов тестирования ──────────────────
    check("онтология: параметров объектов тестирования в правилах НЕТ",
          report["ontology_rules"]["hits"] == 0,
          str(report["ontology_rules"]["items"][:6]))
    check("онтология: ключи правил — идентификаторы схемы (advisory, не вердикт)",
          report["ontology_rules"]["schema_key_advisory"] >= 0)

    # ── 5. доказательство автоматической сборки ─────────────────────────────
    proof = ga.generality_proof(cfg)
    probe = proof.get("probe") or {}
    unknown = proof.get("unknown_field") or {}
    check("доказательство: поле-зонд НЕ имеет файла в ontology_project",
          not (ga.graph_dir(cfg) / f"{probe.get('field_unknown')}.yaml").exists(),
          str(probe.get("field_unknown")))
    check("доказательство: граф незнакомого поля СОБРАН из онтологии",
          unknown.get("pipeline_source") == "ontology"
          and int(unknown.get("stages") or 0) > 0
          and int(unknown.get("steps") or 0) > 0, str({k: unknown.get(k) for k in
                                                       ("pipeline_source", "stages", "steps")}))
    check("доказательство: состав содержит шаги с функциями",
          int(unknown.get("functions") or 0) > 0, str(unknown.get("functions_sample")))
    check("доказательство: роли распознавания выведены ИЗ ОНТОЛОГИИ",
          len(proof.get("roles_from_ontology") or {}) >= 5,
          str(len(proof.get("roles_from_ontology") or {})))
    check("доказательство: форматы входа выведены ИЗ ОНТОЛОГИИ",
          len(proof.get("formats_from_ontology") or {}) >= 3,
          str(list((proof.get("formats_from_ontology") or {}).keys())))
    check("доказательство: требования шагов к объектам — ИЗ ОНТОЛОГИИ",
          len(proof.get("object_requirements_from_ontology") or {}) >= 5,
          str(len(proof.get("object_requirements_from_ontology") or {})))
    check("доказательство: привязки ролей — ИЗ ОНТОЛОГИИ",
          len(proof.get("object_binding_roles_from_ontology") or {}) >= 5,
          str(len(proof.get("object_binding_roles_from_ontology") or {})))
    minimal = proof.get("field_with_minimal_data") or {}
    check("доказательство: поле с МИНИМАЛЬНЫМ файлом данных собирается",
          minimal.get("pipeline_source") == "ontology"
          and int(minimal.get("stages") or 0) > 0, str(minimal.get("stages")))
    check("доказательство: минимальный файл данных = только field + dataset_root",
          sorted(minimal.get("field_keys_from_data") or []) == ["dataset_root", "field"],
          str(minimal.get("field_keys_from_data")))
    check("доказательство: добавление поля НЕ требует правок кода",
          int(probe.get("code_files_modified") or 0) == 0, str(probe))
    params = proof.get("ontology_parameters") or {}
    check("доказательство: параметры петрофизики/структуры — ИЗ ОНТОЛОГИИ",
          bool((params.get("petrophysics") or {}).get("verdict"))
          and bool((params.get("structural") or {}).get("verdict")),
          str({k: (v or {}).get("verdict") for k, v in params.items()}))

    # ── 6. исключения из скана объявлены данными с обоснованием ─────────────
    exclusions = ga.scan_exclusions()
    check("исключения скана: объявлены ДАННЫМИ с обоснованием",
          bool(exclusions) and all(str(why).strip() for why in exclusions.values()),
          str(exclusions))

    print(f"\n=== ИТОГ ===\nпроверок: {CHECKS} | провалено: {len(FAILED)}")
    for item in FAILED:
        print("  -", item)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
