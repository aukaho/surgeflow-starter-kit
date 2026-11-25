# SurgeFlow Starter Kit

Examples, clients, and app sources for SurgeFlow research data.

SurgeFlow covers four equity markets: the United States (`us`), China (`cn`), Japan (`jp`), and Hong Kong (`hk`).
The API provides research data only, not investment advice.

## Start without a key

Read public research snapshots as JSON or CSV. No API key is required.

```bash
curl "https://surgeflows.capital/api/public/snapshots/momentum-hotlist.json?market=us"
```

Public snapshots cover momentum Hotlist samples, macro indicators, news sentiment, factor overviews, and data freshness.
The factor overview is a **frozen baseline (data to 11 April 2026, not updated daily)**.
For current daily factor data, use keyless `GET https://surgeflows.capital/api/factor-reference/latest`.
Data can be delayed or historical. Free access does not grant redistribution rights.

Use these resources:

- [Public manifest](https://surgeflows.capital/api/public/manifest.json)
- [OpenAPI 3.1 document](https://surgeflows.capital/api/public/openapi.json), the authoritative public contract
- [API documentation](https://surgeflows.capital/membership/api)
- [Postman collection](https://surgeflows.capital/data/surgeflow.postman_collection.json)
- [Member API catalogue](https://surgeflows.capital/api/v1/catalog)
- [llms.txt](https://surgeflows.capital/llms.txt)
- [Quickstart](docs/surgeflow-api-quickstart.md)

## Create a member API key

1. Join or sign in to SurgeFlow.
2. Open the [account page](https://surgeflows.capital/account).
3. Create a key and copy it when it appears.
4. Store the key privately because SurgeFlow cannot display the full key again.

The member beta allows 2,000 requests per day and 180 requests per minute for each key.
Member endpoints provide read-only market research data.

Send the key as a bearer token:

```bash
curl \
  -H "Authorization: Bearer sf_live_REPLACE_WITH_YOUR_KEY" \
  "https://surgeflows.capital/api/v1/markets/us/hotlist"
```

Use `us`, `cn`, `jp`, or `hk` in member market paths.
The [member API catalogue](https://surgeflows.capital/api/v1/catalog) is authoritative for member endpoints and plans.

## Install and run

### Examples

The [examples](examples/) include cURL, Python, JavaScript, and Google Sheets versions.

```bash
bash examples/curl/public.sh
python examples/python/public.py
node examples/javascript/public.mjs
```

The Python example requires `requests`. It uses `pandas` when that optional package is installed.
The JavaScript example requires Node 18 or later.

### Python client

Install the local `surgeflow` package:

```bash
python -m pip install ./python
```

See the [Python client guide](python/README.md). The package is not yet on PyPI.

### Member notebooks

Install the optional notebook dependencies and open the quickstart:

```bash
python -m pip install './python[notebooks]'
jupyter notebook notebooks/00_quickstart.ipynb
```

The eleven notebooks cover the quickstart, nine member offerings, and the live monitor.
Notebook 03 shows cohort analytics as research measurements, with explicit status text when a metric is not available.
The offering 01 through 06, 08 and 09 routes are member research routes (beta). The offering 07 routes are the catalogued /api/v1 market hotlist and realtime routes.
The routes are listed in /api/v1/catalog member_research_endpoints.
The 03 and 09 routes were not live when this version was built.
The notebooks read `SURGEFLOW_API_KEY`, with a hidden `getpass` prompt as fallback. They never print the key or put it in a URL.
The catalogue supplies `base_url`; `SURGEFLOW_BASE_URL` overrides it. Set `SURGEFLOW_FIXTURES=1` to use synthetic responses without network requests.
Fixture mode reads `python/tests/fixtures` from a repository checkout; for an installed package, set `SURGEFLOW_FIXTURE_DIR` to that folder.

Each panel refreshes on a schedule; each panel shows its source date. Only a response marked as session-live describes the current session.
The monitor uses fixed weekday exchange hours and does not handle holidays. Changed rows receive a highlight. A 429 response's `Retry-After` counts from the response and pauses every panel, because the limit applies to the whole key.
Cohort and layoff panels refresh at most once every six hours. **Feed unavailable** is an availability state, not an error.
US cohorts are enabled by default. Set `SURGEFLOW_COHORT_MARKETS` to a comma-separated list to enable other cohort markets.

The member beta permits 2,000 requests per day and 180 per minute for each key, shared by every process using it.
The monitor budget defaults to 1,500 per day for each running monitor. A restart starts it from zero and spends about 22 requests on the first full refresh.
In notebook 10, the budget is capped once at startup from the key's remaining daily count reported by `/api/v1/me`.
Requests made later by other processes are not tracked. This table gives the maximum projected requests on a full active weekday:

| Offering | Requests per fetch | Cadence | Requests per day |
|---|---:|---:|---:|
| 01 Macro model votes | 5 routes | 30 min | 240 |
| 02 Bull & bear sentiment picks | 2 routes | 30 min | 96 |
| 03 Technical cohorts, US | 1 route | 6 h | 4 |
| 04 Pure factor portfolios | 3 routes | 6 h | 12 |
| 05 Fundamental rankings | 2 routes | 6 h | 8 |
| 06 Watchlists | 1 route | 5 min | 288 |
| 06 Screens, alerts, and portfolios | 3 routes | 30 min | 144 |
| 07 Hotlist and session board, US | 2 routes | 120 s during 6.5 session hours | 390 |
| 08 Daily actionable insights | 1 route | 30 min | 48 |
| 09 Layoffs | 1 route | 6 h | 4 |
| **Scheduled total** | | | **1,234** |
| One startup account check | 1 route | Once | 1 |
| **Projected total** | | | **1,235** |

Each additional enabled cohort market adds four requests per day.
All four cohort markets give 1,246 scheduled requests plus one account check, for 1,247 total requests.
Each refresh is delayed by 0 to 10% so monitors started together do not poll in lockstep. The delay is never negative, so no panel refreshes sooner than its cadence and a day does not exceed these totals.

Free access grants no redistribution rights. **Do not republish the data you fetch.**

### JavaScript client

Install the local `surgeflow` package:

```bash
npm install ./javascript
```

See the [JavaScript client guide](javascript/README.md). The package is not yet on npm.

### Google Sheets add-on

Install the source as a bound script by following [these steps](apps/google-sheets-add-on/README.md).
A public CSV snapshot also works with `IMPORTDATA` and needs no add-on.

### Excel add-in

Sideload the hosted manifest by following [these steps](apps/excel-add-in/README.md).
The site serves the panel files.

### Chrome extension

Load the unpacked extension by following [these steps](apps/chrome-extension/README.md).

These three app products are not yet in their stores.

## Data dates and limits

Check the source date, market, currency, and measurement window in each response.
Historical, factor, and valuation datasets follow their disclosed source cadence.
A current-session board is not a live-tick feed across every market.

The app sources show only SurgeFlow tickers and ranks, data freshness, and official open-licence macro statistics with credits. These official statistics can include economies beyond the four equity markets (for example the United Kingdom, Taiwan, and World Bank country series), each with its publisher credit.
They show no prices, returns, or company names.

## Support

Email [support@surgeflows.capital](mailto:support@surgeflows.capital) or open an issue.

## Licence and disclaimer

Code is available under the [MIT licence](LICENSE).

SurgeFlow is research software. This starter kit and API provide research data only.
They do not provide investment advice, broker-dealer services, order routing, portfolio management, or securities recommendations.
