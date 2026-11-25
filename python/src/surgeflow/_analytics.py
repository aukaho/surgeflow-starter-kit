import math
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

COHORT_ANALYTICS_METRICS = (
    "window_return",
    "benchmark_window_return",
    "active_mean_ann",
    "volatility_daily",
    "tracking_error_ann",
    "information_ratio_ann",
    "sharpe_ann",
    "ic_mean_30d",
)
MEDIAN_METRICS = ("window_return", "information_ratio_ann", "tracking_error_ann")
NO_ANALYTICS = "analytics not published for this cohort"
_STATUSES = ("available", "incomplete", "not_computable")
_PERCENT_METRICS = {
    "window_return",
    "benchmark_window_return",
    "active_mean_ann",
    "volatility_daily",
    "tracking_error_ann",
}


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _format_value(name: str, value: float) -> str:
    if name in _PERCENT_METRICS:
        return f"{value:.2%}"
    if name == "ic_mean_30d":
        return f"{value:.3f}"
    return f"{value:.2f}"


def _metric(analytics: Dict[str, Any], name: str) -> Any:
    group = "skill" if name == "ic_mean_30d" else "portfolio"
    container = analytics.get(group)
    return container.get(name) if isinstance(container, dict) else None


def _metric_display(name: str, metric: Any) -> Tuple[str, Optional[float], str]:
    if not isinstance(metric, dict):
        return "not_computable", None, "not_computable: metric not published"
    status = metric.get("status")
    reason = metric.get("reason")
    reason_text = reason if isinstance(reason, str) and reason else "reason not supplied"
    if status == "available":
        value = _number(metric.get("value"))
        if value is None:
            # Counted as incomplete so the monitor's available count matches its medians.
            return "incomplete", None, "available: value not supplied"
        return status, value, _format_value(name, value)
    if status in ("incomplete", "not_computable"):
        return status, None, f"{status}: {reason_text}"
    return "not_computable", None, "not_computable: metric not published"


def _contains_carried_risk_free(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "risk_free_carried" and item is True:
                return True
            if _contains_carried_risk_free(item):
                return True
    elif isinstance(value, list):
        return any(_contains_carried_risk_free(item) for item in value)
    return False


def _text(value: Any) -> str:
    return str(value) if value not in (None, "") else "not supplied"


def _count_text(value: Any) -> str:
    number = _number(value)
    return str(int(number)) if number is not None and number == int(number) else "not supplied"


def _records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = payload.get("data", payload)
    if not isinstance(data, dict) or not isinstance(data.get("cohorts"), list):
        return []
    records = []
    for cohort in data["cohorts"]:
        if not isinstance(cohort, dict):
            continue
        observation = cohort.get("observation")
        observation = observation if isinstance(observation, dict) else {}
        analytics = observation.get("analytics")
        row = {
            "cohort_id": _text(cohort.get("cohort_id")),
            "strategy_id": _text(cohort.get("strategy_id")),
            "market": _text(cohort.get("market") or data.get("market") or "us"),
            "weighting": _text(cohort.get("weighting")),
            "as_of": _text(
                cohort.get("as_of") or observation.get("as_of")
            ),
        }
        if not isinstance(analytics, dict):
            row["benchmark"] = NO_ANALYTICS
            row["window"] = NO_ANALYTICS
            row.update({name: NO_ANALYTICS for name in COHORT_ANALYTICS_METRICS})
            row.update(
                {
                    "_window_n": None,
                    "_statuses": None,
                    "_values": {},
                    "_risk_free_proxy": False,
                    "_risk_free_carried": False,
                }
            )
            records.append(row)
            continue

        row["as_of"] = _text(
            analytics.get("as_of") or observation.get("as_of") or cohort.get("as_of")
        )
        benchmark = analytics.get("benchmark")
        row["benchmark"] = _text(benchmark.get("name") if isinstance(benchmark, dict) else None)
        window = analytics.get("window")
        window = window if isinstance(window, dict) else {}
        window_n = _number(window.get("n"))
        row["window"] = (
            f"{_count_text(window.get('n'))} of target {_count_text(window.get('target'))} sessions, "
            f"minimum {_count_text(window.get('minimum'))}"
            if window
            else "not_computable: window not published"
        )
        statuses = {}
        values = {}
        for name in COHORT_ANALYTICS_METRICS:
            status, value, display = _metric_display(name, _metric(analytics, name))
            statuses[name] = status
            values[name] = value
            row[name] = display
        risk_free = analytics.get("risk_free")
        row.update(
            {
                "_window_n": window_n,
                "_statuses": statuses,
                "_values": values,
                "_risk_free_proxy": (
                    isinstance(risk_free, dict) and risk_free.get("proxy") is True
                ),
                "_risk_free_carried": _contains_carried_risk_free(analytics),
            }
        )
        records.append(row)
    return records


def cohort_analytics_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return one display-ready analytics row for each cohort in a feed payload.

    Available values use display formatting. Other statuses retain their supplied
    reasons, and older cohorts without analytics use an explicit not-published
    message. Unknown fields are ignored, apart from the carried risk-free note.
    """
    private_keys = {"_window_n", "_statuses", "_values"}
    # Longest windows first (measurable cohorts on top); sorted() is stable, so feed order breaks ties.
    records = sorted(
        _records(payload),
        key=lambda row: (row["_window_n"] is None, -(row["_window_n"] or 0)),
    )
    return [
        {key: value for key, value in row.items() if key not in private_keys}
        for row in records
    ]


def summarize_cohort_analytics(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return window coverage, metric status counts, and available-value medians."""
    records = _records(payload)
    status_counts = {
        name: {status: 0 for status in _STATUSES}
        for name in COHORT_ANALYTICS_METRICS
    }
    available_values: Dict[str, List[float]] = {name: [] for name in MEDIAN_METRICS}
    for row in records:
        statuses = row["_statuses"]
        if statuses is not None:
            for name, status in statuses.items():
                status_counts[name][status] += 1
        for name in MEDIAN_METRICS:
            value = row["_values"].get(name)
            if value is not None:
                available_values[name].append(value)
    return {
        "cohort_count": len(records),
        "window_n_at_least_10": sum(
            row["_window_n"] is not None and row["_window_n"] >= 10 for row in records
        ),
        "not_published_count": sum(row["_statuses"] is None for row in records),
        "status_counts": status_counts,
        "medians": {
            name: median(available_values[name]) if available_values[name] else None
            for name in MEDIAN_METRICS
        },
        "risk_free_carried": any(row["_risk_free_carried"] for row in records),
    }


def format_cohort_analytics_summary(summary: Dict[str, Any]) -> str:
    """Format cohort analytics statistics as compact monitor status lines."""
    lines = [
        "SurgeFlow cohort analytics (research measurement, not a forecast): "
        "window target 30 sessions, minimum 10; "
        f"{summary['window_n_at_least_10']} of {summary['cohort_count']} cohorts "
        "have at least 10 sessions"
    ]
    if summary["not_published_count"]:
        lines[0] += (
            f"; {NO_ANALYTICS}: {summary['not_published_count']}"
        )
    counts = []
    for name in COHORT_ANALYTICS_METRICS:
        by_status = summary["status_counts"][name]
        counts.append(
            f"{name}={by_status['available']}/{by_status['incomplete']}/"
            f"{by_status['not_computable']}"
        )
    lines.append(
        "Analytics status counts (available/incomplete/not_computable): "
        + "; ".join(counts)
    )
    medians = []
    for name in MEDIAN_METRICS:
        value = summary["medians"][name]
        medians.append(
            f"{name}={_format_value(name, value) if value is not None else 'not available'}"
        )
    lines.append("Analytics medians (available values): " + "; ".join(medians))
    lines.append("A 30-session window is short and these estimates are noisy.")
    if summary["risk_free_carried"]:
        lines.append("For some dates, the risk-free rate is carried forward from the previous date.")
    return "\n".join(lines)
