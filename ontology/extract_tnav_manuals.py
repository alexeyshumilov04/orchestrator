from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


HERE = Path(__file__).resolve().parent
MANUAL_DIR = HERE.parents[1] / "Справочные материалы" / "Мануалы_тнав"
OUT = HERE / "corpus_analysis"

MANUALS = [
    "tNavUserGuideDesignerRussian.pdf",
    "tNavWorkflowLibraryRussian.pdf",
    "tNavAPIServerUserGuideRussian.pdf",
    "tNavDataFormatsRussian.pdf",
]

THEMES = {
    "import_export": ["импорт", "экспорт", "загруз", "формат данных", "crs", "система координат"],
    "wells_logs": ["скваж", "траектор", "крив", "гис", "well log", "каротаж"],
    "seismic": ["сейсм", "горизонт", "разлом", "куб", "инверс", "атрибут"],
    "stratigraphy": ["стратиграф", "корреляц", "зон", "сло", "поверхност"],
    "facies_lithology": ["фаци", "литолог", "порода", "sis", "tgs", "pgs", "mps", "amazonas"],
    "petrophysics": ["петрофиз", "порист", "проница", "насыщ", "керн", "archie"],
    "pressure_pvt": ["давлен", "pvt", "флюид", "контакт", "equil", "капилляр"],
    "grid_properties": ["3d сет", "грид", "свойств", "вариограмм", "криг", "интерпол", "апскейл"],
    "uncertainty_ahm": ["неопредел", "ансамб", "многовариант", "адаптац", "history match", "objective"],
    "workflow_api": ["workflow", "python", "api", "скрипт", "функци", "server"],
}

FUNCTION_CALL = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+){1,})\s*\(", re.IGNORECASE)
FUNCTION_NAME = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+){2,})\b", re.IGNORECASE)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\x00", " ")).strip()


def open_recovered(path: Path) -> PdfReader:
    raw = path.read_bytes()
    marker = raw.rfind(b"%%EOF")
    if marker >= 0:
        raw = raw[:marker + 5]
    return PdfReader(BytesIO(raw), strict=False)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manual_index = []
    function_pages: dict[tuple[str, str], set[int]] = defaultdict(set)
    thematic_rows = []


    for manual_name in MANUALS:
        path = MANUAL_DIR / manual_name
        reader = open_recovered(path)
        print(f"{manual_name}: {len(reader.pages)} pages", flush=True)
        theme_counts = Counter()
        theme_samples = Counter()
        function_counts = Counter()
        front_text = []
        for page_no, page in enumerate(reader.pages, start=1):
            try:
                text = clean(page.extract_text() or "")
            except Exception:
                text = ""
            if page_no <= 24 and text:
                front_text.append(f"[{page_no}] {text}")
            lower = text.lower()
            for match in FUNCTION_CALL.findall(text):
                function_counts[match] += 3
                function_pages[(manual_name, match)].add(page_no)
            if "workflow" in manual_name.lower() or "designer" in manual_name.lower():
                for match in FUNCTION_NAME.findall(text):
                    if "_" in match and len(match) < 100:
                        function_counts[match] += 1
                        function_pages[(manual_name, match)].add(page_no)
            for theme, terms in THEMES.items():
                hits = sum(lower.count(term) for term in terms)
                if not hits:
                    continue
                theme_counts[theme] += hits
                if theme_samples[theme] < 18 and text:
                    positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
                    pos = min(positions) if positions else 0
                    start = max(0, pos - 180)
                    sample = text[start:start + 950]
                    thematic_rows.append({
                        "manual": manual_name,
                        "page": page_no,
                        "theme": theme,
                        "excerpt": sample,
                    })
                    theme_samples[theme] += 1
            if page_no % 100 == 0:
                print(f"  page {page_no}/{len(reader.pages)}", flush=True)
        manual_index.append({
            "manual": manual_name,
            "pages": len(reader.pages),
            "front_matter": "\n".join(front_text)[:80_000],
            "theme_hits": dict(theme_counts),
            "candidate_functions": len(function_counts),
        })

    with (OUT / "tnav_manual_index.json").open("w", encoding="utf-8") as fh:
        json.dump(manual_index, fh, ensure_ascii=False, indent=2)
    with (OUT / "tnav_thematic_excerpts.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for row in thematic_rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    with (OUT / "tnav_function_candidates.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["manual", "function_name", "pages"])
        writer.writeheader()
        for (manual, function), pages in sorted(function_pages.items()):
            writer.writerow({"manual": manual, "function_name": function, "pages": ";".join(map(str, sorted(pages)[:80]))})
    print(json.dumps({
        "manuals": len(manual_index),
        "thematic_excerpts": len(thematic_rows),
        "function_candidates": len(function_pages),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
