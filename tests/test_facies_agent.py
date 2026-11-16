"""Тесты фациального агента (E7): метод→функция из ДАННЫХ, дискретный куб, палитра,
пропорции по скважинам, геотела, согласованность с сеткой, триады.

Запуск:  python -X utf8 tests/test_facies_agent.py

Проверяется:
  * FaciesAgent (AG_FACIES) — наследник BaseAgent; `decide_facies` сохраняет прежний
    контракт (`enabled/method/n_facies/variogram/parameters/reason` — тесты 223);
  * КАРТА «метод → функция тНава» читается ИЗ ДАННЫХ (`ontology/facies_methods.yaml`):
    подмена данных во временном каталоге меняет выбранную функцию; функция, которой
    нет в шагах пайплайна, не исполняется (честный `enabled=false` + `unknown`);
  * «НЕИЗВЕСТНОЕ != ЛОЖЬ»: нет данных карты / нет метода → `unknown` с перечнем, а не
    молчаливое «прошло»; нет пропорций → `unknown`, а не нули;
  * ПРОПОРЦИИ ФАЦИЙ по скважинам: локальный расчёт по LAS с ЯВНОЙ пометкой источника
    («рассчитано локально: …», не результат тНава); готовое свидетельство этапа имеет
    приоритет;
  * ПАТЧИ параметров применяются только к кодам, реально присутствующим в шаблоне
    (иначе dry-run дал бы `render_warnings`);
  * ТРИАДЫ (правило 2) новых функций фаций: шаблон + правило + блок шага; рендер
    этапа 6 без предупреждений, имена объектов подставлены из данных;
  * отчёт `report.json`: `facies_policy` расширен (функция/спека метода/палитра/
    пропорции/согласованность с сеткой), шаги фаций отрендерены, `pending_template=0`.

Данные в тестах — обезличенные (нейтральные имена), домен поля не используется.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_PASS: list[str] = []
_FAIL: list[str] = []

# Триады (правило 2), за которые отвечает этап E7 (facies).
TRIADS = ("grid_property_interpolate_by_wells_log_sgs_multilayer_facies",
          "grid_property_facies_modeling", "grid_property_create_by_zones",
          "grid_property_create_by_values")
# ПОДТВЕРЖДЁННАЯ пробой функция шага фаций (куб FACIES создаёт сама, мануал 57.3.12).
FACIES_FUNCTION = "grid_property_interpolate_by_wells_log_sgs_multilayer_facies"
# Функции этапа 6/6.1, объявленные в проектном YAML (палитра + куб + геотела).
STAGE6_FUNCTIONS = ("create_object_template", FACIES_FUNCTION,
                    "object_template_mapping", "geobody_create_by_property")


def check(name: str, cond: bool, detail: str = "") -> None:
    (_PASS if cond else _FAIL).append(name)
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + ("" if cond else f"  <-- {detail}"))


# -- тестовые данные (нейтральные имена) -------------------------------------------
def _methods_data(method: str = "m_sis", function: str = "fn_facies",
                  creates_cube: bool = True) -> dict:
    """Данные карты методов во временном каталоге (обезличенные имена)."""
    return {
        "version": 1,
        "agent": "AG_TEST",
        "methods": {method: {"function": function, "creates_cube": creates_cube,
                             "interpolator": "kriging", "manual_pages": "1-2"}},
        "interpolators": ["kriging"],
        "patch_codes": {"interpolator_type": "interpolator", "range_main": "range_main"},
        "palette": {"name": "PAL", "type": "Discrete palette"},
        "geobody": {"function": "fn_geobody"},
        "placeholders": {"result_grid_property": '"__RESULT__"'},
        "proportions": {"source": "evidence", "min_wells": 1},
    }


def _ontology_dir(tmp: Path, data: dict | None) -> Path:
    """Каталог данных онтологии: с файлом карты методов или пустой."""
    root = Path(tmp) / "ontology"
    root.mkdir(parents=True, exist_ok=True)
    if data is not None:
        (root / "facies_methods.yaml").write_text(
            yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return root


class _StubCfg:
    """Мини-конфиг: точечный доступ к ключам + разрешение путей (для теста данных)."""

    def __init__(self, ontology_root: Path) -> None:
        self._root = Path(ontology_root)
        self.raw: dict = {}

    def get(self, dotted: str, default=None):
        return {"ontology.root": str(self._root)}.get(dotted, default)

    def path(self, dotted: str, default=None) -> Path:
        value = self.get(dotted, default)
        return Path(str(value)) if value else ROOT / "domain" / "templates"

    def resolve(self, value, base=None) -> Path:
        path = Path(str(value))
        return path if path.is_absolute() else ROOT / path


def _project(method: str = "m_sis", function: str = "fn_facies",
             *, extra_step: str = "") -> dict:
    """Проектный граф-заготовка: секция geostat + пайплайн с шагом фаций."""
    steps = [{"function": function,
              "replace": {'"__RESULT__"': '"CUBE"'},
              "objects": {"mesh": {"obj_name": "GRID", "obj_type": "Grid3d"},
                          "blocked_wells": {"obj_name": "BW", "obj_type": "BlockedWells"}}}]
    if extra_step:
        steps.append({"function": extra_step})
    return {
        "geostat": {"facies_method": method, "n_facies": 2,
                    "hole_range_m": 1000.0, "nugget": 0.2, "anisotropy": 0.5},
        "pipeline": [{"stage": "s6", "steps": steps}],
    }


def _real_project() -> dict:
    return yaml.safe_load((ROOT / "ontology_project" / "gerasimovskoe.yaml")
                          .read_text(encoding="utf-8"))


# -- 1. контракт агента и совместимость обёртки -------------------------------------
def test_agent_contract() -> None:
    from agents.base_agent import BaseAgent
    from agents.facies import FaciesAgent as Canonical
    from agents.facies_policy import FaciesAgent, decide_facies

    check("агент: FaciesAgent — наследник BaseAgent (канонический = в facies_policy)",
          issubclass(FaciesAgent, BaseAgent) and issubclass(Canonical, BaseAgent)
          and FaciesAgent is Canonical)
    check("агент: BDI-профиль AG_FACIES (идентификатор схемы)",
          FaciesAgent.agent_id == "AG_FACIES")

    project = _real_project()
    fd = decide_facies(project, {})
    check("агент: метод и число классов из данных проекта",
          fd["enabled"] is True and fd["n_facies"] == 3 and fd["method"] == "sis", str(fd)[:300])
    check("агент: вариограмма из данных проекта",
          fd["variogram"]["range_m"] == 3500.0 and fd["variogram"]["nugget"] == 0.15)
    check("агент: нет n_facies → стадия отключается (неизвестное != ложь)",
          decide_facies({"geostat": {}}, {})["enabled"] is False)
    check("агент: метаданные BDI-цикла сохранены (mode/coverage_report/plan)",
          {"mode", "coverage_report", "plan", "unknown"} <= set(fd), str(sorted(fd))[:200])


# -- 2. карта «метод → функция» — ИЗ ДАННЫХ ------------------------------------------
def test_method_map_from_data() -> None:
    from agents.facies import FaciesAgent

    with tempfile.TemporaryDirectory() as tmp:
        root = _ontology_dir(Path(tmp), _methods_data())
        agent = FaciesAgent(cfg=_StubCfg(root))
        out = agent.decide(_project("m_sis", "fn_facies"), {})
        check("данные: метод → функция выбрана по данным карты",
              out["grid_function"] == "fn_facies" and out["enabled"] is True,
              str(out)[:300])
        check("данные: спека метода (страницы мануала/признак создания куба) в отчёте",
              out["method_spec"].get("manual_pages") == "1-2"
              and out["method_spec"].get("creates_cube") is True, str(out["method_spec"]))
        check("данные: имена куба/сетки/blocked well прочитаны из шага (данные)",
              out["cube"] == "CUBE" and out["mesh"] == "GRID"
              and out["blocked_wells"] == "BW", str(out)[:300])

        other = agent.decide(_project("m_sis", "fn_other"), {})
        check("данные: функция карты не объявлена в пайплайне → не исполняется + unknown",
              other["enabled"] is False
              and any("не объявлена" in u for u in other["unknown"]), str(other["unknown"]))

        missing = agent.decide(_project("m_absent", "fn_facies"), {})
        check("данные: метод не описан в карте → unknown, функция не выдумана",
              missing["enabled"] is False and bool(missing["unknown"])
              and missing["grid_function"] == "", str(missing)[:300])


# -- 3. нет данных карты → честный unknown (правило 6) -------------------------------
def test_unknown_without_data() -> None:
    from agents.facies import FaciesAgent

    with tempfile.TemporaryDirectory() as tmp:
        root = _ontology_dir(Path(tmp), None)
        out = FaciesAgent(cfg=_StubCfg(root)).decide(_project(), {})
        check("правило 6: без данных карты методов — unknown, а не «прошло»",
              out["enabled"] is False and bool(out["unknown"]), str(out)[:300])
        check("правило 6: пропорции без данных не подменяются нулями",
              out["proportions"] == {} and out["proportions_source"] == "",
              str({"props": out["proportions"], "src": out["proportions_source"]}))

    # метод не задан, но в пайплайне ровно одна функция из карты → выбор с оговоркой
    with tempfile.TemporaryDirectory() as tmp:
        data = _methods_data()
        root = _ontology_dir(Path(tmp), data)
        project = _project("", "fn_facies")
        project["geostat"].pop("facies_method")
        out = FaciesAgent(cfg=_StubCfg(root)).decide(project, {})
        check("правило 6: метод не задан → функция объявленная, но с unknown-оговоркой",
              out["grid_function"] == "fn_facies"
              and any("не задан" in u for u in out["unknown"]), str(out["unknown"]))


# -- 4. пропорции фаций по скважинам --------------------------------------------------
def test_proportions() -> None:
    from agents.facies import FaciesAgent

    out = FaciesAgent().decide(_real_project(), {})
    props = out["proportions"]
    check("пропорции: посчитаны по LAS проекта (локальный расчёт)",
          bool(props) and out["proportion_wells"] > 0
          and abs(sum(float(v) for v in props.values()) - 1.0) < 0.01,
          str({"props": props, "wells": out["proportion_wells"]}))
    check("пропорции: источник помечен как ЛОКАЛЬНЫЙ расчёт (не тНав)",
          "локально" in out["proportions_source"], out["proportions_source"])
    check("пропорции: коды фаций не выдуманы (несколько кодов из данных)",
          len(out["classes_from_data"]) >= 2, str(out["classes_from_data"]))

    ready = FaciesAgent().decide(_real_project(), {"facies_proportions": {"1": 0.7, "2": 0.3}})
    check("пропорции: готовое свидетельство этапа имеет приоритет",
          ready["proportions"] == {"1": 0.7, "2": 0.3}
          and ready["proportions_source"] == "свидетельство этапа", str(ready)[:300])


# -- 5. палитра и патчи параметров ----------------------------------------------------
def test_palette_and_patches() -> None:
    from agents.facies import FaciesAgent

    project = _real_project()
    out = FaciesAgent().decide(project, {})
    palette_required = out["palette"]["required"]
    check("палитра: политика дискретности — из данных (creates_cube функции)",
          palette_required is False, str(out["palette"]))
    check("палитра: имя/тип/папка/тип объекта берутся из данных карты",
          {"name", "type", "folder", "object_type"} <= set(out["palette"])
          and out["palette"]["folder"] != "", str(out["palette"]))

    with tempfile.TemporaryDirectory() as tmp:
        root = _ontology_dir(Path(tmp), _methods_data(creates_cube=False))
        out2 = FaciesAgent(cfg=_StubCfg(root)).decide(_project(), {})
        check("палитра: функция БЕЗ создания куба → требование предсозданного куба + unknown",
              out2["palette"]["required"] is True
              and any("дискретный куб" in u for u in out2["unknown"]), str(out2["unknown"]))

    patches = (out.get("parameters") or {}).get(FACIES_FUNCTION) or {}
    template = (ROOT / "domain" / "templates" / f"{FACIES_FUNCTION}.txt").read_text(
        encoding="utf-8")
    check("патчи: вариограмма политики (range/nugget) применяется к подтверждённому шаблону",
          patches.get("range_main") == 3500.0
          and patches.get("range_vertical") == 1750.0
          and patches.get("nugget_effect") == 0.15, str(patches))
    check("патчи: каждый код патча реально есть в шаблоне (нет render_warnings)",
          all(f"{code}=" in template for code in patches), str(sorted(patches)))
    check("патчи: нет unknown о неприменённых параметрах шаблона",
          not any("шаблон" in u and "патч" in u for u in out["unknown"]),
          str(out["unknown"]))


# -- 6. согласованность с сеткой ------------------------------------------------------
def test_grid_consistency() -> None:
    from agents.facies import FaciesAgent

    ev = {"grid_policy": {"step": {"step_x": 5000, "step_y": 5000}}}
    out = FaciesAgent().decide(_real_project(), ev)
    check("сетка: радиус корреляции < шага сетки → замечание (issue)",
          any("шага сетки" in i for i in out["grid_check"]["issues"]),
          str(out["grid_check"]))
    check("сетка: число классов против кодов литологии в данных — замечание",
          any("не совпадает" in i for i in out["grid_check"]["issues"]),
          str(out["grid_check"]))
    ok = FaciesAgent().decide(_real_project(), {"grid_policy": {"step": {"step_x": 50}}})
    check("сетка: при корректных данных согласованность подтверждается",
          ok["grid_check"]["cell_m"] == 50
          and not any("шага сетки" in i for i in ok["grid_check"]["issues"]),
          str(ok["grid_check"]))


# -- 7. триады (правило 2) и рендер этапа 6 -------------------------------------------
def test_triads_and_render() -> None:
    from core.config import load_config
    from core.coordinator import Coordinator

    for fn in TRIADS:
        tpl = ROOT / "domain" / "templates" / f"{fn}.txt"
        rdf = ROOT / "domain" / "ontology_rules" / f"{fn}.rdf"
        check(f"триада {fn}: шаблон и правило на месте",
              tpl.is_file() and tpl.stat().st_size > 20
              and rdf.is_file() and fn in rdf.read_text(encoding="utf-8"),
              str(tpl))

    project = _real_project()
    stage6 = next(s for s in project["pipeline"] if str(s.get("stage", "")).startswith("6."))
    declared = {st.get("function") for st in stage6.get("steps") or []}
    check("триада: этап 6 объявляет палитру, куб фаций и привязку шаблона",
          {"create_object_template", FACIES_FUNCTION,
           "object_template_mapping"} <= declared, str(sorted(declared)))
    cube_step = next(st for st in stage6["steps"]
                     if st.get("function") == FACIES_FUNCTION)
    check("триада: имена объектов куба переданы ИЗ ДАННЫХ (objects: mesh/result/well_log)",
          {"mesh", "result_grid_property", "well_log"} <= set(cube_step.get("objects") or {}),
          str(cube_step.get("objects")))

    coord = Coordinator(load_config())
    rules = coord.function_rules()
    rule_map = {n: rules.read(n) for n in rules.all_names()}
    nodes = coord.assembler("Герасимовское").node_genes()
    by_fn = {f.function: f for n in nodes for f in n.functions}
    check("триада: функции этапа 6/6.1 попали в гены пайплайна",
          all(fn in by_fn for fn in STAGE6_FUNCTIONS),
          str([fn for fn in STAGE6_FUNCTIONS if fn not in by_fn]))
    check("триада: у всех функций этапа 6/6.1 есть правило (не pending_template)",
          all(rule_map.get(fn) is not None for fn in STAGE6_FUNCTIONS),
          str([fn for fn in STAGE6_FUNCTIONS if rule_map.get(fn) is None]))

    builder = coord.workflow_builder()
    # Патчи политики применяются к гену ТАК ЖЕ, как в прогоне (`_variant_gene`): иначе
    # проверка «вариограмма попала в вызов» проверяла бы шаблон, а не поведение агента.
    from agents.facies import decide_facies

    facies_patches = (decide_facies(project, {}) or {}).get("parameters") or {}
    index = 1
    blocks: list[str] = []
    for fn in STAGE6_FUNCTIONS:
        gene = coord._variant_gene(by_fn[fn], rule_map[fn], facies_patches)
        block, index = builder.render_block(rule_map[fn], gene, index)
        blocks.append(block)
    rendered = "\n\n".join(blocks)
    check("триада: рендер этапа 6 без предупреждений builder",
          builder.warnings == [], str(builder.warnings))
    check("триада: в рендере нет незаполненных плейсхолдеров имён",
          "__MESH__" not in rendered and "__RESULT_PROPERTY__" not in rendered
          and '"main_grid"' in rendered and '"FACIES"' in rendered, rendered[:200])
    check("куб FACIES: подтверждённая функция вызывает создание свойства по логу LIT",
          FACIES_FUNCTION in rendered
          and 'well_log=typed_object_name (obj_name="LIT"' in rendered,
          rendered[:300])
    check("куб FACIES: вариограмма политики (range/nugget) отрендерена в вызове",
          "range_main=3500.0" in rendered and "nugget_effect=0.15" in rendered
          and "range_vertical=1750.0" in rendered, rendered[300:700])
    check("палитра: привязка дискретного шаблона к свойству сетки отрендерена",
          '"3D-Grids"' in rendered and '"Property"' in rendered
          and "use_grid=True" in rendered, rendered[-400:])
    # СИНТАКСИС: собранный этап обязан быть валидным Python (иначе тНав отвечает
    # «Could not parse python code: SyntaxError» и этап падает целиком — ловится
    # только компиляцией/пробой, не dry-run-ом).
    stage_file = builder.assemble(blocks)
    try:
        compile(stage_file, "<stage6>", "exec")
        syntax_ok, syntax_err = True, ""
    except SyntaxError as exc:
        syntax_ok, syntax_err = False, str(exc)
    check("триада: собранный этап 6 — валидный Python (тНав не упадёт на разборе)",
          syntax_ok, syntax_err)


# -- 8. отчётные ключи dry-run --------------------------------------------------------
def test_report_keys_from_dry_run() -> None:
    from core.config import load_config
    from core.coordinator import Coordinator

    coord = Coordinator(load_config(), dry_run=True)
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / "run"
        report = coord.run("Герасимовское", run_dir=run_dir, execute=False)
        progress = json.loads((run_dir / "agents" / "progress.json")
                              .read_text(encoding="utf-8"))

    steps = report.get("steps") or {}
    skipped = (steps.get("counts") or {}).get("skipped_by_policy", 0)
    check("отчёт: dry-run без ошибок и без pending_template",
          steps.get("error") == 0 and steps.get("pending_template") == 0
          and report.get("render_warnings") == [],
          str({"steps": steps, "render_warnings": report.get("render_warnings")}))
    check("отчёт: done = total − skipped_by_policy",
          steps.get("done") == steps.get("total", 0) - skipped, str(steps))

    facies = report.get("facies_policy") or {}
    check("отчёт: facies_policy расширен (функция, спека метода, палитра, пропорции, сетка)",
          {"enabled", "method", "n_facies", "variogram", "grid_function", "method_spec",
           "palette", "proportions", "grid_check", "unknown"} <= set(facies),
          str(sorted(facies)))
    check("отчёт: функция фаций выбрана по данным и совпадает с объявленной в этапе 6",
          facies.get("grid_function") == FACIES_FUNCTION
          and facies.get("declared_in_pipeline") is True, str(facies.get("grid_function")))
    check("отчёт: пропорции фаций посчитаны локально с явной пометкой источника",
          bool(facies.get("proportions")) and "локально" in str(facies.get("proportions_source")),
          str(facies.get("proportions_source")))

    # Шаг фаций может быть ПРОПУЩЕН по данным, если его сигнатура не подтверждена
    # пробой на живой лицензии (workflow.unconfirmed_steps; F-21). Тогда он обязан
    # присутствовать в шине со статусом skipped_by_policy И НЕПУСТОЙ причиной —
    # «не подтверждено» != «выполнено», но и не тихий пропуск.
    by_fn = {s.get("function"): s for s in (progress.get("steps") or {}).get("steps") or []}
    missing = [fn for fn in STAGE6_FUNCTIONS if fn not in by_fn]
    bad = [fn for fn in STAGE6_FUNCTIONS
           if fn in by_fn and by_fn[fn].get("status") not in ("done", "skipped_by_policy")]
    unexplained = [fn for fn in STAGE6_FUNCTIONS
                   if fn in by_fn and by_fn[fn].get("status") == "skipped_by_policy"
                   and not str(by_fn[fn].get("message") or "").strip()]
    check("отчёт: шаги этапа 6/6.1 зарегистрированы в шине (done либо skipped с причиной)",
          not missing and not bad and not unexplained,
          str({"нет_в_шине": missing, "недопустимый_статус": bad,
               "без_причины": unexplained}))


def main() -> int:
    for fn in (test_agent_contract, test_method_map_from_data, test_unknown_without_data,
               test_proportions, test_palette_and_patches, test_grid_consistency,
               test_triads_and_render, test_report_keys_from_dry_run):
        print(f"\n--- {fn.__name__} ---")
        fn()
    print("\n=== ИТОГ ===")
    print(f"пройдено: {len(_PASS)} | провалено: {len(_FAIL)}")
    if _FAIL:
        print("Проваленные: " + ", ".join(_FAIL))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
