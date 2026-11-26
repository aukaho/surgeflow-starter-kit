from typing import Any, Dict

from ._analytics import _number

_LABELS = ("Measured hit rate", "Always-up base rate", "Down-call hit rate")


def _unavailable() -> Dict[str, str]:
    return {label: "Unavailable" for label in _LABELS}


def _whole_number(value: Any) -> Any:
    number = _number(value)
    if number is None or number < 0 or number != int(number):
        return None
    return int(number)


def index_voter_metric_display(metrics: Any) -> Dict[str, str]:
    """Return display strings for an index voter's measured metrics."""
    if not isinstance(metrics, dict) or not isinstance(metrics.get("confusion"), dict):
        return _unavailable()

    confusion = metrics["confusion"]
    scored_votes = _whole_number(metrics.get("scored_votes"))
    down_votes = _whole_number(metrics.get("down_votes"))
    counts = {name: _whole_number(confusion.get(name)) for name in ("tp", "tn", "fn")}
    if (
        not scored_votes
        or down_votes is None
        or any(value is None for value in counts.values())
    ):
        return _unavailable()

    tp, tn, fn = counts["tp"], counts["tn"], counts["fn"]
    return {
        "Measured hit rate": f"{(tp + tn) / scored_votes:.1%}",
        "Always-up base rate": f"{(tp + fn) / scored_votes:.1%}",
        "Down-call hit rate": (
            f"{tn / down_votes:.1%}" if down_votes else "No down calls"
        ),
    }
