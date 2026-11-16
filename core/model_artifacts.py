"""Сохранение модели и артефактов прогона в предсказуемое место + манифест (task-17).

Замечание заказчика: «не вижу, чтобы модели сохранялись». Причина установлена:
проект ``<поле>.snp`` и рабочий каталог ``<поле>.snf`` создаются ВНУТРИ каталога
прогона, а приёмочные прогоны запускаются с ВРЕМЕННЫМ ``run_dir`` — модель
исчезает вместе с временным каталогом (в рабочем каталоге не оставалось ни одного
``*.snp``, кроме пробного огрызка 102 Б).

Модуль персистит артефакты СРАЗУ по завершении ``Coordinator.run`` (то есть до
того, как вызывающая сторона удалит временный каталог) и пишет ``manifest.json``
с размерами и sha256. Пути и набор шаблонов — ДАННЫЕ (``project.models_dir``,
``project.model_dir``, ``project.model_artifacts.globs``); доменных имён
(месторождений/пластов/объектов) в коде нет — поле приходит параметром.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

# Шаблоны ФАЙЛОВ МОДЕЛИ по умолчанию — инфраструктура (расширения форматов), не домен.
# Переопределяются данными: project.model_artifacts.globs.
DEFAULT_MODEL_GLOBS = ("*.snp", "*.snf", "*.data", "*.GRDECL", "*.egrid", "*.init",
                       "*.unrst", "*.INIT", "*.UNRST", "*.EGRID")
# Файлы ОПИСАНИЯ прогона (по ним модель воспроизводима и открываема).
DEFINITION_FILES = ("plan.json", "steps.json", "project.json", "report.json",
                    "report_execute.json")
MANIFEST_NAME = "manifest.json"
LATEST_NAME = "latest.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """sha256 файла (потоково: артефакты тНава бывают крупными)."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _model_globs(cfg) -> tuple[str, ...]:
    """Шаблоны файлов модели: из ДАННЫХ (project.model_artifacts.globs) или умолчание."""
    raw = []
    try:
        raw = list(cfg.get("project.model_artifacts.globs", []) or [])
    except Exception:                              # noqa: BLE001 — данных может не быть
        raw = []
    globs = [str(x) for x in raw if str(x).strip()]
    return tuple(globs) if globs else DEFAULT_MODEL_GLOBS


def _expand_model_files(run_dir: Path, globs: tuple[str, ...]) -> list[tuple[Path, str]]:
    """Файлы модели в каталоге прогона: [(путь, вид)]; каталоги ``*.snf`` — целиком."""
    found: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for pattern in globs:
        for path in sorted(run_dir.glob(pattern)):
            if path.is_dir():
                for inner in sorted(p for p in path.rglob("*") if p.is_file()):
                    if inner not in seen:
                        seen.add(inner)
                        found.append((inner, "model"))
            elif path.is_file() and path not in seen:
                seen.add(path)
                found.append((path, "model"))
    return found


def _definition_files(run_dir: Path, field: str) -> list[tuple[Path, str]]:
    """Файлы описания прогона (воркфлоу + планы/отчёты), если они есть."""
    out: list[tuple[Path, str]] = []
    for name in DEFINITION_FILES:
        cand = run_dir / name
        if cand.is_file():
            out.append((cand, "definition"))
    for wf in sorted(run_dir.glob("*.py")):
        if wf.is_file():
            out.append((wf, "definition"))
    return out


def _target_dir(cfg, run_dir: Path, run_id: str, *, model_present: bool) -> Path:
    """Каталог сохранения: ``project.model_dir`` (данные) → иначе ``models/<run_id>``.

    Без ``run_id`` (CLI-прогон) имя дополняется меткой времени, чтобы модель
    предыдущего прогона не была затёрта. Исключение — прогон БЕЗ модели (dry-run):
    его описание одинаково от прогона к прогону, поэтому пишем в СТАБИЛЬНЫЙ каталог
    ``models/_run_artifacts/<каталог прогона>``, иначе приёмочные прогоны плодят
    десятки каталогов по ~4.6 МБ (наблюдалось: 44 каталога, 271 МБ).
    """
    fixed = str(cfg.get("project.model_dir", "") or "").strip()
    if fixed:
        return cfg.path("project.model_dir", fixed)
    root = cfg.path("project.models_dir", "models")
    name = str(run_id or "").strip()
    if not name and not model_present:
        return root / "_run_artifacts" / run_dir.name
    if not name:
        name = f"{run_dir.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return root / name


def _hash_cap(cfg) -> int:
    """Сколько файлов манифеста хешировать: ДАННЫЕ `project.model_artifacts.max_hashed_files`.

    0/отсутствие ключа → хешировать всё (прежнее, наиболее доказательное поведение).
    Сверх порога пишем размер и честную пометку `hashed: false` (не выдумываем хеш).
    """
    try:
        return max(0, int(cfg.get("project.model_artifacts.max_hashed_files", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _keep_last(cfg) -> int:
    """Ретенция моделей на поле: ДАННЫЕ `project.model_artifacts.keep_last`.

    0/отсутствие ключа → хранить все модели (консервативное умолчание).
    """
    try:
        return max(0, int(cfg.get("project.model_artifacts.keep_last", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _apply_retention(cfg, target: Path, field: str) -> dict:
    """Удалить старые сохранённые модели ПОЛЯ сверх `keep_last` (с логом в манифест).

    Трогаем только каталоги-сохранения моделей: с `manifest.json`, где `field`
    совпадает и `execute=true`. Ветки (`branches/`), описания dry-run
    (`_run_artifacts/`), кэш и пробные каталоги НЕ удаляются никогда.
    """
    keep = _keep_last(cfg)
    report = {"keep_last": keep, "removed": [], "kept": 0}
    if keep <= 0:
        return report
    root = target.parent
    candidates: list[tuple[float, Path]] = []
    for d in root.iterdir() if root.is_dir() else []:
        if not d.is_dir() or d.name.startswith("_") or d.name in ("branches",):
            continue
        man = d / MANIFEST_NAME
        if not man.is_file():
            continue
        try:
            data = json.loads(man.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(data.get("field")) != str(field) or not data.get("execute"):
            continue
        candidates.append((d.stat().st_mtime, d))
    candidates.sort(key=lambda x: x[0], reverse=True)
    report["kept"] = min(len(candidates), keep)
    for _, d in candidates[keep:]:
        try:
            shutil.rmtree(d)
            report["removed"].append(str(d))
        except OSError:
            continue
    return report


def _branch_refs(branches) -> list[dict]:
    """Ссылки на модели веток ансамбля (пути/размеры/sha256 .snp + объём .snf).

    Ветки живут в пер-прогонной зоне `models/branches/<run_key>/<vid>` (task-18/B) —
    их НЕ копируем повторно (десятки МБ на ветку), но фиксируем в манифесте.
    """
    out: list[dict] = []
    for b in branches or []:
        if not isinstance(b, dict):
            out.append({"id": str(b)})
            continue
        path = Path(str(b.get("path") or ""))
        snf = path.with_suffix(".snf")
        files = [p for p in snf.rglob("*") if p.is_file()] if snf.is_dir() else []
        out.append({"id": str(b.get("id") or ""), "path": str(path),
                    "snp_exists": path.is_file(),
                    "snp_size": path.stat().st_size if path.is_file() else 0,
                    "snp_sha256": sha256_file(path) if path.is_file() else "",
                    "snf_files": len(files),
                    "snf_bytes": sum(p.stat().st_size for p in files),
                    "metric": b.get("metric"), "ok": b.get("ok")})
    return out


def persist_model(cfg, run_dir, field: str, *, run_id: str = "", run_key: str = "",
                  execute: bool = False, caller: str = "unknown",
                  tnav_version: str = "", tnav_executable: str = "",
                  branches: list | None = None, extra: dict | None = None) -> dict:
    """Сохранить модель/артефакты прогона и записать манифест.

    Возвращает блок для ``report.json`` (ключ ``model_artifacts``). Никогда не
    бросает исключение: сохранение не должно ронять прогон (ошибка честно
    попадает в ``verdict=error`` + ``reason``).

    ``run_key`` — ключ прогона (имя каталога модели и зоны веток), ``caller`` —
    источник запуска (cli|web|test|verify) для однозначной атрибуции снапшота.
    """
    run_dir = Path(run_dir)
    expected = run_dir / f"{field}.snp"
    models_dir = cfg.path("project.models_dir", "models")
    result: dict = {"verdict": "nothing_to_save", "reason": "", "dir": "",
                    "manifest": "", "files": 0, "bytes": 0, "sha256": {},
                    "model_present": False, "expected_project": str(expected),
                    "project_file_present": expected.is_file(), "warning": "",
                    "run_dir": str(run_dir), "models_dir": str(models_dir),
                    "run_key": str(run_key or run_id or ""), "caller": str(caller or "unknown"),
                    "created_at": _utc_now()}
    try:
        found = _expand_model_files(run_dir, _model_globs(cfg))
        # В dry-run модель НЕ создаётся: найденные `.snp`/`.snf` — остатки прошлого
        # реального прогона в том же каталоге. Копировать их под именем dry-run нельзя
        # (манифест врал бы «модель сохранена» и это +58 МБ на каждый dry-run).
        model_files = found if execute else []
        def_files = _definition_files(run_dir, field)
        result["model_present"] = bool(model_files)
        result["stale_project_files"] = 0 if execute else len(found)
        target = _target_dir(cfg, run_dir, run_key or run_id,
                             model_present=result["model_present"])
        if not model_files and not def_files:
            result["reason"] = (f"в каталоге прогона {run_dir} нет ни файлов модели "
                                f"({', '.join(_model_globs(cfg))}), ни описания прогона")
            return result

        target.mkdir(parents=True, exist_ok=True)
        entries: list[dict] = []
        cap = _hash_cap(cfg)          # 0 → хешировать всё (см. _hash_cap)
        hashed = 0
        for path, kind in model_files + def_files:
            rel = path.relative_to(run_dir)
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            size = dest.stat().st_size
            result["bytes"] += size
            result["files"] += 1
            rel_key = str(rel).replace("\\", "/")
            if cap and hashed >= cap:
                # Сверх порога — размер есть, sha256 НЕТ (и это видно в манифесте).
                entries.append({"rel": rel_key, "kind": kind, "size": size,
                                "sha256": "", "hashed": False})
                continue
            digest = sha256_file(dest)
            hashed += 1
            result["sha256"][rel_key] = digest
            entries.append({"rel": rel_key, "kind": kind, "size": size,
                            "sha256": digest, "hashed": True})

        if result["model_present"]:
            verdict, reason, warning = "saved", "проект модели сохранён", ""
        elif execute:
            # Реальный прогон обязан оставить проект на диске. Если его нет — это
            # дефект сохранения тНавом: фиксируем ЯВНО (иначе «модели не сохраняются»
            # невозможно отличить от «модель не строилась»).
            verdict = "workflow_only"
            reason = (f"прогон execute, но в каталоге прогона нет файлов проекта "
                      f"(ожидался {expected.name} и каталог {expected.stem}.snf): "
                      f"тНав не сохранил проект по указанному пути — модель НЕ персистится")
            warning = reason
        else:
            verdict = "workflow_only"
            reason = ("dry-run: модель не создаётся, сохранено описание прогона "
                      "(план/шаги/отчёт/воркфлоу)")
            if result.get("stale_project_files"):
                reason += (f"; в каталоге прогона остались файлы проекта прошлого "
                           f"прогона ({result['stale_project_files']}) — не копируются")
            warning = ""
        result["warning"] = warning

        manifest = {
            "manifest_version": 1,
            "field": field,
            "run_id": str(run_id or ""),
            "run_key": str(run_key or run_id or ""),
            "caller": str(caller or "unknown"),
            "execute": bool(execute),
            "created_at": result["created_at"],
            "source_run_dir": str(run_dir),
            "target_dir": str(target),
            "models_dir": str(models_dir),
            "tnav": {"executable": str(tnav_executable or ""),
                     "version": str(tnav_version or "")},
            "files": entries,
            "totals": {"files": result["files"], "bytes": result["bytes"],
                       "hashed": hashed, "unhashed": result["files"] - hashed,
                       "max_hashed_files": cap},
            "model_present": result["model_present"],
            "stale_project_files": result.get("stale_project_files", 0),
            "expected_project": str(expected),
            "project_file_present": result["project_file_present"],
            "warning": warning,
            "retention": {"keep_last": _keep_last(cfg), "removed": [], "kept": 0},
            "branches": _branch_refs(branches),
            "verdict": verdict,
            "reason": reason,
            "extra": dict(extra or {}),
        }
        manifest_path = target / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2,
                                            default=str), encoding="utf-8")
        # Ретенция — ПОСЛЕ записи манифеста: иначе текущая модель ещё не считается
        # сохранённой и в кандидаты не попадает (проверено тестом).
        if result["model_present"]:
            retention = _apply_retention(cfg, target, field)
            if retention["removed"]:
                manifest["retention"] = retention
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2,
                                                    default=str), encoding="utf-8")
        else:
            retention = {"keep_last": _keep_last(cfg), "removed": [], "kept": 0}
        # Указатель на последнюю сохранённую модель: предсказуемая точка входа
        # для интерфейса и заказчика (не нужно угадывать имя каталога).
        try:
            (target.parent / LATEST_NAME).write_text(
                json.dumps({"field": field, "run_id": str(run_id or ""),
                            "run_key": str(run_key or run_id or ""),
                            "caller": str(caller or "unknown"),
                            "dir": str(target), "manifest": str(manifest_path),
                            "models_dir": str(models_dir),
                            "created_at": result["created_at"],
                            "model_present": result["model_present"]},
                           ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except OSError:
            pass

        result.update({"verdict": manifest["verdict"], "reason": manifest["reason"],
                       "dir": str(target), "manifest": str(manifest_path),
                       "retention": retention,
                       "hashed_files": hashed,
                       "unhashed_files": result["files"] - hashed})
        return result
    except Exception as exc:                       # noqa: BLE001 — не роняем прогон
        result["verdict"] = "error"
        result["reason"] = f"сохранение модели не удалось: {exc}"
        return result
