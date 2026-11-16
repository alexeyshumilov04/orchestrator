#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Отчёт по петрофизике/фациям своими модулями (БЕЗ запуска тНава).

Что делает (всё — по ДАННЫМ, правило 1; нет данных → unknown, правило 6):

  1. собирает скважинные последовательности кодов фаций из LAS поля
     (мнемоника ищется по кандидатам `columns.lithotype` из онтологии);
  2. считает доли классов, net-to-gross (если передана карта ролей), связность
     и число тел — модуль `domain/facies_model.py`;
  3. если передан CSV керна (`--core`) — подгоняет k = f(φ) ОТДЕЛЬНО по
     литотипам со статусом источника и выводит cut-off по меченому керну —
     модуль `domain/petrophysics_fit.py`;
  4. печатает отчёт и (опционально) пишет JSON: `--out <путь>`.

Примеры:
  python tools/petrofacies_report.py --field Герасимовское
  python tools/petrofacies_report.py --field Герасимовское --core data/core.csv
  python tools/petrofacies_report.py --project ontology_project/gerasimovskoe.yaml \\
      --logs data/Герасимовское/Source/LAS --roles "1=reservoir,2=barrier"

ВАЖНО: карта ролей «код фации → роль» — ДАННЫЕ поля; без неё NTG = unknown.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_config                     # noqa: E402
from domain import facies_model as fm                   # noqa: E402
from domain import petrofacies_data as pdata            # noqa: E402
from domain import petrophysics_fit as pf               # noqa: E402
from domain.geostat import read_las                     # noqa: E402


def project_graph(cfg, field: str, project_path: str | None) -> tuple[Path | None, dict]:
    """Граф поля: явный путь либо поиск по значению `field` в ontology_project."""
    if project_path:
        path = Path(project_path)
        return path, pdata.read_yaml(path)
    graph_dir = cfg.path("project.graph_dir", "ontology_project")
    for candidate in sorted(graph_dir.glob("*.y*ml")):
        graph = pdata.read_yaml(candidate)
        if str(graph.get("field") or "").strip() == str(field).strip():
            return candidate, graph
    return None, {}


def logs_dir(cfg, graph: dict, override: str | None) -> Path | None:
    """Каталог LAS: аргумент → `dataset_root`+`inputs.logs` графа поля."""
    if override:
        return Path(override)
    root = graph.get("dataset_root")
    inputs = graph.get("inputs") if isinstance(graph.get("inputs"), dict) else {}
    logs = inputs.get("logs") if isinstance(inputs, dict) else None
    if not root or not logs:
        return None
    return cfg.resolve(str(root)) / str(logs)


def facies_series(path: Path, rules) -> list[int] | None:
    """Последовательность кодов фаций из LAS по кандидатам мнемоник онтологии."""
    las = read_las(path)
    mnems = [str(item).upper() for item in (las.get("mnems") or [])]
    index: int | None = None
    for candidate in pdata.column_candidates(rules, "lithotype"):
        if candidate.upper() in mnems:
            index = mnems.index(candidate.upper())
            break
    if index is None:
        return None
    null = las.get("null")
    out: list[int] = []
    for row in las.get("data") or []:
        if index >= len(row):
            continue
        value = row[index]
        if abs(value) > 1e28 or (null is not None and abs(value - null) < 1e-3):
            continue
        out.append(int(round(value)))
    return out or None


def collect_well_codes(directory: Path, rules, limit: int) -> tuple[dict, int]:
    """{скважина: коды фаций} по LAS каталога + число прочитанных файлов."""
    well_codes: dict[str, list[int]] = {}
    files = sorted(directory.glob("*.las"))
    if limit > 0:
        files = files[:limit]
    for path in files:
        series = facies_series(path, rules)
        if series:
            well_codes[path.stem] = series
    return well_codes, len(files)


def read_core(path: Path) -> list[dict]:
    """Таблица керна (CSV, разделитель определяется) → список словарей."""
    text = path.read_text(encoding="utf-8", errors="replace")
    sample = text[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    return [dict(row) for row in csv.DictReader(text.splitlines(), delimiter=delimiter)]


def parse_roles(raw: str | None) -> dict:
    """Карта ролей из CLI (`код=роль,код=роль`) — данные поля, не код."""
    roles: dict = {}
    for item in (raw or "").split(","):
        if "=" not in item:
            continue
        code, role = item.split("=", 1)
        if code.strip():
            roles[code.strip()] = role.strip()
    return roles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--field", default="", help="имя поля (поиск в project.graph_dir)")
    parser.add_argument("--project", default="", help="путь к YAML проектного графа")
    parser.add_argument("--logs", default="", help="каталог LAS (иначе из графа поля)")
    parser.add_argument("--core", default="", help="CSV керна (пары φ/k, литотип)")
    parser.add_argument("--roles", default="", help="карта ролей: код=роль,код=роль")
    parser.add_argument("--template", default="", help="шаблон функции тНава (для патча)")
    parser.add_argument("--limit", type=int, default=0, help="максимум LAS-файлов")
    parser.add_argument("--out", default="", help="сохранить отчёт в JSON")
    args = parser.parse_args()

    cfg = load_config()
    rules = pdata.load_rules(cfg)
    report: dict = {"rules_sources": pdata.loaded_sources(rules),
                    "rules_missing": pdata.missing_sources(rules),
                    "status": "unknown", "unknown": []}
    print(f"онтология: {', '.join(pdata.loaded_sources(rules)) or 'НЕ ПРОЧИТАНА'}")

    graph_path, graph = project_graph(cfg, args.field, args.project)
    directory = logs_dir(cfg, graph, args.logs) if (graph or args.logs) else None
    if directory and directory.is_dir():
        well_codes, files = collect_well_codes(directory, rules, args.limit)
        print(f"LAS: {directory} — файлов {files}, со кодами фаций {len(well_codes)}")
        summary = fm.aggregate_facies(well_codes=well_codes, roles=parse_roles(args.roles),
                                      rules=rules)
        report["facies"] = summary
        report["logs_dir"] = str(directory)
        _print_facies(summary)
        if args.template or args.roles:
            template = Path(args.template).read_text(encoding="utf-8") \
                if args.template and Path(args.template).is_file() else None
            if not summary.get("proportions"):
                print("параметры шага фаций: долей нет — патч не строится")
            else:
                patch, unknown = fm.facies_step_parameters(summary, rules,
                                                           template_text=template)
                report["facies_step_parameters"] = {"patch": patch, "unknown": unknown}
                print(f"параметры шага фаций: {patch or '—'}")
                for item in unknown:
                    print(f"  unknown: {item}")
    else:
        report["unknown"].append("каталог LAS не найден — фации не считались "
                                 "(неизвестное != ложь)")
        print("фации: каталог LAS не найден — агрегаты не считаются (unknown)")

    if args.core:
        core_path = Path(args.core)
        if core_path.is_file():
            rows = read_core(core_path)
            fit = pf.fit_from_rows(rows, rules)
            report["petrophysics_fit"] = fit
            report["core"] = str(core_path)
            _print_fit(fit)
            columns = {str(key).lower() for key in rows[0]} if rows else set()
            has_labels = any(candidate.lower() in columns for candidate in
                             pdata.column_candidates(rules, "reservoir_label"))
            if has_labels:
                cut = pf.cutoff_from_labelled_core(rows, rules)
                report["cutoff"] = cut
                print(f"cut-off: {cut.get('value')} ({cut.get('status')}) — "
                      f"{cut.get('reason')}")
            else:
                report["unknown"].append(
                    "в таблице керна нет колонки роли «коллектор/нет» — cut-off "
                    "не выводится (unknown, не константа)")
                print("cut-off: меток коллектора нет — порог не выводится (unknown)")
        else:
            report["unknown"].append(f"файл керна не найден: {args.core}")
            print(f"керн: файл не найден ({args.core}) — подгонка не считалась")

    if report.get("facies", {}).get("status") == "ok" or report.get("petrophysics_fit"):
        report["status"] = "ok"
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        print(f"отчёт записан: {target}")
    return 0


def _print_facies(summary: dict) -> None:
    print(f"фации: статус {summary.get('status')}, классов {len(summary.get('classes') or [])}")
    for item in (summary.get("classes") or [])[:12]:
        body = "" if item.get("bodies") is None else f", тел {item['bodies']}"
        share = item.get("proportion")
        share_text = "—" if share is None else format(share, ".3f")
        role = str(item.get("role") or "")
        role_text = "" if not role else ", роль " + role
        print(f"  код {item.get('code')}: доля {share_text}{body}{role_text}")
    ntg = summary.get("net_to_gross")
    ntg_text = "unknown" if ntg is None else format(ntg, ".3f")
    wells = summary.get("wells") or 0
    wells_text = "" if not wells else f", скважин {wells}"
    print(f"  net-to-gross: {ntg_text}{wells_text}")
    conn = summary.get("connectivity") or {}
    if conn:
        bodies = conn.get("bodies_total")
        bodies_text = "" if bodies is None else f", тел всего {bodies}"
        print(f"  связность: {conn.get('status')}{bodies_text}")
    for item in summary.get("unknown") or []:
        print(f"  unknown: {item}")


def _print_fit(fit: dict) -> None:
    print(f"керн: статус {fit.get('status')}, пар {fit.get('n_pairs_total')}, "
          f"порог достаточности {fit.get('min_pairs')}")
    for item in fit.get("fits") or []:
        coef = "—" if item.get("slope") is None else \
            f"a={item['slope']:.4f}, b={item['intercept']:.4f}"
        r2 = "—" if item.get("r2") is None else format(item["r2"], ".3f")
        print(f"  литотип {item.get('lithotype')}: {item.get('status')}, "
              f"источник {item.get('source')}, n={item.get('n_pairs')}, r2={r2}, {coef}")
    for item in fit.get("issues") or []:
        print(f"  замечание: {item}")


if __name__ == "__main__":
    raise SystemExit(main())
