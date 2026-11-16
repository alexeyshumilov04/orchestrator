"""Конвертация таблицы отбивок поля в ПЛОСКУЮ таблицу для импорта маркеров.

Зачем: шаг tNavigator `marker_import_txt_format` ожидает плоскую таблицу с колонками
`Well, Marker, MD` (default-шаблон: `columns=["Well", "Marker", "MD"]`). Если файл поля в
другом формате (проверено на ТЕСТ2: Petrel Well Tops), импорт не создаёт маркеров, и
потребители роли `reservoir_top` падают с «Parameter "Well Marker" is not valid».

Правила чтения форматов — ДАННЫЕ онтологии (`ontology/input_recognition_rules.yaml →
formats`); доменных имён в коде нет. Инструмент НИКОГДА не пишет в каталог данных поля:
результат кладётся туда, куда указано (`--out`), по умолчанию — в stdout.

Использование:
    python tools/prepare_marker_table.py --source <файл отбивок> [--out <файл>] [--dry]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SENTINEL_BLANKS = (-999.0, -999.2, -999.25, 9999900.0)


def _read_text(path: Path) -> str:
    """Прочитать файл, перебрав кодировки (Petrel-файлы бывают в cp1251)."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1251", "utf-16"):
        try:
            return raw.decode(enc)
        except Exception:  # noqa: BLE001
            continue
    return raw.decode("utf-8", errors="replace")


def parse_well_tops(path: Path) -> tuple[list[tuple[str, str, float]], str]:
    """Разобрать отбивки: [(скважина, маркер, глубина)], имя распознанного формата."""
    lines = _read_text(path).splitlines()
    head = (lines[0] if lines else "").strip()

    # Petrel Well Tops: колонки X Y Z MD Type "Surface Name" "Well Name" Interpreter
    if head.lower().startswith("#petrel") or "petrel well tops" in head.lower():
        rows: list[tuple[str, str, float]] = []
        for line in lines:
            s = line.strip()
            if not s or s.startswith("#") or s.upper().startswith(("BEGIN", "END", "VERSION")):
                continue
            quoted = [q for q in re.findall(r'"([^"]*)"', s)]
            if len(quoted) < 2:
                continue
            marker, well = quoted[0].strip(), quoted[1].strip()
            nums = [t for t in s.split() if re.fullmatch(r"-?\d+(\.\d+)?", t)]
            if not marker or not well or len(nums) < 3:
                continue
            try:
                # КОЛОНКИ Petrel: X, Y, Z, MD. Импортёр маркеров ожидает MD —
                # ПОЛОЖИТЕЛЬНУЮ измеренную глубину, а не Z (абсолютная отметка, ниже
                # уровня моря отрицательная). Проверено: с Z (отрицательные) импорт не
                # создавал объекты-маркеры, и потребители падали «Well Marker is not valid».
                depth = float(nums[3]) if len(nums) >= 4 else float(nums[2])
            except ValueError:
                continue
            if any(abs(depth - b) < 1e-6 for b in SENTINEL_BLANKS):
                continue
            rows.append((well, marker, depth))
        return rows, "petrel_well_tops"

    # Плоская таблица: порядок колонок бывает разным (проверено: у Герасимовского файл
    # `well, marker, MD, label` — табуляция, 4 колонки). Глубину берём как ПЕРВОЕ числовое
    # поле начиная с третьей колонки, а не «последнее» (иначе в глубину попадала метка).
    rows = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.replace(",", " ").replace("\t", " ").split()
        if len(parts) < 3:
            continue
        depth = None
        for tok in parts[2:]:
            try:
                depth = float(tok)
            except ValueError:
                continue
            break
        if depth is None:
            continue
        if any(abs(depth - b) < 1e-6 for b in SENTINEL_BLANKS):
            continue
        rows.append((parts[0], parts[1], depth))
    return rows, "flat_table"


def to_flat_table(rows: list[tuple[str, str, float]]) -> str:
    """Плоская таблица `Well Marker MD` (табуляция)."""
    lines = ["Well\tMarker\tMD"]
    lines += [f"{w}\t{m}\t{d:.2f}" for w, m, d in rows]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Подготовка плоской таблицы отбивок для импорта")
    ap.add_argument("--source", required=True, help="файл отбивок поля")
    ap.add_argument("--out", default="", help="куда записать результат (по умолчанию stdout)")
    ap.add_argument("--dry", action="store_true", help="только показать статистику")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.is_file():
        print(f"файл не найден: {src}")
        return 2
    rows, fmt = parse_well_tops(src)
    wells = {w for w, _m, _d in rows}
    markers = {m for _w, m, _d in rows}
    print(f"формат: {fmt} | строк: {len(rows)} | скважин: {len(wells)} | маркеров: {len(markers)}")
    if not rows:
        print("пустая таблица — импорт маркеров не получит данных (проверить формат/кодировку)")
        return 1
    table = to_flat_table(rows)
    if args.dry or not args.out:
        head = "\n".join(table.splitlines()[:5])
        print("--- начало таблицы ---")
        print(head)
        return 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(table, encoding="utf-8")
    print(f"записано: {out} ({len(rows)} строк)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
