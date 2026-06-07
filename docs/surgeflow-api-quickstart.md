# SurgeFlow Beginner Quickstart

Status: free public API beta.

Best first path: use the website. You do **not** need to install Python, Jupyter, VS Code, Postman, or any developer tool.

## First Successful Use

1. Open `https://surgeflows.capital/extension`.
2. Go to **Create your API key**.
3. Enter only your name and email.
4. Agree to the terms.
5. Click **Create key**.
6. Copy the key when it appears. It starts with `sf_live_`.
7. In the same panel, choose a market and click **Realtime** or **Hotlist**.
8. You should see a live table immediately.

That is the first successful API use. Nothing else is required.

## What The Key Can Access

- Realtime turnover tables
- Momentum hotlists
- Market screen rows
- Six markets: US, China, Japan, Hong Kong, UK, India

## Free Beta Limits

- 250 requests per day
- 50 requests per minute
- Read-only market research data

## Recommended Paths

### Path A: No Code, Today

Use the table preview on the Extension page after creating your key. This confirms the key works and shows the table shape.

### Path B: Google Sheets

After the Google Sheets add-on is approved in Google Workspace Marketplace, install it from Google Sheets and refresh tables from the spreadsheet menu. The add-on will not require you to understand APIs or JSON.

Current status page:

```text
https://surgeflows.capital/extension/google-sheets
```

### Path C: Google Colab, No Local Install

1. Open the notebook directly in Colab:
   `https://colab.research.google.com/github/aukaho/surgeflow-starter-kit/blob/main/notebooks/surgeflow-realtime-hotlist-60s.ipynb`
2. Run the cells from top to bottom.
3. Paste your `sf_live_` key when asked.

Colab runs in your browser. You do not need to install Python.

### Path D: Developers

Use the direct API base URL:

```text
https://stock-api-c4qdowjxva-uc.a.run.app
```

Authentication:

```text
Authorization: Bearer sf_live_...
```

First developer endpoints:

```text
GET /api/v1/health
GET /api/v1/me
GET /api/v1/summary
GET /api/v1/markets/{market}/screen
GET /api/v1/markets/{market}/realtime
GET /api/v1/markets/{market}/hotlist
```

Markets: `us`, `cn`, `jp`, `hk`, `uk`, `in`.

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
api_key = "sf_live_..."  # paste your key here only in a private notebook
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

`screen`:

```python
payload["rows"]
```

`realtime` and `hotlist`:

```python
payload["data"]["rows"]
```

## Important Safety Note

Keep your key private. If you share screenshots, hide or blur the key. SurgeFlow stores only the key hash and cannot show the full key again.

## Support

Email: support@surgeflows.capital
