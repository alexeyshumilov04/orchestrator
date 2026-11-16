"""Тесты контрактов QA/QC: реестр проверок ИЗ ДАННЫХ, qaqc в отчёте, пороги гейтов.

Запуск:  python -X utf8 tests/test_contracts.py

Что проверяется (этап E2):
  * ``CheckRegistry.from_data`` строит проверки из данных: код (builtin/contract) +
    пакет ``domain/qaqc`` по блокам из ``checks.package_blocks`` + CSV-описания
    ``ontology/qa_checks/*.csv``; файлы-индексы проверками НЕ становятся;
  * реестр не падает без каталога/CSV (неизвестное ≠ ложь);
  * ``qaqc`` появляется в report.json верхнего уровня и в ``qaqc_coverage.json``;
    блоки и веса — из данных; покрытие 6065 пунктов чеклиста (реализовано /
    not_applicable+причина / unknown+причина);
  * ``min_kq``/``min_kc`` применяются только при посчитанных метриках, поэтому
    dry-run не деградирует и гейты остаются pending_execution;
  * неизвестное ≠ ложь: пустые данные → not_applicable, битая схема → unknown,
    и ни то, ни другое не становится failed.
"""
from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_PASS: list[str] = []
_FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (_PASS if cond else _FAIL).append(name)
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + ("" if cond else f"  <-- {detail}"))


def _cfg():
    from core.config import load_config
    return load_config()


FIXTURE_HEADER = ("ID;Блок;Название;Способ выполнения;Порог;Входные ключи;Значимость;"
                  "Формула;Критерий;Используется критерием критика")
FIXTURE_ROWS = [
    "QC_T_001;99. Тестовый блок;Порог K;direct;>= 0.5;K;0.95;K;K >= 0.5;да",
    "QC_T_002;99. Тестовый блок;Нет данных;direct;>= 0.5;MISSING;0.80;MISSING;MISSING >= 0.5;",
    "QC_T_003;99. Тестовый блок;Битый порог;direct;~0.5;K;0.50;K;K ~ 0.5;",
    "QC_T_004;99. Тестовый блок;Чужой примитив;svm;>= 0.5;K;0.50;svm(K);—;",
    # неэкранированный ';' в колонке порога → строка «съезжает» (должна стать unknown)
    "QC_T_005;99. Тестовый блок;Двойной порог;direct;>= 0.1;>= 0.2;A, B;0.60;A,B;—;",
    # корректный двухклаузный порог: клаузы через '|', поле в кавычках
    'QC_T_006;99. Тестовый блок;Два порога;direct;"NUG <= 0.1 | RNG >= 500";NUG, RNG;'
    "0.60;NUG,RNG;—;",
]


def _fixture_root(tmp: Path) -> Path:
    """Синтетические данные: карта гейтов + CSV-описания проверок + файл-индекс."""
    (tmp / "ontology" / "qa_checks").mkdir(parents=True, exist_ok=True)
    import yaml
    (tmp / "ontology" / "qa_gate_map.yaml").write_text(yaml.safe_dump({
        "meta": {"total_items": 5, "blocks_total": 1},
        "severity_levels": {"critical": 0.9, "major": 0.75},
        "gates": {"G-X": {"agent": "AG_TEST", "stages": [0], "blocks": ["99"]}},
        "blocks": {"99": {"title": "Тестовый блок", "items": 5, "gates": ["G-X"],
                          "implemented": 5, "severity": "from_weight", "status": "partial",
                          "reason": "тест"}},
    }, allow_unicode=True), encoding="utf-8")
    (tmp / "ontology" / "qa_checks" / "fixture.csv").write_text(
        FIXTURE_HEADER + "\n" + "\n".join(FIXTURE_ROWS) + "\n", encoding="utf-8")
    # файл-индекс чеклиста: НЕ каталог проверок (шапка без схемы проверки)
    (tmp / "ontology" / "qa_checks" / "checklist_index.csv").write_text(
        "ID;Блок;Тип записи\nIT-1;99;Пункт\nIT-2;99;Пункт\n", encoding="utf-8")
    return tmp


# -- 1. данные карты гейтов ---------------------------------------------------------
def test_gate_map_data() -> None:
    from agents.checks.base import (blocks_by_gate, gates_by_block, load_gate_map,
                                   severity_levels)
    gate_map = load_gate_map(_cfg())
    check("карта: ontology/qa_gate_map.yaml читается", bool(gate_map.get("blocks")))
    blocks = gate_map.get("blocks") or {}
    check("карта: 13 блоков чеклиста (01..13)",
          all(f"{i:02d}" in blocks for i in range(1, 14)),
          str(sorted(blocks)))
    check("карта: пункты блоков — факт чеклиста (6065 всего)",
          int((gate_map.get("meta") or {}).get("total_items") or 0) == 6065,
          str((gate_map.get("meta") or {}).get("total_items")))
    levels = severity_levels(gate_map)
    check("карта: уровни severity — данные", levels == (0.9, 0.75), str(levels))
    # сверка с живым индексом пунктов (если команда QA/QC его положила)
    from agents.checks.report import load_checklist_index
    index = load_checklist_index(ROOT)
    if index:
        mismatch = {c: (b.get("items"), index["by_block"].get(c))
                    for c, b in blocks.items() if c in index["by_block"]
                    and int(b.get("items") or 0) != index["by_block"][c]}
        check("карта: пункты блоков совпадают с checklist_index.csv",
              not mismatch and index.get("total") == 6065, str(mismatch))
    # гейты карты согласованы с config.yaml (данные против данных)
    cfg = _cfg()
    cfg_gates = {str(g.get("id")): str(g.get("agent", ""))
                 for g in (cfg.get("gates") or [])}
    from agents.checks.report import blocks_by_gate as blocks_by_gate_cfg
    cfg_blocks = blocks_by_gate_cfg(cfg)
    map_blocks = blocks_by_gate(gate_map)
    check("карта: блоки гейтов совпадают с checks.package_blocks",
          {g: sorted(v) for g, v in map_blocks.items() if g in cfg_blocks}
          == {g: sorted(v) for g, v in cfg_blocks.items() if g in map_blocks},
          str({"map": map_blocks, "cfg": cfg_blocks}))
    check("карта: агенты гейтов — из config.yaml",
          all((gate_map.get("gates") or {}).get(g, {}).get("agent") == a
              for g, a in cfg_gates.items()
              if g in (gate_map.get("gates") or {})), str(cfg_gates))
    check("карта: блок 13 привязан к G-PETRO",
          "G-PETRO" in gates_by_block(gate_map).get("13", ()),
          str(gates_by_block(gate_map).get("13")))


# -- 2. реестр из данных -------------------------------------------------------------
def test_registry_from_data() -> None:
    from agents.checks import CheckRegistry
    from agents.checks.base import load_check_catalog

    base = CheckRegistry()
    check("реестр: дефолт — только код (21 проверка)",
          base.stats()["total"] == 21 and base.stats()["by_source"] == {"builtin": 21},
          str(base.stats()))

    reg = CheckRegistry.from_data(_cfg())
    stats = reg.stats()
    catalog = load_check_catalog(ROOT)
    from agents.checks.base import code_checks, result_checks
    code_n = len(code_checks()) + len(result_checks())
    check("реестр: сборка из данных (код + проверки результата + каталог)",
          stats["total"] == code_n + len(catalog), str(stats))
    check("реестр: каждый каталог-ряд попал ровно один раз",
          stats["by_source"].get("package", 0) + stats["by_source"].get("csv", 0)
          == len(catalog), str(stats["by_source"]))
    ids = [c.id for c in reg.all()]
    check("реестр: дубликатов ID нет", len(ids) == len(set(ids)),
          f"{len(ids)} против {len(set(ids))}")
    fg = reg.for_gate("G-FACIES")
    check("реестр: гейты берутся из данных карты (блоки 05/06 → G-FACIES)",
          any(c.block == "05" for c in fg) and any(c.block == "06" for c in fg),
          str(sorted({c.block for c in fg})))
    check("реестр: проверки без гейта помечены unknown, а не failed",
          all(c.unknown_reason for c in reg.unknown_specs()),
          str([(c.id, c.unknown_reason) for c in reg.unknown_specs()]))


# -- 3. CSV-описания проверок (схема) -------------------------------------------------
def test_registry_csv_schema() -> None:
    from agents.checks import CheckRegistry

    with tempfile.TemporaryDirectory() as tmp:
        root = _fixture_root(Path(tmp))
        reg = CheckRegistry.from_data(root=root)
        csv_specs = [c for c in reg.all() if c.source == "csv"]
        check("csv: проверки собраны из CSV-описания", len(csv_specs) == 6,
              str([c.id for c in csv_specs]))
        check("csv: файл-индекс чеклиста проверками НЕ стал",
              all(not c.id.startswith("IT-") for c in csv_specs))
        spec = next(c for c in csv_specs if c.id == "QC_T_001")
        check("csv: severity из данных значимости (0.95 → critical)",
              spec.severity == "critical", spec.severity)
        check("csv: входные ключи/порог/формула — из данных",
              spec.inputs == ("K",) and spec.threshold == ">= 0.5", str(spec.to_dict()))
        check("csv: признак фитнеса из данных («да»)",
              spec.fitness is True and next(c for c in csv_specs
                                            if c.id == "QC_T_002").fitness is False)

        rep = reg.run_report("G-X", {"values": {"K": [0.7], "NUG": [0.05], "RNG": [600.0]}},
                             include_runtime=True)
        states = {o.id: o.state for o in rep.outcomes}
        check("csv: порог выполнен → passed", states.get("QC_T_001") == "passed",
              str(states))
        check("csv: нет входного ключа → not_applicable (не failed)",
              states.get("QC_T_002") == "not_applicable", str(states))
        check("csv: непарсибельный порог → unknown (не failed)",
              states.get("QC_T_003") == "unknown", str(states))
        check("csv: неизвестный примитив → unknown (не failed)",
              states.get("QC_T_004") == "unknown", str(states))
        check("csv: неэкранированный ';' в значении → unknown, а не тихий разбор",
              states.get("QC_T_005") == "unknown", str(states))
        bad = [o for o in rep.outcomes if o.id == "QC_T_003"]
        check("csv: причина unknown записана",
              bool(bad and "порог" in bad[0].reason.lower()), str(bad))
        malformed = [o for o in rep.outcomes if o.id == "QC_T_005"]
        check("csv: причина битой строки названа (лишние поля)",
              bool(malformed and "лишних полей" in malformed[0].reason),
              str(malformed))
        # двухклаузный порог: клаузы выровнены по ключам, оба выполнены → passed
        check("csv: клаузы порога выровнены по ключам (оба ок) → passed",
              states.get("QC_T_006") == "passed", str(states))

        rep2 = reg.run_report("G-X", {"values": {"K": [0.2], "NUG": [0.05], "RNG": [100.0]}},
                              include_runtime=True)
        states2 = {o.id: o.state for o in rep2.outcomes}
        check("csv: порог нарушен → failed", states2.get("QC_T_001") == "failed",
              str(states2))
        check("csv: вторая клауза нарушена → failed", states2.get("QC_T_006") == "failed",
              str(states2))
        failed = [f for f in rep2.findings if not f.passed]
        check("csv: находка несёт серьёзность/источник",
              bool(failed) and failed[0].severity == "critical"
              and failed[0].source == "csv", str(failed[:1]))


def test_registry_degraded_paths() -> None:
    from agents.checks import CheckRegistry
    from agents.checks.base import build_data_checks, code_checks, result_checks

    code_n = len(code_checks()) + len(result_checks())
    with tempfile.TemporaryDirectory() as tmp:
        specs = build_data_checks(Path(tmp))
        check("реестр: без данных — код + проверки результата, без исключений",
              len(specs) == code_n, f"{len(specs)} против {code_n}")
    check("реестр: отсутствие CSV не роняет сборку",
          CheckRegistry.from_data(root=Path(tempfile.gettempdir())).stats()["total"] == code_n,
          str(CheckRegistry.from_data(root=Path(tempfile.gettempdir())).stats()))


# -- 4. порог гейта: min_kq/min_kc ---------------------------------------------------
def test_threshold_data_and_dry_run_safety() -> None:
    from pathlib import Path as _P

    from agents.contracts import FAILED, PASSED, Finding
    from agents.gates import GateEngine, GateSpec, load_gate_specs
    from core.config import Config

    spec = GateSpec(id="G-X", agent="A", stages=(0,), min_kq=0.9, min_kc=0.9)
    eng = GateEngine(_cfg())
    ok_finding = [Finding("c", "major", True, title="t")]
    empty = eng.evaluate(spec, ok_finding, metrics={})
    check("порог: без метрик НЕ применяется (не валит dry-run)",
          empty.status == PASSED and empty.thresholds["applied"] is False
          and set(empty.thresholds["skipped"]) == {"min_kq", "min_kc"},
          str(empty.thresholds))
    computed = eng.evaluate(spec, ok_finding, metrics={"kq": 0.1, "kc": 0.2,
                                                       "applicable": 5})
    check("порог: при посчитанных метриках валит гейт",
          computed.status == FAILED and computed.thresholds["applied"] is True,
          str(computed.thresholds))
    zero_applicable = eng.evaluate(spec, ok_finding,
                                   metrics={"kq": 0.1, "kc": 0.2, "applicable": 0})
    check("порог: 0 применимых проверок → порог не применяется",
          zero_applicable.status == PASSED and zero_applicable.thresholds["skipped"],
          str(zero_applicable.thresholds))
    passing = eng.evaluate(spec, ok_finding, metrics={"kq": 0.95, "kc": 0.99,
                                                      "applicable": 5})
    check("порог: метрики выше порога → passed", passing.status == PASSED)

    cfg_more = _cfg()
    cfg_more.set("checks.min_applicable_checks", 10)
    strict = GateEngine(cfg_more).evaluate(spec, ok_finding,
                                           metrics={"kq": 0.95, "kc": 0.95,
                                                    "applicable": 5})
    check("порог: планка применимости — из данных (checks.min_applicable_checks)",
          strict.status == PASSED and set(strict.thresholds["skipped"]) == {"min_kq", "min_kc"},
          str(strict.thresholds))

    data = {"gates": [{"id": "G-X", "agent": "A", "stages": [0], "min_kq": 0.9,
                       "min_kc": 0.8, "min_applicable": 7}],
            "execution": {"gate_bypass": True}}
    specs = load_gate_specs(Config(data, _P("config.yaml")))
    check("порог: min_kq/min_kc/min_applicable читаются ИЗ ДАННЫХ",
          len(specs) == 1 and specs[0].min_kq == 0.9 and specs[0].min_kc == 0.8
          and specs[0].min_applicable == 7, str(specs))

    # (а) планка применимости приходит ИЗ ДАННЫХ (checks.min_applicable_checks)
    cfg_data = _cfg()
    configured = cfg_data.get("checks.min_applicable_checks")
    from agents.gates import GateSpec as _GS
    check("порог: applicable_requirement берёт планку из данных",
          configured is not None
          and GateEngine(cfg_data).applicable_requirement(_GS("G-X", "A", (0,))) == int(configured),
          str({"data": configured,
               "engine": GateEngine(cfg_data).applicable_requirement(_GS("G-X", "A", (0,)))}))
    check("порог: gate-специфичная планка сильнее общей (данные гейта)",
          GateEngine(cfg_data).applicable_requirement(
              _GS("G-X", "A", (0,), min_applicable=99)) == 99)
    bare = Config({"gates": [], "execution": {"gate_bypass": True}}, _P("config.yaml"))
    check("порог: без данных планка = 1; значение гейта берётся само",
          GateEngine(bare).applicable_requirement(_GS("G-X", "A", (0,))) == 1
          and GateEngine(bare).applicable_requirement(
              _GS("G-X", "A", (0,), min_applicable=7)) == 7)

    # (б) physical = None, когда метрик нет (не «зелено» по умолчанию)
    no_metrics = eng.evaluate(_GS("G-Y", "A", (0,), min_kq=0.9), ok_finding, metrics={})
    check("порог: physical = None без метрик (не проверялось ≠ зелено)",
          no_metrics.physical is None, str(no_metrics.physical))
    explicit_true = eng.evaluate(_GS("G-Y", "A", (0,)), ok_finding,
                                 metrics={"physical": True, "applicable": 3})
    check("порог: physical=True только когда он явно посчитан",
          explicit_true.physical is True)
    not_physical = eng.evaluate(_GS("G-Y", "A", (0,)), ok_finding,
                                metrics={"physical": False, "applicable": 3})
    check("порог: явный physical=False валит гейт", not_physical.status == FAILED)

    # (в) applicable == 0: ни порог, ни физичность не валят и не «зеленят»
    none_applicable = eng.evaluate(_GS("G-Y", "A", (0,), min_kq=0.9, min_kc=0.9),
                                   ok_finding, metrics={"applicable": 0})
    check("порог: applicable=0 → не failed, порог пропущен, physical = None",
          none_applicable.status == PASSED and none_applicable.physical is None
          and none_applicable.thresholds["applied"] is False
          and set(none_applicable.thresholds["skipped"]) == {"min_kq", "min_kc"},
          str({"status": none_applicable.status,
               "physical": none_applicable.physical,
               "thresholds": none_applicable.thresholds}))

    check("порог: в config.yaml значения min_kq/min_kc НЕ заданы (прогон не меняется)",
          all(s.min_kq is None and s.min_kc is None for s in GateEngine(_cfg()).specs()),
          str([(s.id, s.min_kq, s.min_kc) for s in GateEngine(_cfg()).specs()]))


def test_parse_threshold() -> None:
    from agents.checks.base import parse_threshold, split_thresholds

    th, why = parse_threshold("<= 5%")
    check("порог: «<= 5%» → 0.05 (le)", th is not None and th.op == "le"
          and abs(th.value - 0.05) < 1e-12 and not why, f"{th} {why}")
    th, _ = parse_threshold(">= 0.7")
    check("порог: «>= 0.7» → ge 0.7", th is not None and th.op == "ge" and th.value == 0.7)
    th, _ = parse_threshold("in [0.01, 0.50]")
    check("порог: «in [a, b]» → between",
          th is not None and th.op == "between" and (th.lo, th.hi) == (0.01, 0.50))
    th, why = parse_threshold("~0.5")
    check("порог: непарсибельный → (None, причина)", th is None and bool(why), str(why))
    th, _ = parse_threshold("Nugget ≤ 0.1")
    check("порог: имя метрики и Unicode «≤» распознаются (≤ 0.1)",
          th is not None and th.op == "le" and abs(th.value - 0.1) < 1e-12, str(th))
    th, _ = parse_threshold(">= 100%")
    check("порог: «>= 100%» → 1.0", th is not None and th.value == 1.0, str(th))
    check("порог: клаузы через «;»",
          len(split_thresholds("Nugget <= 0.1; Range >= 500")) == 2)
    check("порог: клаузы через «|» (безопасно для CSV-разделителя «;»)",
          len(split_thresholds("NUG <= 0.1 | RNG >= 500")) == 2)


# -- 5. qaqc в отчёте и покрытие чеклиста ---------------------------------------------
def test_qaqc_artifacts() -> None:
    import json

    from agents.checks.report import build_qaqc_artifacts, package_blocks

    cfg = _cfg()
    with tempfile.TemporaryDirectory() as tmp:
        payload = build_qaqc_artifacts(cfg, {}, tmp)
        required = ("total", "passed", "failed", "not_applicable", "unknown", "by_block",
                    "kq", "kc", "fitness", "physical", "failed_checks")
        check("отчёт: блок qaqc содержит все обязательные ключи",
              all(k in payload for k in required), str(sorted(payload)))
        check("отчёт: qaqc.json и qaqc_coverage.json записаны",
              (Path(tmp) / "qaqc.json").is_file()
              and (Path(tmp) / "qaqc_coverage.json").is_file())
        total = payload["total"]
        check("отчёт: сумма состояний = total",
              payload["passed"] + payload["failed"] + payload["not_applicable"]
              + payload["unknown"] == total, str(payload["total"]))
        check("отчёт: блоки — из данных checks.package_blocks",
              set(payload["by_block"]) <= set(package_blocks(cfg)),
              str(sorted(payload["by_block"])))
        check("отчёт: пустые значения → not_applicable, а не failed",
              payload["failed"] == 0 and payload["not_applicable"] > 0,
              str({k: payload[k] for k in ("failed", "not_applicable", "applicable")}))
        check("отчёт: applicable = passed + failed (сколько проверок судило модель)",
              payload["applicable"] == payload["passed"] + payload["failed"],
              str({"applicable": payload["applicable"], "passed": payload["passed"],
                   "failed": payload["failed"]}))
        check("отчёт: «не проверялось» ≠ «зелено» (physical = null без данных)",
              payload["physical"] is None and payload["physical_known"] is False,
              str({"physical": payload["physical"],
                   "known": payload["physical_known"]}))
        check("отчёт: веса свёртки — из данных (alpha/beta)",
              payload["weights"] == {"alpha": cfg.get("checks.fitness_alpha"),
                                     "beta": cfg.get("checks.fitness_beta")},
              str(payload["weights"]))

        coverage = json.loads((Path(tmp) / "qaqc_coverage.json").read_text(encoding="utf-8"))
        summary = coverage["summary"]
        check("покрытие: 6065 пунктов чеклиста", summary["checklist_items"] == 6065,
              str(summary))
        check("покрытие: реализовано = каталог проверок",
              summary["implemented"] == payload["sources"]["catalog_checks"],
              str({"implemented": summary["implemented"],
                   "catalog": payload["sources"]["catalog_checks"]}))
        check("покрытие: неформализованные пункты = unknown с причиной",
              summary["unknown_unformalized"] > 0
              and all(b["reason"] for b in coverage["blocks"] if b["not_implemented"]),
              str([b["block"] for b in coverage["blocks"] if b["not_implemented"]
                   and not b["reason"]]))
        check("покрытие: источники чисел пунктов зафиксированы",
              all(b["checklist_items_source"] for b in coverage["blocks"]))
        b11 = next(b for b in coverage["blocks"] if b["block"] == "11")
        check("покрытие: блок вне области — unknown с причиной, не failed",
              b11["implemented"] == 0 and b11["status"] == "out_of_scope"
              and bool(b11["reason"]), json.dumps(b11, ensure_ascii=False)[:200])
        check("покрытие: у каждой проверки — блок/гейт/агент",
              all(b["gates"] or b["block"] in ("11", "12", "14") for b in coverage["blocks"]),
              str([b["block"] for b in coverage["blocks"] if not b["gates"]]))
        reasons = [r for b in coverage["blocks"] for r in b["unknown_reasons"]]
        check("покрытие: у unknown-проверок есть причина",
              all(r.get("reason") for r in reasons), str(reasons[:3]))

        # --- построчный статус 195 пунктов вне 13 блоков (требование приёмки) ---
        meta = coverage["meta"]
        outside = meta.get("items_outside_blocks")
        detail = meta.get("items_outside_blocks_detail")
        check("покрытие: items_outside_blocks — число (арифметика 6065 не ломается)",
              isinstance(outside, int) and outside == 195, str(outside))
        check("покрытие: у 195 внешних пунктов построчный статус и причина",
              isinstance(detail, dict) and detail.get("total") == outside
              and len(detail.get("items") or []) == outside
              and all(len(row) == 3 for row in (detail.get("items") or [])[:5])
              and bool(detail.get("reason")) and bool(detail.get("by_type")),
              json.dumps(detail, ensure_ascii=False)[:220] if isinstance(detail, dict)
              else str(detail))
        points = summary.get("points") or {}
        by_status = points.get("by_status") or {}
        check("покрытие: авторитетная раскладка 6065 ПУНКТОВ из пакета QA/QC",
              points.get("total") == 6065
              and sum(int(v) for v in by_status.values()) == 6065
              and set(by_status) == {"implemented", "not_applicable", "unknown"},
              json.dumps(points, ensure_ascii=False)[:220])
        with_points = [b for b in coverage["blocks"] if b.get("points")]
        pts_sum = sum(int(b["points"].get("total") or 0) for b in with_points)
        check("покрытие: пункты по блокам + внешние = 6065",
              pts_sum + outside == 6065
              and all(b["points"].get("status") for b in with_points),
              f"по блокам {pts_sum} + внешних {outside}")
        check("покрытие: статус блока дан и на уровне ПУНКТОВ (status_note)",
              all(b["points"].get("status_note") for b in with_points),
              str([b["block"] for b in with_points if not b["points"].get("status_note")]))

        # --- 7 «качественных» проверок: авторитетный источник ---
        consistency = payload.get("consistency") or {}
        described = set(consistency.get("described_only_ids") or [])
        unknown_ids = {r["id"] for r in reasons}
        check("описания без исполнителя: перечень — из данных пакета (DESCRIBED_ONLY)",
              consistency.get("described_but_not_executable") == len(described)
              and described <= unknown_ids,
              str({"described": sorted(described), "consistency": consistency})[:220])
        check("описания без исполнителя: причина названа (не «провал»)",
              all("DESCRIBED_ONLY" in r["reason"] for r in reasons
                  if r["id"] in described),
              str([r for r in reasons if r["id"] in described][:2]))
        check("покрытие: артефакт самодостаточен (consistency есть и в qaqc_coverage)",
              (coverage.get("consistency") or {}).get("described_only_ids")
              == consistency.get("described_only_ids")
              and bool((coverage.get("consistency") or {}).get("described_only_ids")),
              str(coverage.get("consistency"))[:200])


def test_qaqc_blocks_come_from_data() -> None:
    """Смена данных `checks.package_blocks` меняет объём qaqc — списков в коде нет."""
    import json

    from agents.checks.report import build_qaqc_artifacts
    from core.config import Config

    cfg = _cfg()
    raw = json.loads(json.dumps(cfg.raw))
    raw["checks"]["package_blocks"] = {"G-DATA": ["02"]}
    cfg2 = Config(raw, Path("config.yaml").resolve())
    with tempfile.TemporaryDirectory() as tmp:
        payload = build_qaqc_artifacts(cfg2, {}, tmp)
        check("данные: один блок в данных → только он в отчёте",
              list(payload["by_block"]) == ["02"], str(payload["by_block"]))
        check("данные: total = число проверок блока 02", payload["total"] == 438,
              str(payload["total"]))


# -- 6. dry-run с включёнными порогами (сквозная проверка) ----------------------------
def test_dry_run_with_thresholds() -> None:
    import json

    from core.coordinator import Coordinator

    cfg = _cfg()
    for gate in ("G-DATA", "G-STRUCT", "G-GRID", "G-FACIES", "G-PETRO",
                 "G-SAT", "G-VOL", "G-MAPS"):
        cfg.set(f"gates_override.{gate}.min_kq", 0.99)
        cfg.set(f"gates_override.{gate}.min_kc", 0.99)
    coord = Coordinator(cfg, dry_run=True)
    with tempfile.TemporaryDirectory() as tmp:
        report = coord.run("Герасимовское", run_dir=Path(tmp) / "run", execute=False)
        agents = report.get("agents") or {}
        stages = agents.get("stages") or []
        statuses = sorted({s["status"] for s in stages})
        check("dry-run: порог 0.99 не валит и не деградирует гейты",
              not ({"failed", "bypassed", "skipped"} & set(statuses)), str(statuses))
        check("dry-run: вердикт прогона pending_execution",
              agents.get("verdict") == "pending_execution", str(agents.get("verdict")))
        check("dry-run: error=0 и render_warnings=[]",
              report["steps"]["error"] == 0 and report["render_warnings"] == [],
              str({"steps": report["steps"], "warnings": report["render_warnings"]}))
        # Пропусков может быть несколько (врез + неподтверждённые пробой шаги +
        # шаги без объекта-предпосылки): инвариант — каждый пропуск учтён в счётчике.
        counts = report["steps"]["counts"]
        check("dry-run: skipped_by_policy >= 1 и done = total − skipped",
              counts.get("skipped_by_policy", 0) >= 1
              and report["steps"]["done"] == report["steps"]["total"]
              - counts.get("skipped_by_policy", 0),
              str({"counts": counts, "steps": report["steps"]}))
        qaqc = report.get("qaqc")
        check("dry-run: qaqc в report.json посчитан",
              isinstance(qaqc, dict) and qaqc.get("total")
              and "by_block" in qaqc and "failed_checks" in qaqc, str(qaqc)[:200])
        check("dry-run: «не проверялось» ≠ «зелено» в отчёте (physical = null)",
              qaqc.get("physical") is None and qaqc.get("applicable") == 0,
              str({k: qaqc.get(k) for k in ("physical", "applicable", "passed",
                                            "failed", "not_applicable")}))
        gate_file = Path(tmp) / "run" / "agents" / "gates" / "G-STRUCT.json"
        verdict = json.loads(gate_file.read_text(encoding="utf-8")) if gate_file.is_file() else {}
        check("dry-run: вердикт гейта несёт physical=null и пропущенный порог",
              verdict.get("physical") is None
              and verdict.get("thresholds", {}).get("applied") is False
              and verdict.get("thresholds", {}).get("skipped"),
              json.dumps({k: verdict.get(k) for k in ("status", "physical", "thresholds")},
                         ensure_ascii=False))
        check("dry-run: qaqc-артефакты в каталоге прогона",
              (Path(tmp) / "run" / "qaqc.json").is_file()
              and (Path(tmp) / "run" / "qaqc_coverage.json").is_file())


def test_qaqc_matches_package_adapter() -> None:
    """Сводка верхнего уровня НЕ расходится с domain/qaqc_adapter на тех же данных.

    Оба пути вызывают один движок, поэтому passed/failed/not_applicable и kq/kc
    обязаны совпасть (иначе в отчёте два разных числа качества).
    """
    try:
        from domain import qaqc
        from domain.qaqc_adapter import evaluate as adapter_eval, package_available
    except Exception as exc:                       # noqa: BLE001
        check("сверка с пакетом: импорт", False, repr(exc))
        return
    if not package_available():
        return
    from agents.checks.report import collect_outcomes, package_blocks, summarize

    cfg = _cfg()
    blocks = package_blocks(cfg)
    values = {"H_well": [10.0, 12.0], "H_topo": [10.5, 11.0], "THICKNESS": [12.0, 15.0],
              "H_top": [-1000.0, -1010.0], "H_bot": [-1012.0, -1025.0],
              "observed": [0.0, 1.0, 2.0], "model": [0.0, 1.0, 3.0],
              "D_bottom": [200.0, 300.0], "D_top": [150.0, 190.0],
              "GRID": [250.0, 311.0, 22.0], "H_grid": [-2529.8, -2360.3]}
    adapter = adapter_eval(values, blocks=tuple(blocks), alpha=0.5, beta=0.5)
    rows = [r for r in collect_outcomes(cfg, values, only_blocks=blocks)
            if r.id in qaqc.CHECKS]
    mine = summarize(rows, alpha=0.5, beta=0.5)
    check("сверка с пакетом: total совпадает",
          mine["total"] == adapter.total,
          f"adapter={adapter.total} mine={mine['total']}")
    check("сверка с пакетом: passed/failed/not_applicable совпадают",
          (mine["passed"], mine["failed"], mine["not_applicable"])
          == (adapter.passed, adapter.failed, adapter.not_applicable),
          f"adapter=({adapter.passed},{adapter.failed},{adapter.not_applicable}) "
          f"mine=({mine['passed']},{mine['failed']},{mine['not_applicable']})")
    check("сверка с пакетом: kq/kc/fitness совпадают",
          (mine["kq"], mine["kc"], mine["fitness"])
          == (round(adapter.kq, 4), round(adapter.kc, 4), round(adapter.fitness, 4)),
          f"adapter=({adapter.kq:.4f},{adapter.kc:.4f},{adapter.fitness:.4f}) "
          f"mine=({mine['kq']},{mine['kc']},{mine['fitness']})")


def test_result_checks_f19() -> None:
    """F-19: гейт обязан видеть РЕЗУЛЬТАТ — «формально прошло, результата нет» нельзя.

    (а) нет свидетельства → unverified (не passed и не failed), гейт НЕ passed;
    (б) свойство отсутствует в списке → failed с явным сообщением;
    (в) свойство есть и непусто → passed.
    """
    from agents.checks import CheckRegistry, UNVERIFIED
    from agents.contracts import FAILED, PASSED, PENDING
    from agents.gates import GateEngine

    cfg = _cfg()
    reg = CheckRegistry.from_config(cfg)
    engine = GateEngine(cfg)
    spec = engine.spec("G-FACIES")
    ctx = {"properties": cfg.get("checks.properties"),
           "metric_name": cfg.get("ensemble.metric")}

    # (а) свидетельства нет вовсе
    report = reg.run_report("G-FACIES", {}, ctx, include_runtime=True)
    states = {o.id: o.state for o in report.outcomes}
    check("F-19: без свидетельства проверки результата — unverified (не passed/failed)",
          states.get("facies.cube_exists") == UNVERIFIED
          and states.get("facies.cube_nonempty") == UNVERIFIED, str(states))
    verdict = engine.evaluate(spec, report.findings)
    check("F-19: гейт НЕ passed без свидетельства о результате (pending_execution)",
          verdict.status == PENDING and verdict.unverified
          and "facies.cube_exists" in verdict.unverified,
          str({"status": verdict.status, "unverified": verdict.unverified}))
    check("F-19: unverified не считается ни passed, ни failed в счётчиках",
          all(v == {"passed": 0, "failed": 0} for v in verdict.counts.values()),
          str(verdict.counts))

    # (б) свидетельство есть, куба НЕТ
    report2 = reg.run_report("G-FACIES", {"grid_properties": ["PORO", "PERM"]}, ctx,
                             include_runtime=True)
    exists = next(o for o in report2.outcomes if o.id == "facies.cube_exists")
    check("F-19: нет куба среди свойств → failed с явным сообщением",
          exists.state == "failed" and exists.finding is not None
          and not exists.finding.passed and "FACIES" in exists.finding.message
          and "PORO" in exists.finding.message,
          str(exists.finding.message if exists.finding else exists.state))
    verdict2 = engine.evaluate(spec, report2.findings)
    check("F-19: гейт failed, если проверка результата (critical) провалена",
          verdict2.status == FAILED, str(verdict2.status))

    # (в) куб есть и непуст
    ev_ok = {"grid_properties": ["FACIES", "PORO"],
             "property_stats": {"FACIES": {"count": 125000, "nulls": 0,
                                           "classes": [1, 2, 3]}}}
    report3 = reg.run_report("G-FACIES", ev_ok, ctx, include_runtime=True)
    states3 = {o.id: o.state for o in report3.outcomes if "cube" in o.id}
    check("F-19: куб есть и непуст → passed",
          states3.get("facies.cube_exists") == "passed"
          and states3.get("facies.cube_nonempty") == "passed", str(states3))
    verdict3 = engine.evaluate(spec, report3.findings)
    check("F-19: гейт passed только при подтверждённом результате",
          verdict3.status == PASSED and not verdict3.unverified, str(verdict3.status))

    # пустой куб: присутствует, но без значений
    ev_empty = {"grid_properties": ["FACIES"],
                "property_stats": {"FACIES": {"count": 0, "nulls": 125000, "classes": []}}}
    report4 = reg.run_report("G-FACIES", ev_empty, ctx, include_runtime=True)
    empty = next(o for o in report4.outcomes if o.id == "facies.cube_nonempty")
    check("F-19: присутствующий, но пустой куб ловится (failed)",
          empty.state == "failed"
          and "пуст" in (empty.finding.message if empty.finding else ""),
          str(empty.finding.message if empty.finding else empty.state))

    # правило разбора от petro: `classes` НИКОГДА не решает вопрос о непустоте
    def _nonempty(node: dict):
        ev = {"grid_properties": ["FACIES"], "property_stats": {"FACIES": node}}
        rep = reg.run_report("G-FACIES", ev, ctx, include_runtime=True)
        return next(o for o in rep.outcomes if o.id == "facies.cube_nonempty")

    truncated = _nonempty({"count": 100, "cells": 1000, "nulls": 900,
                           "unique_count": 100, "classes_truncated": 1})
    check("F-19: классы не перечислены (classes_truncated) → НЕ «пусто»",
          truncated.state == "passed" and truncated.finding is not None
          and "не перечислены" in truncated.finding.message,
          str({"state": truncated.state,
               "message": truncated.finding.message if truncated.finding else ""}))
    foreign_empty = _nonempty({"count": 500, "cells": 1000, "nulls": 500,
                               "classes": [], "unique_count": 3})
    check("F-19: пустой список классов при непустом кубе → решение по count (passed)",
          foreign_empty.state == "passed"
          and bool((foreign_empty.finding.evidence.get("classes_note")
                    if foreign_empty.finding else "")),
          str({"state": foreign_empty.state,
               "note": (foreign_empty.finding.evidence.get("classes_note")
                        if foreign_empty.finding else "")}))
    fraction_only = _nonempty({"nonempty_fraction": 0.42, "unique_count": 5,
                               "classes_truncated": 1})
    check("F-19: доля непустых из данных (nonempty_fraction) используется как критерий",
          fraction_only.state == "passed", str(fraction_only.state))
    no_count = _nonempty({"cells": 1000})
    check("F-19: только общее число ячеек (без nulls/count) → unverified, не «зелено»",
          no_count.state == UNVERIFIED, str(no_count.state))
    contradiction = _nonempty({"count": 10, "unique_count": 0})
    check("F-19: противоречие свидетельства (count>0, unique=0) → unverified",
          contradiction.state == UNVERIFIED, str(contradiction.state))

    # --- G-VOL: существует И непусто свойство-МЕТРИКА (данные: ensemble.metric) ---
    vol = engine.spec("G-VOL")
    metric = str(cfg.get("ensemble.metric"))

    def _vol(ev: dict):
        rep = reg.run_report("G-VOL", ev, ctx, include_runtime=True)
        return {o.id: o.state for o in rep.outcomes if o.id.startswith("cube.")}, rep.findings

    # (а) метрики нет среди свойств сетки → failed
    st_a, f_a = _vol({"grid_properties": ["zone_id", "FACIES"]})
    check("G-VOL(а): метрики нет в grid_properties → failed",
          st_a.get("cube.metric_exists") == "failed"
          and any(not f.passed and f.id == "cube.metric_exists" for f in f_a)
          and engine.evaluate(vol, f_a).status == FAILED,
          str(st_a))
    # (б) метрика есть, но пуста → failed по непустоте
    st_b, f_b = _vol({"grid_properties": [metric],
                      "property_stats": {metric: {"count": 0, "cells": 1000, "nulls": 1000}}})
    check("G-VOL(б): метрика есть, count=0 → failed (cube.metric_nonempty)",
          st_b.get("cube.metric_nonempty") == "failed"
          and engine.evaluate(vol, f_b).status == FAILED, str(st_b))
    # (в) метрика есть и непуста → passed
    st_c, f_c = _vol({"grid_properties": [metric],
                      "property_stats": {metric: {"count": 205_000_000, "cells": 205_000_000,
                                                  "nulls": 0}}})
    check("G-VOL(в): метрика есть и непуста → passed",
          st_c.get("cube.metric_exists") == "passed"
          and st_c.get("cube.metric_nonempty") == "passed"
          and engine.evaluate(vol, f_c).status == PASSED, str(st_c))
    # (г) свидетельства property_stats нет → unverified → гейт НЕ passed
    st_d, f_d = _vol({"grid_properties": [metric]})
    verdict_d = engine.evaluate(vol, f_d)
    check("G-VOL(г): нет property_stats → unverified и гейт pending_execution",
          st_d.get("cube.metric_nonempty") == UNVERIFIED
          and "cube.metric_nonempty" in verdict_d.unverified
          and verdict_d.status == PENDING, str({"states": st_d,
                                                "status": verdict_d.status}))
    # (д) регистрация непустоты метрики — в данных qa_gate_map
    from agents.checks.base import load_gate_map as _load_map
    vol_listed = ((_load_map(cfg).get("result_checks") or {}).get("G-VOL") or [])
    check("G-VOL(д): cube.metric_nonempty зарегистрирован данными и включён в G-VOL",
          "cube.metric_nonempty" in vol_listed
          and "cube.metric_exists" in vol_listed, str(vol_listed))
    # (е) уровень из данных реально управляет вердиктом (не только спецификацией)
    cfg_low = _cfg()
    cfg_low.set("checks.check_severity", {"cube.metric_nonempty": "minor"})
    reg_low = CheckRegistry.from_config(cfg_low)
    rep_low = reg_low.run_report(
        "G-VOL", {"grid_properties": [metric],
                  "property_stats": {metric: {"count": 0, "cells": 1000, "nulls": 1000}}},
        ctx, include_runtime=True)
    code = next(o for o in rep_low.outcomes if o.id == "cube.metric_nonempty")
    check("G-VOL(е): уровень из данных доходит до находки и вердикта (minor → не failed)",
          code.severity == "minor" and code.state == "failed"
          and engine.evaluate(vol, rep_low.findings).status == PASSED,
          str({"severity": code.severity, "state": code.state,
               "verdict": engine.evaluate(vol, rep_low.findings).status}))
    # (ж) `note` — информационный уровень: находка видна, гейт по ней не падает
    from agents.contracts import SEVERITIES
    cfg_note = _cfg()
    cfg_note.set("checks.check_severity", {"cube.metric_nonempty": "note"})
    reg_note = CheckRegistry.from_config(cfg_note)
    rep_note = reg_note.run_report(
        "G-VOL", {"grid_properties": [metric],
                  "property_stats": {metric: {"count": 0, "cells": 1000, "nulls": 1000}}},
        ctx, include_runtime=True)
    note_out = next(o for o in rep_note.outcomes if o.id == "cube.metric_nonempty")
    verdict_note = engine.evaluate(vol, rep_note.findings)
    check("G-VOL(ж): уровень `note` из данных поддержан (находка видна, гейт не failed)",
          "note" in SEVERITIES and note_out.severity == "note"
          and note_out.state == "failed" and verdict_note.status == PASSED
          and verdict_note.counts.get("note", {}).get("failed") == 1,
          str({"severity": note_out.severity, "state": note_out.state,
               "verdict": verdict_note.status, "counts": verdict_note.counts}))

    # уровни проверок — ИЗ ДАННЫХ (checks.check_severity)
    from agents.checks import apply_severity_overrides
    from agents.checks.base import CheckSpec
    probe = CheckSpec("facies.cube_nonempty", "G-FACIES", "major", "t", lambda e, c: None)
    cfg_sev = _cfg()
    # ключи карты — ID проверок КАК ЕСТЬ (точки в id не являются путём)
    cfg_sev.set("checks.check_severity", {"facies.cube_nonempty": "critical"})
    check("F-19: уровень проверки переопределяется ИЗ ДАННЫХ (checks.check_severity)",
          apply_severity_overrides(probe, cfg_sev).severity == "critical"
          and apply_severity_overrides(probe, _cfg()).severity == "major",
          str({"override": apply_severity_overrides(probe, cfg_sev).severity,
               "base": apply_severity_overrides(probe, _cfg()).severity}))
    cfg_bad = _cfg()
    cfg_bad.set("checks.check_severity", {"facies.cube_nonempty": "что-то"})
    check("F-19: недопустимый уровень игнорируется (встроенный остаётся)",
          apply_severity_overrides(probe, cfg_bad).severity == "major")

    # регистрация: перечень из данных совпадает с зарегистрированными проверками
    from agents.checks.base import load_gate_map
    listed = (load_gate_map(cfg).get("result_checks") or {})
    registered = {c.id: (c.gate, tuple(c.gates)) for c in reg.all()}
    missing = [cid for ids in listed.values() for cid in ids if cid not in registered]
    wrong = [(cid, registered[cid][0]) for gid, ids in listed.items() for cid in ids
             if cid in registered and gid not in (registered[cid][0], *registered[cid][1])]
    check("F-19: регистрация проверок результата — из данных qa_gate_map.result_checks",
          bool(listed) and not missing and not wrong,
          str({"missing": missing, "wrong_gate": wrong}))
    ids = {i for blk in listed.values() for i in blk}
    check("F-19: проверки результата runtime (в dry-run не исполняются)",
          all(c.runtime for c in reg.all() if c.id in ids),
          str([c.id for c in reg.all() if c.id in ids and not c.runtime]))


def main() -> int:
    for fn in (test_gate_map_data, test_registry_from_data, test_registry_csv_schema,
               test_registry_degraded_paths, test_threshold_data_and_dry_run_safety,
               test_parse_threshold, test_qaqc_artifacts,
               test_qaqc_blocks_come_from_data, test_qaqc_matches_package_adapter,
               test_result_checks_f19, test_dry_run_with_thresholds):
        try:
            fn()
        except Exception as exc:                       # noqa: BLE001
            check(f"{fn.__name__}: без исключений", False, repr(exc))
    print("\n=== ИТОГ ===")
    print(f"всего: {len(_PASS) + len(_FAIL)} | провалено: {len(_FAIL)}")
    if _FAIL:
        print("Проваленные: " + ", ".join(_FAIL))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
