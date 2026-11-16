"""Свёртка веера ансамбля по ФИЗИЧЕСКОЙ метрике (а не «успех/неуспех»).

Операторы: best (лучшая по метрике) | pareto (недоминируемое подмножество) |
p10_p50_p90 (распределение метрики по ветвям).
"""
from __future__ import annotations

# метрики, где «больше — лучше»
_MAX_METRICS = {"recovery_factor", "cumulative_oil", "success"}


def _metric_value(member, metric: str) -> float | None:
    metrics = getattr(member, "metrics", {}) or {}
    value = metrics.get(metric)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _scored(members: list, metric: str) -> list[tuple]:
    out = []
    for m in members:
        value = _metric_value(m, metric)
        if value is not None:
            out.append((m, value))
    return out


def _percentile(values: list[float], p: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    idx = min(len(values) - 1, max(0, int(round(p / 100 * (len(values) - 1)))))
    return values[idx]


def rollup(members: list, *, operator: str = "best",
           metric: str = "recovery_factor") -> dict:
    """Свёртка веера. Возвращает решение по ансамблю и полный список ветвей."""
    scored = _scored(members, metric)
    base = {"metric": metric, "members": [m.to_dict() for m in members],
            "scored": len(scored), "valid": len(scored) > 0}

    if operator == "pareto":
        pool = list(scored)
        frontier = [m for m in pool
                    if not any((v > _metric_value(n, metric)
                                and (n.metrics.get("success", 0) >= m.metrics.get("success", 0)))
                               for n, v in pool if n is not m)]
        return {**base, "operator": "pareto",
                "selected": [m.scenario_id for m in frontier]}

    if operator in {"p10_p50_p90", "aggregate"}:
        values = [v for _, v in scored]
        if not values:
            return {**base, "operator": "p10_p50_p90"}
        return {**base, "operator": "p10_p50_p90",
                "p10": _percentile(values, 10), "p50": _percentile(values, 50),
                "p90": _percentile(values, 90)}

    # best (по умолчанию): максимум метрики; при равенстве — с большим success
    if not scored:
        return {**base, "operator": "best"}
    winner, value = max(scored, key=lambda t: (t[1], t[0].metrics.get("success", 0)))
    return {**base, "operator": "best", "selected": winner.scenario_id, "value": value}
