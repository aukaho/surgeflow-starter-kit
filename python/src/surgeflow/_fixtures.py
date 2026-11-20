import json
import os
from pathlib import Path
from typing import Dict, Optional, Union

from ._errors import SurgeFlowResponseError

Params = Dict[str, Union[str, int, bool]]

_EXACT = {
    "/api/v1/catalog": "catalog.json",
    "/api/v1/me": "me.json",
    "/api/macro/model-votes": "macro-model-votes.json",
    "/api/macro/index-votes": "macro-index-votes.json",
    "/api/macro/cycle-composites": "macro-cycle-composites.json",
    "/api/macro/recession-probability": "macro-recession-probability.json",
    "/api/fund/hmm-regime": "fund-hmm-regime.json",
    "/api/us/weekly-pure-books": "weekly-pure-books.json",
    "/api/us/historical-pure-books": "historical-pure-books.json",
    "/api/us/three-model/portfolios": "three-model-portfolios-us.json",
    "/api/us/fundamental-picks": "fundamental-picks.json",
    "/api/us/fundamental-peers": "fundamental-peers.json",
    "/api/watchlists": "watchlists.json",
    "/api/screens": "screens.json",
    "/api/alerts": "alerts.json",
    "/api/portfolio": "portfolio.json",
    "/api/us/daily-insights": "daily-insights.json",
}
_DYNAMIC = {
    "/api/{market}/stock-scores": "stock-scores-{market}.json",
    "/api/{market}/sentiment-whale-picks": "sentiment-whale-picks-{market}.json",
    "/api/{market}/three-model/portfolios": "three-model-portfolios-{market}.json",
    "/api/v1/markets/{market}/hotlist": "member-hotlist-{market}.json",
    "/api/v1/markets/{market}/realtime": "member-realtime-{market}.json",
}


def fixture_enabled() -> bool:
    return os.environ.get("SURGEFLOW_FIXTURES") == "1"


def fixture_directory() -> Path:
    configured = os.environ.get("SURGEFLOW_FIXTURE_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def fixture_name(path: str) -> Optional[str]:
    if path in _EXACT:
        return _EXACT[path]
    for market in ("us", "cn", "jp", "hk"):
        for template, name in _DYNAMIC.items():
            if path == template.format(market=market):
                return name.format(market=market)
    return None


def read_fixture(path: str, params: Params, response_format: str):
    if path == "/api/public/snapshots/factor-overview.json":
        market = str(params.get("market", ""))
        if market not in ("us", "cn", "jp", "hk"):
            raise SurgeFlowResponseError("A fixture requires a valid market")
        name = f"factor-overview-{market}.json"
    else:
        name = fixture_name(path)
    if name is None:
        raise SurgeFlowResponseError(f"No fixture is registered for {path}")
    fixture_path = fixture_directory() / name
    if response_format == "csv":
        fixture_path = fixture_path.with_suffix(".csv")
    if not fixture_path.is_file():
        raise SurgeFlowResponseError(f"Fixture is missing: {fixture_path.name}")
    if response_format == "csv":
        return fixture_path.read_text(encoding="utf-8")
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SurgeFlowResponseError("Fixture contains invalid JSON") from exc
    if not isinstance(payload, dict):
        raise SurgeFlowResponseError("Fixture must contain a JSON object")
    return payload
