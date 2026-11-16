"""Агент сетки и волюметрии (AG_GRID_VOLUMETRICS): бокс, шаг, слои, QC ячеек, разломы.

Агент отвечает на вопрос «какой сеткой считать модель» по ДАННЫМ проекта и
свидетельствам этапа:

  * БОКС (`min_x/min_y/length_x/length_y`) — из EXTENT структурной карты
    (свидетельство `maps` = статистика irap): область карты совпадает с боксом
    модели, иначе горизонт строится на пустой области;
  * ШАГ (`step_x/step_y`) и сам шаг пайплайна («функция сетки») — из данных
    проектного графа (шаг с параметрами бокса и объектом типа ``Grid3d``);
  * ОЖИДАЕМЫЕ РАЗМЕРЫ — ``expected_nx/expected_ny`` = round(length / step);
    ``expected_nz``/``expected_cells`` — ТОЛЬКО если число слоёв объявлено в
    данных шага (иначе честный `unknown`, «неизвестное != ложь»);
  * РАЗЛОМЫ — политика решает, включать ли разломы, по ДАННЫМ: есть вход
    `inputs.faults` И подтверждено наличие объекта разломов в проекте. Нет
    подтверждения → сетка строится БЕЗ разломов (базовый прогон не меняется);
  * QC ЯЧЕЕК — агенту передаются ожидания (nx/ny/nz/cells/шаг/бокс), с которыми
    гейт G-GRID сверяет фактические размеры ячейки (пороги — `checks.*`).

В коде нет ни одного имени объекта/числа поля — только КЛЮЧИ данных. Имена типов
объектов онтологии (``Grid3d``, ``Fault3d``) — идентификаторы СХЕМЫ, не значения
поля (прецедент: :data:`agents.grid_policy._GRID_OBJ_TYPE`).

Каноническая реализация — :class:`GridAgent`; тонкая обёртка :func:`decide_grid`
живёт в :mod:`agents.grid_policy` (совместимость `StageRunner` и тестов v5).
"""
from __future__ import annotations

from agents.base_agent import BaseAgent

# --- идентификаторы СХЕМЫ онтологии (не значения поля) ------------------------
_GRID_OBJ_TYPE = "Grid3d"        # тип объекта «3D-сетка»
_FAULT_OBJ_TYPE = "Fault3d"      # тип объекта «разломы»

# --- КЛЮЧИ данных -------------------------------------------------------------
_K_PARAMETERS = "parameters"
_K_OBJECTS = "objects"
_K_OBJ_TYPE = "obj_type"
_K_OBJ_NAME = "obj_name"
_K_FUNCTION = "function"
_K_PIPELINE = "pipeline"
_K_STEPS = "steps"
_K_INPUTS = "inputs"
_K_FAULTS = "faults"
_K_COUNTS_STEP = "counts_step"
_K_HORIZONS_TABLE = "horizons_table"
_K_ONE_LAYERING = "use_one_layering_column"
_K_MIN_X, _K_MIN_Y = "min_x", "min_y"
_K_LENGTH_X, _K_LENGTH_Y = "length_x", "length_y"
_K_STEP_X, _K_STEP_Y = "step_x", "step_y"
_K_AUTODETECT_BOX = "autodetect_box"
_EV_MAPS = "maps"
_EV_EXTENT = "extent"
_EV_FAULTS = "faults"
_EV_OBJECTS = "objects"


class GridAgent(BaseAgent):
    """Решение агента сетки: бокс из extent карты, шаг, слои, QC ячеек, разломы."""

    agent_id = "AG_GRID_VOLUMETRICS"
    label = "Агент сетки и волюметрии"

    def decision(self, project: dict, evidence: dict | None = None) -> dict:
        """Решение: {enabled, grid_function, box, step, expected_*, faults, qc, reason}."""
        ev = evidence or {}
        fn, params = self._grid_step(project)
        if not fn:
            return {"enabled": False, "grid_function": "", "box": {}, "step": {},
                    "parameters": {}, "faults": self._faults(project, ev, ""),
                    "reason": ("в данных нет шага сетки с параметрами бокса "
                               "(min_x/length_x) — сетка не корректируется")}

        box = self._box_from_extent(ev)
        step = {k: params[k] for k in (_K_STEP_X, _K_STEP_Y) if k in params}
        patch: dict = {}
        if box:
            patch.update(box)
            patch[_K_AUTODETECT_BOX] = False     # бокс задан ЯВНО (по карте)
        patch.update(step)

        expected = self._expected_nxny(box, step)
        nz = self._expected_layers(params)
        if nz is not None:
            expected["expected_nz"] = nz
            if expected:
                expected["expected_cells"] = (expected.get("expected_nx", 1)
                                              * expected.get("expected_ny", 1) * nz)

        unknown: list[str] = []
        if nz is None:
            unknown.append("layers: число слоёв сетки в данных шага не объявлено — "
                           "ожидаемое nz не выводится (неизвестное != ложь)")

        faults = self._faults(project, ev, fn)
        if faults.get("requested") and not faults.get("enabled"):
            unknown.append("faults: включение разломов в сетку данными не "
                           "подтверждено (неизвестное != ложь)")

        if box:
            # Шаг печатается ТОЛЬКО если объявлены ОБЕ компоненты (неполные данные
            # шага — не повод падать: «неизвестное != ложь»).
            step_note = (f", шаг {step[_K_STEP_X]:g}×{step[_K_STEP_Y]:g} м"
                         if _K_STEP_X in step and _K_STEP_Y in step else "")
            reason = (f"бокс сетки = extent структурной карты "
                      f"x[{box[_K_MIN_X]:g}..{box[_K_MIN_X] + box[_K_LENGTH_X]:g}] "
                      f"y[{box[_K_MIN_Y]:g}..{box[_K_MIN_Y] + box[_K_LENGTH_Y]:g}]"
                      + step_note)
        else:
            reason = ("нет свидетельства карты (extent) — бокс берётся из "
                      "проектного YAML (неизвестное != ложь)")

        out = {"enabled": bool(box), "grid_function": fn, "box": box, "step": step,
               **expected,
               "parameters": {fn: patch} if patch else {},
               "faults": faults, "unknown": unknown, "reason": reason}
        out["qc"] = {"expected_nx": out.get("expected_nx"),
                     "expected_ny": out.get("expected_ny"),
                     "expected_nz": out.get("expected_nz"),
                     "expected_cells": out.get("expected_cells"),
                     "step": dict(step), "box": dict(box),
                     "limits_from": "checks.*"}
        return out

    # -- поиск шага сетки в данных пайплайна --------------------------------------
    @classmethod
    def _grid_step(cls, project: dict) -> tuple[str, dict]:
        """Найти шаг сетки в ДАННЫХ пайплайна: бокс (min_x/length_x) + объект сетки.

        Признак шага сетки — параметры бокса И создаваемый объект онтологического
        типа ``Grid3d`` (имя типа — из юзер-данных шага, не из кода домена).
        """
        for stage in project.get(_K_PIPELINE) or []:
            for step in (stage.get(_K_STEPS) if isinstance(stage, dict) else None) or []:
                step = step or {}
                params = step.get(_K_PARAMETERS) or {}
                if _K_MIN_X not in params or _K_LENGTH_X not in params:
                    continue
                objs = step.get(_K_OBJECTS) or {}
                if any(str((o or {}).get(_K_OBJ_TYPE)) == _GRID_OBJ_TYPE
                       for o in objs.values()):
                    return str(step.get(_K_FUNCTION) or ""), dict(params)
        return "", {}

    # -- ожидаемые размеры --------------------------------------------------------
    @staticmethod
    def _expected_nxny(box: dict, step: dict) -> dict:
        """Ожидаемые размеры сетки по плану: ``round(length / step)`` для X и Y.

        Возвращает ``{}``, если данных не хватает («неизвестное != ложь») — тогда
        проверка качества сетки не сверяет число ячеек с боксом.
        """
        try:
            sx, sy = float(step[_K_STEP_X]), float(step[_K_STEP_Y])
            lx, ly = float(box[_K_LENGTH_X]), float(box[_K_LENGTH_Y])
        except (KeyError, TypeError, ValueError):
            return {}
        if sx > 0 and sy > 0 and lx > 0 and ly > 0:
            return {"expected_nx": max(1, round(lx / sx)),
                    "expected_ny": max(1, round(ly / sy))}
        return {}

    @staticmethod
    def _expected_layers(params: dict) -> int | None:
        """Число слоёв сетки из ДАННЫХ шага (или None — «неизвестное != ложь»).

        Источники (в порядке приоритета), оба — коды параметров машинного шаблона:
          * скалярный ``counts_step`` — разбиение одноколоночного лейеринга;
          * ``horizons_table`` — сумма ``counts_step`` по строкам, если лейеринг
            задаётся НЕ одной колонкой (при ``use_one_layering_column`` сумма
            неоднозначна — тогда None, а не выдуманное число).
        """
        try:
            scalar = params.get(_K_COUNTS_STEP)
            if scalar is not None:
                return int(scalar)
        except (TypeError, ValueError):
            return None
        table = params.get(_K_HORIZONS_TABLE)
        if not isinstance(table, list) or not table:
            return None
        if params.get(_K_ONE_LAYERING):
            return None
        total = 0
        for row in table:
            counts = (row or {}).get(_K_COUNTS_STEP) if isinstance(row, dict) else None
            try:
                total += int(counts)
            except (TypeError, ValueError):
                return None
        return total or None

    # -- бокс из extent карты ------------------------------------------------------
    @staticmethod
    def _box_from_extent(evidence: dict) -> dict:
        """Бокс модели из extent структурной карты (свидетельство `maps`)."""
        for m in evidence.get(_EV_MAPS) or []:
            ext = (m or {}).get(_EV_EXTENT) if isinstance(m, dict) else None
            if not isinstance(ext, dict):
                continue
            try:
                x0, x1 = float(ext["x0"]), float(ext["x1"])
                y0, y1 = float(ext["y0"]), float(ext["y1"])
            except (KeyError, TypeError, ValueError):
                continue
            if x1 <= x0 or y1 <= y0:
                continue
            return {_K_MIN_X: x0, _K_MIN_Y: y0,
                    _K_LENGTH_X: round(x1 - x0, 6),
                    _K_LENGTH_Y: round(y1 - y0, 6)}
        return {}

    # -- разломы (политика, по умолчанию ВЫКЛЮЧЕНЫ) --------------------------------
    @classmethod
    def _faults(cls, project: dict, evidence: dict, grid_fn: str) -> dict:
        """Решение о разломах: по данным `inputs.faults` + подтверждению объекта.

        По умолчанию разломы НЕ включаются (базовый прогон не меняется): пока
        наличие объекта разломов в проекте не подтверждено свидетельством,
        решение — «выключено» с явным `unknown`, а не «ложь».
        """
        requested = bool((project.get(_K_INPUTS) or {}).get(_K_FAULTS))
        obj_name = cls._declared_object(project, _FAULT_OBJ_TYPE)
        fn = cls._faults_grid_function(project, grid_fn)
        confirmed = cls._faults_confirmed(evidence, obj_name)

        if not requested:
            return {"enabled": False, "requested": False, "confirmed": None,
                    "object": obj_name, "function": fn,
                    "reason": "вход разломов не задан — сетка строится без разломов"}
        if confirmed is None:
            reason = (f"вход разломов задан, но наличие объекта «{obj_name or '—'}» "
                      f"в проекте не подтверждено — сетка строится без разломов "
                      f"(неизвестное != ложь)")
        elif not confirmed:
            reason = ("объект разломов в проекте отсутствует — сетка строится "
                      "без разломов")
        elif not fn:
            reason = ("объект разломов подтверждён, но функция сетки с разломами "
                      "не объявлена в данных шага — включение не выполнено "
                      "(эталон GDAHM1.1, проба на лицензии)")
        else:
            reason = (f"объект разломов «{obj_name}» подтверждён — разломы "
                      f"включаются функцией {fn}")
        enabled = bool(confirmed) and bool(fn)
        return {"enabled": enabled, "requested": bool(requested),
                "confirmed": confirmed if confirmed is None else bool(confirmed),
                "object": obj_name, "function": fn, "reason": reason}

    @staticmethod
    def _declared_object(project: dict, obj_type: str) -> str:
        """Имя объекта заданного онтологического типа, объявленное в данных шагов."""
        for stage in project.get(_K_PIPELINE) or []:
            for step in (stage.get(_K_STEPS) if isinstance(stage, dict) else None) or []:
                for obj in ((step or {}).get(_K_OBJECTS) or {}).values():
                    if str((obj or {}).get(_K_OBJ_TYPE)) == obj_type:
                        return str((obj or {}).get(_K_OBJ_NAME) or "")
        return ""

    @classmethod
    def _faults_grid_function(cls, project: dict, grid_fn: str) -> str:
        """Функция сетки с разломами: шаг, который создаёт сетку И объект разломов."""
        for stage in project.get(_K_PIPELINE) or []:
            for step in (stage.get(_K_STEPS) if isinstance(stage, dict) else None) or []:
                fn = str((step or {}).get(_K_FUNCTION) or "")
                if not fn or fn == grid_fn:
                    continue
                objs = [o or {} for o in ((step or {}).get(_K_OBJECTS) or {}).values()]
                types = {str(o.get(_K_OBJ_TYPE)) for o in objs}
                if _GRID_OBJ_TYPE in types and _FAULT_OBJ_TYPE in types:
                    return fn
        return ""

    @staticmethod
    def _faults_confirmed(evidence: dict, obj_name: str) -> bool | None:
        """Подтверждение объекта разломов свидетельством этапа (None = неизвестно)."""
        flag = evidence.get(_EV_FAULTS)
        if isinstance(flag, dict):
            return bool(flag.get("confirmed") or flag.get("count")
                        or flag.get("n_objects"))
        if flag:
            return True
        objects = evidence.get(_EV_OBJECTS)
        if isinstance(objects, (list, tuple, set)) and obj_name:
            return str(obj_name) in {str(x) for x in objects}
        return None


def decide_grid(project: dict, evidence: dict | None = None, *, cfg=None, kb=None,
                registry=None, gate_engine=None) -> dict:
    """Тонкая обёртка (совместимость): решение :class:`GridAgent`."""
    return GridAgent(cfg, kb=kb, registry=registry,
                     gate_engine=gate_engine).decide(project, evidence)
