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

The key unlocks 15 authenticated, read-only endpoints in four markets: `us`
(United States), `cn` (China), `jp` (Japan) and `hk` (Hong Kong). They cover:

- identity, plan and usage;
- the four-market summary, the market screen and the sector snapshot;
- current-session turnover boards and momentum hotlists;
- AI analyst ratings and the AI paper grade book;
- ML clusters and institutional-holdings (whale) boards;
- news, factor portfolios, daily Notes, the macro calendar and bond ETFs.

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
`06-ml-lab`, listed in the repository README. Each endpoint section below
names the notebook that teaches it. Colab runs in your browser, so you do not
need to install Python.

### Path C: Google Sheets

The included Apps Script wrapper refreshes current-session and hotlist tables
for `us`, `cn`, `jp` and `hk`. The authenticated API and Colab notebooks
support the same four markets.

The Google Sheets add-on has been submitted for Google authentication and
Workspace Marketplace review. It is **not yet available for public one-click
installation**.

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
  `error.message`; do not rely on other keys inside `error`.
- `429`: you are over the rate limit. Wait before you retry, and honour
  `Retry-After` when it is sent.
- **An error inside an HTTP 200.** An endpoint whose upstream source fails can
  answer `200` with `"ok": true` at the top level and the error one level
  down: `{"ok": true, "data": {"ok": false, "error": {...}}}`. `news` does
  this while its feed is down. Always check `payload["data"].get("ok")`.
- **HTTP 500 with a plain-text body.** `summary` can answer
  `500 Internal Server Error` with no JSON envelope. Treat it as temporarily
  unavailable and try again later.

### Where the records live

Most payloads wrap their content in `data`. The market screen is the legacy
exception, with its rows at the top level. The catalogue's `response_shapes`
names the main record list for each endpoint:

| Endpoint | Records (`response_shapes`) |
|---|---|
| `screen` | `payload.rows` |
| `realtime`, `hotlist`, `sector` | `payload.data.rows` |
| `ai/ratings` | `payload.data.names` |
| `ai/grade-book` | `payload.data.rows` (positions) and `payload.data.decisions` |
| `ml/clusters` | `payload.data.clusters` and `payload.data.anomaly_watch` |
| `whales` | `payload.data.signal_board.signals` (a dict of boards) |
| `news` | `payload.data.articles` |
| `factor-portfolios` | `payload.data.data.factors` |
| `notes/daily` | `payload.data.notes` |
| `macro/calendar` | `payload.data.data.events` |
| `bond/etfs` | `payload.data.data.etfs` |
| `me`, `summary` | Not listed. `me` is a flat object. The summary's per-market rows are at `payload.data.markets` (inferred; not yet confirmed live) |

**An empty list is normal.** A closed market, a weekend, or a hotlist with no
qualifying names can return zero rows. Read the freshness fields (`as_of_*`,
`market_status`, `data_quality`, `stale_reason`) before the numbers.

**Check the unit of every number.** Two "returns" in this API are measured
differently, so never mix them:

- Fractions (0.0142 = 1.42%): screen and sector `change_pct`, the sector
  means, `ma*_excess`, `ep`, `bp`, `sp`, `profit_margin`, `revenue_growth`
  and `dividend_yield`. Factor `return_series` values are fractions in the
  synthetic fixtures; confirm the unit when a factor is published (every
  factor was blocked, with an empty series, in the live snapshots).
- Percents (1.42 = 1.42%): realtime and hotlist `intraday_return_pct`,
  grade-book returns, and the bond ETF `pct_change_1d`, the `*_pct` fields
  and `expense_ratio`.
- Ratios (2.0 = twice): `turnover_vs_10d` and `projected_vs_yesterday`.
- Money: screen and realtime amounts are in local currency. Fields ending in
  `_usd` and the bond ETF `aum` are in US dollars.

## Open endpoints (no key)

### `GET /api/v1/health`

Shows operational health and data-quality disclosures, overall and for each
market. It takes no parameters. Notebook: 00 Setup and account.

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
- Taught in: 00 Setup and account, and the 60-second quick start.

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
- **It can fail.** At the time of writing it answers `HTTP 500 Internal
  Server Error`, so treat it as optional and keep your code running without
  it.
- Records: one row per market at `payload.data.markets`, with FX rates at
  `payload.data.fx_rates`. This layout has not been confirmed against a
  working live response; check it when the endpoint answers again. Each
  market's `total_turnover` is in local currency, so convert it before you
  compare markets.
- Taught in: 00 Setup and account.

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
- Taught in: 01 Market boards. Used again in 06 ML lab.

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
- Taught in: 01 Market boards and the 60-second quick start. Used again in
  06 ML lab.

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
- Taught in: 01 Market boards and the 60-second quick start.

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
- Taught in: 01 Market boards.

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

### AI research council

#### `GET /api/v1/ai/ratings`

The AI analyst panel scoreboard for the US hotlist. It gives each name a
composite score, plus a score and a comment from each analyst, paper long and
short flags, tenure and stop states. This is research documentation, not
investment advice.

- Scope: `ai`. Query: `checkpoint` (default `latest`; also `morning`,
  `midday`, `close`).
- Records: `payload.data.names`, with `checkpoint_id`, `checkpoint_time` and
  `as_of_date` beside it. Each name has `ticker`, `rank`, `composite_score`,
  `long`, `short` and `per_analyst` (seat to `score` and `comment`).
- **Check the meeting's age.** `latest` is the most recent meeting, which can
  be days or weeks old. Compare `checkpoint_time` (UTC) with today before you
  read the scores.
- The analyst comments are member content. Read them in your own notebook, but
  do not republish them.
- Taught in: 02 AI research council.

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/ai/ratings?checkpoint=latest"
```

```python
from datetime import datetime, timezone

data = get("/api/v1/ai/ratings", checkpoint="latest")["data"]
age = datetime.now(timezone.utc) - datetime.fromisoformat(data["checkpoint_time"])
print(data["checkpoint_id"], data["as_of_date"], f"{age.days} days old")
for name in data["names"][:5]:
    print(name["ticker"], name["composite_score"], name["long"], name["short"])
```

#### `GET /api/v1/ai/grade-book`

The deterministic paper book. A grade above 70 opens a LONG and a grade below
30 opens a SHORT. Each position records its side-aware entry, exit and
outcome, and the book includes today's gate decisions. This is research
documentation, not investment advice.

- Scope: `ai`. Query: `market` (default `us`) and `limit` (1 to 200,
  default 80; caps `rows` only).
- Records: positions at `payload.data.rows` (`ticker`, `side`, `status`,
  `entry_price`, `exit_price`, `realized_return_pct` in percent, ...),
  opener decisions at `payload.data.decisions` (`qualifies`,
  `reject_reasons`). Read `payload.data.exit_contract` for the exit rule in
  force before you chart stops or targets.
- Taught in: 02 AI research council.

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/ai/grade-book?market=us&limit=80"
```

```python
from collections import Counter

data = get("/api/v1/ai/grade-book", market="us", limit=80)["data"]
positions, decisions = data["rows"], data["decisions"]
print(Counter(row["status"] for row in positions), "exit rule:", data["exit_contract"]["rule"])
print(sum(decision["qualifies"] for decision in decisions), "of", len(decisions), "openers qualify today")
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
- Taught in: 03 ML market map and whales. Used again in 06 ML lab.

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
- Taught in: 03 ML market map and whales. Used again in 06 ML lab.

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
- **It can fail inside an HTTP 200.** While the news feed is down, every
  market answers
  `{"ok": true, ..., "data": {"ok": false, "error": {"code": "INTERNAL_ERROR", "message": "news feed temporarily unavailable"}}}`.
  Check `payload["data"].get("ok") is False` before you read the articles
  (the `get` helper above raises `SurgeFlowError` for it).
- Records: `payload.data.articles`. The article fields used below
  (`published_utc`, `sentiment_score`, and `tickers` and `keywords` as
  JSON-encoded strings that you decode with `json.loads`) have not been
  confirmed against a working live response; check them when articles return.
- Taught in: 04 News, notes, macro and bonds.

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
- Taught in: 04 News, notes, macro and bonds.

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
- Taught in: 04 News, notes, macro and bonds.

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
- Taught in: 04 News, notes, macro and bonds.

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

#### `GET /api/v1/markets/{market}/factor-portfolios`

The canonical pure-factor portfolios, ERP to LIQ, with signed holdings
weights, expected-shortfall statistics, aligned correlations and daily
return series. Each factor discloses its publication gate state instead of
being filtered out.

- Scope: `factors`. Query: none.
- Records: `payload.data.data.factors` (two `data` levels), always 7
  factors. A blocked factor has `publish_state: "blocked"`, a `gate_reason`
  listing the checks it has not passed, `stats` whose values are null
  (`n_obs: 0`) and an empty `return_series`. All seven can be blocked at the
  same time, so handle a release with no returns.
- Taught in: 05 Factor portfolios. Used again in 06 ML lab (PCA on factor
  returns).

```bash
curl -sS -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/markets/us/factor-portfolios"
```

```python
factors = get("/api/v1/markets/us/factor-portfolios")["data"]["data"]["factors"]
for factor in factors:
    print(factor["factor_id"], factor["publish_state"], len(factor["return_series"]), factor["gate_reason"])
```

## Data boundary

Endpoint names such as `realtime` describe the current-session board.
SurgeFlow does not claim a live-tick feed for any of the four markets.
Historical, factor and fundamental outputs may be current to the last
completed market session, and cadence varies by market. Check each response's
freshness and evidence fields before you use it.

SurgeFlow is research software. It does not place orders and is not
investment advice.

## Support

`support@surgeflows.capital`
