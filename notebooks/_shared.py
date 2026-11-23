import getpass
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Optional

import pandas as pd
from IPython.display import display

from surgeflow import NotAvailableYet, SurgeFlow, SurgeFlowFeedUnavailable

PLACEHOLDER = "sf_live_REPLACE_WITH_YOUR_KEY"


def fixture_mode() -> bool:
    return os.environ.get("SURGEFLOW_FIXTURES") == "1"


# The synthetic fixtures are dated for this moment, so fixture runs do not expire.
FIXTURE_NOW = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)


def now_utc() -> datetime:
    return FIXTURE_NOW if fixture_mode() else datetime.now(timezone.utc)


def fetched_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_api_key() -> str:
    if fixture_mode():
        return PLACEHOLDER
    key = os.environ.get("SURGEFLOW_API_KEY", "").strip()
    if not key:
        key = getpass.getpass("SurgeFlow member key (hidden input): ").strip()
    if not key:
        raise ValueError("A SurgeFlow member key is required outside fixture mode")
    return key


def make_client():
    catalogue = SurgeFlow().catalog()
    base_url = os.environ.get("SURGEFLOW_BASE_URL", "").strip()
    if not base_url:
        base_url = str(catalogue["base_url"]).strip()
    if not base_url:
        raise ValueError("The catalogue did not provide base_url")
    return SurgeFlow(base_url=base_url), catalogue


def nested(payload: Dict[str, Any], *path: str) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def show_panel(
    title: str,
    payload: Dict[str, Any],
    rows: Iterable[Dict[str, Any]],
    columns: Dict[str, str],
    *,
    source_date: Any = None,
    status: Any = None,
    message: Optional[str] = None,
) -> Any:
    materialized = list(rows)
    frame = pd.DataFrame(
        [{name: row.get(name) for name in columns} for row in materialized],
        columns=list(columns),
    )
    print(title)
    print(
        f"Data status: {status or 'not supplied'}; "
        f"source date: {source_date or 'not supplied'}; fetched at: {fetched_at()}"
    )
    if message:
        print(f"Message: {message}")
    print("Column guide:")
    for name, explanation in columns.items():
        print(f"- {name}: {explanation}")
    if frame.empty:
        print(f"Empty response: {message or 'No rows returned.'}")
    else:
        display(frame)
    return frame


def fetch_payload(
    title: str, fetch: Callable[[], Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    try:
        return fetch()
    except SurgeFlowFeedUnavailable:
        print(
            f"{title}\nData status: Feed unavailable; source date: not supplied; "
            f"fetched at: {fetched_at()}"
        )
        print("No member data fetched. The response was not replaced with an empty table.")
        return None
    except NotAvailableYet as exc:
        print(f"{title}\nUnavailable by member key: {exc}; fetched at: {fetched_at()}")
        print("No member data fetched.")
        return None
    except Exception as exc:
        print(f"{title}\nError {type(exc).__name__}: {exc}; fetched at: {fetched_at()}")
        print("The response was not replaced with an empty table.")
        return None


def fetch_panel(
    title: str,
    fetch: Callable[[], Dict[str, Any]],
    rows: Callable[[Dict[str, Any]], Iterable[Dict[str, Any]]],
    columns: Dict[str, str],
    *,
    source_date: Callable[[Dict[str, Any]], Any],
    status: Callable[[Dict[str, Any]], Any],
    message: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
) -> Any:
    payload = fetch_payload(title, fetch)
    if payload is None:
        return None
    return show_panel(
        title,
        payload,
        rows(payload),
        columns,
        source_date=source_date(payload),
        status=status(payload),
        message=message(payload) if message else None,
    )


def selected(row: Dict[str, Any], names: Iterable[str]) -> Dict[str, Any]:
    return {name: row.get(name) for name in names}


def status_with(status: Any, **extra: Any) -> str:
    """Keep freshness and fallback states beside the availability status."""
    parts = [str(status or "not supplied")]
    parts += [f"{name.replace('_', ' ')}: {value}" for name, value in extra.items() if value not in (None, "")]
    return "; ".join(parts)
