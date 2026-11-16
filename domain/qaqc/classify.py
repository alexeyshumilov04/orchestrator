"""Threshold parsing and rule-based classification of checks into MetricSpecs."""
from __future__ import annotations

import re
from typing import List, Tuple

from .model import MetricSpec, Threshold


_REPL = {
    "\u2212": "-", "\u2013": "-", "\u2014": "-", "\u2010": "-",
    "\u00d7": "*", "\u00b7": "*", "\u2022": "*",
    "\u2264": "<=", "\u2265": ">=", "\u2260": "!=", "\u2261": "==", "\u2248": "~=",
    "\u2208": " in ", "\u2209": " notin ", "\u2207": " grad_", "\u2202": " d_",
    "\u0394": " Delta_", "\u03bc": " mu_", "\u03c3": " sigma_", "\u03b7": " eta_",
    "\u03c1": " rho_", "\u03b8": " theta_", "\u03a3": " Sum_", "\u03c0": " pi_",
    "\u00b0": " ", "\u00b2": "^2", "\u00b3": "^3", "\u2192": " -> ",
    "\u03b5": " eps_", "\u2264": "<=",
}

_NUM = r"[-+]?\d*\.?\d+"


def _clean(t: str) -> str:
    for k, v in _REPL.items():
        t = t.replace(k, v)
    return t


def parse_thresholds(text: str) -> List[Tuple[str, Threshold]]:
    t = _clean(text)
    ths: List[Tuple[str, Threshold]] = []
    for m in re.finditer(
        r"(?:([A-Za-z_]{1,20})\s*)?(<=|>=|==|!=|~=|<|>|=)\s*(" + _NUM + r")\s*(%|[A-Za-z_/]*)?", t
    ):
        label = (m.group(1) or "").strip("_").lower()
        op = {"<=": "le", "<": "lt", ">=": "ge", ">": "gt", "=": "eq", "==": "eq", "!=": "ne", "~=": "eq"}[m.group(2)]
        val = float(m.group(3))
        unit = (m.group(4) or "").strip()
        is_pct = "%" in unit or "%" in t[max(0, m.start() - 4):m.start() + 12]
        if is_pct:
            val = val / 100.0
        ths.append((label, Threshold(op=op, value=val, unit=unit, is_percent=is_pct, raw=m.group(0))))
    for m in re.finditer(r"\[\s*(" + _NUM + r")\s*,\s*(" + _NUM + r")\s*\]", t):
        ths.append(("range", Threshold(op="between", lo=float(m.group(1)), hi=float(m.group(2)), raw=m.group(0))))
    if not ths and re.search(r"100\s*%", t):
        ths.append(("", Threshold(op="eq", value=1.0, is_percent=True, raw="100%")))
    return ths


def extract_mnemonics(text: str, mnemonics) -> List[str]:
    upper = text.upper()
    found = []
    for m in sorted(mnemonics, key=len, reverse=True):
        if len(m) < 2:
            continue
        if re.search(r"(?<![A-Z0-9])" + re.escape(m) + r"(?![A-Z0-9])", upper):
            found.append(m)
    return found


def _parse_corr_args(f: str):
    m = re.search(r"corr\s*\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)", f)
    if not m:
        return None, None, []
    a = m.group(1).strip()
    b = m.group(2).strip()
    logs = []
    for i, x in enumerate((a, b)):
        lm = re.match(r"log\s*\(\s*([^)]+)\s*\)", x)
        if lm:
            logs.append(lm.group(1).strip())
            if i == 0:
                a = lm.group(1).strip()
            else:
                b = lm.group(1).strip()
    return a.strip(), b.strip(), logs


def _metric_key(formula: str, name: str, cid: str = "metric") -> str:
    lhs = _clean(formula).split("=")[0].strip()
    lhs = re.sub(r"[^A-Za-z0-9_]+", "_", lhs).strip("_")
    if lhs and re.search(r"[A-Za-z]", lhs):
        return lhs
    n = re.sub(r"[^A-Za-z0-9_]+", "_", _clean(name)).strip("_")
    if n and re.search(r"[A-Za-z]", n):
        return n
    return cid


def classify_check(cid: str, name: str, formula: str, criterion: str, mnemonics):
    """Return (metrics, parameters_used) for one check."""
    f = _clean(formula)
    c = _clean(criterion)
    n = _clean(name)
    low_f = f.lower()
    low_n = n.lower()
    ths = parse_thresholds(criterion)
    primary = ths[0][1] if ths else Threshold(op="bool_true", raw=criterion)
    used = extract_mnemonics(formula + " | " + name, mnemonics)
    metrics: List[MetricSpec] = []

    # 1. correlation r = corr(X, Y)
    if "corr(" in low_f or "corr (" in low_f:
        a, b, logs = _parse_corr_args(low_f)
        kind = "spearman" if ("spearman" in low_f or "spearman" in low_n) else "pearson"
        metrics.append(MetricSpec(kind=kind, inputs=[a or "X", b or "Y"], log_inputs=logs, threshold=primary, note="correlation"))
        return metrics, used

    # 2. RMSE / MAE / MAPE
    if "rmse" in low_f or "rmse" in low_n:
        metrics.append(MetricSpec(kind="rmse", inputs=_err_inputs(f), threshold=primary, note="rmse"))
        return metrics, used
    if re.search(r"\bmae\b", low_f) or re.search(r"\bmae\b", low_n):
        metrics.append(MetricSpec(kind="mae", inputs=_err_inputs(f), threshold=primary, note="mae"))
        return metrics, used
    if "mape" in low_f or "mape" in low_n:
        metrics.append(MetricSpec(kind="mape", inputs=_err_inputs(f), threshold=primary, note="mape"))
        return metrics, used

    # 3. R^2 and eta^2
    if "r^2" in low_f or " r2" in low_f or "r2 " in low_f or "r2=" in low_f:
        metrics.append(MetricSpec(kind="r2", inputs=_err_inputs(f), threshold=primary, note="r2"))
        return metrics, used
    if "eta_" in low_f and "^2" in low_f:
        metrics.append(MetricSpec(kind="eta_squared", inputs=["groups", "values"], threshold=primary, note="eta^2"))
        return metrics, used

    # 4. z-score / MAD outliers
    if re.search(r"\bz\s*=", low_f) or "z-score" in low_f or "zscore" in low_f:
        metrics.append(MetricSpec(kind="zscore_max", inputs=[_first_input(f) or "X"], threshold=primary, note="z-score"))
        return metrics, used
    if "mad" in low_f or "mad" in low_n:
        metrics.append(MetricSpec(kind="mad_outlier_fraction", inputs=[_first_input(f) or "X"], threshold=primary, note="MAD outliers"))
        return metrics, used

    # 5. saturation sum
    if re.search(r"sw\s*\+\s*so\s*\+\s*sg", low_f) or re.search(r"sw\s*\+\s*so\s*\+\s*sg", low_n):
        metrics.append(MetricSpec(kind="saturation_sum_fail", inputs=["SW", "SO", "SG"], params={"eps": _extract_eps(f, 0.01)}, threshold=primary, note="SW+SO+SG=1"))
        return metrics, used

    # 6. monotonic time series
    if "q(t)" in low_f or "q(t)" in low_n:
        metrics.append(MetricSpec(kind="monotonic_fail", inputs=["Q"], threshold=primary, note="monotonic"))
        return metrics, used

    # 7. gradient / curvature / angle
    if "grad_" in low_f or "gradient" in low_f:
        metrics.append(MetricSpec(kind="gradient_max", inputs=["grid"], params={"dx": 1.0}, threshold=primary, note="gradient"))
        return metrics, used
    if "curvature" in low_f:
        metrics.append(MetricSpec(kind="curvature_max", inputs=["grid"], params={"dx": 1.0}, threshold=primary, note="curvature"))
        return metrics, used
    if "arctan" in low_f or "angle" in low_f:
        metrics.append(MetricSpec(kind="angle_max", inputs=["grid"], params={"dx": 1.0}, threshold=primary, note="angle"))
        return metrics, used

    # 8. KS / ANOVA
    if "ks" in low_n or "kolmogorov" in low_n or "\u043a\u043e\u043b\u043c\u043e\u0433\u043e\u0440\u043e\u0432" in n.lower():
        metrics.append(MetricSpec(kind="ks_pvalue", inputs=["sample_a", "sample_b"], threshold=primary, note="KS test"))
        return metrics, used
    if "anova" in low_f or "anova" in low_n:
        metrics.append(MetricSpec(kind="anova_pvalue", inputs=["groups", "values"], threshold=primary, note="ANOVA"))
        return metrics, used

    # 9. coverage / completeness / ratio
    if "coverage" in low_f or "coverage" in low_n:
        a, b = _ratio_inputs(f)
        metrics.append(MetricSpec(kind="coverage", inputs=a and [a, b] or ["loaded", "available"], threshold=primary, note="coverage"))
        return metrics, used
    if "completeness" in low_f or "completeness" in low_n:
        a, b = _ratio_inputs(f)
        metrics.append(MetricSpec(kind="ratio", inputs=a and [a, b] or ["available", "required"], threshold=primary, note="completeness"))
        return metrics, used

    # 10. null fraction
    if "null_fraction" in low_f or "null" in low_f or "null_fraction" in low_n:
        metrics.append(MetricSpec(kind="null_fraction", inputs=[_first_input(f) or "values"], threshold=primary, note="null fraction"))
        return metrics, used

    # 11. nearest neighbor
    if "nearest" in low_f or "nearest" in low_n or "neighbor" in low_n:
        metrics.append(MetricSpec(kind="nearest_neighbor_index", inputs=["points"], threshold=primary, note="nearest neighbor"))
        return metrics, used

    # 12. in-range checks: "X in [lo, hi]" or "X notin [lo, hi]"
    in_matches = re.findall(r"([A-Za-z_][A-Za-z_0-9]*)\s*(notin|in)\s*\[\s*(" + _NUM + r")\s*,\s*(" + _NUM + r")\s*\]", low_f)
    if in_matches:
        for ident, opword, lo, hi in in_matches:
            kind = "fraction_outside_range" if opword == "notin" else "fraction_in_range"
            metrics.append(MetricSpec(kind=kind, inputs=[ident.upper()], params={"lo": float(lo), "hi": float(hi)}, threshold=primary, note=f"{ident} in [{lo},{hi}]"))
        return metrics, used

    # 13. fail = count(...)/N with a range
    if ("fail" in low_f or "count(" in low_f) and re.search(r"/\s*[nN]", f):
        rg = re.search(r"\[\s*(" + _NUM + r")\s*,\s*(" + _NUM + r")\s*\]", low_f)
        if rg:
            ident = _first_input(f) or "X"
            metrics.append(MetricSpec(kind="fraction_outside_range", inputs=[ident], params={"lo": float(rg.group(1)), "hi": float(rg.group(2))}, threshold=primary, note="fraction outside range"))
            return metrics, used
        if "sw+so+sg" in low_f.replace(" ", ""):
            metrics.append(MetricSpec(kind="saturation_sum_fail", inputs=["SW", "SO", "SG"], params={"eps": _extract_eps(f, 0.01)}, threshold=primary, note="SW+SO+SG=1"))
            return metrics, used
        if "q(t)" in low_f:
            metrics.append(MetricSpec(kind="monotonic_fail", inputs=["Q"], threshold=primary, note="monotonic"))
            return metrics, used
        am = re.search(r"\|\s*([^\s|>-]+)\s*-\s*([^\s|>-]+)\s*\|\s*>\s*(" + _NUM + r")", f)
        if am:
            metrics.append(MetricSpec(kind="fraction_abs_above", inputs=[am.group(1), am.group(2)], params={"tol": float(am.group(3))}, threshold=primary, note="fraction |A-B|>tol"))
            return metrics, used

    # 14. difference / bias: Delta_ X = A - B, or Bias = mean(A-B)
    dm = re.search(r"([A-Za-z_][A-Za-z_0-9]*)\s*=\s*([A-Za-z_][A-Za-z_0-9]*)\s*-\s*([A-Za-z_][A-Za-z_0-9]*)", f)
    if dm or "bias" in low_f or " delta_" in low_f or low_f.startswith("delta_"):
        if dm:
            a, b = dm.group(2), dm.group(3)
        else:
            a, b = "observed", "model"
        agg = "abs_max"
        if "max" in low_f:
            agg = "abs_max"
        elif "mean" in low_f or "bias" in low_f or "mu_" in low_f:
            agg = "mean"
        elif "std" in low_f:
            agg = "std"
        kind = "abs_diff" if (agg in ("abs_max", "abs_mean")) else "diff"
        metrics.append(MetricSpec(kind=kind, inputs=[a, b], agg=agg, threshold=primary, note="difference"))
        return metrics, used

    # 15. multi threshold (mean + max) from criterion
    if len(ths) >= 2:
        for label, th in ths:
            agg = {"mu": "mean", "mean": "mean", "max": "abs_max", "min": "min", "std": "std"}.get(label, "identity")
            a, b = _two_inputs(f)
            if not a:
                a, b = "observed", "model"
            kind = "abs_diff" if agg in ("abs_max", "abs_mean", "mean", "std") else "direct"
            metrics.append(MetricSpec(kind=kind, inputs=[a, b] if kind != "direct" else [_metric_key(formula, name, cid)], agg=agg, threshold=th, note=label or "multi"))
        return metrics, used

    # 16. generic direct / boolean metric
    key = _metric_key(formula, name, cid)
    kind = "bool" if primary.op in ("bool_true", "bool_false") else "direct"
    metrics.append(MetricSpec(kind=kind, inputs=[key], threshold=primary, note="direct"))
    return metrics, used


def _err_inputs(f: str):
    a, b = _two_inputs(f)
    if a and b:
        base_a = re.sub(r"_[A-Za-z0-9]+$", "", a)
        base_b = re.sub(r"_[A-Za-z0-9]+$", "", b)
        if len(base_a) > 1 and len(base_b) > 1:
            return [a, b]
    return ["observed", "predicted"]


def _first_input(f: str):
    m = re.search(r"(?:notin|in)\s*\[?\s*([A-Za-z_][A-Za-z_0-9]*)", f)
    if m:
        return m.group(1)
    m = re.search(r"count\s*\(\s*([A-Za-z_][A-Za-z_0-9]*)", f)
    if m:
        return m.group(1)
    return None


def _two_inputs(f: str):
    m = re.search(r"\(\s*([A-Za-z_][A-Za-z_0-9]*)\s*[-,\u2212]\s*([A-Za-z_][A-Za-z_0-9]*)\s*\)", f)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"([A-Za-z_][A-Za-z_0-9]*)\s*[-,\u2212]\s*([A-Za-z_][A-Za-z_0-9]*)", f)
    if m:
        return m.group(1), m.group(2)
    return (None, None)


def _ratio_inputs(f: str):
    m = re.search(r"([A-Za-z_][A-Za-z_0-9]*)\s*/\s*([A-Za-z_][A-Za-z_0-9]*)", f)
    if m:
        return m.group(1), m.group(2)
    return (None, None)


def _extract_eps(f: str, default: float) -> float:
    m = re.search(r"eps?_?\s*=\s*([-+]?\d*\.?\d+)", f)
    if m:
        return float(m.group(1))
    m = re.search(r">\s*([-+]?\d*\.?\d+)", f)
    if m:
        return float(m.group(1))
    return default