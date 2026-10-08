# SurgeFlow API Beginner Quickstart

Status: free public API beta.

Best first path: create a key on the website and run one read-only request.
You do **not** need to install Python, Jupyter, VS Code, Postman, or another
developer tool.

## First successful use

1. Open `https://surgeflows.capital/membership#api-key`.
2. Enter your email and optional name.
3. Agree to the terms.
4. Click **Create key**.
5. Copy the key when it appears. It starts with `sf_live_`.
6. Use the website preview or the Colab notebook to load a current-session
   turnover table or momentum hotlist.

The full key is displayed once. Keep it private. SurgeFlow stores only its
hash and cannot show it again.

## What the key can access

The key unlocks 14 authenticated, read-only endpoints in four markets: `us`
(United States), `cn` (China), `jp` (Japan) and `hk` (Hong Kong). They cover:

- identity, plan and usage;
- the four-market summary, the market screen and the sector snapshot;
- current-session turnover boards and momentum hotlists;
- ML clusters and institutional-holdings (whale) boards;
- news, daily Notes, the macro calendar and bond ETFs;
- the weekly factor portfolios and their publication metadata (`/meta`).

The AI research committee is paused. Its endpoints, `/api/v1/ai/ratings` and
`/api/v1/ai/grade-book`, are retired and answer HTTP 410 with the code
`ENDPOINT_RETIRED`.

The live catalogue is authoritative for endpoints, plans, limits and response
shapes:

```text
https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/catalog
```

## Free beta limits

- 2,000 requests per day per key
- 180 requests per minute per key
- Read-only market research data

## Recommended paths

### Path A: website preview

Create a key at `https://surgeflows.capital/membership#api-key`, then use the
preview to confirm that the key works and to look at the response shape.

### Path B: Google Colab

1. Open the 60-second quick start in Colab:
   `https://colab.research.google.com/github/aukaho/surgeflow-starter-kit/blob/main/notebooks/surgeflow-realtime-hotlist-60s.ipynb`
2. Optional: add a Colab secret named `SURGEFLOW_API_KEY` (key icon in the
   left sidebar) and switch on notebook access.
3. Run the cells from top to bottom. Paste your `sf_live_` key if you are
   asked for it.
4. Choose any of the four supported markets.

Then work through the notebook series, `00-setup-and-account` to
`05-ml-lab`, listed in the [README](../README.md#notebook-series). Each
endpoint section below links to the notebook that teaches it. Colab runs in
your browser, so you do not need to install Python.

### Path C: Google Sheets

The included Apps Script wrapper refreshes current-session and hotlist tables
for `us`, `cn`, `jp` and `hk`. The authenticated API and Colab notebooks
support the same four markets. The wrapper uses the keyless `/api/addin`
endpoints, so it needs no API key.

The Google Sheets add-on has been submitted for Google authentication and
Workspace Marketplace review. It is **not yet available for public one-click
installation**. Until then, add the Apps Script source to a Google Sheets copy
of the starter workbook:
[Use it today](../apps-script/README.md#use-it-today) has the steps.

Current status:

```text
https://surgeflows.capital/membership/google-sheets
```

### Path D: developers

The rest of this guide covers each endpoint.

## Basics for every call

Base URL for scripts, notebooks and third-party apps:

```text
https://stock-api-c4qdowjxva-uc.a.run.app
```

The catalogue also lists a website proxy URL. That URL is reserved for
same-origin SurgeFlow pages and may not send CORS headers, so use the base URL
above.

Authentication:

```text
Authorization: Bearer sf_live_...
```

The catalogue also accepts `X-API-Key`, `X-SurgeFlow-API-Key` and an `apiKey`
query parameter. Use the query parameter only for quick tests, because keys in
URLs end up in logs.

Set the key once in your shell for the cURL examples:

```bash
export SURGEFLOW_API_KEY="sf_live_..."
```

The Python examples share this setup. The key comes from an environment
variable, so it never appears in your code. `get` raises `SurgeFlowError` for
every error described in the next section, including the one some endpoints
nest inside an HTTP 200 answer:

```python
import os

import requests

BASE_URL = "https://stock-api-c4qdowjxva-uc.a.run.app"
session = requests.Session()
session.headers["Authorization"] = f"Bearer {os.environ['SURGEFLOW_API_KEY']}"


class SurgeFlowError(RuntimeError):
    pass


def get(path, **params):
    response = session.get(f"{BASE_URL}{path}", params=params, timeout=60)
    try:
        payload = response.json()
    except ValueError:  # a bare "Internal Server Error" page is not JSON
        raise SurgeFlowError(f"HTTP {response.status_code}: {response.text[:100]}") from None
    data = payload.get("data")
    nested = isinstance(data, dict) and data.get("ok") is False  # error inside an HTTP 200
    if not response.ok or nested:
        error = (data if nested else payload).get("error") or {}
        raise SurgeFlowError(f"HTTP {response.status_code} {error.get('code')}: {error.get('message')}")
    return payload
```

### Errors

Errors use one envelope:

```json
{"ok": false, "error": {"code": "API_KEY_REQUIRED", "message": "Provide a SurgeFlow API key with `Authorization: Bearer sf_live_...`."}}
```

- `401 API_KEY_REQUIRED`: the key is missing or invalid.
- `4xx VALIDATION_ERROR`: a parameter is out of range, for example
  `page_size=101` on the screen (the maximum is 100). Read `error.code` and
  `error.message`; do not rely on other keys inside `error` (the one
  documented extra is `error.factors` on `INVALID_FACTOR`, below).
- `400 INVALID_FACTOR`, `400 INVALID_DATE`, `400 INVALID_MARKET`: the factor
  portfolios reject an unknown `factor` (`error.factors` lists the valid
  names), a `formation_date` that is not `YYYY-MM-DD`, or a market outside
  `us`, `cn`, `jp` and `hk`.
- `410 ENDPOINT_RETIRED`: the endpoint has been retired, so retrying will not
  help. The paused AI committee's two endpoints answer this way.
- `429`: you are over the rate limit. Wait before you retry, and honour
  `Retry-After` when it is sent.
- `503`: the factor portfolios cannot read their data right now. Treat it as
  temporarily unavailable and try again later.
- **An error inside an HTTP 200.** An endpoint whose upstream source fails can
  answer `200` with `"ok": true` at the top level and the error one level
  down: `{"ok": true, "data": {"ok": false, "error": {...}}}`. `news` does
  this while its feed is down. Always check `payload["data"].get("ok")`.
- **HTTP 500 with a plain-text body.** `summary` can answer
  `500 Internal Server Error` with no JSON envelope. Treat it as temporarily
  unavailable and try again later.
- **An empty state is not an error.** The factor portfolios answer `200` with
  `{"ok": true, "data": {"status": "empty", "reason_code": "...", "message": "..."}}`
  when there is nothing to serve, for example for a market without a
  publication. Check `payload["data"]["status"]` and show `data.message`.

### Where the records live

Most payloads wrap their content in `data`. The market screen is the legacy
exception, with its rows at the top level. The catalogue's `response_shapes`
names the main record list for each endpoint, and for the factor portfolios
also the state to read first (`payload.data.status`):

| Endpoint | Records (`response_shapes`) |
|---|---|
| `screen` | `payload.rows` |
| `realtime`, `hotlist`, `sector` | `payload.data.rows` |
| `ml/clusters` | `payload.data.clusters` and `payload.data.anomaly_watch` |
| `whales` | `payload.data.signal_board.signals` (a dict of boards) |
| `news` | `payload.data.articles` |
| `factor-portfolios` | `payload.data.portfolios` (one book per factor). State at `payload.data.status`. The weekly returns are at `payload.data.returns`, a dict keyed by factor |
| `factor-portfolios/meta` | `payload.data.publications`. State at `payload.data.status` |
| `notes/daily` | `payload.data.notes` |
| `macro/calendar` | `payload.data.data.events` |
| `bond/etfs` | `payload.data.data.etfs` |
| `me`, `summary` | Not listed. `me` is a flat object. The summary's per-market rows are at `payload.data.markets` (checked against a live response) |

**An empty list is normal.** A closed market, a weekend, or a hotlist with no
qualifying names can return zero rows. Read the freshness fields (`as_of_*`,
`market_status`, `data_quality`, `stale_reason`) before the numbers. The factor
portfolios say so explicitly: `data.status` is `"empty"`, with a `reason_code`
and a `message`, and their freshness is a block of its own (`data.freshness`).

**Check the unit of every number.** Two "returns" in this API are measured
differently, so never mix them:

- Fractions (0.0142 = 1.42%): screen and sector `change_pct`, the sector
  means, `ma*_excess`, `ep`, `bp`, `sp`, `profit_margin`, `revenue_growth`
  and `dividend_yield`, and the summary's `avg_change_pct`. In the factor
  portfolios: every `week_return` (a weekly return, 0.0125 = 1.25% for the
  week), holding `weight` (a book's weights sum to 1) and the
  `*_weight_share` fields.
- Exposures (1.0 = one unit): factor-portfolio `exposures`, `own_exposure`
  and `max_abs_other_style` are loadings on a style, not percents.
- Percents (1.42 = 1.42%): realtime and hotlist `intraday_return_pct`, and
  the bond ETF `pct_change_1d`, the `*_pct` fields and `expense_ratio`.
- Ratios (2.0 = twice): `turnover_vs_10d` and `projected_vs_yesterday`.
- Money: screen and realtime amounts are in local currency. Fields ending in
  `_usd` and the bond ETF `aum` are in US dollars.

## Open endpoints (no key)

### `GET /api/v1/health`

Shows operational health and data-quality disclosures, overall and for each
market. It takes no parameters. Notebook: 00 Setup and account. Used again in
02 ML market map and whales, to date the ML run in trading sessions.

`health` answers **HTTP 200 even when it reports a problem**. For example, if
one market is stale (as `cn` is during a holiday), the top level can read
`"ok": false` and `"status": "degraded"` while the other markets are healthy.
Read each market in `payload.markets.{market}`. Use `status`,
`data_quality_status`, `published_session_date` and `reason`. Treat
`"ok": false` from `health` as data, not as a failed request.

```bash
curl -sS "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/health"
```

```python
health = requests.get(f"{BASE_URL}/api/v1/health", timeout=30).json()
print(health["status"])
for market, info in health["markets"].items():
    print(market, info["status"], info["published_session_date"], info["reason"])
```

### `GET /api/v1/catalog`

Returns the catalogue: base URL, authentication options, plans and limits,
every endpoint, `response_shapes` and the supported `markets`. It takes no
parameters. Notebook: 00 Setup and account.

```bash
curl -sS "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/catalog"
```

```python
catalog = requests.get(f"{BASE_URL}/api/v1/catalog", timeout=30).json()
print(catalog["markets"])  # ['us', 'cn', 'jp', 'hk']
for endpoint in catalog["authenticated_endpoints"]:
    print(endpoint["path"], "-", endpoint["scope"])
```

### `POST /api/v1/keys`

The Membership page form uses this endpoint to issue a free key. Create your
key on the website at `https://surgeflows.capital/membership#api-key`. Scripts
do not need this endpoint.

## Authenticated endpoints

Each section gives the catalogue scope and the notebook that teaches the
endpoint. The free plan includes every scope listed here. Parameter ranges
match the backend at the time of writing; the live catalogue wins if they
differ.

### Account

#### `GET /api/v1/me`

Inspect the active key: plan, scopes, rate-limit counters and rolling usage.
The response never includes the secret.

- Scope: any. Query: none.
- Records: a flat object with no records list. Use `plan`, `scopes`,
  `rate_limit` (the rate-limit headers, as strings) and `usage` (`used_7d`,
  `used_30d`, `last_used_at`).
- **Personal fields.** The object also holds `key_prefix`, `member_id`,
  `referral_code`, `invite_url`, `referrals` and founding-member details. Do
  not print the whole object in a notebook, terminal or screenshot that you
  might share. Select the fields above instead.
- Taught in: [00 Setup and account](../notebooks/00-setup-and-account.ipynb),
  and the
  [60-second quick start](../notebooks/surgeflow-realtime-hotlist-60s.ipynb).

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/me"
```

```python
me = get("/api/v1/me")
print(me["plan"], me["scopes"])
print(me["usage"]["used_7d"], "requests in 7 days;",
      me["rate_limit"]["X-RateLimit-Daily-Remaining"], "left today")
```

#### `GET /api/v1/summary`

A four-market market-watch summary with freshness metadata and FX context.

- Scope: `summary`. Query: none.
- Records: one row per market at `payload.data.markets`, with FX rates
  (local units per US dollar) at `payload.data.fx_rates`. This layout has been
  checked against a live response. Each market row carries `as_of_date`,
  `surge_count`, `avg_change_pct` (a **fraction**: 0.005 = +0.5%, the plain
  mean of the day's `change_pct` over the market screen's names) and
  `total_turnover`. `total_turnover` is in local currency, so convert it
  before you compare markets.
- **It can fail.** The summary can answer `HTTP 500 Internal Server Error`
  with a plain-text body. Treat it as optional and keep your code running
  without it.
- Taught in: [00 Setup and account](../notebooks/00-setup-and-account.ipynb).

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/summary"
```

```python
try:
    summary = get("/api/v1/summary")
except SurgeFlowError as exc:  # e.g. HTTP 500: Internal Server Error
    print("Summary unavailable right now:", exc)
else:
    for market in summary["data"]["markets"]:
        print(market["market"], market["as_of_date"], market["surge_count"])
```

### Market boards

#### `GET /api/v1/markets/{market}/screen`

The paged institutional market screen: one row per stock, with price, daily
change, turnover, market cap, trend, valuation and quality fields.

- Scope: `screen`.
- Query: `page` (from 1), `page_size` (1 to 100; a larger value is rejected
  with `VALIDATION_ERROR`) and `sort=market_cap_usd` (largest companies
  first).
- Records: `payload.rows`, at the top level. The top level also carries
  `market`, `as_of_date`, `generated_at`, `page`, `page_size`, `total_pages`,
  `count` and `data_quality` (a dict of coverage statistics). `count` is the
  number of stocks in the whole screen, not the rows on this page. A page past
  the end returns `rows: []`.
- Row fields: `ticker`, `company_name`, `sector`, `industry`, `price`,
  `change_pct` (a **fraction**: the daily change against the previous close,
  0.0142 = +1.42%), `turnover`, `previous_day_turnover` (local currency;
  always null for `cn`), `turnover_vs_10d` (ratio), `market_cap_usd`,
  `ma10_excess`, `ma50_excess`, `ma200_excess`, `ep`, `bp`, `sp`,
  `profit_margin`, `revenue_growth`, `dividend_yield` (all fractions;
  `dividend_yield` is always null for `hk`), `ratio_quality` and
  `institutional_default`.
- **Do not fetch every page.** The US screen holds about 3,300 stocks (33
  pages of 100). Fetch the first few pages of the largest companies.
- Taught in: [01 Market boards](../notebooks/01-market-boards.ipynb). Used
  again in
  [02 ML market map and whales](../notebooks/02-ml-map-and-whales.ipynb) (a
  market-cap cross-check) and [05 ML lab](../notebooks/05-ml-lab.ipynb).

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/markets/us/screen?page=1&page_size=100&sort=market_cap_usd"
```

```python
rows = []
for page in (1, 2, 3):  # the 300 largest companies
    payload = get("/api/v1/markets/us/screen", page=page, page_size=100, sort="market_cap_usd")
    rows += payload["rows"]
    if not payload["rows"] or page >= payload["total_pages"]:
        break
print(len(rows), "of", payload["count"], "stocks, as of", payload["as_of_date"])
top = rows[0]
print(top["ticker"], f"{top['change_pct']:+.2%}")  # a fraction: 0.0142 -> +1.42%
```

#### `GET /api/v1/markets/{market}/realtime`

A spreadsheet-safe, current-session turnover board: the most-traded names,
with turnover per second, projected turnover and pace versus yesterday.

- Scope: `realtime`. Query: `limit` (1 to 100, default 50).
- Records: `payload.data.rows`. `payload.data` also carries `market`,
  `as_of_utc`, `as_of_local`, `market_status` (`OPEN` or `CLOSED`),
  `data_quality` (`ok`, or `stale` after the close), `stale_reason`
  (`market_closed`), `source` and `count`. A closed market returns its last
  session.
- Row fields: `rank`, `ticker`, `company_name`, `price`,
  `intraday_return_pct` (a **percent**: -1.19 = -1.19%), `turnover_per_second`,
  `accumulated_turnover`, `projected_turnover`, `previous_day_turnover` (local
  currency) and `projected_vs_yesterday` (ratio). `intraday_return_pct` is
  measured differently from the screen's `change_pct`, so do not compare or
  combine the two.
- Taught in: [01 Market boards](../notebooks/01-market-boards.ipynb) and the
  [60-second quick start](../notebooks/surgeflow-realtime-hotlist-60s.ipynb).
  Used again in [05 ML lab](../notebooks/05-ml-lab.ipynb).

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/markets/us/realtime?limit=25"
```

```python
data = get("/api/v1/markets/us/realtime", limit=25)["data"]
print(data["market_status"], data["data_quality"], data["stale_reason"], data["as_of_utc"])
for row in data["rows"][:5]:
    print(row["rank"], row["ticker"], f"{row['intraday_return_pct']:+.2f}%", f"{row['projected_vs_yesterday']:.2f}x")
```

#### `GET /api/v1/markets/{market}/hotlist`

The spreadsheet-safe momentum hotlist: a short list of the session's momentum
names.

- Scope: `hotlist`. Query: none.
- Records: `payload.data.rows`, with the same `payload.data` metadata as
  realtime.
- Row fields: `hotlist_rank`, `market` (upper case), `ticker`,
  `company_name`, `industry`, `factor_style`, `price` (local currency),
  `intraday_return_pct` (percent), `turnover_per_second`, `market_cap_usd`,
  `projected_turnover_usd`, `previous_day_turnover_usd` (US dollars) and
  `projected_vs_yesterday` (ratio).
- **Empty is normal.** A market with no qualifying names returns `count: 0`,
  `rows: []`, `data_quality: "empty"` and
  `stale_reason: "no_current_hotlist_members"`. Several markets can be empty
  at once. Print a friendly message instead of raising.
- Taught in: [01 Market boards](../notebooks/01-market-boards.ipynb) and the
  [60-second quick start](../notebooks/surgeflow-realtime-hotlist-60s.ipynb).

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/markets/us/hotlist"
```

```python
data = get("/api/v1/markets/jp/hotlist")["data"]
if not data["rows"]:
    print(f"No hotlist names in {data['market']} right now ({data['stale_reason']}). That is normal.")
for row in data["rows"]:
    print(row["hotlist_rank"], row["ticker"], f"{row['intraday_return_pct']:+.2f}%", row["projected_vs_yesterday"])
```

#### `GET /api/v1/markets/{market}/sector`

A compact sector snapshot: each ticker's daily change, with market-cap-weighted
sector and industry means and a whale overlay.

- Scope: `screen`. Query: none.
- Records: `payload.data.rows`. This is the whole screen in one unpaged
  response. Row fields: `ticker`, `name`, `sector`, `industry`, `change_pct`
  (fraction, the same value as the screen), `sector_mean_1d` and
  `industry_mean_1d` (cap-weighted means, fractions), `is_microcap`,
  `whale_fund_count`, `whale_trend` and `whale_confidence`. The sector means
  repeat on every row, so de-duplicate by `sector` to get the sector table.
- Taught in: [01 Market boards](../notebooks/01-market-boards.ipynb). Used
  again in
  [03 News, notes, macro and bonds](../notebooks/03-news-notes-macro-bonds.ipynb)
  (news joined to the day's price changes).

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/markets/us/sector"
```

```python
rows = get("/api/v1/markets/us/sector")["data"]["rows"]
sectors = {row["sector"]: row["sector_mean_1d"] for row in rows}
for sector, mean in sorted(sectors.items(), key=lambda item: item[1]):
    print(f"{sector:<25} {mean:+.2%}")
```

### ML market map and whales

#### `GET /api/v1/markets/{market}/ml/clusters`

The latest ML clustering run: cluster profiles, sector mix, representative
tickers, an anomaly watch and stability diagnostics. This is descriptive
analytics, not prediction.

- Scope: `ml`. Query: none.
- Records: clusters at `payload.data.clusters`, anomalies at
  `payload.data.anomaly_watch`. Freshness is at `payload.data.run`
  (`as_of_date`, `stale`). `cluster_id` is an id, not a position: the ids skip
  numbers, and clusters are listed by size.
- Taught in:
  [02 ML market map and whales](../notebooks/02-ml-map-and-whales.ipynb). Used
  again in [05 ML lab](../notebooks/05-ml-lab.ipynb).

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/markets/us/ml/clusters"
```

```python
data = get("/api/v1/markets/us/ml/clusters")["data"]
print(data["run"]["as_of_date"], "stale:", data["run"]["stale"])
for cluster in data["clusters"]:
    print(cluster["cluster_id"], cluster["cluster_name"], cluster["ticker_count"])
```

#### `GET /api/v1/markets/{market}/whales`

The institutional-holdings signal board, built from disclosure filings:
consensus, conviction, crowdedness, position deltas and network reads.

- Scope: `whales`. Query: none.
- Records: `payload.data.signal_board.signals`. This is a **dict of boards**
  (`consensus`, `conviction`, `crowdedness`, `position_delta`, `network`,
  `ll_predictive`), each holding a list of rows. Filings lag the market, so
  date each row by its `as_of_date`. `quarter` is a free-text label whose
  format varies by market (`cn` mixes `2026-Q2` with fund-report titles; `jp`
  and `hk` carry a date), so do not group or parse by it.
- Taught in:
  [02 ML market map and whales](../notebooks/02-ml-map-and-whales.ipynb). Used
  again in [05 ML lab](../notebooks/05-ml-lab.ipynb).

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/markets/us/whales"
```

```python
boards = get("/api/v1/markets/us/whales")["data"]["signal_board"]["signals"]
for board, rows in boards.items():
    print(board, len(rows), rows[0]["as_of_date"] if rows else "-")
```

### News, notes, macro and bonds

#### `GET /api/v1/markets/{market}/news`

The latest scored news articles, with sentiment, tickers and keywords.

- Scope: `news`. Query: `ticker`, `sentiment` (`positive`, `negative` or
  `neutral`) and `limit` (at most 50).
- Records: `payload.data.articles`. The article fields used below have been
  checked against live responses: `published_utc`, `sentiment_score`, and
  `tickers` and `keywords` as JSON-encoded strings that you decode with
  `json.loads`. A successful answer has no `data.ok` key.
- **It can fail inside an HTTP 200.** While the news feed is down, every
  market can answer
  `{"ok": true, ..., "data": {"ok": false, "error": {"code": "INTERNAL_ERROR", "message": "news feed temporarily unavailable"}}}`.
  Check `payload["data"].get("ok") is False` before you read the articles
  (the `get` helper above raises `SurgeFlowError` for it).
- Taught in:
  [03 News, notes, macro and bonds](../notebooks/03-news-notes-macro-bonds.ipynb).

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/markets/us/news?ticker=AAPL&sentiment=positive&limit=50"
```

```python
import json

try:
    articles = get("/api/v1/markets/us/news", sentiment="negative", limit=50)["data"]["articles"]
except SurgeFlowError as exc:  # e.g. HTTP 200 INTERNAL_ERROR: news feed temporarily unavailable
    print("News is unavailable right now:", exc)
    articles = []
for article in articles[:5]:
    print(article["published_utc"], article["sentiment_score"], json.loads(article["tickers"]))
```

#### `GET /api/v1/notes/daily`

The complete daily research notes: the global note plus one note per market.

- Scope: `notes`. Query: `market` (default `all`; or `us`, `cn`, `jp`, `hk`)
  and `as_of_date` (`YYYY-MM-DD`).
- Records: `payload.data.notes`. The default returns five notes, each with
  `market` (`all` for the global note), `title` and `sections` (`tab`,
  `label`, `ok`, `headline`, plus tab-specific fields).
- The notes are member content. Read them in your own notebook, but do not
  republish them.
- Taught in:
  [03 News, notes, macro and bonds](../notebooks/03-news-notes-macro-bonds.ipynb).

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/notes/daily?market=all"
```

```python
notes = get("/api/v1/notes/daily", market="all")["data"]["notes"]
jp_note = next(note for note in notes if note["market"] == "jp")
for section in jp_note["sections"]:
    print(section["tab"], "-", section["headline"])
```

#### `GET /api/v1/macro/calendar`

A per-market calendar of upcoming macro releases, with previous values and
consensus.

- Scope: `macro`. Query: `market` (`us`, `cn`, `jp` or `hk`; default `us`) and
  `days` (1 to 60, default 14).
- Records: `payload.data.data.events` (two `data` levels), with `stale` and
  `last_checked_utc` beside them. Event fields include `indicator_name`,
  `category`, `importance` (`low`, `medium`, `high`), `release_time_utc`,
  `local_time`, `previous`, `consensus`, `unit` and `status` (`scheduled`, or
  `missing_consensus` when there is no consensus). `actual` and `surprise`
  (`actual - consensus`) stay null until the figure is released.
- Taught in:
  [03 News, notes, macro and bonds](../notebooks/03-news-notes-macro-bonds.ipynb).

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/macro/calendar?market=us&days=30"
```

```python
calendar = get("/api/v1/macro/calendar", market="us", days=30)["data"]["data"]
print(calendar["last_checked_utc"], "stale:", calendar["stale"])
for event in [e for e in calendar["events"] if e["importance"] == "high"][:5]:
    print(event["release_time_utc"], event["indicator_name"], event["previous"], event["consensus"])
```

#### `GET /api/v1/bond/etfs`

The bond ETF board: AUM, expense ratio, last close, 1-year and YTD returns,
yields and credit spreads across the US credit and rates complex.

- Scope: `macro`. Query: none.
- Records: `payload.data.data.etfs` (two `data` levels). Percent fields
  (`pct_change_1d`, `*_pct`, `expense_ratio`) are in percent, so 0.14 means
  0.14%. `aum` is in US dollars and `credit_spread_bps` in basis points.
- Taught in:
  [03 News, notes, macro and bonds](../notebooks/03-news-notes-macro-bonds.ipynb).

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/bond/etfs"
```

```python
etfs = get("/api/v1/bond/etfs")["data"]["data"]["etfs"]
for etf in etfs:
    print(etf["ticker"], etf["aum"], etf["return_ytd_pct"], etf["credit_spread_bps"])
```

### Factor portfolios

Two endpoints serve SurgeFlow's weekly **long-only pure factor portfolios**
(schema `surgeflow.factor_portfolios.v2`): one book per style (`SIZE`,
`VALUE`, `MOMENTUM`, `PROFITABILITY`, `INVESTMENT`, `LIQUIDITY`) plus a
`MARKET` book. Read the small `/meta` answer first, then ask the main endpoint
for only what you need, and read `payload.data.status` before anything else.

How to read the books (this matters before any number):

- **Long-only, fully invested, rebuilt weekly.** Each book only buys stocks,
  its weights sum to 1, and it is built so that its exposure is about 1 to its
  own style and about 0 to the other styles. Its **market exposure is 1 by
  construction** (`data.labels.product` states this).
- **So raw returns move together.** Every book carries the market once, so the
  raw weekly returns of all seven books rise and fall with the market.
- **The style is the difference.** A style book's weekly return **minus the
  `MARKET` book's** return for the same week cancels the market *exposure*:
  both have market exposure 1, and they differ by about one unit of the
  style. A style's own returns can still move with the market, so a spread
  need not be uncorrelated with the `MARKET` book; the second column of the
  table below measures this (section 4.10 of notebook 04 does it in full).
- **PCA, two ways.** A PCA on the raw long-only returns is dominated by one
  market component. Run it on the style-minus-`MARKET` series to see the
  styles.
- **Return basis and costs.** Returns are gross of costs. The return basis is
  declared per market and can differ between markets (a split-adjusted price
  return in one, a dividend-adjusted total return in another, for example).
  Quote the response's own `data.return_basis.returns_label`, and `/meta`'s
  `cost_label`, instead of paraphrasing them.
- **Freshness.** Publications are weekly, and the API reports how many weeks
  the latest formation is behind the current week together with a `state` (it
  counts one week behind as `current`). Show `state` and `weeks_behind`
  exactly as the response reports them.
- **Not recommendations.** `data.labels.candidates` says it in the API's own
  words: these are model candidates, not recommendations, and no accuracy or
  performance claim is made. Research and education only.

#### `GET /api/v1/markets/{market}/factor-portfolios/meta`

Publication metadata for the factor portfolios: a small answer to read before
the books.

- Scope: `factors`. Query: none.
- State: `payload.data.status` is `"available"` or `"empty"` (HTTP 200 either
  way). An empty answer carries `data.reason_code`
  (`no_publication_for_market` for a market without a publication) and
  `data.message`, and none of the publication fields below: no
  `publications`, `publication`, `models`, `freshness`, `cost_label` or
  `served_caveats`. A few blocks are still there, with null values where
  nothing is published: `return_basis` (`state` reads
  `no_portfolios_published` and `returns_label` is `null`), `degraded_rule`,
  `labels` (the `status` labels, with a `null` degraded rule) and
  `market_caveats`, the known data caveats for that market. So test
  `data.status`, not whether a key is present.
- Records: `payload.data.publications`, one row per publication, with
  `publication_id`, `first_formation`, `last_formation`,
  `data_through_session` and `published_at`. The publication being served is
  also at `payload.data.publication`.
- Also in `payload.data`: `models` (each model's `state`, for example
  `published` or `not_published`, and its formation window), `universe`
  (`n_in_universe` and its dates), `holdout` and `holdout_label`,
  `cost_basis` and `cost_label`, `return_basis` (with `returns_label`),
  `served_caveats.items[]` (`key`, `state`, `text`), `survivorship` and
  `labels`.
- **Freshness, per model.** `data.freshness.portfolios` holds
  `latest_formation_date`, `latest_week_start`, `current_week_start`,
  `weeks_behind` and `state`; a model that is not published yet is `null`
  here. (The main endpoint's `data.freshness` is the same block without the
  model level.)
- Taught in: [04 Factor portfolios](../notebooks/04-factor-portfolios.ipynb).
  Used again in [05 ML lab](../notebooks/05-ml-lab.ipynb) (the cost label and
  the freshness block).

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/markets/us/factor-portfolios/meta"
```

```python
for market in ("us", "cn", "jp", "hk"):
    meta = get(f"/api/v1/markets/{market}/factor-portfolios/meta")["data"]
    if meta["status"] != "available":  # "empty" is an HTTP 200 state, not an error
        print(f"{market}: {meta['status']} ({meta['reason_code']}) {meta['message']}")
        continue
    fresh = meta["freshness"]["portfolios"]
    print(f"{market}: {len(meta['publications'])} publication(s), serving {meta['publication']['publication_id']}")
    print(f"    freshness state: {fresh['state']} | weeks_behind: {fresh['weeks_behind']}")
    print(f"    {meta['cost_label']}")
```

#### `GET /api/v1/markets/{market}/factor-portfolios`

The books themselves: for one formation week, each book's exposures, the
API's own checks and its largest holdings, plus the weekly return series of
every book, status counts, labels, caveats, the return basis and the freshness
block.

- Scope: `factors`.
- Query (all optional):

  | Parameter | Values | Default | What it does |
  |---|---|---|---|
  | `factor` | `MARKET`, `SIZE`, `VALUE`, `MOMENTUM`, `PROFITABILITY`, `INVESTMENT`, `LIQUIDITY` | all seven | Return one book only |
  | `formation_date` | `YYYY-MM-DD` | the latest | The formation week whose books you want |
  | `weeks` | 1 to 1000 | 52 | Weeks of returns per book |
  | `holdings` | 0 to 5000 | 25 | Largest holdings per book; 0 for none |
  | `measurement` | `true`, `false` | `true` | Add the Fama-French 2x3 long-short measurement twins |

- **Ask for what you need.** Five years of weeks with 25 holdings and the
  measurement twins come to several megabytes. For return series only, send
  `holdings=0` and `measurement=false`.
- State: `payload.data.status`, `"available"` or `"empty"` (HTTP 200 either
  way). An empty answer carries `data.reason_code` and `data.message`: for
  example `no_publication_for_market` for a market without a publication
  (`hk` when this guide was written), or `formation_date_not_published` for
  a `formation_date` that is not a published formation week. Show
  `data.message`; it is not an error.
- Errors: HTTP 400 `INVALID_FACTOR` (`error.factors` lists the valid names),
  `INVALID_DATE` or `INVALID_MARKET`; HTTP 503 when the data cannot be read
  right now.
- Records: `payload.data.portfolios`, one record per book: `factor`,
  `status`, `week_return` (fraction), `n_holdings`, `universe_n`,
  `exposures` (`market`, `size`, `value`, `momentum`, `profitability`,
  `investment`, `liquidity`), `own_exposure`, `max_abs_other_style`, `checks`
  (`sum_ok`, `own_ok`, `others_ok`, `bounds_ok`, `matches_published`),
  `sum_weight`, `holdings` (`ticker`, `sector`, `weight`, `exposures`),
  `holdings_truncated`, `return_basis_label`, and the carried, invalid and
  exit weight shares. A book that could not be formed that week has a
  `status` other than `"available"` (for example `"infeasible"`, with
  `infeasible_constraint` naming the failed constraint), `n_holdings: 0` and
  no `exposures` or `checks`, so check `status` before you read them.
- Weekly returns: `payload.data.returns` is a **dict keyed by factor**. Each
  value is a list of weekly rows with `week_start`, `formation_date`,
  `week_end_session`, `week_return` (fraction), `status` (`ok`, `degraded`,
  `unavailable`, `no_holdings`, ...; `status_label` explains each),
  `in_inference`, `carried_weight_share`, `in_holdout` and
  `return_basis_label`. `week_return` is `null` when a week has no return.
  A degraded week keeps its return but is excluded from inference
  (`in_inference: false`); `data.degraded_rule` states the rule. Calendar
  weeks in which the market was closed all week are gaps
  (`data.calendar_grid.gap_weeks`), never compressed.
- Also in `payload.data`: `counts` (weeks per status, per factor),
  `publication` (`publication_id`, `first_formation`, `last_formation`,
  `data_through_session`, `published_at`), `n_weeks` (weeks in the whole
  publication, not in this answer), `freshness` (`latest_formation_date`,
  `latest_week_start`, `current_week_start`, `weeks_behind`, `state`),
  `labels` (`product`, `returns`, `cost`, `candidates`, `holdout`, `timing`,
  `status`), `return_basis` (`returns_label`), `served_caveats.items[]`,
  `survivorship` (`state`, `estimate_label`, `points_per_year`, `bound`),
  `calendar_grid`, `degraded_rule`, `week_state`, `return_state` and `cache`.
- Measurement twins (with `measurement=true`):
  `payload.data.measurement_twins.s3b_ff_2x3_ew` (equal weight) and
  `.s3b_ff_2x3_rp126` (inverse 126-session volatility weight). Each is a
  Fama-French 2x3 long-short measurement portfolio, not the product, with its
  own `label` and `returns_label` and weekly rows at `returns[FACTOR]`, shaped
  like `data.returns`.
- In the kit, `records(payload, "factor_portfolios")` returns
  `payload.data.portfolios`; read `payload.data.returns` yourself.
- Taught in: [04 Factor portfolios](../notebooks/04-factor-portfolios.ipynb).
  Used again in [05 ML lab](../notebooks/05-ml-lab.ipynb) (PCA on the weekly
  returns, raw and style minus `MARKET`).

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/markets/us/factor-portfolios?weeks=156&holdings=10&measurement=false"

# One book, one week, no holdings (an unknown factor answers HTTP 400 INVALID_FACTOR)
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/markets/jp/factor-portfolios?factor=VALUE&weeks=1&holdings=0&measurement=false"
```

```python
data = get("/api/v1/markets/us/factor-portfolios", weeks=156, holdings=10, measurement="false")["data"]
if data["status"] != "available":  # "empty" is an HTTP 200 state, not an error
    print(data["reason_code"], "-", data["message"])
else:
    fresh = data["freshness"]
    print("freshness state:", fresh["state"], "| weeks_behind:", fresh["weeks_behind"])
    print(data["return_basis"]["returns_label"])
    print(data["labels"]["candidates"])
    for book in data["portfolios"]:
        if book["status"] != "available":  # e.g. "infeasible": no holdings this week
            print(f"{book['factor']:<13} {book['status']} ({book.get('infeasible_constraint')})")
            continue
        print(f"{book['factor']:<13} own exposure {book['own_exposure']:.3f} | largest other "
              f"{book['max_abs_other_style']:.1e} | {book['n_holdings']} names | checks pass: {all(book['checks'].values())}")
```

Then turn the returns dict into one table and subtract the `MARKET` book:

```python
import pandas as pd

weekly = pd.DataFrame({  # one column per book, one row per week_start
    factor: pd.Series({row["week_start"]: row["week_return"] for row in rows if row["in_inference"]}, dtype=float)
    for factor, rows in data["returns"].items()
}).sort_index()
print(weekly.count())  # weeks per book that count for inference; a book can have few or none
spreads = weekly.drop(columns="MARKET").sub(weekly["MARKET"], axis=0)  # style book minus MARKET book
print(pd.DataFrame({
    "raw book vs MARKET": weekly.drop(columns="MARKET").corrwith(weekly["MARKET"]),
    "book minus MARKET vs MARKET": spreads.corrwith(weekly["MARKET"]),
}).round(2))
```

The first column shows the raw long-only books moving with the market; the
second shows how much of that is left once the `MARKET` book is subtracted.
The market exposure cancels by construction, but a style's own returns can
still co-move with the market, so the second column need not be near zero for
every style or market.

## Data boundary

Endpoint names such as `realtime` describe the current-session board.
SurgeFlow does not claim a live-tick feed for any of the four markets.
Historical and fundamental outputs may be current to the last completed market
session, the factor portfolios are weekly, and cadence varies by market. Check
each response's freshness and evidence fields before you use it.

SurgeFlow is research software. It does not place orders and is not
investment advice.

## Support

`support@surgeflows.capital`
