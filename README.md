# SurgeFlow Starter Kit

Public beta templates for SurgeFlow market research in Google Sheets and the SurgeFlow Public API v1.

SurgeFlow covers common stocks across the US, China, Japan, Hong Kong, India, and the UK. This starter kit helps beta users get from zero to a working market monitor without touching private brokerage data or spreadsheet contents.

## What Is Included

- `templates/surgeflow-google-sheets-starter.xlsx` - starter workbook with dashboard, sample `Surgeflow_US` output, and API endpoint map.
- `docs/surgeflow-api-quickstart.md` - compact API guide with auth, limits, endpoints, and examples.
- `apps-script/Code.gs` and `apps-script/Sidebar.html` - Google Sheets add-on source for the submitted SurgeFlow Realtime add-on.

## Website Downloads

- Extension page: https://surgeflows.capital/extension
- Google Sheets page: https://surgeflows.capital/extension/google-sheets
- Starter workbook: https://surgeflows.capital/templates/surgeflow-google-sheets-starter.xlsx
- API quickstart: https://surgeflows.capital/templates/surgeflow-api-quickstart.txt
- Starter ZIP: https://surgeflows.capital/templates/surgeflow-starter-kit.zip

## API Beta

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

Do not send authenticated `GET /api/v1/*` calls through `https://surgeflows.capital` yet. Use the direct Cloud Run API base above until Cloudflare bypasses and purges `/api/v1/*`.

## Support

Email: support@surgeflows.capital

## Disclaimer

SurgeFlow is research software. This starter kit and API are for educational and research use only. They are not investment advice, broker-dealer services, order routing, portfolio management, or a recommendation to buy or sell securities.
