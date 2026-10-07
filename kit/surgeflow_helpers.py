# SurgeFlow shared helpers - identical in every notebook of the starter kit.
# Source of truth: kit/surgeflow_helpers.py (tools/build_notebooks.py copies it in).
from __future__ import annotations

import getpass
import os
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import requests
from IPython.display import Markdown, display

BASE_URL = os.getenv("SURGEFLOW_BASE_URL", "https://stock-api-c4qdowjxva-uc.a.run.app")
MARKETS = ("us", "cn", "jp", "hk")
MARKET_NAMES = {"us": "United States", "cn": "China", "jp": "Japan", "hk": "Hong Kong"}

# Where each endpoint keeps its main records inside the JSON response.
# Mirrors "response_shapes" in GET /api/v1/catalog.
RESPONSE_SHAPES = {
    "screen": ("rows",),
    "realtime": ("data", "rows"),
    "hotlist": ("data", "rows"),
    "ml_clusters": ("data", "clusters"),
    "ml_anomalies": ("data", "anomaly_watch"),
    "whales": ("data", "signal_board", "signals"),
    "sector": ("data", "rows"),
    "news": ("data", "articles"),
    "factor_portfolios": ("data", "data", "factors"),
    "notes": ("data", "notes"),
    "macro_calendar": ("data", "data", "events"),
    "bond_etfs": ("data", "data", "etfs"),
}


class SurgeFlowError(RuntimeError):
    """Readable API error: carries the HTTP status and SurgeFlow error code."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"HTTP {status} {code}: {message}")
        self.status, self.code = status, code


def _load_api_key() -> str:
    """Environment variable -> Colab secret -> hidden prompt. The key is never printed."""
    key = os.getenv("SURGEFLOW_API_KEY", "").strip()
    if not key:
        try:
            from google.colab import userdata  # only exists inside Google Colab

            key = (userdata.get("SURGEFLOW_API_KEY") or "").strip()
        except Exception:
            key = ""
    if not key:
        key = getpass.getpass("Paste your SurgeFlow API key (sf_live_...): ").strip()
    if not key.startswith("sf_"):
        raise ValueError("Expected a SurgeFlow key that starts with sf_live_.")
    return key


_session = requests.Session()
_session.headers.update({"Authorization": f"Bearer {_load_api_key()}", "Accept": "application/json"})
_calls = {"count": 0, "last": 0.0}


def sf_get(path: str, retries: int = 3, **params) -> dict:
    """GET a SurgeFlow endpoint and return the JSON payload.

    Spaces calls ~0.4 s apart (free limit: 180/min, 2,000/day) and retries
    429 / 5xx responses, honouring the Retry-After header.
    """
    params = {k: v for k, v in params.items() if v is not None}
    for attempt in range(retries + 1):
        wait = 0.4 - (time.monotonic() - _calls["last"])
        if wait > 0:
            time.sleep(wait)
        _calls["last"] = time.monotonic()
        _calls["count"] += 1
        response = _session.get(f"{BASE_URL}{path}", params=params, timeout=60)
        if response.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(float(response.headers.get("Retry-After") or 2 ** (attempt + 1)))
            continue
        try:
            payload = response.json()
        except ValueError:
            raise SurgeFlowError(response.status_code, "NON_JSON", response.text[:200]) from None
        # /health answers 200 with "ok": false when degraded - that is data, not an error.
        # Some endpoints wrap an upstream failure inside a 200: {"ok": true, "data": {"ok": false, "error": ...}}.
        inner = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        failed = payload if "error" in payload else inner if inner.get("ok") is False and "error" in inner else None
        if not response.ok or (failed is not None and failed.get("ok") is False):
            error = (failed or payload).get("error") or {}
            raise SurgeFlowError(
                response.status_code,
                error.get("code", "HTTP_ERROR"),
                error.get("message", str(payload)[:200]),
            )
        return payload
    raise SurgeFlowError(response.status_code, "RETRIES_EXHAUSTED", path)


def sf_try(path: str, **params) -> dict | None:
    """Like sf_get, but a temporarily unavailable endpoint prints a note and returns None."""
    try:
        return sf_get(path, **params)
    except SurgeFlowError as exc:
        if exc.status == 410:  # retired endpoint: retrying will not help
            display(Markdown(f"**{path} has been retired** ({exc}). Skipping this section."))
        else:
            display(Markdown(f"**{path} is unavailable right now** ({exc}). Skipping this section - try again later."))
        return None


def dig(obj, *keys, default=None):
    """Walk nested dicts safely: dig(payload, "data", "rows") -> payload["data"]["rows"] or default."""
    for key in keys:
        if not isinstance(obj, dict) or key not in obj:
            return default
        obj = obj[key]
    return obj


def records(payload: dict, shape: str) -> list:
    """Return the main record list for an endpoint, using RESPONSE_SHAPES."""
    found = dig(payload, *RESPONSE_SHAPES[shape], default=[])
    return found if isinstance(found, list) else []


def to_frame(payload: dict, shape: str, sep: str = ".") -> pd.DataFrame:
    """Records -> DataFrame. Nested objects become dotted columns (json_normalize)."""
    rows = records(payload, shape)
    return pd.json_normalize(rows, sep=sep) if rows else pd.DataFrame()


def freshness(payload: dict) -> dict:
    """Pick out the as-of / status / quality fields an endpoint discloses (if any)."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    keys = ("market", "as_of_utc", "as_of_local", "as_of_date", "market_status",
            "data_quality", "stale_reason", "count")
    return {k: (payload.get(k) if k in payload else data.get(k)) for k in keys
            if k in payload or k in data}


def show_freshness(payload: dict, label: str = "") -> None:
    """Print one line of freshness metadata - always check it before reading the numbers."""
    meta = freshness(payload)
    text = " | ".join(f"**{k}**: {v}" for k, v in meta.items()) or "no freshness fields disclosed"
    display(Markdown(f"{label} {text}".strip()))


def api_calls_used() -> int:
    """Requests made from this notebook session (counts toward 2,000/day)."""
    return _calls["count"]


# ---- Chart theme --------------------------------------------------------------
# Categorical slots are assigned in fixed order and follow the entity, never its rank.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
MARKET_COLORS = dict(zip(MARKETS, SERIES))
SIDE_COLORS = {"LONG": "#2a78d6", "SHORT": "#e34948", "HOLD": "#898781"}
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DIVERGING = [[0.0, "#b3261e"], [0.25, "#e34948"], [0.5, "#f0efec"], [0.75, "#3987e5"], [1.0, "#184f95"]]
INK, INK_2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"

pio.templates["surgeflow"] = go.layout.Template(
    layout=dict(
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", size=13, color=INK_2),
        title=dict(font=dict(size=17, color=INK), x=0, xanchor="left"),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        colorway=SERIES,
        colorscale=dict(sequential=[[i / 6, c] for i, c in enumerate(SEQUENTIAL)], diverging=DIVERGING),
        xaxis=dict(gridcolor=GRID, linecolor=AXIS, zerolinecolor=AXIS, tickcolor=AXIS, ticks="outside"),
        yaxis=dict(gridcolor=GRID, linecolor=AXIS, zerolinecolor=AXIS, tickcolor=AXIS, ticks="outside"),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=INK_2)),
        hoverlabel=dict(bgcolor="white", font=dict(color=INK)),
        margin=dict(l=60, r=30, t=70, b=50),
        bargap=0.25,
    ),
    data=dict(
        scatter=[go.Scatter(marker=dict(size=9, line=dict(width=1, color=SURFACE)), line=dict(width=2))],
        bar=[go.Bar(marker=dict(line=dict(width=1, color=SURFACE)))],
    ),
)
pio.templates.default = "plotly_white+surgeflow"
pd.set_option("display.max_columns", 60)
pd.set_option("display.width", 180)

print(f"Connected to {BASE_URL} | markets: {', '.join(MARKETS)} | key loaded (hidden).")
