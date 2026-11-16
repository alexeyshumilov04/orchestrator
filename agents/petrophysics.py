"""Агент петрофизики (AG_PETROPHYSICS): метод, кубы, вариограмма, диапазоны φ/k.

Данные читаются по КЛЮЧАМ (ни одного доменного значения в коде — правило 1):

  * ``petrophysics.method``     — метод интерполяции (политика агента);
  * ``petrophysics.cubes``      — карта «мнемоника LAS → blocked well → куб сетки»;
  * ``petrophysics.variogram``  — ``range_main`` / ``nugget_effect`` / ``sill``;
  * ``petrophysics.facies``     — способ учёта фаций (зонный/беззонный, куб зон);
  * ``checks.petro_methods``    — разрешённый набор методов (политика гейта G-PETRO);
  * ``checks.properties``       — роль куба (напр. пористость/проницаемость) → куб;
  * ``thresholds.<роль>``       — диапазон физичности (пороги — ДАННЫЕ проекта).

Решение — надмножество прежнего контракта (``enabled`` / ``method`` / ``cubes`` /
``variogram`` / ``reason`` / ``parameters``) плюс ``method_ok``, ``ranges``,
``zone``, ``unknown``, ``missing``. Правило 6: нет кубов → этап отключён; нет
порога физичности → диапазон уходит в ``unknown``, а не считается «прошло»; нет
куба зон в данных → беззонная форма, и это фиксируется как решение, а не как ложь.

Реализация — :class:`PetrophysicsAgent` (наследник :class:`~agents.base_agent.BaseAgent`);
модульная функция :func:`decide_petrophysics` — тонкая обёртка для `StageRunner`
(совместимость с v5: те же ключи на входе/выходе).
"""
from __future__ import annotations

import csv
from pathlib import Path

from agents.base_agent import BaseAgent

_DEFAULT_CFG: object = None
_DEFAULT_CFG_TRIED = False


def read_table(path: Path) -> list[dict]:
    """Таблица керна (CSV/TXT) → список словарей; разделитель определяется по данным.

    Файл — ДАННЫЕ поля: имена колонок берутся из онтологии при подгонке
    (`ontology/petrofacies_methods.yaml: columns`), поэтому в коде их нет (правило 1).
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    sample = text[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    if sample.count("\t") > max(sample.count(";"), sample.count(",")):
        delimiter = "\t"
    return [dict(row) for row in csv.DictReader(text.splitlines(), delimiter=delimiter)]


def _default_cfg():
    """Конфигурация сервиса (политика/пороги — данные); None, если недоступна.

    Кэш на процесс: агент создаётся обёрткой без cfg (`decide_petrophysics`),
    но политика (`checks.petro_methods`, `checks.properties`) живёт в config.yaml.
    Недоступная конфигурация не отменяет решение по данным проекта.
    """
    global _DEFAULT_CFG, _DEFAULT_CFG_TRIED
    if not _DEFAULT_CFG_TRIED:
        _DEFAULT_CFG_TRIED = True
        try:
            from core.config import load_config
            _DEFAULT_CFG = load_config()
        except Exception:                       # noqa: BLE001 — конфигурация опциональна
            _DEFAULT_CFG = None
    return _DEFAULT_CFG


class PetrophysicsAgent(BaseAgent):
    """Решение агента петрофизики: метод, кубы, диапазоны и учёт фаций из данных."""

    agent_id = "AG_PETROPHYSICS"
    label = "Агент петрофизики"

    def __init__(self, cfg=None, **kwargs) -> None:
        super().__init__(cfg if cfg is not None else _default_cfg(), **kwargs)

    # -- данные конфигурации ------------------------------------------------------
    def _cfg_value(self, dotted: str, default=None):
        if self.cfg is None:
            return default
        return self.cfg.get(dotted, default)

    def allowed_methods(self) -> list[str]:
        """Разрешённые методы интерполяции (ДАННЫЕ `checks.petro_methods`)."""
        value = self._cfg_value("checks.petro_methods", [])
        return [str(x).strip().lower() for x in (value or []) if str(x).strip()]

    def cube_roles(self) -> dict[str, str]:
        """Куб → роль (ДАННЫЕ `checks.properties.<роль>.cube`)."""
        props = self._cfg_value("checks.properties", {}) or {}
        out: dict[str, str] = {}
        for role, item in props.items():
            if isinstance(item, dict) and item.get("cube"):
                out[str(item["cube"])] = str(role)
        return out

    # -- решение -----------------------------------------------------------------
    def decision(self, project: dict, evidence: dict | None = None) -> dict:
        """Решение по петрофизике: {enabled, method, cubes, variogram, ranges, zone}."""
        petro = self._section(project, "petrophysics")
        cubes = [c for c in (petro.get("cubes") or []) if isinstance(c, dict)]
        method = str(petro.get("method") or "").strip().lower()
        vg = petro.get("variogram") or {}
        variogram = {
            "range_main": self._num(vg.get("range_main"), 0.0),
            "nugget_effect": self._num(vg.get("nugget_effect"), 0.0),
            "sill": self._num(vg.get("sill"), 0.0),
        }
        allowed = self.allowed_methods()
        method_ok = None                      # None = не проверено (нет данных политики)
        if method and allowed:
            method_ok = method in allowed

        thresholds = self._section(project, "thresholds")
        roles = self.cube_roles()
        ranges: dict[str, list[float]] = {}
        unknown: list[str] = []
        for cube in cubes:
            name = str(cube.get("cube") or "")
            role = roles.get(name, "")
            rng = thresholds.get(role) if role else None
            if isinstance(rng, (list, tuple)) and len(rng) == 2:
                ranges[name] = [self._num(rng[0], 0.0), self._num(rng[1], 0.0)]
            else:
                # Порог физичности не найден → это НЕ «прошло»: фиксируем пробел.
                unknown.append(f"thresholds.{role or name}")

        zone = self._zone_decision(petro)
        permeability_fit = self._permeability_fit(petro)
        enabled = bool(cubes)
        if enabled:
            names = ", ".join(f"{c.get('log')}→{c.get('blocked')}→{c.get('cube')}"
                              for c in cubes)
            reason = (f"петрофизика: метод «{method or 'не задан'}», кубы [{names}], "
                      f"вариограмма range={variogram['range_main']:g} м, "
                      f"nugget={variogram['nugget_effect']:g}; {zone['reason']}")
            if method_ok is False:
                reason += f"; метод вне разрешённого набора {allowed}"
        else:
            reason = ("петрофизика: cubes не заданы — стадия отключается "
                      "(неизвестное != ложь)")
        reason += f"; связь k-φ по керну: {permeability_fit.get('status')}"
        return {"enabled": enabled, "method": method, "method_ok": method_ok,
                "cubes": cubes, "variogram": variogram, "ranges": ranges,
                "zone": zone, "unknown": unknown, "reason": reason,
                "permeability_fit": permeability_fit,
                "parameters": {}}

    # -- связь k = f(φ) по керну: вызов domain/petrophysics_fit.py -----------------
    def _permeability_fit(self, petro: dict) -> dict:
        """Подгонка k = f(φ) по керну ОТДЕЛЬНО по литотипам — своим модулем.

        Путь к таблице керна — ДАННЫЕ поля (`petrophysics.core_data`); не задан →
        `not_applicable` (правило 6: подбор без данных не выдаётся за факт).
        Порог достаточности, r2, роли колонок и бланки — ИЗ ОНТОЛОГИИ.
        """
        try:
            from core.config import SERVICE_ROOT
        except Exception:                           # noqa: BLE001 — путь не критичен
            SERVICE_ROOT = Path(__file__).resolve().parents[1]
        from domain import petrofacies_data, petrophysics_fit

        rules = self._rules()
        declared = str(petro.get("core_data") or petro.get("core_table") or "").strip()
        if not declared:
            return {"status": petrophysics_fit.STATUS_NOT_APPLICABLE,
                    "reason": ("путь к таблице керна не задан в данных поля "
                               "(petrophysics.core_data) — подгонка k-φ не выполняется"),
                    "min_pairs": petrofacies_data.min_pairs(rules),
                    "issues": []}
        path = Path(declared)
        if not path.is_absolute():
            path = Path(SERVICE_ROOT) / path
        if not path.is_file():
            return {"status": petrophysics_fit.STATUS_NOT_APPLICABLE,
                    "reason": f"файл керна не найден: {path}",
                    "min_pairs": petrofacies_data.min_pairs(rules), "issues": []}
        result = petrophysics_fit.fit_from_rows(read_table(path), rules)
        return {"status": result.get("status"), "lithotypes": result.get("lithotypes"),
                "fits": result.get("fits"), "pooled": result.get("pooled"),
                "min_pairs": result.get("min_pairs"),
                "source": result.get("source"),
                "columns": result.get("columns"), "skipped": result.get("skipped"),
                "issues": result.get("issues") or [],
                "path": str(path)}

    def _rules(self) -> dict:
        """Правила из онтологии (кэш на экземпляр агента; пусто — неизвестное)."""
        cached = getattr(self, "_rules_cache", None)
        if cached is None:
            try:
                from domain import petrofacies_data
                cached = petrofacies_data.load_rules(self.cfg)
            except Exception:                       # noqa: BLE001 — правила опциональны
                cached = {}
            self._rules_cache = cached
        return cached

    def _zone_decision(self, petro: dict) -> dict:
        """Способ учёта фаций (зон) при распространении свойства — из ДАННЫХ.

        Учёт фаций возможен только при заданном кубе зон: интерполяция «по зонам»
        без куба зон не выполняется (проверено реальным прогоном v7 — «No zones or
        regions are selected for interpolation!»). Если данных о зоне нет, выбирается
        БЕЗзонная форма, и это решение (а не «ложь»): `mode = no_zone`.
        """
        facies = petro.get("facies") if isinstance(petro.get("facies"), dict) else {}
        zone_cube = str(facies.get("zone_cube") or petro.get("zone_cube") or "")
        want_zone = bool(facies.get("use_zone", petro.get("use_zone", False)))
        if want_zone and zone_cube:
            return {"use_zone": True, "cube": zone_cube, "mode": "zone",
                    "reason": f"учёт фаций включён по кубу зон «{zone_cube}»"}
        mode = "no_zone" if not zone_cube else "no_zone_by_policy"
        why = ("куб зон в данных не задан" if not zone_cube
               else "учёт фаций отключён данными (use_zone=false)")
        return {"use_zone": False, "cube": zone_cube, "mode": mode,
                "reason": f"учёт фаций: беззонная форма — {why}"}


def decide_petrophysics(project: dict, evidence: dict | None = None, *,
                        cfg=None, kb=None, registry=None, gate_engine=None) -> dict:
    """Тонкая обёртка (совместимость v5): решение :class:`PetrophysicsAgent`.

    `cfg`/`kb`/`registry`/`gate_engine` — kw-only (интеграция `StageRunner`:
    политика полноты входов, опыт БЗ, движок гейтов). Старый двухаргументный
    вызов продолжает работать без изменений.
    """
    return PetrophysicsAgent(cfg, kb=kb, registry=registry,
                             gate_engine=gate_engine).decide(project, evidence)
