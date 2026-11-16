"""Проба сохранения проекта тНава (task-17, одна сессия тНава).

Отвечает на вопросы приёмки:
  1) что реально лежит на диске после прогона (`.snp` 102 Б — это пустышка или
     указатель на каталог `.snf` с данными проекта?);
  2) пишет ли `save_project()` (тот вызов, что делает наш клиент) что-то на диск;
  3) материализуют ли документированные вызовы API копию проекта на диске:
     `Project.copy_project(path)` и `Connection.open_project_copy(source, dest)`;
  4) принимает ли консоль тНава аргумент пути у `save_project (path = ...)`
     (проба, а не догадка — правило 8).

Сигнатуры взяты из официального `tNavigator_python_API.py` 26.2 (не выдуманы).
Сырой вывод пишется в `runs/_probe_model_save.txt`.

Запуск: python -X utf8 tools/probe_model_save.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_config            # noqa: E402
from domain.tnav_client import TnavClient      # noqa: E402

OUT: list[str] = []
REPORT = ROOT / "runs" / "_probe_model_save.txt"


def log(text: str) -> None:
    print(text, flush=True)
    OUT.append(text)


def dir_files(path: Path) -> int:
    return sum(1 for p in path.rglob("*") if p.is_file()) if path.is_dir() else 0


def dir_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.is_dir() else 0


def describe(title: str, snp: Path) -> None:
    snf = snp.with_suffix(".snf")
    log(f"  {title}: .snp exists={snp.is_file()} size={snp.stat().st_size if snp.is_file() else 0} Б "
        f"| .snf exists={snf.is_dir()} files={dir_files(snf)} bytes={dir_bytes(snf)}")


def main() -> int:
    cfg = load_config()
    cfg.set("tnavigator.dry_run", False)
    field = str(cfg.get("project.default_field", "") or "")
    models = cfg.path("project.models_dir", "models")
    probe_dir = cfg.path("runs.root", "runs") / "_probe_model_save"
    probe_dir.mkdir(parents=True, exist_ok=True)

    src = None
    for cand in sorted(models.glob(f"S00*/{field}.snp")):
        if cand.with_suffix(".snf").is_dir():
            src = cand
    log(f"поле (данные config): {field}")
    log(f"исходный РЕАЛЬНЫЙ проект: {src}")
    if src is None:
        log("нет готового проекта ветки — пробу отменяю (нет модели для копирования)")
        return 2
    describe("источник", src)

    client = TnavClient(cfg)
    client.dry_run = False
    client.cfg.set("tnavigator.dry_run", False)
    client.set_log(lambda t: log(f"  тНав: {t}"))
    started = time.time()
    # Проект мог остаться открытым другим экземпляром тНава (в т.ч. после приёмки):
    # перебираем доступные проекты веток и берём первый, который реально открылся.
    opened = False
    for cand in sorted(models.glob(f"S00*/{field}.snp")):
        if not cand.with_suffix(".snf").is_dir():
            continue
        try:
            client.open(project_path=cand, create=False)
            src, opened = cand, True
            log(f"открыт проект: {cand}")
            break
        except Exception as exc:                       # noqa: BLE001
            log(f"проект {cand.name} ({cand.parent.name}) не открылся: {exc}")
    if not opened:
        log("ни один проект ветки не открылся — проба не выполнена (свободного проекта нет)")
        try:
            client.close()
        except Exception:                              # noqa: BLE001
            pass
        log("ИТОГ: " + json.dumps({"opened": False, "reason": "все проекты заняты/недоступны",
                                   "source_snp_size": src.stat().st_size if src.is_file() else 0,
                                   "source_snf_files": dir_files(src.with_suffix(".snf")),
                                   "source_snf_bytes": dir_bytes(src.with_suffix(".snf"))},
                                  ensure_ascii=False))
        REPORT.write_text("\n".join(OUT), encoding="utf-8")
        return 3
    try:
        log(f"1) open(create=False): project_path()={client.project_path()!r}")
        describe("после open", src)

        # 2) наш вызов сохранения (TnavClient.save_project → run_py_code('save_project()'))
        before = src.stat().st_size if src.is_file() else 0
        ok = client.save_project()
        log(f"2) save_project(): вернул {ok}; .snp было {before} Б, стало "
            f"{src.stat().st_size if src.is_file() else 0} Б")
        describe("после save_project", src)

        # 3) документированный API: Project.copy_project(path)
        dest = probe_dir / "copy" / f"{field}.snp"
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            client._project.copy_project(str(dest))
            log("3) Project.copy_project(path): вызов выполнен")
            describe("копия", dest)
        except Exception as exc:                       # noqa: BLE001
            log(f"3) Project.copy_project(path): ОШИБКА {type(exc).__name__}: {exc}")

        # 4) проба аргумента пути у консольной функции save_project (правило 8: проба)
        probe_snp = probe_dir / "as_path" / f"{field}.snp"
        probe_snp.parent.mkdir(parents=True, exist_ok=True)
        try:
            res = client._project.run_py_code(code=f'save_project (path = "{probe_snp}")')
            log(f"4) run_py_code('save_project (path = ...)'): ответ={res!r}")
        except Exception as exc:                       # noqa: BLE001
            log(f"4) run_py_code('save_project (path = ...)'): ОШИБКА "
                f"{type(exc).__name__}: {exc}")
        describe("после save_project(path=...)", probe_snp)

        # 5) наш вызов save_project с аргументом пути (как это делает agents/runner.py):
        #    ожидаем TypeError (наш метод аргументов не принимает) — фиксируем факт
        try:
            client.save_project(str(probe_dir / "via_runner" / f"{field}.snp"))
            log("5) client.save_project(path): принял аргумент (неожиданно)")
        except TypeError as exc:
            log(f"5) client.save_project(path): TypeError как ожидалось — {exc}")
    finally:
        try:
            client.close()
        except Exception as exc:                       # noqa: BLE001
            log(f"close: ошибка {exc}")
    log(f"сессия тНава: {time.time() - started:.1f} с")

    # 6) документированный API: Connection.open_project_copy(source, dest)
    client2 = TnavClient(cfg)
    client2.dry_run = False
    client2.cfg.set("tnavigator.dry_run", False)
    client2.set_log(lambda t: log(f"  тНав: {t}"))
    d2 = probe_dir / "opencopy" / f"{field}.snp"
    d2.parent.mkdir(parents=True, exist_ok=True)
    try:
        client2.open(project_path=src, create=False)
        try:
            client2._conn.open_project_copy(source_path=str(src), dest_path=str(d2),
                                            save_on_close=True)
            log("6) Connection.open_project_copy(source, dest): вызов выполнен")
            describe("копия open_project_copy", d2)
        except Exception as exc:                       # noqa: BLE001
            log(f"6) Connection.open_project_copy: ОШИБКА {type(exc).__name__}: {exc}")
    except Exception as exc:                           # noqa: BLE001
        log(f"6) не удалось открыть соединение: {type(exc).__name__}: {exc}")
    finally:
        try:
            client2.close()
        except Exception as exc:                       # noqa: BLE001
            log(f"close2: ошибка {exc}")

    summary = {
        "field": field, "source": str(src),
        "source_snp_size": src.stat().st_size if src.is_file() else 0,
        "source_snf_files": dir_files(src.with_suffix(".snf")),
        "source_snf_bytes": dir_bytes(src.with_suffix(".snf")),
        "copy_project_snp": (probe_dir / "copy" / f"{field}.snp").is_file(),
        "copy_project_snf_files": dir_files(probe_dir / "copy" / f"{field}.snf"),
        "save_project_path_arg": probe_snp.is_file(),
        "open_project_copy_snp": d2.is_file(),
        "open_project_copy_snf_files": dir_files(d2.with_suffix(".snf")),
    }
    log("ИТОГ: " + json.dumps(summary, ensure_ascii=False))
    REPORT.write_text("\n".join(OUT), encoding="utf-8")
    log(f"сырой вывод: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
