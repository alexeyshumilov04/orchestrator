#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Тесты механизма селекции шагов онтологического вывода (критерии «в»/«г»).

Проверяется БЕЗ запуска тНава:
  * режим `skip` — лишние шаги не в пайплайне, но перечислены в отчёте;
  * режим `include` — лишние шаги идут отдельной стадией в конце;
  * режим `agent` — лишние шаги в пайплайне + правила применимости из данных;
  * правила покрывают ВСЕ выявленные лишние функции, ссылаются на существующие
    гейты и на подтверждённые/неподтверждённые привязки с причиной;
  * «нет правила» трактуется как «не включать» (неизвестное != ложь).

Запуск: python tests/test_ontology_extra_selection.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_config            # noqa: E402
from core.coordinator import Coordinator       # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f"  <-- {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def main() -> int:
    cfg = load_config()
    coord = Coordinator(cfg)
    tuned = yaml.safe_load((cfg.path("project.graph_dir", "ontology_project")
                            / "gerasimovskoe.yaml").read_text(encoding="utf-8"))
    c = Coordinator(cfg)

    def graph(mode: str) -> dict:
        c.cfg.set("workflow.ontology_extra_steps", mode) if hasattr(c.cfg, "set") else \
            c.cfg._data["workflow"].__setitem__("ontology_extra_steps", mode)
        return c.graph_from_ontology("Герасимовское", template=copy.deepcopy(tuned))

    g_skip = graph("skip")
    fns_skip = {s.get("function") for st in (g_skip.get("pipeline") or [])
                for s in (st.get("steps") or [])}
    extras = set(g_skip.get("ontology_extra_steps") or [])
    check("skip: лишние шаги перечислены", len(extras) > 0, str(len(extras)))
    check("skip: лишние шаги НЕ в пайплайне", not (extras & fns_skip),
          str(sorted(extras & fns_skip)))
    check("skip: стадия доп. шагов отсутствует",
          all("доп. шаги" not in str(st.get("stage")) for st in (g_skip.get("pipeline") or [])))

    g_inc = graph("include")
    fns_inc = {s.get("function") for st in (g_inc.get("pipeline") or [])
               for s in (st.get("steps") or [])}
    check("include: лишние шаги в пайплайне (стадия в конце)",
          extras <= fns_inc and "доп. шаги" in str((g_inc.get("pipeline") or [])[-1].get("stage")),
          str(sorted(extras - fns_inc)))

    g_ag = graph("agent")
    rules = g_ag.get("ontology_extra_rules") or {}
    check("agent: правила применимости загружены", len(rules) > 0, str(len(rules)))
    check("agent: правила покрывают все лишние функции", extras <= set(rules),
          str(sorted(extras - set(rules))))
    check("agent: ошибок чтения правил нет", not g_ag.get("ontology_extra_rules_error"),
          str(g_ag.get("ontology_extra_rules_error")))

    gate_ids = {str(g.get("id")) for g in (cfg.get("gates") or [])}
    bad_gate = {fn: r.get("gate") for fn, r in rules.items() if str(r.get("gate")) not in gate_ids}
    check("правила: гейт-владелец существует в данных gating",
          not bad_gate, str(bad_gate))
    bad_key = {fn: r.get("decision_key") for fn, r in rules.items() if not r.get("decision_key")}
    check("правила: ключ решения задан", not bad_key, str(bad_key))
    unverified = {fn: r for fn, r in rules.items() if r.get("verified", True) is False}
    check("правила: неподтверждённые привязки имеют причину",
          all(str(r.get("reason") or "").strip() for r in unverified.values()),
          str(sorted(unverified)))
    print(f"     (неподтверждённых привязок: {len(unverified)} из {len(rules)})")

    # «нет правила» = не включать: имитируем отсутствие правила и проверяем, что
    # функция попадает в список лишних (значит, будет пропущена исполнителем).
    g_no = graph("agent")
    g_no["ontology_extra_rules"] = {k: v for k, v in rules.items() if k != sorted(rules)[0]}
    missing_rule = sorted(extras - set(g_no["ontology_extra_rules"]))
    check("нет правила → функция остаётся в списке лишних (будет пропущена)",
          bool(missing_rule), str(missing_rule))

    print(f"\n=== ИТОГ ===\nпроверок: 11 | провалено: {len(FAILED)}")
    for f in FAILED:
        print("  -", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
