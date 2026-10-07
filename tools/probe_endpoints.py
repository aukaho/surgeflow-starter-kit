"""Call all 15 authenticated endpoints and compare live shapes with the fixtures.

    SURGEFLOW_API_KEY=sf_live_... python tools/probe_endpoints.py

Saves each live response to tests/fixtures/live/ (git-ignored, never
committed) and prints, per endpoint, the key paths that exist live but not
in the mock fixture (+) and the reverse (-). Use it to correct fixtures and
notebook column names after the API changes. Uses about 40 requests.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
LIVE = FIXTURES / "live"
BASE_URL = os.getenv("SURGEFLOW_BASE_URL", "https://stock-api-c4qdowjxva-uc.a.run.app")
MARKETS = ("us", "cn", "jp", "hk")

GLOBAL = {
    "me": "/api/v1/me",
    "summary": "/api/v1/summary",
    "ai_ratings": "/api/v1/ai/ratings",
    "ai_grade_book": "/api/v1/ai/grade-book",
    "notes_daily": "/api/v1/notes/daily",
    "macro_calendar": "/api/v1/macro/calendar",
    "bond_etfs": "/api/v1/bond/etfs",
}
PER_MARKET = {
    "screen": "screen",
    "realtime": "realtime",
    "hotlist": "hotlist",
    "ml_clusters": "ml/clusters",
    "whales": "whales",
    "sector": "sector",
    "news": "news",
    "factor_portfolios": "factor-portfolios",
}


def paths(obj, prefix: str = "") -> set[str]:
    """Key paths with list items collapsed to [] (first 5 items sampled)."""
    out = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{prefix}.{key}" if prefix else key
            out.add(here)
            out |= paths(value, here)
    elif isinstance(obj, list):
        for item in obj[:5]:
            out |= paths(item, f"{prefix}[]")
    return out


def main() -> int:
    key = os.getenv("SURGEFLOW_API_KEY", "").strip()
    if not key:
        print("Set SURGEFLOW_API_KEY first.")
        return 2
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {key}"
    LIVE.mkdir(parents=True, exist_ok=True)

    jobs = [(name, path) for name, path in GLOBAL.items()]
    for name, suffix in PER_MARKET.items():
        jobs += [(f"{name}_{m}", f"/api/v1/markets/{m}/{suffix}") for m in MARKETS]
    failures = 0
    for name, path in jobs:
        time.sleep(0.5)
        response = session.get(BASE_URL + path, timeout=60)
        try:
            payload = response.json()
        except ValueError:
            payload = {"_non_json": response.text[:500]}
        (LIVE / f"{name}.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False))
        mock_file = FIXTURES / f"{name}.json"
        if not mock_file.exists():
            mock_file = FIXTURES / f"{name.rsplit('_', 1)[0]}.json"
        mock = json.loads(mock_file.read_text()) if mock_file.exists() else {}
        live_paths, mock_paths = paths(payload), paths(mock)
        added, missing = sorted(live_paths - mock_paths), sorted(mock_paths - live_paths)
        status = "OK " if response.ok else "ERR"
        failures += not response.ok
        print(f"{status} {response.status_code} {path}  (+{len(added)} / -{len(missing)})")
        for p in added[:40]:
            print(f"      + {p}")
        for p in missing[:40]:
            print(f"      - {p}")
    print(f"\nSaved live responses to {LIVE.relative_to(ROOT)}/ (git-ignored).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
