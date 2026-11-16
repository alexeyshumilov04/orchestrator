"""Структурный агент (AG_STRUCTURAL): рабочий интервал, «врез», план правок.

Агент отвечает на вопрос «как строить структуру» по ДАННЫМ проекта (секция
`structural:` проектного YAML) и свидетельствам этапа:

  * РАБОЧИЙ ИНТЕРВАЛ — маркеры кровли/подошвы (`interval_top_marker` /
    `interval_base_marker`) и покрытие интервала отбивками скважин (`welltops`);
  * ВРЕЗ / ЭРОЗИЯ — режим `erosion` (auto|on|off) и порог покрытия
    (`erosion_when_top_coverage_lt`): покрытие кровли НИЖЕ порога → пласт частично
    размыт → шаги вреза (`erosion_steps`) исполняются; ВЫШЕ/РАВНО → шаги
    ПРОПУСКАЮТСЯ (`skipped_by_policy`). `on`/`off` — принудительное решение
    человека (имеет приоритет над расчётом);
  * ПЛАН ПРАВОК (`edits`) — какие шаги этапа исполняются/пропускаются и для каких
    функций параметры взяты из БЗ;
  * ТЮНИНГ (`recall`/`suggest`) — параметры IDW/сглаживания/тренда предлагаются
    из БЗ ТОЛЬКО при наличии удачного опыта; опыта нет → параметры остаются из
    данных проекта, а факт отсутствия опыта честно пишется в `unknown`
    («неизвестное != ложь»).

Решение ДЕТЕРМИНИРОВАННОЕ (без LLM в числах). В коде нет ни одного имени
маркера/объекта/числа поля — только КЛЮЧИ данных; пороги и списки шагов приходят
из проектного YAML.

Каноническая реализация — :class:`StructuralAgent`. Прежний контракт
(`decide_erosion`, ключи `enabled/reason/coverage/top_marker/base_marker/mode/steps`)
сохранён: тонкая обёртка живёт в :mod:`agents.structure_policy`.
"""
from __future__ import annotations

from agents.base_agent import BaseAgent

# --- КЛЮЧИ данных (не значения поля) -----------------------------------------
_SEC_STRUCTURAL = "structural"          # секция проекта «структурные построения»
_Q_TOP = "interval_top_marker"          # маркер кровли рабочего интервала
_Q_BASE = "interval_base_marker"        # маркер подошвы рабочего интервала
_Q_MODE = "erosion"                     # auto | on | off
_Q_STEPS = "erosion_steps"              # шаги вреза (пропускаются решением агента)
_Q_THRESHOLD = "erosion_when_top_coverage_lt"   # порог покрытия кровли отбивками
_Q_FUNCTIONS = "functions"              # переопределения функций (данные)
_Q_PARAMETERS = "parameters"            # настраиваемые параметры функции
_Q_PIPELINE = "pipeline"                # этапы пайплайна (данные)
_Q_STEP_LIST = "steps"                  # шаги этапа
_Q_FUNCTION = "function"                # имя функции шага
_EV_WELLTOPS = "welltops"               # свидетельство: отбивки скважин

# --- режимы вреза (идентификаторы схемы, не домен) ---------------------------
_MODE_AUTO, _MODE_ON, _MODE_OFF = "auto", "on", "off"


class StructuralAgent(BaseAgent):
    """Решение структурного агента: интервал, врез, план правок и тюнинг."""

    agent_id = "AG_STRUCTURAL"
    label = "Структурный агент"

    def decision(self, project: dict, evidence: dict | None = None) -> dict:
        """Вердикт: {enabled, reason, coverage, interval, edits, parameters, …}."""
        st = self._section(project, _SEC_STRUCTURAL)
        top_marker = str(st.get(_Q_TOP) or "")
        base_marker = str(st.get(_Q_BASE) or "")
        steps = [str(x) for x in (st.get(_Q_STEPS) or [])]
        mode = str(st.get(_Q_MODE) or _MODE_AUTO)
        threshold = self._num(st.get(_Q_THRESHOLD), 1.0)

        tops = dict((evidence or {}).get(_EV_WELLTOPS) or {})
        total, with_top, with_base = self._coverage_counts(tops, top_marker, base_marker)
        coverage = (with_top / total) if (total and top_marker) else None

        enabled, reason = self._erosion_verdict(mode, coverage, threshold,
                                                with_top, total, top_marker)
        interval = {"top_marker": top_marker, "base_marker": base_marker,
                    "wells_total": total, "wells_with_top": with_top,
                    "wells_with_base": with_base,
                    "top_coverage": (round(coverage, 4) if coverage is not None else None)}

        tunable, suggested, unknown = self._tuning(project)
        edits = self._edits(steps, suggested, enabled)
        # ПЛАН ПРАВОК: при включённом врезе в план входят ЕГО шаги (параметры — из
        # данных пайплайна), дополненные подсказками БЗ. Значения не выдумываются.
        patches = dict(suggested)
        if enabled:
            for fn, params in self._erosion_plan(project, steps).items():
                patches.setdefault(fn, params)

        return {"enabled": enabled, "reason": reason,
                "coverage": (round(coverage, 4) if coverage is not None else None),
                "top_marker": top_marker, "base_marker": base_marker,
                "mode": mode, "steps": steps, "interval": interval,
                "edits": edits, "tunable_functions": tunable,
                "parameters": patches, "unknown": unknown}

    # -- расчёт покрытия ---------------------------------------------------------
    @staticmethod
    def _coverage_counts(tops: dict, top_marker: str,
                         base_marker: str) -> tuple[int, int, int]:
        """(всего скважин с отбивками, с кровлей интервала, с подошвой).

        Совпадение маркера — по началу имени (отбивка ``BAJ`` покрывает ``BAJ1``):
        так же, как в прежнем контракте (совместимость тестов v5).
        """
        def hits(marker: str) -> int:
            if not marker:
                return 0
            m = marker.upper()
            return sum(1 for marks in tops.values()
                       if any(str(name).upper().startswith(m) for name, _ in marks))

        return len(tops), hits(top_marker), hits(base_marker)

    # -- вердикт о врезе ---------------------------------------------------------
    @staticmethod
    def _erosion_verdict(mode: str, coverage: float | None, threshold: float,
                         with_top: int, total: int,
                         top_marker: str) -> tuple[bool, str]:
        """Решение о врезе: принудительное (on/off) или по покрытию отбивками."""
        if mode == _MODE_ON:
            return True, "erosion=on: решение оператора"
        if mode == _MODE_OFF:
            return False, "erosion=off: решение оператора"
        if not top_marker or not total:
            return False, ("нет отбивок или не задан interval_top_marker — "
                           "врез не строится (неизвестное != ложь)")
        enabled = coverage is not None and coverage < threshold
        if enabled:
            reason = (f"покрытие кровли {top_marker} отбивками {with_top}/{total} "
                      f"({coverage:.0%}) < порога {threshold:.0%}: пласт частично "
                      f"размыт — врез строится")
        else:
            reason = (f"покрытие кровли {top_marker} отбивками {with_top}/{total} "
                      f"({coverage:.0%}) >= порога {threshold:.0%}: врез не требуется")
        return enabled, reason

    # -- план правок -------------------------------------------------------------
    @staticmethod
    def _erosion_plan(project: dict, steps: list[str]) -> dict:
        """Параметры шагов вреза ИЗ ДАННЫХ пайплайна: {функция: parameters шага}."""
        want = set(steps)
        out: dict = {}
        for stage in project.get(_Q_PIPELINE) or []:
            for step in ((stage or {}).get(_Q_STEP_LIST) or []):
                fn = str((step or {}).get(_Q_FUNCTION) or "")
                if fn and fn in want:
                    out[fn] = dict((step or {}).get(_Q_PARAMETERS) or {})
        return out

    @staticmethod
    def _edits(steps: list[str], suggested: dict, enabled: bool) -> list[dict]:
        """План правок: что агент делает со шагами этапа и параметрами."""
        action = "run" if enabled else "skip"
        edits = [{"target": fn, "action": action,
                  "source": f"{_SEC_STRUCTURAL}.{_Q_STEPS}"} for fn in steps]
        edits += [{"target": str(fn), "action": "patch_parameters", "source": "kb"}
                  for fn in sorted(suggested or {})]
        return edits

    # -- тюнинг из БЗ ------------------------------------------------------------
    def _tuning(self, project: dict) -> tuple[list[str], dict, list[str]]:
        """(настраиваемые функции, подсказка параметров из БЗ, честные пробелы)."""
        tunable = self._tunable_functions(project)
        if not tunable:
            return [], {}, ["tuning: настраиваемые функции этапа в данных не "
                            "объявлены — подсказки БЗ не применяются"]
        suggested = self.suggest(functions=tunable) if self.kb is not None else {}
        if not suggested:
            return tunable, {}, ["tuning: удачного опыта в БЗ нет — параметры "
                                 "берутся из данных проекта"]
        return tunable, dict(suggested), []

    @staticmethod
    def _tunable_functions(project: dict) -> list[str]:
        """Функции, объявленные в ДАННЫХ настраиваемыми И присутствующие в пайплайне.

        Признак «настраиваемая» — у функции в секции переопределений заданы
        `parameters`; признак «в пайплайне» — функция вызывается шагом этапа.
        Оба признака — данные, ни одного имени функции в коде нет.
        """
        overrides = project.get(_Q_FUNCTIONS) or {}
        declared = {str(fn) for fn, spec in overrides.items()
                    if isinstance(spec, dict) and spec.get(_Q_PARAMETERS)}
        used = {str((step or {}).get(_Q_FUNCTION) or "")
                for stage in project.get(_Q_PIPELINE) or []
                for step in ((stage or {}).get(_Q_STEP_LIST) or [])}
        return sorted((declared & used) - {""})


def decide_erosion(project: dict, evidence: dict | None = None, *, cfg=None,
                   kb=None, registry=None, gate_engine=None) -> dict:
    """Тонкая обёртка (совместимость): решение :class:`StructuralAgent`."""
    return StructuralAgent(cfg, kb=kb, registry=registry,
                           gate_engine=gate_engine).decide(project, evidence)
