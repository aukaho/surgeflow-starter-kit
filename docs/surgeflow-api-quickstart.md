# SurgeFlow API Quickstart

Status: public API beta.

Use this base URL for authenticated API calls:

```text
https://stock-api-c4qdowjxva-uc.a.run.app
```

Do not send authenticated `GET /api/v1/*` calls through `https://surgeflows.capital` until the Cloudflare bypass and purge for `/api/v1/*` is finished.

## Auth

Each beta member should receive a unique key:

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

curl -H "Authorization: Bearer ${SURGEFLOW_API_KEY}" \
  "https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/markets/us/realtime?limit=25"
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

const data = await response.json();
console.log(data.rows);
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
    params={"limit": 25},
    timeout=30,
)
response.raise_for_status()
print(response.json()["rows"])
```

## Support

Email `support@surgeflows.capital`.
