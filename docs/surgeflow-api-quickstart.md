# SurgeFlow API quickstart

Use this guide with the [authoritative OpenAPI document](https://surgeflows.capital/api/public/openapi.json).
SurgeFlow supports the United States (`us`), China (`cn`), Japan (`jp`), and Hong Kong (`hk`).

## 1. Read a public snapshot

Public snapshots need no API key. Request JSON or CSV with a plain GET request.

```bash
curl "https://surgeflows.capital/api/public/snapshots/data-freshness.json"
curl "https://surgeflows.capital/api/public/snapshots/momentum-hotlist.csv?market=us"
```

The public snapshot paths are:

```text
GET /api/public/snapshots/momentum-hotlist.json?market={market}
GET /api/public/snapshots/momentum-hotlist.csv?market={market}
GET /api/public/snapshots/macro-indicators.json
GET /api/public/snapshots/macro-indicators.csv
GET /api/public/snapshots/news-sentiment.json?days=30
GET /api/public/snapshots/news-sentiment.csv?days=30
GET /api/public/snapshots/factor-overview.json?market={market}
GET /api/public/snapshots/factor-overview.csv?market={market}
GET /api/public/snapshots/data-freshness.json
GET /api/public/snapshots/data-freshness.csv
```

Use `us`, `cn`, `jp`, or `hk` for `{market}`.
The `days` parameter accepts an integer from 1 through 365.

The [public manifest](https://surgeflows.capital/api/public/manifest.json) lists snapshot URLs, coverage, and caveats.
The `generated_at` field records package creation time. It does not replace an observation date.

## 2. Inspect the response

JSON snapshots include `ok`, `snapshot`, `market`, `generated_at`, `row_count`, `source`, and `data` fields.
Check `ok` and the fields inside `data` before using a result.

The momentum Hotlist sample includes `data.rows`, `data.total_count`, and `data.truncated`.
Rows are ordered by `selection_rank`. The public sample can contain at most three rows.
The full board requires the signed-in site or member API.

Data freshness includes `data.status`, `data.timezone`, and `data.rows`.
Freshness rows include `market`, `latest_date`, `expected_latest`, `trading_days_stale`, and `status`.

CSV snapshots flatten nested fields and can encode complex cells.
Check the header row instead of assuming that JSON and CSV have identical structures.

## 3. Run the examples

Run the cURL example:

```bash
bash examples/curl/public.sh
```

Run the Python example with `requests` installed:

```bash
python examples/python/public.py
```

The Python example reads a public snapshot and one market Hotlist.
It also loads public CSV into `pandas` when that optional package is installed.

Run the JavaScript example with Node 18 or later:

```bash
node examples/javascript/public.mjs
```

Use this formula in a Google Sheets cell for a public CSV snapshot:

```text
=IMPORTDATA("https://surgeflows.capital/api/public/snapshots/momentum-hotlist.csv?market=us")
```

The formula needs no API key. Google Sheets controls the refresh schedule.

## 4. Use a member endpoint

1. Join or sign in to SurgeFlow.
2. Open [your account](https://surgeflows.capital/account).
3. Create a member API key.
4. Copy the key when it appears and store it privately.

The member beta allows 2,000 requests per day and 180 requests per minute for each key.
Do not commit a key or save it in an example file.

This starter kit uses these member endpoints:

```text
GET /api/v1/me
GET /api/v1/markets/{market}/hotlist
```

Set `SURGEFLOW_API_KEY` in your shell and run the member cURL example:

```bash
export SURGEFLOW_API_KEY="sf_live_REPLACE_WITH_YOUR_KEY"
bash examples/curl/member.sh
```

The example sends this header:

```text
Authorization: Bearer sf_live_REPLACE_WITH_YOUR_KEY
```

See the [member API catalogue](https://surgeflows.capital/api/v1/catalog) for the authoritative member contract.
Do not use the placeholder as a real key.

## 5. Install a client or app

- Install the Python client with `python -m pip install ./python`.
- Install the JavaScript client with `npm install ./javascript`.
- Install the [Google Sheets source](../apps/google-sheets-add-on/README.md) as a bound script.
- Sideload the [Excel manifest](../apps/excel-add-in/README.md) in Excel on the web.
- Load the [Chrome extension](../apps/chrome-extension/README.md) as an unpacked extension.

The app products are not yet in their stores.
They show only SurgeFlow tickers and ranks, data freshness, and official open-licence macro statistics with credits. These official statistics can include economies beyond the four equity markets (for example the United Kingdom, Taiwan, and World Bank country series), each with its publisher credit.
They show no prices, returns, or company names.

## 6. Run the member notebooks

Install the local package with notebook dependencies:

```bash
python -m pip install './python[notebooks]'
jupyter notebook notebooks/00_quickstart.ipynb
```

The notebooks read `SURGEFLOW_API_KEY`, with a hidden `getpass` prompt as fallback.
They use the catalogue `base_url`; set `SURGEFLOW_BASE_URL` to override it.
They send the key only in the `Authorization: Bearer` header and never print it.
Set `SURGEFLOW_FIXTURES=1` to run every notebook with synthetic responses and no network request.
Fixture mode reads `python/tests/fixtures` from a repository checkout; for an installed package, set `SURGEFLOW_FIXTURE_DIR` to that folder.

The quickstart shows plan and usage without showing the key. Notebooks 01 through 09 cover the nine offerings.
The offering 01, 02, 04, 05, 06, and 08 routes are member research routes (beta). They are not yet listed in `/api/v1/catalog`.
Technical cohorts and Layoffs are not reachable by member key yet. Their notebooks show no member response.
The Hotlist notebook supports `us`, `cn`, `jp`, and `hk`. The monitor defaults to `us` during fixed exchange hours.

Each panel refreshes on a schedule; each panel shows its source date. Only a session-live response describes the current session.
The free beta permits 2,000 requests per day and 180 per minute for each key. The monitor defaults to 1,500 per day.
Its full weekday projection is 1,226 scheduled requests plus one startup account check.

Free access grants no redistribution rights. **Do not republish the data you fetch.**

## Data boundaries

Read the source date, market, currency, and measurement window in every response.
Data can be delayed, stale, historical, or unavailable.
Coverage depth differs by market and source.

Free access does not grant redistribution rights. Source materials can have separate provider terms.
SurgeFlow provides research data only, not investment advice.

Email [support@surgeflows.capital](mailto:support@surgeflows.capital) for help.
