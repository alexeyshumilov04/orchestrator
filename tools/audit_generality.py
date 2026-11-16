#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Отчёт общности: онтология без параметров объектов, домен — только в данных.

Команда-обёртка над `core/generality_audit.py` (машинно-читаемый JSON):

    python tools/audit_generality.py [--no-probe] [--out reports/generality.json]

Также доступна как подкоманда: `python main.py audit --generality`.

Что попадает в отчёт:
  * `registry` — имена объектов поля, собранные ИЗ ДАННЫХ (поле, маркеры, кубы,
    мнемоники, входные файлы, объекты шагов, ветви ансамбля); генерическая
    лексика (единицы измерения) исключена по данным с обоснованием;
  * `code` — вхождения токенов реестра в литералы/имена/КОММЕНТАРИИ рантайм-кода
    с разметкой: violation | declared_debt | allowed; docstring-и отдельно;
  * `ontology_rules` — параметры объектов тестирования в файлах правил (значения);
  * `generality_proof` — сборка графа для поля БЕЗ файла в `ontology_project` и для
    поля с минимальным файлом данных: состав/роли/форматы/требования к объектам
    выводятся из онтологии, правок кода не требуется.

Код возврата: 0 — нарушений нет; 1 — есть нарушения (violation) или параметры
объектов в правилах.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_config                    # noqa: E402
from core.generality_audit import audit                # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="аудит общности онтологии и кода")
    parser.add_argument("--config", default=None, help="путь к config.yaml")
    parser.add_argument("--no-probe", action="store_true",
                        help="без доказательства сборки для незнакомого поля")
    parser.add_argument("--out", default=None, help="записать отчёт в JSON-файл")
    args = parser.parse_args()

    report = audit(load_config(args.config), probe=not args.no_probe)
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"отчёт записан: {target}")

    registry = report["registry"]
    code = report["code"]
    rules = report["ontology_rules"]
    verdict = report["verdict"]
    print(f"реестр поля (из данных): {registry['size']} токенов {registry['by_class']}")
    print(f"код: нарушения {code['violations']} | объявленный долг {code['declared_debt']} | "
          f"разрешено схемой {code['allowed']} | комментарии/литералы/имена учтены; "
          f"docstring-и (документация) {code['advisory_docstring']}")
    print(f"онтология: параметров объектов тестирования {rules['hits']} "
          f"(файлов проверено {len(rules['files'])})")
    for row in code["violation_items"][:10]:
        print(f"  [НАРУШЕНИЕ] {row['file']}:{row['line']} {row['kind']} "
              f"«{str(row['value'])[:60]}» домен «{row['token']}»")
    for row in rules["items"][:10]:
        print(f"  [ОНТОЛОГИЯ] {row['file']}:{row['line']} {row['kind']} "
              f"«{str(row['value'])[:60]}» домен «{row['token']}»")
    proof = report.get("generality_proof") or {}
    if proof:
        unknown = proof.get("unknown_field") or {}
        minimal = proof.get("field_with_minimal_data") or {}
        print(f"доказательство: поле без файла → этапов {unknown.get('stages')}, "
              f"шагов {unknown.get('steps')}, функций {unknown.get('functions')} "
              f"(источник {unknown.get('pipeline_source')})")
        print(f"доказательство: поле с минимальным файлом данных "
              f"({', '.join(minimal.get('field_keys_from_data') or [])}) → этапов "
              f"{minimal.get('stages')}; ролей из онтологии "
              f"{len(proof.get('roles_from_ontology') or {})}, форматов "
              f"{len(proof.get('formats_from_ontology') or {})}, требований к объектам "
              f"{len(proof.get('object_requirements_from_ontology') or {})}; "
              f"правок кода {proof.get('probe', {}).get('code_files_modified')}")
    print(f"вердикт: {verdict['general']} "
          f"(нарушений {verdict['code_violations']}, параметров объектов в правилах "
          f"{verdict['ontology_object_parameter_hits']}, объявленный долг "
          f"{verdict['code_declared_debt']})")
    if not args.out:
        print(text)
    return 0 if verdict["general"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
