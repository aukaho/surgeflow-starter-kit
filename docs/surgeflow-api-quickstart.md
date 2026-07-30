# SurgeFlow API Beginner Quickstart

Status: free public API beta.

Best first path: create a key on the website and run one read-only request.
You do **not** need to install Python, Jupyter, VS Code, Postman, or another
developer tool.

## First Successful Use

1. Open `https://surgeflows.capital/membership#api-key`.
2. Enter your email and optional name.
3. Agree to the terms.
4. Click **Create key**.
5. Copy the key when it appears. It starts with `sf_live_`.
6. Use the website preview or the Colab notebook to load a current-session
   turnover table or momentum hotlist.

The full key is displayed once. Keep it private.

## What The Key Can Access

The authenticated API currently exposes 15 read-only endpoint families:

- identity and plan metadata;
- market summaries and screens;
- current-session turnover boards and momentum hotlists;
- AI ratings and the AI grade book;
- ML clusters;
- whale, sector, news, factor-portfolio, Notes, macro-calendar, and bond-ETF
  research.

Markets: `us`, `cn`, `jp`, `hk`, `tw`, `kr`, `uk`, `in`.

The live catalogue is authoritative:

```text
https://surgeflows.capital/api/v1/catalog
```

## Free Beta Limits

- 2,000 requests per day per key
- 180 requests per minute per key
- read-only market research data

## Recommended Paths

### Path A: Website Preview

Create a key at `https://surgeflows.capital/membership#api-key`, then use the
preview to confirm that the key works and inspect the response shape.

### Path B: Google Colab

1. Open the notebook directly in Colab:
   `https://colab.research.google.com/github/aukaho/surgeflow-starter-kit/blob/main/notebooks/surgeflow-realtime-hotlist-60s.ipynb`
2. Run the cells from top to bottom.
3. Paste your `sf_live_` key when asked.
4. Select any of the eight supported markets.

Colab runs in your browser. You do not need to install Python.

### Path C: Google Sheets

The included Apps Script wrapper refreshes current-session and hotlist tables
for `us`, `cn`, `jp`, `hk`, `tw`, `kr`, `uk`, and `in`. The authenticated API
and Colab notebook support the same eight markets.

The Google Sheets add-on has been submitted for Google authentication and
Workspace Marketplace review. It is **not yet available for public one-click
installation**. Before resubmission, synchronize the included source into the
linked Apps Script project and re-run the eight-market contract test.

Current status:

```text
https://surgeflows.capital/membership/google-sheets
```

### Path D: Developers

API base URL:

```text
https://stock-api-c4qdowjxva-uc.a.run.app
```

Authentication:

```text
Authorization: Bearer sf_live_...
```

Authenticated endpoints:

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

Open utility endpoints:

```text
GET /api/v1/health
GET /api/v1/catalog
POST /api/v1/keys
```

## cURL Example

```bash
export SURGEFLOW_API_KEY="sf_live_..."

curl -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/me"

curl -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/markets/us/realtime?limit=25"
```

## Python Example

```python
import requests

base_url = "https://stock-api-c4qdowjxva-uc.a.run.app"
api_key = "sf_live_..."  # use only in a private notebook or environment variable
headers = {"Authorization": f"Bearer {api_key}"}

response = requests.get(
    f"{base_url}/api/v1/markets/us/hotlist",
    headers=headers,
    timeout=30,
)
response.raise_for_status()
payload = response.json()
rows = payload["data"]["rows"]
print(rows[:5])
```

## Response Shape

Most endpoint payloads include an `ok` flag, freshness metadata, and a
`data` object. The market screen is the legacy exception:

```python
screen_rows = payload["rows"]
realtime_or_hotlist_rows = payload["data"]["rows"]
```

## Data Boundary

Endpoint names such as `realtime` describe the current-session board. SurgeFlow
does not claim a live-tick feed across all eight markets. Historical, factor,
and fundamental outputs may be current to the last completed market session.
Inspect each response's freshness and evidence fields before use.

SurgeFlow is research software. It does not place orders and is not investment
advice.

## Support

`support@surgeflows.capital`
