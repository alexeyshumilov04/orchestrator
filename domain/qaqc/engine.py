"""Generic evaluation engine: dispatches a check spec against provided data."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np

from .model import Check, CheckResult, DataContext, MetricSpec, MetricValue, Threshold
from . import primitives as P


AGG = {
    "identity": lambda a: a,
    "mean": lambda a: float(np.nanmean(a)),
    "max": lambda a: float(np.nanmax(a)),
    "min": lambda a: float(np.nanmin(a)),
    "std": lambda a: float(np.nanstd(a)),
    "abs_max": lambda a: float(np.nanmax(np.abs(a))),
    "abs_mean": lambda a: float(np.nanmean(np.abs(a))),
    "fraction": lambda a: float(np.nanmean(np.asarray(a, dtype=float))),
    "count": lambda a: float(np.nansum(np.asarray(a, dtype=bool))),
}

PRIMITIVES = {
    "pearson": P.pearson,
    "spearman": P.spearman,
    "rmse": P.rmse,
    "mae": P.mae,
    "mape": P.mape,
    "r2": P.r2,
    "eta_squared": P.eta_squared,
    "mean": P.mean,
    "median": P.median,
    "std": P.std,
    "min": P.amin,
    "max": P.amax,
    "range": P.arange,
    "p_range": P.p_range,
    "zscore_max": P.zscore_max,
    "mad_outlier_fraction": P.mad_outlier_fraction,
    "diff": P.diff,
    "abs_diff": P.abs_diff,
    "fraction_in_range": P.fraction_in_range,
    "fraction_outside_range": P.fraction_outside_range,
    "fraction_abs_above": P.fraction_abs_above,
    "ratio": P.ratio,
    "coverage": P.coverage,
    "null_fraction": P.null_fraction,
    "saturation_sum_fail": P.saturation_sum_fail,
    "monotonic_fail": P.monotonic_fail,
    "gradient_max": P.gradient_max,
    "curvature_max": P.curvature_max,
    "angle_max": P.angle_max,
    "ks_pvalue": P.ks_pvalue,
    "anova_pvalue": P.anova_pvalue,
    "nearest_neighbor_index": P.nearest_neighbor_index,
    "all_true": P.all_true,
    "count_false": P.count_false,
}


def compare(value, th: Threshold) -> bool:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    op = th.op
    if op == "bool_true":
        return bool(value)
    if op == "bool_false":
        return not bool(value)
    if op == "between":
        return bool(th.lo <= value <= th.hi)
    v = th.value
    if op == "le":
        return bool(value <= v)
    if op == "lt":
        return bool(value < v)
    if op == "ge":
        return bool(value >= v)
    if op == "gt":
        return bool(value > v)
    if op == "eq":
        return bool(abs(value - v) <= 1e-12)
    if op == "ne":
        return bool(abs(value - v) > 1e-12)
    return False


def _resolve(key: str, data: Any, inputs: Dict[str, Any]) -> Any:
    if inputs is not None:
        if key in inputs:
            return inputs[key]
        for k, v in inputs.items():
            if str(k).lower() == key.lower():
                return v
    if data is not None:
        if isinstance(data, dict):
            if key in data:
                return data[key]
            for k, v in data.items():
                if str(k).lower() == key.lower():
                    return v
        elif hasattr(data, "get"):
            v = data.get(key)
            if v is not None:
                return v
    raise KeyError(key)


def _to_scalar(v: Any) -> float:
    if isinstance(v, (list, tuple, np.ndarray)):
        arr = np.asarray(v, dtype=float)
        if arr.size == 0:
            return float("nan")
        return float(np.nanmean(arr))
    if isinstance(v, (int, float, np.floating, np.integer)):
        return float(v)
    return float(v)


def _compute(spec: MetricSpec, data: Any, inputs: Dict[str, Any]) -> float:
    if spec.kind in ("direct", "bool"):
        key = spec.inputs[0]
        return _to_scalar(_resolve(key, data, inputs))

    args = []
    for k in spec.inputs:
        v = _resolve(k, data, inputs)
        arr = np.asarray(v, dtype=float)
        if k in spec.log_inputs:
            arr = np.log(np.maximum(arr, 1e-300))
        args.append(arr)

    p = spec.params
    kind = spec.kind
    fn = PRIMITIVES.get(kind)
    if fn is None:
        raise ValueError(f"unknown primitive: {kind}")

    if kind in ("fraction_in_range", "fraction_outside_range"):
        result = fn(args[0], p.get("lo", 0.0), p.get("hi", 1.0))
    elif kind == "saturation_sum_fail":
        result = fn(args[0], args[1], args[2], p.get("eps", 0.01))
    elif kind == "fraction_abs_above":
        result = fn(args[0], args[1], p.get("tol", 0.0))
    elif kind in ("gradient_max", "curvature_max", "angle_max"):
        result = fn(args[0], p.get("dx", 1.0), p.get("dy"))
    else:
        result = fn(*args)

    if spec.agg != "identity":
        result = AGG.get(spec.agg, AGG["identity"])(result)
    return float(result)


def _run_check(check: Check, data: Any = None, inputs: Optional[Dict[str, Any]] = None) -> CheckResult:
    inputs = inputs or {}
    data = data if data is not None else DataContext()
    values: List[MetricValue] = []
    all_pass = True
    messages: List[str] = []
    for spec in check.metrics:
        key = spec.inputs[0] if spec.inputs else "?"
        msg = ""
        try:
            value = _compute(spec, data, inputs)
            passed = compare(value, spec.threshold) if spec.threshold is not None else True
        except KeyError as e:
            value = None
            passed = False
            msg = f"missing data key(s) for '{key}': {e}"
            messages.append(msg)
        except Exception as e:  # noqa: BLE001
            value = None
            passed = False
            msg = f"error computing '{key}' ({spec.kind}): {e}"
            messages.append(msg)
        all_pass = all_pass and passed
        values.append(MetricValue(key=key, value=value, passed=passed, threshold=spec.threshold, message=msg))
    return CheckResult(
        check_id=check.id,
        name=check.name,
        passed=all_pass,
        values=values,
        message="; ".join(messages),
        check=check,
    )


def run_check(check_id: str, data: Any = None, **inputs: Any) -> CheckResult:
    """Run a single check by its ID (e.g. 'B02-0001').

    data may be a DataContext/dict/pandas-like object; **inputs can override
    individual data keys directly.
    """
    from .checks import CHECKS
    if check_id not in CHECKS:
        raise KeyError(f"unknown check id: {check_id}")
    return _run_check(CHECKS[check_id], data, inputs)


def run_all(data: Any = None, **inputs: Any) -> List[CheckResult]:
    """Run every check in the registry and return the list of results."""
    from .checks import CHECKS
    return [run_check(cid, data, **inputs) for cid in CHECKS]


def run_block(block_prefix: str, data: Any = None, **inputs: Any) -> List[CheckResult]:
    """Run all checks whose id starts with the given prefix (e.g. 'B02')."""
    from .checks import CHECKS
    return [run_check(cid, data, **inputs) for cid in CHECKS if cid.startswith(block_prefix)]


def report(results: List[CheckResult]) -> str:
    n = len(results)
    passed = sum(1 for r in results if r.passed)
    lines = [f"TOTAL: {passed}/{n} passed"]
    for r in results:
        if not r.passed:
            lines.append(f"  FAIL {r.check_id}: {r.message or r.name}")
    return "\n".join(lines)