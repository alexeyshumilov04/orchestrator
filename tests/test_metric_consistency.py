#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Тесты сверки «карта метрики против табличного агрегата» (правило 6).

Проверяется чистая логика `core/metric_consistency.py` — без запуска тНава:
  * сумма выгрузки считается только по НЕПУСТЫМ ячейкам (бланк — из данных);
  * признак бланка берётся из данных шага выгрузки, а не зашит в код;
  * в пределах допуска → `passed`; вне допуска → `unknown`; нет величины → `unverified`.

Запуск: python tests/test_metric_consistency.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.metric_consistency import blank_from_graph, map_sum, to_num, verdict  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f"  <-- {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def main() -> int:
    check("to_num: число и мусор", to_num("1.5") == 1.5 and to_num("abc") is None
          and to_num(None) is None)

    graph = {"pipeline": [{"stage": "s", "steps": [
        {"function": "map_2d_export_ascii_format",
         "parameters": {"file_name": "Maps/STOIIP.txt", "default_value": 9999900}}]}]}
    check("blank_from_graph: признак бланка из данных",
          blank_from_graph(graph, "STOIIP.txt") == 9999900.0,
          str(blank_from_graph(graph, "STOIIP.txt")))
    check("blank_from_graph: чужой файл → признак не найден",
          blank_from_graph(graph, "PORO.txt") is None)

    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "M.txt"
        f.write_text("9999900\n9999900\n100\n200\n", encoding="utf-8")
        res = map_sum(f, 9999900.0)
        check("map_sum: бланк не входит в сумму и в счётчик непустых",
              res == (300.0, 2, 4), str(res))
        check("map_sum: файла нет → свидетельства нет", map_sum(Path(td) / "нет.txt", 0.0) is None)
        f.write_text("1\n2\n", encoding="utf-8")
        check("map_sum: без признака бланка считаются все числа",
              map_sum(f, None) == (3.0, 2, 2), str(map_sum(f, None)))

    check("verdict: в допуске → passed",
          verdict(100.0, 100.0, 0.05)["verdict"] == "passed",
          str(verdict(100.0, 100.0, 0.05)))
    check("verdict: вне допуска → unknown (не «прошло»)",
          verdict(84.0, 100.0, 0.05)["verdict"] == "unknown",
          str(verdict(84.0, 100.0, 0.05)))
    check("verdict: нет карты → unverified",
          verdict(None, 100.0, 0.05)["verdict"] == "unverified")
    check("verdict: нет агрегата → unverified",
          verdict(100.0, None, 0.05)["verdict"] == "unverified")
    check("verdict: нулевой агрегат не делится на ноль",
          verdict(100.0, 0.0, 0.05)["verdict"] == "unverified")
    check("verdict: причина всегда заполнена",
          all(str(verdict(a, b, 0.05).get("reason") or "").strip()
              for a, b in ((100.0, 100.0), (1.0, 100.0), (None, None))))

    print(f"\n=== ИТОГ ===\nпроверок: 12 | провалено: {len(FAILED)}")
    for f in FAILED:
        print("  -", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
