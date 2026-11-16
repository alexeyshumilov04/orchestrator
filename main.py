"""orchestrator-v5 — единая точка входа.

Команды:
    preflight   — проверить тНав (путь/версия/API) и доступность онтологии v4;
    plan        — собрать ген-план из онтологии (без запуска);
    run         — отрендерить tNavigator-воркфлоу, прогнать (dry-run) и сделать QA/QC.

Запуск:  python main.py plan --field Герасимовское
         python main.py run  --field Герасимовское [--execute]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config import load_config            # noqa: E402
from core.coordinator import Coordinator       # noqa: E402
import wire                                    # noqa: E402  (композиционный корень: регистрирует staged)


def _print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def cmd_preflight(coord: Coordinator) -> int:
    info = coord.tnav().preflight()
    ont = coord.ontology.stats()
    _print({"tnavigator": info, "ontology": ont})
    ok = info.get("present") and ont.get("operations", 0) > 0
    print(f"\npreflight: {'OK' if ok else 'ЕСТЬ ЗАМЕЧАНИЯ'}")
    return 0 if ok else 1


def cmd_plan(coord: Coordinator, field: str | None) -> int:
    _print(coord.plan(field))
    return 0


def cmd_run(coord: Coordinator, field: str | None, execute: bool,
            ensemble_size: int = 0) -> int:
    """Прогон с ПРОГРЕССОМ в консоль: старт, лог этапов, ненулевой код при сбое тНава."""
    field_name = field or str(coord.cfg.get("project.default_field", "") or "")
    mode = "РЕАЛЬНЫЙ прогон тНава" if execute else "dry-run (тНав не запускается)"
    print(f"старт прогона: поле={field_name}, режим={mode}"
          + (f", ансамбль={ensemble_size}" if ensemble_size else ""), flush=True)

    def on_log(text: str) -> None:
        print(f"  · {text}", flush=True)

    def on_event(ev) -> None:
        data = ev.to_dict() if hasattr(ev, "to_dict") else dict(ev or {})
        if str(data.get("status")) in ("done", "error", "pending_template"):
            print(f"  [{data.get('index', '?')}] {data.get('stage', '')}: "
                  f"{data.get('function', '')} — {data.get('status')}", flush=True)

    report = coord.run(field, execute=execute, ensemble_size=ensemble_size,
                       on_log=on_log, on_event=on_event)
    _print(report)
    verdict = report["critic"]["verdict"]
    tnav = report.get("tnav") or {}
    print(f"\nпрогон завершён: вердикт QA/QC = {verdict}")
    if not tnav.get("ok", True):
        print(f"ОШИБКА тНава: {tnav.get('error') or tnav.get('returncode') or 'см. отчёт'}")
        return 1
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Поднять веб-сервис FastAPI (api:app) через uvicorn."""
    try:
        import uvicorn
    except ImportError:
        print("Нужен uvicorn: pip install 'uvicorn[standard]' fastapi")
        return 2
    print(f"orchestrator-v5: http://{args.host}:{args.port}  (Ctrl+C — остановить)")
    uvicorn.run("api:app", host=args.host, port=args.port, reload=False)
    return 0


def _resolve_template(explicit, graph_dir: Path, field: str) -> Path:
    """Граф-шаблон: явный путь → файл по имени поля → первый доступный в папке."""
    if explicit is not None:
        return Path(explicit)
    for name in (f"{field}.yaml", f"{field}.yml", f"{field}.json"):
        cand = graph_dir / name
        if cand.is_file():
            return cand
    found = sorted([*graph_dir.glob("*.yaml"), *graph_dir.glob("*.yml"),
                    *graph_dir.glob("*.json")])
    return found[0] if found else graph_dir / f"{field}.yaml"


def cmd_graph(args: argparse.Namespace) -> int:
    """B8: сгенерировать ЧЕРНОВИК проектного графа по данным набора."""
    import yaml
    from core.graph_generator import build_draft

    cfg = load_config(args.config)
    field = args.field
    data_root = (Path(args.data) if args.data
                 else cfg.path("data.root", "data") / field / "Source")
    graph_dir = cfg.path("project.graph_dir", "ontology_project")
    default_field = str(cfg.get("project.default_field", field) or field)
    template_path = _resolve_template(args.template, graph_dir, default_field)
    template: dict = {}
    if template_path.is_file():
        template = yaml.safe_load(template_path.read_text(encoding="utf-8")) or {}
    draft = build_draft(field, data_root, template)
    if getattr(args, "pipeline_from_ontology", False):
        # Фаза B: перечень шагов строится ИЗ КАТАЛОГОВ онтологии, а полевой шаблон
        # остаётся источником объектов/параметров (см. core/project_generator).
        from core.coordinator import Coordinator
        from core.project_generator import derive_pipeline, merge_with_template

        coord = Coordinator(cfg)
        derived = derive_pipeline(coord.ontology, rules_dir=cfg.path(
            "workflow.rules_dir", "domain/ontology_rules"), templates_dir=cfg.path(
            "workflow.templates_dir", "domain/templates"))
        draft.graph["pipeline"] = merge_with_template(derived, draft.graph)
        draft.auto["pipeline_from_ontology"] = len(derived)
    fmt = str(args.format or "yaml").lower()
    text = draft.to_json() if fmt == "json" else draft.to_yaml()
    out = (Path(args.out) if args.out
           else graph_dir / f"{field}.{'json' if fmt == 'json' else 'yaml'}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(json.dumps({"out": str(out), "data_root": str(data_root),
                      "template": str(template_path), "auto": draft.auto,
                      "todo": draft.todo}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="orchestrator-v5 ГГДМ")
    parser.add_argument("--config", default=None, help="путь к config.yaml")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("preflight", help="проверка тНава и онтологии")

    p_plan = sub.add_parser("plan", help="план из онтологии (без запуска)")
    p_plan.add_argument("--field", default=None)

    p_run = sub.add_parser("run", help="рендер воркфлоу + прогон + QA/QC")
    p_run.add_argument("--field", default=None)
    p_run.add_argument("--execute", action="store_true",
                       help="реально запустить тНав (иначе dry-run)")
    p_run.add_argument("--ensemble-size", type=int, default=None,
                       help="число реализаций ансамбля (по умолчанию — execution.ensemble_size)")

    p_graph = sub.add_parser("graph", help="черновик проектного графа по данным (B8)")
    p_graph.add_argument("--field", required=True)
    p_graph.add_argument("--data", default=None, help="папка данных (по умолчанию data/<поле>/Source)")
    p_graph.add_argument("--template", default=None, help="граф-шаблон (по умолчанию — граф поля по умолчанию)")
    p_graph.add_argument("--format", default="yaml", choices=("yaml", "json"))
    p_graph.add_argument("--out", default=None, help="выходной файл (по умолчанию ontology_project/<поле>.<fmt>)")
    p_graph.add_argument("--pipeline-from-ontology", action="store_true",
                         help="Фаза B: перечень шагов вывести ИЗ каталогов онтологии "
                              "(полевой шаблон — только объекты/параметры)")

    p_serve = sub.add_parser("serve", help="поднять веб-сервис (FastAPI + SPA)")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8770)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return 2

    if args.cmd == "serve":
        return cmd_serve(args)
    if args.cmd == "graph":
        return cmd_graph(args)

    cfg = load_config(args.config)
    coord = Coordinator(cfg)

    if args.cmd == "preflight":
        return cmd_preflight(coord)
    if args.cmd == "plan":
        return cmd_plan(coord, args.field)
    if args.cmd == "run":
        # размер ансамбля: CLI > execution.ensemble_size (иначе берутся ВСЕ вариации из проекта)
        ens = args.ensemble_size
        if ens is None:
            ens = int(cfg.get("execution.ensemble_size", 0) or 0)
        return cmd_run(coord, args.field, args.execute, ens)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
