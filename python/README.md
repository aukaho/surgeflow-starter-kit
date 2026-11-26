# surgeflow Python client

`surgeflow` 0.4.1 reads SurgeFlow public snapshots and member research endpoints.
It requires Python 3.9 or later and uses `requests` as its only core dependency.
The client and member API remain in beta.

The package is not yet on PyPI. Install it from this local folder:

```bash
python -m pip install ./python
```

## Public snapshots

```python
from surgeflow import SurgeFlow

client = SurgeFlow(timeout=30)
freshness = client.data_freshness()
hotlist = client.momentum_hotlist("us")
macro = client.macro_indicators()
news = client.news_sentiment(days=30)
factors = client.factor_overview("us")
hotlist_csv = client.momentum_hotlist("us", response_format="csv")
```

Public methods return decoded JSON objects by default. Use `response_format="csv"` to receive CSV text.
Market arguments accept `us`, `cn`, `jp`, or `hk`. The `days` argument accepts 1 through 365.
The factor overview is a **frozen baseline (data to 11 April 2026, not updated daily)**.
For current daily factor data, use keyless `GET https://surgeflows.capital/api/factor-reference/latest`.

Use `public_snapshot(snapshot_id, market=None, days=None, response_format="json")` for the generic snapshot method.
The [public OpenAPI document](https://surgeflows.capital/api/public/openapi.json) defines the live public contract.

## Member methods

Create a key on the [account page](https://surgeflows.capital/account).
Read the catalogue to get the external `base_url`, or set `SURGEFLOW_BASE_URL` to override it.
Pass your own key directly to each member method. The client sends it only in the bearer header.

```python
import os
from surgeflow import SurgeFlow

catalogue = SurgeFlow().catalog()
base_url = os.environ.get("SURGEFLOW_BASE_URL", catalogue["base_url"])
client = SurgeFlow(base_url=base_url)
key = "sf_live_REPLACE_WITH_YOUR_KEY"
plan = client.member_me(key)
hotlist = client.member_hotlist("us", key)
insights = client.member_daily_insights(key)
cohorts = client.member_technical_cohorts("us", key)
layoffs = client.member_layoffs(key)
```

The member methods map these routes. The offering 01 through 06, 08 and 09 routes are member research routes (beta). The offering 07 routes are the catalogued /api/v1 market hotlist and realtime routes.
The routes are listed in /api/v1/catalog member_research_endpoints.
The 03 and 09 routes were not live when this version was built.

| Offering | Method | Route |
|---|---|---|
| Account | `member_me` | `/api/v1/me` |
| 01 | `member_macro_model_votes` | `/api/macro/model-votes` |
| 01 | `member_macro_index_votes` | `/api/macro/index-votes` |
| 01 | `member_macro_cycle_composites` | `/api/macro/cycle-composites` |
| 01 | `member_macro_recession_probability` | `/api/macro/recession-probability` |
| 01 | `member_fund_hmm_regime` | `/api/fund/hmm-regime` |
| 02 | `member_sentiment_scores` | `/api/{market}/stock-scores` |
| 02 | `member_sentiment_whale_picks` | `/api/{market}/sentiment-whale-picks` |
| 03 | `member_technical_cohorts` | `/api/{market}/technical-strategies/cohorts` |
| 04 | `member_weekly_pure_books` | `/api/us/weekly-pure-books` |
| 04 | `member_historical_pure_books` | `/api/us/historical-pure-books` |
| 04 | `member_three_model_portfolios` | `/api/{market}/three-model/portfolios` |
| 05 | `member_fundamental_picks` | `/api/us/fundamental-picks` |
| 05 | `member_fundamental_peers` | `/api/us/fundamental-peers` |
| 06 | `member_watchlists` | `/api/watchlists` |
| 06 | `member_screens` | `/api/screens` |
| 06 | `member_alerts` | `/api/alerts` |
| 06 | `member_portfolio` | `/api/portfolio` |
| 07 | `member_hotlist` | `/api/v1/markets/{market}/hotlist` |
| 07 | `member_realtime` | `/api/v1/markets/{market}/realtime` |
| 08 | `member_daily_insights` | `/api/us/daily-insights` |
| 09 | `member_layoffs` | `/api/us/layoffs/latest` |

The sentiment score method defaults to `basis="news_led"`.
The weekly and historical book handlers accept no query parameters. The three-model method exposes its `holdings` limit.
The Managerial Control methods use GET only. The notebooks never change member data.
`member_technical_cohorts(market, api_key)` accepts `us`, `cn`, `jp`, or `hk`.
The 03 and 09 routes require the `screen` scope. Their HTTP 503 feed states use `SurgeFlowFeedUnavailable`.

The free plan grants all scopes used by these routes. It permits 2,000 requests per day and 180 per minute for each key.
The [member API catalogue](https://surgeflows.capital/api/v1/catalog) defines the catalogued member contract, including `/api/v1/me` and the market hotlist and realtime routes.
The catalogue exposes `member_research_endpoints` for the beta routes.

## Notebooks and monitor

Install the optional dependencies and open the quickstart:

```bash
python -m pip install './python[notebooks]'
jupyter notebook notebooks/00_quickstart.ipynb
```

The `notebooks` extra adds Jupyter Notebook, pandas, IPython, ipywidgets, and jinja2 (for monitor row highlights; without it the monitor marks changed rows in text). The core client still needs only `requests`.
The notebooks read `SURGEFLOW_API_KEY`, with hidden `getpass` entry as fallback. They never print the key.
Set `SURGEFLOW_FIXTURES=1` to read the local synthetic fixtures without network requests.
Fixture mode reads `python/tests/fixtures` from a repository checkout; for an installed package, set `SURGEFLOW_FIXTURE_DIR` to that folder.

`surgeflow.monitor` provides panels, a scheduler, fixed session gates, change detection, and a request counter.
The default budget is 1,500 requests per day for each running monitor. A restart starts it from zero and spends about 22 requests on the first full refresh.
The key's 2,000 per day is shared by every process using it. Notebook 10 caps the budget once from the remaining count reported by `/api/v1/me`.
Requests made later by other processes are not tracked. The full weekday projection is 1,234 scheduled requests plus one account check.
Hotlist requests run every 120 seconds during the fixed US session. Watchlists run every five minutes.
Sentiment, insights, and macro votes run every 30 minutes. Fundamentals and factor books run every six hours.
Cohorts and layoffs run every six hours. US cohorts are enabled by default.
Set `SURGEFLOW_COHORT_MARKETS` to a comma-separated list to enable other cohort markets. Each added market costs four requests per day.
Screens, alerts, and your portfolios also run every 30 minutes.

Each panel refreshes on a schedule; each panel shows its source date. Only a session-live response describes the current session.
Fixed exchange hours do not include holidays. The scheduler honours 429 `Retry-After` values.
**Feed unavailable** is an availability state, not an error.

## Errors and timeouts

The default timeout is 30 seconds. Set `timeout` in seconds when constructing the client.

- `SurgeFlowTimeoutError` identifies a timeout.
- `SurgeFlowConnectionError` identifies a transport failure.
- `SurgeFlowApiError` identifies a non-success HTTP status and includes `status_code`, `payload`, and `retry_after`.
- `SurgeFlowFeedUnavailable` identifies either documented HTTP 503 feed state with the text `Feed unavailable`.
- `SurgeFlowResponseError` identifies invalid JSON or a response with `ok=false`.
- `SurgeFlowError` is the base class for these errors.

Every request uses the `surgeflow-python/0.4.1` user agent.

## Test

Install the test dependencies, then run from this folder:

```bash
python -m pip install './python[test]'
PYTHONPATH=src python -m pytest
```

Tests use synthetic fixtures and fake sessions. They make no network requests.
The notebook test uses `nbclient` to execute all eleven notebooks in fixture mode.

Research data only, not investment advice. Free access grants no redistribution rights.
**Do not republish the data you fetch.**
