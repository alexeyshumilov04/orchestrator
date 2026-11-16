"""Тесты QA/QC-пакета E4: оцифрованные проверки чеклиста ГПН (блоки 05…13).

Запуск:  python -X utf8 tests/test_qaqc_checks.py

Проверяется:
  1) состав: 62 оцифрованные строки в ``ontology/qa_checks/bNN.csv`` (6/11/10/8/12/10/5),
     из них 55 вычислимых попадают в ``CHECKS``, 7 качественных — нет (``unknown``);
  2) ПОРОГИ СОВПАДАЮТ С ЧЕКЛИСТОМ: дословное совпадение «Критерий»/«Название»/
     «Значимость»/«Формула» с ``QAQC/QA_QC_чеклист.xlsx``; каждое число машинного
     порога объяснено числом из «Критерий» или «Метод / формула» того же пункта
     (7 исключений перечислены в ``ontology/qa_checks/README.md`` п.2.3);
  3) НЕИЗВЕСТНОЕ ≠ ЛОЖЬ: без данных проверки дают ``not_applicable`` (не ``failed``
     и не «прошло»); с данными — считаются;
  4) ОБРАТНАЯ СОВМЕСТИМОСТЬ: 652 исторические проверки не изменились (SHA-256 тела
     ``checks_table.csv`` из ``baseline.json``), сборка идемпотентна, старые записи
     ``checks.py``/``check_functions.py`` сохраняются дословно;
  5) ``qaqc_coverage.json``: все 6065 пунктов, статусы только из
     {implemented, not_applicable, unknown}, у каждого не-implemented есть причина,
     суммы по блокам сходятся, ни один пункт не помечен «пройдено».
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

QA_DIR = ROOT / "ontology" / "qa_checks"
PKG = ROOT / "domain" / "qaqc"
XLSX = ROOT.parent / "QAQC" / "QA_QC_чеклист.xlsx"

_PASS: list[str] = []
_FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (_PASS if cond else _FAIL).append(name)
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + ("" if cond else f"  <-- {detail}"))


def read_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(QA_DIR.glob("b[0-9][0-9].csv")):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                r["_file"] = path.name
                rows.append(r)
    return rows


def xlsx_rows() -> dict[str, dict]:
    """Строки чеклиста ГПН по ID (шапка в 3-й строке)."""
    import pandas as pd
    df = pd.read_excel(XLSX, sheet_name="Чек-лист", header=2, dtype=object)
    df.columns = ["N", "ID", "Type", "Layer", "Contour", "Where", "Block", "Check", "What",
                  "Inputs", "Method", "Criterion", "Weight", "ErrSource", "Complexity",
                  "Output", "Class", "Mechanism", "Who", "State", "Evidence", "Todo", "Source"]
    df = df[df["ID"].astype(str).str.strip().ne("ID проверки / пункта")]
    return {str(r["ID"]): r for _, r in df.iterrows()}


def norm(text) -> str:
    return " ".join(str(text).replace("\xa0", " ").split()).strip()


def nums(text) -> set[float]:
    """Числа текста; диапазоны «1.8-2.2» дают и 1.8, и 2.2 (берём модуль)."""
    out: set[float] = set()
    for m in re.findall(r"-?\d+(?:[.,]\d+)?", str(text or "")):
        try:
            v = round(float(m.replace(",", ".")), 10)
        except ValueError:
            continue
        out.add(v)
        out.add(round(abs(v), 10))
    return out


# --------------------------------------------------------------------------- #
def test_structure() -> None:
    rows = read_rows()
    check("структура: 62 оцифрованные строки", len(rows) == 62, f"получено {len(rows)}")
    per_file = {"b05.csv": 6, "b06.csv": 11, "b07.csv": 10, "b08.csv": 8,
                "b09.csv": 12, "b10.csv": 10, "b13.csv": 5}
    got = {name: sum(1 for r in rows if r["_file"] == name) for name in per_file}
    check("структура: состав по блокам 6/11/10/8/12/10/5", got == per_file, str(got))
    ids = [r["ID"] for r in rows]
    check("структура: ID уникальны", len(ids) == len(set(ids)))
    keys = {r["Ключ"] for r in csv.DictReader(
        open(QA_DIR / "model_keys.csv", encoding="utf-8-sig", newline=""), delimiter=";")}
    undeclared = sorted({k.strip() for r in rows for k in r["Входные ключи"].split(",")
                         if k.strip()} - keys)
    check("структура: все входные ключи объявлены в model_keys.csv", not undeclared,
          str(undeclared))
    from domain.qaqc.engine import PRIMITIVES
    allowed = set(PRIMITIVES) | {"direct", "bool", "unknown"}
    bad = sorted({r["Способ выполнения"] for r in rows} - allowed)
    check("структура: примитивы только из схемы (или unknown)", not bad, str(bad))


def test_target_ids_present() -> None:
    want = ([f"QC_GS_{i:03d}" for i in range(1, 7)]
            + [f"QC_LITH_{i:03d}" for i in range(1, 12)]
            + [f"QC_POR_{i:03d}" for i in range(1, 11)]
            + [f"QC_PERM_{i:03d}" for i in range(1, 9)]
            + [f"QC_SAT_{i:03d}" for i in range(1, 13)]
            + [f"QC_RES_{i:03d}" for i in range(1, 11)]
            + ["QC_PHYS_001", "QC_PHYS_002", "QC_PHYS_003", "QC_PHYS_005", "QC_PHYS_006"])
    have = {r["ID"] for r in read_rows()}
    check("целевой шаблон: все 62 требуемых QC_* оцифрованы",
          set(want) == have, f"нет: {sorted(set(want) - have)}; лишние: {sorted(have - set(want))}")


def test_thresholds_match_checklist() -> None:
    from domain.qaqc import CHECKS
    src = xlsx_rows()
    rows = read_rows()
    from domain.qaqc.build_from_ontology import collect
    by_id = {c.id: c for c in collect()["checks"]}

    mismatch_verbatim: list[str] = []
    unjustified: list[str] = []
    unknown_in_checks: list[str] = []
    # пороги, для которых числа нет в критерии — обоснованы методом (README 2.3)
    method_only = {"QC_GS_006"}
    semantic_zero = {"QC_GS_003", "QC_PERM_003", "QC_RES_008",
                     "QC_PHYS_001", "QC_PHYS_002", "QC_PHYS_003"}
    for row in rows:
        cid = row["ID"]
        s = src.get(cid)
        if s is None:
            mismatch_verbatim.append(f"{cid}: нет в чеклисте")
            continue
        for col, value in (("Критерий", "Criterion"), ("Название", "Check"),
                           ("Формула", "Method")):
            if norm(row[col]) != norm(s[value]):
                mismatch_verbatim.append(f"{cid}.{col}")
        if abs(float(row["Значимость"]) - float(s["Weight"])) > 1e-9:
            mismatch_verbatim.append(f"{cid}.Значимость")
        if row["Способ выполнения"] == "unknown":
            if cid in CHECKS:
                unknown_in_checks.append(cid)
            continue
        chk = by_id[cid]
        n_allowed = nums(s["Criterion"]) | nums(s["Method"])
        for spec in chk.metrics:
            th = spec.threshold
            vals = {round(v, 10) for v in (th.value,) if v is not None}
            if th.op == "between":
                vals = {round(th.lo, 10), round(th.hi, 10)}
            for v in vals:
                if v in n_allowed:
                    continue
                if th.is_percent and round(v * 100.0, 10) in n_allowed:
                    continue                      # «≤ 5%» → 0.05
                if abs(v) < 1e-12 and cid in semantic_zero:
                    continue                      # «нет аномалий/расхождений…» ⇔ 0
                if v == 1.0 and cid in semantic_zero:
                    continue                      # «a ≥ среднего» ⇔ отношение ≥ 1
                if cid in method_only:
                    continue
                unjustified.append(f"{cid}: порог {v}")
            for v in (spec.params or {}).values():
                if (round(float(v), 10) not in n_allowed
                        and round(float(v) * 100.0, 10) not in n_allowed):
                    unjustified.append(f"{cid}: диапазон {v}")
    check("пороги: «Критерий»/«Название»/«Формула»/«Значимость» дословно из чеклиста",
          not mismatch_verbatim, str(mismatch_verbatim[:5]))
    check("пороги: каждое число порога объяснено чеклистом (или README 2.3)",
          not unjustified, str(unjustified[:8]))
    check("пороги: проверки с «unknown» НЕ попадают в CHECKS", not unknown_in_checks,
          str(unknown_in_checks))


def test_no_data_is_not_applicable() -> None:
    from domain.qaqc import CHECKS
    from domain.qaqc_adapter import _applicability
    from domain.qc import values as val
    new = [c for cid, c in CHECKS.items() if cid.startswith("QC_")]
    check("неизвестное≠ложь: 55 вычислимых QC_* в CHECKS", len(new) == 55, str(len(new)))
    bad_slug, bad_state = [], []
    for chk in new:
        slot = val.evaluate(chk, {})
        if slot.state != val.NOT_APPLICABLE:
            bad_slug.append(f"{chk.id}={slot.state}")
        result = __import__("domain.qaqc", fromlist=["run_check"]).run_check(chk.id)
        if _applicability(result) != "not_applicable":
            bad_state.append(chk.id)
    check("неизвестное≠ложь: без данных все QC_* → not_applicable (values)", not bad_slug,
          str(bad_slug[:5]))
    check("неизвестное≠ложь: без данных все QC_* → not_applicable (адаптер пакета)",
          not bad_state, str(bad_state[:5]))
    check("неизвестное≠ложь: 7 качественных критериев остались unknown",
          len(new) == 55 and len(read_rows()) - len(new) == 7)


def test_with_data_computes() -> None:
    from domain.qc import values as val
    from domain.qaqc import CHECKS
    cases = [
        ("QC_PHYS_001", {"PORO": [0.2, 0.3, 0.4]}, val.PASSED),
        ("QC_PHYS_001", {"PORO": [0.2, 0.9]}, val.FAILED),
        ("QC_PHYS_002", {"PERM": [1.0, 100.0]}, val.PASSED),
        ("QC_PHYS_003", {"SW": [0.0, 1.0]}, val.PASSED),
        ("QC_GS_005", {"N_REALIZATIONS": 50}, val.PASSED),
        ("QC_GS_005", {"N_REALIZATIONS": 10}, val.FAILED),
        ("QC_GS_004", {"RANGE_MAJOR_M": 1000.0, "RANGE_MINOR_M": 400.0}, val.PASSED),
        ("QC_GS_004", {"RANGE_MAJOR_M": 1000.0, "RANGE_MINOR_M": 10.0}, val.FAILED),
        ("QC_LITH_002", {"NTG_MOD": 0.80, "NTG_WELLS": 0.78}, val.PASSED),
        ("QC_LITH_002", {"NTG_MOD": 0.80, "NTG_WELLS": 0.70}, val.FAILED),
        ("QC_PERM_001", {"LOG_PERM_PRED": [1.0, 2.0, 3.0], "LOG_PERM_OBS": [1.1, 1.9, 3.1]},
         val.PASSED),
        ("QC_SAT_004", {"WOC_DIP_DEG": 0.5}, val.PASSED),
        ("QC_SAT_004", {"WOC_DIP_DEG": 1.5}, val.FAILED),
        ("QC_SAT_006", {"ARCHIE_M": 2.0, "ARCHIE_N": 2.0, "ARCHIE_A": 1.0}, val.PASSED),
        ("QC_SAT_006", {"ARCHIE_M": 3.0, "ARCHIE_N": 2.0, "ARCHIE_A": 1.0}, val.FAILED),
        ("QC_RES_009", {"N_CALC": 100.0, "N_MOD": 102.0}, val.PASSED),
        ("QC_RES_009", {"N_CALC": 100.0, "N_MOD": 110.0}, val.FAILED),
        ("QC_RES_008", {"PVT_MODEL": [1.2, 1.0], "PVT_APPROVED": [1.2, 1.0]}, val.PASSED),
        ("QC_RES_008", {"PVT_MODEL": [1.2, 1.0], "PVT_APPROVED": [1.2, 1.1]}, val.FAILED),
    ]
    wrong = []
    for cid, values, expect in cases:
        slot = val.evaluate(CHECKS[cid], values)
        if slot.state != expect:
            wrong.append(f"{cid}: {slot.state} != {expect}")
    check("с данными: 19 эталонных случаев считаются верно", not wrong, str(wrong[:5]))

    # частичные данные: не хватает одного ключа → not_applicable с перечнем
    slot = val.evaluate(CHECKS["QC_SAT_006"], {"ARCHIE_M": 2.0})
    check("частичные данные: не хватает ключей → not_applicable + перечень",
          slot.state == val.NOT_APPLICABLE and set(slot.missing) == {"ARCHIE_N", "ARCHIE_A"},
          f"{slot.state} {slot.missing}")
    summary = val.summarize(val.evaluate_all({"PORO": [0.2], "N_REALIZATIONS": 60},
                                             blocks=("05", "13")))
    check("матрица применимости: сводка различает применимые и неприменимые",
          summary["total"] >= 11 and summary["passed"] >= 1
          and summary["not_applicable"] >= 9 and summary["failed"] == 0,
          json.dumps(summary, ensure_ascii=False)[:200])


def test_backward_compat_and_idempotency() -> None:
    base = json.loads((QA_DIR / "baseline.json").read_text(encoding="utf-8"))
    raw = (PKG / "checks_table.csv").read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    lines = raw.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    body = lines[1:]
    n_base = int(base["checks_table_rows"])
    got = hashlib.sha256(("\n".join(body[:n_base]) + "\n").encode("utf-8")).hexdigest()
    check("совместимость: первые 652 строки checks_table.csv не изменились",
          got == base["sha256_body"], f"{got[:16]} != {base['sha256_body'][:16]}")
    check("совместимость: в CSV 652 старые + 62 новые проверки",
          len([r for r in csv.reader(open(PKG / "checks_table.csv", encoding="utf-8-sig",
                                          newline=""), delimiter=";")][1:]) == n_base + 62)

    from domain.qaqc import CHECKS
    old = [cid for cid in CHECKS if not cid.startswith("QC_")]
    check("совместимость: 652 исторические проверки на месте", len(old) == 652, str(len(old)))
    check("совместимость: вычислимость исторических проверок 234/418 не сдвинулась",
          sum(1 for c in old if any(m.kind not in ("direct", "bool")
                                    for m in CHECKS[c].metrics)) == 234)

    from domain.qaqc import build_from_ontology as bfo
    data = bfo.collect()
    ids = {r["ID"] for r in data["rows"]}
    table_now = (PKG / "checks_table.csv").read_text(encoding="utf-8-sig")
    merged, _ = bfo.merge_table(table_now, data["rows"], ids)
    check("идемпотентность: checks_table.csv пересобирается в тот же текст",
          merged == table_now)
    checks_now = (PKG / "checks.py").read_text(encoding="utf-8")
    check("идемпотентность: checks.py пересобирается в тот же текст",
          bfo.merge_checks_py(checks_now, data["checks"], data["described"], ids) == checks_now)
    funcs_now = (PKG / "check_functions.py").read_text(encoding="utf-8")
    check("идемпотентность: check_functions.py пересобирается в тот же текст",
          bfo.merge_funcs_py(funcs_now, data["checks"], ids) == funcs_now)


def test_coverage() -> None:
    from domain.qaqc import coverage
    rep = coverage.build()
    check("покрытие: 6065 пунктов чеклиста", rep["total"] == 6065, str(rep["total"]))
    allowed = {coverage.STATUS_IMPLEMENTED, coverage.STATUS_NOT_APPLICABLE,
               coverage.STATUS_UNKNOWN}
    bad = {p[2] for p in rep["points"]} - allowed
    check("покрытие: статусы только implemented/not_applicable/unknown", not bad, str(bad))
    check("покрытие: статуса «пройдено» нет ни у одного пункта",
          "passed" not in json.dumps(rep["by_status"]))
    check("покрытие: у каждого не-implemented пункта есть причина",
          all(p[3] for p in rep["points"] if p[2] != coverage.STATUS_IMPLEMENTED))
    total_block = sum(v["total"] for v in rep["by_block"].values())
    check("покрытие: суммы по блокам = 6065", total_block == 6065, str(total_block))
    counts = rep["by_status"]
    check("покрытие: суммы статусов = 6065",
          sum(counts.values()) == 6065, str(counts))
    check("покрытие: историческая база 234/418 в пакете сохранена",
          rep["packages"]["checks_total"] == 707
          and rep["packages"]["checks_implemented"] == 289
          and rep["packages"]["checks_not_applicable"] == 418,
          json.dumps(rep["packages"], ensure_ascii=False)[:160])
    check("покрытие: +55 вычислимых QC_* попали в implemented",
          counts[coverage.STATUS_IMPLEMENTED] >= 55, str(counts))
    check("покрытие: 7 качественных QC_* помечены unknown (R3)",
          any(r["code"] == coverage.R_QUALITATIVE and r["count"] == 7
              for r in rep["reasons"]))
    files = PKG / "qaqc_coverage.json"
    check("покрытие: артефакт domain/qaqc/qaqc_coverage.json записан", files.is_file())
    if files.is_file():
        disk = json.loads(files.read_text(encoding="utf-8"))
        check("покрытие: артефакт совпадает с пересчётом",
              disk["by_status"] == rep["by_status"] and disk["total"] == rep["total"])


def test_adapters() -> None:
    from agents.checks import adapters
    # B02-0001: max |H_well − H_topo| <= 1.0 — данные есть, проверка применима
    values = {"H_well": [100.0], "H_topo": [100.5]}
    findings, metrics = adapters.package_evaluate(("02",), values, alpha=0.6, beta=0.4)
    check("адаптеры: package_evaluate принимает alpha/beta и даёт kq/kc",
          isinstance(metrics, dict) and "kq" in metrics and "kc" in metrics
          and bool(findings), json.dumps(metrics, ensure_ascii=False)[:120])
    empty, m_empty = adapters.package_evaluate(("05",), {})
    check("адаптеры: пустые значения → нет находок (модель не штрафуется)",
          empty == [] and m_empty == {})
    matrix = adapters.applicability_matrix(("13",), {"PORO": [0.2]})
    check("адаптеры: матрица применимости считает not_applicable без находок",
          matrix.get("total", 0) >= 1 and "missing_keys" in matrix)
    report = adapters.not_applicable_report(values)
    check("адаптеры: not_applicable_report — данные, не находки",
          isinstance(report, list) and all(isinstance(x, dict) for x in report))


def test_generator_validation() -> None:
    from domain.qaqc import build_from_ontology as bfo
    data = bfo.collect()
    known = bfo.known_package_ids()
    problems = bfo.validate(data["rows"], data["keys"],
                            {i for i in known if not i.startswith("QC_")})
    check("генератор: данные ontology/qa_checks проходят валидацию", not problems,
          str(problems[:3]))
    bad = [dict(r) for r in data["rows"][:1]]
    bad[0]["Порог"] = "<= abc"
    extra = bfo.validate(bad + data["rows"][1:], data["keys"],
                         {i for i in known if not i.startswith("QC_")})
    check("генератор: непарсибельный порог — ошибка, а не тихий пропуск", bool(extra))
    bad2 = [dict(data["rows"][0])]
    bad2[0]["Входные ключи"] = "НЕТ_ТАКОГО_КЛЮЧА"
    bad2[0]["Порог"] = ">= 0"
    extra2 = bfo.validate(bad2, data["keys"], set())
    check("генератор: незаявленный ключ — ошибка", any("model_keys" in p for p in extra2),
          str(extra2[:2]))


def test_coverage_block_status() -> None:
    from domain.qaqc import coverage
    rep = coverage.build()
    bad: list[str] = []
    for code, slot in rep["by_block"].items():
        status = slot.get("status")
        impl, na, unk = (slot[coverage.STATUS_IMPLEMENTED],
                         slot[coverage.STATUS_NOT_APPLICABLE],
                         slot[coverage.STATUS_UNKNOWN])
        if impl + na + unk != slot["total"]:
            bad.append(f"{code}: числа не сходятся")
        want = (coverage.BLOCK_NOT_IMPLEMENTED if impl == 0
                else coverage.BLOCK_IMPLEMENTED if impl == slot["total"]
                else coverage.BLOCK_PARTIAL)
        if status != want:
            bad.append(f"{code}: status={status} при implemented={impl}/{slot['total']}")
        note = slot.get("status_note", "")
        if f"implemented={impl}" not in note or f"из {slot['total']}" not in note:
            bad.append(f"{code}: причина не согласована с числами: {note[:60]}")
    check("покрытие: статус каждого блока согласован с его числами", not bad, str(bad[:4]))
    check("покрытие: блоки 07/08/09/10 не помечены not_implemented при implemented>0",
          all(rep["by_block"][b]["status"] != coverage.BLOCK_NOT_IMPLEMENTED
              for b in ("07", "08", "09", "10")),
          str({b: rep["by_block"].get(b, {}).get("status") for b in ("07", "08", "09", "10")}))

    meta = rep["meta"]["items_outside_blocks"]
    check("покрытие: 195 пунктов вне 13 блоков вынесены в meta.items_outside_blocks",
          meta["total"] == 195 and len(meta["items"]) == 195, str(meta["total"]))
    check("покрытие: у пунктов вне блоков построчный статус unknown + причина",
          all(it[1] == coverage.STATUS_UNKNOWN and it[2] for it in meta["items"])
          and meta["status"] == coverage.STATUS_UNKNOWN)
    check("покрытие: meta.by_type покрывает все 195 пунктов",
          sum(meta["by_type"].values()) == 195, str(meta["by_type"]))
    check("покрытие: сводка без passed/failed и суммой 6065",
          set(rep["by_status"]) == {coverage.STATUS_IMPLEMENTED,
                                    coverage.STATUS_NOT_APPLICABLE,
                                    coverage.STATUS_UNKNOWN}
          and sum(rep["by_status"].values()) == 6065)


def test_physical_tristate() -> None:
    from domain.qaqc_adapter import evaluate
    empty = evaluate({})
    check("физичность: нет применимых проверок → physical=None (не «зелено»)",
          empty.physical is None and empty.applicable == 0
          and empty.to_dict()["physical_known"] is False,
          f"physical={empty.physical} applicable={empty.applicable}")
    ok = evaluate({"H_well": [100.0], "H_topo": [100.5]})
    check("физичность: применимая проверка пройдена → physical=True (applicable>0)",
          ok.physical is True and ok.applicable >= 1, str(ok.physical))
    bad = evaluate({"H_well": [100.0], "H_topo": [120.0]})
    check("физичность: провал → physical=False",
          bad.physical is False and bad.failed >= 1, str(bad.physical))
    from agents.checks import adapters
    _, metrics = adapters.package_evaluate(("02",), {"H_well": [100.0], "H_topo": [100.5]})
    check("адаптеры: physical_known передаётся в метрики гейта",
          metrics.get("physical") is True and metrics.get("physical_known") is True,
          json.dumps(metrics, ensure_ascii=False)[:120])


def test_described_only() -> None:
    """7 качественных проверок: в пакете описаны, но НЕ исполняемы (правило 6)."""
    from domain.qaqc import CHECKS, DESCRIBED_ONLY
    want = {"QC_LITH_005", "QC_LITH_006", "QC_LITH_008", "QC_LITH_010",
            "QC_PERM_006", "QC_SAT_007", "QC_SAT_008"}
    check("качественные: 7 проверок есть в пакете как DESCRIBED_ONLY",
          set(DESCRIBED_ONLY) == want, str(sorted(DESCRIBED_ONLY)))
    check("качественные: в CHECKS их нет (метрики не выдуманы)",
          not (set(DESCRIBED_ONLY) & set(CHECKS)))
    check("качественные: у них нет метрик (иначе «пройдено» без критерия)",
          all(not c.metrics for c in DESCRIBED_ONLY.values()))
    from domain.qaqc import coverage
    rep = coverage.build()
    check("качественные: покрытие видит их как described_only",
          set(rep["packages"]["checks_described_only"]) == want
          and any(r["code"] == coverage.R_QUALITATIVE and r["count"] == 7
                  for r in rep["reasons"]))


def main() -> int:
    for fn in (test_structure, test_target_ids_present, test_thresholds_match_checklist,
               test_no_data_is_not_applicable, test_with_data_computes,
               test_backward_compat_and_idempotency, test_coverage,
               test_coverage_block_status, test_physical_tristate, test_described_only,
               test_adapters, test_generator_validation):
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
