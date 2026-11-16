"""Метрики ветви ансамбля из результатов tNavigator (осмысленная свёртка).

Парсим `RESULTS/<deck>/result.sum` (Summary) — берём начальные запасы нефти
(OOIP) и финальную накопленную добычу нефти (TOP). Метрика ветви:
  * recovery_factor = TOP_final / OOIP   (КИН-прокси, по умолчанию);
  * cumulative_oil  = TOP_final          (накопленная добыча);
  * success         = 1 при удачном расчёте, иначе 0.
Плюс статус расчёта (`result.status`: finished / TNAV_STATE_CALCULATED) и число шагов.
"""
from __future__ import annotations

import re
from pathlib import Path

_FLOAT = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
_RE_OOIP = re.compile(r"Начальные запасы нефти:\s*(" + _FLOAT + r")\s*(млн\.|млрд\.|тыс\.)?")
_RE_TOP = re.compile(r"\bTOP=(" + _FLOAT + r")")
_RE_FOIP = re.compile(r"\bFOIP=(" + _FLOAT + r")")
_UNIT_SCALE = {"млн.": 1.0e6, "млрд.": 1.0e9, "тыс.": 1.0e3, None: 1.0}


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_summary(work_dir: Path, deck_stem: str) -> Path | None:
    candidates = [
        work_dir / "RESULTS" / deck_stem / "result.sum",
        work_dir / "result.sum",
        work_dir / "RESULTS" / "result.sum",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    hits = sorted(work_dir.rglob("result.sum"))
    return hits[0] if hits else None


def _find_status(work_dir: Path, deck_stem: str) -> Path | None:
    for cand in (work_dir / "RESULTS" / deck_stem / "result.status",
                 work_dir / "result.status"):
        if cand.is_file():
            return cand
    hits = sorted(work_dir.rglob("result.status"))
    return hits[0] if hits else None


def parse_summary(sum_path: Path) -> dict:
    """Извлечь OOIP, финальные TOP/FOIP и статус из result.sum."""
    data = {"ooip": None, "fopt": None, "foip": None, "steps": 0, "raw_status": ""}
    try:
        text = Path(sum_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return data
    ooip = None
    for raw_value, unit in _RE_OOIP.findall(text):
        value = _to_float(raw_value)
        if value is None:
            continue
        ooip = value * _UNIT_SCALE.get(unit or None, 1.0)   # привести к м³
        break
    data["ooip"] = ooip
    tops = [_to_float(m) for m in _RE_TOP.findall(text)]
    tops = [v for v in tops if v is not None]
    if tops:
        data["fopt"] = tops[-1]
    foips = [_to_float(m) for m in _RE_FOIP.findall(text)]
    foips = [v for v in foips if v is not None]
    if foips:
        data["foip"] = foips[-1]
    data["steps"] = len(re.findall(r"Summary at time=", text))
    return data


def parse_status(status_path: Path) -> dict:
    try:
        text = Path(status_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"sim_status": "", "common_status": ""}
    sim = re.search(r'"SIM_STATUS":\s*"([^"]+)"', text)
    common = re.search(r'"COMMON_STATUS":\s*"([^"]+)"', text)
    return {"sim_status": sim.group(1) if sim else "",
            "common_status": common.group(1) if common else ""}


def compute_metrics(work_dir: Path, deck_stem: str, *, ok: bool) -> dict:
    """Метрики ветви: ok, recovery_factor, cumulative_oil, ooip, steps."""
    work_dir = Path(work_dir)
    sum_path = _find_summary(work_dir, deck_stem)
    status_path = _find_status(work_dir, deck_stem)
    summary = parse_summary(sum_path) if sum_path else {}
    status = parse_status(status_path) if status_path else {}
    ooip = summary.get("ooip")
    fopt = summary.get("fopt")
    recovery = None
    if ooip and fopt is not None and ooip > 0:
        recovery = fopt / ooip
    return {
        "ok": bool(ok),
        "success": 1.0 if ok else 0.0,
        "recovery_factor": recovery,
        "cumulative_oil": fopt,
        "ooip": ooip,
        "steps": summary.get("steps", 0),
        "sim_status": status.get("sim_status", ""),
        "common_status": status.get("common_status", ""),
        "source": str(sum_path) if sum_path else "",
    }
