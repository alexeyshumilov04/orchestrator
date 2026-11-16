"""Каталог наборов данных: ЧТО реально есть в наборе (влияет на план).

Данные разные — не зашиваем конкретное месторождение. Каждая подпапка корня =
отдельный набор. Ключевое отличие от «подсчёта файлов»: набор отдаёт список
ДОСТУПНЫХ ТИПОВ данных (logs, surfaces, wellheads, welltops, core, seismic,
production_history, decks, projects, archives). Именно от них зависит план:
операция, для которой нет входных данных, помечается и не исполняется.
"""
from __future__ import annotations

from pathlib import Path

# Тип данных -> шаблоны имён файлов (учитываем регистр через нижий регистр совпадения).
DATA_KINDS: dict[str, tuple[str, ...]] = {
    "logs": ("*.las",),
    "surfaces": ("*.irap",),
    "wellheads": ("wellhead*.txt", "*устья*.txt", "*устьев*.txt"),
    "welltops": ("welltop*.txt", "*отбивк*.txt"),
    "core": ("*.core", "*core*.csv", "*керн*.csv"),
    "seismic": ("*.sgy", "*.segy", "*.seis"),
    "production_history": ("*history*.csv", "*история*.csv", "*welltest*.csv", "*.his"),
    "decks": ("*.data",),
    "projects": ("*.snp",),
    "archives": ("*.zip", "*.7z"),
    # Универсальность (проверка на втором объекте, ТЕСТ2): файлы БЕЗ расширения и иные
    # форматы полей. Роли/маски для них описаны в онтологии
    # (ontology/input_recognition_rules.yaml), здесь — только каталог форматов.
    "deviation": ("*.dev",),
    "well_header": ("Well*Header*", "*header*.txt", "*устья*"),
    "well_tops": ("Well*Top*", "*отбивк*"),
    "log_mnemonics": ("*Mnemonic*", "*мнемоник*"),
    "surfaces_any": ("*.irap", "*.cps", "*.txt"),
}


def _find(root: Path, patterns: tuple[str, ...], limit: int = 400) -> list[Path]:
    """Найти файлы по любому из шаблонов (регистронезависимо)."""
    root = Path(root)
    found: list[Path] = []
    seen: set[str] = set()
    for pattern in patterns:
        for p in root.rglob(pattern):
            if not p.is_file():
                continue
            key = str(p).lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(p)
            if len(found) >= limit:
                return sorted(found)
    return sorted(found)


def inventory(root: Path) -> dict[str, list[str]]:
    """Инвентаризация типов данных внутри набора (пути как строки)."""
    root = Path(root)
    result: dict[str, list[str]] = {}
    for kind, patterns in DATA_KINDS.items():
        result[kind] = [str(p) for p in _find(root, patterns)]
    return result


def available_kinds(root: Path) -> list[str]:
    """Доступные типы данных набора (непустые)."""
    inv = inventory(root)
    return sorted(k for k, v in inv.items() if v)


def inspect_dataset(path: Path) -> dict:
    """Описание набора: имя, путь, доступные типы, образцы файлов, архивы."""
    path = Path(path)
    inv = inventory(path)
    counts = {k: len(v) for k, v in inv.items()}
    return {
        "name": path.name,
        "path": str(path),
        "kinds": sorted(k for k, v in inv.items() if v),
        "counts": counts,
        "well_logs": counts.get("logs", 0),
        "surfaces": counts.get("surfaces", 0),
        "has_wellhead": counts.get("wellheads", 0) > 0,
        "has_welltop": counts.get("welltops", 0) > 0,
        "tnav_projects": counts.get("projects", 0),
        "archives": [Path(z).name for z in inv.get("archives", [])],
        "sample_logs": [Path(x).name for x in inv.get("logs", [])[:5]],
        "sample_surfaces": [Path(x).name for x in inv.get("surfaces", [])[:8]],
    }


def scan_datasets(root: Path) -> list[dict]:
    """Просканировать корень: подпапка = набор; если вложенных наборов нет — сам корень."""
    root = Path(root)
    if not root.exists():
        return []
    datasets: list[dict] = []
    for child in sorted(root.iterdir()):
        if child.is_dir():
            datasets.append(inspect_dataset(child))
    if not datasets:
        probe = inspect_dataset(root)
        if probe["kinds"]:
            datasets.append(probe)
    return datasets


# -- предпочтительные входы (для сборки дека) --------------------------------
# ПРАВИЛО 1: конкретные имена файлов поля (например «depth_*.irap») в коде НЕ живут.
# Маски предпочтений — ДАННЫЕ онтологии (`ontology/input_recognition_rules.yaml`
# → `preferred_names`); нет правила → берётся первый кандидат по алфавиту
# (неизвестное не подменяется «угаданным» значением, правило 6).
_ONTOLOGY_RULES = Path(__file__).resolve().parent.parent / "ontology" / "input_recognition_rules.yaml"


def preferred_names(kind: str) -> tuple[str, ...]:
    """Маски предпочтений входа для роли — ИЗ ДАННЫХ онтологии (иначе пусто)."""
    try:
        import yaml
        data = yaml.safe_load(_ONTOLOGY_RULES.read_text(encoding="utf-8")) or {}
    except Exception:                                   # noqa: BLE001 — данные опциональны
        return ()
    value = (data.get("preferred_names") or {}).get(kind)
    return tuple(str(item) for item in value) if isinstance(value, (list, tuple)) else ()


def _pick_by_name(candidates: list[str], preferred: tuple[str, ...]) -> Path | None:
    """Первый кандидат по маске (точное имя → glob → вхождение токена)."""
    import fnmatch
    by_lower = {Path(c).name.lower(): Path(c) for c in candidates}
    for pattern in preferred:
        low = pattern.lower()
        if low in by_lower:
            return by_lower[low]
        for name_low, path in sorted(by_lower.items()):
            if fnmatch.fnmatch(name_low, low):
                return path
    for pattern in preferred:
        token = pattern.replace("*.txt", "").replace("*", "").lower()
        for low, path in sorted(by_lower.items()):
            if token and token in low:
                return path
    return sorted(Path(c) for c in candidates)[:1][0] if candidates else None


def resolve_inputs(dataset_root: Path) -> dict:
    """Конкретные входы набора для сборки дека/операций.

    Возвращает: surface (IRAP), wellheads, welltops, logs (список), decks.
    Маски предпочтений — из онтологии (правило 1), не из кода.
    """
    root = Path(dataset_root)
    inv = inventory(root)
    return {
        "surface": _pick_by_name(inv.get("surfaces", []), preferred_names("surface")),
        "wellheads": _pick_by_name(inv.get("wellheads", []), preferred_names("wellheads")),
        "welltops": _pick_by_name(inv.get("welltops", []), preferred_names("welltops")),
        "logs": [Path(x) for x in inv.get("logs", [])],
        "decks": [Path(x) for x in inv.get("decks", [])],
    }
