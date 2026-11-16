"""Встраивание отрендеренных архитектурных схем в итоговые DOCX и PPTX.

Схемы — PNG из `docs/architecture_png/` (рендер: tools/render_architecture.py).
Скрипт ИДЕМПОТЕНТЕН по смыслу: добавляет только новые слайды/разделы в конец,
не трогая существующее содержимое. Запускать интерпретатором с python-docx и
python-pptx (bundled DSH runtime).

    python tools/embed_architecture.py
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Cm, Pt
from pptx import Presentation
from pptx.util import Inches, Pt as PPt

ROOT = Path(__file__).resolve().parents[1]
PNG_DIR = ROOT / "docs" / "architecture_png"
DOCX = ROOT / "docs" / "ОТЧЁТ_ГеоМАС_v8_обновление_10.10.docx"
PPTX = ROOT / "docs" / "ГеоМАС_v8_ИТОГ_приёмка.pptx"

TITLES_RU = {
    "01_sloi_sistemy": "Слои системы",
    "02_sborka_iz_ontologii": "Сборка воркфлоу из онтологии",
    "03_posledovatelnost_progona": "Полный прогон: от данных до сохранённой модели",
    "04_qaqc_geity": "QA/QC в форме гейтов",
    "05_ansambl_i_model": "Ансамбль, изоляция прогонов и сохранение модели",
    "06_veb_i_graf": "Веб-слой и вкладка «Граф моделирования»",
    "07_novoe_mestorozhdenie": "Добавление нового месторождения",
}

CAPTIONS = {
    "01_sloi_sistemy": "Слои системы: данные → домен → ядро → агенты → приложение. "
                       "Домен живёт в данных; код читает правила и конкретику поля.",
    "02_sborka_iz_ontologii": "Сборка воркфлоу из онтологии: распознавание по содержимому, "
                              "объектная модель из данных, derive/reconcile, рендер шаблон + .rdf.",
    "03_posledovatelnost_progona": "Полный прогон: блокировка → подготовка данных → решения агентов → "
                                   "этапы → свидетельства и вердикты → ансамбль → сохранение модели.",
    "04_qaqc_geity": "QA/QC в форме гейтов: реестр проверок из данных (чеклист + csv + config), "
                     "цепочка G-DATA → G-MAPS, вердикты passed/failed/unverified.",
    "05_ansambl_i_model": "Ансамбль, изоляция прогонов и сохранение модели: runs-каталоги, "
                          "models/<run_key>, ветки в пер-прогонной зоне, манифест с sha256.",
    "06_veb_i_graf": "Веб-слой и вкладка «Граф моделирования»: эндпоинты API, чтение графа из файлов "
                     "прогона, признак согласованности артефактов.",
    "07_novoe_mestorozhdenie": "Добавление нового месторождения: только данные, 0 правок кода — "
                               "подтверждается командой audit --generality.",
}


def _title(doc, text: str, size: int) -> None:
    """Заголовок БЕЗ зависимости от именованных стилей (в исходном DOCX их может не быть)."""
    par = doc.add_paragraph()
    run = par.add_run(text)
    run.bold = True
    run.font.size = Pt(size)
    return par


def embed_docx() -> int:
    doc = Document(str(DOCX))
    doc.add_page_break()
    _title(doc, "Приложение. Архитектурные схемы", 16)
    doc.add_paragraph(
        "Схемы отрисованы из документа docs/18_АРХИТЕКТУРА_схемы.md (Mermaid) скриптом "
        "tools/render_architecture.py. Они отражают фактическое устройство прототипа: слои, "
        "сборку воркфлоу из онтологии, последовательность прогона, QA/QC-гейты, ансамбль и "
        "сохранение моделей, веб-слой с графом моделирования, порядок добавления нового поля."
    )
    added = 0
    for name, caption in CAPTIONS.items():
        png = PNG_DIR / f"{name}.png"
        if not png.is_file():
            continue
        _title(doc, TITLES_RU.get(name, name), 12)
        doc.add_picture(str(png), width=Cm(16.5))
        par = doc.add_paragraph(caption)
        if par.runs:
            par.runs[0].font.size = Pt(9)
        added += 1
    doc.save(str(DOCX))
    return added


def embed_pptx() -> int:
    prs = Presentation(str(PPTX))
    layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[0]
    # заголовочный слайд приложения
    s = prs.slides.add_slide(layout)
    tb = s.shapes.add_textbox(Inches(0.6), Inches(2.6), Inches(12.1), Inches(2.0))
    tf = tb.text_frame
    tf.text = "Приложение. Архитектурные схемы"
    tf.paragraphs[0].runs[0].font.size = PPt(36)
    tf.paragraphs[0].runs[0].font.bold = True
    p2 = tf.add_paragraph()
    p2.text = ("7 схем: слои системы · сборка из онтологии · прогон · QA/QC-гейты · "
               "ансамбль и модель · веб и граф · новое месторождение")
    p2.runs[0].font.size = PPt(16)

    added = 1
    for name, caption in CAPTIONS.items():
        png = PNG_DIR / f"{name}.png"
        if not png.is_file():
            continue
        slide = prs.slides.add_slide(layout)
        title = TITLES_RU.get(name, CAPTIONS[name].split(":")[0])
        tb = slide.shapes.add_textbox(Inches(0.4), Inches(0.15), Inches(12.5), Inches(0.7))
        tf = tb.text_frame
        tf.text = title
        tf.paragraphs[0].runs[0].font.size = PPt(24)
        tf.paragraphs[0].runs[0].font.bold = True
        # картинка вписывается в область 12.6 x 6.0 дюйма с сохранением пропорций
        from PIL import Image

        with Image.open(png) as im:
            w_px, h_px = im.size
        max_w, max_h = 12.6, 6.0
        scale = min(max_w / w_px, max_h / h_px)
        w_in, h_in = w_px * scale, h_px * scale
        slide.shapes.add_picture(str(png), Inches((13.33 - w_in) / 2), Inches(0.95),
                                 width=Inches(w_in), height=Inches(h_in))
        added += 1
    prs.save(str(PPTX))
    return added


def main() -> int:
    n_docx = embed_docx()
    n_pptx = embed_pptx()
    print(f"DOCX: добавлено схем {n_docx} → {DOCX.name} ({DOCX.stat().st_size:,} Б)")
    print(f"PPTX: добавлено слайдов {n_pptx} → {PPTX.name} ({PPTX.stat().st_size:,} Б)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
