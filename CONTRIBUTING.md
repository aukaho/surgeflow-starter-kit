# Contributing to the SurgeFlow Starter Kit

The notebooks teach every one of the 15 authenticated SurgeFlow API v1
endpoints, then go further: cleaning the data, visualising it, and applying
basic machine learning. These rules keep the series consistent.

## Layout

```text
kit/surgeflow_helpers.py      shared client + chart theme, copied into every notebook
notebooks/src/NN-name.py      notebook sources (edit these)
notebooks/NN-name.ipynb       built notebooks (generated - do not hand-edit)
tools/build_notebooks.py      sources -> .ipynb (adds the helper cell and Colab badge)
tools/run_notebooks.py        executes notebooks offline (--mock) or live (--live)
tools/mock_api.py             offline API stand-in serving tests/fixtures/*.json
tools/probe_endpoints.py      live shape check: compares the real API with the fixtures
tests/fixtures/               synthetic responses shaped like the live API
```

`notebooks/surgeflow-realtime-hotlist-60s.ipynb` is the original quick-start
and is edited directly.

## Workflow

```bash
pip install -r requirements.txt
python tools/build_notebooks.py 01-market-boards        # rebuild one notebook
python tools/run_notebooks.py --mock 01-market-boards   # must print PASS
python tools/build_notebooks.py --check                 # built files up to date?
SURGEFLOW_API_KEY=sf_live_... python tools/probe_endpoints.py   # live shapes vs fixtures
SURGEFLOW_API_KEY=sf_live_... python tools/run_notebooks.py --live
```

Commit notebooks **without outputs** (the builder produces them that way).

## Source format

```python
# %% [markdown]
# # Title
# Prose in Markdown, each line prefixed with "# ".

# %%
MARKET = "us"  # code cell

# %% [helpers]
```

`# %% [helpers]` becomes the shared helper cell. Every notebook uses it
exactly once, right after the "Connect" heading. Never copy helper code into
a notebook; change `kit/surgeflow_helpers.py` and rebuild all notebooks.

## Helper API (available after the helper cell)

| Name | Use |
|---|---|
| `sf_get(path, **params)` | GET an endpoint; spaced ~0.4 s apart, retries 429/5xx, raises `SurgeFlowError` |
| `records(payload, shape)` / `to_frame(payload, shape)` | main record list / DataFrame using `RESPONSE_SHAPES` |
| `dig(obj, *keys, default=None)` | safe nested lookup |
| `show_freshness(payload, label)` | prints as-of, market status, data quality - call it after every fetch |
| `api_calls_used()` | requests made this session |
| `MARKETS`, `MARKET_NAMES` | `("us", "cn", "jp", "hk")` |
| `MARKET_COLORS`, `SIDE_COLORS`, `SERIES`, `SEQUENTIAL`, `DIVERGING`, `INK`, `INK_2`, `MUTED`, `GRID` | chart colours |

The Plotly template `plotly_white+surgeflow` is the default.

## Notebook anatomy

1. Title, one-paragraph purpose, "What you will learn", and a table of the
   endpoints used (method, path, what it returns).
2. `## 1. Connect` with a short note on the key: an environment variable,
   then a Colab secret named `SURGEFLOW_API_KEY`, then a hidden prompt. Then
   `# %% [helpers]`.
3. A parameters cell (`MARKET = "us"`, limits) with comments listing the
   allowed values.
4. One section per endpoint with these parts, in order:
   - what the endpoint is for;
   - the call, with the path written out literally (`sf_get("/api/v1/markets/{MARKET}/whales")`);
   - `show_freshness`;
   - a raw preview (`df.head()`);
   - cleaning;
   - a chart;
   - "How to read this";
   - caveats.
5. Extensions (cleaning, visualisation, ML), clearly marked as going beyond
   the raw API.
6. `## Next steps`, then the footer: research and education only, not
   investment advice; `realtime` names a current-session board, not a
   live-tick feed; cadence varies by market.

## Data rules

- **Empty is normal.** A closed market, weekend or new day can return zero
  rows. Check for it and print a friendly sentence instead of crashing.
- **A missing field is a contract change.** Let it raise. Do not silently
  skip columns that the documented shape promises.
- Show cleaning explicitly; never hide it in a helper:
  - `pd.to_numeric(errors="coerce")`;
  - UTC datetime parsing;
  - de-duplication on the natural key;
  - quantile clipping (winsorising) for heavy tails;
  - `np.log1p` for turnover and market cap;
  - z-scores before distance-based ML;
  - an explicit, counted NaN policy.
- Budget: under about 3 minutes and 80 requests per notebook (free tier:
  2,000/day, 180/min). Print `api_calls_used()` at the end.
- Never print, log or save the API key.

## Chart rules (from the SurgeFlow chart theme)

- Plotly only. Pick the form by the data's job: magnitude, change over time,
  part-to-whole or relationship. Sometimes a stat line or table beats a chart.
- Colour follows the entity: markets always use `MARKET_COLORS`, long, short
  and hold always use `SIDE_COLORS`. Never colour by rank. Never use a
  rainbow or default continuous scale: sequential magnitude uses `SEQUENTIAL`
  (one hue) and signed values use `DIVERGING` (blue/red, grey midpoint at 0,
  symmetric range).
- No dual y-axes. Use two charts, facets, or an index to a common base.
- Scatter and bubble charts use at most 3 colours. With 4 markets, facet or
  add symbol as a second encoding.
- Every chart with 2 or more series has a legend. Label selectively, never
  every point.
- The title states the takeaway. Axis titles include units. Hover templates
  format numbers ($, %, B/M).
- Use a log axis for turnover, market cap and AUM.
- Keep a table twin: display the tidy DataFrame behind every chart.

## Machine-learning rules

- Cross-sectional and descriptive. Say plainly that a regression across
  today's stocks explains differences between them. It does not forecast
  returns or recommend trades.
- Fix `random_state`. Scale features inside a scikit-learn `Pipeline`.
  Evaluate with cross-validation or a hold-out split. Report robust (HC3)
  standard errors for OLS.
- PCA: standardise first, show the scree and cumulative explained variance,
  and interpret the loadings.
- Clustering: choose k with silhouette or elbow evidence, then compare with
  SurgeFlow's own `ml/clusters` using the adjusted Rand index.
