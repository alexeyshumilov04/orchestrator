"""НЕЗАВИСИМАЯ СВЕРКА ССЫЛОК НА МАНУАЛ тНава (правило 8) С САМИМ PDF.

Написан верификатором (task-6). Ничего в чужом коде не меняет.

Зачем: многие новые шаблоны обоснованы не машинным эталоном, а мануалом Дизайнера
(«стр. 2733–2734», «41.3.6», «стр. 2581»). Проверить это можно только по самому PDF.
Инструмент берёт из комментариев шаблонов/правил цитаты в «кавычках» и номера страниц,
ищет цитаты по страницам мануала и сверяет найденную страницу с заявленной.

Запуск:  python -X utf8 tests/test_verify_manual_citations.py [--json]
Требуется `pymupdf`/`fitz` (есть в anaconda). Если PDF недоступен — честно пишет
«не проверено» и не выдумывает результат.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUALS = Path(r"C:\Program Files\tNavigator\26.2\manuals")
DEFAULT_PDF = MANUALS / "tNavUserGuideDesignerRussian.pdf"
TEMPLATES = ROOT / "domain" / "templates"
RULES = ROOT / "domain" / "ontology_rules"

_QUOTED = re.compile(r"«([^»]{15,240})»")
_PAGE = re.compile(r"стр\.\s*(\d{3,4})", re.IGNORECASE)
_SECTION = re.compile(r"\b(\d{2}\.\d{1,2}\.\d{1,2})\b")
_PDF_NAME = re.compile(r"([A-Za-z0-9_]+\.pdf)")
_MANUAL_HINT = re.compile(r"(мануал|manual|designer|tNavUserGuide|стр\.)", re.IGNORECASE)
_MANUAL_STRONG = re.compile(r"(мануал|manual|designer|tNavUserGuide)", re.IGNORECASE)
_PROBE_HINT = re.compile(r"(проб|probe|_probe|ОТЧЁТ ПРОБ|tNav 26\.2\))", re.IGNORECASE)

FAIL: list[str] = []
WARN: list[str] = []
INFO: list[str] = []


def fail(msg: str) -> None:
    FAIL.append(msg)
    print(f"[FAIL] {msg}")


def warn(msg: str) -> None:
    WARN.append(msg)
    print(f"[WARN] {msg}")


def _blocks(path: Path) -> list[str]:
    """Блоки подряд идущих строк-комментариев (одна тема = один блок)."""
    if not path.is_file():
        return []
    out, cur = [], []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.lstrip().startswith("#"):
            cur.append(ln.lstrip("# ").rstrip())
        else:
            if cur:
                out.append("\n".join(cur))
                cur = []
    if cur:
        out.append("\n".join(cur))
    return out


def _norm(text: str) -> str:
    """Нормализация для поиска: без пунктуации/решеток, одиночные пробелы."""
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def collect() -> list[dict]:
    out: list[dict] = []
    for path in sorted([*TEMPLATES.glob("*.txt"), *RULES.glob("*.rdf")]):
        units: list[dict] = []
        for block in _blocks(path):
            lines = block.splitlines()
            for i, line in enumerate(lines):
                quotes = [_norm(q) for q in _QUOTED.findall(line)]
                quotes = [q for q in quotes if len(q) >= 15]
                if not quotes:
                    continue
                # ищем строку-подпись источника в окне ±2 и берём страницы из неё
                src_line = ""
                for j in range(max(0, i - 2), min(len(lines), i + 3)):
                    if _MANUAL_STRONG.search(lines[j]) and not _PROBE_HINT.search(lines[j]):
                        src_line = lines[j]
                        break
                if not src_line:
                    continue                               # не ссылка на мануал
                pages = [int(p) for p in _PAGE.findall(src_line)]
                units.append({"quotes": sorted(set(quotes)), "pages": sorted(set(pages)),
                              "source_line": _norm(src_line)[:110]})
        if units:
            out.append({"file": path.relative_to(ROOT).as_posix(), "units": units})
    return out


def search(doc, phrases: list[str]) -> dict[str, list[int]]:
    hits: dict[str, list[int]] = {p: [] for p in phrases}
    low = [(p, _norm(p).lower()) for p in phrases]
    for i in range(doc.page_count):
        text = _norm(doc[i].get_text()).lower()
        if not text:
            continue
        for orig, p in low:
            if len(hits[orig]) < 5 and p in text:
                hits[orig].append(i + 1)
    return hits


def main() -> int:
    try:
        import fitz                                        # noqa: N813 (pymupdf)
    except Exception as exc:                               # noqa: BLE001
        warn(f"pymupdf/fitz недоступен ({exc}) — сверка с мануалом НЕ ВЫПОЛНЕНА")
        return 0
    if not DEFAULT_PDF.is_file():
        warn(f"мануал не найден: {DEFAULT_PDF} — сверка НЕ ВЫПОЛНЕНА")
        return 0

    items = collect()
    if not items:
        print("нет шаблонов/правил с цитатами мануала — сверять нечего")
        return 0
    print(f"источников с цитатами: {len(items)}; мануал: {DEFAULT_PDF.name}")

    doc = fitz.open(DEFAULT_PDF)
    print(f"страниц в мануале: {doc.page_count}")
    all_phrases = sorted({q for it in items for u in it["units"] for q in u["quotes"]})
    print(f"уникальных цитат мануала: {len(all_phrases)}")
    hits = search(doc, all_phrases)

    checked = unverified = 0
    for it in items:
        print(f"\n--- {it['file']}")
        for u in it["units"]:
            print(f"   заявленные стр.: {u['pages'] or '—'}")
            for q in u["quotes"]:
                pages = hits.get(q, [])
                if pages:
                    checked += 1
                    ok = (not u["pages"]) or any(p in pages for p in u["pages"])
                    print(f"    [{'OK ' if ok else 'FAIL'}] «{q[:70]}» -> PDF стр. {pages[:4]}"
                          + ("" if ok else f"  <-- заявлено {u['pages']}"))
                    if not ok:
                        fail(f"правило 8: {it['file']}: цитата «{q[:60]}» найдена на стр. "
                             f"{pages[:4]}, а заявлено {u['pages']}")
                else:
                    unverified += 1
                    print(f"    [WARN] «{q[:70]}» -> в мануале НЕ найдена (проверить вручную)")
                    warn(f"правило 8: {it['file']}: цитата «{q[:60]}» не найдена в "
                         f"{DEFAULT_PDF.name}")
    print(f"\n=== ИТОГ (manual citations) ===")
    print(f"проверено цитат: {checked}; не найдено: {unverified}; FAIL: {len(FAIL)}")
    if "--json" in sys.argv:
        print(json.dumps({"fail": FAIL, "warn": WARN, "items": items},
                         ensure_ascii=False, indent=2))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
