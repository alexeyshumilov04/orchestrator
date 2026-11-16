"""НЕЗАВИСИМАЯ ПРИЁМОЧНАЯ ЦЕПОЧКА: тесты → preflight → dry-run → инварианты отчёта.

Написан верификатором (task-6). Ничего в чужом коде не меняет; запускает команды
в подпроцессах и проверяет ИНВАРИАНТЫ (базовая линия обновлена Lead-ом 2026-10-09):

  * tests/test_v5.py            -> 32/32
  * tests/test_agents.py        -> 223/223
  * tests/test_base_agent.py    -> 37/37
  * tests/test_no_domain_in_code.py -> зелёный (0 провалов)
  * тесты участников (если появились): test_contracts, test_qaqc_checks,
    test_structural_agent, test_facies_agent, test_petro_agent
  * только через pytest (-m pytest -q): нет скрытых ошибок импорта
  * main.py preflight           -> "preflight: OK"
  * main.py run --field Герасимовское (dry-run):
        steps.error == 0
        render_warnings == []
        steps.pending_template == 0
        steps.done == steps.total - skipped_by_policy
        (рост steps.total сам по себе НЕ дефект)
  * отчёт верхнего уровня: ключ `qaqc` есть, в нём total/passed/failed/not_applicable
    и kq/kc; `runs/<id>/qaqc_coverage.json` существует
  * реальный `--execute`: НЕ запускается этим скриптом (нужна лицензия ~13 мин);
    при `--execute` он только фиксирует, доступна ли лицензия (preflight).

Запуск:  python -X utf8 tests/test_verify_chain.py [--skip-heavy] [--json]
Код возврата: 1 при любом нарушении инварианта.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = r"C:\ProgramData\anaconda3\python.exe"
RUN_DIR = ROOT / "runs" / "run_Герасимовское"


def dry_dir() -> Path:
    """Каталог dry-run: `runs/run_<поле><runs.dry_suffix>` (task-18/A, умолчание `_dry`)."""
    suffix = "_dry"
    try:
        from core.config import load_config
        suffix = str(load_config().get("runs.dry_suffix", "_dry") or "_dry")
    except Exception:                              # noqa: BLE001
        pass
    return RUN_DIR.parent / f"{RUN_DIR.name}{suffix}"


ART_DIR = RUN_DIR          # каталог, из которого читаем артефакты (уточняется в main)

EXPECTED = {
    "tests/test_v5.py": 32,
    "tests/test_agents.py": 223,
    "tests/test_base_agent.py": 39,      # было 37; Lead расширил контракт facies-агента
}
PARTICIPANT_TESTS = [
    "tests/test_contracts.py",
    "tests/test_qaqc_checks.py",
    "tests/test_structural_agent.py",
    "tests/test_facies_agent.py",
    "tests/test_petro_agent.py",
]

FAIL: list[str] = []
WARN: list[str] = []


def fail(msg: str) -> None:
    FAIL.append(msg)
    print(f"[FAIL] {msg}")


def warn(msg: str) -> None:
    WARN.append(msg)
    print(f"[WARN] {msg}")


def run(args: list[str], timeout: int = 1800) -> tuple[int, str]:
    p = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


_RESULT = re.compile(r"(?:пройдено|всего):\s*(\d+)\s*\|\s*провалено:\s*(\d+)")


def parse_counts(out: str) -> tuple[int, int] | None:
    m = None
    for m in _RESULT.finditer(out):
        pass
    return (int(m.group(1)), int(m.group(2))) if m else None


def py_test(rel: str) -> tuple[int, int] | None:
    path = ROOT / rel
    if not path.is_file():
        return None
    code, out = run([PY, "-X", "utf8", rel])
    counts = parse_counts(out)
    tail = " | ".join(out.strip().splitlines()[-3:])
    if counts is None:
        fail(f"{rel}: не удалось разобрать итог (exit={code}); хвост: {tail[:200]}")
        return None
    passed, failed = counts
    print(f"  {rel}: пройдено {passed}, провалено {failed} (exit={code})")
    if failed:
        fail(f"{rel}: {failed} проваленных проверок")
    return passed, failed


def find_saved_execute_report() -> Path | None:
    """Сохранённый отчёт РЕАЛЬНОГО прогона (F-17), а не dry-run.

    Каталог `runs/<id>/` пересобирается следующей попыткой, поэтому копии кладут в
    `report_execute*.json` или в снапшоты `runs/artifacts/execute_*/report_execute.json`.
    ВАЖНО: туда попадают и dry-run'ы (у них `qaqc.physical is None`), поэтому выбираем
    отчёт, где метрика физичности РЕАЛЬНАЯ (не None); при равенстве — самый свежий.
    """
    cands = [*RUN_DIR.glob("report_execute*.json"),
             *RUN_DIR.parent.glob("report_execute*.json"),
             *RUN_DIR.parent.rglob("report_execute*.json")]
    best: tuple[tuple[int, float], Path] | None = None
    for p in {c.resolve() for c in cands if c.is_file()}:
        try:
            data = load_json_stable(p, attempts=2)
            q = (data or {}).get("qaqc") or {} if isinstance(data, dict) else {}
            real = 1 if q.get("physical") is not None else 0
            branches = (((data or {}).get("project") or {}).get("ensemble") or {}) \
                if isinstance(data, dict) else {}
            scored = 1 if branches.get("scored") else 0
            key = (real + scored, p.stat().st_mtime)
        except Exception:                              # noqa: BLE001
            continue
        if best is None or key > best[0]:
            best = (key, p)
    return best[1] if best else None


def load_json_stable(path: Path, attempts: int = 3) -> object:
    """Прочитать JSON устойчиво к гонке записи (файл мог переписываться в момент чтения).

    Если mtime/размер изменились между чтением и разбором — повторяем. Это защита от
    полу-записанного артефакта (та же гонка, что ловил foundation 19:2x).
    """
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


def _lock_path() -> Path:
    """Путь файловой блокировки прогонов (ДАННЫЕ: `runs.lock_file`), с fallback."""
    try:
        from core.config import load_config
        return Path(str(load_config().path("runs.lock_file", "runs/.run.lock")))
    except Exception:                              # noqa: BLE001
        return ROOT / "runs" / ".run.lock"


def safety_gate(*, from_art: bool, lock_override: str | None = None,
                confirm: bool = False) -> bool:
    """Проверки ПЕРЕД реальным прогоном: блокировка, процессы тНава, состояние моделей.

    Возвращает True, если можно запускать. Реальный `--execute` разрешаем только с
    явным `--confirm` и при отсутствии ЖИВОЙ блокировки `runs/.run.lock` — иначе
    два прогона при одной сессии тНава портят общие артефакты, а `_build_ensemble`
    (`shutil.rmtree(models/<vid>)`) может уничтожить модели чужого прогона.
    """
    if from_art:
        return True
    ok = True
    lock = Path(lock_override) if lock_override else _lock_path()
    if lock.is_file():
        try:
            payload = lock.read_text(encoding="utf-8", errors="replace")[:200]
        except OSError:
            payload = "?"
        fail(f"найден файл блокировки {lock} ({payload}) — похоже, прогон уже идёт. "
             f"Реальный --execute НЕ запускаю (ЖИВУЮ блокировку снимать нельзя; "
             f"устаревшую снимает main.py при следующем прогоне)")
        ok = False
    model_dirs = sorted((ROOT / "models").glob("S0*"))
    filled = [d.name for d in model_dirs if any(d.rglob("*.snp"))]
    print(f"  модели ветвей: {len(model_dirs)} каталогов, с проектом .snp: {filled or '—'}")
    if model_dirs and not filled:
        warn("все каталоги models/S0* сейчас без .snp — предыдущий деградированный прогон "
             "мог их очистить; реальный прогон перезапишет их снова")
    if not confirm:
        fail("реальный --execute требует явного `--confirm` (защита от случайного запуска, "
             "который делит models/ и одну сессию тНава с другими прогонами)")
        ok = False
    return ok


def main() -> int:
    global EXECUTE, ART_DIR
    skip_heavy = "--skip-heavy" in sys.argv
    from_art = "--from-artifacts" in sys.argv      # аудит артефактов чужого --execute
    EXECUTE = ("--execute" in sys.argv) or from_art
    # task-18/A: dry-run пишет в СВОЙ каталог; артефакты читаем оттуда, execute — из общего
    ART_DIR = RUN_DIR if EXECUTE else dry_dir()
    print(f"  каталог артефактов: {ART_DIR.relative_to(ROOT)} "
          f"({'execute' if EXECUTE else 'dry-run'})")
    if EXECUTE:
        print(f"!!! РЕЖИМ --execute{' (аудит артефактов, прогон НЕ запускаю)' if from_art else ''}"
              f": реальный прогон тНава (нужна лицензия, ~13 мин на ветвь)")
        lock_override = None
        for i, a in enumerate(sys.argv):
            if a == "--lock-file" and i + 1 < len(sys.argv):
                lock_override = sys.argv[i + 1]
        if not from_art:
            print(f"  каталог прогона: {RUN_DIR} (общий! ветки пишутся в models/)")
            if not safety_gate(from_art=from_art, lock_override=lock_override,
                               confirm="--confirm" in sys.argv):
                print("\n=== ИТОГ (chain) ===\nFAIL: запуск отклонён по безопасности "
                      "(блокировка/нет --confirm)")
                return 2
        stuck = subprocess.run(["tasklist", "/FI", "IMAGENAME eq tNavigator*"],
                               capture_output=True, text=True, errors="replace")
        if "tNavigator" in (stuck.stdout or ""):
            warn("в системе есть процессы tNavigator — возможен «залипший» API "
                 "(см. открытый вопрос 5 PLAN). Вывод tasklist:\n" + stuck.stdout[:800])

    print("=== 1. ОБЯЗАТЕЛЬНЫЕ ТЕСТЫ (python) ===")
    for rel, exp in EXPECTED.items():
        counts = py_test(rel)
        if counts and counts[0] < exp:
            fail(f"{rel}: пройдено {counts[0]} < {exp} — тесты ПОТЕРЯНЫ против базовой линии")
        elif counts and counts[0] > exp:
            warn(f"{rel}: пройдено {counts[0]} > {exp} (ожидание базы) — тесты добавлены, "
                 f"обновить базовую линию")

    print("\n=== 1b. ТЕСТ АУДИТА ХАРДКОДА ===")
    code, out = run([PY, "-X", "utf8", "tests/test_no_domain_in_code.py"])
    counts = parse_counts(out)
    print(f"  exit={code}, итог: {counts}; долг: "
          f"{'известный долг есть' if 'известный долг' in out else 'долга нет'}")
    if counts and counts[1]:
        fail("test_no_domain_in_code: есть провалы")
    if code != 0:
        fail("test_no_domain_in_code: ненулевой код возврата")

    print("\n=== 1c. ТЕСТЫ УЧАСТНИКОВ ===")
    present = 0
    for rel in PARTICIPANT_TESTS:
        if not (ROOT / rel).is_file():
            fail(f"нет теста участника {rel} (обязателен по заданию этапа)")
            continue
        present += 1
        py_test(rel)
    print(f"  найдено тестов участников: {present}/{len(PARTICIPANT_TESTS)}")

    print("\n=== 1d. ПЕРЕСЧЁТ ЧЕРЕЗ pytest (скрытые ошибки импорта) ===")
    if skip_heavy:
        warn("pytest пропущен (--skip-heavy)")
    else:
        code, out = run([PY, "-m", "pytest", "-q", "tests/test_v5.py", "tests/test_agents.py",
                         "--no-header", "-p", "no:cacheprovider"], timeout=1800)
        tail = "\n".join(out.strip().splitlines()[-12:])
        print(tail)
        m = re.search(r"(\d+) passed", out)
        if not m:
            warn("pytest не сообщил 'N passed' — смотреть вывод выше")
        else:
            print(f"  pytest: {m.group(1)} passed, errors="
                  f"{'есть' if ('error' in out.lower() and 'errors' in out.lower()) else 'нет'}")

    print("\n=== 2. PREFLIGHT ===")
    code, out = run([PY, "-X", "utf8", "main.py", "preflight"], timeout=300)
    ok = "preflight: OK" in out
    print(f"  exit={code}; строка 'preflight: OK': {ok}")
    if not ok:
        fail("main.py preflight не вернул 'preflight: OK'")

    print("\n=== 3. DRY-RUN + ИНВАРИАНТЫ ОТЧЁТА ===")
    if from_art:
        print("  прогон не запускаю (--from-artifacts): читаю артефакты существующего прогона")
    elif skip_heavy:
        warn("dry-run пропущен (--skip-heavy) — проверяются артефакты прошлого прогона")
    else:
        args = [PY, "-X", "utf8", "main.py", "run", "--field", "Герасимовское"]
        if EXECUTE:
            args.append("--execute")
        code, out = run(args, timeout=7200 if EXECUTE else 1800)
        print("  " + "\n  ".join(out.strip().splitlines()[-8:]))
        if code != 0:
            fail(f"{'--execute' if EXECUTE else 'dry-run'} завершился с кодом {code}")
        # сырой вывод — только хвост, в свою зону (docs/VERIFY_*), не в runs/
        tail_txt = "\n".join(out.strip().splitlines()[-200:])
        (ROOT / "docs" / "VERIFY_run_stdout.md").write_text(
            f"# Сырой вывод {'--execute' if EXECUTE else 'dry-run'} "
            f"(хвост, {len(out.splitlines())} строк всего)\n\n````\n{tail_txt}\n````\n",
            encoding="utf-8")

    report_p = ART_DIR / "report.json"
    saved = find_saved_execute_report()
    if from_art and saved is not None:
        report_p = saved
        print(f"  читаю СОХРАНЁННЫЙ отчёт реального прогона: "
              f"{saved.relative_to(ROOT)}")
    if not report_p.is_file():
        fail("нет runs/run_Герасимовское/report.json")
        return 1
    report = load_json_stable(report_p)  # noqa: E501
    steps = report.get("steps") or {}
    counts = steps.get("counts") or {}
    skipped = int(counts.get("skipped_by_policy") or 0)
    total = int(steps.get("total") or 0)
    done = int(steps.get("done") or 0)
    err = int(steps.get("error") or 0)
    pend = int(steps.get("pending_template") or 0)
    warnings = report.get("render_warnings") or []
    print(f"  steps: total={total} done={done} error={err} "
          f"pending_template={pend} skipped_by_policy={skipped}")
    print(f"  render_warnings={warnings[:5]}")
    if err != 0:
        fail(f"steps.error={err} (инвариант: 0)")
    if pend != 0:
        fail(f"steps.pending_template={pend} (инвариант: 0 — рост шагов только с шаблоном)")
    if warnings:
        fail(f"render_warnings непуст: {warnings[:5]} (инвариант: [])")
    if done != total - skipped:
        fail(f"steps.done={done} != total-skipped={total - skipped}")
    if skipped > 1:
        warn(f"skipped_by_policy={skipped} (на базовой линии был ровно 1 — шаг вреза)")

    print("\n=== 4. QA/QC В ОТЧЁТЕ ВЕРХНЕГО УРОВНЯ ===")
    q = report.get("qaqc")
    if not isinstance(q, dict):
        fail("report.json: ключа `qaqc` нет или он не словарь (E2 не выполнен)")
    else:
        need = {"total", "passed", "failed", "not_applicable"}
        absent = sorted(need - set(q))
        if absent:
            fail(f"qaqc: нет полей {absent}")
        print(f"  qaqc: total={q.get('total')} passed={q.get('passed')} "
              f"failed={q.get('failed')} not_applicable={q.get('not_applicable')} "
              f"kq={q.get('kq')} kc={q.get('kc')} physical={q.get('physical')}")
        if q.get("kq") is None or q.get("kc") is None:
            print("  [note] kq/kc отсутствуют или None — на dry-run без модели это "
                  "допустимо, но должно быть явно (не подменяться нулём без пометки)")
        if q.get("failed") and int(q.get("failed") or 0) > 0:
            warn("qaqc.failed > 0 на dry-run — проверить, что это не «нет данных = провал»")
    cov = ART_DIR / "qaqc_coverage.json"
    if cov.is_file():
        cdata = load_json_stable(cov)
        n = None
        if isinstance(cdata, dict):
            summ = cdata.get("summary") or {}
            for k in ("checklist_items", "total", "points_total", "checklist_total"):
                if isinstance(summ.get(k), (int, float)):
                    n = int(summ[k])
                    break
            if n is None:
                for k in ("total", "points_total", "checklist_total"):
                    if isinstance(cdata.get(k), (int, float)):
                        n = int(cdata[k])
        print(f"  qaqc_coverage.json есть; заявленный охват: {n}")
        if n is not None and n != 6065:
            fail(f"qaqc_coverage.json: охват {n} != 6065 пунктов чеклиста")
    else:
        fail("нет runs/run_Герасимовское/qaqc_coverage.json (E4 не выполнен)")

    print("\n=== 5. МЕСТА QA/QC В АРТЕФАКТАХ ===")
    maps_dir = ART_DIR / "maps"
    pngs = sorted(maps_dir.glob("*.png")) if maps_dir.is_dir() else []
    print(f"  карт PNG в runs/<id>/maps/: {len(pngs)}: {[p.stem for p in pngs]}")
    if EXECUTE:
        try:
            import yaml
            cfg_raw = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
            expected_maps = [str(x) for x in ((cfg_raw.get("checks") or {}).get("map_files") or [])]
        except Exception:                              # noqa: BLE001
            expected_maps = []
        have = [m for m in expected_maps if (maps_dir / f"{m}.png").is_file()]
        miss = [m for m in expected_maps if not (maps_dir / f"{m}.png").is_file()]
        print(f"  ожидаемые карты (checks.map_files): {expected_maps}")
        print(f"  построено: {have}; НЕТ PNG: {miss}")
        if len(expected_maps) >= 8 and len(have) < 8:
            fail(f"E9: построено {len(have)} из {len(expected_maps)} ожидаемых карт "
                 f"(требование ≥8) — нет {miss}")
        # пустые экспорты: доля непустых ячеек в <map>.txt
        for m in expected_maps:
            txt = maps_dir / f"{m}.txt"
            if not txt.is_file():
                continue
            tot = nonblank = 0
            for line in txt.read_text(encoding="utf-8", errors="replace").splitlines()[4:]:
                for tok in line.split():
                    try:
                        v = float(tok)
                    except ValueError:
                        continue
                    tot += 1
                    if abs(v) < 1e6:
                        nonblank += 1
            share = 100 * nonblank / max(tot, 1)
            flag = "  <-- ПУСТОЙ ЭКСПОРТ" if tot and nonblank == 0 else ""
            print(f"    {m}.txt: ячеек {tot}, непустых {nonblank} ({share:.1f}%){flag}")
            if tot and nonblank == 0:
                fail(f"E9: экспорт {m}.txt полностью пуст (все значения = novalue) — "
                     f"карта не содержит данных")
        if not expected_maps:
            warn("в config.yaml нет checks.map_files — ожидаемый список карт не задан данными")
    else:
        print(f"  (dry-run: карты не обязательны; на --execute ожидается >= 8)")
    branches = ((report.get("project") or {}).get("ensemble") or {}).get("branches") or []
    print(f"  ветвей ансамбля в отчёте: {len(branches)}")
    exec_branches = [b for b in branches if b.get("ok")]
    if EXECUTE:
        cubes = ((report.get("project") or {}).get("ensemble") or {})
        print(f"  ветвей ok: {len(exec_branches)}/{len(branches)}; metric заполнена у "
              f"{sum(1 for b in branches if isinstance(b.get('metric'), (int, float)))}")
        for b in branches:
            q = b.get("qaqc") or {}
            print(f"    {b.get('id')}: ok={b.get('ok')} metric={b.get('metric')} "
                  f"qaqc={{p:{q.get('passed')}, f:{q.get('failed')}, na:{q.get('not_applicable')}, "
                  f"kq:{q.get('kq')}, kc:{q.get('kc')}}} err={str(b.get('error') or '')[:60]}")
        if not exec_branches:
            fail("--execute: ни одна ветвь ансамбля не завершилась успешно")
    wf = ART_DIR / "Structure_modeling.py"
    if wf.is_file():
        text = wf.read_text(encoding="utf-8", errors="replace")
        items = len(re.findall(r"begin_wf_item", text))
        print(f"  отрендеренный воркфлоу: строк {len(text.splitlines())}, "
              f"begin_wf_item={items}")
        if items != done:
            fail(f"в воркфлоу {items} блоков begin_wf_item, а done-шагов {done} "
                 f"(шаг без блока или блок без шага)")
        # правило 7: чужые токены обучения не должны попасть в рендер
        try:
            import yaml
            cfg_raw = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
            foreign = [str(t) for t in ((cfg_raw.get("workflow") or {}).get("foreign_tokens")
                                        or []) if str(t)]
        except Exception:                          # noqa: BLE001
            foreign = []
        hits = [t for t in foreign if t in text]
        print(f"  чужые токены обучения в рендере: {hits if hits else 'нет'} "
              f"(всего проверено {len(foreign)})")
        if hits:
            fail(f"правило 7: в отрендеренном воркфлоу остались чужие токены: {hits}")

    print("\n=== 6. РЕАЛЬНЫЙ ПРОГОН (--execute) ===")
    if not EXECUTE:
        print("  не запускался: нужен флаг --execute (лицензия, ~13 мин)")
    else:
        tnav = report.get("tnav") or {}
        print(f"  tnav: ok={tnav.get('ok')} kind={tnav.get('kind')} "
              f"error={str(tnav.get('error') or '')[:120]}")
        if not tnav.get("ok", False):
            fail(f"реальный прогон тНава не ok: {tnav.get('error') or tnav.get('returncode')}")
        models = (report.get("project") or {}).get("models_dir") or "models"
        for vid in [b.get("id") for b in branches][:8]:
            snp = ROOT / str(models) / str(vid) / "Герасимовское.snp"
            print(f"    ветка {vid}: проект {'есть' if snp.exists() else 'НЕТ'} ({snp.name})")
            if not snp.exists():
                warn(f"ветка {vid}: нет файла проекта {snp} — кубы FACIES/PORO/PERM не доказаны "
                     f"артефактом")
    print("\n=== ИТОГ (chain) ===")
    print(f"FAIL: {len(FAIL)} | WARN: {len(WARN)}")
    if "--json" in sys.argv:
        print(json.dumps({"fail": FAIL, "warn": WARN}, ensure_ascii=False, indent=2))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
