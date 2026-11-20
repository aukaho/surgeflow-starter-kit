# SurgeFlow examples

All public examples use the four supported markets: `us`, `cn`, `jp`, and `hk`.
They need no API key.

- `curl/public.sh` reads JSON and CSV public snapshots with cURL.
- `python/public.py` uses `requests` and optionally loads CSV with `pandas`.
- `javascript/public.mjs` uses `fetch` in Node 18 or later.
- `google-sheets/formula.txt` contains an `IMPORTDATA` formula for a public CSV snapshot.

Run the public examples from the repository root:

```bash
bash examples/curl/public.sh
python examples/python/public.py
node examples/javascript/public.mjs
```

The member cURL example needs a real key in `SURGEFLOW_API_KEY`.
It calls only `GET /api/v1/me` and `GET /api/v1/markets/us/hotlist`.

```bash
export SURGEFLOW_API_KEY="sf_live_REPLACE_WITH_YOUR_KEY"
bash examples/curl/member.sh
```

Never commit a real key. Public data is research data only, and free access grants no redistribution rights.
