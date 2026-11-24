# surgeflow JavaScript client

`surgeflow` 0.1.0 reads SurgeFlow public snapshots and two member research endpoints.
It requires Node 18 or later, uses ESM, includes types, and has no runtime dependencies.

The package is not yet on npm. Install it from this local folder:

```bash
npm install ./javascript
```

## Public snapshots

```javascript
import { SurgeFlow } from "surgeflow";

const client = new SurgeFlow({ timeout: 30000 });
const freshness = await client.dataFreshness();
const hotlist = await client.momentumHotlist("us");
const macro = await client.macroIndicators();
const news = await client.newsSentiment(30);
const factors = await client.factorOverview("us");
const hotlistCsv = await client.momentumHotlist("us", { responseFormat: "csv" });
```

Public methods return decoded JSON objects by default. Use `{ responseFormat: "csv" }` to receive CSV text.
Market arguments accept `us`, `cn`, `jp`, or `hk`. The `days` argument accepts 1 through 365.
The factor overview is a **frozen baseline (data to 11 April 2026, not updated daily)**.
For current daily factor data, use keyless `GET https://surgeflows.capital/api/factor-reference/latest`.

Use `publicSnapshot(snapshotId, { market, days, responseFormat })` for the generic snapshot method.
The [public OpenAPI document](https://surgeflows.capital/api/public/openapi.json) defines the live contract.

## Member methods

Create a key on the [account page](https://surgeflows.capital/account).
Pass the key directly to each member method:

```javascript
import { SurgeFlow } from "surgeflow";

const client = new SurgeFlow();
const key = "sf_live_REPLACE_WITH_YOUR_KEY";
const plan = await client.memberMe(key);
const hotlist = await client.memberHotlist("us", key);
```

These methods call:

```text
GET /api/v1/me
GET /api/v1/markets/{market}/hotlist
```

The [member API catalogue](https://surgeflows.capital/api/v1/catalog) defines the live member contract.
The member beta allows 2,000 requests per day and 180 requests per minute for each key.

## Errors and timeouts

The default timeout is 30,000 milliseconds. Set `timeout` in milliseconds when constructing the client.

- `SurgeFlowTimeoutError` identifies a timeout.
- `SurgeFlowNetworkError` identifies a transport failure.
- `SurgeFlowApiError` identifies a non-success HTTP status and includes `statusCode` and `payload`.
- `SurgeFlowResponseError` identifies invalid JSON or a response with `ok=false`.
- `SurgeFlowError` is the base class for these errors.

Every request uses the `surgeflow-javascript/0.1.0` user agent.

## Test

Run from this folder:

```bash
npm test
```

Tests use recorded public fixtures and injected `fetch` functions. They make no network requests.

Research data only, not investment advice. Free access does not grant redistribution rights.
