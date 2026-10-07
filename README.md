# SurgeFlow Starter Kit

Google Colab notebooks and examples for the free SurgeFlow Public API v1. They
take you from a free API key to clean tables, honest charts and basic machine
learning on four equity markets: the United States (`us`), China (`cn`), Japan
(`jp`) and Hong Kong (`hk`). You need no brokerage credentials and no private
spreadsheet data, and Colab needs nothing installed.

[Create a free API key and run the first example](https://surgeflows.capital/membership?utm_source=github&utm_medium=referral&utm_campaign=github_colab_quickstart_v1&utm_content=readme_hero#api-key)

## Start here

1. Create a free key and store it as a Colab secret: see
   [Your API key](#your-api-key).
2. Make one call to check the key. The
   [API quickstart](docs/surgeflow-api-quickstart.md#get-apiv1me) has cURL and
   Python examples for `GET /api/v1/me`.
3. Open the
   [60-second quick start](notebooks/surgeflow-realtime-hotlist-60s.ipynb) in
   Colab, then work through notebooks 00 to 05 in the
   [notebook series](#notebook-series).

Working in Google Sheets instead? See [Google Sheets beta](#google-sheets-beta).
The Sheets wrapper needs no API key.

## Your API key

1. Create a free key at https://surgeflows.capital/membership#api-key. Enter
   your email, agree to the terms (a name is optional) and copy the key. It
   starts with `sf_live_` and is shown once. SurgeFlow stores only its hash and
   cannot display it again.
2. In Colab, open **Secrets** (the key icon in the left sidebar), add a secret
   named `SURGEFLOW_API_KEY` with your key as the value, and switch on notebook
   access.
3. Run the notebook. It looks for the key in this order: the
   `SURGEFLOW_API_KEY` environment variable, the `SURGEFLOW_API_KEY` Colab
   secret, then a hidden prompt. The key is never printed or saved to disk.

Never paste the key into a code cell, a screenshot or a commit.

## Notebook series

Start with the 60-second quick start, then work through 00 to 05 in order.
Together they teach all 13 authenticated endpoints. Each endpoint gets the
call, a freshness check, cleaning, a chart and a "how to read this" note.

| Order | Notebook | Endpoints | What you learn | Open |
|---|---|---|---|---|
| Quick start | [`surgeflow-realtime-hotlist-60s`](notebooks/surgeflow-realtime-hotlist-60s.ipynb) | `me`, `realtime`, `hotlist` | Check your key, then load a current-session turnover board and momentum hotlist that refresh every 60 s | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/aukaho/surgeflow-starter-kit/blob/main/notebooks/surgeflow-realtime-hotlist-60s.ipynb) |
| 00 | [Setup and account](notebooks/00-setup-and-account.ipynb) | `health`, `catalog` (both open), `me`, `summary` | Store the key as a Colab secret, read per-market health and freshness, check your plan, scopes and usage | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/aukaho/surgeflow-starter-kit/blob/main/notebooks/00-setup-and-account.ipynb) |
| 01 | [Market boards](notebooks/01-market-boards.ipynb) | `screen` (paged), `realtime`, `hotlist`, `sector` | Page through the largest companies safely, keep fraction and percent returns apart, clean types and heavy tails, read the session boards (empty hotlists included) and the sector map | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/aukaho/surgeflow-starter-kit/blob/main/notebooks/01-market-boards.ipynb) |
| 02 | [ML market map and whales](notebooks/02-ml-map-and-whales.ipynb) | `ml/clusters`, `whales` | Read style clusters and anomaly scores, fund-holding signal boards and disclosure lags | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/aukaho/surgeflow-starter-kit/blob/main/notebooks/02-ml-map-and-whales.ipynb) |
| 03 | [News, notes, macro and bonds](notebooks/03-news-notes-macro-bonds.ipynb) | `news`, `notes/daily`, `macro/calendar`, `bond/etfs` | Clean text, use query filters, scale macro surprises, read credit spreads | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/aukaho/surgeflow-starter-kit/blob/main/notebooks/03-news-notes-macro-bonds.ipynb) |
| 04 | [Factor portfolios](notebooks/04-factor-portfolios.ipynb) | `factor-portfolios` | Signed weights, publication gates (a factor can be withheld), and risk and tail statistics rebuilt from the return series | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/aukaho/surgeflow-starter-kit/blob/main/notebooks/04-factor-portfolios.ipynb) |
| 05 | [ML lab](notebooks/05-ml-lab.ipynb) | `screen`, `realtime`, `whales`, `ml/clusters`, `factor-portfolios` | Cleaning, cross-sectional regression, PCA on style features (plus factor returns when published), and clustering compared with SurgeFlow's own clusters | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/aukaho/surgeflow-starter-kit/blob/main/notebooks/05-ml-lab.ipynb) |

Each notebook in the 00-05 series stays under about 80 requests and prints
how many it used. The quick start makes 3 requests, then 2 per refresh (9 with
the default three refreshes), and also prints its count.

## Endpoints by notebook

Base URL for scripts and notebooks: `https://stock-api-c4qdowjxva-uc.a.run.app`.
Send the key as `Authorization: Bearer sf_live_...`. `{market}` is one of
`us`, `cn`, `jp`, `hk`.

```text
00 Setup and account
   GET /api/v1/health                              open, no key
   GET /api/v1/catalog                             open, no key
   GET /api/v1/me
   GET /api/v1/summary
01 Market boards
   GET /api/v1/markets/{market}/screen             paged: page, page_size (max 100), sort=market_cap_usd
   GET /api/v1/markets/{market}/realtime           limit (max 100)
   GET /api/v1/markets/{market}/hotlist
   GET /api/v1/markets/{market}/sector
02 ML market map and whales
   GET /api/v1/markets/{market}/ml/clusters
   GET /api/v1/markets/{market}/whales
03 News, notes, macro and bonds
   GET /api/v1/markets/{market}/news               ticker, sentiment, limit (max 50)
   GET /api/v1/notes/daily                         market, as_of_date
   GET /api/v1/macro/calendar                      market, days (max 60)
   GET /api/v1/bond/etfs
04 Factor portfolios
   GET /api/v1/markets/{market}/factor-portfolios
05 ML lab
   reuses screen, realtime, whales, ml/clusters and factor-portfolios
```

The AI research committee is paused. Its two endpoints, `/api/v1/ai/ratings`
and `/api/v1/ai/grade-book`, are retired and answer HTTP 410.

A board can come back empty, for example while a market is closed. The
notebooks then print the API's `data_quality` and `stale_reason` instead of a
table. Two endpoints can fail even with a valid key:
`summary` can answer HTTP 500, and `news` can report an error inside an HTTP
200 answer (`"data": {"ok": false, "error": ...}`). The notebooks skip those
sections with a note and carry on. `/api/v1/me` also returns personal account
fields, so the notebooks show only your plan, scopes, rate limit and usage.

The membership form uses the open `POST /api/v1/keys` endpoint. Create keys on
the website. For parameters, response shapes, and cURL and Python examples for
every endpoint, see [`docs/surgeflow-api-quickstart.md`](docs/surgeflow-api-quickstart.md).

Free beta limits: 2,000 requests per day and 180 per minute per key, read-only.
The live catalogue is authoritative for endpoints, plans and limits:
https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/catalog

## What is in this repository

- `notebooks/`: the series above and the 60-second quick start, all committed
  without outputs.
- `docs/surgeflow-api-quickstart.md`: a reference for each endpoint.
  `docs/surgeflow-api-quickstart.txt` is a short plain-text quickstart based
  on the website's version and kept in line with this kit.
- `apps-script/`: the Google Sheets wrapper source (`appsscript.json`,
  `Code.gs`, `Sidebar.html`) for `us`, `cn`, `jp` and `hk`.
- `templates/README.md`: where to download the Google Sheets starter
  workbook. The workbook is hosted on the website, not in this repository.
- `kit/`, `tools/`, `tests/fixtures/`: the shared helper cell, the build and
  test tools, and synthetic offline fixtures (see "For contributors").

## Website downloads

- Membership and API key: https://surgeflows.capital/membership#api-key
- Google Sheets guide: https://surgeflows.capital/membership/google-sheets
- Starter workbook (website only): https://surgeflows.capital/templates/surgeflow-google-sheets-starter.xlsx
- Plain-text API quickstart: https://surgeflows.capital/templates/surgeflow-api-quickstart.txt

## Google Sheets beta

The Google Sheets add-on has been submitted for Google review. You cannot
install it from the Google Workspace Marketplace yet.

Until then, add the Apps Script source in `apps-script/` to a Google Sheets
copy of the starter workbook, or use the Colab notebooks.
[Use it today](apps-script/README.md#use-it-today) has the steps. No API key
is needed: the wrapper reads the keyless `/api/addin/realtime` and
`/api/addin/hotlist` contract for `us`, `cn`, `jp` and `hk`. Maintainer steps
for resubmission are in [`apps-script/README.md`](apps-script/README.md).

## For contributors

Read [CONTRIBUTING.md](CONTRIBUTING.md) first. Edit the sources in
`notebooks/src/*.py`. The built `.ipynb` files are generated, so do not edit
them by hand. The exception is the quick start, which is edited directly.

```bash
pip install -r requirements.txt
python tools/build_notebooks.py 01-market-boards                # build one notebook
python tools/build_notebooks.py --check                         # built files up to date?
python tools/run_notebooks.py --mock                            # offline run on tests/fixtures; must print PASS
SURGEFLOW_API_KEY=sf_live_... python tools/probe_endpoints.py   # save live snapshots, compare shapes with the fixtures
python tools/run_notebooks.py --mock --fixtures tests/fixtures/live   # replay the live snapshots; no API calls
SURGEFLOW_API_KEY=sf_live_... python tools/run_notebooks.py --live
```

The fixtures in `tests/fixtures/` copy the structure of live responses but
hold synthetic values. Only `catalog.json` and `health.json` are real. See
`tests/fixtures/README.md` for the field reference.

**Live-snapshot mode.** `tools/probe_endpoints.py` saves every live response
to `tests/fixtures/live/` (about 50 requests). After that,
`python tools/run_notebooks.py --mock --fixtures tests/fixtures/live` runs the
notebooks on those real snapshots with zero API calls, so you can re-run as
often as you like. It replays the saved responses: real values, that day's
empty boards and withheld factors, and the `news` error nested inside an HTTP
200, which the synthetic fixtures replace with an inferred success shape.

The replay is not exact in four ways:

- A response that was not JSON (the `summary` HTTP 500 page) is served as
  HTTP 200 with a `{"_non_json": "..."}` placeholder, so `sf_get` returns it
  instead of raising.
- `?market=` on `/macro/calendar` and `/notes/daily` returns the saved
  default response: the US calendar and the all-markets notes. The probe saves
  only the default response for these two endpoints, so code that asks them
  for `cn`, `jp` or `hk` has not been checked against live shapes for those
  markets.
- Only screen pages 1 to 3 are saved. Page 4 and later come back with
  `rows: []` even though `total_pages` is larger, so a run with
  `SCREEN_PAGES` above 3 stops after page 3 without saying why.
- Other query parameters (`limit`, `sort`, `page_size`, `ticker`,
  `sentiment`, `days`) are ignored: realtime always returns the saved 50 rows,
  whatever `limit` asks for.

Executed copies go to `build/executed/<name>.mock-live.ipynb`.
`tests/fixtures/live/` and `build/` are git-ignored. Never commit them: the
snapshots contain your account fields and member-only content.

## Release note

SurgeFlow covers four markets: `us`, `cn`, `jp` and `hk`. Use the direct Cloud
Run API base above for scripts and notebooks. The website proxy is reserved for
same-origin SurgeFlow pages. Endpoint names such as `realtime` describe the
current-session board. SurgeFlow does not claim a live-tick feed for any of the
four markets. Historical, factor and valuation datasets are daily or follow
their disclosed source cadence. Check the freshness fields in every response.

## Support

Email: support@surgeflows.capital

## Disclaimer

SurgeFlow is research software. This starter kit and API are for educational
and research use only. They are not investment advice, broker-dealer services,
order routing, portfolio management, or a recommendation to buy or sell
securities.
