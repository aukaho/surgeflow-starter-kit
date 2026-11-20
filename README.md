# SurgeFlow Starter Kit

Examples, clients, and app sources for SurgeFlow research data.

SurgeFlow covers four equity markets: the United States (`us`), China (`cn`), Japan (`jp`), and Hong Kong (`hk`).
The API provides research data only, not investment advice.

## Start without a key

Read public research snapshots as JSON or CSV. No API key is required.

```bash
curl "https://surgeflows.capital/api/public/snapshots/momentum-hotlist.json?market=us"
```

Public snapshots cover momentum Hotlist samples, macro indicators, news sentiment, factor overviews, and data freshness.
Data can be delayed or historical. Free access does not grant redistribution rights.

Use these resources:

- [Public manifest](https://surgeflows.capital/api/public/manifest.json)
- [OpenAPI 3.1 document](https://surgeflows.capital/api/public/openapi.json), the authoritative public contract
- [API documentation](https://surgeflows.capital/membership/api)
- [Postman collection](https://surgeflows.capital/data/surgeflow.postman_collection.json)
- [Member API catalogue](https://surgeflows.capital/api/v1/catalog)
- [llms.txt](https://surgeflows.capital/llms.txt)
- [Quickstart](docs/surgeflow-api-quickstart.md)

## Create a member API key

1. Join or sign in to SurgeFlow.
2. Open the [account page](https://surgeflows.capital/account).
3. Create a key and copy it when it appears.
4. Store the key privately because SurgeFlow cannot display the full key again.

The member beta allows 2,000 requests per day and 180 requests per minute for each key.
Member endpoints provide read-only market research data.

Send the key as a bearer token:

```bash
curl \
  -H "Authorization: Bearer sf_live_REPLACE_WITH_YOUR_KEY" \
  "https://surgeflows.capital/api/v1/markets/us/hotlist"
```

Use `us`, `cn`, `jp`, or `hk` in member market paths.
The [member API catalogue](https://surgeflows.capital/api/v1/catalog) is authoritative for member endpoints and plans.

## Install and run

### Examples

The [examples](examples/) include cURL, Python, JavaScript, and Google Sheets versions.

```bash
bash examples/curl/public.sh
python examples/python/public.py
node examples/javascript/public.mjs
```

The Python example requires `requests`. It uses `pandas` when that optional package is installed.
The JavaScript example requires Node 18 or later.

### Python client

Install the local `surgeflow` package:

```bash
python -m pip install ./python
```

See the [Python client guide](python/README.md). The package is not yet on PyPI.

### JavaScript client

Install the local `surgeflow` package:

```bash
npm install ./javascript
```

See the [JavaScript client guide](javascript/README.md). The package is not yet on npm.

### Google Sheets add-on

Install the source as a bound script by following [these steps](apps/google-sheets-add-on/README.md).
A public CSV snapshot also works with `IMPORTDATA` and needs no add-on.

### Excel add-in

Sideload the hosted manifest by following [these steps](apps/excel-add-in/README.md).
The site serves the panel files.

### Chrome extension

Load the unpacked extension by following [these steps](apps/chrome-extension/README.md).

These three app products are not yet in their stores.

## Data dates and limits

Check the source date, market, currency, and measurement window in each response.
Historical, factor, and valuation datasets follow their disclosed source cadence.
A current-session board is not a live-tick feed across every market.

The app sources show only SurgeFlow tickers and ranks, data freshness, and official open-licence macro statistics with credits. These official statistics can include economies beyond the four equity markets (for example the United Kingdom, Taiwan, and World Bank country series), each with its publisher credit.
They show no prices, returns, or company names.

## Support

Email [support@surgeflows.capital](mailto:support@surgeflows.capital) or open an issue.

## Licence and disclaimer

Code is available under the [MIT licence](LICENSE).

SurgeFlow is research software. This starter kit and API provide research data only.
They do not provide investment advice, broker-dealer services, order routing, portfolio management, or securities recommendations.
