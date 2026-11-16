"""Рендер архитектурных схем прототипа в PNG (офлайн, matplotlib).

Mermaid-CLI в окружении нет, поэтому схемы рисуются напрямую: слои/блоки + стрелки.
Скрипт детерминированный: одни и те же входные данные → один и тот же PNG (без даты
в имени и без случайных элементов), чтобы артефакты можно было сверять по хешу.

Запуск:
    python tools/render_architecture.py --out docs/architecture_png
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # без GUI: серверный рендер
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

TITLE_FS = 15
BOX_FS = 8.5
EDGE_FS = 7.5

# Цвета по группам (нейтральные, читаемые на проекторе и в печати)
COLORS = {
    "data": "#E8F1FB",
    "domain": "#EAF6EC",
    "core": "#FFF4E5",
    "agents": "#F3EAFB",
    "app": "#FDECEF",
    "t nav": "#E6E6E6",
    "accent": "#DCE9F7",
}

# ── Описание схем: подзаголовок + строки блоков + связи ─────────────────────────
# Строка = (y_уровень, [ (id, текст, группа) ... ]); связи = (from, to, подпись, стиль)
DIAGRAMS: list[dict] = [
    {
        "name": "01_sloi_sistemy",
        "title": "Слои системы: данные → домен → ядро → агенты → приложение",
        "rows": [
            [(("cfg", "config.yaml\nпути, пороги,\nрежимы", "data")),
             (("ont", "ontology/*rules*.yaml\nправила в ОБЩЕМ виде:\nроли, маски, форматы", "data")),
             (("ontp", "ontology_project/<поле>.yaml\nВСЯ конкретика поля", "data")),
             (("tpl", "templates/*.txt\n+ ontology_rules/*.rdf", "data")),
             (("field", "data/<поле>/Source/**\nданные заказчика (чтение)", "data")),
             (("lit", "Литература/ +\nontology/literature_*.csv", "data"))],
            [(("geo", "geostat, irap,\nmap_render", "domain")),
             (("pet", "petrophysics_fit,\nsaturation_model", "domain")),
             (("fac", "facies_model, welltops,\ntrajectories, datasets", "domain")),
             (("prob", "qc/probes,\nqc/maps, qc/values", "domain"))],
            [(("coord", "coordinator.py\nоркестрация прогона", "core")),
             (("graph", "graph_generator.py\nраспознавание входов", "core")),
             (("rend", "workflow_renderer.py\nрендер воркфлоу", "core")),
             (("tnav", "tnav_client.py\nодна сессия", "core")),
             (("art", "model_artifacts.py\nмодель + манифест", "core")),
             (("audit", "generality_audit.py\nаудит общности", "core"))],
            [(("base", "BaseAgent v2\nБЗ опыта, abstain", "agents")),
             (("pol", "политики: structural,\ngrid, facies, petro,\nsaturation, maps", "agents")),
             (("chk", "checks: реестр\nпроверок ИЗ ДАННЫХ", "agents")),
             (("gt", "gates, contracts,\nstage_map, runner", "agents"))],
            [(("api", "api.py (FastAPI)\nruns / chat / graph / maps", "app")),
             (("web", "frontend/\n«Прогон» + «Граф моделирования»", "app")),
             (("cli", "main.py\npreflight | plan | run |\nserve | graph | audit", "app"))],
            [(("tn", "tNavigator 26.2 — исполнение (лицензия, одна сессия)", "t nav"))],
        ],
        "edges": [
            ("cfg", "coord", "", "solid"), ("ont", "graph", "правила", "solid"),
            ("ontp", "rend", "конкретика поля", "solid"), ("tpl", "rend", "шаблон", "solid"),
            ("field", "graph", "распознавание", "solid"), ("lit", "chk", "источники", "dashed"),
            ("geo", "coord", "", "solid"), ("pet", "pol", "", "solid"),
            ("fac", "graph", "", "solid"), ("prob", "chk", "свидетельства", "solid"),
            ("coord", "tnav", "", "solid"), ("rend", "tnav", "воркфлоу", "solid"),
            ("graph", "coord", "состав", "solid"), ("art", "coord", "сохранение", "solid"),
            ("base", "pol", "", "solid"), ("chk", "gt", "", "solid"),
            ("pol", "coord", "решения", "solid"), ("gt", "coord", "вердикты", "solid"),
            ("api", "web", "", "solid"), ("cli", "coord", "", "solid"),
            ("coord", "api", "статус/лог", "solid"), ("tnav", "tn", "", "solid"),
        ],
    },
    {
        "name": "02_sborka_iz_ontologii",
        "title": "Сборка воркфлоу из онтологии (без хардкода)",
        "rows": [
            [(("inp", "данные поля\ndata/<поле>/Source", "data")),
             (("o1", "ontology/\ninput_recognition_rules\nроли, маски, форматы, internal_key", "data"))],
            [(("rec", "распознавание по СОДЕРЖИМОМУ\nи маскам → inputs: роли + форматы", "core"))],
            [(("o2", "ontology/\nobject_binding_rules\nbindings, producers/consumers, naming", "data")),
             (("om", "объектная модель: имена объектов\nвыводятся из данных, а не из кода", "core"))],
            [(("pipe", "ontology_project/<поле>.yaml\npipeline: этапы → шаги", "data")),
             (("o3", "ontology/*_rules.yaml\ncomposition: выгрузки после производителей", "data")),
             (("der", "derive + reconcile: состав,\nприоритеты, порядок", "core"))],
            [(("draft", "draft.graph: этапы → шаги\nс параметрами и объектами", "core"))],
            [(("q", "у поля есть проектный pipeline?", "accent"))],
            [(("pg", "_pipeline_genes:\nпорядок поля (Герасимовское)", "core")),
             (("og", "_ontology_genes:\nсостав из онтологии (новое поле)", "core"))],
            [(("render", "workflow_renderer:\nшаблон + .rdf + подстановки", "core"))],
            [(("st", "постадийные артефакты\nruns/<прогон>/agents/stages/*.py", "core")),
             (("flow", "object_flow:\nпотребитель раньше производителя?", "agents"))],
            [(("tn", "tNavigator: исполнение этапов", "t nav"))],
        ],
        "edges": [
            ("inp", "rec", "", "solid"), ("o1", "rec", "правила", "solid"),
            ("rec", "om", "inputs", "solid"), ("o2", "om", "привязки", "solid"),
            ("om", "der", "объекты", "solid"), ("pipe", "der", "этапы", "solid"),
            ("o3", "der", "порядок", "solid"), ("der", "draft", "", "solid"),
            ("draft", "q", "", "solid"), ("q", "pg", "да", "solid"),
            ("q", "og", "нет", "solid"), ("pg", "render", "", "solid"),
            ("og", "render", "", "solid"), ("render", "st", "", "solid"),
            ("st", "tn", "", "solid"), ("draft", "flow", "контроль", "dashed"),
            ("flow", "der", "нарушение → пересборка", "dashed"),
        ],
    },
    {
        "name": "03_posledovatelnost_progona",
        "title": "Полный прогон: от данных до сохранённой модели",
        "rows": [
            [(("u", "CLI / Web / пользователь", "app"))],
            [(("lock", "блокировка runs/.run.lock (F-25)", "core")),
             (("stage", "_stage_data: копия данных\nв каталог прогона", "core"))],
            [(("dirs", "execute → runs/run_<поле>\ndry-run → runs/run_<поле>_dry (данные)", "data"))],
            [(("prep", "подготовка маркеров и траекторий:\nформато-осознанные адаптеры", "domain"))],
            [(("ag", "агенты: сборка состава и решений\n(данные + база знаний)", "agents")),
             (("rend", "рендер воркфлоу\n(шаблон + .rdf)", "core"))],
            [(("exec", "исполнение этапов в тНаве", "t nav"))],
            [(("ev", "свидетельства → проверки", "agents")),
             (("ver", "passed / failed /\nunverified / not_applicable", "accent"))],
            [(("ens", "ансамбль S001..S00N:\nметрика каждой ветки", "agents")),
             (("br", "ветки в models/branches/<run_key>/<vid>\nrmtree только в своей зоне", "data"))],
            [(("best", "выбор лучшей ветки (из данных)", "agents"))],
            [(("persist", "persist_model: копия модели +\nmanifest.json (sha256, версия тНава)", "core")),
             (("rep", "report.json + снапшот\nruns/artifacts/execute_<ts>/", "core"))],
            [(("out", "статус, вердикт QA/QC, карты, путь модели", "app"))],
        ],
        "edges": [
            ("u", "lock", "", "solid"), ("lock", "stage", "", "solid"),
            ("stage", "dirs", "", "solid"), ("dirs", "prep", "", "solid"),
            ("prep", "ag", "", "solid"), ("ag", "rend", "", "solid"),
            ("rend", "exec", "", "solid"), ("exec", "ev", "", "solid"),
            ("ev", "ver", "", "solid"), ("ver", "ens", "нет данных → unverified", "dashed"),
            ("ens", "br", "", "solid"), ("ens", "best", "", "solid"),
            ("best", "persist", "", "solid"), ("persist", "rep", "", "solid"),
            ("rep", "out", "", "solid"),
        ],
    },
    {
        "name": "04_qaqc_geity",
        "title": "QA/QC в форме гейтов: проверки из данных",
        "rows": [
            [(("cl", "QAQC/чеклист.xlsx\nблоки 06,07,08,13 + 09,10", "data")),
             (("csv", "ontology/qa_checks/*.csv\nоцифрованные пункты", "data")),
             (("pkg", "domain/qaqc/checks_table.csv\nпакет проверок", "data")),
             (("thr", "config.yaml: checks.*\nпороги, свойства, карты, severity", "data"))],
            [(("reg", "реестр проверок (agents/checks/base.py)", "agents"))],
            [(("prim", "примитивы builtin.py:\nсуществование/непустота куба, пороги,\nфизичность, QA/QC", "agents"))],
            [("gd", "G-DATA", "accent"), ("gs", "G-STRUCT", "accent"), ("gg", "G-GRID", "accent"),
             ("gf", "G-FACIES", "accent"), ("gp", "G-PETRO", "accent"), ("gv", "G-VOL", "accent"),
             ("gm", "G-MAPS", "accent")],
            [(("p", "passed", "domain")), (("f", "failed → degraded / halt (policy)", "app")),
             (("un", "pending_execution / unverified", "data"))],
            [(("rep", "report.json: qaqc, gates,\nfindings, remediation", "core")),
             (("cov", "qaqc_coverage.json:\nреализовано / not_applicable / unknown", "core"))],
        ],
        "edges": [
            ("cl", "reg", "", "solid"), ("csv", "reg", "", "solid"),
            ("pkg", "reg", "", "solid"), ("thr", "reg", "пороги", "solid"),
            ("reg", "prim", "", "solid"), ("prim", "gd", "", "solid"),
            ("gd", "gs", "", "solid"), ("gs", "gg", "", "solid"), ("gg", "gf", "", "solid"),
            ("gf", "gp", "", "solid"), ("gp", "gv", "", "solid"), ("gv", "gm", "", "solid"),
            ("gm", "p", "критичные passed", "solid"), ("gm", "f", "есть failed", "solid"),
            ("gm", "un", "нет данных", "solid"), ("p", "rep", "", "solid"),
            ("f", "rep", "", "solid"), ("un", "rep", "", "solid"), ("rep", "cov", "", "solid"),
        ],
    },
    {
        "name": "05_ansambl_i_model",
        "title": "Ансамбль, изоляция прогонов и сохранение модели",
        "rows": [
            [(("re", "runs/run_<поле>\nexecute", "data")), (("rd", "runs/run_<поле>_dry\ndry-run (runs.dry_suffix)", "data")),
             (("ar", "runs/artifacts/execute_<ts>/\nснапшоты отчётов", "data"))],
            [(("pm", "persist_model()", "core"))],
            [(("mm", "models/<run_key>/\nмодель + manifest.json", "data")),
             (("ml", "models/latest.json", "data")),
             (("mb", "models/branches/<run_key>/<vid>\n.snp + .snf веток", "data")),
             (("bc", "models/_cache/ (опция\nproject.branch_cache)", "data"))],
            [(("man", "manifest.json: поле, run_id/run_key, caller,\ntnav.version, файлы + sha256, ветки и метрики, verdict", "core"))],
            [(("mh", "сверх max_hashed_files:\nфайл с размером и hashed: false", "accent")),
             (("kl", "keep_last (0 = хранить все):\nретенция моделей поля", "accent")),
             (("zk", "branch_zones_keep (1):\nуборка старых зон веток", "accent"))],
        ],
        "edges": [
            ("re", "pm", "", "solid"), ("rd", "pm", "", "solid"),
            ("pm", "mm", "", "solid"), ("mm", "ml", "", "solid"),
            ("pm", "mb", "", "solid"), ("pm", "man", "", "solid"),
            ("man", "mh", "", "solid"), ("kl", "mm", "ретенция", "dashed"),
            ("zk", "mb", "уборка", "dashed"), ("pm", "bc", "опция", "dashed"),
        ],
    },
    {
        "name": "06_veb_i_graf",
        "title": "Веб-слой и вкладка «Граф моделирования»",
        "rows": [
            [(("b", "браузер: вкладки «Прогон» и «Граф моделирования»", "app"))],
            [(("api", "api.py (FastAPI)", "core"))],
            [(("st", "GET /api/runs\nruns/_web_state.json", "data")),
             (("sub", "POST /api/runs → _submit\nкоординатор", "core")),
             (("chat", "POST /api/chat:\nпри известном поле СТАРТУЕТ прогон", "core")),
             (("ws", "WS /api/runs/<id>/events\nстатус и лог", "core"))],
            [(("g", "GET /api/runs/<id>/graph\nbuild_model_graph: узлы/рёбра", "core")),
             (("mp", "GET /api/runs/<id>/maps/<file>\nкарты прогона", "core"))],
            [(("f1", "report_(execute).json", "data")),
             (("f2", "steps.json,\nagents/gates/*.json,\nhandoffs/*.json", "data")),
             (("f3", "manifest.json\n(артефакты модели)", "data"))],
            [(("cons", "summary.artifacts_consistent:\ntrue / false / null (неизвестно)", "accent"))],
            [(("sv", "сервер: env GeoMAS\n(uvicorn только там)", "accent"))],
        ],
        "edges": [
            ("b", "api", "", "solid"), ("api", "st", "", "solid"), ("api", "sub", "", "solid"),
            ("b", "chat", "", "solid"), ("b", "ws", "", "solid"), ("b", "g", "", "solid"),
            ("api", "mp", "", "solid"), ("g", "f1", "читает", "solid"),
            ("g", "f2", "читает", "solid"), ("g", "f3", "читает", "solid"),
            ("g", "cons", "", "solid"), ("sv", "api", "запускает", "dashed"),
        ],
    },
    {
        "name": "07_novoe_mestorozhdenie",
        "title": "Добавление нового месторождения: только данные, 0 правок кода",
        "rows": [
            [(("d1", "1. положить данные\ndata/<новое_поле>/Source/**", "data"))],
            [(("d2", "2. создать файл поля\nontology_project/<новое_поле>.yaml\n(field + dataset_root)", "data"))],
            [(("d3", "3. всё остальное — из онтологии:\nроли, маски, форматы, привязки,\nобъектная модель, порядок", "core"))],
            [(("d4", "4. preflight → dry-run → execute", "core"))],
            [(("d5", "5. гейты сами решают,\nчто применимо (нет данных → unverified)", "agents"))],
            [(("d6", "6. модель сохраняется в models/<run_key>/\nс манифестом (sha256)", "data"))],
            [(("d0", "ПРАВОК КОДА — 0\n(подтверждается audit --generality)", "accent"))],
        ],
        "edges": [
            ("d1", "d2", "", "solid"), ("d2", "d3", "", "solid"), ("d3", "d4", "", "solid"),
            ("d4", "d5", "", "solid"), ("d5", "d6", "", "solid"), ("d0", "d3", "доказательство", "dashed"),
        ],
    },
]


def _wrap(text: str) -> str:
    """Перенос длинных строк по словам (переносы автора сохраняются)."""
    out = []
    for line in text.split("\n"):
        out.extend(textwrap.wrap(line, width=26) or [""])
    return "\n".join(out)


def render(diagram: dict, out_dir: Path) -> Path:
    rows = diagram["rows"]
    n_rows = len(rows)
    max_boxes = max(len(r) for r in rows)
    fig_w = max(13.0, 3.05 * max_boxes)          # чем больше блоков в ряду, тем шире холст
    fig_h = 1.05 * n_rows + 1.0
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=170)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 10 * n_rows)
    ax.axis("off")
    ax.set_title(diagram["title"], fontsize=TITLE_FS, fontweight="bold", pad=14)

    pos: dict[str, tuple[float, float, float, float]] = {}   # id -> (x, y, w, h)
    box_h = 6.6
    for r, row in enumerate(rows):
        y = (n_rows - 1 - r) * 10 + (10 - box_h) / 2
        n = len(row)
        margin = 1.5
        usable = 100 - 2 * margin
        slot = usable / n
        for i, (nid, label, group) in enumerate(row):
            w = slot * 0.90
            if n <= 2:
                w = min(w, 36.0)
            x = margin + slot * i + (slot - w) / 2
            pos[nid] = (x, y, w, box_h)
            ax.add_patch(FancyBboxPatch(
                (x, y), w, box_h, boxstyle="round,pad=0.35,rounding_size=0.8",
                linewidth=1.1, edgecolor="#5A6B7C", facecolor=COLORS.get(group, "#F2F2F2"),
                zorder=2))
            ax.text(x + w / 2, y + box_h / 2, _wrap(label), ha="center", va="center",
                    fontsize=BOX_FS - 0.5, zorder=3, linespacing=1.2)

    for src, dst, label, style in diagram["edges"]:
        if src not in pos or dst not in pos:
            continue
        sx, sy, sw, sh = pos[src]
        dx, dy, dw, dh = pos[dst]
        tail = (sx + sw / 2, sy + sh / 2)
        head = (dx + dw / 2, dy + dh / 2)
        # стрелка между краями блоков (сверху вниз / по горизонтали)
        if abs(sy - dy) < 0.1 and abs(dx - sx) > 60:  # далёкие «горизонтальные» связи не рисуем
            continue
        if abs(sy - dy) < 0.1:                      # один уровень — горизонталь
            tail = (sx + (sw if dx > sx else 0), sy + sh / 2)
            head = (dx + (0 if dx > sx else dw), dy + dh / 2)
        elif dy < sy:                               # ниже: из нижнего края в верхний
            tail = (sx + sw / 2, sy)
            head = (dx + dw / 2, dy + dh)
        else:
            tail = (sx + sw / 2, sy + sh)
            head = (dx + dw / 2, dy)
        ax.add_patch(FancyArrowPatch(
            tail, head, arrowstyle="-|>", mutation_scale=11, linewidth=1.1,
            linestyle=(0, (5, 3)) if style == "dashed" else "solid",
            color="#44576B", shrinkA=2, shrinkB=2, zorder=1,
            connectionstyle="arc3,rad=0.08"))
        if label and abs(head[1] - tail[1]) + abs(head[0] - tail[0]) > 6:
            mx, my = (tail[0] + head[0]) / 2, (tail[1] + head[1]) / 2
            inside = any(bx - 1 <= mx <= bx + bw + 1 and by - 1 <= my <= by + bh + 1
                         for (bx, by, bw, bh) in pos.values())
            if inside:
                label = ""
            ax.text(mx, my + 0.35, label, fontsize=EDGE_FS, color="#33475B",
                    ha="center", va="bottom", zorder=4,
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{diagram['name']}.png"
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Рендер архитектурных схем в PNG")
    ap.add_argument("--out", default="docs/architecture_png")
    args = ap.parse_args()
    out_dir = Path(args.out)
    for d in DIAGRAMS:
        p = render(d, out_dir)
        print(f"{p}  {p.stat().st_size:,} Б")
    print(f"схем отрисовано: {len(DIAGRAMS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
