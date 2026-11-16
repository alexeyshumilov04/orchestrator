"""Фаза B генератора спеки: `pipeline` ВЫВОДИТСЯ из каталогов онтологии.

Раньше этапы/шаги/функции пайплайна целиком клонировались из полевого шаблона
(константы). Здесь скелет строится из ДАННЫХ онтологии:

  * `ontology/tnavigator_functions.csv` — какие функции тНава относятся к каким
    стадиям (`stage`, `function`, `status`);
  * `domain/ontology_rules/*.rdf` (+ `domain/templates/*.txt`) — фильтр
    «рендеропригодности»: функция попадает в пайплайн только если для неё есть
    правило и шаблон (иначе рендер воркфлоу упадёт);
  * полевой шаблон — источник ОБЪЕКТОВ/ПАРАМЕТРОВ (семантика поля), при этом
    сам список шагов больше не является константой.

Функция чистая (никакого тНава) — пригодна для юнит-тестов.
"""
from __future__ import annotations

from pathlib import Path


def renderable_functions(rules_dir: Path, templates_dir: Path) -> set[str]:
    """Функции, которые мы умеем рендерить: есть И правило, И шаблон."""
    rules = {p.stem for p in Path(rules_dir).glob("*.rdf") if p.stem != "ontology"}
    tpls = {p.stem for p in Path(templates_dir).glob("*.txt") if p.stem != "template_wf"}
    return rules & tpls


def derive_pipeline(ontology, *, rules_dir: Path, templates_dir: Path,
                    functions: list[dict] | None = None) -> list[dict]:
    """Скелет пайплайна (этапы → шаги → функции) из КАТАЛОГОВ онтологии.

    `functions` — приоритетный (явный) список функций поля; если он задан, служит
    фильтром/порядком. Возвращает список `{"stage": label, "steps": [{"function": fn}]}`.
    """
    allowed = renderable_functions(rules_dir, templates_dir)
    explicit = [f for f in (functions or []) if f in allowed]
    by_stage: dict[str, list[str]] = {}
    for row in ontology.tnav_functions():
        fn = str(getattr(row, "function", "") or "").strip()
        if not fn or fn not in allowed:
            continue
        stage = str(getattr(row, "stage", "") or "—").strip() or "—"
        seen = by_stage.setdefault(stage, [])
        if fn not in seen:
            seen.append(fn)
    stages = sorted(by_stage.items())
    out: list[dict] = []
    for i, (stage, fns) in enumerate(stages, start=1):
        if explicit:
            fns = [fn for fn in fns if fn in explicit]
            if not fns:
                continue
        out.append({"stage": f"этап {i} [{stage}]",
                    "steps": [{"function": fn} for fn in fns]})
    return out


def template_functions(template_graph: dict) -> list[str]:
    """Функции в ПОРЯДКЕ следования по шаблону (проверенный прогонами порядок этапов)."""
    out: list[str] = []
    for stage in (template_graph or {}).get("pipeline") or []:
        for step in stage.get("steps") or []:
            fn = str(step.get("function") or "").strip()
            if fn and fn not in out:
                out.append(fn)
    return out


def audit_pipeline(ontology, template_graph, *, rules_dir: Path,
                   templates_dir: Path) -> dict:
    """P2.4: состав пайплайна сверяется с КАТАЛОГОМ онтологии (данные, не код).

    Порядок этапов/шагов НЕ переписывается: он проверен прогонами (стадии 0–10
    зелёные) и является знанием, а не выводом каталога. Из онтологии берётся
    ФАКТ существования функции и её стадия:

    * `verified`   — шаги шаблона, подтверждённые каталогом `tnavigator_functions`;
    * `unverified` — шаги шаблона, которых в каталоге нет (находка: устарели/опечатка);
    * `candidates` — рендеропригодные функции каталога, которых нет в шаблоне
                     (возможные пропуски пайплайна).
    """
    allowed = renderable_functions(rules_dir, templates_dir)
    tpl = template_functions(template_graph)
    catalog = {str(getattr(row, "function", "") or "").strip()
               for row in ontology.tnav_functions()}
    return {"stages": len((template_graph or {}).get("pipeline") or []),
            "verified": [fn for fn in tpl if fn in catalog],
            "unverified": [fn for fn in tpl if fn not in catalog],
            "candidates": sorted(fn for fn in allowed if fn not in tpl),
            "source": "ontology catalog (состав) + template (порядок)"}


def merge_with_template(derived: list[dict], template: dict) -> list[dict]:
    """Скелет из онтологии + ОБЪЕКТЫ/ПАРАМЕТРЫ полевого шаблона по функции.

    Полевой шаблон остаётся источником семантики (какие объекты подставлять), но
    перечень шагов берётся из вывода онтологии (а не из константы файла).
    """
    objects: dict[str, dict] = {}
    params: dict[str, dict] = {}
    for stage in (template or {}).get("pipeline") or []:
        for step in stage.get("steps") or []:
            fn = step.get("function")
            if not fn:
                continue
            if step.get("objects"):
                objects.setdefault(fn, {}).update(step["objects"])
            if step.get("parameters"):
                params.setdefault(fn, {}).update(step["parameters"])
    for stage in (template or {}).get("functions") or {}:
        pass
    for stage in derived:
        for step in stage["steps"]:
            fn = step["function"]
            if fn in objects:
                step["objects"] = dict(objects[fn])
            if fn in params:
                step["parameters"] = dict(params[fn])
    return derived
