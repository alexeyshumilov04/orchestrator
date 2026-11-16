"""Тесты сохранения модели/артефактов прогона и манифеста (task-17).

Проверяется:
  * dry-run: модель не создаётся, но описание прогона сохраняется (`workflow_only`);
  * execute-подобный прогон: `<поле>.snp` + каталог `<поле>.snf` копируются
    в `models/<run_id>/`, манифест содержит размеры и sha256 каждого файла;
  * чужой/временный `run_dir` не нужен после сохранения (копия живёт отдельно) —
    именно это лечит замечание «модели не сохраняются»;
  * повторный прогон без `run_id` (CLI) НЕ затирает модель предыдущего прогона;
  * исходные данные заказчика не изменяются (data_integrity);
  * `report.json` содержит ключ `model_artifacts` (проверяется на dry-run конвейере);
  * доменных имён в коде нет (поле приходит параметром).

Запуск: python -X utf8 tests/test_model_artifacts.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_config                      # noqa: E402
from core.coordinator import (_DEFAULT_DRY_SUFFIX,      # noqa: E402
                              _copy_branch_project as copy_branch_project_probe)
from core.model_artifacts import (MANIFEST_NAME, persist_model,  # noqa: E402
                                  sha256_file)

_PASS: list[str] = []
_FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    cond = bool(cond)
    (_PASS if cond else _FAIL).append(name)
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


def _fake_run_dir(root: Path, field: str, *, with_model: bool) -> Path:
    """Каталог прогона: описание всегда, модель — по флагу."""
    run_dir = root / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "plan.json").write_text("{}", encoding="utf-8")
    (run_dir / "report.json").write_text('{"field": "x"}', encoding="utf-8")
    (run_dir / "Structure_modeling.py").write_text("print('wf')\n", encoding="utf-8")
    if with_model:
        # Проект модели: файл .snp + рабочий каталог .snf с содержимым
        (run_dir / f"{field}.snp").write_bytes(b"SNP-PROJECT-DATA" * 100)
        snf = run_dir / f"{field}.snf"
        (snf / "State").mkdir(parents=True, exist_ok=True)
        (snf / "State" / "project.state").write_bytes(b"state" * 50)
        (run_dir / "main_grid.GRDECL").write_bytes(b"GRID" * 200)
    return run_dir


def main() -> int:
    cfg = load_config()
    field = str(cfg.get("project.default_field", "") or "")
    tmp = Path(tempfile.mkdtemp(prefix="model_artifacts_"))
    models_root = tmp / "models"
    cfg.set("project.models_dir", str(models_root))
    cfg.set("project.model_dir", "")

    # 1) DRY-RUN: модели нет → сохраняется описание прогона, verdict=workflow_only
    run_dry = _fake_run_dir(tmp / "dry", field, with_model=False)
    res_dry = persist_model(cfg, run_dry, field, run_id="dryrun01", execute=False)
    check("dry-run: сохранено описание прогона (verdict=workflow_only)",
          res_dry["verdict"] == "workflow_only" and res_dry["files"] > 0, str(res_dry))
    check("dry-run: каталог сохранения — models/<run_id>",
          Path(res_dry["dir"]) == models_root / "dryrun01", res_dry["dir"])
    man_dry = json.loads(Path(res_dry["manifest"]).read_text(encoding="utf-8"))
    check("dry-run: манифест перечисляет файлы с размерами и sha256",
          bool(man_dry["files"]) and all(
              {"rel", "size", "sha256"} <= set(f) and len(f["sha256"]) == 64
              for f in man_dry["files"]), str(man_dry["files"][:1]))
    check("dry-run: manifest_version/поле/run_id/time записаны",
          man_dry["manifest_version"] == 1 and man_dry["field"] == field
          and man_dry["run_id"] == "dryrun01" and bool(man_dry["created_at"]),
          json.dumps({k: man_dry[k] for k in ("manifest_version", "field", "run_id")},
                     ensure_ascii=False))

    # 2) EXECUTE-подобный: модель копируется, хеши совпадают с источником
    run_ex = _fake_run_dir(tmp / "exec", field, with_model=True)
    branch_dir = tmp / "models" / "S001"
    branch_dir.mkdir(parents=True, exist_ok=True)
    (branch_dir / f"{field}.snp").write_bytes(b"BRANCH-SNP")
    (branch_dir / f"{field}.snf").mkdir(exist_ok=True)
    (branch_dir / f"{field}.snf" / "state.bin").write_bytes(b"x" * 4096)
    src_snp = run_ex / f"{field}.snp"
    res_ex = persist_model(cfg, run_ex, field, run_id="exec01", execute=True,
                           tnav_version="2024.2-test", tnav_executable="tNavigator-con.exe",
                           branches=[{"id": "S001", "path": str(branch_dir / f"{field}.snp"),
                                      "metric": 1234.5, "ok": True}])
    check("execute: модель сохранена (verdict=saved, model_present=True)",
          res_ex["verdict"] == "saved" and res_ex["model_present"] is True, str(res_ex))
    dst_snp = Path(res_ex["dir"]) / f"{field}.snp"
    check("execute: файл .snp скопирован и не пуст",
          dst_snp.is_file() and dst_snp.stat().st_size == src_snp.stat().st_size,
          f"{dst_snp}")
    check("execute: sha256 копии совпадает с источником",
          sha256_file(dst_snp) == sha256_file(src_snp))
    check("execute: каталог .snf скопирован целиком",
          (Path(res_ex["dir"]) / f"{field}.snf" / "State" / "project.state").is_file())
    check("execute: GRDECL-сетка скопирована",
          (Path(res_ex["dir"]) / "main_grid.GRDECL").is_file())
    man = json.loads(Path(res_ex["manifest"]).read_text(encoding="utf-8"))
    check("execute: манифест содержит версию/исполняемый файл тНава",
          man["tnav"]["version"] == "2024.2-test"
          and man["tnav"]["executable"].endswith("tNavigator-con.exe"),
          json.dumps(man["tnav"], ensure_ascii=False))
    bref = (man.get("branches") or [{}])[0]
    check("execute: ветки ансамбля в манифесте — путь/размеры/sha256 .snp и объём .snf",
          [b.get("id") for b in man["branches"]] == ["S001"]
          and bref.get("snp_exists") is True and bref.get("snp_size") == len(b"BRANCH-SNP")
          and len(bref.get("snp_sha256") or "") == 64
          and bref.get("snf_bytes") == 4096 and bref.get("metric") == 1234.5,
          json.dumps(bref, ensure_ascii=False))
    check("execute: итоги (files/bytes) в манифесте не нулевые",
          man["totals"]["files"] == res_ex["files"] and man["totals"]["bytes"] > 0,
          str(man["totals"]))

    # 3) копия НЕЗАВИСИМА от временного каталога прогона: он удалён — модель цела
    shutil.rmtree(tmp / "exec")
    check("модель живёт после удаления каталога прогона (временный run_dir не нужен)",
          dst_snp.is_file() and sha256_file(dst_snp) == sha256_file(src_snp)
          if src_snp.exists() else dst_snp.is_file())

    # 4) указатель на последнюю модель (предсказуемая точка входа)
    latest = models_root / "latest.json"
    check("latest.json указывает на сохранённую модель",
          latest.is_file() and json.loads(latest.read_text(encoding="utf-8"))["dir"]
          == res_ex["dir"])

    # 5) CLI без run_id: имя с меткой времени, модель прошлого прогона не затёрта
    run_cli = _fake_run_dir(tmp / "cli", field, with_model=True)
    res_cli = persist_model(cfg, run_cli, field, run_id="", execute=True)
    check("CLI без run_id: свой каталог с меткой времени (не поверх прошлого)",
          Path(res_cli["dir"]) != Path(res_ex["dir"])
          and Path(res_cli["dir"]).name.startswith(run_cli.name),
          f"{res_cli['dir']} vs {res_ex['dir']}")
    check("CLI: модель предыдущего прогона осталась на месте", dst_snp.is_file())

    # 5б) CLI dry-run без run_id: СТАБИЛЬНЫЙ каталог (не плодим десятки копий по 4.6 МБ)
    run_cli2 = _fake_run_dir(tmp / "clidry", field, with_model=False)
    res_cli2 = persist_model(cfg, run_cli2, field, run_id="", execute=False)
    res_cli3 = persist_model(cfg, run_cli2, field, run_id="", execute=False)
    check("CLI dry-run без run_id: стабильный каталог модели не плодится",
          Path(res_cli2["dir"]) == models_root / "_run_artifacts" / run_cli2.name
          and Path(res_cli2["dir"]) == Path(res_cli3["dir"]), res_cli2["dir"])

    # 6) data_integrity: исходные данные не изменяются
    data_root = ROOT / "data"
    before = {str(p.relative_to(data_root)): (p.stat().st_size, p.stat().st_mtime_ns)
              for p in data_root.rglob("*") if p.is_file()}
    run_di = _fake_run_dir(tmp / "di", field, with_model=True)
    persist_model(cfg, run_di, field, run_id="di01", execute=True)
    after = {str(p.relative_to(data_root)): (p.stat().st_size, p.stat().st_mtime_ns)
             for p in data_root.rglob("*") if p.is_file()}
    check("data_integrity: каталог данных заказчика не изменён", before == after,
          f"было {len(before)} файлов, стало {len(after)}")

    # 7) фиксированное место из данных проекта (project.model_dir)
    fixed = tmp / "fixed_models"
    cfg.set("project.model_dir", str(fixed))
    run_fix = _fake_run_dir(tmp / "fix", field, with_model=True)
    res_fix = persist_model(cfg, run_fix, field, run_id="ignored", execute=True)
    check("путь из данных project.model_dir имеет приоритет",
          Path(res_fix["dir"]) == fixed, res_fix["dir"])
    cfg.set("project.model_dir", "")

    # 8) пустой каталог прогона: честное «нечего сохранять», без исключения
    empty = tmp / "empty"
    empty.mkdir()
    res_empty = persist_model(cfg, empty, field, run_id="empty1")
    check("пустой каталог: verdict=nothing_to_save с причиной (не падение)",
          res_empty["verdict"] == "nothing_to_save" and bool(res_empty["reason"]),
          str(res_empty))

    # 8б) EXECUTE без файла проекта: явное предупреждение (дефект сохранения тНавом)
    run_nomodel = _fake_run_dir(tmp / "nomodel", field, with_model=False)
    res_nm = persist_model(cfg, run_nomodel, field, run_id="nomodel1", execute=True)
    check("execute без .snp: verdict=workflow_only + warning «НЕ персистится»",
          res_nm["verdict"] == "workflow_only" and res_nm["project_file_present"] is False
          and "НЕ персистится" in (res_nm.get("warning") or ""),
          json.dumps({k: res_nm.get(k) for k in ("verdict", "warning")}, ensure_ascii=False))
    check("execute без .snp: в манифесте зафиксировано ожидаемое имя проекта",
          json.loads(Path(res_nm["manifest"]).read_text(encoding="utf-8"))["expected_project"]
          .endswith(f"{field}.snp"))

    # 9) конвейер dry-run кладёт ключ model_artifacts в report.json
    from core.coordinator import Coordinator              # noqa: PLC0415
    cfg.set("project.models_dir", str(models_root))
    coord = Coordinator(cfg)
    with tempfile.TemporaryDirectory() as td:
        report = coord.run(field, run_dir=Path(td) / "run", execute=False)
    ma = report.get("model_artifacts") or {}
    check("конвейер dry-run: report.model_artifacts заполнен (путь + манифест)",
          bool(ma.get("dir")) and Path(ma["manifest"]).is_file()
          and ma.get("verdict") == "workflow_only",
          json.dumps({k: ma.get(k) for k in ("verdict", "dir", "files")}, ensure_ascii=False))
    check("конвейер: project.model_artifacts совпадает с report",
          (report.get("project") or {}).get("model_artifacts", {}).get("dir") == ma.get("dir"))
    check("конвейер: report содержит атрибуцию (execute=false, caller, run_key, models_dir)",
          report.get("execute") is False and bool(report.get("caller"))
          and bool(report.get("run_key")) and bool(report.get("models_dir")),
          json.dumps({k: report.get(k) for k in ("execute", "caller", "run_key", "models_dir")},
                     ensure_ascii=False))

    # 10) в коде нет доменных имён: поле приходит параметром
    src = (ROOT / "core" / "model_artifacts.py").read_text(encoding="utf-8")
    check("домен только в данных: имя поля в коде не зашито",
          field and field not in src, field)

    # 11) task-18/5: атрибуция прогона в манифесте и результате
    res_attr = persist_model(cfg, _fake_run_dir(tmp / "attr", field, with_model=True),
                             field, run_id="web42", run_key="web42", caller="web",
                             execute=True)
    man_attr = json.loads(Path(res_attr["manifest"]).read_text(encoding="utf-8"))
    check("манифест: run_key/caller/models_dir/run_dir записаны (атрибуция источника)",
          man_attr["run_key"] == "web42" and man_attr["caller"] == "web"
          and man_attr["models_dir"] == str(models_root)
          and "attr" in man_attr["source_run_dir"]
          and res_attr["caller"] == "web",
          json.dumps({k: man_attr[k] for k in ("run_key", "caller", "models_dir")},
                     ensure_ascii=False))

    # 12) task-18/4: порог хеширования из ДАННЫХ (сверх порога — размер без sha256)
    cfg.set("project.model_artifacts.max_hashed_files", 2)
    res_cap = persist_model(cfg, _fake_run_dir(tmp / "cap", field, with_model=True),
                            field, run_key="cap01", execute=True)
    man_cap = json.loads(Path(res_cap["manifest"]).read_text(encoding="utf-8"))
    unhashed = [f for f in man_cap["files"] if f.get("hashed") is False]
    check("порог max_hashed_files: часть файлов без sha256, но с пометкой hashed:false",
          man_cap["totals"]["max_hashed_files"] == 2 and man_cap["totals"]["hashed"] == 2
          and len(unhashed) >= 1 and all(f["sha256"] == "" for f in unhashed),
          json.dumps(man_cap["totals"], ensure_ascii=False))
    check("порог: файлы без sha256 всё равно перечислены с размером",
          all(f["size"] > 0 for f in unhashed), str(unhashed[:1]))
    cfg.set("project.model_artifacts.max_hashed_files", 0)

    # 13) task-18/4: ретенция keep_last (старые модели поля удаляются, описания — нет)
    keep_root = tmp / "keep_models"
    cfg.set("project.models_dir", str(keep_root))
    cfg.set("project.model_artifacts.keep_last", 1)
    first = persist_model(cfg, _fake_run_dir(tmp / "k1", field, with_model=True),
                          field, run_key="keep_one", execute=True)
    dry_desc = persist_model(cfg, _fake_run_dir(tmp / "k0", field, with_model=False),
                             field, run_key="", execute=False)
    second = persist_model(cfg, _fake_run_dir(tmp / "k2", field, with_model=True),
                           field, run_key="keep_two", execute=True)
    man_keep = json.loads(Path(second["manifest"]).read_text(encoding="utf-8"))
    check("ретенция keep_last=1: старая модель удалена, новая осталась, описания целы",
          not Path(first["dir"]).exists() and Path(second["dir"]).is_dir()
          and Path(dry_desc["dir"]).is_dir()
          and man_keep["retention"]["removed"] == [first["dir"]],
          json.dumps(man_keep["retention"], ensure_ascii=False))
    cfg.set("project.model_artifacts.keep_last", 0)
    cfg.set("project.models_dir", str(models_root))

    # 14) task-18/B: пер-прогонная зона веток и кэш по ключу вариации
    branch_src = tmp / "branch_src"
    (branch_src / f"{field}.snf").mkdir(parents=True, exist_ok=True)
    (branch_src / f"{field}.snp").write_bytes(b"SNP")
    (branch_src / f"{field}.snf" / "state.bin").write_bytes(b"x" * 32)
    cache_root = tmp / "models" / "branches" / "_cache"
    coord2 = Coordinator(cfg)
    vparams = {"horizon_smooth": {"radius": 400}}
    coord2._branch_cache_put(cache_root, "S001", vparams, branch_src, field)
    key = coord2._branch_cache_key(cache_root, "S001", vparams)
    other = coord2._branch_cache_key(cache_root, "S001", {"horizon_smooth": {"radius": 50}})
    check("кэш ветки: ключ вариации находит готовый проект, другая вариация — нет",
          bool(key) and Path(key).is_dir() and other == "",
          f"key={key} other={other}")
    dest = tmp / "branch_zone" / "run_key_A" / "S001"
    ok_copy = copy_branch_project_probe(branch_src, dest, field)
    check("ветки в пер-прогонной зоне: проект копируется в models/branches/<run_key>/<vid>",
          ok_copy and (dest / f"{field}.snp").is_file()
          and (dest / f"{field}.snf" / "state.bin").is_file(), str(dest))
    src_coord = (ROOT / "core" / "coordinator.py").read_text(encoding="utf-8")
    check("rmtree ветки — только внутри своей зоны run_key (общий models/<vid> не трогаем)",
          "vdir = run_zone / vid" in src_coord
          and "shutil.rmtree(vdir" not in src_coord,
          "ищем run_zone и отсутствие rmtree(vdir)")

    # 15) task-18/A: dry-run пишет в СВОЙ каталог (суффикс — ДАННЫЕ)
    dry_root = tmp / "dry_runs"
    cfg.set("runs.root", str(dry_root))
    coord3 = Coordinator(cfg)
    rep_a = coord3.run(field, execute=False)
    dir_a = Path(str(rep_a["run_dir"]))
    check("dry-run: отдельный каталог с суффиксом (execute-каталог не смешивается)",
          dir_a.parent == dry_root and dir_a.name == f"run_{field}_dry",
          str(dir_a))
    cfg.set("runs.dry_suffix", "-X")
    rep_b = Coordinator(cfg).run(field, execute=False)
    check("суффикс dry-run берётся из ДАННЫХ (runs.dry_suffix)",
          Path(str(rep_b["run_dir"])).name == f"run_{field}-X",
          str(rep_b["run_dir"]))
    cfg.set("runs.dry_suffix", _DEFAULT_DRY_SUFFIX)
    cfg.set("runs.root", str(ROOT / "runs"))

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nпройдено: {len(_PASS)} | провалено: {len(_FAIL)}")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
