# SurgeFlow Starter Kit

Working examples for the free SurgeFlow Public API v1 and Google Sheets.

The member API covers equity research data across eight markets: the US,
China, Japan, Hong Kong, Taiwan, Korea, the UK, and India. These files take a
new user from a free membership to a current market table without brokerage
credentials or access to private spreadsheet data.

[Create a free API key and run the first example](https://surgeflows.capital/membership?utm_source=github&utm_medium=referral&utm_campaign=github_colab_quickstart_v1&utm_content=readme_hero#api-key)

## What Is Included

- `templates/surgeflow-google-sheets-starter.xlsx` - a starter workbook with a
  dashboard, sample `Surgeflow_US` output, and API endpoint map.
- `docs/surgeflow-api-quickstart.md` - a beginner guide for the website,
  Sheets, Colab, cURL, and Python paths.
- `notebooks/surgeflow-realtime-hotlist-60s.ipynb` - a browser-based Colab
  notebook for the current-session turnover board and momentum hotlist. It
  supports all eight API markets and never saves the key to disk.
- `apps-script/appsscript.json`, `apps-script/Code.gs`, and
  `apps-script/Sidebar.html` - the submitted Google Sheets wrapper source. Its
  current source covers all eight markets (`us`, `cn`, `jp`, `hk`, `tw`, `kr`,
  `uk`, `in`). The Marketplace listing remains under review; synchronize this
  source into the linked Apps Script project and re-test before resubmission.

## Website Downloads

- Membership and API key: https://surgeflows.capital/membership#api-key
- Google Sheets guide: https://surgeflows.capital/membership/google-sheets
- Starter workbook: https://surgeflows.capital/templates/surgeflow-google-sheets-starter.xlsx
- API quickstart: https://surgeflows.capital/templates/surgeflow-api-quickstart.txt
- Open notebook in Colab: https://colab.research.google.com/github/aukaho/surgeflow-starter-kit/blob/main/notebooks/surgeflow-realtime-hotlist-60s.ipynb

## API Beta

Create a free beta key from the Membership page:

```text
https://surgeflows.capital/membership#api-key
```

The form asks for an email address, terms agreement, and an optional name. The
key appears once. Store it privately: SurgeFlow stores only its hash and
cannot display the full key again.

Use the direct API base URL for authenticated calls:

```text
https://stock-api-c4qdowjxva-uc.a.run.app
```

Send your issued key as:

```text
Authorization: Bearer sf_live_...
```

Open endpoints:

```text
GET /api/v1/health
GET /api/v1/catalog
POST /api/v1/keys
```

Authenticated endpoint families:

```text
GET /api/v1/me
GET /api/v1/summary
GET /api/v1/markets/{market}/screen
GET /api/v1/markets/{market}/realtime
GET /api/v1/markets/{market}/hotlist
GET /api/v1/ai/ratings
GET /api/v1/ai/grade-book
GET /api/v1/markets/{market}/ml/clusters
GET /api/v1/markets/{market}/whales
GET /api/v1/markets/{market}/sector
GET /api/v1/markets/{market}/news
GET /api/v1/markets/{market}/factor-portfolios
GET /api/v1/notes/daily
GET /api/v1/macro/calendar
GET /api/v1/bond/etfs
```

Markets: `us`, `cn`, `jp`, `hk`, `tw`, `kr`, `uk`, `in`.

Free beta limits:

- 2,000 requests per day per key
- 180 requests per minute per key
- Read-only market research endpoints

The live catalogue is authoritative for endpoint and plan changes:

```text
https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/catalog
```

## Google Sheets Beta

The Google Sheets add-on has been submitted for Google review. It is not
currently installable from Google Workspace Marketplace.

Today, use the starter workbook with the included Apps Script source, or use
the Colab notebook. The current Sheets wrapper source and authenticated API
cover all eight markets. Synchronize the included source into the linked Apps
Script project and re-run the contract test before Marketplace resubmission.

## Important Release Note

Use the direct Cloud Run API base above for scripts and notebooks. Endpoint
names such as `realtime` describe the current-session board; SurgeFlow does
not claim a live-tick feed across all eight markets. Historical, factor, and
valuation datasets are daily or tied to their disclosed source cadence.

## Support

Email: support@surgeflows.capital

## Disclaimer

SurgeFlow is research software. This starter kit and API are for educational
and research use only. They are not investment advice, broker-dealer services,
order routing, portfolio management, or a recommendation to buy or sell
securities.
