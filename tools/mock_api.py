"""Offline stand-in for the SurgeFlow API, used by tools/run_notebooks.py --mock.

Patches requests.Session.request so notebook code runs unchanged while the
responses come from tests/fixtures/*.json. Fixture lookup for a request path:

    /api/v1/markets/{m}/ml/clusters  -> ml_clusters_{m}.json, else ml_clusters.json
    /api/v1/ai/grade-book            -> ai_grade_book.json
    /api/v1/notes/daily              -> notes_daily.json

When only the market-agnostic fixture exists, every "market" field equal to
"us" is rewritten to the requested market. A request for page > 1 returns
the page fixture ({name}_{m}.page{N}.json) if present, otherwise the base
fixture with its top-level "rows" emptied and "page" echoed (as the live API
does past the end), so paging loops terminate.

Endpoints without a market path segment that take ?market= (macro/calendar,
notes/daily) are served from {name}_{market}.json when that file exists,
otherwise from {name}.json unchanged. Other query parameters (limit, sort,
ticker, sentiment, days, checkpoint, page_size) are ignored.

Set SURGEFLOW_FIXTURES_DIR to serve another directory, e.g. the live
snapshots that tools/probe_endpoints.py saves in tests/fixtures/live/.
"""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

FIXTURES = Path(os.getenv("SURGEFLOW_FIXTURES_DIR") or Path(__file__).resolve().parents[1] / "tests" / "fixtures")
CALLS: list[str] = []


def _slug(text: str) -> str:
    return re.sub(r"[/\-]+", "_", text.strip("/"))


def _retarget(obj, market: str):
    if isinstance(obj, dict):
        return {k: (market if k == "market" and v == "us" else _retarget(v, market)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_retarget(v, market) for v in obj]
    return obj


def resolve(path: str, params: dict) -> tuple[int, dict]:
    rel = path.split("/api/v1/", 1)[-1] if "/api/v1/" in path else _slug(path)
    match = re.match(r"markets/([a-z]{2})/(.+)$", rel)
    market = match.group(1) if match else None
    name = _slug(match.group(2) if match else rel)
    if market and market not in ("us", "cn", "jp", "hk"):
        return 404, {"ok": False, "error": {"code": "UNSUPPORTED_MARKET", "message": f"market {market} not supported"}}

    page = int(params.get("page", 1) or 1)
    query_market = str(params.get("market") or "").lower()
    candidates = []
    if market:
        if page > 1:
            candidates.append(f"{name}_{market}.page{page}.json")
        candidates.append(f"{name}_{market}.json")
    elif query_market in ("us", "cn", "jp", "hk"):
        candidates.append(f"{name}_{query_market}.json")
    candidates.append(f"{name}.json")
    for candidate in candidates:
        file = FIXTURES / candidate
        if file.exists():
            payload = json.loads(file.read_text())
            if market and not candidate.startswith(f"{name}_{market}"):
                payload = _retarget(payload, market)
            if page > 1 and ".page" not in candidate:
                payload = copy.deepcopy(payload)
                if "page" in payload:
                    payload["page"] = page
                if isinstance(payload.get("rows"), list):
                    payload["rows"] = []
                if isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("rows"), list):
                    payload["data"]["rows"] = []
            return 200, payload
    return 404, {"ok": False, "error": {"code": "NOT_FOUND", "message": f"no fixture for {path}"}}


class _Response(requests.Response):
    def __init__(self, status: int, payload: dict, url: str):
        super().__init__()
        self.status_code = status
        self._content = json.dumps(payload).encode()
        self.headers["Content-Type"] = "application/json"
        self.url = url
        self.encoding = "utf-8"


def install() -> None:
    def fake_request(self, method, url, params=None, **kwargs):
        parsed = urlparse(url)
        merged = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        merged.update({k: v for k, v in (params or {}).items()})
        CALLS.append(f"{method} {parsed.path}")
        status, payload = resolve(parsed.path, merged)
        return _Response(status, payload, url)

    requests.Session.request = fake_request
