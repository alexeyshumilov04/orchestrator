"""Данные-контракт для расчётных модулей петрофизики и фаций.

Правило 1 (жёсткое): в этом модуле НЕТ доменных значений — ни имён колонок, ни
мнемоник, ни бланков, ни порогов. Всё читается из онтологии (`ontology/*.yaml`)
по КЛЮЧАМ, а сами ключи и значения — данные:

    * `ontology/petrofacies_methods.yaml` — параметры алгоритмов и карта «роль →
      имена колонок»; его секция `sources` задаёт СПИСОК файлов онтологии, которые
      сшиваются в один набор правил (поздний перекрывает ранний, deep merge);
    * `ontology/petrophysics_rules.yaml` — достаточность выборки, лестница
      источников k-φ, проверки единиц/непрерывности;
    * `ontology/geomate_reuse_rules.yaml` — контракты GeoMate и бланк
      `validations.blank_sentinel.value` (LEGACY_NO_VALUE).

Правило 6: если данных/правил нет — функции возвращают `None`/`unknown`, а не
выдуманные числа. Ошибка чтения YAML не подменяется «правилом по умолчанию»:
набор правил становится пустым, и вызывающий модуль честно фиксирует unknown.

Источник методик — наработки GeoMate (см. `ontology/petrofacies_methods.yaml`),
перенесённые КАК ДАННЫЕ; кода GeoMate здесь нет.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

_ROOT = Path(__file__).resolve().parents[1]

#: файл-«сшивка»: его секция `sources` перечисляет файлы правил (ДАННЫЕ)
RULES_FILE = "petrofacies_methods.yaml"
#: аварийный список, если файл-сшивка недоступен (те же имена — данные)
DEFAULT_SOURCES = ("petrophysics_rules.yaml", "geomate_reuse_rules.yaml",
                   "petrofacies_methods.yaml")
_LOADED_KEY = "_loaded_sources"
_MISSING_KEY = "_missing_sources"


# ── чтение данных ────────────────────────────────────────────────────────────
def ontology_dir(cfg: Any = None, *, root: str | Path | None = None) -> Path:
    """Каталог онтологии: параметр → `ontology.root` конфига → папка сервиса.

    `ontology.root` в config.yaml указывает на каталог RDF-сборки (не на файлы
    правил), поэтому предпочитается каталог, где РЕАЛЬНО лежит файл-сшивка
    `petrofacies_methods.yaml`; иначе берётся первый существующий кандидат.
    """
    if root is not None:
        return Path(root)
    candidates: list[Path] = []
    if cfg is not None:
        try:
            candidates.append(Path(cfg.path("ontology.root", "ontology")))
        except Exception:                       # noqa: BLE001 — конфиг опционален
            pass
    candidates.append(_ROOT / "ontology")
    for candidate in candidates:
        if (candidate / RULES_FILE).is_file():
            return candidate
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[-1]


def read_yaml(path: str | Path) -> dict:
    """Прочитать YAML-словарь; нет файла/битый — `{}` (неизвестное != ложь)."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def deep_merge(base: dict, over: Mapping[str, Any]) -> dict:
    """Рекурсивное слияние: скаляры/списки позднего файла перекрывают ранние."""
    out = dict(base)
    for key, value in (over or {}).items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[str(key)] = deep_merge(out[key], value)
        else:
            out[str(key)] = value
    return out


def load_rules(cfg: Any = None, *, root: str | Path | None = None,
               sources: Sequence[str] | None = None,
               filename: str = RULES_FILE) -> dict:
    """Собрать набор правил из файлов онтологии (порядок — секция `sources`).

    Возвращает объединённый словарь. Служебные ключи `_loaded_sources` /
    `_missing_sources` показывают, что реально прочитано (проверяемость).
    """
    base = ontology_dir(cfg, root=root)
    glue = read_yaml(base / filename)
    if sources is None:
        declared = glue.get("sources")
        sources = tuple(str(s) for s in declared) if isinstance(declared, list) \
            and declared else DEFAULT_SOURCES
    merged: dict = {}
    loaded: list[str] = []
    missing: list[str] = []
    for name in sources:
        data = read_yaml(base / str(name))
        if data:
            merged = deep_merge(merged, data)
            loaded.append(str(name))
        else:
            missing.append(str(name))
    merged[_LOADED_KEY] = loaded
    merged[_MISSING_KEY] = missing
    return merged


def loaded_sources(rules: Mapping[str, Any] | None) -> list[str]:
    """Файлы онтологии, реально прочитанные при сборке правил (проверяемость)."""
    value = get(rules, _LOADED_KEY, [])
    return [str(item) for item in value] if isinstance(value, (list, tuple)) else []


def missing_sources(rules: Mapping[str, Any] | None) -> list[str]:
    """Объявленные, но недоступные файлы правил (честный unknown, не «правило»)."""
    value = get(rules, _MISSING_KEY, [])
    return [str(item) for item in value] if isinstance(value, (list, tuple)) else []


def get(rules: Mapping[str, Any] | None, dotted: str, default: Any = None) -> Any:
    """Значение по точечному пути (`a.b.c`) из набора правил."""
    node: Any = rules or {}
    for part in str(dotted).split("."):
        if not isinstance(node, Mapping) or part not in node:
            return default
        node = node[part]
    return node


def section(rules: Mapping[str, Any] | None, name: str) -> dict:
    """Секция правил как словарь (иначе `{}`)."""
    value = get(rules, name, {})
    return dict(value) if isinstance(value, Mapping) else {}


# ── бланки: «нет данных != ноль» (GeoMate normalise_number) ──────────────────
def blank_values(rules: Mapping[str, Any] | None) -> tuple[float, ...]:
    """Список бланков из ДАННЫХ: LAS-бланки + sentinel GeoMate + дополнения поля."""
    out: list[float] = []
    for dotted in ("log_preparation.null_values", "blank_handling.extra_values"):
        value = get(rules, dotted, [])
        if isinstance(value, (list, tuple)):
            for item in value:
                num = _to_float(item)
                if num is not None:
                    out.append(num)
    sentinel = _to_float(get(rules, "validations.blank_sentinel.value"))
    if sentinel is not None:
        out.append(sentinel)
    single = _to_float(get(rules, "blank_handling.value"))
    if single is not None:
        out.append(single)
    return tuple(dict.fromkeys(out))


def blank_tolerance(rules: Mapping[str, Any] | None) -> float:
    """Допуск сравнения с бланком — из данных (нет данных → строгое равенство)."""
    value = _to_float(get(rules, "blank_handling.abs_tolerance"))
    return float(value) if value is not None else 0.0


def is_blank(value: Any, rules: Mapping[str, Any] | None) -> bool:
    """True, если значение — бланк/None/нечисло (в т.ч. sentinel GeoMate)."""
    num = _to_float(value)
    if num is None or not math.isfinite(num):
        return True
    tol = blank_tolerance(rules)
    return any(abs(num - blank) <= tol for blank in blank_values(rules))


def clean_number(value: Any, rules: Mapping[str, Any] | None) -> float | None:
    """Бланк → `None` (никогда не ноль); иначе — конечное число."""
    if is_blank(value, rules):
        return None
    num = _to_float(value)
    return num if num is not None and math.isfinite(num) else None


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


# ── роли данных → колонки (имена колонок — ДАННЫЕ, не код) ───────────────────
def column_candidates(rules: Mapping[str, Any] | None, role: str) -> tuple[str, ...]:
    """Кандидаты имён колонок/свойств для роли (сверху вниз по приоритету)."""
    value = get(rules, f"columns.{role}", [])
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def pick_column(keys: Iterable[str], role: str,
                rules: Mapping[str, Any] | None) -> str:
    """Первая колонка из кандидатов роли, присутствующая в наборе ключей."""
    present = {str(k) for k in keys}
    for candidate in column_candidates(rules, role):
        if candidate in present:
            return candidate
    lowered = {k.lower(): k for k in present}
    for candidate in column_candidates(rules, role):
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return ""


def row_value(row: Mapping[str, Any], role: str,
              rules: Mapping[str, Any] | None) -> Any:
    """Значение роли из строки данных (по кандидатам колонок из онтологии)."""
    column = pick_column(row.keys(), role, rules)
    return row.get(column) if column else None


# ── достаточность выборки и лестница источников (из petrophysics_rules.yaml) ──
def min_pairs(rules: Mapping[str, Any] | None) -> int | None:
    """Порог достаточности пар: `core_data_contract.min_pairs` (единый источник)."""
    value = _to_float(get(rules, "core_data_contract.min_pairs"))
    if value is None:
        for item in source_ladder(rules):
            if isinstance(item, Mapping) and "core" == str(item.get("id", "")):
                value = _to_float(item.get("min_pairs"))
                break
    if value is None or value < 1:
        return None
    return int(value)


def source_ladder(rules: Mapping[str, Any] | None) -> list[dict]:
    """Лестница источников k-φ (core → literature → unknown) — ДАННЫЕ."""
    value = get(rules, "permeability_model.source_ladder", [])
    return [dict(item) for item in value if isinstance(item, Mapping)] \
        if isinstance(value, (list, tuple)) else []


def ladder_step(rules: Mapping[str, Any] | None, step_id: str) -> dict:
    """Шаг лестницы источников по id (`core`/`literature`/`unknown`)."""
    for item in source_ladder(rules):
        if str(item.get("id", "")) == str(step_id):
            return item
    return {}


def constraints(rules: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Обязательные правила-ограничения k-φ (id правил — ДАННЫЕ)."""
    value = get(rules, "permeability_model.constraints", [])
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def knowledge_status(rules: Mapping[str, Any] | None, step_id: str) -> str:
    """Статус знания шага лестницы (напр. `UNKNOWN`, `EVIDENCE_BACKED_CANDIDATE`)."""
    step = ladder_step(rules, step_id)
    return str(step.get("knowledge_status") or "")


# ── масштаб пористости: проценты → доли (порог — ДАННЫЕ) ─────────────────────
def scale_porosity(values: Sequence[float],
                   rules: Mapping[str, Any] | None) -> tuple[list[float], str]:
    """Привести пористость к долям по данным; возвращает (значения, пояснение).

    Если `porosity_scale.auto_detection=true` и максимум выше `max_above` —
    умножаем на `factor` (обычно 0.01). Нет правила → значения не меняются.
    """
    numbers = [float(v) for v in values]
    spec = section(rules, "porosity_scale")
    if not numbers or not spec.get("auto_detection"):
        return numbers, ""
    max_above = _to_float(spec.get("max_above"))
    factor = _to_float(spec.get("factor"))
    if max_above is None or factor is None:
        return numbers, ""
    if max(numbers) > max_above:
        return [v * factor for v in numbers], f"пористость приведена к долям (×{factor:g})"
    return numbers, ""
