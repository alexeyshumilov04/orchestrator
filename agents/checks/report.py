"""QA/QC в отчёте прогона: сводка по проверкам и покрытие чеклиста (ДАННЫЕ, не код).

Модуль — единая точка сборки того, что раньше НЕ попадало в ``report.json`` верхнего
уровня: ключ ``qaqc`` и артефакт ``runs/<id>/qaqc_coverage.json``.

Что откуда берётся:

* **блоки** — только ``checks.package_blocks`` (config.yaml); списков в коде нет;
* **веса** — ``checks.fitness_alpha`` / ``checks.fitness_beta`` (ff = α·kq + β·kc);
* **проверки** — оцифрованный каталог: ``domain/qaqc/checks_table.csv`` (пакет) +
  ``ontology/qa_checks/*.csv`` (новые, от команды QA/QC); состояние каждой проверки
  считается доменным движком (``domain/qaqc``) по значениям модели;
* **пункты чеклиста и гейты** — ``ontology/qa_gate_map.yaml``.

Принцип «неизвестное ≠ ложь» (правило 6): отсутствие входных данных — это
``not_applicable`` с причиной; неформализованный пункт чеклиста — ``unknown`` с
причиной; ни то, ни другое не штрафует модель и не подменяется нулём.

Совместимость: если каталога/CSV нет — модуль отдаёт сводку с нулями и причинами,
а не падает и не выдумывает ``failed``.
"""
from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agents.checks.base import (FAILED, NOT_APPLICABLE, PASSED, PENDING, UNKNOWN,
                                UNVERIFIED, CheckRegistry, _service_root,
                                described_only_ids, load_gate_map, load_check_catalog,
                                severity_levels)

QAQC_FILE = "qaqc.json"
COVERAGE_FILE = "qaqc_coverage.json"
CHECKLIST_INDEX = "ontology/qa_checks/checklist_index.csv"
MAX_FAILED_CHECKS = 50
_BLOCK_RE = re.compile(r"^\s*(\d{2})(?:\s*\.|\s*$)")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_checklist_index(root: Path) -> dict:
    """Индекс пунктов чеклиста из данных (``ontology/qa_checks/checklist_index.csv``).

    Возвращает {"total", "by_block", "outside", "source"}; нет файла → {} (не падаем:
    тогда числа пунктов берутся из ``ontology/qa_gate_map.yaml``).
    """
    path = Path(root) / CHECKLIST_INDEX
    if not path.is_file():
        return {}
    by_block: dict[str, int] = {}
    total = outside = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            first = fh.readline()
            if not first:
                return {}
            fh.seek(0)
            delim = ";" if first.count(";") >= max(first.count(","), 1) else ","
            reader = csv.DictReader(fh, delimiter=delim)
            block_col = next((c for c in (reader.fieldnames or [])
                              if c and c.strip().lower().startswith("блок")), None)
            if block_col is None:
                return {}
            for row in reader:
                total += 1
                m = _BLOCK_RE.match(str(row.get(block_col) or ""))
                if m:
                    by_block[m.group(1)] = by_block.get(m.group(1), 0) + 1
                else:
                    outside += 1
    except OSError:
        return {}
    if not total:
        return {}
    return {"total": total, "by_block": by_block, "outside": outside,
            "source": CHECKLIST_INDEX}


# --- данные конфигурации -----------------------------------------------------------
def package_blocks(cfg) -> list[str]:
    """Уникальные блоки чеклиста из ``checks.package_blocks`` (порядок как в данных)."""
    raw = cfg.get("checks.package_blocks") if cfg is not None else None
    out: list[str] = []
    if isinstance(raw, dict):
        for blocks in raw.values():
            for b in blocks or []:
                code = str(b).strip()
                if code and code not in out:
                    out.append(code)
    elif isinstance(raw, (list, tuple)):
        out = [str(b).strip() for b in raw if str(b).strip()]
    return out


def fitness_weights(cfg) -> tuple[float, float]:
    """Веса свёртки фитнеса из данных (``checks.fitness_alpha`` / ``fitness_beta``)."""
    alpha = cfg.get("checks.fitness_alpha", 0.5) if cfg is not None else 0.5
    beta = cfg.get("checks.fitness_beta", 0.5) if cfg is not None else 0.5
    try:
        return float(alpha), float(beta)
    except (TypeError, ValueError):
        return 0.5, 0.5


def blocks_by_gate(cfg) -> dict[str, list[str]]:
    """``checks.package_blocks`` как есть (данные), с приведением типов."""
    raw = cfg.get("checks.package_blocks") if cfg is not None else None
    out: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for gate, blocks in raw.items():
            out[str(gate)] = [str(b).strip() for b in (blocks or []) if str(b).strip()]
    return out


# --- исполнение проверок каталога --------------------------------------------------
@dataclass
class OutcomeRow:
    """Состояние одной формализованной проверки (для сводки и покрытия)."""

    id: str
    block: str
    gate: str
    source: str
    severity: str
    state: str
    reason: str = ""
    title: str = ""
    fitness: bool = False

    def to_dict(self) -> dict:
        return {"id": self.id, "block": self.block, "gate": self.gate, "source": self.source,
                "severity": self.severity, "state": self.state, "reason": self.reason,
                "title": self.title, "fitness": self.fitness}


def collect_outcomes(cfg, values: dict | None = None, *, root: Path | None = None,
                     registry: CheckRegistry | None = None,
                     only_blocks: list[str] | None = None) -> list[OutcomeRow]:
    """Прогнать все формализованные (data) проверки каталога по значениям модели.

    ``only_blocks`` — блоки чеклиста из данных (``checks.package_blocks``); пусто/None —
    без фильтра. Списков блоков в коде нет.
    """
    base = Path(root) if root is not None else _service_root(cfg)
    reg = registry if registry is not None else CheckRegistry.from_data(cfg, root=base)
    allowed = {str(b) for b in (only_blocks or [])}
    payload = {"values": dict(values or {})}
    rows: list[OutcomeRow] = []
    for spec in reg.all():
        if spec.source not in ("package", "csv"):
            continue
        if allowed and spec.block not in allowed:
            continue
        gate = spec.gate or ",".join(spec.gates or ())
        if spec.unknown_reason:
            rows.append(OutcomeRow(spec.id, spec.block, gate, spec.source, spec.severity,
                                   UNKNOWN, spec.unknown_reason, spec.title, spec.fitness))
            continue
        try:
            finding = spec.func(payload, {})
        except Exception as exc:                    # noqa: BLE001 — проверка не роняет отчёт
            rows.append(OutcomeRow(spec.id, spec.block, gate, spec.source, spec.severity,
                                   UNKNOWN, f"ошибка вычисления: {exc}", spec.title,
                                   spec.fitness))
            continue
        reason = str(getattr(spec.func, "reason", "") or "")
        state = str(getattr(spec.func, "state", "") or "")
        if finding is None:
            if state not in (NOT_APPLICABLE, UNKNOWN):
                state = UNKNOWN if ("не найден" in reason or "не распознан" in reason
                                    or "не определ" in reason) else NOT_APPLICABLE
            rows.append(OutcomeRow(spec.id, spec.block, gate, spec.source, spec.severity,
                                   state, reason or "нет данных для суждения", spec.title,
                                   spec.fitness))
            continue
        rows.append(OutcomeRow(spec.id, spec.block, gate, spec.source, spec.severity,
                               (UNVERIFIED if finding.state == UNVERIFIED else
                                (PASSED if finding.passed else FAILED)),
                               (finding.message or "")[:200], spec.title, spec.fitness))
    return rows


def _mean(scores: list[float]) -> float:
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def summarize(rows: list[OutcomeRow], *, alpha: float = 0.5,
              beta: float = 0.5) -> dict:
    """Свернуть состояния проверок в qaqc-блок отчёта (единицы — проверки)."""
    counts = {PASSED: 0, FAILED: 0, NOT_APPLICABLE: 0, UNKNOWN: 0, UNVERIFIED: 0}
    by_block: dict[str, dict] = {}
    by_source: dict[str, dict] = {}
    failed_checks: list[dict] = []
    fit_scores: list[float] = []
    qc_scores: list[float] = []
    for row in rows:
        counts[row.state] = counts.get(row.state, 0) + 1
        slot = by_block.setdefault(row.block or "—",
                                   {PASSED: 0, FAILED: 0, NOT_APPLICABLE: 0, UNKNOWN: 0,
                                    UNVERIFIED: 0, "total": 0})
        slot[row.state] = slot.get(row.state, 0) + 1
        slot["total"] += 1
        src = by_source.setdefault(row.source, {PASSED: 0, FAILED: 0, NOT_APPLICABLE: 0,
                                                UNKNOWN: 0, UNVERIFIED: 0, "total": 0})
        src[row.state] = src.get(row.state, 0) + 1
        src["total"] += 1
        if row.state in (PASSED, FAILED):
            score = 1.0 if row.state == PASSED else 0.0
            (fit_scores if row.fitness else qc_scores).append(score)
        if row.state == FAILED and len(failed_checks) < MAX_FAILED_CHECKS:
            failed_checks.append({"id": row.id, "block": row.block, "gate": row.gate,
                                  "severity": row.severity, "source": row.source,
                                  "title": row.title[:120], "message": row.reason[:200]})
    kq = _mean(fit_scores)
    kc = _mean(qc_scores)
    applicable = counts[PASSED] + counts[FAILED]
    return {
        "units": "checks",
        "total": len(rows),
        "passed": counts[PASSED],
        "failed": counts[FAILED],
        "not_applicable": counts[NOT_APPLICABLE],
        "unknown": counts[UNKNOWN],
        # applicable = passed + failed: сколько проверок РЕАЛЬНО судило модель.
        "applicable": applicable,
        "by_block": by_block,
        "by_source": by_source,
        "kq": kq,
        "kc": kc,
        "fitness": round(alpha * kq + beta * kc, 4),
        # «Не проверялось» ≠ «зелено»: без применимых проверок физичность = null.
        "physical": (counts[FAILED] == 0) if applicable else None,
        "physical_known": applicable > 0,
        "weights": {"alpha": alpha, "beta": beta},
        "failed_checks": failed_checks,
    }


# --- покрытие чеклиста -------------------------------------------------------------
def package_point_coverage() -> dict:
    """Покрытие ПУНКТОВ чеклиста из данных пакета (``domain.qaqc.coverage.build()``).

    Пункт чеклиста и проверка — разные единицы: проверка может закрывать пункт, а
    может быть формализована без вычислимых входов. Здесь берётся АВТОРИТЕТНАЯ
    построчная раскладка 6065 пунктов (реализовано / not_applicable / unknown +
    причина), включая построчный статус 195 пунктов вне 13 блоков. Пакет недоступен
    → {} (тогда остаются только счётчики проверок, без выдумывания).
    """
    try:
        from domain.qaqc.coverage import build as _build
    except Exception:                              # noqa: BLE001 — пакет опционален
        return {}
    try:
        data = _build()
    except Exception:                              # noqa: BLE001
        return {}
    if not isinstance(data, dict):
        return {}
    return {"by_block": data.get("by_block") or {},
            "by_status": data.get("by_status") or {},
            "total": data.get("total"),
            "reasons": data.get("reasons") or [],
            "items_outside_blocks": ((data.get("meta") or {}).get("items_outside_blocks")
                                     if isinstance(data.get("meta"), dict) else None),
            "notes": data.get("notes") or [],
            "source": "domain.qaqc.coverage.build() (пакет QA/QC, пункты чеклиста)"}


def coverage(gate_map: dict, rows: list[OutcomeRow], *, catalog=None,
             index: dict | None = None, points: dict | None = None,
             consistency: dict | None = None, top_level=None) -> dict:
    """Покрытие пунктов чеклиста по блокам: реализовано / not_applicable+причина / unknown+причина.

    «Реализовано» считается по ЖИВОМУ каталогу проверок (независимо от выбора гейтов),
    число пунктов блока — по живому индексу чеклиста (``checklist_index.csv``), а при
    его отсутствии — по ``qa_gate_map.yaml``; источники фиксируются в записи блока.
    """
    blocks = gate_map.get("blocks") or {}
    meta = gate_map.get("meta") or {}
    index = index or {}
    points = points or {}
    point_blocks = points.get("by_block") or {}
    index_by_block = index.get("by_block") or {}
    catalog_ids: dict[str, list[str]] = {}
    for row in catalog or []:
        if row.block_code:
            catalog_ids.setdefault(row.block_code, []).append(row.id)
    by_block_rows: dict[str, list[OutcomeRow]] = {}
    for row in rows:
        by_block_rows.setdefault(row.block, []).append(row)
    known = set(blocks)
    extra = [b for b in set(list(catalog_ids) + list(by_block_rows)) if b and b not in known]
    entries: list[dict] = []
    totals = {"checklist_items": 0, "implemented": 0, "not_implemented": 0,
              "checks_not_applicable": 0, "checks_unknown": 0, "checks_failed": 0,
              "checks_passed": 0, "checks_evaluated": 0, "checks_unverified": 0}
    for code in sorted(set(list(blocks) + extra)):
        info = dict(blocks.get(code) or {})
        block_rows = by_block_rows.get(code, [])
        map_items = int(info.get("items") or 0)
        if code in index_by_block:
            items = int(index_by_block[code])
            items_source = index.get("source", "checklist_index.csv")
        else:
            items = map_items
            items_source = "ontology/qa_gate_map.yaml"
        implemented = len(catalog_ids.get(code) or []) or len(block_rows)
        implemented_ids = sorted(catalog_ids.get(code) or [row.id for row in block_rows])
        states = {PASSED: 0, FAILED: 0, NOT_APPLICABLE: 0, UNKNOWN: 0, UNVERIFIED: 0}
        for row in block_rows:
            states[row.state] = states.get(row.state, 0) + 1
        not_implemented = max(items - implemented, 0)
        reasons = {}
        for row in block_rows:
            if row.state in (NOT_APPLICABLE, UNKNOWN) and row.reason:
                reasons.setdefault(row.state, []).append({"id": row.id, "reason": row.reason})
        # Статус/причина блока — ПО ЖИВОМУ КАТАЛОГУ (снимок в данных не может
        # противоречить фактам): «вне области» — единственный ручной статус (данные).
        map_status = str(info.get("status") or "")
        if implemented == 0 and map_status == "out_of_scope":
            status, reason = "out_of_scope", str(info.get("reason") or "")
        elif implemented == 0:
            status, reason = "not_implemented", "нет оцифрованных проверок блока"
        elif items and implemented >= items:
            status, reason = "implemented", "проверки блока оцифрованы"
        elif items:
            status = "partial"
            reason = f"проверки блока оцифрованы частично ({implemented} из {items} пунктов)"
        else:
            status, reason = "out_of_checklist", (
                "блок есть в каталоге проверок, но отсутствует в чеклисте")
        entries.append({
            "block": code,
            "title": info.get("title", ""),
            "gates": list(info.get("gates") or []),
            "agents": [str((gate_map.get("gates") or {}).get(g, {}).get("agent", ""))
                       for g in (info.get("gates") or [])],
            "status": status,
            "status_source": "каталог проверок (живые данные)",
            "map_status": map_status or None,
            "checklist_items": items,
            "checklist_items_source": items_source,
            "checklist_items_map": map_items,
            "implemented": implemented,
            "not_implemented": not_implemented,
            "implemented_ids": implemented_ids,
            "evaluated": len(block_rows),
            "states": {k: v for k, v in states.items()},
            # Покрытие ПУНКТОВ блока (авторитетно — из пакета QA/QC, если он есть):
            # сколько пунктов реализовано / not_applicable / unknown и почему.
            "points": point_blocks.get(code) or None,
            "points_source": points.get("source", "") if point_blocks.get(code) else "",
            "unknown_reasons": reasons.get(UNKNOWN, []),
            "not_applicable_reasons": reasons.get(NOT_APPLICABLE, []),
            "reason": reason,
        })
        totals["checklist_items"] += items
        totals["implemented"] += implemented
        totals["not_implemented"] += not_implemented
        totals["checks_evaluated"] += len(block_rows)
        totals["checks_passed"] += states[PASSED]
        totals["checks_failed"] += states[FAILED]
        totals["checks_not_applicable"] += states[NOT_APPLICABLE]
        totals["checks_unknown"] += states[UNKNOWN]
        totals["checks_unverified"] += states[UNVERIFIED]
    outside = int(index.get("outside", meta.get("items_outside_blocks") or 0))
    outside_detail = points.get("items_outside_blocks")
    if outside_detail is not None and not isinstance(outside_detail, dict):
        outside_detail = None
    if isinstance(outside_detail, dict) and outside_detail.get("total") is not None:
        try:
            outside = int(outside_detail.get("total"))
        except (TypeError, ValueError):
            pass
    coverage_payload = {
        "meta": {
            "source": "ontology/qa_gate_map.yaml",
            "checklist": meta.get("checklist", ""),
            "checklist_index": index.get("source", ""),
            "sheet": meta.get("sheet", ""),
            "header_row": meta.get("header_row"),
            "first_data_row": meta.get("first_data_row"),
            "checklist_items_total": index.get("total") or meta.get("total_items"),
            "blocks_total": meta.get("blocks_total"),
            # Число — для арифметики «сумма по блокам + вне блоков = 6065»;
            # построчный статус и причина 195 пунктов — в *_detail (пункты вне 13 блоков).
            "items_outside_blocks": outside,
            "items_outside_blocks_detail": outside_detail,
            "point_coverage_source": points.get("source", ""),
            "generated": _utc_now(),
            "units": {"checklist": "пункты чеклиста", "checks": "формализованные проверки"},
            "warnings": ([f"число пунктов индекса {index.get('total')} ≠ "
                          f"qa_gate_map {meta.get('total_items')}"]
                         if index.get("total") and meta.get("total_items")
                         and index.get("total") != meta.get("total_items") else []),
            "note": ("«реализовано» = есть формализованная проверка (пакет/CSV) для блока; "
                     "«unknown» = пункт не формализован ИЛИ проверка невычислима (причина "
                     "указана); not_applicable — проверка есть, но нет входных данных "
                     "(модель не штрафуется). Ни одно неизвестное не считается ложью."),
        },
        "summary": dict(totals, **{
            "checklist_items": int(index.get("total") or meta.get("total_items")
                                   or totals["checklist_items"]),
            "unknown_unformalized": totals["not_implemented"] + outside,
            "catalog_blocks": sorted(catalog_ids),
            # ПУНКТЫ чеклиста (не проверки): авторитетная раскладка из пакета QA/QC.
            "points": ({"total": points.get("total"),
                        "by_status": dict(points.get("by_status") or {}),
                        "source": points.get("source", "")} if points else None),
            "point_reasons": points.get("reasons") or [],
        }),
        "blocks": entries,
        # Сверка «описано ↔ реализовано» и авторитетный перечень
        # domain/qaqc.DESCRIBED_ONLY — прямо в артефакте покрытия (самодостаточен
        # для верификатора, без чтения report.json).
        "consistency": dict(consistency or {}),
    }
    if top_level is not None:
        coverage_payload["summary"]["qaqc"] = {
            "total": top_level.get("total"), "passed": top_level.get("passed"),
            "failed": top_level.get("failed"),
            "not_applicable": top_level.get("not_applicable"),
            "unknown": top_level.get("unknown"),
            "kq": top_level.get("kq"), "kc": top_level.get("kc"),
            "fitness": top_level.get("fitness"), "physical": top_level.get("physical"),
        }
    return coverage_payload


def _engine_checks(root: Path, blocks: list[str]) -> int:
    """Сколько проверок выбранных блоков РЕАЛИЗОВАНО в движке ``domain/qaqc``."""
    try:
        from domain import qaqc as _qaqc
    except Exception:                              # noqa: BLE001
        return 0
    checks = getattr(_qaqc, "CHECKS", None) or {}
    if not blocks:
        return len(checks)
    return sum(1 for c in checks.values()
               if any(str(getattr(c, "block", "") or "").startswith(b) for b in blocks))


# --- единая точка для report.json ---------------------------------------------------
def _write_json(path: Path, payload) -> None:
    """АТОМАРНАЯ запись JSON: читатель (верификатор/интерфейс) не увидит полу-файл.

    Артефакты покрытия читаются сразу после прогона, поэтому запись идёт через
    временный файл + ``os.replace`` (атомарно в пределах тома Windows).
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    os.replace(tmp, path)


def build_qaqc_artifacts(cfg, values: dict | None = None, run_dir=None, *,
                         root: Path | None = None) -> dict:
    """Блок ``qaqc`` для report.json + файлы ``qaqc.json`` / ``qaqc_coverage.json``.

    Возвращает словарь, готовый к ``report["qaqc"] = ...``. Ничего не выдумывает:
    при пустом каталоге отдаёт нули с причинами (``unknown``/``not_applicable``).
    """
    base = Path(root) if root is not None else _service_root(cfg)
    gate_map = load_gate_map(cfg, root=base)
    blocks = package_blocks(cfg)
    alpha, beta = fitness_weights(cfg)
    if not gate_map:
        gate_map = {"blocks": {b: {"items": 0, "gates": [], "status": "unknown",
                                   "reason": "нет данных ontology/qa_gate_map.yaml"}
                               for b in blocks},
                    "meta": {"source": "missing"}}
    registry = CheckRegistry.from_data(cfg, root=base, gate_map=gate_map)
    rows = collect_outcomes(cfg, values or {}, root=base, registry=registry,
                            only_blocks=blocks)
    summary = summarize(rows, alpha=alpha, beta=beta)
    catalog = load_check_catalog(base)
    index = load_checklist_index(base)
    points = package_point_coverage()
    described = sorted(described_only_ids())
    engine_checks = _engine_checks(base, blocks)
    # Сверка «описано в данных» против «реализовано в движке»: расхождение видно,
    # а не спрятано — нереализованные описания идут в unknown, не в failed.
    consistency = {
        "catalog_checks_in_scope": summary["total"],
        "engine_checks_in_scope": engine_checks,
        "described_but_not_executable": (len(described) or summary["unknown"]),
        "described_only_ids": described,
        "unknown_checks": summary["unknown"],
        "note": ("unknown = описание есть, исполнимой проверки нет (или схема не "
                 "разобрана) — это НЕ провал модели. described_only_ids — "
                 "авторитетный перечень domain/qaqc.DESCRIBED_ONLY"),
    }
    payload = dict(summary)
    payload.update({
        "blocks": blocks,
        "sources": {"package_blocks": blocks_by_gate(cfg),
                    "gate_map": "ontology/qa_gate_map.yaml",
                    "catalog": "domain/qaqc/checks_table.csv + ontology/qa_checks/*.csv",
                    "checklist_index": index.get("source", ""),
                    "severity_levels": severity_levels(gate_map),
                    "catalog_checks": len(catalog),
                    "engine_checks": engine_checks},
        # Сверка «описано в данных» против «реализовано в движке»: расхождение видно,
        # а не спрятано — нереализованные описания идут в unknown, не в failed.
        "consistency": consistency,
        "values_keys": sorted((values or {}).keys()),
        "checklist": {"total_items": index.get("total") or (gate_map.get("meta") or {}).get("total_items"),
                      "blocks": (gate_map.get("meta") or {}).get("blocks_total"),
                      "index_total": index.get("total"),
                      "index_outside_blocks": index.get("outside"),
                      "catalog_checks": len(catalog)},
        "generated": _utc_now(),
    })
    coverage_payload = coverage(gate_map, rows, catalog=catalog, index=index,
                                points=points, consistency=consistency,
                                top_level=payload)
    payload["coverage"] = {"implemented": coverage_payload["summary"]["implemented"],
                           "not_implemented": coverage_payload["summary"]["not_implemented"],
                           "unknown_unformalized": coverage_payload["summary"]["unknown_unformalized"],
                           "file": COVERAGE_FILE}
    if run_dir is not None:
        target = Path(run_dir)
        target.mkdir(parents=True, exist_ok=True)
        _write_json(target / QAQC_FILE, payload)
        _write_json(target / COVERAGE_FILE, coverage_payload)
    return payload


def coverage_summary(run_dir) -> dict:
    """Прочитать сохранённое покрытие (для интерфейса/отчёта); нет файла → {}."""
    path = Path(run_dir) / COVERAGE_FILE
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
