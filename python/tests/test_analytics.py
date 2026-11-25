import json
import os
from collections import Counter
from pathlib import Path

import pytest

from surgeflow import cohort_analytics_rows, summarize_cohort_analytics
from surgeflow._analytics import COHORT_ANALYTICS_METRICS, NO_ANALYTICS

FIXTURES = Path(__file__).parent / "fixtures"
# Optional: point SURGEFLOW_REAL_COHORT_SAMPLE at a saved published US cohort feed.
_SAMPLE = os.environ.get("SURGEFLOW_REAL_COHORT_SAMPLE", "").strip()
REAL_SAMPLE = Path(_SAMPLE) if _SAMPLE else None


def fixture_payload():
    return json.loads(
        (FIXTURES / "technical-cohorts-us.json").read_text(encoding="utf-8")
    )


def test_each_status_and_available_value_render_without_missing_placeholders():
    rows = cohort_analytics_rows(fixture_payload())

    assert {
        name: rows[0][name] for name in COHORT_ANALYTICS_METRICS
    } == {
        "window_return": "1.00%",
        "benchmark_window_return": "1.50%",
        "active_mean_ann": "12.00%",
        "volatility_daily": "20.00%",
        "tracking_error_ann": "2.00%",
        "information_ratio_ann": "1.00",
        "sharpe_ann": "1.25",
        "ic_mean_30d": "0.046",
    }
    assert rows[1]["benchmark_window_return"] == "incomplete: synthetic_incomplete"
    assert rows[1]["sharpe_ann"] == "incomplete: missing_risk_free_or_return"
    assert rows[2]["window_return"] == "not_computable: fewer_than_10_sessions"

    for row in rows:
        for name in COHORT_ANALYTICS_METRICS:
            assert row[name] not in (None, "", 0, 0.0, "0", "0.00", "0.00%")
    assert rows[1]["window_return"] == "3.00%"
    assert rows[0]["window"] == "30 of target 30 sessions, minimum 10"


def test_unknown_keys_and_carried_risk_free_are_tolerated():
    payload = fixture_payload()
    analytics = payload["cohorts"][0]["observation"]["analytics"]
    assert analytics["future_analytics_field"] == {"anything": "ignored"}
    assert analytics["portfolio"]["sharpe_ann"]["future_sharpe_flag"] is True

    rows = cohort_analytics_rows(payload)

    assert rows[0]["sharpe_ann"] == "1.25"
    assert rows[0]["_risk_free_proxy"] is True
    assert rows[0]["_risk_free_carried"] is True
    assert rows[1]["_risk_free_carried"] is False


def test_cohort_without_analytics_has_explicit_text():
    row = cohort_analytics_rows(fixture_payload())[3]

    assert row["window"] == NO_ANALYTICS
    assert all(row[name] == NO_ANALYTICS for name in COHORT_ANALYTICS_METRICS)


def test_analytics_statistics_use_only_available_values_for_medians():
    summary = summarize_cohort_analytics(fixture_payload())

    assert summary["cohort_count"] == 4
    assert summary["window_n_at_least_10"] == 2
    assert summary["not_published_count"] == 1
    assert summary["status_counts"]["window_return"] == {
        "available": 2,
        "incomplete": 0,
        "not_computable": 1,
    }
    assert summary["status_counts"]["sharpe_ann"] == {
        "available": 1,
        "incomplete": 1,
        "not_computable": 1,
    }
    assert summary["medians"] == {
        "window_return": pytest.approx(0.02),
        "information_ratio_ann": pytest.approx(2.0),
        "tracking_error_ann": pytest.approx(0.03),
    }
    assert summary["risk_free_carried"] is True


@pytest.mark.skipif(
    REAL_SAMPLE is None or not REAL_SAMPLE.is_file(),
    reason="set SURGEFLOW_REAL_COHORT_SAMPLE to a saved cohort feed",
)
def test_real_sample_rows_and_sharpe_status_counts():
    payload = json.loads(REAL_SAMPLE.read_text(encoding="utf-8"))

    rows = cohort_analytics_rows(payload)

    # These counts match the feed published on 2026-11-24; a later sample may differ.
    assert len(rows) == 156
    assert Counter(row["sharpe_ann"].split(":", 1)[0] for row in rows) == {
        "incomplete": 144,
        "not_computable": 12,
    }


def _cohort(cohort_id, n, market="us", benchmark="S&P 500", metric=None):
    analytics = {
        "window": {"n": n, "target": 30, "minimum": 10},
        "benchmark": {"name": benchmark},
        "portfolio": {"window_return": metric or {"status": "available", "value": 0.01, "n": n}},
    }
    return {"cohort_id": cohort_id, "market": market, "observation": {"analytics": analytics}}


def test_rows_name_market_and_benchmark_from_the_feed():
    rows = cohort_analytics_rows({"cohorts": [_cohort("hk-1", 12, market="hk", benchmark="Hang Seng Index")]})
    assert rows[0]["market"] == "hk"
    assert rows[0]["benchmark"] == "Hang Seng Index"


def test_rows_put_longest_windows_first_and_no_analytics_last():
    payload = {"cohorts": [_cohort("a", 3), {"cohort_id": "old"}, _cohort("b", 12), _cohort("c", 12), _cohort("d", 0)]}
    assert [row["cohort_id"] for row in cohort_analytics_rows(payload)] == ["b", "c", "a", "d", "old"]


@pytest.mark.parametrize("bad", [True, float("inf"), float("nan"), "abc", None])
def test_window_label_never_prints_invalid_numbers(bad):
    label = cohort_analytics_rows({"cohorts": [_cohort("x", bad)]})[0]["window"]
    assert label == "not supplied of target 30 sessions, minimum 10"


def test_available_without_a_value_counts_as_incomplete():
    payload = {"cohorts": [_cohort("x", 12, metric={"status": "available", "value": None})]}
    assert cohort_analytics_rows(payload)[0]["window_return"] == "incomplete: value not supplied"
    summary = summarize_cohort_analytics(payload)
    assert summary["status_counts"]["window_return"]["available"] == 0
    assert summary["status_counts"]["window_return"]["incomplete"] == 1
    assert summary["medians"]["window_return"] is None


def test_fractional_window_n_is_not_counted():
    payload = {"cohorts": [_cohort("x", 12.5)]}
    assert cohort_analytics_rows(payload)[0]["window"].startswith("not supplied of target")
    assert summarize_cohort_analytics(payload)["window_n_at_least_10"] == 0
