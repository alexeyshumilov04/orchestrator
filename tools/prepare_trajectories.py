"""Подготовка ТРАЕКТОРИЙ скважин (.dev Petrel) для импорта в tNavigator.

Формат источника (проверено на данных второго объекта, `dev/<well>.dev`):

    # WELL NAME:              119G
    # WELL HEAD X-COORDINATE: 451698.7882159
    MD      X             Y             Z          TVD     DX      DY
    0.000000 451698.788216 7012276.417723 113.810000 0.000000 0.000000 0.000000
    ...

Импортёр (`wells_import_path_deviation_format`) ожидает плоскую таблицу
`well_input_data_type="wid_md_x_y_z"` — то есть **well, MD, X, Y, Z**.

Имя скважины: приоритет — имя ФАЙЛА (оно совпадает с UWI из головок скважин проекта,
например `341_119G`), запасной вариант — `WELL NAME` из заголовка (там короткое `119G`).
Запись — только туда, куда указано (`--out`), по умолчанию stdout: данные поля не трогаем.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HEADER_KEYS = ("MD", "X", "Y", "Z")


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1251", "utf-16"):
        try:
            return raw.decode(enc)
        except Exception:  # noqa: BLE001
            continue
    return raw.decode("utf-8", errors="replace")


def parse_deviation(path: Path) -> list[tuple[str, float, float, float, float]]:
    """Разобрать .dev: [(скважина, MD, X, Y, Z)]."""
    text = _read_text(path)
    lines = text.splitlines()
    header_name = ""
    for line in lines[:12]:
        m = re.search(r"WELL NAME:\s*(\S+)", line, re.IGNORECASE)
        if m:
            header_name = m.group(1).strip()
            break
    well = path.stem or header_name
    rows: list[tuple[str, float, float, float, float]] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.replace(",", " ").split()
        if len(parts) < 4:
            continue
        try:
            md, x, y, z = (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
        except ValueError:
            continue                            # строка заголовка колонок — пропускаем
        rows.append((well, md, x, y, z))
    return rows


def to_flat_table(all_rows: list[tuple[str, float, float, float, float]]) -> str:
    out = ["Well\tMD\tX\tY\tZ"]
    out += [f"{w}\t{md:.3f}\t{x:.3f}\t{y:.3f}\t{z:.3f}" for w, md, x, y, z in all_rows]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Подготовка плоской таблицы траекторий (well, MD, X, Y, Z)")
    ap.add_argument("--source", required=True, help="каталог с .dev или один файл")
    ap.add_argument("--out", default="", help="куда записать результат (по умолчанию stdout)")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    src = Path(args.source)
    files = sorted(src.rglob("*.dev")) if src.is_dir() else ([src] if src.is_file() else [])
    if not files:
        print(f"файлы .dev не найдены: {src}")
        return 2
    all_rows: list[tuple[str, float, float, float, float]] = []
    for f in files:
        all_rows += parse_deviation(f)
    wells = {w for w, _m, _x, _y, _z in all_rows}
    print(f"файлов: {len(files)} | строк: {len(all_rows)} | скважин: {len(wells)}")
    if not all_rows:
        print("пустая таблица — импорт траекторий не получит данных (проверить формат/кодировку)")
        return 1
    table = to_flat_table(all_rows)
    if args.dry or not args.out:
        print("--- начало таблицы ---")
        print("\n".join(table.splitlines()[:4]))
        return 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(table, encoding="utf-8")
    print(f"записано: {out} ({len(all_rows)} строк)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
