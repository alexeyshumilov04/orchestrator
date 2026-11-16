"""Индексация литературы и поиск доказательств для правил (E13, задача task-11).

ИНСТРУМЕНТ, не источник фактов: все «литературные» сведения живут в ДАННЫХ
(`ontology/literature_index.csv`, `ontology/literature_rules_ext.csv`,
`ontology/agent_literature_map.yaml`). Здесь нет ни одного правила, порога или
названия объекта — только обход файлов, извлечение текста и запись индекса.

Команды (запуск из `orchestrator_v8/`)::

    python -X utf8 tools/index_literature.py index      # собрать ontology/literature_index.csv
    python -X utf8 tools/index_literature.py scan --domain фаций --keywords "вариограмм,фаци"
    python -X utf8 tools/index_literature.py verify     # метрики приёмки (≥90% файлов, ≥40 правил)

Индекс (`literature_index.csv`) — колонки ровно как в задаче:
``id;путь;тип;заголовок;год/издание;область(домен);страниц;язык;ключевые темы;
использовано_в_правилах`` (разделитель — ЗАПЯТАЯ: так его читает
``agents/knowledge.StaticKnowledge._csv``, он же читает базовый
``literature_and_architecture_rules.csv``).

Честность (правило 6/8): если текст из файла не извлекается (скан-образ),
это пишется в «ключевые темы» префиксом ``[текст: нет]``, а не выдаётся за
прочитанное; страницы для DOC/DJVU, где их число неизвестно, остаются пустыми.

Скан (`scan`) НЕ выдумывает правила: он находит страницы и цитаты, из которых
правила авторизуются вручную в `ontology/literature_rules_ext.csv`.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
LIT_ROOTS = [REPO / "Литература", REPO / "Справочные материалы"]
INDEX_CSV = ROOT / "ontology" / "literature_index.csv"
RULES_CSV = ROOT / "ontology" / "literature_rules_ext.csv"
AGENT_MAP = ROOT / "ontology" / "agent_literature_map.yaml"
BASELINE_RULES_CSV = (ROOT / "ontology" / "bdi_knowledge" / "neurosymbolic_agents" /
                      "literature_and_architecture_rules.csv")

INDEX_COLUMNS = ["id", "путь", "тип", "заголовок", "год/издание", "область(домен)",
                 "страниц", "язык", "ключевые темы", "использовано_в_правилах"]
SUPPORTED = {".pdf": "PDF", ".docx": "DOCX", ".doc": "DOC", ".pptx": "PPTX",
             ".ppt": "PPT", ".djvu": "DJVU", ".xlsx": "XLSX", ".xls": "XLS"}
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_PAGE_REF = re.compile(r"#p(\d+)")
_WS = re.compile(r"\s+")
_BOILERPLATE = ("copyright", "©", "all rights reserved", "isbn", "уДК", "удк",
                "содержание", "оглавление", "table of contents")


def clean(text: str, limit: int = 0) -> str:
    out = _WS.sub(" ", str(text or "")).strip()
    return out[:limit] if limit else out


def is_cyrillic(text: str) -> bool:
    letters = [c for c in str(text or "") if c.isalpha()]
    if not letters:
        return False
    cyr = sum(1 for c in letters if "CYRILLIC" in unicodedata.name(c, ""))
    return cyr / len(letters) > 0.3


def domain_of(path: Path) -> str:
    """Область = имя подпапки верхнего уровня (у «— копия» отбрасывается)."""
    rel = path.relative_to(REPO)
    parts = rel.parts
    if len(parts) >= 3:
        return clean(parts[1].replace("— копия", "")).strip(" -—")
    return clean(parts[0])


def iter_files(roots: list[Path]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        if root.is_dir():
            out.extend(p for p in root.rglob("*") if p.is_file())
    return sorted(out, key=lambda p: str(p).lower())


# --------------------------------------------------------------------------- #
# метаданные по типам файлов
# --------------------------------------------------------------------------- #
@dataclass
class Meta:
    pages: str = ""
    title: str = ""
    year: str = ""
    lang: str = ""
    topics: str = ""
    text_state: str = "нет"
    note: str = ""
    toc: list[str] = field(default_factory=list)


def meta_pdf(path: Path, max_pages: int) -> Meta:
    m = Meta()
    try:
        import pymupdf                                    # noqa: PLC0415
        doc = pymupdf.open(path)
    except Exception as exc:                              # noqa: BLE001
        m.note = f"{type(exc).__name__}"
        return m
    try:
        m.pages = str(doc.page_count)
        md = (doc.metadata or {})
        first = ""
        for i in range(min(max_pages, doc.page_count)):
            first += doc[i].get_text("text") or ""
            if len(first) > 4000:
                break
        m.toc = [clean(t[1], 120) for t in (doc.get_toc() or [])][:40]
        m.text_state = "OK" if len(clean(first)) > 200 else "нет (скан/образ)"
        m.title = clean(md.get("title"), 160)
        if not m.title or any(b in m.title.lower() for b in _BOILERPLATE):
            m.title = ""
        if not m.title:
            for line in (doc[0].get_text("text") or "").splitlines():
                cand = clean(line, 160)
                if len(cand) < 12 or cand.lower().startswith(("http", "doi")):
                    continue
                if any(b in cand.lower() for b in _BOILERPLATE):
                    continue
                m.title = cand
                break
        m.year = ""
        ym = _YEAR.search(clean(md.get("creationDate"), 40)) or _YEAR.search(path.name)
        if ym:
            m.year = ym.group(1)
        else:
            ym = _YEAR.search(first)
            if ym:
                m.year = ym.group(1)
        m.lang = "рус" if is_cyrillic(first or path.name) else "eng"
        parts = m.toc[:8] if m.toc else [clean(l, 90) for l in first.splitlines()[:8]]
        m.topics = "; ".join(t for t in parts if t)[:400]
    except Exception as exc:                              # noqa: BLE001
        m.note = f"{type(exc).__name__}"
    finally:
        doc.close()
    return m


def _zip_xml(path: Path, name: str) -> str:
    import zipfile                                        # noqa: PLC0415
    try:
        with zipfile.ZipFile(path) as z:
            return z.read(name).decode("utf-8", "replace")
    except Exception:                                     # noqa: BLE001
        return ""


def meta_office(path: Path, kind: str) -> Meta:
    m = Meta()
    if kind in ("DOCX", "PPTX", "XLSX"):
        if kind == "DOCX":
            app = _zip_xml(path, "docProps/app.xml")
            pm = re.search(r"<Pages>(\d+)</Pages>", app)
            m.pages = pm.group(1) if pm else ""
            core = _zip_xml(path, "docProps/core.xml")
            m.title = clean(re.search(r"<dc:title>(.*?)</dc:title>", core, re.S).group(1), 160) \
                if re.search(r"<dc:title>(.*?)</dc:title>", core, re.S) else ""
            body = _zip_xml(path, "word/document.xml")
            text = clean(re.sub(r"<[^>]+>", " ", body), 4000)
        elif kind == "PPTX":
            m.pages = str(len(re.findall(r"<p:sld\b", _zip_xml(path, "ppt/presentation.xml")))) \
                if _zip_xml(path, "ppt/presentation.xml") else ""
            core = _zip_xml(path, "docProps/core.xml")
            tm = re.search(r"<dc:title>(.*?)</dc:title>", core, re.S)
            m.title = clean(tm.group(1), 160) if tm else ""
            text = ""
            for i in range(1, 6):
                text += clean(re.sub(r"<[^>]+>", " ", _zip_xml(path, f"ppt/slides/slide{i}.xml")), 900)
        else:
            m.pages = "1"
            text = ""
        m.text_state = "OK" if len(clean(text)) > 200 else "нет (образ/мало текста)"
        m.lang = "рус" if is_cyrillic(text or path.name) else "eng"
        ym = _YEAR.search(path.name)
        m.year = ym.group(1) if ym else ""
        m.topics = clean(text, 300)
        return m
    # старые бинарные DOC/PPT/XLS: только имя файла (текст не извлекаем — честно)
    m.pages = ""
    m.text_state = "нет (устаревший бинарный формат)"
    m.lang = "рус" if is_cyrillic(path.name) else "eng"
    m.topics = clean(path.stem.replace("_", " "), 200)
    return m


def build_meta(path: Path, max_pages: int) -> Meta:
    kind = SUPPORTED.get(path.suffix.lower(), "прочее")
    if kind == "PDF":
        return meta_pdf(path, max_pages)
    if kind in ("DOCX", "PPTX", "XLSX"):
        return meta_office(path, kind)
    if kind in ("DOC", "PPT", "XLS"):
        return meta_office(path, kind)
    m = Meta()
    m.text_state = "нет (формат не читается инструментом)"
    m.lang = "рус" if is_cyrillic(path.name) else "eng"
    m.topics = clean(path.stem.replace("_", " "), 200)
    return m


# --------------------------------------------------------------------------- #
# использовано_в_правилах
# --------------------------------------------------------------------------- #
def rules_source_usage() -> dict[str, list[str]]:
    """id источника → [rule_id], по колонке source_ids файла правил (данные)."""
    usage: dict[str, list[str]] = {}
    if not RULES_CSV.is_file():
        return usage
    with RULES_CSV.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            for ref in str(row.get("source_ids") or "").split(";"):
                ref = ref.strip()
                if not ref:
                    continue
                sid = ref.split("#")[0].strip()
                usage.setdefault(sid, []).append(str(row.get("rule_id") or "").strip())
    return usage


def cmd_index(args) -> int:
    files = iter_files(LIT_ROOTS)
    if args.limit:
        files = files[:args.limit]
    usage = rules_source_usage()
    started = time.time()
    rows: list[dict[str, str]] = []
    skipped: list[str] = []
    for i, path in enumerate(files, start=1):
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        if args.max_size_mb and path.stat().st_size > args.max_size_mb * 1024 * 1024:
            skipped.append(rel)
            continue
        lid = f"LIT-{len(rows) + 1:04d}"
        meta = build_meta(path, args.max_pages)
        title = meta.title or clean(path.stem.replace("_", " "), 160)
        topics = f"[текст: {meta.text_state}]"
        if meta.note:
            topics += f" [{meta.note}]"
        if meta.topics:
            topics += f" {meta.topics}"
        rows.append({
            "id": lid,
            "путь": rel,
            "тип": SUPPORTED.get(path.suffix.lower(), "прочее"),
            "заголовок": title,
            "год/издание": meta.year,
            "область(домен)": domain_of(path),
            "страниц": meta.pages,
            "язык": meta.lang,
            "ключевые темы": clean(topics, 600),
            "использовано_в_правилах": ";".join(usage.get(lid, [])),
        })
        if i % 50 == 0:
            print(f"  … {i}/{len(files)} ({time.time() - started:.0f} c)", flush=True)
    INDEX_CSV.parent.mkdir(parents=True, exist_ok=True)
    with INDEX_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=INDEX_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    by_kind: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    for r in rows:
        by_kind[r["тип"]] = by_kind.get(r["тип"], 0) + 1
        by_domain[r["область(домен)"]] = by_domain.get(r["область(домен)"], 0) + 1
    print(f"индекс: {len(rows)} файлов → {INDEX_CSV.relative_to(ROOT)} "
          f"(за {time.time() - started:.0f} c)")
    print("  по типам:", dict(sorted(by_kind.items(), key=lambda kv: -kv[1])))
    print("  по областям:", dict(sorted(by_domain.items(), key=lambda kv: -kv[1])))
    with_text = sum(1 for r in rows if "[текст: OK]" in r["ключевые темы"])
    print(f"  текст извлечён: {with_text}, без текста: {len(rows) - with_text}")
    if skipped:
        print(f"  пропущено по размеру (>{args.max_size_mb} МБ): {len(skipped)}")
    return 0


# --------------------------------------------------------------------------- #
# поиск доказательств (страница + цитата) — для авторской выверки правил
# --------------------------------------------------------------------------- #
def cmd_scan(args) -> int:
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    if not keywords:
        print("нужен --keywords", file=sys.stderr)
        return 2
    files = iter_files(LIT_ROOTS)
    if args.domain:
        wanted = [d.strip().lower() for d in args.domain.split(",") if d.strip()]
        files = [p for p in files if any(w in domain_of(p).lower() for w in wanted)]
    if args.index_query:
        # отбор целей ПО ИНДЕКСУ (данные): токены ищутся в пути, заголовке и темах
        tokens = [t.strip().lower() for t in args.index_query.split(",") if t.strip()]
        if INDEX_CSV.is_file():
            picked: list[Path] = []
            with INDEX_CSV.open(encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    blob = " ".join([row.get("путь", ""), row.get("заголовок", ""),
                                     row.get("ключевые темы", "")]).lower()
                    if any(t in blob for t in tokens):
                        picked.append(REPO / row["путь"])
            files = [p for p in files if p in set(picked)]
    hits: list[dict] = []
    per_kw: dict[str, int] = {}
    per_doc: dict[tuple[str, str], int] = {}
    docs_scanned = 0
    started = time.time()
    import pymupdf                                        # noqa: PLC0415
    for path in files:
        if args.max_docs and docs_scanned >= args.max_docs:
            break
        if path.suffix.lower() != ".pdf":
            continue
        if args.max_size_mb and path.stat().st_size > args.max_size_mb * 1024 * 1024:
            continue
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        try:
            doc = pymupdf.open(path)
        except Exception:                                 # noqa: BLE001
            continue
        docs_scanned += 1
        try:
            pages = min(doc.page_count, args.pages_cap) if args.pages_cap else doc.page_count
            for pno in range(pages):
                text = doc[pno].get_text("text") or ""
                low = text.lower()
                for kw in keywords:
                    if per_kw.get(kw, 0) >= args.per_kw_limit:
                        continue
                    if per_doc.get((rel, kw), 0) >= args.per_doc_limit:
                        continue
                    pos = low.find(kw.lower())
                    if pos < 0:
                        continue
                    snippet = clean(text[max(0, pos - args.context): pos + args.context],
                                    2 * args.context)
                    if not snippet or snippet.count("..") > 6:
                        continue                              # оглавление/мусор
                    hits.append({"lit_id": "", "path": rel, "page": pno + 1,
                                 "keyword": kw, "snippet": snippet})
                    per_kw[kw] = per_kw.get(kw, 0) + 1
                    per_doc[(rel, kw)] = per_doc.get((rel, kw), 0) + 1
                if all(per_kw.get(kw, 0) >= args.per_kw_limit for kw in keywords):
                    break
        finally:
            doc.close()
        if docs_scanned % 10 == 0:
            print(f"  … {docs_scanned} документов, {len(hits)} попаданий "
                  f"({time.time() - started:.0f} c)", flush=True)
    # привязка к id индекса (данные), чтобы правила ссылались на источник
    id_by_path: dict[str, str] = {}
    if INDEX_CSV.is_file():
        with INDEX_CSV.open(encoding="utf-8-sig", newline="") as fh:
            id_by_path = {r["путь"]: r["id"] for r in csv.DictReader(fh)}
    for h in hits:
        h["lit_id"] = id_by_path.get(h["path"], "")
    out = Path(args.out) if args.out else (Path.home() / "AppData/Local/Temp" / "lit_scan.json")
    out.write_text(json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"скан: документов {docs_scanned}, попаданий {len(hits)} → {out}")
    print("  по ключам:", dict(sorted(per_kw.items(), key=lambda kv: -kv[1])))
    return 0


# --------------------------------------------------------------------------- #
# приёмка
# --------------------------------------------------------------------------- #
def cmd_verify(args) -> int:
    files = iter_files(LIT_ROOTS)
    lit_files = iter_files([LIT_ROOTS[0]])
    spr_files = iter_files([LIT_ROOTS[1]]) if len(LIT_ROOTS) > 1 else []
    rows: list[dict] = []
    if INDEX_CSV.is_file():
        with INDEX_CSV.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))

    def in_root(row: dict, root: Path) -> bool:
        prefix = str(root.relative_to(REPO)).replace("\\", "/") + "/"
        return str(row.get("путь") or "").startswith(prefix)

    lit_rows = [r for r in rows if in_root(r, LIT_ROOTS[0])]
    spr_rows = [r for r in rows if len(LIT_ROOTS) > 1 and in_root(r, LIT_ROOTS[1])]
    ids = {r["id"] for r in rows}
    rules: list[dict] = []
    if RULES_CSV.is_file():
        with RULES_CSV.open(encoding="utf-8-sig", newline="") as fh:
            rules = list(csv.DictReader(fh))
    with_page = [r for r in rules if _PAGE_REF.search(str(r.get("source_ids") or ""))]
    bad_ref = [r.get("rule_id") for r in with_page
               if not (set(_PAGE_REF.findall(str(r.get("source_ids"))) and
                           {s.split("#")[0] for s in str(r["source_ids"]).split(";")}) <= ids)]
    baseline = BASELINE_RULES_CSV.is_file()
    agents = 0
    if AGENT_MAP.is_file():
        import yaml                                         # noqa: PLC0415
        data = yaml.safe_load(AGENT_MAP.read_text(encoding="utf-8")) or {}
        agents = len([k for k in data if str(k).startswith("AG_")])
    cover = (len(lit_rows) / len(lit_files) * 100.0) if lit_files else 0.0
    cover_spr = (len(spr_rows) / len(spr_files) * 100.0) if spr_files else 0.0
    print("=== ПРИЁМКА E13 ===")
    print(f"«Литература»: файлов {len(lit_files)}, в индексе {len(lit_rows)} → покрытие "
          f"{cover:.1f}% ({'>=' if cover >= 90 else '<'} 90%)")
    print(f"«Справочные материалы»: файлов {len(spr_files)}, в индексе {len(spr_rows)} → "
          f"покрытие {cover_spr:.1f}%")
    print(f"файлов всего: {len(files)}; строк в индексе: {len(rows)}")
    print(f"правил в literature_rules_ext.csv: {len(rules)}; со ссылкой на страницу: "
          f"{len(with_page)} ({'>=' if len(with_page) >= 40 else '<'} 40)")
    print(f"ссылок на неизвестный литературный id: {len(bad_ref)} {bad_ref[:5]}")
    print(f"агентов в карте agent_literature_map.yaml: {agents}")
    print(f"базовый набор правил на месте: {baseline}")
    with_text = sum(1 for r in rows if "[текст: OK]" in (r.get("ключевые темы") or ""))
    print(f"источников с извлечённым текстом: {with_text}")
    used = sum(1 for r in rows if (r.get("использовано_в_правилах") or "").strip())
    print(f"источников, использованных в правилах: {used}")
    ok = (cover >= 90 and len(with_page) >= 40 and agents >= 5 and baseline
          and not bad_ref)
    print("ИТОГ:", "OK" if ok else "НЕ ВЫПОЛНЕНО")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Индексация литературы (E13)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index", help="собрать ontology/literature_index.csv")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--max-pages", type=int, default=3, help="страниц для заголовка/языка")
    p.add_argument("--max-size-mb", type=int, default=0,
                   help="0 = без ограничения (индекс обязан покрывать 100% файлов)")
    p.set_defaults(func=cmd_index)
    p = sub.add_parser("scan", help="поиск цитат со страницами (доказательства)")
    p.add_argument("--keywords", required=True)
    p.add_argument("--domain", default="")
    p.add_argument("--index-query", default="",
                   help="токены для отбора документов по ontology/literature_index.csv")
    p.add_argument("--max-docs", type=int, default=0)
    p.add_argument("--max-size-mb", type=int, default=150)
    p.add_argument("--pages-cap", type=int, default=0)
    p.add_argument("--per-kw-limit", type=int, default=8)
    p.add_argument("--per-doc-limit", type=int, default=1,
                   help="попаданий на документ (разнообразие источников)")
    p.add_argument("--context", type=int, default=220)
    p.add_argument("--out", default="")
    p.set_defaults(func=cmd_scan)
    p = sub.add_parser("verify", help="метрики приёмки")
    p.set_defaults(func=cmd_verify)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
