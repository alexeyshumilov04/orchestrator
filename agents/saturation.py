"""Агент насыщения (AG_PVT_SCAL): контакты, способ их задания и контроль.

Данные читаются по КЛЮЧАМ (правило 1):

  * ``contacts.<контакт>``            — явная отметка контакта (модель в Z < 0);
  * ``contacts.<контакт>_offset_m``   — смещение контакта ОТ датума (кровли интервала);
  * ``contacts.datum_marker``         — маркер датума (иначе — кровля интервала
    ``structural.interval_top_marker``);
  * ``thresholds.swl``                — допустимый диапазон водонасыщенности;
  * ``scal.swof`` / ``scal.sgof``     — таблицы насыщенности (для контроля суммы);
  * ``contacts.fwl``                  — свободный уровень (контроль «контакт vs ЗСВ»);
  * ``checks.saturation_sum_tol``     — допуск суммы насыщенностей (данные конфигурации).

Правило 6: нет датума — контакт не вычисляется (``unknown``), а НЕ подставляется
нулём; нет таблиц SCAL — контроль суммы помечается ``unknown`` с причиной;
нет ЗСВ — проверка «контакт относительно ЗСВ» помечается ``unknown``.

Отметки модели ОТРИЦАТЕЛЬНЫЕ (модель в альтитудах), поэтому датум считается как
``−глубина`` отбивки по скважинам (KB не учитывается — та же конвенция, что в
сборе QA/QC-значений координатора); ВНК = датум − смещение.

Реализация — :class:`SaturationAgent` (наследник :class:`~agents.base_agent.BaseAgent`);
модульная функция :func:`decide_saturation` — тонкая обёртка для `StageRunner`.
"""
from __future__ import annotations

from agents.base_agent import BaseAgent
from agents.petrophysics import _default_cfg

# роли контактов: имя в решении → ключ в ДАННЫХ `contacts:`
_CONTACT_ROLES = (("oil_water", "owc"), ("gas_oil", "goc"), ("free_water", "fwl"))


class SaturationAgent(BaseAgent):
    """Решение агента насыщения: способ задания контактов и контроль — из данных."""

    agent_id = "AG_PVT_SCAL"
    label = "Агент насыщения (PVT/SCAL)"

    def __init__(self, cfg=None, **kwargs) -> None:
        super().__init__(cfg if cfg is not None else _default_cfg(), **kwargs)

    def decision(self, project: dict, evidence: dict | None = None) -> dict:
        """Решение по насыщению: {enabled, contacts, datum, controls, mode, reason}."""
        contacts = self._section(project, "contacts")
        structural = self._section(project, "structural")
        marker = str(contacts.get("datum_marker")
                     or structural.get("interval_top_marker") or "")
        ev = evidence if isinstance(evidence, dict) else {}
        datum_z, datum_note = self._datum(project, ev, contacts, marker)

        out: dict[str, dict] = {}
        unknown: list[str] = []
        for role, key in _CONTACT_ROLES:
            if contacts.get(key) not in (None, ""):
                out[role] = {"z": self._num(contacts.get(key), 0.0), "mode": "value"}
                continue
            offset = contacts.get(f"{key}_offset_m")
            if offset in (None, ""):
                continue                     # контакт не задан — это не контакт-«ложь»
            if datum_z is None:
                unknown.append(f"datum:{marker or 'не задан'}")
                out[role] = {"z": None, "mode": "offset", "offset_m":
                             self._num(offset, 0.0)}
            else:
                out[role] = {"z": round(datum_z - self._num(offset, 0.0), 3),
                             "mode": "offset", "offset_m": self._num(offset, 0.0)}

        controls = self._controls(project, contacts, unknown)
        scal_model = self._scal_model(project)
        for issue in (scal_model.get("issues") or [])[:3]:
            unknown.append(f"scal:{issue}")
        enabled = bool(out)
        if enabled:
            names = ", ".join(f"{role}={c['z'] if c['z'] is not None else 'unknown'}"
                              for role, c in out.items())
            reason = (f"насыщение: контакты [{names}]; датум — {datum_note or 'не определён'}; "
                      f"контроль: {controls['summary']}")
        else:
            reason = ("насыщение: контакты не заданы (нет contacts.<контакт> и "
                      "*_offset_m) — стадия отключается (неизвестное != ложь)")
        reason += (f"; J(Sw)/SCAL: {scal_model.get('status')}"
                   f" (J-подгонка: {scal_model.get('j_fit_status')}, концевые точки: "
                   f"{scal_model.get('end_points') or 'нет'})")
        return {"enabled": enabled, "contacts": out, "mode": self._mode(out),
                "datum": {"z": datum_z, "note": datum_note, "marker": marker},
                "controls": controls, "scal_model": scal_model,
                "unknown": unknown, "reason": reason,
                "parameters": {}}

    # -- J(Sw) и концевые точки по SCAL: вызов domain/saturation_model.py ---------
    def _scal_model(self, project: dict) -> dict:
        """Насыщение по J-функции/SCAL — своим модулем (правила — из онтологии).

        Матрицы SCAL поля (`scal.<имя>`) и их колонки описаны ДАННЫМИ
        (`ontology/petrofacies_methods.yaml: saturation.tables`). Нет SCAL →
        `not_applicable` с причиной (правило 6), а не «нулевая насыщенность».
        """
        try:
            from domain import petrofacies_data, saturation_model
        except Exception as exc:                    # noqa: BLE001 — модуль опционален
            return {"status": "unknown", "j_fit_status": "unknown", "end_points": {},
                    "issues": [f"модуль насыщения недоступен: {exc}"]}
        scal = self._section(project, "scal")
        rules = self._rules()
        result = saturation_model.from_project_scal(scal, rules)
        j_fit = result.get("j_fit") or {}
        points = result.get("end_points") or {}
        return {"status": result.get("status"),
                "j_fit_status": j_fit.get("status"),
                "end_points": points.get("values") or {},
                "end_points_status": points.get("status"),
                "tables_used": result.get("tables_used") or [],
                "source_rule": j_fit.get("source_rule") or points.get("source_rule"),
                "knowledge_status": (j_fit.get("knowledge_status")
                                     or points.get("knowledge_status")),
                "issues": result.get("issues") or []}

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

    # -- датум контакта ----------------------------------------------------------
    def _datum(self, project: dict, evidence: dict, contacts: dict,
               marker: str) -> tuple[float | None, str]:
        """Отметка датума (Z < 0): явные данные → отбивки скважин → unknown."""
        explicit = contacts.get("datum_z")
        if explicit not in (None, ""):
            return self._num(explicit, 0.0), f"datum_z из данных ({explicit})"
        tops = evidence.get("welltops") or {}
        depths: list[float] = []
        for marks in tops.values():
            for name, value in (marks or []):
                if marker and str(name).upper().startswith(marker.upper()):
                    try:
                        depths.append(float(value))
                    except (TypeError, ValueError):   # нечисловая отбивка — пропуск
                        continue
        if not depths:
            return None, (f"отбивки «{marker}» не найдены ({len(tops)} скважин) — "
                          f"датум неизвестен")
        depths.sort()
        mid = len(depths) // 2
        median = (depths[mid] if len(depths) % 2
                  else (depths[mid - 1] + depths[mid]) / 2.0)
        return (-median, f"отбивки «{marker}»: {len(depths)} точек, медиана "
                         f"{median:g} м (модель в альтитудах, Z = −глубина)")

    def _mode(self, out: dict) -> str:
        modes = {c.get("mode") for c in out.values()}
        if not modes:
            return "none"
        if modes == {"value"}:
            return "value"
        if modes == {"offset"}:
            return "offset"
        return "mixed"

    # -- контроль ----------------------------------------------------------------
    def _controls(self, project: dict, contacts: dict, unknown: list[str]) -> dict:
        """Контроль насыщения: диапазон Sw, сумма насыщенностей, контакт vs ЗСВ."""
        thresholds = self._section(project, "thresholds")
        swl = thresholds.get("swl")
        sw_range = None
        if isinstance(swl, (list, tuple)) and len(swl) == 2:
            sw_range = [self._num(swl[0], 0.0), self._num(swl[1], 0.0)]
        else:
            unknown.append("thresholds.swl")

        scal = self._section(project, "scal")
        scal_tables = [k for k in ("swof", "sgof") if scal.get(k)]
        if not scal_tables:
            unknown.append("scal.swof/scal.sgof")
        tol = None
        if self.cfg is not None:
            raw = self.cfg.get("checks.saturation_sum_tol")
            if raw is not None:
                tol = self._num(raw, 0.0)
        if tol is None:
            unknown.append("checks.saturation_sum_tol")

        fwl = contacts.get("fwl")
        if fwl in (None, ""):
            unknown.append("contacts.fwl")

        parts: list[str] = []
        parts.append(f"Sw в {sw_range}" if sw_range else "диапазон Sw не задан")
        parts.append(f"таблицы SCAL: {', '.join(scal_tables)}" if scal_tables
                     else "таблицы SCAL не заданы")
        parts.append(f"допуск суммы насыщенностей {tol:g}" if tol is not None
                     else "допуск суммы насыщенностей не задан")
        parts.append("ЗСВ задан — контакт сверяется с ним" if fwl not in (None, "")
                     else "ЗСВ не задан — сверка контакта с ЗСВ не выполняется")
        return {"sw_range": sw_range, "scal_tables": scal_tables,
                "sum_tolerance": tol, "fwl": fwl if fwl not in (None, "") else None,
                "summary": "; ".join(parts)}


def decide_saturation(project: dict, evidence: dict | None = None, *,
                      cfg=None, kb=None, registry=None, gate_engine=None) -> dict:
    """Тонкая обёртка: решение :class:`SaturationAgent` (для `StageRunner`).

    `cfg`/`kb`/`registry`/`gate_engine` — kw-only (интеграция `StageRunner`).
    """
    return SaturationAgent(cfg, kb=kb, registry=registry,
                           gate_engine=gate_engine).decide(project, evidence)
