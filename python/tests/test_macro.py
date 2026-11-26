import pytest

from surgeflow import index_voter_metric_display


def _metrics(**overrides):
    metrics = {
        "schema_version": "index_voter_metrics_v1",
        "confusion": {"tp": 80, "fp": 30, "tn": 40, "fn": 50},
        "scored_votes": 200,
        "up_votes": 110,
        "down_votes": 90,
    }
    metrics.update(overrides)
    return metrics


def test_index_voter_metric_derivations():
    assert index_voter_metric_display(_metrics()) == {
        "Measured hit rate": "60.0%",
        "Always-up base rate": "65.0%",
        "Down-call hit rate": "44.4%",
    }


def test_index_voter_with_no_down_calls():
    display = index_voter_metric_display(
        _metrics(
            confusion={"tp": 55, "fp": 0, "tn": 0, "fn": 45},
            scored_votes=100,
            up_votes=55,
            down_votes=0,
        )
    )

    assert display == {
        "Measured hit rate": "55.0%",
        "Always-up base rate": "100.0%",
        "Down-call hit rate": "No down calls",
    }


@pytest.mark.parametrize(
    "metrics",
    [None, {}, True, float("nan"), float("inf"), _metrics(confusion=None)],
)
def test_unavailable_metrics_never_display_as_zero(metrics):
    assert index_voter_metric_display(metrics) == {
        "Measured hit rate": "Unavailable",
        "Always-up base rate": "Unavailable",
        "Down-call hit rate": "Unavailable",
    }


@pytest.mark.parametrize("scored_votes", [True, float("nan"), float("inf"), 0, 1.5])
def test_invalid_scored_votes_make_all_metrics_unavailable(scored_votes):
    display = index_voter_metric_display(_metrics(scored_votes=scored_votes))

    assert set(display.values()) == {"Unavailable"}
