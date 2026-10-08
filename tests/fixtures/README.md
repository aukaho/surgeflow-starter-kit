# Offline fixtures

`tools/mock_api.py` serves these JSON files when a notebook runs offline
(`python tools/run_notebooks.py --mock`). This file is also the **field
reference** for the 14 authenticated SurgeFlow API v1 endpoints in the live
catalogue (the paused AI committee's two endpoints are retired): check an
endpoint's table before you write a column name into a notebook.

## Provenance

- **Structure from live responses.** On 2026-10-07 (05:00–05:31 UTC) every
  endpoint was called with a real key (`tools/probe_endpoints.py`). The
  responses are saved in `tests/fixtures/live/`, which is git-ignored and must
  never be committed. The fixtures copy their key paths, nesting, JSON types,
  null patterns, enum vocabularies and value ranges. Where an earlier,
  guessed fixture disagreed with a live response, the live response won.
  A second snapshot the same day (about 23:10 UTC) refreshed
  `tests/fixtures/live/`. The factor-portfolio fixtures (v2 and `meta`) and
  the `ml/clusters`, `news` and `summary` shapes follow it.
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
- **Two endpoints errored in the first snapshot.** `news` answered
  `200 {"ok": true, "data": {"ok": false, "error": {"code": "INTERNAL_ERROR", ...}}}`
  for every market, and `summary` answered `HTTP 500 Internal Server Error`,
  so their shapes were first inferred. In the refreshed snapshot both
  answered, and the fixtures now match those bodies (news has no `data.ok`;
  summary has `source` and schema `surgeflow.summary.v1`). Notebooks still
  call both with `sf_try`, which returns `None` and prints a note when an
  upstream failure comes back. (`sf_get` raises `SurgeFlowError` for the error
  nested inside the 200.)

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
| `GET /api/v1/summary` | `summary.json` | `data.markets` (no `RESPONSE_SHAPES` entry) |
| `GET /api/v1/markets/{m}/screen` | `screen_{m}.json`, `screen_{m}.page2.json`, `screen_{m}.page3.json` | `rows` (`screen`) |
| `GET /api/v1/markets/{m}/realtime` | `realtime_{m}.json` | `data.rows` (`realtime`) |
| `GET /api/v1/markets/{m}/hotlist` | `hotlist_{m}.json` | `data.rows` (`hotlist`) |
| `GET /api/v1/markets/{m}/sector` | `sector_{m}.json` | `data.rows` (`sector`) |
| `GET /api/v1/markets/{m}/news` | `news_{m}.json` | `data.articles` (`news`) |
| `GET /api/v1/markets/{m}/ml/clusters` | `ml_clusters_{m}.json` | `data.clusters` (`ml_clusters`), `data.anomaly_watch` (`ml_anomalies`) |
| `GET /api/v1/markets/{m}/whales` | `whales_{m}.json` | `data.signal_board.signals` (`whales`): a **dict of six boards** |
| `GET /api/v1/markets/{m}/factor-portfolios` | `factor_portfolios_{m}.json` (one-line JSON) | `data.portfolios` (`factor_portfolios`); state at `data.status`; weekly rows in the **dict** `data.returns` |
| `GET /api/v1/markets/{m}/factor-portfolios/meta` | `factor_portfolios_meta_{m}.json` | `data.publications` (`factor_portfolios_meta`); state at `data.status` |
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
  `dir`, `tab`, `limit`, `ticker`, `sentiment`, `days`, `as_of_date`, and the
  factor-portfolio `factor`, `formation_date`, `weeks`, `holdings` and
  `measurement`. Notebooks must not assert that a filter was applied.

## Regenerate

```bash
python tests/fixtures/generate_fixtures.py           # rewrites every generated fixture (about 10 s)
python tests/fixtures/generate_fixtures.py --check   # exits 1 if a file differs from the generator output
```

The generator uses the standard library and numpy only, and its output is
deterministic: each component draws from `default_rng([SEED, crc32(name)])`.
Fix values in the generator, never in the JSON files. The 56 generated files
total about 7.4 MB. The four `factor_portfolios_{m}.json` files are one-line
JSON, 3.6 MB together (budget: 4 MB); every other file is indented, and every
whales file is under 150 KB.

## Refresh against the live API

```bash
SURGEFLOW_API_KEY=sf_live_... python tools/probe_endpoints.py
```

The probe makes about 50 requests (51). It saves every response to
`tests/fixtures/live/` and prints, per endpoint, the key paths found live but
not in the fixture (`+`) and the reverse (`-`), using `paths()`, which samples
the first five items of each list. To check without calling the API, compare
the saved snapshots with the fixtures using the same `paths()` helper, then
again over **all** list items. Collapse the two dynamic-key maps first:
`sector_mix` (keys are sector names) and `top_features` (keys are feature
names).

Residual difference after this regeneration (refreshed live snapshot of
2026-10-07 vs fixtures). Each line is expected and documented below:

| File | `paths()` (first 5 items) | All items, dynamic keys collapsed | Why |
|---|---|---|---|
| `factor_portfolios_{cn,jp}.json` | +359 / 0 (cn), +359 / −1 (jp) | +359 (cn), +373 (jp) / 0 | `data.measurement_twins` is omitted in cn and jp (size budget). jp's −1 is the optional `exit_label` (see the us row). |
| `factor_portfolios_us.json` | +10 / −1 | +3 / −1 | Every path in the difference is `exit_label`, which is optional: only rows with an unwitnessed exit carry it, so which series show it depends on the sample and on the fixture's synthetic exits. |
| `ml_clusters_{m}.json` | 3–9 / 4–8 | 0 / 0 | `sector_mix` and `top_features` keys are data, not schema. Every fixture key belongs to the live vocabulary. |
| `hotlist_cn.json` | 0 / −13 | 0 / −13 | Live CN was empty; the fixture has 20 rows with the live US row shape. |
| `realtime_cn.json` | 0 / −10 | 0 / −10 | The refreshed live CN board was empty (Golden Week); the fixture keeps the closed-session rows. |
| `ai_*.json` (live only) | | | Retired endpoints (HTTP 410); no fixture. |
| every other file, including the `meta` file of each market | 0 / 0 | 0 / 0 | |

JSON types match on shared factor-portfolio and `ml/clusters` paths. The
factor-portfolio null patterns match in cn and jp. In us they differ where the
fixture deliberately follows its own status mix rather than the live one: the
us LIQUIDITY book and the twins' SIZE and LIQUIDITY legs are formed in a few
fixture weeks (so their `week_return` and weight-share fields are sometimes
non-null), and `data.portfolios[].exit_state` is `exit_unwitnessed` on the
current us VALUE book, to exercise that path. A few older files differ only in
null patterns that follow the later clock (for example `realtime_{jp,hk}`
`stale_reason` is a string once those markets closed).
The type comparison treats the three screen pages of a market as one table,
because rare nulls land on different pages.

## Fixture clock

The fixtures describe **2026-10-07 about 05:20 UTC**: Tuesday night in New
York, Golden Week in China, the afternoon session in Tokyo and Hong Kong.

| | us | cn | jp | hk |
|---|---|---|---|---|
| Screen and sector `as_of_date` | 2026-10-06 | **2026-09-30** (holiday, stale) | 2026-10-06 | 2026-10-06 |
| Realtime | CLOSED, `stale` / `market_closed`, as of 2026-10-06 20:00 UTC | CLOSED, `stale` / `market_closed`, as of 2026-09-30 06:59 UTC | **OPEN**, `ok`, 15,967 s of 19,800 elapsed | **OPEN**, `ok`, 10,567 s of 19,800 elapsed |
| Hotlist | CLOSED, `stale`, 20 rows | CLOSED, `stale`, 20 rows | OPEN, **`empty`** / `no_current_hotlist_members`, 0 rows | OPEN, **`empty`**, 0 rows |
| ML run `as_of_date` / `age_days` / `stale` | 2026-10-05 / 2 / false | 2026-09-30 / 7 / **true** | 2026-10-06 / 1 / false | 2026-10-06 / 1 / false |
| Factor portfolios (v2) | `available`, freshness `behind` / 4 weeks; current LIQUIDITY book infeasible | `available`, freshness `behind` / 3 weeks | `available`, freshness `current` / 1 week | **`empty`** (`no_publication_for_market`) |

The factor portfolios run on their own publication clock (`FP_CFG` in the
generator): each market's data-through session, latest formation,
`publication_id` (`fixture_{m}_A_{yyyymmdd}_01`) and therefore `weeks_behind`
are fixture choices, picked to cover one `current` and two `behind` markets.
They are not the live values. Only `current_week_start` follows from the wall
clock above (the Monday of its week).

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
  loadings). Screen columns are noisy readings of those styles; the 34
  `ml/clusters` features are other readings of them. Volatility and leverage
  never reach the screen. Per-ticker cluster labels exist only for
  `representative_tickers` (8 per cluster, mostly from the three screen pages),
  `anomaly_watch[]` and `changed_group[].to_cluster_id`: 65–85 labelled screen
  tickers per market. K-means on standardised screen columns (k = the
  cluster count), compared on those tickers, gives an **adjusted Rand index of
  about 0.13–0.24**. `run.quality.silhouette` (0.10–0.17) is measured in the
  model's feature space.
- **Daily change.** `change_pct` = market × beta + sector shock + a weak
  momentum and turnover-surge link + fat-tailed noise. Regressed on the other
  screen columns it gives in-sample R² ≈ 0.36–0.46. Most of that comes from
  `ma10_excess` / `ma50_excess` / `ma200_excess`, because price / MA − 1
  contains today's move mechanically (the live data shows the same, R² ≈
  0.24–0.54). Without the moving-average columns, R² ≈ 0.04–0.11.
- **Factor portfolios.** 104 weeks per published market. Each long-only
  book's weekly return = a common market return + its own style spread +
  small noise, with fat tails and volatility clustering. Raw returns of the
  books correlate at about 0.93–0.99 with MARKET, and PCA on them gives
  PC1 ≈ 95 % of the variance. Book − MARKET cancels the market *exposure*
  and keeps about one unit of the style (weekly volatility about
  0.5–1.0 %, SIZE and LIQUIDITY about 1.0–1.2 %), but not all of the market
  *move*: a style's own returns can co-move with the market, as live
  spreads do, so each style book carries a small generic realised beta of
  1 + `style_beta` (0 to ±0.15 per book, with a different mix per
  market; `FP_CFG`). The spreads therefore correlate with the MARKET book
  at about −0.46 to +0.41: |ρ| ≈ 0.2–0.46 on 14 of the 16 spreads with at
  least 26 clean weeks, near 0 on us PROFITABILITY and cn INVESTMENT. The
  spreads share generic, rounded structure: SIZE with LIQUIDITY (ρ ≈ 0.7),
  VALUE with PROFITABILITY and INVESTMENT, MOMENTUM against VALUE, the two
  blocks mildly opposed; max |ρ| about 0.7. Standardised PCA on the six
  spreads gives PC1 ≈ 42 % (cn) and 38 % (jp), against about 25 % for the
  95th percentile of shuffled noise. us has only four spreads with
  enough weeks (SIZE and LIQUIDITY are rarely formed in the us fixture):
  PC1 ≈ 53 % against about 34 %. The spreads' PC1 score still correlates with the
  MARKET book's return: |ρ| ≈ 0.4 in cn (whose market co-movement lines up
  with the SIZE/LIQUIDITY-against-VALUE/PROFITABILITY block), about 0.2 in
  us and under 0.1 in jp. So the spread PCA can partly pick up the market,
  and an offline run exercises that case. The us twins are long-short and
  carry no `style_beta` (live twins barely co-move with the market). Each
  style leg is about twice as volatile as its book − MARKET (weekly about
  0.8–1.9 %), correlates with it at about 0.6–0.85 (slope of book − MARKET
  on the twin about 0.3–0.45), and VALUE and PROFITABILITY carry a small
  negative market loading (about −0.2 to −0.3). Holdings come from the
  shared universe. Style exposures are normal scores of size (small =
  positive), book/price, 12-1 momentum, margin, conservative investment and
  low turnover. Each style book is the nearest-to-equal-weight long-only
  book (weights ≤ 5 %) with exposure exactly 1 to its own style and 0 to the
  others.
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
  - hk factor portfolios and their `meta` answer the empty state
    (`status: "empty"`, `reason_code: "no_publication_for_market"`).
  - The us LIQUIDITY book is rarely formed: `no_holdings` in all but four
    served weeks, and the current book is infeasible (`status:
    "infeasible"`, no exposures, `holdings: []`). The us SIZE book is formed
    in 30 of the 104 weeks; the current one right after a `no_holdings`
    week, so its `turnover_one_way` is `null`. The us twins' SIZE and
    LIQUIDITY legs are `s3b_cell_below_min` with `week_return: null` except
    in a few older weeks (seven and three). Other books have a few
    `no_holdings` or `unavailable` rows, also with `week_return: null`.
    (The null patterns follow the live shapes; the counts are the
    fixture's own.)
  - cn `anomaly_watch[].coverage_ratio` is `null` and cn
    `model_notes.feature_count` is `null`.
  - One us `changed_group[].from_cluster_name` is `null`: its
    `from_cluster_id` belongs to a cluster that no longer exists. In the
    refreshed snapshot this moved from hk to us, and us has 9 clusters.
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
| factor-portfolios, factor-portfolios/meta | `ok, schema_version, source, market, note, data` |
| notes/daily | `ok, schema_version, source, market` (`"all"` by default), `data` |
| bond/etfs | `ok, schema_version, source, data` |
| me | flat: `ok, schema_version, ...` |
| news | `ok, schema_version, source, market, data`; on failure `data = {"ok": false, "error": {code, message}}` |
| summary | `ok, schema_version, source, data` |

`schema_version` is endpoint-specific (`surgeflow.market_screen.v1`,
`surgeflow.market_realtime.v1`, `surgeflow.market_hotlist.v1`,
`surgeflow.market_sector.v1`, `surgeflow.market_news.v1`,
`surgeflow.ml_clusters.v1`, `surgeflow.market_whales.v1`,
`surgeflow.factor_portfolios.v2`, `surgeflow.factor_portfolios_meta.v2`,
`surgeflow.summary.v1`, `surgeflow.daily_notes.v1`,
`surgeflow.macro_calendar.v1`, `surgeflow.bond_etfs.v1`); `me` uses
`surgeflow.public_api.v1`. `source` names the backend twin
(`/api/page/sector`, `/api/ml/latest`, ...).

### `GET /api/v1/me` → `me.json`

| Field | Type | Notes | Source |
|---|---|---|---|
| `plan` | str | `free` | live |
| `scopes` | list[str] | 10 scopes: `factors, hotlist, macro, ml, news, notes, realtime, screen, summary, whales` (the retired `ai` scope is gone) | live |
| `rate_limit` | dict[str, str] | Response headers **as strings**: `X-RateLimit-Limit` (`"180"`/min), `X-RateLimit-Remaining`, `X-RateLimit-Daily-Limit` (`"2000"`), `X-RateLimit-Daily-Remaining`, `X-SurgeFlow-RateLimit-Store`. Cast with `int()` | live |
| `usage` | dict | `used_7d`, `used_30d` (int), `last_used_at` (UTC), `first_value_reached`, `repeat_value_reached` (bool), `value_days_30d` (int), `note` (str) | live |
| `key_created_at` | str UTC | | live |
| `key_prefix`, `member_id`, `referral_code`, `invite_url`, `referrals`, `founding_analyst_number`, `is_founding_analyst` | various | **Personal. Never display them in a notebook**: screenshots get shared, and `key_prefix` trips the key-leak check. Fixture values are fake | live |

### `GET /api/v1/summary` → `summary.json`

The first snapshot returned `HTTP 500`, so the shape was inferred from the
keyless `/api/summary` twin and the website JavaScript. The refreshed snapshot
answered (`surgeflow.summary.v1`, `source: /api/summary`) and matches the
fixture's key paths and types. Use `sf_try("/api/v1/summary")`.

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

### `GET /api/v1/markets/{market}/news` → `news_{m}.json`

**The first snapshot returned an error for every market** (inside a 200):
`{"ok": true, "schema_version": "surgeflow.market_news.v1", "source": "/api/news/feed", "market": m, "data": {"ok": false, "error": {"code": "INTERNAL_ERROR", "message": "news feed temporarily unavailable"}}}`.
The refreshed snapshot answered for every market, and its key paths and types
match the fixture (there is no `data.ok` on success). Keep using `sf_try`, so
the section survives the error form.

| Field | Type | Notes |
|---|---|---|
| `data.market`, `count`, `total_matching`, `offset` | | |
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
| `clusters[].top_features` | dict[str, float] | **Dynamic keys**: six features with the largest absolute centroid z-score, in that order. Vocabulary: `ret_20d, ret_63d, ret_126d, ret_252d, rv_20, rv_63, rv_252, downside_vol_63, vol_of_vol_63, residual_vol_252_d, beta_252_d, max_drawdown_252, distance_from_high_252, rolling_sharpe_63, r2_252_d, profit_margin, revenue_growth, ni_growth, cfo_growth, leverage_debt_to_mcap, val_ep_z, val_bp_z, val_cfop_z, log_market_cap, turnover_to_mcap, log_turnover, pa_mfe_21d, pa_mae_21d, pa_edge_21d, pa_mfe_52w, pa_mae_52w, pa_edge_52w, pa_sir_infectious, pa_sir_recovered` | live |
| `clusters[].jaccard_vs_prior`, `membership_entrants`, `membership_leavers` | null | Always null live | live |
| `anomaly_watch[]` (40) | dict | `ticker, cluster_id, cluster_name, anomaly_score (0..1), pca_reconstruction_error, centroid_distance, coverage_ratio (float?; null for cn), low_coverage, top_drivers[{feature, z}] (4, z clipped to ±5)` | live |
| `anomaly_total` | int | Names above the anomaly threshold (= `model_notes.anomaly_count_p95`) | live |
| `changed_group[]` (40) | dict | `ticker, from_cluster_id, from_cluster_name (str?), to_cluster_id, to_cluster_name, cluster_confidence, days_in_cluster`. `from_cluster_name` is null when `from_cluster_id` names a cluster that no longer exists (fixture: one us row) | live |
| `model_notes` | dict | `cluster_count, clustered_ticker_count, anomaly_count_p95, avg_confidence, changed_count, feature_count (int?), feature_set_version, model_version, cluster_model_version, estimator_count, methodology, guardrails[4], disclaimer`. `feature_count` is null for cn. The refreshed live value is 36 (34 names observed); the fixture reports its own 34-name vocabulary | live |

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

Schema `surgeflow.factor_portfolios.v2` (source `/api/{market}/three-model/portfolios`).
Shape from the refreshed live snapshot (`weeks=260, holdings=25`,
measurement on); every value in the fixtures is synthetic.

**What the books are.** Seven **weekly, long-only** books, one per factor:
`MARKET, SIZE, VALUE, MOMENTUM, PROFITABILITY, INVESTMENT, LIQUIDITY`. Each book
has exposure ≈ 1 to its own style and ≈ 0 to the other styles; market exposure
is 1 by construction (`labels.product`). So the raw weekly returns of all seven
books move together with the market, and a style shows up as **book − MARKET**.
That difference cancels the market *exposure*, not necessarily all of the
market *move*: a style's own returns can co-move with the market, so a spread
can still rise and fall with it (live spreads do; the fixtures build this in
with a small per-market `style_beta`). In the fixtures PCA on the raw returns
gives PC1 ≈ 95 % of the variance; standardised PCA on the six
style-minus-MARKET series gives PC1 ≈ 42 % (cn) and 38 % (jp)
(shuffled-noise line about 25 %), and on us's four usable spreads about 53 %
(noise about 34 %). The spreads' PC1 score correlates with the MARKET book's
return at |ρ| ≈ 0.4 in cn, about 0.2 in us and under 0.1 in jp.

**Query** (live; **ignored offline**, so the fixture answers every query the
same way): `factor` (one of the seven), `formation_date` (YYYY-MM-DD), `weeks`
(1–1000, default 52), `holdings` (0–5000, default 25), `measurement` (default
true: adds `data.measurement_twins`). Scope `factors`.

**State and errors.**

- `data.status` is `available` or `empty`. **Empty is HTTP 200 with
  `ok: true`**, plus `data.reason_code` and `data.message`. Show the message;
  it is not an error. `reason_code` values: `no_publication_for_market`
  (hk; `factor_portfolios_hk.json` has the live empty-state keys, and its
  `message` is a placeholder: the live wording is not copied) and
  `formation_date_not_published` (a `formation_date` without a publication;
  same keys, no fixture).
- HTTP 400 `INVALID_FACTOR` (`error.factors` lists the valid names),
  `INVALID_DATE`, `INVALID_MARKET`; HTTP 503 when the data cannot be read
  (`sf_get` raises `SurgeFlowError`, `sf_try` returns `None`). The mock serves
  none of these.

**Fixtures.** us, cn and jp are `available` with **104 served weeks** (two
years) and 25 holdings per book; hk is `empty`. Only us carries
`data.measurement_twins`; cn and jp omit the key (size budget; the shape a
`measurement=false` answer is expected to have — inferred). The four files are
one-line JSON, 3.5 MB together (budget 4 MB). The status mix, the publication
clock and the identifiers are the fixture's own (`fp_status_plan` and
`FP_CFG` in the generator), chosen to exercise each path, not copied from a
live response. Built in:

- us: two books that are **rarely feasible**. LIQUIDITY is formed in only
  four weeks (one of them degraded), so its current book is infeasible. SIZE
  is formed in 30 weeks: mostly one half-year stretch with three misses, plus
  six isolated earlier weeks, with five degraded weeks. The current SIZE book
  is formed right after a `no_holdings` week, so its `turnover_one_way` is
  null. There is one week with incomplete return data (`unavailable` for the
  five other books). The twins' SIZE and LIQUIDITY legs are
  `s3b_cell_below_min` except in seven and three older weeks. About 22 % of
  formed book rows carry `exit_unwitnessed`. One degraded row each on MARKET,
  VALUE and MOMENTUM, so us has **nine degraded rows** in nine weeks (meta
  `checks_degraded_weeks`: 9), and an `exit_unwitnessed` state on the
  current VALUE book. The latest `formation_date` (a Tuesday) is later than
  its `week_start` (a Monday holiday).
- cn: one `unavailable` week across all books, two `no_holdings` weeks
  across all books plus two more for LIQUIDITY, one calendar gap week; no
  exits, so no cn row carries `exit_label`. One degraded row each on SIZE
  and LIQUIDITY.
- jp: every week formed and a few `exit_unwitnessed` rows; three degraded
  rows (SIZE 2, LIQUIDITY 1).

| Field | Type | Notes | Source |
|---|---|---|---|
| `data.market`, `contract` | str | `three_model_served_schema_v1` | live |
| `data.status` | str | `available` / `empty`. `reason_code` and `message` exist only in the empty state | live |
| `data.publication` | dict | `publication_id, phase (A), kinds[], published_at (UTC "Z"), first_formation, last_formation, data_through_session, code_commit, image_digest, engine_run_id, s3_run_id, s3b_run_id, attempt, checks_sha256` | live |
| `data.formation_window` | dict | `first, last` (dates) | live |
| `data.formation_date`, `week_start`, `entry_session` | str (date) | Latest formation: the first session of its week, that week's Monday, and the session before the formation | live |
| `data.week_state`, `return_state` | str | `realised` | live |
| `data.open_week`, `in_holdout`, `holdout_start` | null | | live |
| `data.n_weeks` | int | Formation weeks in the whole publication (more than the served rows) | live |
| `data.holdout_rule` | str | | live |
| `data.formation_panel` | list[str] | `["entry_session"]` | live |
| `data.portfolios[]` | list (7) | One record per factor for the latest formation (table below). `records(payload, "factor_portfolios")` | live |
| `data.returns` | **dict** factor → list | Weekly rows, oldest first (table below). A dict, not a list: iterate `.items()` | live |
| `data.counts` | dict factor → dict | `ok, degraded, unavailable, no_holdings, shares_not_recorded, return_not_yet_realised` over the served rows | live |
| `data.calendar_grid` | dict | `n_calendar_weeks, n_formation_weeks, gap_weeks[]` (Mondays of weeks with no session), `gap_share, label`. Gaps are not compressed | live |
| `data.survivorship` | dict | `state (estimated), label, note, source, points_per_year` (float, negative), `bound (lower), estimate_label` | live |
| `data.measurement` | dict | `pure_long_only, s3b_ff_2x3_ew, s3b_ff_2x3_rp126` → `{basis: investable_at_entry, label}` | live |
| `data.served_caveats` | dict | `state (declared), ruling, publication_id, label, items[], n_to_be_measured`. `items[]{key, state (stated), state_label, text}`; keys `formation_timing, measurement_costs_price, vintage, survivorship` (+ `points_per_year, bound`), `coverage_threshold, liquidity_concentration`. Fixture texts are placeholders | live |
| `data.return_basis` | dict | `basis, label, returns_label, twin_returns_label, source (rows), n_rows, declared, ruling, rule`. **The basis differs by market**: us and cn `total_return_dividend_adjusted` ("total return, dividend-adjusted"), jp `price_return_split_adjusted` ("price return, split-adjusted"). Quote `returns_label`; never hard-code the basis | live |
| `data.degraded_rule` | dict | `rule, rule_ruling, text, label, terms [carried, invalid, unwitnessed_exit], threshold (0.05), source, n_rows, n_rows_carrying, stated_values[], per_series{pure_long_only, s3b_ff_2x3_ew, s3b_ff_2x3_rp126}, declared, declaration_state, ruling, mechanism, shares_note` | live |
| `data.labels` | dict | `product, returns, cost, candidates, holdout, timing, status{ok, degraded, unavailable, no_holdings, shares_not_recorded, return_not_yet_realised}, degraded_rule, degraded_rule_label, open_week`. Fixture wording is a placeholder except `candidates` ("Model candidates, not recommendations; no accuracy or performance claim is made.") | live |
| `data.freshness` | dict | `latest_formation_date, latest_week_start, current_week_start, weeks_behind` (int), `state`. Publications are weekly; the API reports how many weeks the latest formation is behind the current week, with a state (one week behind counts as `current`). Display both as served. Fixture (its own clock): us `behind` / 4, cn `behind` / 3, jp `current` / 1 | live |
| `data.measurement_twins` | dict | **us fixture only.** `s3b_ff_2x3_ew`, `s3b_ff_2x3_rp126` → `label, role (measurement_twin), basis, basis_label, return_basis, return_basis_label, returns_label, degraded_rule, degraded_rule_label, returns{FACTOR: rows}`. Fama-French 2x3 **long-short** weekly returns with little market exposure, so the style legs track book − MARKET, at about twice its volatility (fixture: weekly 0.8–1.9 %, ρ about 0.6–0.85); the MARKET twin is a market excess return. us SIZE and LIQUIDITY legs: `s3b_cell_below_min` with `week_return: null` and `week_end_session: null`, except in a few older fixture weeks | live |
| `data.cache` | dict | `state` (`fresh` / `stale_revalidating`), `age_seconds` | live |

`data.portfolios[]`:

| Field | Type | Notes | Source |
|---|---|---|---|
| `factor` | str | | live |
| `status`, `state` | str | `available` / `ok`; a book that could not be formed: `infeasible` / `infeasible` | live |
| `construction` | str? | `normalised_objective_weight` (MARKET; us `normalised_objective_weight_reprojected`), `dual_exact_nearest_ew_l2_turnover` (us, cn), `lsq_linear_nearest_ew_l2_turnover` (jp); null when infeasible | live |
| `infeasible_constraint` | str? | e.g. `other_exposure:SIZE` | live |
| `week_return` | float? | **Fraction**; equals the last row of `returns[factor]` | live |
| `return_status`, `return_state`, `week_status` | str | `ok`, `realised`, the row status; infeasible: `no_holdings` (all three) | live |
| `turnover_one_way` | float? | Null for MARKET, for an infeasible book, and for a book not formed the previous week (its previous row is `no_holdings`; fixture: the current us SIZE book). Do not cast it to float unguarded | live |
| `n_holdings`, `universe_n` | int | Names held / universe size | live |
| `formation_panel` | list[str]? | Null when infeasible | live |
| `return_basis`, `return_basis_label` | str | | live |
| `carried_weight_share`, `invalid_weight_share`, `exit_weight_share` | float? | Fractions (largest share over the holding sessions); null without holdings | live |
| `exit_state` | str? | `exit_unwitnessed` or null. The us fixture sets it on the current VALUE book to exercise the path | live |
| `degraded_rule`, `degraded_rule_label`, `degraded_rule_source` | str | `degraded_rule_source`: `publication_declaration` | live |
| `carried_weight_share_max`, `invalid_weight_share_max`, `exit_unwitnessed_weight_share_max` | null | | live |
| `exposures`, `exposures_published` | dict[str, float] | `market, size, value, momentum, profitability, investment, liquidity`. `market` = sum of weights = 1 | live |
| `own_exposure`, `max_abs_other_style` | float | ≈ 1 and ≈ 0 (fixture: exact to ~1e-15; MARKET cn/jp ≈ 0.007) | live |
| `readback_published` | bool | | live |
| `checks` | dict[str, bool] | `sum_ok, own_ok, others_ok, bounds_ok, matches_published` | live |
| `sum_weight` | float | 1 for the whole book | live |
| `holdings[]` | list | `ticker, sector, weight` (fraction of the book), `exposures{size, value, momentum, profitability, investment, liquidity}` (z-scores). Largest weight first; fixture tickers come from the shared universe | live |
| `holdings_truncated` | bool | True when `n_holdings` exceeds the holdings shown: **the shown weights sum to less than 1** | live |
| `reason_code` | str | **Infeasible books only** (`infeasible_no_holdings`). They have no `exposures`, `own_exposure`, `max_abs_other_style`, `exposures_published`, `readback_published`, `checks`, `sum_weight` or `holdings_truncated`, and `holdings: []` | live |

Weekly rows (`data.returns[F][]` and `data.measurement_twins[T].returns[F][]`):

| Field | Type | Notes | Source |
|---|---|---|---|
| `week_start`, `formation_date` | str (date) | The week's Monday and its first session | live |
| `week_end_session` | str? | The week's last session; null on a twin row that could not form | live |
| `week_return` | float? | **Fraction**; null unless `status` is `ok` or `degraded` | live |
| `status` | str | `ok`, `degraded` (shown, excluded from inference), `unavailable`, `no_holdings`; the vocabulary also has `shares_not_recorded`, `return_not_yet_realised` | live |
| `state` | str | `ok`; `infeasible` (no_holdings); twins: `insufficient`, `degraded` | live |
| `return_status` | str | `ok`, `no_holdings`, `return_unavailable_low_coverage` (us), `return_unavailable_whole_market_gap` (cn); twins: `s3b_cell_below_min` (us, jp), `s3b_low_session_coverage` (us), `s3b_no_formation_universe` and `s3b_whole_panel_gap_day` (cn, live only: cn and jp fixtures omit the twins) | live |
| `status_label` | str | = `labels.status[status]` | live |
| `in_inference` | bool | True only for `ok` | live |
| `carried_weight_share`, `invalid_weight_share`, `exit_weight_share`, `exit_state` | float?, str? | As in the portfolio record. Degraded = the three shares add up to more than 5 % | live |
| `degraded_rule`, `degraded_rule_label`, `degraded_rule_source`, `*_max` | str, null | As in the portfolio record | live |
| `measurement_basis` | str | `investable_at_entry` | live |
| `return_basis`, `return_basis_label` | str | | live |
| `in_holdout` | null | | live |
| `exit_label` | str | **Optional**: only on rows with `exit_state: exit_unwitnessed` (us, jp; none in cn) | live |

### `GET /api/v1/markets/{market}/factor-portfolios/meta` → `factor_portfolios_meta_{m}.json`

Schema `surgeflow.factor_portfolios_meta.v2` (source
`/api/{market}/three-model/meta`), no query. Publication metadata for the same
books. `tools/mock_api.py` maps the path to `factor_portfolios_meta_{m}.json`.
us, cn and jp are `available`; hk is `empty` with its market caveats.

| Field | Type | Notes | Source |
|---|---|---|---|
| `data.market`, `contract`, `status` | str | `available` / `empty` | live |
| `data.reason_code`, `message` | str? | Null when available; hk: `no_publication_for_market` and a placeholder message (the live wording is not copied) | live |
| `data.models` | dict | `portfolios{state (published), first_formation, last_formation, n_publications, latest{...publication}, holdout_start, holdout_rule, open_week, formation_panel}`, `pick{state: not_published}`, `product{state: not_published}` | live |
| `data.publications[]`, `n_publications`, `publication` | list, int, dict | Publication records (keys as `data.publication` above) | live |
| `data.universe` | dict | `rule, computed_as_of, as_of_date, n_in_universe, n_evaluated, measured_state` | live |
| `data.holdout{portfolios{start, rule}}`, `holdout_label` | dict, str | | live |
| `data.cost_basis` | list[str] | `["gross_of_costs"]` | live |
| `data.cost_label` | str | Quote it for the cost basis (placeholder wording in the fixture) | live |
| `data.model_versions` | dict | `A` (str), `C`, `B` (null) | live |
| `data.admission`, `filter_admitted`, `open_week` | null | | live |
| `data.data_through_session` | str (date) | | live |
| `data.served_tables` | list[str] | | live |
| `data.freshness` | dict | `portfolios{latest_formation_date, latest_week_start, current_week_start, weeks_behind, state}` (the same block as the portfolios payload), `pick: null`, `product: null` | live |
| `data.formation_panel`, `measurement`, `survivorship`, `served_caveats` | | As in the portfolios payload | live |
| `data.market_caveats` | dict? | Null for us, cn, jp; hk: `{ruling, label, items[str]}`. Only the shape is kept: the fixture `ruling`, `label` and six `items` are generic placeholders unrelated to the live list | live |
| `data.contract_revision` | str | | live |
| `data.return_basis` | dict | `state (declared), basis, label, returns_label, twin_returns_label, publications[{publication_id, state, basis, sources{...}}], ruling, rule`. hk: `state: no_portfolios_published`, nulls, `publications: []` | live |
| `data.degraded_rule` | dict | `state, rule, rule_ruling, text, label, terms, threshold, publications[{publication_id, state, rule, sources{...}, checks_degraded_weeks}], ruling, mechanism, shares_note, declaration_keys[]`. hk: nulls | live |
| `data.labels` | dict | `candidates, cost, timing, returns, status{...}, degraded_rule, degraded_rule_label, universe`; hk: only `status` (`ok`, `degraded` null), `degraded_rule`, `degraded_rule_label` (null) | live |
| `data.cache` | dict | | live |

The `sources` dicts use dotted key names (`receipt_json.return_basis_declared`);
read them with `["..."]`, not with `dig`.

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

- `news` and `summary` failed in the first snapshot and answered in the
  refreshed one. Call them with `sf_try` and skip the section when it returns
  `None`.
- `/api/v1/me` returns personal fields. Display only `plan`, `scopes`,
  `rate_limit` and `usage`.
- `records(payload, "whales")` is always `[]` (the boards are a dict), and
  `RESPONSE_SHAPES` has no `summary` entry.
- `show_freshness` cannot see the freshness of:
  - ml_clusters (`data.run`);
  - whales (`data.as_of`);
  - factor portfolios (`data.freshness.state` and `weeks_behind`, and
    `data.publication`; empty state: `data.status`, `data.message`);
  - macro (`data.data.last_checked_utc`);
  - bond ETFs (per-row dates).

  Print those fields explicitly.
- Units differ between fields:
  - fractions: screen `change_pct`, `ma*_excess`, `ep/bp/sp`,
    `dividend_yield`, sector means, `crowdedness_pct`, factor
    `week_return`, the factor `*_weight_share` fields and holding `weight`;
  - percents: `intraday_return_pct`, `*_portfolio_pct`,
    bond `*_pct`, `expense_ratio`;
  - ratios: `turnover_vs_10d`, `projected_vs_yesterday`;
  - local currency: screen and realtime money fields;
  - USD: `market_cap_usd`, hotlist `*_usd`, bond `aum`.
- Per-ticker ML cluster labels exist only for representatives, anomalies and
  switchers.
