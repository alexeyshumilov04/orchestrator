"""Единое отображение ОНТОЛОГИЯ <-> ДАННЫЕ (kinds).

Онтология описывает входы операций КЛАССАМИ (`data:LasRaw`, `data:WellheadRaw`, ...),
а инвентаризация набора — строками kinds (`logs`, `wellheads`, ...). Ранее связь жила
только в хардкоде `domain/capabilities._STAGE_REQUIRES` (по этапам), из-за чего
контракт операции `op_load_data` (требует `CoreRaw/SeismicRaw/...`) не влиял на план.

Здесь — единственное место отображения. Благодаря ему «план по данным» строится из
I/O-контракта онтологии (core:input), а не из хардкода: обязательные типы становятся
блокирующими `requires`, опциональные — «желательными» `optional`.
"""
from __future__ import annotations

# Онтологический класс сырья -> тип набора (см. core.datasets.DATA_KINDS)
RAW_TO_KIND: dict[str, str] = {
    "data:LasRaw": "logs",
    "data:WellheadRaw": "wellheads",
    "data:WelltopRaw": "welltops",
    "data:CoreRaw": "core",
    "data:SeismicRaw": "seismic",
    "data:ProductionHistoryRaw": "production_history",
    "data:DeckRaw": "decks",
}

# Сырые входы, отсутствие которых НЕ блокирует узел (фиксируется как «нет данных»).
OPTIONAL_RAW: frozenset[str] = frozenset({"data:CoreRaw", "data:SeismicRaw"})

# Узел-инвентаризация: определяет ГРАНИЦУ набора. Его контрактные входы информативны,
# а не блокирующие (иначе «Сбор исходных данных» не запустился бы на неполном наборе).
DISCOVERY_OPS: frozenset[str] = frozenset({"proc:op_load_data"})

# Контракт op_load_data (для отчёта о наборе в обработчике узла).
LOAD_DATA_CONTRACT: tuple[str, ...] = (
    "data:LasRaw", "data:WellheadRaw", "data:WelltopRaw", "data:CoreRaw", "data:SeismicRaw",
)


def kind_for(raw_class: str) -> str | None:
    """Тип набора для онтологического класса сырья (или None, если это не сырьё)."""
    return RAW_TO_KIND.get(raw_class)


def contract_kinds(op_id: str, inputs, *,
                   base_optional: frozenset[str] = OPTIONAL_RAW) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Контракт узла БЕЗ учёта фактических данных: (required_kinds, optional_kinds).

    Для узла-инвентаризации (`DISCOVERY_OPS`) все контрактные входы «желательные».
    Не-сырьевые входы (`dom:*`, `qc:*`) игнорируются — это артефакты других узлов.
    """
    optional = frozenset(RAW_TO_KIND) if op_id in DISCOVERY_OPS else base_optional
    required: list[str] = []
    opt: list[str] = []
    for raw in inputs or ():
        kind = kind_for(raw)
        if kind is None:
            continue
        (opt if raw in optional else required).append(kind)
    return tuple(dict.fromkeys(required)), tuple(dict.fromkeys(opt))


def split_inputs(raw_classes, available_kinds, *,
                 optional: frozenset[str] = OPTIONAL_RAW
                 ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Разложить входы операции по фактическим данным набора.

    Возвращает (required, missing, optional, optional_missing):
      * required / missing          — обязательные типы: есть / отсутствуют;
      * optional / optional_missing — желательные типы: есть / отсутствуют.
    """
    available = set(available_kinds or ())
    required: list[str] = []
    missing: list[str] = []
    opt: list[str] = []
    opt_missing: list[str] = []
    for raw in raw_classes or ():
        kind = kind_for(raw)
        if kind is None:
            continue
        if raw in optional:
            (opt if kind in available else opt_missing).append(kind)
        else:
            (required if kind in available else missing).append(kind)
    uniq = lambda seq: tuple(dict.fromkeys(seq))  # noqa: E731
    return uniq(required), uniq(missing), uniq(opt), uniq(opt_missing)
