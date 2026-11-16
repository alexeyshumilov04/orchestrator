"""Агент карт (E9): какие карты строить, каким путём, контроль полноты.

Проблема, которую решает агент: нативный UI-путь тНава (`create_screenshot`,
`select_geometry_object`) в консоли НЕДОСТУПЕН. Console-safe путь — построить
объект 2D-карты из свойства сетки (`map_2d_create_by_grid_property`) и выгрузить
его файлом (`map_2d_export_cps_format` / `map_2d_export_ascii_format`), после чего
matplotlib (`domain.map_render`) рисует PNG. Правило 8: сигнатуры этих функций
подтверждены пробой на живой лицензии (`tools/probe_maps.py`, отчёт `_probe_maps*.txt`).

Данные (в коде — только КЛЮЧИ, правило 1):
  * ``checks.map_files``   — ожидаемый набор карт (имена PNG);
  * ``checks.map_kinds``   — классификация карт (структура/фации/петрофизика);
  * ``checks.map_sources`` — фолбэк-источник карты (файл в каталоге прогона);
  * шаги этапа карт в проектном графе — маршрут «нативный объект + экспорт»
    (имя объекта, файл выгрузки, формат — из данных шага).

Решение: {enabled, expected, routes, native, fallback, unknown_routes, complete,
reason}. Правило 6: карта без объявленного маршрута попадает в ``unknown_routes``
(и в ``unknown``), а НЕ в «провалено»; отсутствие маршрутов не отключает контроль.
"""
from __future__ import annotations

from agents.base_agent import BaseAgent
from agents.petrophysics import _default_cfg

_EXPORT_PREFIX = "map_2d_export"


class MapsAgent(BaseAgent):
    """Решение агента карт: маршруты построения карт и контроль полноты."""

    agent_id = "AG_MAPS"
    label = "Агент карт (console-safe экспорт)"

    def __init__(self, cfg=None, **kwargs) -> None:
        super().__init__(cfg if cfg is not None else _default_cfg(), **kwargs)

    # -- данные ------------------------------------------------------------------
    def expected(self) -> list[str]:
        """Ожидаемые карты (ДАННЫЕ `checks.map_files`)."""
        if self.cfg is None:
            return []
        return [str(x) for x in (self.cfg.get("checks.map_files") or []) if str(x)]

    def sources(self) -> dict:
        """Фолбэк-источники карт (ДАННЫЕ `checks.map_sources`)."""
        if self.cfg is None:
            return {}
        value = self.cfg.get("checks.map_sources") or {}
        return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}

    def kinds(self) -> dict:
        """Классификация карт (ДАННЫЕ `checks.map_kinds`)."""
        if self.cfg is None:
            return {}
        value = self.cfg.get("checks.map_kinds") or {}
        out: dict[str, str] = {}
        if isinstance(value, dict):
            for kind, names in value.items():
                for name in (names or []):
                    out[str(name)] = str(kind)
        return out

    @staticmethod
    def _export_steps(project: dict) -> list[dict]:
        """Шаги выгрузки карт из проектного графа (маршрут «нативный объект»).

        Читаются ДАННЫЕ шага: имя выгружаемой карты (роль объекта или замена
        `name="…"`), файл выгрузки и формат (по имени функции тНава).
        """
        out: list[dict] = []
        for stage in (project or {}).get("pipeline") or []:
            for step in (stage or {}).get("steps") or []:
                fn = str((step or {}).get("function") or "")
                if not fn.startswith(_EXPORT_PREFIX):
                    continue
                name = ""
                for obj in ((step.get("objects") or {}).values()):
                    if isinstance(obj, dict) and obj.get("obj_name"):
                        name = str(obj["obj_name"])
                        break
                file_name = str((step.get("parameters") or {}).get("file_name") or "")
                for old, new in (step.get("replace") or {}).items():
                    if '"name=' in str(old) and not name:
                        name = str(new).split('"')[1] if '"' in str(new) else str(new)
                    if "file_name" in str(old):
                        file_name = str(new)
                    if "__MAP__" in str(old):
                        name = str(new)
                out.append({"function": fn, "name": name, "file_name": file_name,
                            "format": "cps" if fn.endswith("cps_format") else "ascii"})
        return out

    # -- решение ------------------------------------------------------------------
    def decision(self, project: dict, evidence: dict | None = None) -> dict:
        """Решение по картам: {enabled, expected, routes, complete, reason}."""
        expected = self.expected()
        sources = self.sources()
        kinds = self.kinds()
        exports = self._export_steps(project)
        native_by_name = {e["name"]: e for e in exports if e.get("name")}

        routes: list[dict] = []
        unknown_routes: list[str] = []
        for name in expected:
            route = {"name": name, "kind": kinds.get(name, "")}
            native = native_by_name.get(name)
            source = sources.get(name) or ""
            if native is not None:
                route.update({"path": "native", "object": native["name"],
                              "file": native.get("file_name") or "",
                              "format": native.get("format") or ""})
            elif source:
                route.update({"path": "fallback", "source": source})
            else:
                # Ни нативного маршрута, ни источника в данных → это НЕ провал.
                route.update({"path": "unknown"})
                unknown_routes.append(name)
            routes.append(route)

        declared_export_names = sorted(native_by_name)
        exported = [r["name"] for r in routes if r["path"] == "native"]
        ready = [r["name"] for r in routes if r["path"] in ("native", "fallback")]
        enabled = bool(expected)
        if enabled:
            reason = (f"карты: ожидается {len(expected)}, маршрут есть у {len(ready)} "
                      f"(нативный экспорт: {len(exported)}, фолбэк: "
                      f"{len(ready) - len(exported)}), без маршрута: "
                      f"{len(unknown_routes)}")
            if declared_export_names and len(declared_export_names) != len(exported):
                reason += ("; шаги выгрузки объявлены для "
                           + ", ".join(declared_export_names))
        else:
            reason = ("карты: список ожидаемых карт не задан (checks.map_files) — "
                      "контроль полноты не выполняется (неизвестное != ложь)")
        return {"enabled": enabled, "expected": expected, "routes": routes,
                "native": exported, "fallback": [r["name"] for r in routes
                                                 if r["path"] == "fallback"],
                "unknown_routes": unknown_routes, "unknown": list(unknown_routes),
                "complete": bool(expected) and not unknown_routes,
                "reason": reason, "parameters": {}}


def decide_maps(project: dict, evidence: dict | None = None, *,
                cfg=None, kb=None, registry=None, gate_engine=None) -> dict:
    """Тонкая обёртка: решение :class:`MapsAgent` (для `StageRunner`).

    `cfg`/`kb`/`registry`/`gate_engine` — kw-only (интеграция `StageRunner`).
    """
    return MapsAgent(cfg, kb=kb, registry=registry,
                     gate_engine=gate_engine).decide(project, evidence)
