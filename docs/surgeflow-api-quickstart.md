# SurgeFlow API Quickstart

Status: public API beta.

## What happens next

After downloading this guide, create a free beta key from the Extension page.

1. Open `https://surgeflows.capital/extension`.
2. Enter name and email.
3. Agree to the terms.
4. Copy the key when it appears.
5. Save the key locally as `SURGEFLOW_API_KEY`.
6. Call `/api/v1/me` to confirm the key works.
7. Pull one market endpoint, usually `realtime` first.
8. Use the returned rows in Google Sheets, Python, JavaScript, or a dashboard.

Use this base URL for authenticated API calls:

```text
https://stock-api-c4qdowjxva-uc.a.run.app
```

Do not send authenticated `GET /api/v1/*` calls through `https://surgeflows.capital` until the Cloudflare bypass and purge for `/api/v1/*` is finished.

## Auth

Each beta user receives a unique key:

```text
Authorization: Bearer sf_live_...
```

SurgeFlow stores only the key hash. Save the key when it is issued.

## Free beta limits

- 250 requests per day per key
- 50 requests per minute per key
- Read-only market research endpoints

## First endpoints

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

## cURL

```bash
export SURGEFLOW_API_KEY="sf_live_..."

curl "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/health"

curl -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/me"

curl -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/markets/us/realtime?limit=25"
```

## Response shape

`screen` returns rows at the top level:

```js
payload.rows
```

`realtime` and `hotlist` wrap the add-in contract under `data`:

```js
payload.data.rows
```

## JavaScript

```js
const baseUrl = "https://stock-api-c4qdowjxva-uc.a.run.app";
const response = await fetch(`${baseUrl}/api/v1/markets/us/hotlist?limit=25`, {
  headers: {
    Authorization: `Bearer ${process.env.SURGEFLOW_API_KEY}`,
  },
});

if (!response.ok) {
  throw new Error(await response.text());
}

const payload = await response.json();
console.log(payload.data.rows);
```

## Python

```python
import os
import requests

base_url = "https://stock-api-c4qdowjxva-uc.a.run.app"
headers = {"Authorization": f"Bearer {os.environ['SURGEFLOW_API_KEY']}"}

response = requests.get(
    f"{base_url}/api/v1/markets/us/screen",
    headers=headers,
    params={"page": 1, "page_size": 25},
    timeout=30,
)
response.raise_for_status()
payload = response.json()
print(payload["rows"])
```

## Support

Email `support@surgeflows.capital`.
