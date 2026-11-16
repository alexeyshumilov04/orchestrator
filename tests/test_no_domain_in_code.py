"""Аудит ХАРДКОДА: домен — только в данных (жёсткое правило 1).

Проверяется, что в рантайм-коде (`agents/`, `core/`, `domain/`) НЕТ доменных значений:
имён объектов, маркеров, кубов, порогов, координат поля, путей к данным поля — ни в
литералах, ни в ИМЕНАХ, ни в КОММЕНТАРИЯХ (доменный пример в пояснении — тот же
перенос объекта в код). Значения-домен живут в `config.yaml`,
`ontology_project/*.yaml`, `domain/templates/`, `domain/ontology_rules/`, `ontology/`
— то есть читаются из ДАННЫХ.

Как работает:
  1) список «запрещённых» токенов СОБИРАЕТСЯ ИЗ ДАННЫХ: секция `hardcode_audit` в
     `config.yaml` (ключи-носители домена в проектном YAML + явные токены) и
     `workflow.foreign_tokens`; для каждого токена помнится КЛЮЧ-ИСТОЧНИК;
  2) из списка исключается ГЕНЕРИЧЕСКАЯ ЛЕКСИКА — значения-единицы измерения из
     ключей-носителей единиц (`*.units`), объявленные с обоснованием в
     `ontology/generic_vocabulary.yaml` (иначе слово-единица ложно ловило бы флаг
     «%» порога, ключ прогресса отчёта, имя статистики API);
  3) файлы разбираются через `ast` — учитываются строковые литералы кода
     (docstring-и исключаются), имена функций/переменных (мягкий класс) и тексты
     комментариев;
  4) исключения — тоже ДАННЫЕ: `hardcode_audit.allow` (префикс пути → токены).

Сгенерированный пакет QA/QC (`domain/qaqc/**`) и машинный эталон
(`domain/ontology_rules/reference_workflow.py`) исключены из скана: это ДАННЫЕ
(оцифрованный чеклист и выгрузка тНава), а не рукописный код.

Запуск:  python -X utf8 tests/test_no_domain_in_code.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_PASS: list[str] = []
_FAIL: list[str] = []

SCAN_DIRS = ("agents", "core", "domain")
SKIP_PREFIXES = ("domain/qaqc/", "domain/ontology_rules/reference_workflow.py")
DEFAULT_TOKEN_KEYS = (
    "marker", "markers", "reservoir_horizon", "field", "obj_name", "cube", "blocked",
    "log", "mesh", "grid", "properties", "input_horizon", "output_horizon",
    "result_horizon", "result_map_2d", "result_grid_property", "blocked_wells",
    "min_x", "min_y", "length_x", "length_y",
)


def check(name: str, cond: bool, detail: str = "") -> None:
    (_PASS if cond else _FAIL).append(name)
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + ("" if cond else f"  <-- {detail}"))


def _norm(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _string_literals(path: Path) -> list[tuple[int, str]]:
    """Строковые литералы кода: [(строка, значение)] БЕЗ docstring-ов."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    docs: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and \
                    isinstance(body[0].value, ast.Constant) and \
                    isinstance(body[0].value.value, str):
                docs.add(id(body[0].value))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and \
                id(node) not in docs:
            out.append((node.lineno, node.value))
    return out


def _names(path: Path) -> list[tuple[int, str]]:
    """Имена (функции/классы/переменные/атрибуты) — мягкий класс совпадений."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute):
            out.append((node.lineno, node.attr))
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            out.append((node.lineno, node.name))
        elif isinstance(node, ast.arg):
            out.append((node.lineno, node.arg))
    return out


def _tokens_from_project(project: dict, keys: tuple[str, ...]) -> dict[str, str]:
    """Доменные значения из ПРОЕКТНОГО YAML по ключам-носителям: {токен: ключ-источник}.

    Ключ-источник нужен, чтобы отличить ДОМЕН от ГЕНЕРИЧЕСКОЙ ЛЕКСИКИ: значение под
    ключом-носителем единиц измерения (`*.units`) — единица (percent/mD/…), а не имя
    объекта поля. Перечень таких значений — ДАННЫЕ `ontology/generic_vocabulary.yaml`.
    """
    found: dict[str, str] = {}

    def walk(node, key: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, str(k))
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, str):
            low = key.lower()
            if any(k in low for k in keys) and len(node.strip()) >= 2:
                found.setdefault(node.strip(), low)

    walk(project)
    return found


def _generic_unit_values() -> tuple[set[str], tuple[str, ...]]:
    """(значения-единицы, ключи-носители единиц) — ИЗ ДАННЫХ, с обоснованием."""
    path = ROOT / "ontology" / "generic_vocabulary.yaml"
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, Exception):                       # noqa: BLE001 — данные опциональны
        return set(), ("units", "unit")
    if not isinstance(data, dict):
        return set(), ("units", "unit")
    values = {str(item.get("value", "")).strip()
              for item in (data.get("generic_unit_values") or [])
              if isinstance(item, dict) and str(item.get("value", "")).strip()}
    policy = data.get("policy") if isinstance(data.get("policy"), dict) else {}
    carriers = tuple(str(key) for key in
                     (policy.get("carrier_keys_for_units") or ["units", "unit"]))
    return values, carriers


def _in_list(value: str, entries: set[str]) -> bool:
    """Литерал совпал с записью-исключением: точно ИЛИ запись — его префикс.

    Префиксное сравнение защищает от типовой ошибки данных: строка, скопированная
    из отчёта теста, обрезана там до 60 символов.
    """
    return value in entries or any(value.startswith(e) for e in entries if e)


def _scan(cfg) -> tuple[list[str], list[str], set[str], list[str], list[str], dict]:
    """(нарушения-литералы, нарушения-имена, токены, долг, нарушения-комментарии, отчёт).

    Комментарии проверяются ОТДЕЛЬНО (жёсткое правило 1 не делает исключения для
    пояснений: доменный пример в комментарии — тот же перенос объекта в код).
    Генерическая лексика (единицы измерения) исключается ТОЛЬКО по данным
    `ontology/generic_vocabulary.yaml` и ТОЛЬКО для значений из ключей-носителей
    единиц: иначе слово-единица ложно ловило бы флаг «%» порога или ключ прогресса.
    """
    keys = tuple(str(k) for k in
                 (cfg.get("hardcode_audit.token_keys") or DEFAULT_TOKEN_KEYS))
    explicit: set[str] = {str(t) for t in (cfg.get("workflow.foreign_tokens") or [])}
    explicit |= {str(t) for t in (cfg.get("hardcode_audit.tokens") or [])}
    explicit |= {str(t) for t in (cfg.get("hardcode_audit.domain_tokens") or [])}
    sources: dict[str, str] = {token: "config:hardcode_audit" for token in explicit}
    graph_dir = cfg.path("project.graph_dir", "ontology_project")
    if graph_dir.is_dir():
        import yaml
        # Берём ВСЕ проектные графы папки: имя файла может не совпадать с именем поля
        # (в данных: field: Герасимовское, файл gerasimovskoe.yaml).
        for cand in sorted([*graph_dir.glob("*.yaml"), *graph_dir.glob("*.yml")]):
            try:
                project = yaml.safe_load(cand.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            if isinstance(project, dict):
                for token, source_key in _tokens_from_project(project, keys).items():
                    sources.setdefault(token, f"{cand.name}:{source_key}")

    unit_values, unit_keys = _generic_unit_values()
    generic_excluded: dict[str, str] = {}
    tokens: set[str] = set()
    for token, source in sources.items():
        location = source.split(":", 1)[-1].lower()
        if location.endswith(tuple(unit_keys)) and token in unit_values:
            generic_excluded[token] = source
            continue
        tokens.add(token)
    tokens = {t for t in tokens if len(t) >= 2 and t.lower() not in
              {"on", "off", "auto", "true", "false", "none", "yes", "no", "grid", "log"}}

    allow = cfg.get("hardcode_audit.allow") or {}
    ident_allow = cfg.get("hardcode_audit.identifier_allow") or {}
    debt = cfg.get("hardcode_audit.known_debt") or {}
    literal_hits: list[str] = []
    name_hits: list[str] = []
    comment_hits: list[str] = []
    literal_debt: list[str] = []
    name_debt: list[str] = []
    for sub in SCAN_DIRS:
        for path in sorted((ROOT / sub).rglob("*.py")):
            rel = _norm(path)
            if any(rel.startswith(p) for p in SKIP_PREFIXES):
                continue
            # Исключения — ДАННЫЕ: точные строки (идентификаторы схемы онтологии,
            # напр. id гейта G-FACIES или профиль AG_FACIES) и точные имена.
            allowed_literals = {str(x) for x in (allow.get(rel) or [])}
            allowed_ids = {str(x) for x in (ident_allow.get(rel) or [])}
            # Известный долг (правило 1 ещё не доведено до конца) — виден, но не валит
            # сборку: точный перечень в данных, чтобы долг нельзя было скрыть.
            slot = debt.get(rel) if isinstance(debt.get(rel), dict) else {}
            debt_literals = {str(x) for x in (slot.get("literals") or [])}
            debt_ids = {str(x) for x in (slot.get("identifiers") or [])}
            for line, value in _string_literals(path):
                if value in allowed_literals:
                    continue
                found = [t for t in tokens if t in value]
                if not found:
                    continue
                row = (f"{rel}:{line}: литерал «{value[:60]}» содержит домен "
                       f"«{found[0]}»")
                (literal_debt if _in_list(value, debt_literals) else literal_hits).append(row)
            for line, value in _names(path):
                if value in allowed_ids:
                    continue
                # Идентификаторы сравниваются ПО СЕГМЕНТАМ имени (split по "_"),
                # иначе «LITERATURE_FILE» ложно совпадает с токеном «LIT».
                segments = [seg for seg in str(value).split("_") if seg]
                found = [t for t in tokens if t in segments]
                if not found:
                    continue
                row = f"{rel}:{line}: имя «{value}» содержит домен «{found[0]}»"
                (name_debt if _in_list(value, debt_ids) else name_hits).append(row)
            for line, text in _comment_texts(path):
                if text in allowed_literals or \
                        any(item in text for item in allowed_literals):
                    continue                                # идентификатор СХЕМЫ в тексте
                found = [t for t in tokens if t in text]
                if not found:
                    continue
                row = (f"{rel}:{line}: комментарий «{text[:60]}» содержит домен "
                       f"«{found[0]}»")
                (name_debt if _in_list(text, debt_literals) else comment_hits).append(row)
    report = {"generic_excluded": generic_excluded}
    return (sorted(set(literal_hits)), sorted(set(name_hits)), tokens,
            sorted(set(literal_debt)) + sorted(set(name_debt)),
            sorted(set(comment_hits)), report)


def _comment_texts(path: Path) -> list[tuple[int, str]]:
    """Тексты комментариев кода (`# …`) — построчно, вне строковых литералов."""
    out: list[tuple[int, str]] = []
    for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if "#" not in line:
            continue
        text = line.split("#", 1)[1].strip()
        if text:
            out.append((number, text))
    return out


def _generic_vocabulary_justified() -> bool:
    """Каждая позиция генерической лексики обязана иметь обоснование `why`."""
    path = ROOT / "ontology" / "generic_vocabulary.yaml"
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, Exception):                       # noqa: BLE001
        return False
    items = (data.get("generic_unit_values") or []) if isinstance(data, dict) else []
    if not items:
        return False
    return all(isinstance(item, dict) and str(item.get("value", "")).strip()
               and str(item.get("why", "")).strip() for item in items)


def main() -> int:
    from core.config import load_config

    cfg = load_config()
    literals, names, tokens, debt, comments, report = _scan(cfg)
    print(f"токенов домена собрано из данных: {len(tokens)}")
    excluded = report.get("generic_excluded") or {}
    if excluded:
        print(f"генерическая лексика (единицы измерения) исключена — ДАННЫЕ, "
              f"с обоснованием: {len(excluded)}")
        for token, source in sorted(excluded.items()):
            print(f"       [не домен] «{token}» ← {source}")

    check("hardcode: доменных литералов в agents/core/domain нет",
          not literals, f"{len(literals)} шт.: " + "; ".join(literals[:8]))
    check("hardcode: доменных имён в agents/core/domain нет",
          not names, f"{len(names)} шт.: " + "; ".join(names[:8]))
    check("hardcode: доменных КОММЕНТАРИЕВ в agents/core/domain нет",
          not comments, f"{len(comments)} шт.: " + "; ".join(comments[:8]))
    check("hardcode: токены домена приходят из данных",
          bool(tokens), "список токенов пуст — аудит бессмыслен")
    check("hardcode: известный долг зафиксирован в данных (не скрыт)",
          all("known_debt" in cfg.raw.get("hardcode_audit", {}) for _ in (0,)),
          "секция hardcode_audit.known_debt отсутствует")
    check("hardcode: генерическая лексика объявлена в данных с обоснованием",
          _generic_vocabulary_justified(),
          "ontology/generic_vocabulary.yaml: у каждой позиции обязан быть why")

    if debt:
        print(f"\n[WARN] известный долг правила 1 (вынести в данные): {len(debt)}")
        for row in debt[:20]:
            print(f"       {row}")
        if len(debt) > 20:
            print(f"       … ещё {len(debt) - 20}")

    print("\n=== ИТОГ ===")
    print(f"пройдено: {len(_PASS)} | провалено: {len(_FAIL)}")
    if _FAIL:
        print("Проваленные: " + ", ".join(_FAIL))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
