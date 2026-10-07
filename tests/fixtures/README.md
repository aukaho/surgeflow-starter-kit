# Offline fixtures

`tools/mock_api.py` serves these JSON files when a notebook runs offline
(`python tools/run_notebooks.py --mock`). This file is also the **field
reference** for the 15 authenticated SurgeFlow API v1 endpoints: check an
endpoint's table before you write a column name into a notebook.

## Provenance

- **Structure from live responses.** On 2026-10-07 (05:00–05:31 UTC) every
  endpoint was called with a real key (`tools/probe_endpoints.py`). The
  responses are saved in `tests/fixtures/live/`, which is git-ignored and must
  never be committed. The fixtures copy their key paths, nesting, JSON types,
  null patterns, enum vocabularies and value ranges. Where an earlier,
  guessed fixture disagreed with a live response, the live response won.
- **Values are synthetic.** `generate_fixtures.py` writes every value except
  in `catalog.json` and `health.json`:
  - no number is copied from a live response;
  - free text (notes, analyst-seat comments, rationales, headlines, summaries)
    is a neutral placeholder sentence built from the fixture's own numbers;
  - account fields in `me.json` are fake (`key_prefix` is `sf_live_xxxx`,
    which the key-leak check ignores);
  - fund names, synthetic tickers and synthetic company names are invented.

  Real tickers and company names are used for the largest listings (NVDA,
  601398, 7203, 00700, ...) so charts read naturally. Contract vocabulary is
  kept as observed: schema versions, sector and industry names, enum values,
  gate tokens, formulas, methodology version ids and site URLs.
- **Real files.** `catalog.json` (`GET /api/v1/catalog`) and `health.json`
  (`GET /api/v1/health`) are live responses from 2026-10-07. The generator
  never writes them.
- **Two endpoints errored live.** `news` answered
  `200 {"ok": true, "data": {"ok": false, "error": {"code": "INTERNAL_ERROR", ...}}}`
  for every market, and `summary` answered `HTTP 500 Internal Server Error`.
  Their fixtures keep an **inferred** success shape. Notebooks must call both
  with `sf_try`, which returns `None` and prints a note. (`sf_get` raises
  `SurgeFlowError` for the error nested inside the 200.)

Labels used in the tables:

| Label | Meaning |
|---|---|
| live | Key, JSON type and vocabulary seen in the live v1 response of 2026-10-07. |
| live-empty | The key exists live, but on 2026-10-07 it was an empty list or `null`. The fixture fills it; the item shape comes from the keyless backend twin, so treat it as unconfirmed. |
| inferred | Not seen in any live v1 response. Expect `probe_endpoints.py` to flag it once the endpoint works again. |

In the type column `?` means nullable (`float?` = float or null). **Fraction**
means 0.05 = 5%. **Percent** means 5.0 = 5%.

## Files and mock lookup

| Endpoint | Fixture file(s) | Records (`RESPONSE_SHAPES` key) |
|---|---|---|
| `GET /api/v1/me` | `me.json` | flat object |
| `GET /api/v1/summary` | `summary.json` (**inferred**) | `data.markets` (no `RESPONSE_SHAPES` entry) |
| `GET /api/v1/markets/{m}/screen` | `screen_{m}.json`, `screen_{m}.page2.json`, `screen_{m}.page3.json` | `rows` (`screen`) |
| `GET /api/v1/markets/{m}/realtime` | `realtime_{m}.json` | `data.rows` (`realtime`) |
| `GET /api/v1/markets/{m}/hotlist` | `hotlist_{m}.json` | `data.rows` (`hotlist`) |
| `GET /api/v1/markets/{m}/sector` | `sector_{m}.json` | `data.rows` (`sector`) |
| `GET /api/v1/markets/{m}/news` | `news_{m}.json` (**inferred**) | `data.articles` (`news`) |
| `GET /api/v1/markets/{m}/ml/clusters` | `ml_clusters_{m}.json` | `data.clusters` (`ml_clusters`), `data.anomaly_watch` (`ml_anomalies`) |
| `GET /api/v1/markets/{m}/whales` | `whales_{m}.json` | `data.signal_board.signals` (`whales`): a **dict of six boards** |
| `GET /api/v1/markets/{m}/factor-portfolios` | `factor_portfolios_{m}.json` | `data.data.factors` (`factor_portfolios`) |
| `GET /api/v1/notes/daily` | `notes_daily.json` (market=all), `notes_daily_{m}.json` (**inferred**) | `data.notes` (`notes`) |
| `GET /api/v1/macro/calendar` | `macro_calendar.json` (market=us), `macro_calendar_{cn,jp,hk}.json` (**inferred** market copies) | `data.data.events` (`macro_calendar`) |
| `GET /api/v1/bond/etfs` | `bond_etfs.json` | `data.data.etfs` (`bond_etfs`) |
| `GET /api/v1/catalog`, `/api/v1/health` | `catalog.json`, `health.json` (real) | n/a |

How `tools/mock_api.py` resolves a request (see its docstring):

- A path market must be `us`, `cn`, `jp` or `hk`; anything else gets
  `404 UNSUPPORTED_MARKET`.
- `page > 1` loads `{name}_{m}.page{N}.json`. Past page 3 it returns page 1
  with `rows: []` and `page` echoed back, the same way the live API answers a
  page past the end. `count` and `total_pages` stay as on page 1.
- `macro/calendar` and `notes/daily` with `?market=` load
  `{name}_{market}.json` when it exists, otherwise `{name}.json`. The live
  probe saved only the defaults (`market=us` for the calendar, `market=all`
  for notes), so the per-market files are inferred copies of the same shape.
- **Every other query parameter is ignored offline**: `page_size`, `sort`,
  `dir`, `tab`, `limit`, `ticker`, `sentiment`, `days` and `as_of_date`.
  Notebooks must not assert that a filter was applied.

## Regenerate

```bash
python tests/fixtures/generate_fixtures.py           # rewrites every generated fixture (about 10 s)
python tests/fixtures/generate_fixtures.py --check   # exits 1 if a file differs from the generator output
```

The generator uses the standard library and numpy only, and its output is
deterministic: each component draws from `default_rng([SEED, crc32(name)])`.
Fix values in the generator, never in the JSON files. The 56 files total about
4.5 MB (limit: 5 MB); every whales file is under 150 KB.

## Refresh against the live API

```bash
SURGEFLOW_API_KEY=sf_live_... python tools/probe_endpoints.py
```

The probe uses about 50 requests. It saves every response to
`tests/fixtures/live/` and prints, per endpoint, the key paths found live but
not in the fixture (`+`) and the reverse (`-`), using `paths()`, which samples
the first five items of each list. To check without calling the API, compare
the saved snapshots with the fixtures using the same `paths()` helper, then
again over **all** list items. Collapse the two dynamic-key maps first:
`sector_mix` (keys are sector names) and `top_features` (keys are feature
names).

Residual difference after this regeneration (live snapshot of 2026-10-07 vs
fixtures). Each line is expected and documented below:

| File | `paths()` (first 5 items) | All items, dynamic keys collapsed | Why |
|---|---|---|---|
| `news_{m}.json` | +3 / −38 | +3 / −40 | Live sent the nested error (`data.error.*`); the fixture keeps the inferred success shape. |
| `summary.json` | +1 / −291 | +1 / −298 | Live sent HTTP 500 (saved as `_non_json`); the fixture keeps the inferred shape. |
| `factor_portfolios_{us,cn,jp}.json` | 0 / −16 | 0 / −22 | Live blocked all seven factors, so `return_series[]`, `top_holdings[]` and the `factor_correlation` object were empty or null. The fixture publishes most factors (live-empty shapes). `factor_portfolios_hk.json` is identical to live. |
| `hotlist_cn.json` | 0 / −13 | 0 / −14 | Live CN was empty; the fixture has 20 rows with the live US row shape. |
| `ml_clusters_{m}.json` | 5–10 / 2–8 | 0 / 0 | `sector_mix` and `top_features` keys are data, not schema. Every fixture key belongs to the live vocabulary. |
| every other file | 0 / 0 | 0 / 0 | |

JSON types also match for every shared path. The only exceptions are the
populated factor fields (live-empty, above). The type comparison treats the
three screen pages of a market as one table, because rare nulls land on
different pages.

## Fixture clock

The fixtures describe **2026-10-07 about 05:20 UTC**: Tuesday night in New
York, Golden Week in China, the afternoon session in Tokyo and Hong Kong.

| | us | cn | jp | hk |
|---|---|---|---|---|
| Screen and sector `as_of_date` | 2026-10-06 | **2026-09-30** (holiday, stale) | 2026-10-06 | 2026-10-06 |
| Realtime | CLOSED, `stale` / `market_closed`, as of 2026-10-06 20:00 UTC | CLOSED, `stale` / `market_closed`, as of 2026-09-30 06:59 UTC | **OPEN**, `ok`, 15,967 s of 19,800 elapsed | **OPEN**, `ok`, 10,567 s of 19,800 elapsed |
| Hotlist | CLOSED, `stale`, 20 rows | CLOSED, `stale`, 20 rows | OPEN, **`empty`** / `no_current_hotlist_members`, 0 rows | OPEN, **`empty`**, 0 rows |
| ML run `as_of_date` / `age_days` / `stale` | 2026-10-05 / 2 / false | 2026-09-30 / 7 / **true** | 2026-10-06 / 1 / false | 2026-10-06 / 1 / false |
| Factor portfolios | 6 of 7 published (LIQ blocked) | 5 of 7 (CMA, LIQ blocked) | 6 of 7 (LIQ blocked) | **all 7 blocked**, as every market was live |

The AI research committee is paused and its two endpoints are retired (HTTP
410), so there are no AI fixtures.

## The synthetic universe

Each market has one ticker universe: **1,000** names for us, **1,150** for
cn, **900** for jp and **600** for hk. Live markets are larger (3,281 / 5,101 /
3,503 / 1,754 screened names). Screen `count`, `total_pages`, the sector board
and `qa_summary` all describe the fixture universe. Screen, sector, realtime,
hotlist, whales, ml/clusters, factor holdings, news and notes all draw from the
same universe, so **joins on `ticker` work everywhere**. The AI files use the
US universe. Tickers are strings: cn has 6 digits, hk has 5 digits
zero-padded (`"00700"`), and some jp codes contain a letter (`"285A"`). Never
cast them to int.

Structure built in, so the tutorials find something:

- **Clusters.** Every ticker belongs to a latent style archetype (momentum,
  volatility, quality, value, growth, attention, size and leverage
  loadings). Screen columns are noisy readings of those styles; the 33
  `ml/clusters` features are other readings of them. Volatility and leverage
  never reach the screen. Per-ticker cluster labels exist only for
  `representative_tickers` (8 per cluster, mostly from the three screen pages),
  `anomaly_watch[]` and `changed_group[].to_cluster_id`: 65–85 labelled screen
  tickers per market. K-means on standardised screen columns (k = the
  cluster count), compared on those tickers, gives an **adjusted Rand index of
  about 0.16–0.26**. `run.quality.silhouette` (0.10–0.17) is measured in the
  model's feature space.
- **Daily change.** `change_pct` = market × beta + sector shock + a weak
  momentum and turnover-surge link + fat-tailed noise. Regressed on the other
  screen columns it gives in-sample R² ≈ 0.36–0.46. Most of that comes from
  `ma10_excess` / `ma50_excess` / `ma200_excess`, because price / MA − 1
  contains today's move mechanically (the live data shows the same, R² ≈
  0.24–0.54). Without the moving-average columns, R² ≈ 0.04–0.11.
- **Factor returns.** 252 trading days of daily returns per published factor,
  with fat tails, volatility clustering and modest correlations (mean |ρ|
  about 0.15, max about 0.4: HML–CMA +0.4, HML–WML −0.35, SMB–LIQ +0.35).
  `stats` and `aggregate.factor_correlation` are computed from the series.
- **Identities that hold** (most also hold live):
  - Sector rows are the screen universe: same `change_pct`, and `name` equals
    the screen's `company_name`.
  - `sector_mean_1d` and `industry_mean_1d` are market-cap-weighted means of
    `change_pct`. An industry with a single member has `industry_mean_1d:
    null`, as live.
  - Realtime on an OPEN market (jp, hk): `previous_day_turnover` equals the
    screen `turnover` of the same ticker, rounded to whole units. On a CLOSED
    market the board shows the screen session.
  - Realtime `projected_turnover` = `turnover_per_second` × session seconds
    (us 23,400, cn 14,400, jp and hk 19,800), and `projected_vs_yesterday` =
    `projected_turnover / previous_day_turnover`.
  - The sector `whale_fund_count` equals the whales boards'
    `n_funds_holding`. `whale_trend` and the position-delta board share one
    flow signal.
  - The notes `whales` section repeats the top five rows of each whales board.
    The `news` section embeds three articles from `news_{m}.json`.
- **Empty and null, as live.**
  - cn screen `previous_day_turnover` is always `null`.
  - hk screen `dividend_yield` is always `null`, and
    `data_quality.dividend_yield_currency_aligned_pct` is 0.0.
  - jp and hk hotlists are empty.
  - hk factor portfolios are fully blocked.
  - cn `anomaly_watch[].coverage_ratio` is `null` and cn
    `model_notes.feature_count` is `null`.
  - Some hk `changed_group[].from_cluster_name` values are `null` (a cluster
    id that no longer exists).
  - The cn notes `turnover` section has no `top_rows`.

  The live API can also return an empty realtime board or hotlist, so **notebooks must handle an empty list everywhere**.

---

## Field reference

Envelope keys differ by endpoint (all live unless marked):

| Endpoint | Top-level keys |
|---|---|
| screen | `ok, schema_version, market, as_of_date, generated_at, page, page_size, total_pages, count, data_quality, rows`; legacy shape: no `data` |
| realtime, hotlist | `ok, schema_version, source_schema_version, data` |
| sector, whales, ml/clusters, macro/calendar | `ok, schema_version, source, market, data` |
| factor-portfolios | `ok, schema_version, source, market, note, data` |
| notes/daily | `ok, schema_version, source, market` (`"all"` by default), `data` |
| bond/etfs | `ok, schema_version, source, data` |
| me | flat: `ok, schema_version, ...` |
| news | `ok, schema_version, source, market, data`; on failure `data = {"ok": false, "error": {code, message}}` |
| summary | **inferred**: `ok, schema_version, data` |

`schema_version` is endpoint-specific (`surgeflow.market_screen.v1`,
`surgeflow.market_realtime.v1`, `surgeflow.market_hotlist.v1`,
`surgeflow.market_sector.v1`, `surgeflow.market_news.v1`,
`surgeflow.ml_clusters.v1`, `surgeflow.market_whales.v1`,
`surgeflow.factor_portfolios.v1`, `surgeflow.daily_notes.v1`,
`surgeflow.macro_calendar.v1`, `surgeflow.bond_etfs.v1`); `me` uses
`surgeflow.public_api.v1`. `source` names the backend twin
(`/api/page/sector`, `/api/ml/latest`, ...).

### `GET /api/v1/me` → `me.json`

| Field | Type | Notes | Source |
|---|---|---|---|
| `plan` | str | `free` | live |
| `scopes` | list[str] | 11 scopes: `ai, factors, hotlist, macro, ml, news, notes, realtime, screen, summary, whales` | live |
| `rate_limit` | dict[str, str] | Response headers **as strings**: `X-RateLimit-Limit` (`"180"`/min), `X-RateLimit-Remaining`, `X-RateLimit-Daily-Limit` (`"2000"`), `X-RateLimit-Daily-Remaining`, `X-SurgeFlow-RateLimit-Store`. Cast with `int()` | live |
| `usage` | dict | `used_7d`, `used_30d` (int), `last_used_at` (UTC), `first_value_reached`, `repeat_value_reached` (bool), `value_days_30d` (int), `note` (str) | live |
| `key_created_at` | str UTC | | live |
| `key_prefix`, `member_id`, `referral_code`, `invite_url`, `referrals`, `founding_analyst_number`, `is_founding_analyst` | various | **Personal. Never display them in a notebook**: screenshots get shared, and `key_prefix` trips the key-leak check. Fixture values are fake | live |

### `GET /api/v1/summary` → `summary.json` (inferred)

Live returned `HTTP 500` on 2026-10-07, so the whole shape is **inferred** from
the keyless `/api/summary` twin and the website JavaScript. Use
`sf_try("/api/v1/summary")`.

| Field | Type | Notes |
|---|---|---|
| `data.timestamp` | str UTC | Build time |
| `data.fx_rates` | dict[str, float] | `cnyPerUsd`, `hkdPerUsd`, `jpyPerUsd`, ... (local units per USD) |
| `data.totals` | dict | Universe counts across the four markets |
| `data.markets[]` | list (4) | Per market: `market, label, as_of_date, eod_session_date, ticker_count, screen_eligible_tickers, institutional_tickers, surge_count, above_ma10_count, avg_change_pct` (fraction), `total_turnover` (local), `universe{tracked_count, screen_eligible_count, exclusions}`, `factor_leaders{hml,rmw,smb,wml}`, `factor_premiums` (cn/hk only), `factor_premiums_meta`, `macro_cycle{leading, coincident, lagging, date}`, `market_cap_history[]` (30 sessions), `market_cap_long_history[]` (monthly), `market_cap_long_meta` |
| `data.factor_premiums_meta`, `data.factor_leaders_methodology` | dict | Publication status and ranking rules |

### `GET /api/v1/markets/{market}/screen` → `screen_{m}.json` + pages

Paged, largest market cap first by default (`sort=market_cap_usd`).
`page_size` is at most 100; a larger value answers `4xx VALIDATION_ERROR`.
A page past the end answers `rows: []`. Fetch a few pages, never the whole
market: live has thousands of names.

| Field | Type | Notes | Source |
|---|---|---|---|
| `market`, `as_of_date`, `generated_at` | str | Session date and build time (UTC) | live |
| `page`, `page_size`, `total_pages`, `count` | int | `count` = names in the screened universe | live |
| `data_quality` | dict | `coverage` (`full`), `fund_shares_populated_pct`, `statement_line_populated_pct`, `validated_market_cap_pct`, `market_cap_information_pit_pct`, `eps_governed_pct`, `bvps_governed_pct`, `dividend_yield_currency_aligned_pct`, `per_share_currency_pct` (all percent), `basis_population` (int), `basis_coverage_note` (str), `limitation` (str?) | live |
| `rows[].ticker`, `company_name`, `sector` | str | 11 sectors plus `Unclassified` (cn/jp/hk) | live |
| `rows[].industry` | str? | Null for some cn/jp/hk names and always for `Unclassified` | live |
| `rows[].price` | float | Local currency | live |
| `rows[].change_pct` | float?, **fraction** | Daily change vs previous close: 0.0142 = +1.42%. Not the same measure as realtime `intraday_return_pct` (percent) | live |
| `rows[].turnover`, `previous_day_turnover` | float, float? | Local currency. `previous_day_turnover` is **always null for cn** | live |
| `rows[].turnover_vs_10d` | float, ratio | Today's turnover / 10-day average | live |
| `rows[].market_cap_usd` | **int**, USD | Use a log axis | live |
| `rows[].ma10_excess`, `ma50_excess`, `ma200_excess` | float?, fraction | price / MA − 1. Each includes today's move | live |
| `rows[].ep`, `bp`, `sp` | float?, fraction | Earnings, book and sales yields (E/P can be negative) | live |
| `rows[].profit_margin`, `revenue_growth` | float?, fraction | Null more often in small caps; hk revenue growth runs high | live |
| `rows[].dividend_yield` | float?, fraction | **Always null for hk** | live |
| `rows[].ratio_quality` | str | `good` / `acceptable` | live |
| `rows[].institutional_default` | bool | Always `true` in the default screen | live |

### `GET /api/v1/markets/{market}/sector` → `sector_{m}.json`

The whole screened universe in one call (live: thousands of rows).

| Field | Type | Notes | Source |
|---|---|---|---|
| `data.ok`, `method` (`page_sector_v1`), `market`, `tab` (`sector`), `as_of_date`, `generated_at`, `filter_version`, `ratio_schema_version` | | Metadata | live |
| `data.qa_summary` | dict[str, int] | Screening funnel: `total_fund`, `excluded_adr`, `excluded_non_equity`, `excluded_no_price`, `excluded_no_fundamentals`, `screened_total`, `all_4_missing`, `any_missing`, `missing_source_null`, `missing_sanity_capped`, `ep_gt_sp`, `bp_gt_100pct`, `quality_good`, `quality_acceptable`, `quality_suspect`, `quality_unusable`, `revenue_model_industrial`, `revenue_model_financial`, `revenue_model_holding`, `null_sector`, `null_industry`, `null_profit_margin`, `null_revenue_growth` | live |
| `data.market_fundamentals_status` | dict | Same keys as screen `data_quality` | live |
| `data.count` | int | `len(rows)` | live |
| `rows[].ticker`, `name`, `market`, `sector`, `industry` (str?) | | `name` = screen `company_name` | live |
| `rows[].change_pct` | float?, fraction | Same value as the screen | live |
| `rows[].sector_mean_1d`, `industry_mean_1d` | float, float? | Cap-weighted means of `change_pct`; `industry_mean_1d` is null for one-member or null industries | live |
| `rows[].is_microcap` | bool | | live |
| `rows[].whale_fund_count` | int? | Reporting funds holding the name; null when none | live |
| `rows[].whale_trend` | str? | `accumulating` / `stable` / `distributing` (jp and hk live: no `stable`) | live |
| `rows[].whale_confidence` | str? | `low` / `medium` / `high` | live |

Row key order differs by market live (serialisation detail); the fixture keeps it.

### `GET /api/v1/markets/{market}/realtime` → `realtime_{m}.json`

The current-session turnover board (50 rows), not a live-tick feed.

| Field | Type | Notes | Source |
|---|---|---|---|
| `data.schema_version` | str | `addin.realtime.v1` | live |
| `data.market`, `as_of_utc`, `as_of_local`, `cache_ttl_seconds` (60), `count` | | | live |
| `data.market_status` | str | `OPEN` / `CLOSED` | live |
| `data.data_quality`, `stale_reason` | str, str? | `ok` + null while open; `stale` + `market_closed` after the close | live |
| `data.source` | str | `polygon` (us), `akshare_cn_spot_em` (cn), `tradingview_tse` (jp), `sina_amount_fmp_price_overlay` (hk) | live |
| `rows[].rank`, `ticker`, `company_name`, `price` | | Sorted by `projected_turnover`, largest first | live |
| `rows[].intraday_return_pct` | float, **percent** | −1.19 = −1.19%. Measured differently from screen `change_pct`; do not mix them | live |
| `rows[].turnover_per_second`, `accumulated_turnover`, `projected_turnover`, `previous_day_turnover` | float | Local currency | live |
| `rows[].projected_vs_yesterday` | float, ratio | `projected_turnover / previous_day_turnover` | live |

Live on 2026-10-07 the CN board held smaller names than the CN screen's top
pages. The fixture board is simply the top 50 of its universe.

### `GET /api/v1/markets/{market}/hotlist` → `hotlist_{m}.json`

Same `data` metadata as realtime (`schema_version: addin.hotlist.v1`,
`source: null`). **Empty boards are normal.** Live jp and hk (and cn) returned
`count: 0`, `rows: []`, `data_quality: "empty"`,
`stale_reason: "no_current_hotlist_members"`. Print a friendly sentence for them.

| Field | Type | Notes | Source |
|---|---|---|---|
| `rows[].hotlist_rank` | int | | live |
| `rows[].market` | str | **Upper case** (`US`, `CN`) | live |
| `rows[].ticker`, `company_name`, `industry` | str | | live |
| `rows[].factor_style` | str | Seven labels joined by `" / "`: `Market Long`, `Large Cap`/`Small Cap`, `Value`/`Growth`, `Momentum`/`Reversal`, `Strong Quality`/`Weak Quality`, `Conservative`/`Aggressive`, `Liquid`/`Illiquid` | live (one row seen; the alternatives are inferred) |
| `rows[].price` | float | Local currency | live |
| `rows[].intraday_return_pct` | float, percent | | live |
| `rows[].turnover_per_second`, `market_cap_usd`, `projected_turnover_usd`, `previous_day_turnover_usd` | float, **USD** | | live |
| `rows[].projected_vs_yesterday` | float, ratio | | live |

### `GET /api/v1/markets/{market}/news` → `news_{m}.json` (inferred)

**Live returned an error for every market on 2026-10-07** (inside a 200):
`{"ok": true, "schema_version": "surgeflow.market_news.v1", "source": "/api/news/feed", "market": m, "data": {"ok": false, "error": {"code": "INTERNAL_ERROR", "message": "news feed temporarily unavailable"}}}`.
Use `sf_try`, and keep the section working when articles come back. The
success shape is **inferred**:

- The envelope follows the error response, with `data.ok: true`.
- The article keys match the three articles that live `notes/daily` embeds
  per market, which raises confidence in them.
- `count`, `total_matching`, `offset`, `coverage{...}` and `methodology{...}`
  follow the keyless `/api/news/feed` twin.

| Field | Type | Notes |
|---|---|---|
| `data.ok`, `market`, `count`, `total_matching`, `offset` | | |
| `data.coverage` | dict | `total_articles, scored_pct, disclosures, media, languages[], latest_date, scope, sentiment_latest_date` |
| `data.articles[].article_id`, `published_utc` | str | `published_utc` is ISO `...Z` for most providers and `YYYY-MM-DD HH:MM:SS` for `fmp` |
| `data.articles[].title`, `description`, `publisher_name`, `article_url` | str | `article_url` can be `""`. Fixture text is placeholder; fixture links point to example.com |
| `data.articles[].tickers`, `keywords` | str | **JSON-encoded lists** (`json.loads` them) |
| `data.articles[].ticker_count` | int | |
| `data.articles[].sentiment_score`, `sentiment_label` | float (−1..1), str | `positive` / `negative` / `neutral` |
| `data.articles[].provider`, `source_family`, `language`, `article_type` | str | e.g. `benzinga` / `vendor_news` / `en` / `news`; `article_type` ∈ `news, stock, market, media, disclosure` |
| `data.articles[].sentiment_available`, `content_available` | bool | |
| `data.methodology` | dict | `source, source_family, sentiment_available, sentiment_source, content_license, note` |

### `GET /api/v1/markets/{market}/ml/clusters` → `ml_clusters_{m}.json`

| Field | Type | Notes | Source |
|---|---|---|---|
| `data.available`, `data.market` | bool, str | | live |
| `data.run` | dict | `run_id, market, as_of_date, age_days, stale, run_finished_at, universe_ticker_count, eligible_count, clustered_ticker_count, avg_coverage_ratio, has_prior_comparison, partition_stability (null)` | live |
| `data.run.quality` | dict | `k, n_clusters, silhouette, realized_max_cluster_share, balance_cap (0.4), balance_cap_satisfied, size_entropy, effective_clusters, k_scan[{k, silhouette, max_share}] (k = 6..10), cluster_sizes[] (descending), anomaly_intensity{recon_median, recon_p95, recon_p99, centroid_median, centroid_p95, pct_vs_trailing, trailing_runs, legs_correlation, note}, interpretation` | live |
| `clusters[].cluster_id` | int | **Not contiguous** (e.g. us `0, 3, 2, 9, 10, ...`); clusters are listed by size | live |
| `clusters[].cluster_name` | str | Three phrases joined by `" · "`, named after the top features (`high margin`, `low volatility (3m)`, `expensive (low E/P)`, ...) | live |
| `clusters[].ticker_count` | int | Sums to `clustered_ticker_count` | live |
| `clusters[].sector_mix` | dict[str, int] | **Dynamic keys**: the six largest sectors; `Unknown` for unclassified | live |
| `clusters[].representative_tickers` | list[str] (8) | | live |
| `clusters[].top_features` | dict[str, float] | **Dynamic keys**: six features with the largest absolute centroid z-score, in that order. Vocabulary: `ret_20d, ret_63d, ret_126d, ret_252d, rv_20, rv_63, rv_252, downside_vol_63, vol_of_vol_63, residual_vol_252_d, beta_252_d, max_drawdown_252, distance_from_high_252, rolling_sharpe_63, r2_252_d, profit_margin, revenue_growth, ni_growth, cfo_growth, leverage_debt_to_mcap, val_ep_z, val_bp_z, val_cfop_z, log_market_cap, turnover_to_mcap, pa_mfe_21d, pa_mae_21d, pa_edge_21d, pa_mfe_52w, pa_mae_52w, pa_edge_52w, pa_sir_infectious, pa_sir_recovered` | live |
| `clusters[].jaccard_vs_prior`, `membership_entrants`, `membership_leavers` | null | Always null live | live |
| `anomaly_watch[]` (40) | dict | `ticker, cluster_id, cluster_name, anomaly_score (0..1), pca_reconstruction_error, centroid_distance, coverage_ratio (float?; null for cn), low_coverage, top_drivers[{feature, z}] (4, z clipped to ±5)` | live |
| `anomaly_total` | int | Names above the anomaly threshold (= `model_notes.anomaly_count_p95`) | live |
| `changed_group[]` (40) | dict | `ticker, from_cluster_id, from_cluster_name (str?), to_cluster_id, to_cluster_name, cluster_confidence, days_in_cluster` | live |
| `model_notes` | dict | `cluster_count, clustered_ticker_count, anomaly_count_p95, avg_confidence, changed_count, feature_count (int?), feature_set_version, model_version, cluster_model_version, estimator_count, methodology, guardrails[4], disclaimer` | live |

### `GET /api/v1/markets/{market}/whales` → `whales_{m}.json`

`records(payload, "whales")` returns `[]`: `signals` is a **dict of six
boards** (top 20 each). Iterate over `payload["data"]["signal_board"]["signals"].items()`.

| Field | Type | Notes | Source |
|---|---|---|---|
| `data.market`, `as_of`, `method` (`page_whales_v1`) | str | | live |
| every board row | | `market, ticker, quarter, as_of_date, ..., methodology_version, updated_at, stock_name (str?)`. `quarter` is a date (`2026-06-30`) in us/jp/hk; cn mixes `2026-Q2` and `2026年2季度股票投资明细` | live |
| `consensus[]` | | `n_funds_holding, total_market_value (float; 0.0 when undisclosed), aum_weighted_portfolio_pct, avg_portfolio_pct (percent), consensus_score, consensus_percentile, consensus_rank, components_json (JSON string)` | live |
| `conviction[]` | | `n_funds_holding, ticker_conviction_score, ticker_conviction_percentile, ticker_conviction_rank, max_fund_conviction_z, top_conviction_fund, components_json` | live |
| `crowdedness[]` | | `n_funds_holding, n_funds_total, crowdedness_pct (fraction), crowdedness_quintile, crowdedness_rank` | live |
| `position_delta[]` | | `n_funds_buying, n_funds_selling, net_shares_change, gross_shares_buying, gross_shares_selling` (**≤ 0**), `delta_z, delta_rank, delta_percentile` | live |
| `network[]` | | `degree, weighted_degree, eigenvector_centrality, community_id, n_tickers_in_community, n_communities, modularity` | live |
| `ll_predictive[]` | | `n_funds_holding_q, n_funds_holding_q_minus_1, owner_count_change, portfolio_weight_change, ll_score_z, ll_rank, ll_percentile` | live |
| `data.signal_gate_status` | dict | `count` (all markets), `gates[]{signal_id, market, as_of_date, publish_state (publish_tested / restricted / draft), in_sample_fit?, oos_lift_pct?, stability?, spanning_alpha?, sensitivity_test_pass, gate_reason}`. Live jp/hk send thousands of gates; the fixture keeps 60–100 | live |
| `data.funds` | dict | `count` (= `len(funds)`), `funds[]{market, fund_name, fund_id, quarters, total_holdings, latest_quarter}`. Live jp/hk list up to ~20,000 funds; the fixture keeps 100–150 | live |
| `data.fund_lead_lag` | dict? | **US only** (null elsewhere): `count, funds[]{fund_name, n_quarters_observed, avg_filing_speed_days, intraday_lead_rank_avg, leader_score, leader_score_z, data_depth_caveat?}` | live |
| `data.letter_nlp` | dict? | **US only**: `count, letters[]{fund_name, letter_date, letter_type, total_tokens, n_positive, n_negative, n_uncertainty, sentiment_score, uncertainty_intensity, net_tone, lexical_diversity, finbert_positive, finbert_negative, finbert_neutral, finbert_net_tone, finbert_n_chunks}` | live |

### `GET /api/v1/markets/{market}/factor-portfolios` → `factor_portfolios_{m}.json`

`payload["data"]["data"]` holds the release. Always seven factors
(`contract_factors`: `erp, smb, hml, wml, rmw, cma, liq`). Gate state is
disclosed, not used as a row filter.

| Field | Type | Notes | Source |
|---|---|---|---|
| `market, release_id, factor_contract_sha256, contract_factors[], research_passport{...}, n_active, n_risk_ready, raw_survivors_summary[], disclosure` | | `research_passport` carries `benchmark_id` (`sp500`, `csi300`, `nikkei225`, `hsi`) and the cost model | live |
| `as_of` | str? | Null when nothing is published | live |
| `factors[].factor_id, factor_label, factor_name_published, side_displayed, effective_sign, semantic_label, evidence_status` | | e.g. `smb` / `Size` / `SMB_FF3` / `long-short pure factor` | live |
| `factors[].publish_state` | str | `blocked` (**live: all factors in all markets**) / `published` (fixture, from the twin) | live / live-empty |
| `factors[].gate_reason` | str? | `;`-joined tokens such as `correlation_triangle_not_tested`, `premium_not_significant_5pct`, `factor_sample_below_252`; null when published | live |
| `factors[].is_risk_ready`, `risk_ready_reason` (`factor_withheld`), `agreement_score` | | | live |
| `factors[].n_holdings_active_leg, holdings_as_of, holdings_weighting, holdings_preview_count, holdings_complete, benchmark_id, benchmark_name, constituent_source, return_construction` | | Null/0 when blocked | live (values when published: live-empty) |
| `factors[].stats` | dict | `n_obs, vol_annual, sharpe, max_dd, var_95_252d, es_95_252d, mean_annual`; all null when blocked | live (populated: live-empty) |
| `factors[].holdings_metrics` | dict | `ep_mcap_weighted, dy_mcap_weighted, tot_market_cap, n_constituents_total, n_constituents_with_mcap, n_constituents_with_ep, n_constituents_with_dy` | live (populated: live-empty) |
| `factors[].top_holdings[]` | list | `leg (index / long / short), ticker, name, sector, market_cap (local), latest_price, weight (signed), leg_weight, signal_value?, weight_source` | **live-empty** |
| `factors[].return_series[]` | list | `{date, ret}`, ret is a daily **fraction**, 252 days when published | **live-empty** |
| `factors[].distribution_series` | list | Always `[]` | live |
| `aggregate` | dict | `equal_weight_stats{...}, factor_correlation ({factor_ids, values} or null), n_aligned_dates, correlation_start, correlation_as_of, return_series[{date, ret}]` | live (populated: live-empty) |
| `word_cloud` | list | `[]` live and in the fixture | live |
| `narrative_coverage` | dict | `holdings_total, holdings_with_narrative, coverage_pct` | live |

### `GET /api/v1/notes/daily` → `notes_daily.json`, `notes_daily_{m}.json`

**Member-only content.** Show it in the user's own notebook, never copy it
into committed files. Every fixture sentence is a placeholder. The default
(`market=all`) returns five notes: global, cn, hk, jp, us. The per-market files
(one note each) are **inferred** for `?market=<m>`.

| Field | Type | Notes | Source |
|---|---|---|---|
| `data.ok, count, as_of_date, market, methodology_version, disclosure` | | | live |
| `data.agent_rating_contract` | dict | `schema_version, status, scale{min 1, max 5}, top_down[macro, sentiment, factor], bottom_up[technical, fundamental, risk], method` | live |
| `notes[].as_of_date, generated_at, updated_at, scope (global / market), market, title, subtitle, website_url, methodology_version` | | | live |
| `notes[].x_post, reddit_post, copy_markdown` | str | Copy-ready text (Markdown) | live |
| `notes[].source_status` | dict | Global: `market_count, section_count, ok_sections`; market: `market, section_count, ok_sections` | live |
| `notes[].sections[]` | list | `tab, label, ok, headline` plus tab-specific keys (below) | live |

Section keys by `tab` (live):

- Global note: `macro-fx`, `bond`, `macro-event` and `news` carry
  `source_url`; `markets` carries `lines[]`.
- Market notes:
  - `ma_breakthrough` (Price Momentum), `turnover` (Turnover Surge) and
    `fundamental` (Fundamental Valuation): `as_of_date, source_url, tab_url,
    filter, sort, top_rows[], error`.
  - `market_structure`: `methodology, top_rows[], error`.
  - `whales`: `lines[], leaders{consensus, conviction, crowdedness,
    position_delta, network, ll_predictive}`, each the top five rows of the
    whales board.
  - `macro` (Macro Risk): `lines[], scores{leading, coincident, lagging}`.
  - `ml_clusters` and `ai_agents` (us only): `lines[], tab_url, as_of_date`.
  - `news`: `lines[], articles[3], error`, with the same article keys as
    `news`.
- `top_rows[]` keys:
  - momentum: `ticker, name, sector, industry, market_cap (local int),
    market_cap_usd (int), price, avwap, avwap_cushion, trend_run, rsi_14,
    rsi_state, change_pct, return_5d, ytd_return, ticker_url, tab_url,
    trend_making_streak_days (some rows only), agent_rating`;
  - turnover: `ticker, name, sector, industry, turnover, turnover_usd,
    market_cap, market_cap_usd, turnover_ratio, to_yest_mult, change_pct,
    return_5d, ytd_return, ticker_url, tab_url, agent_rating`;
  - fundamental: `ticker, name, sector, industry, market_cap, market_cap_usd,
    revenue_growth, profit_margin, composite_quality, change_pct, return_5d,
    ytd_return, ep, cfop, ticker_url, tab_url, agent_rating`;
  - market structure: `structure_type, leader, metric_label, metric_value,
    secondary_label, secondary_value, [turnover_weight_pct,
    market_cap_weight_pct], member_count, as_of_date, source, tab_url`.
- `agent_rating`: `schema_version, as_of, state, available_lenses,
  total_lenses (6), overall, top_down, bottom_up, lenses{macro, sentiment,
  factor, technical, fundamental, risk: {value (1–5 int?), state, as_of,
  source, explanation?}}`, where `top_down` and `bottom_up` are the means of
  their three lenses and `overall` is the mean of the two.

### `GET /api/v1/macro/calendar` → `macro_calendar.json` (+ `_cn`, `_jp`, `_hk`)

| Field | Type | Notes | Source |
|---|---|---|---|
| `data.ok`; `data.data.days (14), source (fmp), available, last_checked_utc, stale, market` | | | live |
| `events[].event_id, market, country (US/CN/JP/HK), indicator_name, category, importance, source (fmp)` | str | `category` ∈ `other, housing, inflation, trade, growth, labor, survey, credit`; `importance` ∈ `low, medium, high` | live |
| `events[].release_time_utc`, `local_time`, `market_tz` | str | `local_time` is `YYYY-MM-DD HH:MM`, or a date alone when `time_tbd` is true (the event then sits at 00:00 UTC) | live |
| `events[].previous`, `consensus` | float? | | live |
| `events[].actual`, `surprise` | null | **Always null live**: the window lists upcoming releases only | live |
| `events[].unit` | str? | `%`, `K`, `M`, `B`, `T`, `Points` or null | live |
| `events[].status` | str | `scheduled` (has consensus) / `missing_consensus` | live |
| `events[].time_tbd`, `is_upcoming` | bool | `is_upcoming` is always true | live |

The cn/jp/hk files reuse this shape for `?market=<m>` (inferred).

### `GET /api/v1/bond/etfs` → `bond_etfs.json`

Ten US credit ETFs at `payload["data"]["data"]["etfs"]`.

| Field | Type | Notes | Source |
|---|---|---|---|
| `ticker, name, asset_class (Fixed Income), etf_company, category, fund_category, market_region (us), short_label` | str | | live |
| `aum` | float, USD | Use a log axis | live |
| `expense_ratio` | float, **percent** | 0.14 = 0.14% | live |
| `nav, last_close` | float | USD | live |
| `pct_change_1d, return_1y_pct, return_ytd_pct` | float, percent | | live |
| `volume` / `avg_volume` | float / null | | live |
| `latest_bar_date, inception_date, treasury_curve_date` | str date | | live |
| `sec_yield_30d_pct, ytm_proxy_pct, matched_treasury_yield_pct` | float, percent | | live |
| `avg_maturity_years` | float | | live |
| `credit_spread_bps` | float, bp | `(sec_yield_30d_pct − matched_treasury_yield_pct) × 100`; can be negative | live |
| `aum_source, expense_ratio_source, nav_source, inception_date_source, metadata_completeness, metadata_methodology_version` | str | Provenance | live |

## Known gaps for notebook authors

- `news` and `summary` failed live on 2026-10-07. Call them with `sf_try` and
  skip the section when it returns `None`.
- `/api/v1/me` returns personal fields. Display only `plan`, `scopes`,
  `rate_limit` and `usage`.
- `records(payload, "whales")` is always `[]` (the boards are a dict), and
  `RESPONSE_SHAPES` has no `summary` entry.
- `show_freshness` cannot see the freshness of:
  - ml_clusters (`data.run`);
  - whales (`data.as_of`);
  - factor portfolios (`data.data.as_of`, often null);
  - macro (`data.data.last_checked_utc`);
  - bond ETFs (per-row dates).

  Print those fields explicitly.
- Units differ between fields:
  - fractions: screen `change_pct`, `ma*_excess`, `ep/bp/sp`,
    `dividend_yield`, sector means, `crowdedness_pct`, factor `ret`;
  - percents: `intraday_return_pct`, `*_portfolio_pct`,
    bond `*_pct`, `expense_ratio`;
  - ratios: `turnover_vs_10d`, `projected_vs_yesterday`;
  - local currency: screen and realtime money fields;
  - USD: `market_cap_usd`, hotlist `*_usd`, bond `aum`.
- Per-ticker ML cluster labels exist only for representatives, anomalies and
  switchers.
