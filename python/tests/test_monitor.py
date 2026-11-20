from datetime import datetime, timezone

import pandas as pd
import pytest

from surgeflow import SurgeFlowApiError
from surgeflow.monitor import (
    Monitor,
    Panel,
    RequestBudget,
    _with_change_flags,
    default_panels,
    is_market_open,
    projected_requests_per_day,
    summarize_payload,
)


class Clock:
    def __init__(self):
        self.tick = 0.0
        self.wall = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)

    def monotonic(self):
        return self.tick

    def now(self):
        return self.wall


def simple_panel(fetch, cadence=120, name="panel", market=None):
    return Panel(
        "07 Hotlist", name, cadence, fetch,
        lambda payload: (pd.DataFrame(payload), "Source date: 2026-11-20; status: available"),
        market,
    )


def test_cadence_limits_fetches():
    clock = Clock()
    calls = []
    panel = simple_panel(lambda: calls.append(clock.tick) or [{"value": 1}])
    monitor = Monitor([panel], monotonic=clock.monotonic, now=clock.now)

    monitor.run_due()
    clock.tick = 119
    monitor.run_due()
    clock.tick = 120
    monitor.run_due()

    assert calls == [0.0, 120.0]


def test_budget_stops_before_request_over_limit():
    clock = Clock()
    calls = []
    first = simple_panel(lambda: calls.append("first") or [{"value": 1}], name="first")
    second = simple_panel(lambda: calls.append("second") or [{"value": 2}], name="second")
    budget = RequestBudget(daily_limit=1)
    monitor = Monitor(
        [first, second], budget=budget,
        monotonic=clock.monotonic, now=clock.now
    )

    monitor.run_due()

    assert calls == ["first"]
    assert budget.used == 1
    assert monitor.stopped is True
    assert "Budget stop" in monitor.states["second"].status


@pytest.mark.parametrize(
    "market,wall,expected",
    [
        ("us", datetime(2026, 11, 23, 14, 30, tzinfo=timezone.utc), True),
        ("us", datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc), False),
        ("cn", datetime(2026, 11, 23, 4, 0, tzinfo=timezone.utc), False),
        ("cn", datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc), True),
        ("jp", datetime(2026, 11, 23, 3, 0, tzinfo=timezone.utc), False),
        ("jp", datetime(2026, 11, 23, 3, 30, tzinfo=timezone.utc), True),
        ("hk", datetime(2026, 11, 23, 4, 30, tzinfo=timezone.utc), False),
        ("hk", datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc), True),
    ],
)
def test_fixed_session_gating(market, wall, expected):
    assert is_market_open(market, wall) is expected


def test_closed_market_does_not_fetch():
    clock = Clock()
    clock.wall = datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc)
    calls = []
    panel = simple_panel(lambda: calls.append(1) or [{"value": 1}], market="us")
    monitor = Monitor([panel], monotonic=clock.monotonic, now=clock.now)

    monitor.run_due()

    assert calls == []
    assert "holidays are not handled" in monitor.states["panel"].status


def test_retry_after_delays_next_fetch():
    clock = Clock()
    calls = []

    def fetch():
        calls.append(clock.tick)
        if len(calls) == 1:
            raise SurgeFlowApiError(429, "Slow down", retry_after=17)
        return [{"value": 1}]

    panel = simple_panel(fetch)
    monitor = Monitor([panel], monotonic=clock.monotonic, now=clock.now)
    monitor.run_due()
    clock.tick = 16
    monitor.run_due()
    clock.tick = 17
    monitor.run_due()

    assert calls == [0.0, 17.0]
    assert "Retry-After 17 seconds" in monitor.states["panel"].status or monitor.states["panel"].frame is not None


def test_change_detection_marks_changed_rows_and_counts_removed():
    first = pd.DataFrame([{"ticker": "A", "value": 1}, {"ticker": "B", "value": 2}])
    flagged, hashes, removed = _with_change_flags(first, None)
    assert flagged["_changed"].tolist() == [False, False]
    assert removed == 0

    second = pd.DataFrame([
        {"ticker": "A", "value": 3},
        {"ticker": "B", "value": 2},
        {"ticker": "C", "value": 4},
    ])
    flagged, _, removed = _with_change_flags(second, hashes)

    assert flagged["_changed"].tolist() == [True, False, True]
    assert removed == 1


def test_default_projection_is_under_budget():
    panels = default_panels(object(), "sf_live_REPLACE_WITH_YOUR_KEY")

    assert projected_requests_per_day(panels) == 1226
    assert len(panels) == 19


def test_empty_payload_status_is_not_silent():
    frame, status = summarize_payload({"data": {"status": "unavailable", "message": "No run", "rows": []}})

    assert frame.empty
    assert "No run" in status
    assert "empty response" in status


def test_nested_book_date_appears_in_status():
    payload = {
        "data": {
            "status": "available",
            "portfolio": {
                "formation_date": "2026-11-16",
                "books": [{"factor": "VALUE", "status": "available", "n_holdings": 1}],
            },
        }
    }

    frame, status = summarize_payload(payload)

    assert frame.iloc[0]["formation_date"] == "2026-11-16"
    assert "Source date: 2026-11-16" in status
