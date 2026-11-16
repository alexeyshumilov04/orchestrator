"""Чтение отбивок (Welltop) — ДАННЫЕ, а не хардкод.

Формат строк (без заголовка, табуляция/пробелы):
    well_name <TAB> marker <TAB> depth_m <TAB> label

`depth_m` — глубина кровли пласта (положительная, вниз от устья/дат). Для совместимости
со структурной поверхностью (TVDSS, отрицательные отметки) переводим в `-depth`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence


def read_welltops(path: Path) -> dict[str, list[tuple[str, float]]]:
    """Вернуть {well_name: [(marker, depth_m), ...]} из файла отбивок."""
    path = Path(path)
    # ФОРМАТО-ОСОЗНАННОЕ ЧТЕНИЕ (round 205): штатный разбор принимал координаты за имена
    # скважин — на Petrel-файле второго объекта выходило 1405 «скважин» вместо 79, из-за
    # чего проверка покрытия маркеров давала «0 из 1405» и гейт G-DATA останавливал этап.
    # Используем проверенный адаптер (он же готовит плоскую таблицу для импорта маркеров).
    try:
        import importlib.util
        tool = Path(__file__).resolve().parents[1] / "tools" / "prepare_marker_table.py"
        if tool.is_file():
            spec = importlib.util.spec_from_file_location("_pmt_read", tool)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)        # type: ignore[union-attr]
            rows, fmt = mod.parse_well_tops(path)
            if fmt == "petrel_well_tops" and rows:
                grouped: dict[str, list[tuple[str, float]]] = {}
                for w, m, d in rows:
                    grouped.setdefault(str(w), []).append((str(m), float(d)))
                return grouped
    except Exception:                           # noqa: BLE001 — остаётся прежний путь
        pass
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    out: dict[str, list[tuple[str, float]]] = {}
    for line in lines:
        parts = line.replace(",", "\t").split()
        if len(parts) < 3:
            continue
        well, marker = parts[0].strip(), parts[1].strip()
        try:
            depth = float(parts[2])
        except ValueError:
            continue
        out.setdefault(well, []).append((marker, depth))
    return out


def normalize_marker_wells(path: Path, canonical_names, *, inplace: bool = True) -> dict:
    """Привести имена скважин в файле отбивок к именам ПРОЕКТА (регистр/синонимы).

    Данные месторождения хранят одно и то же имя в разном регистре (`10G` в головках
    и в инклинометрии, `10g` в отбивках). тНав ищет скважину по имени и при промахе
    молча теряет маркеры — «Fail to add marker ... Well ... is not present in the
    project»; после этого IDW-горизонты остаются без данных и вырождаются. Здесь
    строки переписываются на КАНОНИЧЕСКОЕ имя (из `Wells/*.txt`, т.е. из
    инклинометрии), а отбивки скважин, которых в проекте нет, отбрасываются и
    перечисляются в отчёте. Зашитых имён нет — только сопоставление без регистра.
    """
    path = Path(path)
    if not path.is_file():
        return {"found": False, "kept": 0, "dropped_rows": 0, "unknown_wells": []}
    lookup: dict[str, str] = {}
    for name in canonical_names:
        key = str(name).strip()
        if key:
            lookup.setdefault(key.lower(), key)
    out_lines: list[str] = []
    kept = dropped = 0
    unknown: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        canon = lookup.get(parts[0].strip().lower())
        if canon is None:
            dropped += 1
            unknown[parts[0]] = unknown.get(parts[0], 0) + 1
            continue
        parts[0] = canon
        out_lines.append("\t".join(parts))
        kept += 1
    # F-28 (КРИТИЧНО): запись «на месте» только если РЕАЛЬНО что-то сохранилось.
    # Иначе пустой результат (например, формат файла не распознан: Petrel Well Tops)
    # затирал ИСХОДНЫЙ файл данных поля — воспроизведено: 564 640 Б → 2 Б на dry-run.
    # Правило 6: «нет распознанных строк» != «обнулить файл».
    if inplace and out_lines:
        path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return {"found": True, "kept": kept, "dropped_rows": dropped,
            "unknown_wells": sorted(unknown)}


def tops_summary(tops: dict[str, list[tuple[str, float]]],
                 reservoir_marker_tokens: Sequence[str] = ()) -> dict:
    """Сводка по отбивкам + оценка кровли резервуара в TVDSS (отрицательная).

    Мнемоники-кандидаты кровли — ДАННЫЕ поля (`markers.reservoir_top` /
    `markers.order` проектного графа), а не литералы кода: не заданы → оценка
    кровли не выдаётся (правило 6: неизвестное не подменяется «первым маркером»).
    """
    depths = [d for marks in tops.values() for _, d in marks]
    markers = {m for marks in tops.values() for m, _ in marks}
    result: dict = {"n_wells": len(tops), "n_markers": len(markers), "n_tops": len(depths)}
    if depths:
        result["depth_min"] = round(min(depths), 2)
        result["depth_max"] = round(max(depths), 2)
        result["depth_mean"] = round(sum(depths) / len(depths), 2)

    chosen: list[float] = []
    token = ""
    for token in [str(item) for item in (reservoir_marker_tokens or ()) if str(item)]:
        for marks in tops.values():
            hits = [d for m, d in marks if m.upper().startswith(token.upper())]
            if hits:
                chosen.append(min(hits))
                break
        if chosen:
            break
    if chosen:
        result["reservoir_top_tvdss"] = round(-(sum(chosen) / len(chosen)), 2)
        result["reservoir_top_marker"] = token
    return result
