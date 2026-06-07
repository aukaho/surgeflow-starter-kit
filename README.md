# SurgeFlow Templates

Public beta templates for SurgeFlow market research in Google Sheets and the SurgeFlow Public API v1.

SurgeFlow covers common stocks across the US, China, Japan, Hong Kong, India, and the UK. These files help beta users get from zero to a working market monitor without touching private brokerage data or spreadsheet contents.

## What Is Included

- `templates/surgeflow-google-sheets-starter.xlsx` - starter workbook with dashboard, sample `Surgeflow_US` output, and API endpoint map.
- `docs/surgeflow-api-quickstart.md` - beginner guide that starts with the no-code website preview, then offers Sheets, Colab, and developer paths.
- `notebooks/surgeflow-realtime-hotlist-60s.ipynb` - Google Colab notebook source that prompts for an API key and displays realtime + hotlist tables with 60-second refresh. No local Python install required.
- `apps-script/appsscript.json`, `apps-script/Code.gs`, and `apps-script/Sidebar.html` - Google Sheets add-on source for the submitted SurgeFlow Realtime add-on.

## Website Downloads

- Extension page: https://surgeflows.capital/extension
- Google Sheets page: https://surgeflows.capital/extension/google-sheets
- Starter workbook: https://surgeflows.capital/templates/surgeflow-google-sheets-starter.xlsx
- API quickstart: https://surgeflows.capital/templates/surgeflow-api-quickstart.txt
- Open notebook in Colab: https://colab.research.google.com/github/aukaho/surgeflow-starter-kit/blob/main/notebooks/surgeflow-realtime-hotlist-60s.ipynb

## API Beta

Create a free beta key from the Extension page:

```text
https://surgeflows.capital/extension
```

The form asks only for name, email, and terms agreement. The key appears once, then users can test realtime and hotlist tables directly on the Extension page.

Use the direct API base URL for authenticated calls:

```text
https://stock-api-c4qdowjxva-uc.a.run.app
```

Send your issued key as:

```text
Authorization: Bearer sf_live_...
```

First release endpoints:

```text
GET /api/v1/health
GET /api/v1/catalog
POST /api/v1/keys
GET /api/v1/me
GET /api/v1/summary
GET /api/v1/markets/{market}/screen
GET /api/v1/markets/{market}/realtime
GET /api/v1/markets/{market}/hotlist
```

Markets: `us`, `cn`, `jp`, `hk`, `uk`, `in`.

Free beta limits:

- 250 requests per day per key
- 50 requests per minute per key
- Read-only market research endpoints

## Google Sheets Beta

The Google Sheets add-on has been submitted for Google review. After approval, users will install it from Google Workspace Marketplace and refresh market sheets directly from the spreadsheet menu.

Until then, the starter workbook shows the expected sheet layout and output shape.

## Important Release Note

Use the direct Cloud Run API base above for external scripts, notebooks, and third-party browser apps. The `https://surgeflows.capital/api/v1/*` proxy is for same-origin SurgeFlow website pages.

## Support

Email: support@surgeflows.capital

## Disclaimer

SurgeFlow is research software. These templates and the API are for educational and research use only. They are not investment advice, broker-dealer services, order routing, portfolio management, or a recommendation to buy or sell securities.
