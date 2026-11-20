from dataclasses import dataclass, field
from datetime import datetime, time as wall_time, timezone
import math
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from ._errors import SurgeFlowApiError

try:
    import pandas as pd
except ImportError as exc:
    raise ImportError(
        "surgeflow.monitor needs pandas; install surgeflow[notebooks]"
    ) from exc

SummarizeResult = Tuple[Any, str]


@dataclass(frozen=True)
class Panel:
    offering: str
    name: str
    cadence_seconds: int
    fetch: Callable[[], Any]
    summarize: Callable[[Any], SummarizeResult]
    market: Optional[str] = None
    cost: int = 1

    def __post_init__(self) -> None:
        if self.cadence_seconds <= 0:
            raise ValueError("cadence_seconds must be greater than zero")
        if self.cost <= 0:
            raise ValueError("cost must be greater than zero")


@dataclass
class PanelState:
    next_attempt: float = 0.0
    frame: Any = None
    status: str = "Not fetched yet."
    previous_hashes: Any = None


@dataclass
class RequestBudget:
    daily_limit: int = 1500
    used: int = 0
    day: str = field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat()
    )

    def __post_init__(self) -> None:
        if (
            isinstance(self.daily_limit, bool)
            or not isinstance(self.daily_limit, int)
            or not 1 <= self.daily_limit <= 1500
        ):
            raise ValueError("daily_limit must be an integer from 1 through 1500")

    def consume(self, cost: int = 1, now: Optional[datetime] = None) -> bool:
        current_day = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        current_day_text = current_day.date().isoformat()
        if current_day_text != self.day:
            self.day = current_day_text
            self.used = 0
        if cost <= 0 or self.used + cost > self.daily_limit:
            return False
        self.used += cost
        return True

    @property
    def remaining(self) -> int:
        return self.daily_limit - self.used


# shortcut: fixed exchange hours ignore exchange holidays and exceptional closures.
SESSIONS = {
    "us": ("America/New_York", ((wall_time(9, 30), wall_time(16, 0)),)),
    "cn": (
        "Asia/Shanghai",
        ((wall_time(9, 30), wall_time(11, 30)), (wall_time(13, 0), wall_time(15, 0))),
    ),
    "jp": (
        "Asia/Tokyo",
        ((wall_time(9, 0), wall_time(11, 30)), (wall_time(12, 30), wall_time(15, 0))),
    ),
    "hk": (
        "Asia/Hong_Kong",
        ((wall_time(9, 30), wall_time(12, 0)), (wall_time(13, 0), wall_time(16, 0))),
    ),
}


def is_market_open(market: str, now: datetime) -> bool:
    if market not in SESSIONS:
        raise ValueError("market must be us, cn, jp, or hk")
    zone_name, windows = SESSIONS[market]
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(ZoneInfo(zone_name))
    if local.weekday() >= 5:
        return False
    current = local.time().replace(tzinfo=None)
    return any(start <= current < end for start, end in windows)


def projected_requests_per_day(panels: Sequence[Panel]) -> int:
    total = 0
    for panel in panels:
        if panel.market is None:
            active_seconds = 86400
        else:
            _, windows = SESSIONS[panel.market]
            active_seconds = sum(
                (end.hour * 3600 + end.minute * 60 + end.second)
                - (start.hour * 3600 + start.minute * 60 + start.second)
                for start, end in windows
            )
        total += (active_seconds // panel.cadence_seconds) * panel.cost
    return total


def _scalar_rows(rows: List[Dict[str, Any]]) -> Any:
    return pd.DataFrame(
        [
            {
                key: value
                for key, value in row.items()
                if value is None or isinstance(value, (str, int, float, bool))
            }
            for row in rows
        ]
    )


def _first(payload: Dict[str, Any], names: Sequence[str]) -> Any:
    data = payload.get("data")
    snapshot = payload.get("snapshot")
    source = data.get("source") if isinstance(data, dict) else None
    for container in (data, payload, snapshot, source):
        if isinstance(container, dict):
            for name in names:
                value = container.get(name)
                if value not in (None, ""):
                    return value
    return None


def summarize_payload(payload: Dict[str, Any]) -> SummarizeResult:
    data = payload.get("data", payload)
    rows: List[Dict[str, Any]] = []
    if isinstance(data, list):
        rows = [row for row in data if isinstance(row, dict)]
    elif isinstance(data, dict):
        if isinstance(data.get("rows"), list):
            rows = [row for row in data["rows"] if isinstance(row, dict)]
        elif isinstance(data.get("indexes"), list):
            for index in data["indexes"]:
                for voter in index.get("voters") or []:
                    rows.append(
                        {
                            "index_id": index.get("index_id"),
                            "index_label": index.get("label"),
                            "majority": (index.get("tally") or {}).get("majority"),
                            **voter,
                        }
                    )
        elif isinstance(data.get("categories"), list):
            for category in data["categories"]:
                for row in category.get("rows") or []:
                    rows.append({"category": category.get("id"), **row})
        elif isinstance(data.get("rankings"), list):
            for category in data["rankings"]:
                for row in category.get("rows") or []:
                    rows.append({"category": category.get("id"), **row})
        elif isinstance(data.get("watchlists"), list):
            for watchlist in data["watchlists"]:
                items = watchlist.get("items") or [None]
                for item in items:
                    rows.append(
                        {
                            "watchlist_id": watchlist.get("watchlist_id"),
                            "name": watchlist.get("name"),
                            "updated_at": watchlist.get("updated_at"),
                            **(item or {}),
                        }
                    )
        elif isinstance(data.get("portfolios"), list):
            for portfolio in data["portfolios"]:
                row = dict(portfolio)
                row.pop("holdings", None)
                rows.append(row)
        elif isinstance(data.get("alerts"), list):
            rows = [row for row in data["alerts"] if isinstance(row, dict)]
        elif isinstance(data.get("screens"), list):
            rows = [row for row in data["screens"] if isinstance(row, dict)]
        elif isinstance(data.get("cards"), list):
            for card in data["cards"]:
                for item in card.get("items") or [None]:
                    rows.append(
                        {
                            "card_id": card.get("id"),
                            "title": card.get("title"),
                            "body": card.get("body"),
                            **(item or {}),
                        }
                    )
        elif isinstance(data.get("portfolio"), dict):
            for book in (data["portfolio"].get("books") or []):
                rows.append(
                    {
                        "formation_date": data["portfolio"].get("formation_date"),
                        **{key: value for key, value in book.items() if key != "holdings"},
                    }
                )
        elif isinstance(data.get("archive"), dict):
            for book in (data["archive"].get("books") or []):
                rows.append(
                    {
                        "formation_date": data["archive"].get("formation_date"),
                        **{key: value for key, value in book.items() if key != "holdings"},
                    }
                )
        elif isinstance(data.get("bull"), list) or isinstance(data.get("bear"), list):
            for side in ("bull", "bear"):
                for row in data.get(side) or []:
                    rows.append({"side": side, **row})
        elif isinstance(data.get("votes"), dict):
            rows = [
                {
                    "as_of_date": (data.get("source") or {}).get("as_of_date"),
                    "score": data.get("score"),
                    "state": data.get("state"),
                    "regime_confirmation": data.get("regime_confirmation"),
                    **{f"vote_{key}": value for key, value in data["votes"].items()},
                }
            ]
        else:
            rows = [data]
    elif isinstance(payload, dict):
        rows = [payload]

    frame = _scalar_rows(rows)
    source_date = _first(
        payload,
        (
            "as_of_date",
            "as_of",
            "as_of_utc",
            "date",
            "formation_date",
            "statement_watermark",
            "_rebuild_date",
            "whale_as_of",
            "news_rebuild_date",
            "published_at",
        ),
    )
    if source_date is None and not frame.empty:
        for name in (
            "as_of_date", "as_of_utc", "date", "formation_date",
            "statement_watermark", "updated_at", "created_at", "available_at",
        ):
            if name in frame and frame[name].notna().any():
                source_date = frame[name].dropna().iloc[0]
                break
    status = _first(
        payload, ("status", "state", "market_status", "data_quality", "source_mode")
    )
    message = _first(
        payload, ("message", "reason", "stale_reason", "reason_code")
    )
    parts = [
        f"Source date: {source_date or 'not supplied'}",
        f"status: {status or 'not supplied'}",
    ]
    if message:
        parts.append(f"message: {message}")
    if frame.empty:
        parts.append("empty response; no rows returned")
    return frame, "; ".join(parts)


def _with_change_flags(frame: Any, previous_hashes: Any) -> Tuple[Any, Any, int]:
    current = frame.copy()
    if current.empty:
        hashes = pd.Series(dtype="uint64")
    else:
        hashes = pd.util.hash_pandas_object(current, index=False)
    if previous_hashes is None:
        current["_changed"] = False
        return current, hashes, 0
    previous = set(previous_hashes.tolist())
    current["_changed"] = ~hashes.isin(previous)
    removed = len(previous - set(hashes.tolist()))
    return current, hashes, removed


class Monitor:
    def __init__(
        self,
        panels: Sequence[Panel],
        budget: Optional[RequestBudget] = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.panels = list(panels)
        self.budget = budget or RequestBudget()
        self.monotonic = monotonic
        self.now = now
        self.states = {panel.name: PanelState() for panel in self.panels}
        self.stopped = False

    def print_projection(self) -> int:
        projected = projected_requests_per_day(self.panels)
        print(f"Projected scheduled requests per full active day: {projected}")
        print(f"Local daily request budget: {self.budget.daily_limit}")
        print("Each panel refreshes on a schedule; each panel shows its source date.")
        return projected

    def run_due(self) -> None:
        tick = self.monotonic()
        wall_now = self.now()
        for panel in self.panels:
            state = self.states[panel.name]
            if tick < state.next_attempt:
                continue
            if panel.market is not None and not is_market_open(panel.market, wall_now):
                state.status = (
                    "Market closed under fixed weekday hours; holidays are not handled; "
                    f"fetched at {wall_now.isoformat()}"
                )
                state.next_attempt = tick + panel.cadence_seconds
                continue
            if self.stopped or not self.budget.consume(panel.cost, wall_now):
                self.stopped = True
                state.status = (
                    f"Budget stop at {self.budget.used}/{self.budget.daily_limit} requests; "
                    f"fetched at {wall_now.isoformat()}"
                )
                state.next_attempt = math.inf
                continue
            try:
                payload = panel.fetch()
                frame, status = panel.summarize(payload)
                frame, hashes, removed = _with_change_flags(
                    frame, state.previous_hashes
                )
                state.frame = frame
                state.previous_hashes = hashes
                state.status = f"{status}; fetched at {wall_now.isoformat()}"
                if removed:
                    state.status += f"; {removed} prior row versions no longer present"
                state.next_attempt = tick + panel.cadence_seconds
            except SurgeFlowApiError as exc:
                delay = panel.cadence_seconds
                if exc.status_code == 429:
                    delay = (
                        max(0.0, exc.retry_after)
                        if exc.retry_after is not None
                        else panel.cadence_seconds
                    )
                    state.status = (
                        f"HTTP 429; Retry-After {delay:g} seconds; message: {exc}; "
                        f"fetched at {wall_now.isoformat()}"
                    )
                else:
                    state.status = (
                        f"HTTP {exc.status_code}; message: {exc}; "
                        f"fetched at {wall_now.isoformat()}"
                    )
                state.next_attempt = tick + delay
            except Exception as exc:
                state.status = (
                    f"Error {type(exc).__name__}: {exc}; "
                    f"fetched at {wall_now.isoformat()}"
                )
                state.next_attempt = tick + panel.cadence_seconds

    def render(self) -> None:
        from IPython.display import clear_output, display

        clear_output(wait=True)
        print(f"Requests used locally: {self.budget.used}/{self.budget.daily_limit}")
        for panel in self.panels:
            state = self.states[panel.name]
            print(f"\n{panel.offering} — {panel.name}\n{state.status}")
            if state.frame is None:
                print("No response rows.")
            elif state.frame.empty:
                print("Empty response; no table to display.")
            else:
                if "_changed" in state.frame:
                    styled = state.frame.style.apply(
                        lambda row: [
                            "background-color: #fff3cd" if row["_changed"] else ""
                            for _ in row
                        ],
                        axis=1,
                    )
                    display(styled)
                else:
                    display(state.frame)


def default_panels(client: Any, api_key: str, hotlist_market: str = "us") -> List[Panel]:
    if hotlist_market not in SESSIONS:
        raise ValueError("hotlist_market must be us, cn, jp, or hk")

    def panel(
        offering: str,
        name: str,
        cadence: int,
        fetch: Callable[[], Any],
        market: Optional[str] = None,
    ) -> Panel:
        return Panel(offering, name, cadence, fetch, summarize_payload, market)

    return [
        panel("01 Macro model votes", "model-votes", 1800,
              lambda: client.member_macro_model_votes(api_key)),
        panel("01 Macro model votes", "index-votes", 1800,
              lambda: client.member_macro_index_votes(api_key)),
        panel("01 Macro model votes", "cycle-composites", 1800,
              lambda: client.member_macro_cycle_composites(api_key)),
        panel("01 Macro model votes", "recession-probability", 1800,
              lambda: client.member_macro_recession_probability(api_key)),
        panel("01 Macro model votes", "hmm-regime", 1800,
              lambda: client.member_fund_hmm_regime(api_key)),
        panel("02 Bull & bear sentiment picks", "news-led-scores", 1800,
              lambda: client.member_sentiment_scores("us", api_key, limit=10)),
        panel("02 Bull & bear sentiment picks", "whale-picks", 1800,
              lambda: client.member_sentiment_whale_picks("us", api_key)),
        panel("04 Pure factor portfolios", "weekly-pure-books", 21600,
              lambda: client.member_weekly_pure_books(api_key)),
        panel("04 Pure factor portfolios", "historical-pure-books", 21600,
              lambda: client.member_historical_pure_books(api_key)),
        panel("04 Pure factor portfolios", "three-model-portfolios", 21600,
              lambda: client.member_three_model_portfolios(api_key)),
        panel("05 Fundamental rankings", "fundamental-picks", 21600,
              lambda: client.member_fundamental_picks(api_key)),
        panel("05 Fundamental rankings", "fundamental-peers", 21600,
              lambda: client.member_fundamental_peers(api_key, "AAPL")),
        panel("06 Managerial Control", "watchlists", 300,
              lambda: client.member_watchlists(api_key)),
        panel("06 Managerial Control", "screens", 1800,
              lambda: client.member_screens(api_key)),
        panel("06 Managerial Control", "alerts", 1800,
              lambda: client.member_alerts(api_key)),
        panel("06 Managerial Control", "portfolio", 1800,
              lambda: client.member_portfolio(api_key)),
        panel("07 Hotlist", f"{hotlist_market}-hotlist", 120,
              lambda: client.member_hotlist(hotlist_market, api_key), hotlist_market),
        panel("07 Hotlist", f"{hotlist_market}-realtime", 120,
              lambda: client.member_realtime(hotlist_market, api_key), hotlist_market),
        panel("08 Daily actionable insights", "daily-insights", 1800,
              lambda: client.member_daily_insights(api_key)),
    ]
