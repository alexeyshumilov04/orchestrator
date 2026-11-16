from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET


HERE = Path(__file__).resolve().parent
SOURCE_ROOT = HERE.parent
OUT = HERE / "corpus_analysis"

TEXT_EXTENSIONS = {
    ".txt", ".xml", ".bxml", ".xbml", ".py", ".html", ".data",
    ".inc", ".grdecl", ".sch", ".dat", ".prp", ".map", ".trj",
    ".tnavproject", ".datasource", ".fileregistrydatasource",
}

THEMES = {
    "qaqc": ["qaqc", "qa/qc", "quality", "качест", "провер", "контрол", "ошиб", "валидац"],
    "regional_play": ["regional", "регион", "basin", "бассейн", "play", "petroleum system", "нефтегаз"],
    "stratigraphy": ["stratigraph", "стратиграф", "correlation", "корреляц", "sequence", "секвенс"],
    "sedimentology_facies": ["sediment", "седимент", "facies", "фаци", "deposition", "обстанов"],
    "seismic_structural": ["seismic", "сейсм", "structural", "структур", "fault", "разлом", "horizon", "горизонт"],
    "petrophysics_logs": ["petrophys", "петрофиз", "well log", "logging", "гис", "core", "керн", "archie"],
    "pressure_welltest": ["pressure transient", "well test", "гдис", "давлен", "приток", "deliverability", "inflow"],
    "geomechanics": ["geomechan", "геомехан", "stress", "напряж", "fracture", "трещин"],
    "geostatistics_grid": ["geostat", "геостат", "variogram", "вариограмм", "kriging", "криг", "grid", "сетка"],
    "uncertainty": ["uncertaint", "неопредел", "risk", "риск", "ensemble", "ансамб", "monte carlo"],
    "dynamic_history": ["history match", "адаптац", "simulation", "гидродинами", "flow simulation", "reservoir engineering"],
    "software_tnavigator": ["tnavigator", "tNav", "rock flow dynamics", "designer", "workflow", "api"],
    "software_petrel": ["petrel", "ocean", "schlumberger", "slb"],
    "standards_units": ["standard", "стандарт", "spe", "prms", "resqml", "witsml", "las", "unit", "единиц"],
}

HIGH_VALUE_NAME = re.compile(
    r"qaqc|qa[_ /-]?qc|чеклист|проблемы исходных|методичес|tNav.*English|"
    r"userguideenglish|usermanualenglish|ahmuserguideenglish|pvt.*english|"
    r"geolog|геолог|petrophys|петрофиз|well.?test|гдис|seismic|сейсм|"
    r"sediment|седимент|facies|фаци|geomechan|геомехан|uncertain|неопредел|"
    r"structur|структур|stratigraph|стратиграф|reservoir|model|модел",
    re.IGNORECASE,
)

SKIP_SAMPLE = re.compile(r"open_hole_interp_chartbook|slb_charts|\\plots\\", re.IGNORECASE)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\x00", " ")).strip()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def score_path(rel: str) -> int:
    lower = rel.lower()
    score = 0
    if HIGH_VALUE_NAME.search(rel):
        score += 5
    if "qaqc" in lower or "чеклист" in lower:
        score += 5
    if "мануалы тнавигатор" in lower and "english" in lower:
        score += 5
    if "моделирование" in lower:
        score += 2
    if SKIP_SAMPLE.search(rel):
        score -= 6
    if "chinese" in lower or "spanish" in lower:
        score -= 4
    return score


def classify(text: str) -> tuple[str, str]:
    lower = text.lower()
    counts = Counter()
    for theme, terms in THEMES.items():
        for term in terms:
            counts[theme] += lower.count(term.lower())
    if not counts or counts.most_common(1)[0][1] == 0:
        return "other", ""
    ordered = [name for name, count in counts.most_common() if count > 0]
    return ordered[0], ";".join(ordered[:5])


def extract_zip_xml(path: Path, patterns: tuple[str, ...], limit: int = 100_000) -> tuple[str, dict]:
    chunks: list[str] = []
    names: list[str] = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            low = name.lower()
            if not any(re.fullmatch(p, low) for p in patterns):
                continue
            names.append(name)
            try:
                root = ET.fromstring(zf.read(name))
            except Exception:
                continue
            texts = [normalize(node.text or "") for node in root.iter() if node.text and normalize(node.text)]
            if texts:
                chunks.append(f"[{name}] " + " | ".join(texts))
            if sum(map(len, chunks)) >= limit:
                break
    return "\n".join(chunks)[:limit], {"xml_parts": len(names)}


def extract_docx(path: Path) -> tuple[str, dict]:
    return extract_zip_xml(
        path,
        (r"word/document\.xml", r"word/header\d+\.xml", r"word/footer\d+\.xml", r"word/footnotes\.xml", r"word/endnotes\.xml"),
    )


def extract_pptx(path: Path) -> tuple[str, dict]:
    return extract_zip_xml(path, (r"ppt/slides/slide\d+\.xml", r"ppt/notesSlides/notesSlide\d+\.xml"))


def extract_xlsx(path: Path) -> tuple[str, dict]:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=False)
        chunks: list[str] = []
        cells = 0
        sheets = []
        for ws in wb.worksheets:
            sheets.append(ws.title)
            chunks.append(f"[Лист: {ws.title}]")
            for row in ws.iter_rows():
                values = []
                for cell in row:
                    if cell.value not in (None, ""):
                        values.append(f"{cell.coordinate}={cell.value}")
                        cells += 1
                if values:
                    chunks.append(" | ".join(values))
                if sum(map(len, chunks)) > 150_000:
                    break
        wb.close()
        return "\n".join(chunks)[:150_000], {"sheets": sheets, "nonempty_cells": cells}
    except Exception as exc:
        return "", {"error": f"xlsx: {exc}"}


def extract_text_file(path: Path) -> tuple[str, dict]:
    if path.stat().st_size > 20 * 1024 * 1024:
        limit = 160_000
    else:
        limit = 300_000
    raw = path.read_bytes()[:limit]
    for enc in ("utf-8-sig", "cp1251", "latin-1"):
        try:
            return raw.decode(enc), {"encoding": enc, "sample_bytes": len(raw)}
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), {"encoding": "utf-8-replace", "sample_bytes": len(raw)}


def selected_pdf_pages(path: Path, page_count: int, priority: int) -> list[int]:
    rel = str(path.relative_to(SOURCE_ROOT))
    if SKIP_SAMPLE.search(rel):
        return []
    lower = rel.lower()
    if "tNav".lower() in lower and "english" in lower:
        head = 24
    elif priority >= 8:
        head = 18
    elif priority >= 5:
        head = 10
    else:
        head = 4
    pages = set(range(min(page_count, head)))
    if page_count > head:
        pages.update(range(max(0, page_count - 2), page_count))
        for frac in (0.25, 0.5, 0.75):
            pages.add(min(page_count - 1, int(page_count * frac)))
    return sorted(pages)


def extract_pdf(path: Path, priority: int) -> tuple[str, dict]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(path, strict=False)
        page_count = len(reader.pages)
        pages = selected_pdf_pages(path, page_count, priority)
        chunks = []
        failed = 0
        for idx in pages:
            try:
                text = normalize(reader.pages[idx].extract_text() or "")
            except Exception:
                text = ""
                failed += 1
            if text:
                chunks.append(f"[PDF page {idx + 1}/{page_count}] {text}")
            if sum(map(len, chunks)) > 120_000:
                break
        metadata = {str(k): str(v) for k, v in (reader.metadata or {}).items() if v}
        return "\n".join(chunks)[:120_000], {
            "pages": page_count,
            "sampled_pages": pages,
            "failed_pages": failed,
            "pdf_metadata": metadata,
        }
    except Exception as exc:
        return "", {"error": f"pdf: {exc}"}


def extract(path: Path, priority: int) -> tuple[str, dict]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return extract_pdf(path, priority)
    if ext == ".docx":
        return extract_docx(path)
    if ext == ".pptx" and not path.name.startswith("~$"):
        return extract_pptx(path)
    if ext == ".xlsx" and not path.name.startswith("~$"):
        return extract_xlsx(path)
    if ext in TEXT_EXTENSIONS:
        return extract_text_file(path)
    return "", {}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in SOURCE_ROOT.rglob("*") if p.is_file() and HERE not in p.parents)
    inventory: list[dict] = []
    extracts = []
    started = time.time()
    for index, path in enumerate(files, start=1):
        rel = str(path.relative_to(SOURCE_ROOT))
        stat = path.stat()
        priority = score_path(rel)
        digest = sha256(path)
        text, meta = extract(path, priority)
        primary_theme, themes = classify(rel + "\n" + text)
        row = {
            "source_id": f"SRC_LOCAL_{index:04d}",
            "relative_path": rel,
            "top_group": Path(rel).parts[0],
            "extension": path.suffix.lower(),
            "bytes": stat.st_size,
            "modified_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
            "sha256": digest,
            "priority_score": priority,
            "primary_theme": primary_theme,
            "themes": themes,
            "text_chars": len(text),
            "extract_status": "ok" if text else ("metadata_only" if not meta.get("error") else "error"),
            "details": json.dumps(meta, ensure_ascii=False, separators=(",", ":")),
        }
        inventory.append(row)
        if text:
            extracts.append({
                "source_id": row["source_id"],
                "relative_path": rel,
                "primary_theme": primary_theme,
                "themes": themes.split(";") if themes else [],
                "text": text,
            })
        if index % 25 == 0 or index == len(files):
            print(f"processed {index}/{len(files)} files; extracts={len(extracts)}", flush=True)

    fields = list(inventory[0]) if inventory else []
    with (OUT / "corpus_inventory.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(inventory)
    with (OUT / "corpus_extracts.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for row in extracts:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    by_ext = Counter(row["extension"] or "[none]" for row in inventory)
    by_theme = Counter(row["primary_theme"] for row in inventory)
    dup_groups = defaultdict(list)
    for row in inventory:
        dup_groups[row["sha256"]].append(row["relative_path"])
    duplicate_sets = [paths for paths in dup_groups.values() if len(paths) > 1]
    summary = [
        "# Анализ локального корпуса Задачи_3",
        "",
        f"- Файлов: {len(inventory)}",
        f"- Файлов с извлечённым текстом: {len(extracts)}",
        f"- Уникальных SHA-256: {len(dup_groups)}",
        f"- Наборов точных дублей: {len(duplicate_sets)}",
        f"- Время анализа: {time.time() - started:.1f} с",
        "",
        "## Распределение по форматам",
        "",
    ]
    summary.extend(f"- `{ext}`: {count}" for ext, count in by_ext.most_common())
    summary += ["", "## Основные темы", ""]
    summary.extend(f"- `{theme}`: {count}" for theme, count in by_theme.most_common())
    summary += ["", "## Крупнейшие группы точных дублей", ""]
    for paths in sorted(duplicate_sets, key=len, reverse=True)[:30]:
        summary.append(f"- {len(paths)} копии: `{paths[0]}`")
    (OUT / "corpus_summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(json.dumps({
        "files": len(inventory),
        "extracts": len(extracts),
        "unique_sha256": len(dup_groups),
        "duplicate_sets": len(duplicate_sets),
        "seconds": round(time.time() - started, 1),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
