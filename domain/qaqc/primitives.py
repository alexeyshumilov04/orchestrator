"""Numerical primitives used by checks.

Every function accepts array-like inputs (lists, numpy arrays, pandas Series)
and returns a scalar float (or an array for the diff-style helpers).
"""
from __future__ import annotations

import numpy as np

try:
    from scipy import stats as _stats
except Exception:  # pragma: no cover
    _stats = None


def _arr(x):
    a = np.asarray(x, dtype=float)
    if a.ndim == 0:
        a = a.reshape(1)
    return np.ravel(a)


def _finite_pair(a, b):
    a, b = _arr(a), _arr(b)
    m = np.isfinite(a) & np.isfinite(b)
    return a[m], b[m]


def _finite(x):
    x = _arr(x)
    return x[np.isfinite(x)]


def pearson(a, b):
    a, b = _finite_pair(a, b)
    if a.size < 2:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def spearman(a, b):
    a, b = _finite_pair(a, b)
    if a.size < 2:
        return float("nan")
    if _stats is not None:
        try:
            return float(_stats.spearmanr(a, b).statistic)
        except Exception:
            pass
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


def rmse(a, b):
    a, b = _finite_pair(a, b)
    return float(np.sqrt(np.mean((a - b) ** 2))) if a.size else float("nan")


def mae(a, b):
    a, b = _finite_pair(a, b)
    return float(np.mean(np.abs(a - b))) if a.size else float("nan")


def mape(a, b):
    a, b = _finite_pair(a, b)
    m = np.abs(a) > 1e-12
    a, b = a[m], b[m]
    return float(np.mean(np.abs((a - b) / a)) * 100.0) if a.size else float("nan")


def r2(a, b):
    a, b = _finite_pair(a, b)
    if a.size < 2:
        return float("nan")
    ss_res = float(np.sum((a - b) ** 2))
    ss_tot = float(np.sum((a - np.mean(a)) ** 2))
    return float(1.0 - ss_res / ss_tot) if ss_tot != 0.0 else float("nan")


def eta_squared(groups, values):
    groups = np.asarray(groups)
    values = _arr(values)
    m = np.isfinite(values)
    groups, values = groups[m], values[m]
    if values.size < 2:
        return float("nan")
    grand = float(np.mean(values))
    ss_total = float(np.sum((values - grand) ** 2))
    ss_within = 0.0
    for g in np.unique(groups):
        gv = values[groups == g]
        ss_within += float(np.sum((gv - np.mean(gv)) ** 2))
    return float(1.0 - ss_within / ss_total) if ss_total != 0.0 else float("nan")


def mean(x):
    x = _finite(x)
    return float(np.mean(x)) if x.size else float("nan")


def median(x):
    x = _finite(x)
    return float(np.median(x)) if x.size else float("nan")


def std(x):
    x = _finite(x)
    return float(np.std(x)) if x.size else float("nan")


def amin(x):
    x = _finite(x)
    return float(np.min(x)) if x.size else float("nan")


def amax(x):
    x = _finite(x)
    return float(np.max(x)) if x.size else float("nan")


def arange(x):
    x = _finite(x)
    return float(np.max(x) - np.min(x)) if x.size else float("nan")


def p_range(x):
    x = _finite(x)
    return float(np.percentile(x, 95) - np.percentile(x, 5)) if x.size else float("nan")


def percentile(x, q):
    x = _finite(x)
    return float(np.percentile(x, q)) if x.size else float("nan")


def zscore_max(x):
    x = _finite(x)
    if x.size < 2:
        return float("nan")
    s = float(np.std(x))
    return float(np.max(np.abs((x - np.mean(x)) / s))) if s != 0 else 0.0


def mad_outlier_fraction(x, k=3.0):
    x = _finite(x)
    if x.size == 0:
        return float("nan")
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    if mad == 0:
        mad = float(np.std(x))
    if mad == 0:
        return 0.0
    return float(np.mean(np.abs(x - med) > k * mad))


def diff(a, b):
    return _arr(a) - _arr(b)


def abs_diff(a, b):
    return np.abs(_arr(a) - _arr(b))


def fraction_in_range(x, lo, hi):
    x = _finite(x)
    return float(np.mean((x >= lo) & (x <= hi))) if x.size else float("nan")


def fraction_outside_range(x, lo, hi):
    x = _finite(x)
    return float(np.mean((x < lo) | (x > hi))) if x.size else float("nan")


def ratio(a, b):
    a = _finite(a)
    b = _finite(b)
    num = float(np.sum(a))
    den = float(np.sum(b))
    return (num / den) if den != 0 else float("nan")


def coverage(a, b):
    return ratio(a, b)


def null_fraction(x):
    x = np.asarray(x, dtype=object).ravel()
    if x.size == 0:
        return float("nan")
    nulls = 0
    for v in x:
        if v is None:
            nulls += 1
        elif isinstance(v, float) and np.isnan(v):
            nulls += 1
        elif isinstance(v, str) and v.strip() == "":
            nulls += 1
    return float(nulls / x.size)


def saturation_sum_fail(sw, so, sg, eps=0.01):
    sw, so, sg = _arr(sw), _arr(so), _arr(sg)
    n = min(sw.size, so.size, sg.size)
    sw, so, sg = sw[:n], so[:n], sg[:n]
    m = np.isfinite(sw) & np.isfinite(so) & np.isfinite(sg)
    sw, so, sg = sw[m], so[m], sg[m]
    return float(np.mean(np.abs(sw + so + sg - 1.0) > eps)) if sw.size else float("nan")


def monotonic_fail(q):
    q = _finite(q)
    if q.size < 2:
        return 0.0
    return float(np.mean(q[1:] < q[:-1]))


def gradient_max(grid, dx=1.0, dy=None):
    g = np.asarray(grid, dtype=float)
    if g.ndim != 2:
        raise ValueError("gradient_max expects a 2D grid")
    dy = dx if dy is None else dy
    gy, gx = np.gradient(g, dx, dy)
    mag = np.sqrt(gx ** 2 + gy ** 2)
    return float(np.nanmax(mag)) if mag.size else float("nan")


def curvature_max(grid, dx=1.0, dy=None):
    g = np.asarray(grid, dtype=float)
    if g.ndim != 2:
        raise ValueError("curvature_max expects a 2D grid")
    dy = dx if dy is None else dy
    gy, gx = np.gradient(g, dx, dy)
    gyy, _ = np.gradient(gy, dx, dy)
    _, gxx = np.gradient(gx, dx, dy)
    lap = gxx + gyy
    return float(np.nanmax(np.abs(lap))) if lap.size else float("nan")


def angle_max(grid, dx=1.0, dy=None):
    g = np.asarray(grid, dtype=float)
    if g.ndim != 2:
        raise ValueError("angle_max expects a 2D grid")
    dy = dx if dy is None else dy
    gy, gx = np.gradient(g, dx, dy)
    mag = np.sqrt(gx ** 2 + gy ** 2)
    return float(np.nanmax(np.degrees(np.arctan(mag)))) if mag.size else float("nan")


def ks_pvalue(a, b):
    a, b = _finite(a), _finite(b)
    if a.size == 0 or b.size == 0 or _stats is None:
        return float("nan")
    return float(_stats.ks_2samp(a, b).pvalue)


def anova_pvalue(groups, values):
    groups = np.asarray(groups)
    values = _arr(values)
    m = np.isfinite(values)
    groups, values = groups[m], values[m]
    if _stats is None:
        return float("nan")
    cats = [values[groups == g] for g in np.unique(groups)]
    cats = [c for c in cats if c.size > 0]
    if len(cats) < 2:
        return float("nan")
    return float(_stats.f_oneway(*cats).pvalue)


def nearest_neighbor_index(points):
    pts = np.asarray(points, dtype=float)
    if pts.ndim != 2 or pts.shape[0] < 2:
        return float("nan")
    from scipy.spatial import distance
    d = distance.cdist(pts, pts)
    np.fill_diagonal(d, np.inf)
    d_obs = np.min(d, axis=1)
    n = pts.shape[0]
    extent = np.ptp(pts, axis=0)
    area = float(np.prod(extent))
    if area <= 0:
        return float("nan")
    d_exp = 0.5 / np.sqrt(n / area)
    return float(np.mean(d_obs) / d_exp) if d_exp > 0 else float("nan")


def all_true(x):
    x = np.asarray(x)
    return float(np.all(x)) if x.size else 0.0


def count_false(x):
    x = np.asarray(x)
    return float(np.sum(~x.astype(bool))) if x.size else float("nan")


def fraction_abs_above(a, b, tol=0.0):
    d = np.abs(_arr(a) - _arr(b))
    d = d[np.isfinite(d)]
    return float(np.mean(d > tol)) if d.size else float("nan")