"""НЕЗАВИСИМЫЙ АУДИТ QA/QC: сверка оцифрованных проверок с ЧЕКЛИСТОМ ГПН.

Написан верификатором (task-6). Ничего в чужом коде не меняет.

Проверяется:
  1) наличие и полнота `ontology/qa_checks/*.csv` и `domain/qaqc/checks_table.csv`:
     сколько проверок по каждому блоку (05, 06, 07, 08, 09, 10, 13) добавлено;
  2) КАЖДЫЙ ID из этих CSV существует ли в `QAQC/QA_QC_чеклист.xlsx` (иначе проверка
     выдумана, а не оцифрована);
  3) числовые пороги/критерии: числа из колонки «Критерий прохождения» чеклиста
     против чисел в колонках «Порог»/«Критерий» CSV — расхождения перечисляются;
  4) обязательный набор QC_* из задания (QC_GS_001…006, QC_LITH_001…011,
     QC_POR_001…010, QC_PERM_001…008, QC_SAT_001…012, QC_RES_001…010,
     QC_PHYS_001/002/003/005/006) — что реально есть, а что нет;
  5) `runs/<id>/qaqc_coverage.json` — все 6065 пунктов чеклиста разложены по
     статусам; у `not_applicable`/`unknown` есть ПРИЧИНА; `implemented` подтверждён
     наличием проверки в пакете.

Запуск:  python -X utf8 tests/test_verify_qaqc_checklist.py [--json]
Код возврата: 1 — расхождения (отсутствующие/выдуманные/необоснованные проверки).
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

XLSX = ROOT.parent / "QAQC" / "QA_QC_чеклист.xlsx"
ONT_DIR = ROOT / "ontology" / "qa_checks"
PKG_CSV = ROOT / "domain" / "qaqc" / "checks_table.csv"

# task-18/A: dry-run пишет в СВОЙ каталог (`runs.dry_suffix`, умолчание `_dry`),
# а `runs/run_<поле>/` остаётся от последнего execute. Читаем ОБА и различаем отчёт
# по полю `execute` (когда есть), иначе по `qaqc.physical is None` и по суффиксу пути.
_CACHE: dict = {}


def _runs_paths() -> dict:
    """(dry_dir, exec_dir, dry_suffix) из ДАННЫХ `runs.*`/`project.default_field`."""
    if _CACHE:
        return _CACHE
    suffix = "_dry"
    field = "Герасимовское"
    root = ROOT / "runs"
    try:
        from core.config import load_config
        cfg = load_config()
        suffix = str(cfg.get("runs.dry_suffix", "_dry") or "_dry")
        field = str(cfg.get("project.default_field", field) or field)
        root = Path(str(cfg.path("runs.root", "runs")))
    except Exception:                              # noqa: BLE001
        pass
    _CACHE.update({"dry": root / f"run_{field}{suffix}", "exec": root / f"run_{field}",
                   "suffix": suffix})
    return _CACHE


def _is_dry(report: dict, path: Path) -> bool:
    """Отчёт dry-run? Приоритет: явное поле `execute` → `qaqc.physical is None` → суффикс."""
    ex = report.get("execute")
    if isinstance(ex, bool):
        return not ex
    if (report.get("qaqc") or {}).get("physical") is None:
        return True
    return path.parent.name.endswith(_runs_paths()["suffix"])


def _pick_coverage() -> tuple[Path, str]:
    """Файл покрытия: предпочитаем каталог dry-run (артефакт каждого dry-run)."""
    dry = _runs_paths()["dry"] / "qaqc_coverage.json"
    ex = _runs_paths()["exec"] / "qaqc_coverage.json"
    if dry.is_file():
        return dry, "dry-run"
    return ex, "execute"


COVERAGE, COVERAGE_KIND = _pick_coverage()
RUN_DIR = _runs_paths()["exec"]

TARGET_IDS = {
    "05": [f"QC_GS_{i:03d}" for i in range(1, 7)],
    "06": [f"QC_LITH_{i:03d}" for i in range(1, 12)],
    "07": [f"QC_POR_{i:03d}" for i in range(1, 11)],
    "08": [f"QC_PERM_{i:03d}" for i in range(1, 9)],
    "09": [f"QC_SAT_{i:03d}" for i in range(1, 13)],
    "10": [f"QC_RES_{i:03d}" for i in range(1, 11)],
    "13": ["QC_PHYS_001", "QC_PHYS_002", "QC_PHYS_003", "QC_PHYS_005", "QC_PHYS_006"],
}
CSV_COLS = ["ID", "Блок", "Название", "Способ выполнения", "Порог", "Входные ключи",
            "Значимость", "Формула", "Критерий", "Используется критерием критика"]

FAIL: list[str] = []
WARN: list[str] = []
INFO: list[str] = []


def fail(msg: str) -> None:
    FAIL.append(msg)
    print(f"[FAIL] {msg}")


def warn(msg: str) -> None:
    WARN.append(msg)
    print(f"[WARN] {msg}")


_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")


def nums(text: str) -> list[float]:
    out = []
    for m in _NUM.findall(text or ""):
        try:
            out.append(float(m.replace(",", ".")))
        except ValueError:
            continue
    return out


def load_json_stable(path: Path, attempts: int = 3) -> object:
    """JSON с защитой от гонки записи (mtime/размер не изменились между чтением и разбором)."""
    import time
    last: object = None
    for _ in range(attempts):
        try:
            before = path.stat()
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            after = path.stat()
            if (before.st_mtime_ns, before.st_size) == (after.st_mtime_ns, after.st_size):
                return data
            last = data
        except Exception as exc:                   # noqa: BLE001
            last = exc
        time.sleep(0.3)
    if isinstance(last, Exception):
        raise last
    return last


def read_csv_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = list(csv.DictReader(text.splitlines(), delimiter=";"))
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in rows]


def load_checklist() -> dict[str, dict]:
    try:
        import openpyxl
    except ImportError:
        warn("openpyxl недоступен — чеклист xlsx не прочитан")
        return {}
    if not XLSX.is_file():
        warn(f"чеклист не найден: {XLSX}")
        return {}
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(min_row=4, values_only=True))
    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    idx = {name: i for i, name in enumerate(header)}
    out: dict[str, dict] = {}
    for r in rows[1:]:
        if not r or r[0] is None:
            continue
        cid = str(r[idx.get("ID проверки / пункта", 1)] or "").strip()
        if not cid:
            continue
        rec = {
            "num": r[0],
            "block": str(r[idx.get("Обязательная область ГПН / блок", 6)] or "").strip(),
            "check": str(r[idx.get("Проверка", 7)] or "").strip(),
            "criterion": str(r[idx.get("Критерий прохождения", 11)] or "").strip(),
            "formula": str(r[idx.get("Метод / формула", 10)] or "").strip(),
            "state": str(r[idx.get("Состояние", 19)] or "").strip(),
        }
        out.setdefault(cid, rec)          # первый дубль
    return out


def main() -> int:
    print(f"чеклист: {XLSX}")
    checklist = load_checklist()
    print(f"строк чеклиста с ID: {len(checklist)}")

    # --- 1/2: проверки из CSV против чеклиста --------------------------------
    csv_files = sorted(ONT_DIR.glob("*.csv")) if ONT_DIR.is_dir() else []
    print(f"\n=== 1. ФАЙЛЫ ontology/qa_checks/*.csv: {len(csv_files)} ===")
    by_block: dict[str, int] = {}
    invented: list[str] = []
    all_rows: list[dict] = []
    for f in csv_files:
        if f.name in ("model_keys.csv", "checklist_index.csv", "block_legend.csv"):
            INFO.append(f"{f.name} — служебный индекс/легенда, не проверки")
            continue
        rows = read_csv_rows(f)
        ids = [r.get("ID", "") for r in rows if r.get("ID")]
        print(f"  {f.name}: {len(ids)} проверок")
        all_rows += [r for r in rows if r.get("ID")]
        for r in rows:
            cid = r.get("ID", "")
            if not cid:
                continue
            blk = str(r.get("Блок", ""))[:2]
            by_block[blk] = by_block.get(blk, 0) + 1
            if checklist and cid not in checklist:
                invented.append(cid)
    print(f"по блокам (из CSV): {dict(sorted(by_block.items()))}")

    pkg_rows = read_csv_rows(PKG_CSV)
    pkg_ids = {r.get("ID", "") for r in pkg_rows if r.get("ID")}
    print(f"пакет domain/qaqc/checks_table.csv: {len(pkg_rows)} проверок")

    if invented:
        fail(f"{len(invented)} ID из ontology/qa_checks/*.csv отсутствуют в чеклисте ГПН: "
             f"{sorted(set(invented))[:12]}")
    else:
        print("все ID из ontology/qa_checks найдены в чеклисте ГПН")

    new_in_pkg = [r.get("ID") for r in all_rows if r.get("ID") and r.get("ID") not in pkg_ids]
    if new_in_pkg:
        warn(f"{len(new_in_pkg)} проверок оцифрованы в ontology/qa_checks, но НЕ попали в "
             f"пакет domain/qaqc/checks_table.csv: {new_in_pkg[:12]}")
    else:
        print("все оцифрованные проверки присутствуют в пакете domain/qaqc")

    # --- 1b: ИСПОЛНЯЕМЫЙ реестр CHECKS против CSV ----------------------------
    print("\n=== 1b. ИСПОЛНЯЕМЫЙ ПАКЕТ: CHECKS vs checks_table.csv ===")
    try:
        from domain import qaqc as _qaqc
        checks = getattr(_qaqc, "CHECKS", {}) or {}
    except Exception as exc:                      # noqa: BLE001
        warn(f"пакет domain/qaqc не импортируется: {exc}")
        checks = {}
    if checks:
        rows_by_id = {r.get("ID", ""): r for r in pkg_rows if r.get("ID")}
        not_exec, unexplained = [], []
        for cid, r in rows_by_id.items():
            if cid in checks:
                continue
            how = str(r.get("Способ выполнения", "")).strip().lower()
            if how in ("unknown", ""):
                not_exec.append(cid)
            else:
                unexplained.append(f"{cid}({how[:24]})")
        print(f"строк CSV: {len(rows_by_id)}; исполняемых CHECKS: {len(checks)}; "
              f"не исполняются со способом «unknown»: {len(not_exec)}")
        if unexplained:
            fail(f"{len(unexplained)} оцифрованных проверок НЕ попали в исполняемый "
                 f"CHECKS при конкретном способе выполнения (выпали молча): "
                 f"{unexplained[:10]}")
        extra = [k for k in checks if k not in rows_by_id]
        if extra:
            warn(f"{len(extra)} проверок есть в CHECKS, но нет в checks_table.csv: "
                 f"{extra[:8]}")
        qc_csv = {r.get("ID", "") for r in all_rows if r.get("ID", "").startswith("QC_")}
        qc_exec = {k for k in checks if k.startswith("QC_")}
        print(f"QC_*: оцифровано {len(qc_csv)}, исполняемых {len(qc_exec)}, "
              f"unknown {len(qc_csv - qc_exec)}: {sorted(qc_csv - qc_exec)}")

    # --- 3: пороги ------------------------------------------------------------
    print("\n=== 3. СВЕРКА ЧИСЛОВЫХ ПОРОГОВ С ЧЕКЛИСТОМ (по ID) ===")
    compared = mism = 0
    for r in all_rows:
        cid = r.get("ID", "")
        if cid not in checklist:
            continue
        crit_x = checklist[cid]["criterion"]
        crit_c = f"{r.get('Порог', '')} ; {r.get('Критерий', '')}"
        nx, nc = nums(crit_x), nums(crit_c)
        if not nx or not nc:
            continue
        compared += 1
        set_x = sorted(set(nx))
        missing = [v for v in set_x if v not in nc]
        if missing:
            mism += 1
            print(f"       [x] {cid}: в чеклисте числа {set_x}, в CSV {sorted(set(nc))} "
                  f"-> нет {missing}")
            print(f"           чеклист: «{crit_x[:100]}»")
            print(f"           CSV:     «{crit_c[:100]}»")
    print(f"сравнено проверок с числами: {compared}; расхождений: {mism}")
    if compared == 0:
        warn("не удалось сравнить ни одной проверки по числам (проверить формат CSV)")

    # --- 4: обязательный набор -------------------------------------------------
    print("\n=== 4. ОБЯЗАТЕЛЬНЫЙ НАБОР QC_* ИЗ ЗАДАНИЯ ===")
    have_pkg = pkg_ids
    have_ont = {r.get("ID", "") for r in all_rows}
    for blk, ids in TARGET_IDS.items():
        rows = [(i, i in have_ont, i in have_pkg,
                 i in checklist) for i in ids]
        missing_ont = [i for i, o, _p, _c in rows if not o]
        missing_pkg = [i for i, _o, p, _c in rows if not p]
        not_in_chk = [i for i, _o, _p, c in rows if not c]
        state = "OK" if not missing_pkg else "НЕ ПОЛНОСТЬЮ"
        print(f"блок {blk}: {len(ids) - len(missing_ont)}/{len(ids)} оцифровано, "
              f"{len(ids) - len(missing_pkg)}/{len(ids)} в пакете -> {state}")
        if missing_ont:
            warn(f"блок {blk}: не оцифрованы {missing_ont}")
        if missing_pkg:
            fail(f"блок {blk}: оцифрованы, но НЕ в пакете: {missing_pkg}")
        if not_in_chk:
            warn(f"блок {blk}: нет в чеклисте ГПН: {not_in_chk}")

    # --- 5: qaqc_coverage.json -------------------------------------------------
    print("\n=== 5. qaqc_coverage.json ===")
    if not COVERAGE.is_file():
        fail(f"нет {COVERAGE.relative_to(ROOT)} — покрытие чеклиста не отчитано")
    else:
        data = load_json_stable(COVERAGE)
        if not isinstance(data, dict):
            warn(f"неожиданная схема qaqc_coverage.json: {type(data).__name__}")
            data = {}
        summary = data.get("summary") or {}
        blocks = data.get("blocks") or []
        meta = data.get("meta") or {}
        print(f"meta.source={meta.get('source')} meta.checklist={meta.get('checklist')}")
        print(f"summary: {json.dumps(summary, ensure_ascii=False)[:400]}")

        total_pts = int(summary.get("checklist_items") or 0)
        # classify: dry-run или execute — «passed без данных» проверяем ТОЛЬКО на dry-run
        _cov_report = COVERAGE.parent / "report.json"
        cov_dry = COVERAGE_KIND == "dry-run"
        if _cov_report.is_file():
            try:
                cov_dry = _is_dry(load_json_stable(_cov_report), _cov_report)
            except Exception:                      # noqa: BLE001
                pass
        print(f"[info] покрытие: {COVERAGE.relative_to(ROOT)} "
              f"({'dry-run' if cov_dry else 'execute'}) — артефакт "
              f"{'без данных модели' if cov_dry else 'реального прогона (passed допустим)'}")
        if total_pts != 6065:
            fail(f"summary.checklist_items={total_pts}, чеклист ГПН = 6065")
        else:
            print("summary.checklist_items = 6065 — охват чеклиста полный")

        if not blocks:
            warn("в qaqc_coverage.json нет разбивки по блокам")
        blocks_sum = sum(int(b.get("checklist_items") or 0) for b in blocks)
        outside = int(meta.get("items_outside_blocks") or 0)
        detail = meta.get("items_outside_blocks_detail") or {}
        if blocks and blocks_sum + outside != total_pts:
            fail(f"сумма пунктов по блокам ({blocks_sum}) + вне блоков ({outside}) "
                 f"!= checklist_items ({total_pts})")
        elif outside:
            items_out = detail.get("items") or []
            bad = [x for x in items_out
                   if not (isinstance(x, (list, tuple)) and len(x) >= 3 and x[1] and x[2])]
            if not items_out:
                warn(f"{outside} пунктов чеклиста НЕ отнесены ни к одному блоку и в отчёте "
                     f"НЕТ построчного статуса (meta.items_outside_blocks_detail отсутствует)")
            elif int(detail.get("total") or 0) != outside or len(items_out) != outside:
                fail(f"items_outside_blocks_detail: total={detail.get('total')}, "
                     f"записей={len(items_out)}, а meta.items_outside_blocks={outside}")
            elif bad:
                fail(f"в items_outside_blocks_detail {len(bad)} записей без статуса/причины: "
                     f"{bad[:3]}")
            else:
                st = {str(x[1]).lower() for x in items_out}
                print(f"[info] построчный статус вне-блочных пунктов есть: {len(items_out)} "
                      f"записей, статусы {sorted(st)}, причина "
                      f"{detail.get('reason_code')}: «{str(detail.get('reason'))[:70]}»")
                if st - {"unknown", "not_applicable"}:
                    fail(f"вне-блочные пункты помечены не как unknown/not_applicable: "
                         f"{sorted(st)}")
        if meta.get("warnings"):
            warn(f"meta.warnings: {meta['warnings']}")

        # --- раскладка ПУНКТОВ чеклиста (summary.points) ------------------------
        pts = summary.get("points") or {}
        if pts:
            t = int(pts.get("total") or 0)
            by = pts.get("by_status") or {}
            s = sum(int(v) for v in by.values())
            print(f"summary.points: total={t}, by_status={by}")
            if t != 6065:
                fail(f"summary.points.total={t} != 6065")
            if s != t:
                fail(f"сумма by_status ({s}) != summary.points.total ({t})")
            if by.get("passed") or by.get("failed"):
                fail(f"в раскладке пунктов есть passed/failed без данных: {by}")
        else:
            warn("в qaqc_coverage.json нет summary.points — раскладка ПУНКТОВ чеклиста "
                 "не отчитана (есть только раскладка проверок)")

        # --- DESCRIBED_ONLY: описано, но не исполняется -------------------------
        described = set(((load_json_stable(COVERAGE) or {}).get("consistency")
                         or {}).get("described_only_ids") or []) or {
            "QC_LITH_005", "QC_LITH_006", "QC_LITH_008", "QC_LITH_010",
            "QC_PERM_006", "QC_SAT_007", "QC_SAT_008"}
        if checks:
            in_checks = sorted(i for i in described if i in checks)
            if in_checks:
                fail(f"DESCRIBED_ONLY-проверки попали в исполняемый CHECKS: {in_checks} "
                     f"(качественный критерий нельзя считать passed)")
            else:
                print(f"[info] DESCRIBED_ONLY ({len(described)}) не входят в CHECKS — "
                      f"корректно (unknown, не passed)")

        impl_sum = sum(int(b.get("implemented") or 0) for b in blocks)
        if blocks and impl_sum != int(summary.get("implemented") or 0):
            fail(f"сумма implemented по блокам ({impl_sum}) != summary.implemented "
                 f"({summary.get('implemented')})")

        # проверки пакета по блокам (для обоснованности implemented)
        pkg_by_block: dict[str, set[str]] = {}
        for r in pkg_rows:
            cid = r.get("ID", "")
            blk = str(r.get("Блок", ""))[:2]
            if cid:
                pkg_by_block.setdefault(blk, set()).add(cid)

        bad_reasons: list[str] = []
        unbacked: list[str] = []
        status_wo_reason: list[str] = []
        wrong_status: list[str] = []
        for b in blocks:
            blk = str(b.get("block") or "")
            states = b.get("states") or {}
            na = int(states.get("not_applicable") or 0)
            unk = int(states.get("unknown") or 0)
            na_reasons = b.get("not_applicable_reasons") or []
            unk_reasons = b.get("unknown_reasons") or []
            impl_ids = b.get("implemented_ids") or []
            impl = int(b.get("implemented") or 0)
            if na and len(na_reasons) < na:
                bad_reasons.append(f"{blk}: not_applicable={na}, причин={len(na_reasons)}")
            if unk and len(unk_reasons) < unk:
                bad_reasons.append(f"{blk}: unknown={unk}, причин={len(unk_reasons)}")
            if states.get("passed") and cov_dry:
                status_wo_reason.append(f"{blk}: passed={states['passed']} (dry-run без данных!)")
            # статус блока должен соответствовать числу оцифрованных проверок
            if impl > 0 and str(b.get("status")) == "not_implemented":
                wrong_status.append(f"{blk}: implemented={impl}, но status='not_implemented', "
                                    f"reason=«{str(b.get('reason') or '')[:50]}»")
            pkg_here = pkg_by_block.get(blk, set())
            # implemented_id должен существовать либо в пакете, либо в чеклисте
            unbacked += [f"{blk}:{i}" for i in impl_ids
                         if i not in pkg_here and i not in checklist]
            bp = b.get("points") or {}
            if bp:
                bt = int(bp.get("total") or 0)
                bs = (int(bp.get("implemented") or 0) + int(bp.get("not_applicable") or 0)
                      + int(bp.get("unknown") or 0))
                if bt != int(b.get("checklist_items") or 0):
                    fail(f"блок {blk}: points.total={bt} != checklist_items="
                         f"{b.get('checklist_items')}")
                if bs != bt:
                    fail(f"блок {blk}: implemented+not_applicable+unknown={bs} != points.total={bt}")
                if str(bp.get("status") or "") != "implemented" and not bp.get("status_note"):
                    warn(f"блок {blk}: у статуса пунктов нет status_note (обоснования)")
            print(f"  блок {blk}: пунктов={b.get('checklist_items')} "
                  f"реализовано={b.get('implemented')} не_реализовано={b.get('not_implemented')} "
                  f"статус={b.get('status')} проверок_в_пакете={len(pkg_here)} "
                  f"points={bp.get('implemented'), bp.get('not_applicable'), bp.get('unknown')} "
                  f"states={states} reason=«{str(b.get('reason') or '')[:60]}»")
        if bad_reasons:
            fail(f"пункты not_applicable/unknown БЕЗ причины (правило 6): {bad_reasons[:6]}")
        if status_wo_reason:
            fail(f"на dry-run есть passed-пункты без данных: {status_wo_reason[:6]}")
        if wrong_status:
            fail(f"статус/причина блока противоречат данным (есть оцифрованные проверки, "
                 f"а блок помечен not_implemented): {wrong_status[:6]}")
        if unbacked:
            warn(f"{len(unbacked)} implemented-id не подтверждены ни пакетом, ни чеклистом: "
                 f"{unbacked[:8]}")
        impl_total = int(summary.get("implemented") or 0)
        pkg_total = len(pkg_ids)
        print(f"реализовано (по отчёту) {impl_total}; проверок в пакете domain/qaqc {pkg_total}")
        if impl_total > pkg_total + len(checklist) * 0:
            warn(f"реализованных пунктов ({impl_total}) больше, чем проверок в пакете "
                 f"({pkg_total}) — проверить, что это действительно оцифрованные проверки")
        na = int(summary.get("checks_not_applicable") or 0)
        unk = int(summary.get("checks_unknown") or 0)
        p = int(summary.get("checks_passed") or 0)
        f_ = int(summary.get("checks_failed") or 0)
        print(f"прогон проверок: passed={p} failed={f_} not_applicable={na} unknown={unk}")
        if p and not (na or f_):
            warn("passed без применимых проверок — уточнить семантику")
        if f_ > 0 and int(summary.get("implemented") or 0) and p == 0:
            warn(f"failed={f_} при passed=0 — возможен штраф за отсутствие данных")

    print("\n=== ИТОГ (qaqc checklist) ===")
    print(f"FAIL: {len(FAIL)} | WARN: {len(WARN)} | INFO: {len(INFO)}")
    if "--json" in sys.argv:
        print(json.dumps({"fail": FAIL, "warn": WARN, "by_block": by_block,
                          "csv_files": [f.name for f in csv_files]},
                         ensure_ascii=False, indent=2))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
