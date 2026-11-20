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


def test_fund_portfolio_summary_flat_shape_and_empty_object():
    frame, status = summarize_payload(
        {"as_of_date": None, "nav_usd": 1000.0, "n_positions": 0,
         "state": "principal_cash_baseline_no_live_holdings"}
    )
    assert frame.iloc[0]["nav_usd"] == 1000.0
    assert "status: principal_cash_baseline_no_live_holdings" in status

    frame, status = summarize_payload({})
    assert frame.empty
    assert "empty response" in status


def test_jp_afternoon_session_runs_to_1530():
    assert is_market_open("jp", datetime(2026, 11, 23, 6, 15, tzinfo=timezone.utc)) is True
    assert is_market_open("jp", datetime(2026, 11, 23, 6, 30, tzinfo=timezone.utc)) is False


def test_closed_market_keeps_last_fetch_source_date():
    clock = Clock()
    clock.wall = datetime(2026, 11, 23, 20, 59, tzinfo=timezone.utc)
    panel = simple_panel(lambda: [{"value": 1}], market="us")
    monitor = Monitor([panel], monotonic=clock.monotonic, now=clock.now)
    monitor.run_due()
    clock.tick, clock.wall = 43200, datetime(2026, 11, 24, 8, 59, tzinfo=timezone.utc)
    monitor.run_due()

    status = monitor.states["panel"].status
    assert status.startswith("Market closed")
    assert "checked at 2026-11-24T08:59:00+00:00" in status
    assert "table shows the last fetch: Source date: 2026-11-20" in status
    assert "fetched at 2026-11-23T20:59:00+00:00" in status


def test_budget_stop_resumes_on_next_utc_day():
    clock = Clock()
    clock.wall = datetime(2026, 11, 23, 23, 50, tzinfo=timezone.utc)
    calls = []
    panel = simple_panel(lambda: calls.append(1) or [{"value": 1}], cadence=60)
    budget = RequestBudget(daily_limit=1, day="2026-11-23")
    monitor = Monitor([panel], budget=budget, monotonic=clock.monotonic, now=clock.now)
    monitor.run_due()
    clock.tick = 60
    monitor.run_due()
    assert monitor.stopped is True and calls == [1]

    clock.tick, clock.wall = 900, datetime(2026, 11, 24, 0, 5, tzinfo=timezone.utc)
    monitor.run_due()

    assert monitor.stopped is False
    assert calls == [1, 1]
    assert budget.day == "2026-11-24" and budget.used == 1


def test_render_marks_changed_rows_without_jinja2(monkeypatch, capsys):
    import IPython.display
    import surgeflow.monitor as monitor_module

    shown = []
    monkeypatch.setattr(monitor_module, "_HAS_JINJA2", False)
    monkeypatch.setattr(IPython.display, "display", shown.append)
    monkeypatch.setattr(IPython.display, "clear_output", lambda wait=False: None)
    clock = Clock()
    rows = [{"ticker": "AAA"}]
    panels = [simple_panel(lambda: rows, name=name) for name in ("one", "two")]
    monitor = Monitor(panels, monotonic=clock.monotonic, now=clock.now)
    monitor.run_due()
    rows = [{"ticker": "BBB"}]
    clock.tick = 1000
    monitor.run_due()
    monitor.render()

    out = capsys.readouterr().out
    assert "one" in out and "two" in out and "Error" not in out
    assert len(shown) == 2
    assert list(shown[0]["_changed"]) == ["changed"]


def test_render_error_in_one_panel_keeps_later_panels(monkeypatch, capsys):
    import IPython.display

    calls = []

    def display(frame):
        calls.append(frame)
        if len(calls) == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(IPython.display, "display", display)
    monkeypatch.setattr(IPython.display, "clear_output", lambda wait=False: None)
    clock = Clock()
    panels = [simple_panel(lambda: [{"ticker": "AAA"}], name=n) for n in ("one", "two")]
    monitor = Monitor(panels, monotonic=clock.monotonic, now=clock.now)
    monitor.run_due()
    monitor.render()

    assert "Error rendering one: RuntimeError: boom" in capsys.readouterr().out
    assert len(calls) == 2


def test_seed_budget_from_rate_limit():
    from surgeflow.monitor import seed_budget_from_rate_limit

    budget = RequestBudget(daily_limit=1500, used=1)
    assert seed_budget_from_rate_limit(budget, {"X-RateLimit-Daily-Limit": "2000"}) is None
    assert seed_budget_from_rate_limit(budget, None) is None
    assert budget.used == 1
    assert seed_budget_from_rate_limit(budget, {"X-RateLimit-Daily-Remaining": "1900"}) == 1900
    assert budget.used == 1
    assert seed_budget_from_rate_limit(budget, {"X-RateLimit-Daily-Remaining": "100"}) == 100
    assert budget.remaining == 100
