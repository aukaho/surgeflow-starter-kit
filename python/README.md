# surgeflow Python client

`surgeflow` 0.1.0 reads SurgeFlow public snapshots and two member research endpoints.
It requires Python 3.9 or later and uses `requests` as its only runtime dependency.

The package is not yet on PyPI. Install it from this local folder:

```bash
python -m pip install ./python
```

## Public snapshots

```python
from surgeflow import SurgeFlow

client = SurgeFlow(timeout=30)
freshness = client.data_freshness()
hotlist = client.momentum_hotlist("us")
macro = client.macro_indicators()
news = client.news_sentiment(days=30)
factors = client.factor_overview("us")
hotlist_csv = client.momentum_hotlist("us", response_format="csv")
```

Public methods return decoded JSON objects by default. Use `response_format="csv"` to receive CSV text.
Market arguments accept `us`, `cn`, `jp`, or `hk`. The `days` argument accepts 1 through 365.

Use `public_snapshot(snapshot_id, market=None, days=None, response_format="json")` for the generic snapshot method.
The [public OpenAPI document](https://surgeflows.capital/api/public/openapi.json) defines the live contract.

## Member methods

Create a key on the [account page](https://surgeflows.capital/account).
Pass the key directly to each member method:

```python
from surgeflow import SurgeFlow

client = SurgeFlow()
key = "sf_live_REPLACE_WITH_YOUR_KEY"
plan = client.member_me(key)
hotlist = client.member_hotlist("us", key)
```

These methods call:

```text
GET /api/v1/me
GET /api/v1/markets/{market}/hotlist
```

The [member API catalogue](https://surgeflows.capital/api/v1/catalog) defines the live member contract.
The member beta allows 2,000 requests per day and 180 requests per minute for each key.

## Errors and timeouts

The default timeout is 30 seconds. Set `timeout` in seconds when constructing the client.

- `SurgeFlowTimeoutError` identifies a timeout.
- `SurgeFlowConnectionError` identifies a transport failure.
- `SurgeFlowApiError` identifies a non-success HTTP status and includes `status_code` and `payload`.
- `SurgeFlowResponseError` identifies invalid JSON or a response with `ok=false`.
- `SurgeFlowError` is the base class for these errors.

Every request uses the `surgeflow-python/0.1.0` user agent.

## Test

Install `pytest`, then run from this folder:

```bash
PYTHONPATH=src python -m pytest
```

Tests use recorded public fixtures and a fake session. They make no network requests.

Research data only, not investment advice. Free access does not grant redistribution rights.
