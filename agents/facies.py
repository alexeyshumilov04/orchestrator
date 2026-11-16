"""Агент фаций (AG_FACIES): дискретный куб, палитра, пропорции, геотела, карты.

Агент отвечает на вопрос «как построить куб фаций» по ДАННЫМ проекта, данным
онтологии и свидетельствам этапа:

  * МЕТОД (`geostat.facies_method`) → ФУНКЦИЯ тНава: карта «метод → функция» живёт
    в ДАННЫХ — `ontology/facies_methods.yaml` (источники и страницы мануала 26.2 —
    в шапке файла; правило 8: ничего не «достраивается по смыслу»);
  * ЧИСЛО КЛАССОВ и ВАРИОГРАММА (`range`/`nugget`/`анизотропия`) — из данных проекта;
  * ПРОПОРЦИИ ФАЦИЙ по скважинам — либо готовое свидетельство этапа, либо
    ЛОКАЛЬНЫЙ расчёт по LAS (`domain/geostat.read_las`); в отчёте источник помечен
    явно («рассчитано локально: …»), чтобы гейт отличал оценку от результата тНава;
  * ДИСКРЕТНОСТЬ куба: если функция НЕ создаёт свойство сама, нужен ЗАРАНЕЕ
    существующий дискретный куб с дискретной палитрой (корневая причина B4:
    «has inappropriate template (Continuous palette)») — агент фиксирует это как
    ТРЕБОВАНИЕ (`palette.required`) и честный `unknown`, а не как «работает»;
  * ГЕОТЕЛА (этап 6.1) — функция и палитра из данных;
  * СОГЛАСОВАННОСТЬ С СЕТКОЙ: радиус корреляции против шага сетки, `nugget ∈ [0,1]`,
    анизотропия `∈ (0,1]`, число классов против кодов литологии в данных.

В коде нет ни одного доменного значения поля: имя куба, имя blocked well, сетка,
палитра, число классов, пороги и пути — читаются по КЛЮЧАМ из данных
(`ontology/facies_methods.yaml` + проектный YAML + `config.yaml`). Идентификаторы
СХЕМЫ (`Grid3d`, `Grid3dProperty`, `BlockedWells`, `AG_FACIES`) — не значения поля
(прецедент: `agents.grid._GRID_OBJ_TYPE`).

Каноническая реализация — :class:`FaciesAgent`; тонкая обёртка :func:`decide_facies`
живёт также в :mod:`agents.facies_policy` (совместимость `StageRunner` и тестов v5).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from agents.base_agent import BaseAgent
from domain.geostat import read_las

# --- идентификаторы СХЕМЫ онтологии (не значения поля) ------------------------
_OBJ_TYPE_WELL_LOG = "WellLog"           # тип объекта «ГИС-лог»
_METHODS_FILE = "facies_methods.yaml"    # файл данных карты «метод → функция»
_ROOT = Path(__file__).resolve().parents[1]

# Ключи данных ПО УМОЛЧАНИЮ (если файл данных карты недоступен/неполон): в коде —
# только ключи, ни одного доменного значения поля.
_DEFAULT_KEYS = {
    "project_section": "geostat",
    "method": "facies_method",
    "classes": "n_facies",
    "range": "hole_range_m",
    "nugget": "nugget",
    "anisotropy": "anisotropy",
    "allowed_methods": "checks.facies_methods",
    "min_classes": "checks.facies_min_classes",
    "templates_dir": "workflow.templates_dir",
    "ontology_root": "ontology.root",
    "logs_dir": "logs",
    "dataset_root": "dataset_root",
    "pipeline": "pipeline",
    "steps": "steps",
    "function": "function",
    "objects": "objects",
    "obj_name": "obj_name",
    "obj_type": "obj_type",
    "input_log_role": "input_log",
}

_DEFAULT_EVIDENCE = {"proportions": "facies_proportions", "grid_policy": "grid_policy",
                     "objects": "objects"}

_DEFAULT_ROLES = {"cube_role": "result_grid_property",
                  "blocked_wells_role": "blocked_wells",
                  "mesh_role": "mesh"}

_DEFAULT_PROPORTIONS = {"source": "well_logs", "max_files": 0, "min_wells": 0,
                        "source_label": "рассчитано локально по LAS"}


def load_methods_data(cfg=None) -> dict:
    """Карта «метод → функция тНава» из ДАННЫХ (путь — из `ontology.root`).

    Файл данных (`ontology/facies_methods.yaml`) содержит и ключи, и сами значения;
    отсутствие/битый файл → `{}`, и агент честно фиксирует `unknown`
    (правило 6: неизвестное не подменяется «ложью»).
    """
    root: Path | None = None
    if cfg is not None:
        try:
            root = cfg.path("ontology.root", "ontology")
        except Exception:                     # noqa: BLE001 — конфиг опционален
            root = None
    if root is None or not Path(root).is_dir():
        root = _ROOT / "ontology"
    path = Path(root) / _METHODS_FILE
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


class FaciesAgent(BaseAgent):
    """Решение агента фаций: метод→функция (данные), куб, палитра, пропорции, геотела."""

    agent_id = "AG_FACIES"
    label = "Агент фаций (дискретный куб, геотела)"

    def __init__(self, cfg=None, **kwargs) -> None:
        super().__init__(cfg, **kwargs)
        self._data: dict | None = None

    # -- данные карты «метод → функция» -------------------------------------------
    def methods_data(self) -> dict:
        """Данные карты методов (кэш на экземпляр; `{}` — данных нет)."""
        if self._data is None:
            self._data = load_methods_data(self.cfg)
        return self._data

    def decision(self, project: dict, evidence: dict | None = None) -> dict:
        """Решение: {enabled, method, grid_function, n_facies, variogram, palette, …}."""
        project = project or {}
        ev = evidence or {}
        data = self.methods_data()
        keys = self._keys(data)
        geo = self._section(project, keys["project_section"])

        n_facies = int(self._num(geo.get(keys["classes"]), 0))
        method = str(geo.get(keys["method"]) or "").strip().lower()
        variogram = {
            "range_m": self._num(geo.get(keys["range"]), 0.0),
            "nugget": self._num(geo.get(keys["nugget"]), 0.0),
            "anisotropy": self._num(geo.get(keys["anisotropy"]), 0.0),
        }
        values = self._values(data, variogram)

        declared = self._declared(project, data, keys)
        spec, function, unknown = self._choose(data, method, declared)
        step = declared.get(function) or {}
        objects = self._objects(step, keys, data)
        roles = {**_DEFAULT_ROLES, **{k: v for k, v in data.items()
                                      if k in _DEFAULT_ROLES}}
        cube = objects.get(roles["cube_role"], "")
        blocked = objects.get(roles["blocked_wells_role"], "")
        mesh = objects.get(roles["mesh_role"], "")

        palette = self._palette(data)
        palette["required"] = not bool(spec.get("creates_cube"))
        palette["cube"] = cube
        if palette["required"]:
            unknown.append(
                "дискретность куба: функция не создаёт свойство сама — нужен заранее "
                "созданный дискретный куб с дискретной палитрой (протокол B4)")

        props, props_source, wells, prop_unknown = self._proportions(project, ev, data, keys)
        unknown += prop_unknown
        codes = sorted(props)

        geobody = self._geobody(data, declared)
        check = self._grid_check(ev, data, keys, variogram, n_facies, codes)
        patch, patch_unknown = self._patches(function, data, values)
        unknown += patch_unknown

        enabled = bool(n_facies > 0 and function and function in declared)
        reason = self._reason(method, spec, n_facies, variogram, function,
                              props, props_source, palette)
        out = {
            "enabled": enabled, "method": method, "n_facies": n_facies,
            "variogram": variogram, "grid_function": function,
            "method_spec": dict(spec), "declared_in_pipeline": bool(function in declared),
            "cube": cube, "blocked_wells": blocked, "mesh": mesh,
            "palette": palette, "geobody": geobody,
            "proportions": props, "proportions_source": props_source,
            "proportion_wells": wells, "classes_from_data": codes,
            "grid_check": check, "unknown": unknown,
            "parameters": {function: patch} if (function and patch) else {},
            "reason": reason,
        }
        return out

    # -- ключи данных ---------------------------------------------------------------
    @staticmethod
    def _keys(data: dict) -> dict:
        keys = data.get("keys") if isinstance(data.get("keys"), dict) else {}
        out = dict(_DEFAULT_KEYS)
        out.update({str(k): str(v) for k, v in keys.items()})
        return out

    @staticmethod
    def _evidence_keys(data: dict) -> dict:
        ev = data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
        out = dict(_DEFAULT_EVIDENCE)
        out.update({str(k): str(v) for k, v in ev.items()})
        return out

    def _cfg_value(self, dotted: str) -> Any:
        return self.cfg.get(dotted) if self.cfg is not None else None

    # -- выбор функции по данным ------------------------------------------------------
    def _declared(self, project: dict, data: dict, keys: dict) -> dict:
        """{функция: шаг} — шаги пайплайна, чьи функции описаны в данных карты."""
        methods = data.get("methods") if isinstance(data.get("methods"), dict) else {}
        known = {str((m or {}).get("function") or "") for m in methods.values()
                 if isinstance(m, dict)}
        geo = data.get("geobody") if isinstance(data.get("geobody"), dict) else {}
        known.add(str(geo.get("function") or ""))
        known.discard("")
        out: dict[str, dict] = {}
        for stage in project.get(keys["pipeline"]) or []:
            for step in (stage.get(keys["steps"]) if isinstance(stage, dict) else None) or []:
                step = step if isinstance(step, dict) else {}
                fn = str(step.get(keys["function"]) or "")
                if fn and fn in known:
                    out.setdefault(fn, step)
        return out

    @staticmethod
    def _choose(data: dict, method: str, declared: dict) -> tuple[dict, str, list[str]]:
        """Выбрать спеку метода и функцию тНава; честные `unknown` при пробелах."""
        methods = data.get("methods") if isinstance(data.get("methods"), dict) else {}
        unknown: list[str] = []
        spec = methods.get(method) if method else None
        if method and not isinstance(spec, dict):
            unknown.append(f"метод фаций «{method}» не описан в данных "
                           f"(карта «метод → функция», {_METHODS_FILE})")
            spec = None
        function = str((spec or {}).get("function") or "")
        if not method:
            from_map = sorted({str((m or {}).get("function") or "") for m in methods.values()
                               if isinstance(m, dict)} & set(declared))
            if len(from_map) == 1:
                function = from_map[0]
                unknown.append("метод фаций в данных не задан — выбрана функция, "
                               "объявленная в шагах пайплайна")
            else:
                unknown.append("метод фаций в данных не задан — функцию выбрать нельзя")
        if function and function not in declared:
            unknown.append(f"функция «{function}» не объявлена в шагах пайплайна — "
                           f"этап её не вызовет")
        return (spec or {}), function, unknown

    @staticmethod
    def _objects(step: dict, keys: dict, data: dict) -> dict:
        """{роль: имя объекта} из шага пайплайна (данные: objects либо placeholders+replace)."""
        objs = step.get(keys["objects"]) if isinstance(step, dict) else None
        out: dict[str, str] = {}
        for role, obj in (objs or {}).items():
            if isinstance(obj, dict):
                out[str(role)] = str(obj.get(keys["obj_name"]) or "")
        placeholders = data.get("placeholders") if isinstance(data.get("placeholders"), dict) else {}
        replace = step.get("replace") if isinstance(step, dict) else None
        for role, placeholder in placeholders.items():
            if str(role) in out:
                continue
            value = (replace or {}).get(str(placeholder))
            if isinstance(value, str):
                out[str(role)] = value.strip().strip('"').strip("'")
        return out

    # -- палитра и геотела ------------------------------------------------------------
    @staticmethod
    def _palette(data: dict) -> dict:
        pal = data.get("palette") if isinstance(data.get("palette"), dict) else {}
        return {str(k): v for k, v in pal.items()}

    @staticmethod
    def _geobody(data: dict, declared: dict) -> dict:
        geo = data.get("geobody") if isinstance(data.get("geobody"), dict) else {}
        out = {str(k): v for k, v in geo.items()}
        out["declared_in_pipeline"] = bool(str(geo.get("function") or "") in declared)
        return out

    # -- вариограмма → значения для патча ---------------------------------------------
    def _values(self, data: dict, variogram: dict) -> dict:
        """Значения параметров шаблона из политики (range/nugget/анизотропия)."""
        var = data.get("variogram") if isinstance(data.get("variogram"), dict) else {}
        rng = float(variogram.get("range_m") or 0.0)
        ani = float(variogram.get("anisotropy") or 0.0)
        table = {
            "range_main": rng,
            "range_normal": rng,
            "range_vertical": rng * ani,
            "nugget": variogram.get("nugget"),
        }
        out: dict[str, Any] = {}
        for code, source in (data.get("patch_codes") or {}).items():
            source = str(source)
            if source == "interpolator":
                continue                        # значение — из спеки метода
            if source in table and table[source] not in (None, ""):
                out[code] = table[source]
        return out

    def _patches(self, function: str, data: dict, values: dict) -> tuple[dict, list[str]]:
        """Патчи параметров шаблона: только коды, реально присутствующие в шаблоне."""
        unknown: list[str] = []
        if not function:
            return {}, unknown
        spec_interp = None
        methods = data.get("methods") if isinstance(data.get("methods"), dict) else {}
        for m in methods.values():
            if isinstance(m, dict) and str(m.get("function") or "") == function:
                spec_interp = str(m.get("interpolator") or "") or None
                break
        allowed = [str(x) for x in (data.get("interpolators") or [])]
        text = self._template_text(function)
        patch: dict[str, Any] = {}
        for code, source in (data.get("patch_codes") or {}).items():
            code, source = str(code), str(source)
            value = spec_interp if source == "interpolator" else values.get(code)
            if value in (None, ""):
                continue
            if source == "interpolator" and allowed and value not in allowed:
                unknown.append(f"значение «{value}» параметра {code} не подтверждено "
                               f"данными (допустимо: {', '.join(allowed)})")
                continue
            if text is None:
                unknown.append(f"шаблон функции «{function}» не найден — патч {code} "
                               f"не применён (параметр останется дефолтным)")
                continue
            if not re.search(r"\b" + re.escape(code) + r"\s*=", text):
                unknown.append(f"параметра «{code}» нет в шаблоне «{function}» — "
                               f"патч не применён (иначе рендер дал бы предупреждение)")
                continue
            patch[code] = value
        return patch, unknown

    def _template_text(self, function: str) -> str | None:
        """Текст шаблона функции (данные `workflow.templates_dir`)."""
        base = None
        if self.cfg is not None:
            try:
                base = self.cfg.path("workflow.templates_dir", "domain/templates")
            except Exception:                  # noqa: BLE001
                base = None
        if base is None:
            base = _ROOT / "domain" / "templates"
        path = Path(base) / f"{function}.txt"
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    # -- пропорции фаций ----------------------------------------------------------------
    def _proportions(self, project: dict, ev: dict, data: dict,
                     keys: dict) -> tuple[dict, str, int, list[str]]:
        """Пропорции кодов фаций: свидетельство этапа либо локальный расчёт по LAS."""
        ev_key = self._evidence_keys(data)["proportions"]
        ready = ev.get(ev_key) if ev_key else None
        if isinstance(ready, dict) and ready:
            props = {str(k): float(v) for k, v in ready.items()
                     if isinstance(v, (int, float))}
            if props:
                return props, "свидетельство этапа", int(ev.get("proportion_wells") or 0), []
        spec = self._proportions_spec(data)
        if str(spec.get("source") or "") != "well_logs":
            return {}, "", 0, ["пропорции фаций: источник в данных не задан"]
        return self._proportions_from_logs(project, data, keys)

    @staticmethod
    def _proportions_spec(data: dict) -> dict:
        """Настройки локального расчёта пропорций (данные + безопасные умолчания)."""
        spec = data.get("proportions") if isinstance(data.get("proportions"), dict) else {}
        out = dict(_DEFAULT_PROPORTIONS)
        out.update({str(k): v for k, v in spec.items()})
        return out

    def _proportions_from_logs(self, project: dict, data: dict,
                               keys: dict) -> tuple[dict, str, int, list[str]]:
        """Локальный расчёт пропорций по LAS (НЕ результат тНава — см. отчёт)."""
        spec = self._proportions_spec(data)
        label = str(spec.get("source_label") or "рассчитано локально по LAS")
        root_rel = project.get(keys.get("dataset_root"))
        logs_rel = self._section(project, "inputs").get(keys.get("logs_dir"))
        mnem = self._log_mnemonic(project, data, keys)
        if not (root_rel and logs_rel and mnem):
            return {}, "", 0, ["пропорции фаций: нет данных LAS "
                               "(dataset_root/inputs.logs/мнемоника лога)"]
        root = self._resolve(str(root_rel)) / str(logs_rel)
        if not Path(root).is_dir():
            return {}, "", 0, [f"пропорции фаций: каталог LAS не найден ({logs_rel})"]
        limit = int(self._num(spec.get("max_files"), 0))
        files = sorted(Path(root).glob("*.las"))
        if limit > 0:
            files = files[:limit]
        counts: dict[int, int] = {}
        wells = 0
        for path in files:
            las = read_las(path)
            mnems = las.get("mnems") or []
            if mnem not in mnems:
                continue
            wells += 1
            idx = mnems.index(mnem)
            null = las.get("null")
            for row in las.get("data") or []:
                if idx >= len(row):
                    continue
                value = row[idx]
                if abs(value) > 1e28 or (null is not None and abs(value - null) < 1e-3):
                    continue
                code = int(round(value))
                if code < 0:
                    continue
                counts[code] = counts.get(code, 0) + 1
        total = sum(counts.values())
        min_wells = int(self._num(spec.get("min_wells"), 0))
        if wells < max(min_wells, 1) or total <= 0:
            return {}, "", wells, [f"пропорции фаций: скважин с логом «{mnem}» — {wells} "
                                   f"(порог {max(min_wells, 1)}) — пропорции не считаются"]
        props = {str(code): round(count / total, 4) for code, count in sorted(counts.items())}
        return props, label, wells, []

    def _log_mnemonic(self, project: dict, data: dict, keys: dict) -> str:
        """Мнемоника ГИС-лога фаций из ДАННЫХ шага (роль «исходный лог»)."""
        role = keys.get("input_log_role") or ""
        for step in self._all_steps(project, keys):
            objs = step.get(keys["objects"]) if isinstance(step, dict) else None
            obj = (objs or {}).get(role) if isinstance(objs, dict) else None
            if not isinstance(obj, dict):
                continue
            obj_type = str(obj.get(keys["obj_type"]) or "")
            if obj_type and obj_type != _OBJ_TYPE_WELL_LOG:
                continue
            name = str(obj.get(keys["obj_name"]) or "")
            if name:
                return name
        return ""

    def _all_steps(self, project: dict, keys: dict) -> list[dict]:
        out: list[dict] = []
        for stage in project.get(keys["pipeline"]) or []:
            steps = (stage.get(keys["steps"]) if isinstance(stage, dict) else None) or []
            out += [s for s in steps if isinstance(s, dict)]
        return out

    def _resolve(self, rel: str) -> Path:
        """Разрешить относительный путь данных от корня сервиса."""
        if self.cfg is not None:
            try:
                return Path(self.cfg.resolve(rel))
            except Exception:                  # noqa: BLE001
                pass
        path = Path(rel)
        return path if path.is_absolute() else _ROOT / path

    # -- согласованность с сеткой ---------------------------------------------------------
    def _grid_check(self, ev: dict, data: dict, keys: dict, variogram: dict,
                    n_facies: int, codes: list[str]) -> dict:
        """Согласованность фаций со структурной сеткой и данными (честные замечания)."""
        pol = ev.get(self._evidence_keys(data)["grid_policy"]) or {}
        step = pol.get("step") if isinstance(pol, dict) else None
        step = step if isinstance(step, dict) else {}
        cell = max(self._num(step.get("step_x"), 0.0), self._num(step.get("step_y"), 0.0))
        rng = float(variogram.get("range_m") or 0.0)
        nug = float(variogram.get("nugget") or 0.0)
        ani = float(variogram.get("anisotropy") or 0.0)
        minimum = self._cfg_value(keys.get("min_classes") or "")
        issues: list[str] = []
        if cell > 0 and 0 < rng < cell:
            issues.append(f"радиус корреляции {rng:g} м меньше шага сетки {cell:g} м")
        if rng > 0 and not 0.0 <= nug <= 1.0:
            issues.append(f"nugget {nug:g} вне [0, 1]")
        if rng > 0 and ani and not 0.0 < ani <= 1.0:
            issues.append(f"анизотропия {ani:g} вне (0, 1]")
        if minimum is not None and n_facies and n_facies < int(self._num(minimum, 0)):
            issues.append(f"классов фаций {n_facies} < {int(self._num(minimum, 0))}")
        if codes and n_facies and len(codes) != n_facies:
            issues.append(f"число классов n_facies={n_facies} не совпадает с числом "
                          f"кодов литологии в данных ({len(codes)}: {', '.join(codes)})")
        return {"cell_m": cell, "range_cells": round(rng / cell, 3) if cell > 0 else None,
                "issues": issues, "consistent": not issues}

    # -- обоснование ------------------------------------------------------------------------
    @staticmethod
    def _reason(method: str, spec: dict, n_facies: int, variogram: dict, function: str,
                props: dict, props_source: str, palette: dict) -> str:
        if not n_facies:
            return ("фации: n_facies в данных не задано — стадия отключается "
                    "(неизвестное != ложь)")
        cube = palette.get("cube") or "—"
        text = (f"фации: метод «{method or 'не задан'}» → функция {function or '—'} "
                f"(куб «{cube}»), классов {n_facies} (range={variogram['range_m']:g} м, "
                f"nugget={variogram['nugget']:g}, анизотропия={variogram['anisotropy']:g})")
        if props:
            top = max(props.items(), key=lambda kv: kv[1])
            text += (f"; пропорции по данным: код {top[0]} = {top[1]:.0%} "
                     f"({props_source or 'источник не указан'})")
        else:
            text += "; пропорции фаций в данных не посчитаны (неизвестное != ложь)"
        if not spec.get("creates_cube", True):
            text += "; требуется предсозданный дискретный куб с дискретной палитрой"
        return text


def decide_facies(project: dict, evidence: dict | None = None, *, cfg=None, kb=None,
                  registry=None, gate_engine=None) -> dict:
    """Тонкая обёртка (совместимость): решение :class:`FaciesAgent`.

    `cfg`/`kb`/`registry`/`gate_engine` прокидываются в агента (как в
    `decide_erosion`/`decide_grid`): с ними работают режимы BDI-цикла
    (`symbolic/hybrid/…`), полнота входов и память опыта (`recall`/`suggest`).
    """
    return FaciesAgent(cfg, kb=kb, registry=registry, gate_engine=gate_engine).decide(
        project, evidence)
