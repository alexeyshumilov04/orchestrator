"""Генератор пакета QA/QC из ДАННЫХ онтологии (``ontology/qa_checks/*``).

Задача E4: дополнить пакет ``domain/qaqc/`` проверками, оцифрованными из чеклиста
ГПН (блоки 05…13), **не изменяя** существующие 652 проверки.

Что делает:

* читает ``ontology/qa_checks/bNN.csv`` (формат 1:1 с ``checks_table.csv``) и
  ``model_keys.csv`` (контракт входных ключей);
* собирает ``Check``/``MetricSpec`` ИЗ ДАННЫХ (никаких порогов и имён в коде);
* ``checks_table.csv`` — первые 652 строки переносятся байт-в-байт (SHA-256 сверяется
  с ``ontology/qa_checks/baseline.json``), новые строки дописываются в конец;
* ``checks.py`` / ``check_functions.py`` — существующие записи переносятся ДОСЛОВНО,
  новые дописываются (генерация идемпотентна);
* ``qaqc_coverage.json`` — матрица покрытия всех 6065 пунктов чеклиста
  (:mod:`domain.qaqc.coverage`).

Ошибочные/неполные данные НЕ «достраиваются по смыслу»: генератор падает с точным
перечнем проблем (правило 8). Примитив ``unknown`` — легальное значение: критерий
не формализован в вычислимую метрику, проверка в ``CHECKS`` не попадает (правило 6).

CLI::

    python -m domain.qaqc.build_from_ontology --check   # только проверка, без записи
    python -m domain.qaqc.build_from_ontology           # пересборка пакета и покрытия
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

from . import classify
from .engine import PRIMITIVES
from .model import Check, MetricSpec, Threshold

ROOT = Path(__file__).resolve().parents[2]
QA_DIR = ROOT / "ontology" / "qa_checks"
PKG_DIR = ROOT / "domain" / "qaqc"
TABLE_CSV = PKG_DIR / "checks_table.csv"
CHECKS_PY = PKG_DIR / "checks.py"
FUNCS_PY = PKG_DIR / "check_functions.py"
KEYS_CSV = QA_DIR / "model_keys.csv"
DETAILS_CSV = QA_DIR / "checklist_details.csv"
BASELINE = QA_DIR / "baseline.json"
COVERAGE_JSON = PKG_DIR / "qaqc_coverage.json"

HEADER = ["ID", "Блок", "Название", "Способ выполнения", "Порог", "Входные ключи",
          "Значимость", "Формула", "Критерий", "Используется критерием критика"]
UNKNOWN_PRIMITIVE = "unknown"

# арность примитивов: сколько входных ключей принимает метрика
ARITY = {
    "direct": 1, "bool": 1, "mean": 1, "median": 1, "std": 1, "min": 1, "max": 1,
    "range": 1, "p_range": 1, "zscore_max": 1, "mad_outlier_fraction": 1,
    "null_fraction": 1, "fraction_in_range": 1, "fraction_outside_range": 1,
    "gradient_max": 1, "curvature_max": 1, "angle_max": 1, "all_true": 1, "count_false": 1,
    "pearson": 2, "spearman": 2, "rmse": 2, "mae": 2, "mape": 2, "r2": 2, "diff": 2,
    "abs_diff": 2, "ratio": 2, "coverage": 2, "ks_pvalue": 2, "fraction_abs_above": 2,
    "eta_squared": 2, "anova_pvalue": 2, "nearest_neighbor_index": 1,
    "saturation_sum_fail": 3, "monotonic_fail": 1,
}
# метрики, возвращающие проценты (порог задаётся числом без знака %)
PERCENT_METRICS = {"mape"}
# метрики-диапазоны: lo/hi берутся из «Формула» (метод из чеклиста)
RANGE_METRICS = {"fraction_in_range", "fraction_outside_range"}
_RANGE_RE = re.compile(
    r"([-+]?\d*\.?\d+)\s*(?:\S{0,8}\s*)?<=\s*\S+\s*<=\s*([-+]?\d*\.?\d+)")


# --------------------------------------------------------------------------- #
# чтение и разбор данных
# --------------------------------------------------------------------------- #
def ontology_files() -> list[Path]:
    """Файлы блоков: строго ``bNN.csv`` (служебные CSV не подхватываются)."""
    return sorted(QA_DIR.glob("b[0-9][0-9].csv"))


def read_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in ontology_files():
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            head = [(c or "").strip() for c in (reader.fieldnames or [])]
            if head != HEADER:
                raise ValueError(f"{path.name}: шапка не совпадает с эталоном: {head}")
            for i, raw in enumerate(reader, start=2):
                row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
                row["_file"] = path.name
                row["_line"] = str(i)
                rows.append(row)
    return rows


def read_model_keys() -> dict[str, dict[str, str]]:
    with open(KEYS_CSV, encoding="utf-8-sig", newline="") as f:
        return {r["Ключ"].strip(): r for r in csv.DictReader(f, delimiter=";") if r.get("Ключ")}


def read_details() -> dict[str, dict[str, str]]:
    with open(DETAILS_CSV, encoding="utf-8-sig", newline="") as f:
        return {r["ID"].strip(): r for r in csv.DictReader(f, delimiter=";") if r.get("ID")}


# --------------------------------------------------------------------------- #
# проверки авторских данных
# --------------------------------------------------------------------------- #
def validate(rows: list[dict[str, str]], keys: dict[str, dict[str, str]],
             known_ids: set[str]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for row in rows:
        cid = row.get("ID", "")
        where = f"{row.get('_file')}:{row.get('_line')} [{cid}]"
        if not re.match(r"^QC_[A-Z]+_\d{3}$", cid):
            problems.append(f"{where}: ID не соответствует шаблону QC_<ГРУППА>_NNN")
        if cid in seen:
            problems.append(f"{where}: ID дублируется")
        if cid in known_ids:
            problems.append(f"{where}: ID уже есть в пакете (коллизия)")
        seen.add(cid)
        blk = row.get("Блок", "")
        want = row.get("_file", "")[1:3]
        if not blk:
            problems.append(f"{where}: пустой «Блок»")
        elif re.match(r"^\d\d\.", blk) and blk[:2] != want:
            problems.append(f"{where}: блок {blk[:2]} не совпадает с файлом {want}")
        prim = row.get("Способ выполнения", "")
        thr = row.get("Порог", "")
        keylist = [k.strip() for k in row.get("Входные ключи", "").split(",") if k.strip()]
        try:
            sig = float(row.get("Значимость", ""))
            if not 0.0 <= sig <= 1.0:
                problems.append(f"{where}: значимость вне [0,1]")
        except ValueError:
            problems.append(f"{where}: значимость не число")
        if row.get("Критерий", "") == "":
            problems.append(f"{where}: пустой «Критерий»")
        if row.get("Используется критерием критика", "") not in ("", "да"):
            problems.append(f"{where}: колонка фитнес-флага должна быть «да» или пусто")
        if prim == UNKNOWN_PRIMITIVE:
            if thr or keylist:
                problems.append(f"{where}: для «{UNKNOWN_PRIMITIVE}» порог и ключи должны быть пустыми")
            continue
        if prim not in PRIMITIVES and prim not in ("direct", "bool"):
            problems.append(f"{where}: примитив «{prim}» отсутствует в схеме {sorted(PRIMITIVES)}")
            continue
        arity = ARITY.get(prim, 2)
        if prim in PERCENT_METRICS and "%" in thr:
            problems.append(f"{where}: у «{prim}» порог в процентах задаётся без знака %")
        clauses = [c.strip() for c in thr.split(";") if c.strip()]
        if not clauses:
            problems.append(f"{where}: пустой «Порог» при вычислимой метрике")
            continue
        if arity == 1 and len(keylist) != len(clauses):
            problems.append(f"{where}: для примитива «{prim}» нужно по клаузе на ключ "
                            f"(клауз {len(clauses)}, ключей {len(keylist)})")
        if arity > 1 and len(clauses) != 1:
            problems.append(f"{where}: для примитива «{prim}» допустима ровно одна клауза порога")
        if arity > 1 and len(keylist) != arity:
            problems.append(f"{where}: для примитива «{prim}» нужно {arity} ключа, "
                            f"передано {len(keylist)}")
        for k in keylist:
            if k not in keys:
                problems.append(f"{where}: ключ «{k}» не описан в model_keys.csv")
        for k in clauses:
            parsed = classify.parse_thresholds(k)
            if len(parsed) != 1:
                problems.append(f"{where}: порог «{k}» не разбирается однозначно")
        if prim in RANGE_METRICS:
            if not _RANGE_RE.search(classify._clean(row.get("Формула", ""))):  # noqa: SLF001
                problems.append(f"{where}: для «{prim}» диапазон не найден в «Формула»")
    return problems


# --------------------------------------------------------------------------- #
# сборка Check из данных
# --------------------------------------------------------------------------- #
def parse_thresholds(text: str) -> list[Threshold]:
    out: list[Threshold] = []
    for clause in [c.strip() for c in text.split(";") if c.strip()]:
        parsed = classify.parse_thresholds(clause)
        if len(parsed) != 1:
            raise ValueError(f"порог «{clause}» не разбирается однозначно: {parsed}")
        out.append(parsed[0][1])
    return out


def build_metrics(row: dict[str, str]) -> list[MetricSpec]:
    prim = row["Способ выполнения"]
    keys = [k.strip() for k in row["Входные ключи"].split(",") if k.strip()]
    thresholds = parse_thresholds(row["Порог"])
    metrics: list[MetricSpec] = []
    if prim in RANGE_METRICS:
        m = _RANGE_RE.search(classify._clean(row["Формула"]))  # noqa: SLF001
        lo, hi = float(m.group(1)), float(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return [MetricSpec(kind=prim, inputs=keys, agg="identity",
                           params={"lo": lo, "hi": hi}, threshold=thresholds[0],
                           note="range")]
    if prim == "direct":
        for key, th in zip(keys, thresholds):
            metrics.append(MetricSpec(kind="direct", inputs=[key], agg="identity",
                                      threshold=th, note="direct"))
        return metrics
    if prim == "abs_diff":
        metrics.append(MetricSpec(kind="abs_diff", inputs=keys, agg="abs_max",
                                  threshold=thresholds[0], note="difference"))
        return metrics
    metrics.append(MetricSpec(kind=prim, inputs=keys, agg="identity",
                              threshold=thresholds[0], note=prim))
    return metrics


def build_check(row: dict[str, str], details: dict[str, dict[str, str]]) -> Check | None:
    """Check из строки данных; None — только если у строки нет ID.

    Неформализованные строки (``Способ выполнения = unknown``) дают Check БЕЗ метрик:
    он идёт в ``DESCRIBED_ONLY`` (описание есть, исполнителя нет) и НЕ идёт в
    ``CHECKS`` — иначе проверка без метрик считалась бы «пройденной» (правило 6).
    """
    if not row.get("ID"):
        return None
    det = details.get(row["ID"], {})
    is_fitness = row.get("Используется критерием критика", "") == "да"
    metrics = ([] if row["Способ выполнения"] == UNKNOWN_PRIMITIVE
               else build_metrics(row))
    keys = sorted({k for m in metrics for k in m.inputs})
    return Check(
        id=row["ID"],
        number=int(det.get("№") or 0),
        block=row["Блок"],
        group=det.get("Класс проверки", ""),
        name=row["Название"],
        comment=det.get("Что именно проверяется", ""),
        formula=row["Формула"],
        criterion=row["Критерий"],
        significance=float(row["Значимость"]),
        error_source=det.get("Источник ошибки", ""),
        status=det.get("Состояние", ""),
        complexity=det.get("Сложность", ""),
        expert_comment=det.get("Что осталось сделать", ""),
        fitness_function="да" if is_fitness else "нет",
        fitness_component="качество результата" if is_fitness else "—",
        flag_justification="",
        metrics=metrics,
        parameters_used=keys,
    )


# --------------------------------------------------------------------------- #
# рендер кода
# --------------------------------------------------------------------------- #
def render_threshold(th: Threshold) -> str:
    return (f"Threshold(op={th.op!r}, value={th.value!r}, lo={th.lo!r}, hi={th.hi!r}, "
            f"unit={th.unit!r}, is_percent={th.is_percent!r}, raw={th.raw!r})")


def render_spec(spec: MetricSpec) -> str:
    return (f"MetricSpec(kind={spec.kind!r}, inputs={spec.inputs!r}, "
            f"log_inputs={spec.log_inputs!r}, agg={spec.agg!r}, params={spec.params!r}, "
            f"threshold={render_threshold(spec.threshold)}, note={spec.note!r})")


def render_entry(c: Check) -> str:
    metrics = ", ".join(render_spec(m) for m in c.metrics)
    return (
        f"    {c.id!r}: Check(id={c.id!r}, number={c.number!r}, block={c.block!r}, "
        f"group={c.group!r}, name={c.name!r}, comment={c.comment!r}, formula={c.formula!r}, "
        f"criterion={c.criterion!r}, significance={c.significance!r}, "
        f"error_source={c.error_source!r}, status={c.status!r}, complexity={c.complexity!r}, "
        f"expert_comment={c.expert_comment!r}, fitness_function={c.fitness_function!r}, "
        f"fitness_component={c.fitness_component!r}, flag_justification={c.flag_justification!r}, "
        f"metrics=[{metrics}], parameters_used={c.parameters_used!r}),"
    )


def func_name(cid: str) -> str:
    return "check_" + cid.lower().replace("-", "_")


def render_func(c: Check) -> str:
    doc = "\n".join([c.name, f"ID: {c.id}", f"Блок: {c.block}", f"Группа задач: {c.group}",
                     f"Формула: {c.formula}", f"Критерий: {c.criterion}",
                     f"Значимость: {c.significance}",
                     f"Данные (ключи): {', '.join(sorted(c.parameters_used))}"])
    name = func_name(c.id)
    return (f"def {name}(data=None, **inputs):\n"
            f"    return run_check({c.id!r}, data, **inputs)\n"
            f"{name}.__doc__ = {doc!r}\n")


_ENTRY_RE = re.compile(r"^\s*'([^']+)': Check\(")
_FUNC_RE = re.compile(
    r"def (check_\w+)\(data=None, \*\*inputs\):\n"
    r"    return run_check\('([^']+)', data, \*\*inputs\)\n"
    r"\1\.__doc__ = ('[^\n]*')\n")


def merge_checks_py(text: str, new_checks: list[Check],
                    described: list[Check], generated: set[str]) -> str:
    """Дописать CHECKS и DESCRIBED_ONLY, сохранив существующие записи ДОСЛОВНО.

    ``DESCRIBED_ONLY`` (проверки с качественным критерием: описание есть, метрики нет)
    всегда перерисовывается из данных целиком.
    """
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("CHECKS = {"))
    stop = next(i for i in range(start + 1, len(lines)) if lines[i].rstrip() == "}")
    head, body = lines[:start + 1], lines[start + 1:stop]
    tail = lines[stop + 1:]
    cut = len(tail)
    for i, line in enumerate(tail):
        if line.startswith("DESCRIBED_ONLY") or line.startswith("# Проверки с качественным"):
            cut = i
            break
    while cut > 0 and tail[cut - 1].startswith("#"):
        cut -= 1
    tail = [l for l in tail[:cut] if l.strip()]
    kept, seen = [], set()
    for line in body:
        m = _ENTRY_RE.match(line)
        cid = m.group(1) if m else None
        if cid and cid in generated:
            continue
        if cid:
            seen.add(cid)
        kept.append(line)
    extra = [render_entry(c) for c in new_checks if c.id not in seen]
    out = "\n".join(head + kept + extra + ["}"])
    if described:
        out += ("\n\n# Проверки с качественным критерием: описание есть, вычислимой метрики нет.\n"
                "# В CHECKS не входят (правило 6: неизвестное != «пройдено»).\n"
                "DESCRIBED_ONLY = {\n"
                + "\n".join(render_entry(c) for c in described) + "\n}\n")
    else:
        out += "\n"
    while tail and not tail[-1].strip():
        tail.pop()
    if tail:
        out += "\n".join(tail) + "\n"
    return out


def merge_funcs_py(text: str, new_checks: list[Check], generated: set[str]) -> str:
    """Дописать функции новых проверок, сохранив существующие блоки ДОСЛОВНО.

    Файл режется по началу ``def check_``: каждый кусок — функция вместе со своими
    пустыми строками, поэтому форматирование существующих 652 функций не меняется.
    """
    idx = text.find("def check_")
    head, blocks = (text, []) if idx < 0 else (text[:idx], [
        b for b in re.split(r"(?=^def check_)", text[idx:], flags=re.M) if b.strip()])
    kept, have = [], set()
    for block in blocks:
        m = _FUNC_RE.match(block)
        cid = m.group(2) if m else None
        if cid in generated:
            continue
        if cid:
            have.add(cid)
        kept.append(block)
    extra = [render_func(c) for c in new_checks if c.id not in have]
    body = "".join(kept)
    if extra:
        return head + body + "\n\n".join(extra) + "\n"
    return head + body


# --------------------------------------------------------------------------- #
# checks_table.csv: первые 652 строки не меняются
# --------------------------------------------------------------------------- #
def baseline_sha() -> tuple[int, str]:
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    return int(data["checks_table_rows"]), str(data["sha256_body"])


def sha_body(lines: list[str]) -> str:
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def table_rows(text: str) -> tuple[list[str], list[str]]:
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines[:1], lines[1:]


def merge_table(text: str, rows: list[dict[str, str]],
                generated: set[str]) -> tuple[str, int]:
    """Пересобрать ``checks_table.csv``: 652 базовые строки + строки из данных.

    Базовые строки переносятся ТЕКСТОМ (байт-в-байт, SHA-256 из ``baseline.json``).
    Хвост, дописанный генератором ранее, отбрасывается и пишется заново из данных,
    поэтому сборка идемпотентна. Чужие строки в хвосте (не из ``ontology/qa_checks``)
    НЕ удаляются молча — генератор падает.
    """
    n_base, want_sha = baseline_sha()
    header, body = table_rows(text)
    first = body[:n_base]
    if len(first) < n_base:
        raise ValueError(f"checks_table.csv: строк {len(body)} < базовых {n_base}")
    got = sha_body(first)
    if got != want_sha:
        raise ValueError("checks_table.csv: первые %d строк изменились (sha256 %s != %s)"
                         % (n_base, got[:16], want_sha[:16]))
    tail = list(csv.reader(io.StringIO("\n".join(body[n_base:])), delimiter=";"))
    foreign = sorted({r[0] for r in tail if r and r[0] and r[0] not in generated})
    if foreign:
        raise ValueError("checks_table.csv: в хвосте чужие строки, не из "
                         f"ontology/qa_checks: {foreign[:5]}")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    for row in rows:
        w.writerow([row.get(c, "") for c in HEADER])
    return "\n".join(header + first) + "\n" + buf.getvalue(), len(first)


# --------------------------------------------------------------------------- #
# главный сценарий
# --------------------------------------------------------------------------- #
def collect() -> dict[str, Any]:
    rows = read_rows()
    keys = read_model_keys()
    details = read_details()
    checks, described = [], []
    for row in rows:
        c = build_check(row, details)
        if c is None:
            continue
        (described if row["Способ выполнения"] == UNKNOWN_PRIMITIVE else checks).append(c)
    return {"rows": rows, "keys": keys, "details": details, "checks": checks,
            "described": described}


def known_package_ids() -> set[str]:
    text = TABLE_CSV.read_text(encoding="utf-8-sig")
    _, body = table_rows(text)
    return {l.split(";", 1)[0].strip('"') for l in body if l.strip()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Сборка проверок QA/QC из ontology/qa_checks")
    ap.add_argument("--check", action="store_true",
                    help="только проверить данные и показать план, ничего не писать")
    args = ap.parse_args(argv)

    data = collect()
    rows, checks = data["rows"], data["checks"]
    ontology_ids = {r["ID"] for r in rows}
    generated = {c.id for c in checks}

    known = known_package_ids()
    old_package = {i for i in known if not i.startswith("QC_")}
    problems = validate(rows, data["keys"], old_package)
    unknown_rows = [r for r in rows if r["Способ выполнения"] == UNKNOWN_PRIMITIVE]

    by_block: dict[str, int] = {}
    for c in checks:
        by_block[c.block[:2]] = by_block.get(c.block[:2], 0) + 1
    print(f"строк в ontology/qa_checks: {len(rows)} "
          f"(вычислимых {len(checks)}, unknown {len(unknown_rows)})")
    for b in sorted(by_block):
        print(f"  блок {b}: +{by_block[b]}")
    if unknown_rows:
        print("  unknown (критерий не формализован): "
              + ", ".join(r["ID"] for r in unknown_rows))
    if problems:
        print("ПРОБЛЕМЫ ДАННЫХ:", file=sys.stderr)
        for p in problems:
            print("  -", p, file=sys.stderr)
        return 2
    print("данные корректны")
    if args.check:
        return 0

    text = TABLE_CSV.read_text(encoding="utf-8-sig")
    new_table, n_base = merge_table(text, rows, ontology_ids)
    TABLE_CSV.write_text(new_table, encoding="utf-8-sig")

    checks_py = CHECKS_PY.read_text(encoding="utf-8")
    CHECKS_PY.write_text(merge_checks_py(checks_py, checks, data["described"],
                                         ontology_ids), encoding="utf-8")
    funcs_py = FUNCS_PY.read_text(encoding="utf-8")
    FUNCS_PY.write_text(merge_funcs_py(funcs_py, checks, ontology_ids), encoding="utf-8")

    # модуль checks уже импортирован пакетом — перечитываем, чтобы покрытие видело новые проверки
    import importlib                                       # noqa: PLC0415
    from . import checks as checks_mod                     # noqa: PLC0415
    importlib.reload(checks_mod)

    from . import coverage
    report = coverage.build()
    COVERAGE_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    print(f"checks_table.csv: {n_base} базовых строк сохранено, +{len(rows)} новых")
    print(f"checks.py: +{len(checks)} записей, DESCRIBED_ONLY: {len(data['described'])}; "
          f"check_functions.py: +{len(checks)} функций")
    print("qaqc_coverage.json:", report["by_status"], "total", report["total"])
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
