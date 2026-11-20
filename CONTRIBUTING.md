# Contributing

Issues and focused pull requests are welcome.

Use the [public OpenAPI document](https://surgeflows.capital/api/public/openapi.json) for public API changes.
Use the [member API catalogue](https://surgeflows.capital/api/v1/catalog) for member API changes.

Never include API keys, account details, tokens, or `.env` files.
Use `sf_live_REPLACE_WITH_YOUR_KEY` in examples.

Run the Python and JavaScript tests before proposing client changes.
Do not use network requests in tests. Add or update recorded fixtures when the contract changes.

Keep the four supported market codes: `us`, `cn`, `jp`, and `hk`.
All data is research data only, not investment advice.
