# %% [markdown]
# # 03 · ML market map and whales: clusters, anomalies and institutional holdings
#
# Two SurgeFlow endpoints describe the *structure* of a market rather than its
# daily moves. The **ML clusters** endpoint is a machine-learning map: it sorts
# the market's stocks into a handful of style groups, names each group by its
# strongest traits, flags the stocks that fit no group well, and reports how
# trustworthy the map is. The **whales** endpoint is a signal board built from
# fund holdings disclosures: which stocks the tracked funds agree on, bet big on,
# crowd into, bought or sold, and how the stocks connect through shared holders.
#
# Both are **descriptive**. The clusters say how stocks resemble each other
# today, not where prices go next. The whale boards describe filings that can be
# weeks or months old. This notebook shows you how to read each one, check its
# numbers and chart it honestly.
#
# **What you will learn**
#
# - How to unpack nested JSON (dictionaries inside records) into tidy tables,
#   and check that the parts add up to the totals the API reports.
# - How to read a cluster profile heatmap of robust z-scores, and why ML style
#   clusters cut across sectors.
# - How an anomaly score is built from two "unusualness" legs, and why we do not
#   winsorise the outliers we came to look at.
# - What silhouette, balance and the effective number of clusters say about a
#   clustering, and why the listed stocks that switched cluster are not a
#   random sample of all switchers.
# - Why the ML run's `stale` flag and `age_days` count calendar days, not
#   trading sessions, and how to check the run against the market's last
#   published session instead.
# - What consensus, conviction, crowdedness, position delta, network
#   centrality and owner-count change mean for fund holdings, and how to take a
#   composite score apart.
# - How to spot rows left over from an earlier computation run, and why mixing
#   runs breaks a ranking.
# - How disclosure lags work (US 13F filings come up to 45 days after each
#   quarter; Japan and Hong Kong use faster event-driven filings), and how to
#   date a whale signal before you use it.
# - How to build a holder → stock graph with `networkx`.
#
# **Endpoints used**
#
# | Method | Path | What it returns |
# |---|---|---|
# | GET | `/api/v1/markets/{market}/ml/clusters` | The latest ML clustering run: cluster profiles, sector mix, representative tickers, the anomaly watch list, the stocks that switched cluster, and stability diagnostics |
# | GET | `/api/v1/markets/{market}/whales` | The institutional-holdings signal board: six top-20 boards (`consensus`, `conviction`, `crowdedness`, `position_delta`, `network`, `ll_predictive`), the signal gate status, the tracked holder roster and, for the US only, filing-speed and shareholder-letter studies |
# | GET | `/api/v1/markets/{market}/screen` | Used only as a cross-check in section 4.4 (US only): the market caps of the largest companies, to test whether a reported position value is plausible |
# | GET | `/api/v1/health` | Used only as a cross-check in sections 3 and 5 (open, no key needed): each market's last published session (`markets.<market>.published_session_date`), to date the ML run in trading sessions rather than calendar days |
#
# Markets: `us`, `cn`, `jp`, `hk`. The notebook makes 3 requests (the two
# endpoints for your market, plus health) plus 6 for the four-market comparison
# in section 5 (9 in total), and for the US 3 more screen pages for the sanity
# check in section 4.4 (12; the free plan allows 2,000 a day). It runs in about a minute. The whale responses for Japan
# (about 5 MB) and Hong Kong (about 3 MB) are large because they list every
# tracked holder, so the first fetch can take a few seconds.
#
# **Words used in this notebook**
#
# | Word | Meaning |
# |---|---|
# | cluster | A group of stocks that look alike on many features at once (returns, risk, valuation, fundamentals, trading). An algorithm finds the groups; nobody assigns them by hand |
# | robust z-score | How far a value sits from the market's median stock, measured in interquartile ranges (IQR: the spread of the middle half of all stocks). +1 means one IQR above the typical stock |
# | anomaly | A stock that fits the map badly: far from the centre of its own cluster, or poorly described by the market's main patterns |
# | silhouette | A score from −1 to 1 for how cleanly the clusters separate. Higher is cleaner |
# | whale | A large investor (asset manager, insurer, bank, pension fund, or in Japan and Hong Kong any large shareholder) whose holdings are disclosed in public filings |
# | 13F | The quarterly US filing in which managers with at least $100 million in US-listed stocks list their long positions, due 45 days after quarter end |
# | consensus | Many tracked funds own the stock and give it a large weight |
# | conviction | At least one fund holds an unusually large position in it |
# | crowdedness | The share of funds that own it, out of `n_funds_total` (a count the API sends; it can be smaller than the roster of tracked holders) |
# | centrality | How connected a stock is in the web of shared holders |
# | run | One computation of a board. Every board row carries `updated_at`, the time its run wrote it |

# %% [markdown]
# ## 1. Connect
#
# You need a free SurgeFlow API key. It starts with `sf_live_`. Create one at
# https://surgeflows.capital/membership#api-key.
#
# The next cell looks for the key in three places, in this order:
#
# 1. an environment variable named `SURGEFLOW_API_KEY`;
# 2. a Colab secret named `SURGEFLOW_API_KEY` (key icon in Colab's left sidebar,
#    then allow notebook access);
# 3. a hidden prompt where you paste the key.
#
# The key is never printed or saved. The cell also defines the shared helpers
# (`sf_get`, `records`, `dig`, `show_freshness`, ...) and the chart theme. You
# can run it without reading it.

# %% [helpers]

# %% [markdown]
# ## 2. Parameters
#
# Change `MARKET` and run the notebook again to study another market.

# %%
MARKET = "us"            # one of "us", "cn", "jp", "hk"
COMPARE_MARKETS = True   # section 5 fetches the other three markets (6 more requests); False skips it
SECTOR_SLOTS = 7         # sector mix: name the 7 largest sectors and fold the rest into "Other sectors"
LABEL_TOP = 5            # scatter charts label at most this many points; hover shows the rest
CAP_CHECK_PAGES = 3      # US only: screen pages (100 largest companies each) for the check in 4.4; 0 skips it

# Facts the API does not send with these endpoints.
CURRENCY = {"us": "USD", "cn": "CNY", "jp": "JPY", "hk": "HKD"}
SYMBOL = {"USD": "$", "CNY": "CN¥", "JPY": "¥", "HKD": "HK$"}

assert MARKET in MARKETS, f"MARKET must be one of {MARKETS}"
CCY = CURRENCY[MARKET]
COLOR = MARKET_COLORS[MARKET]                      # this market's colour in every chart of the kit
TODAY = pd.Timestamp.now(tz="UTC").normalize()     # dates below are measured against today (UTC)
print(f"Studying {MARKET_NAMES[MARKET]} ({MARKET}); local currency {CCY}; today is {TODAY:%Y-%m-%d} UTC.")

# %% [markdown]
# A few small utilities keep the later cells short. They are plain code, so read
# them once:
#
# - `pick` keeps exactly the documented columns. If one is missing it raises a
#   `KeyError`: that means the API contract changed, and you want to know. An
#   empty list is normal, so it returns an empty table instead of crashing.
# - `money` and `big_number` turn `25968124707` into `$25.97B` or `25.97B`.
# - `wrap` breaks a long label over several lines, so axis labels stay narrow;
#   `plural` writes "1 day" but "3 days".
# - `feature_label` translates a feature code such as `ret_252d` into words
#   ("1-year return"), and `feature_family` says which group of features it
#   belongs to (returns, risk, price swings, attention, valuation,
#   fundamentals, size). Codes they do not know are shown as they are.
# - `SECTOR_COLORS` gives each of the data vendor's 11 sectors one fixed
#   colour, so a sector keeps its colour in every market and on every day.
#   None of them is a market colour or a pole of the blue/red diverging scale.
#   The order of the dictionary is also the order in which sectors stack.
# - `place_labels` positions point labels so they do not cover each other or
#   the points: for each label it tries a few spots around its point (above,
#   right, left, below, ...) and keeps the first free one.
# - `below_plot` gives the legend position that sits a fixed number of pixels
#   under the plot area, so a horizontal legend never covers the x-axis title,
#   however tall the chart is.
# - `session_check` compares an ML run's session date with the market's last
#   published session ("same", "older" or "newer"), and `explain_run` turns
#   the run's metadata and that check into a few plain sentences.

# %%
import json
import textwrap

import networkx as nx
from plotly.subplots import make_subplots

# The ML model's feature vocabulary (36 features live; these 33 can appear in a cluster's top features).
# code: (family, plain-English label, how to read a positive value)
FEATURES = {
    "ret_20d": ("Returns", "1-month return", ""),
    "ret_63d": ("Returns", "3-month return", ""),
    "ret_126d": ("Returns", "6-month return", ""),
    "ret_252d": ("Returns", "1-year return", ""),
    "rolling_sharpe_63": ("Returns", "Risk-adjusted return (3m)", "return per unit of volatility"),
    "distance_from_high_252": ("Returns", "Distance from 1y high", "+ = nearer the 1-year high"),
    "rv_20": ("Risk", "Volatility (1m)", ""),
    "rv_63": ("Risk", "Volatility (3m)", ""),
    "rv_252": ("Risk", "Volatility (1y)", ""),
    "downside_vol_63": ("Risk", "Downside volatility (3m)", ""),
    "vol_of_vol_63": ("Risk", "Volatility of volatility (3m)", ""),
    "residual_vol_252_d": ("Risk", "Stock-specific volatility (1y)", "volatility the market does not explain"),
    "max_drawdown_252": ("Risk", "Max drawdown (1y)", "+ = a shallower worst fall"),
    "beta_252_d": ("Risk", "Market beta (1y)", ""),
    "r2_252_d": ("Risk", "R² vs market (1y)", "+ = moves more in step with the market"),
    "pa_mfe_21d": ("Price swings", "Upside excursion (21d)", "largest rise within 21 days"),
    "pa_mae_21d": ("Price swings", "Downside excursion (21d)", "largest fall within 21 days; + = shallower"),
    "pa_edge_21d": ("Price swings", "Excursion edge (21d)", "+ = rises outweigh falls"),
    "pa_mfe_52w": ("Price swings", "Upside excursion (1y)", "largest rise within a year"),
    "pa_mae_52w": ("Price swings", "Downside excursion (1y)", "largest fall within a year; + = shallower"),
    "pa_edge_52w": ("Price swings", "Excursion edge (1y)", "+ = rises outweigh falls"),
    "turnover_to_mcap": ("Attention", "Turnover / market cap", "+ = more heavily traded"),
    "pa_sir_infectious": ("Attention", "Attention building (SIR)", "+ = attention is spreading now"),
    "pa_sir_recovered": ("Attention", "Attention spent (SIR)", "+ = a burst of attention has passed"),
    "val_ep_z": ("Valuation", "Earnings yield (E/P)", "+ = cheaper on earnings"),
    "val_bp_z": ("Valuation", "Book-to-price (B/P)", "+ = cheaper on book value"),
    "val_cfop_z": ("Valuation", "Cash-flow yield (CF/P)", "+ = cheaper on cash flow"),
    "profit_margin": ("Fundamentals", "Profit margin", ""),
    "revenue_growth": ("Fundamentals", "Revenue growth", ""),
    "ni_growth": ("Fundamentals", "Net income growth", ""),
    "cfo_growth": ("Fundamentals", "Operating cash-flow growth", ""),
    "leverage_debt_to_mcap": ("Fundamentals", "Debt / market cap", "+ = more leveraged"),
    "log_market_cap": ("Size", "Market cap (log)", "+ = larger company"),
}
FAMILY_ORDER = ["Returns", "Risk", "Price swings", "Attention", "Valuation", "Fundamentals", "Size", "Other"]

# One colour per vendor sector, keyed by name (colour follows the entity, never its size rank). The hues avoid
# MARKET_COLORS and the DIVERGING poles; in this stacking order every pair of neighbours stays distinct for
# colour-blind readers too. A sector not listed here is drawn in MUTED.
SECTOR_COLORS = {
    "Technology": "#4a3aa7", "Healthcare": "#e87ba4", "Financial Services": "#008300",
    "Consumer Cyclical": "#a83c8f", "Industrials": "#9a5a1c", "Communication Services": "#00939a",
    "Basic Materials": "#8f9a14", "Consumer Defensive": "#b08ae0", "Energy": "#3f5a10",
    "Real Estate": "#c45cc0", "Utilities": "#c0884a",
}


def pick(raw: pd.DataFrame, columns: list) -> pd.DataFrame:
    """Keep the documented columns. Empty is normal; a missing column raises KeyError."""
    if raw.empty:
        return pd.DataFrame(columns=columns)
    return raw[columns].copy()


def big_number(value, digits: int = 2) -> str:
    """1607749519 -> '1.61B'. Readable labels for share counts and other big numbers."""
    if pd.isna(value):
        return "n/a"
    sign, value = ("-" if value < 0 else ""), abs(float(value))
    for size, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= size:
            return f"{sign}{value / size:,.{digits}f}{unit}"
    return f"{sign}{value:,.0f}"


def money(value, ccy: str = "USD", digits: int = 2) -> str:
    """25968124707 -> '$25.97B' (a big number with its currency symbol)."""
    if pd.isna(value):
        return "n/a"
    text = big_number(value, digits)
    return f"-{SYMBOL[ccy]}{text[1:]}" if text.startswith("-") else f"{SYMBOL[ccy]}{text}"


def wrap(text: str, width: int = 30) -> str:
    """Break a long label into lines of at most `width` characters (Plotly uses <br> for a new line)."""
    return "<br>".join(textwrap.wrap(str(text), width)) or str(text)


def shorten(text: str, width: int = 26) -> str:
    """Cut a long name to `width` characters, with an ellipsis."""
    text = str(text)
    return text if len(text) <= width else text[: width - 1] + "…"


def feature_label(code: str) -> str:
    """Plain-English name for a feature code; unknown codes are shown as they are."""
    return FEATURES.get(code, ("Other", code, ""))[1]


def feature_family(code: str) -> str:
    """The group a feature belongs to (Returns, Risk, ...); 'Other' for codes this notebook does not know."""
    return FEATURES.get(code, ("Other", code, ""))[0]


def feature_note(code: str) -> str:
    """How to read the sign of a feature, when it is not obvious ('' otherwise)."""
    return FEATURES.get(code, ("Other", code, ""))[2]


def plural(n, word: str, many: str = None) -> str:
    """plural(1, 'day') -> '1 day'; plural(3, 'day') -> '3 days'."""
    n = int(n)
    return f"{n:,} {word if n == 1 else (many or word + 's')}"


def lower_first(text: str) -> str:
    """'Book-to-price (B/P)' -> 'book-to-price (B/P)', but 'AUM-weighted' stays as it is (mid-sentence use)."""
    text = str(text)
    return text[0].lower() + text[1:] if len(text) > 1 and text[1].islower() else text


def place_labels(x, y, labels, width: float = 760, height: float = 330, x_range=None, y_range=None) -> list:
    """Label positions that avoid other labels and points. `labels[i]` is None for points left unlabelled.

    Works in approximate pixels (the plot area is about `width` x `height`; pass the axis ranges when they
    differ from the data's). Returns, for each label, the keyword arguments for fig.add_annotation: an x/y
    shift in pixels and the matching text anchors.
    """
    x, y = np.asarray(x, float), np.asarray(y, float)
    x_lo, x_hi = x_range if x_range else (np.nanmin(x), np.nanmax(x))
    px = (x - x_lo) / ((x_hi - x_lo) or 1.0) * width
    y_lo, y_hi = y_range if y_range else (np.nanmin(y), np.nanmax(y))
    py = (y_hi - y) / ((y_hi - y_lo) or 1.0) * height                              # pixels grow downwards
    tries = [(0, -14), (12, 0), (-12, 0), (0, 14), (14, -18), (-14, -18), (14, 18), (-14, 18), (0, -34), (0, 34)]
    taken, placed = [], []
    for i, text in enumerate(labels):
        if text is None:
            continue
        w, h = 7.2 * len(str(text)) + 4, 15
        for dx, dy in tries:
            left = px[i] + dx - (w / 2 if dx == 0 else 0 if dx > 0 else w)
            top = py[i] + dy - (h / 2 if dy == 0 else h if dy < 0 else 0)
            box = (left, top, left + w, top + h)
            hits_label = any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in taken)
            hits_point = np.any((px > box[0] - 4) & (px < box[2] + 4) & (py > box[1] - 4) & (py < box[3] + 4))
            if not (hits_label or hits_point):
                break                                      # first free spot wins; otherwise keep the last try
        taken.append(box)
        placed.append(dict(index=i, text=str(text), xshift=dx, yshift=-dy, showarrow=False,
                           xanchor="center" if dx == 0 else "left" if dx > 0 else "right",
                           yanchor="middle" if dy == 0 else "bottom" if dy < 0 else "top"))
    return placed


def below_plot(height: float, top: float, bottom: float, px: float = 75) -> float:
    """Legend y (in paper units) that sits `px` pixels under the plot area of a figure `height` pixels tall."""
    return -px / max(height - top - bottom, 60)


def session_check(as_of, last_session):
    """'same', 'older' or 'newer': a run's session date against the market's last published session (None if unknown)."""
    run_day, last_day = pd.to_datetime(as_of, errors="coerce"), pd.to_datetime(last_session, errors="coerce")
    if pd.isna(run_day) or pd.isna(last_day):
        return None
    return "same" if run_day == last_day else "older" if run_day < last_day else "newer"


def explain_run(run: dict, market: str, last_session=None) -> None:
    """A few plain sentences about an ML run's date, age and coverage, checked against the last published session."""
    finished = pd.to_datetime(run["run_finished_at"], utc=True)
    flag = "flags it **stale**" if run["stale"] else "does not flag it stale"
    check = session_check(run["as_of_date"], last_session)
    if check == "same":
        dated = (f"That is the last session SurgeFlow has published for this market (health "
                 f"`published_session_date`: {last_session}), so the map is as recent as the market's data"
                 + ("; the flag reflects the calendar days since then (an exchange holiday, for example), not a "
                    "missing session." if run["stale"] else "."))
    elif check == "older":
        dated = (f"SurgeFlow has published a later session for this market ({last_session}, health "
                 "`published_session_date`), so this map is older than the market's latest data.")
    elif check == "newer":
        dated = (f"Health reports an earlier last session ({last_session}); check health before you rely on "
                 "either date.")
    else:
        dated = (f"Compare `as_of_date` with the market's last trading session (health "
                 f"`markets.{market}.published_session_date`) before you trust the flag.")
    display(Markdown(
        f"> The {MARKET_NAMES[market]} ML map describes the session of **{run['as_of_date']}** "
        f"({plural(run['age_days'], 'calendar day')} ago) and finished at {finished:%Y-%m-%d %H:%M} UTC. "
        f"SurgeFlow {flag}; `stale` and `age_days` count calendar days, not trading sessions. {dated} It clusters "
        f"{run['clustered_ticker_count']:,} of the {run['universe_ticker_count']:,} tickers in the universe "
        f"({run['eligible_count']:,} were eligible); on average a stock had {run['avg_coverage_ratio']:.0%} "
        "of the features."))

# %% [markdown]
# ## 3. ML clusters: the market map
#
# **What it is for.** Once a day per market, SurgeFlow describes every stock
# with about three dozen features: returns over several horizons, volatility
# and drawdown, price swings, valuation yields, growth, margins and leverage,
# size, and trading attention. It scales them, compresses them with PCA (principal component analysis, which
# keeps the main directions in which stocks differ), and groups the stocks with
# a **consensus** of three clustering algorithms (k-means, a Gaussian mixture
# and hierarchical clustering). The result is a map: which stocks behave alike
# right now. It is **cross-sectional and descriptive**: it describes how
# today's stocks differ from one another. It does not forecast returns and it
# does not recommend trades.
#
# The response has five parts:
#
# | Part | What it holds |
# |---|---|
# | `data.run` | When the run happened, how many stocks it covers, and quality scores (`run.quality`) |
# | `data.clusters` | One record per cluster: name, size, sector mix, top features, representative tickers |
# | `data.anomaly_watch` | Up to 40 stocks that fit the map worst |
# | `data.changed_group` | Up to 40 stocks that switched cluster since the previous run |
# | `data.model_notes` | Method, versions and guardrails |
#
# **Freshness lives in `data.run`.** `show_freshness` only finds `market`
# here, so we print the run's date, age and `stale` flag ourselves.
# `run.stale` and `run.age_days` count **calendar days**, not trading
# sessions. During an exchange holiday (China's National Day closure, 1-7
# October 2026, reopening on 8 October, for example) a correct run can be
# flagged stale. SurgeFlow calls this a labelling issue on its side; the data
# itself is correct. So do not trust the flag alone: we also read
# `/api/v1/health` once and compare `run.as_of_date` with the market's last
# published session, `markets.<market>.published_session_date`. When the two
# match, the map covers the market's latest session, whatever the flag says.
# **Empty is normal:** if a market has no run yet, `data.available` is
# `false`, and the cells below print a note instead of charts.

# %%
ml_payload = sf_get(f"/api/v1/markets/{MARKET}/ml/clusters")
show_freshness(ml_payload, "ML clusters:")
ml = ml_payload["data"]
ML_OK = bool(ml["available"])

# Each market's last published session: the yardstick for the run's date (the stale flag counts calendar days).
health_payload = sf_try("/api/v1/health")
LAST_SESSION = {m: dig(health_payload, "markets", m, "published_session_date") for m in MARKETS}
if health_payload is not None:
    show_freshness(health_payload, "Health:")
    print(f"Health built {pd.to_datetime(health_payload['timestamp'], utc=True):%Y-%m-%d %H:%M} UTC. "
          "Last published session per market: "
          + ", ".join(f"{m} {LAST_SESSION[m] or 'n/a'}" for m in MARKETS) + ".")

if ML_OK:
    run, quality, model_notes = ml["run"], ml["run"]["quality"], ml["model_notes"]
    explain_run(run, MARKET, LAST_SESSION[MARKET])
    print(f"Model {model_notes['cluster_model_version']} ({model_notes['estimator_count']} estimators); "
          f"{model_notes['feature_count'] or 'unreported number of'} features ({model_notes['feature_set_version']}).")
    display(Markdown(f"> *{model_notes['methodology']}*"))
else:
    run, quality, model_notes = {}, {}, {}
    display(Markdown(f"> No ML run is available for {MARKET_NAMES[MARKET]} yet "
                     f"({ml.get('message') or 'no message'}). The cells below print a note instead of charts."))

# %% [markdown]
# **Raw preview.** The clusters arrive as a list of records, but two columns
# hold whole dictionaries (`sector_mix`, `top_features`) and one holds a list
# (`representative_tickers`). We use `pd.DataFrame(records(...))` rather than
# the helper `to_frame` here: `to_frame` would spread each dictionary into
# dozens of mostly empty columns. We unpack them ourselves in the next step.

# %%
clusters_raw = pd.DataFrame(records(ml_payload, "ml_clusters"))
anomalies_raw = pd.DataFrame(records(ml_payload, "ml_anomalies"))
changed_raw = pd.DataFrame(ml["changed_group"] if ML_OK else [])
print(f"{len(clusters_raw)} clusters, {len(anomalies_raw)} anomaly-watch rows, "
      f"{len(changed_raw)} changed-group rows.")
clusters_raw.head()

# %% [markdown]
# ### Cleaning the clusters
#
# 1. **Keep the documented columns** (`pick` raises if one is missing).
# 2. **Treat `cluster_id` as a label, not a position.** The IDs are held stable
#    from run to run by membership overlap, so they skip numbers, and the
#    clusters arrive largest first rather than in ID order. We write them as
#    `#3` so that charts treat them as names, never as a 0..k−1 index.
# 3. **De-duplicate on `cluster_id`**, the natural key.
# 4. **Unpack the dictionaries into long tables**: one row per (cluster,
#    feature) and one row per (cluster, sector).
# 5. **Check the parts against the totals** the run reports. A failed check is
#    worth investigating before you read any chart.

# %%
CLUSTER_COLS = ["cluster_id", "cluster_name", "ticker_count", "sector_mix", "representative_tickers",
                "top_features", "jaccard_vs_prior", "membership_entrants", "membership_leavers"]

clusters = pick(clusters_raw, CLUSTER_COLS)
clusters["cluster_id"] = pd.to_numeric(clusters["cluster_id"], errors="coerce").astype("Int64")
clusters["ticker_count"] = pd.to_numeric(clusters["ticker_count"], errors="coerce")
n_before = len(clusters)
clusters = clusters.drop_duplicates(subset="cluster_id").reset_index(drop=True)
clusters["label"] = "#" + clusters["cluster_id"].astype(str)
clusters["share"] = clusters["ticker_count"] / clusters["ticker_count"].sum()
clusters["axis_label"] = ["<b>" + lab + "</b> " + wrap(name, 34)
                          for lab, name in zip(clusters["label"], clusters["cluster_name"])]
NAME = dict(zip(clusters["cluster_id"], clusters["cluster_name"]))       # id -> full name
LABEL = dict(zip(clusters["cluster_id"], clusters["label"]))             # id -> "#3"
TICK = dict(zip(clusters["cluster_id"], clusters["axis_label"]))         # id -> wrapped label for charts
print(f"De-duplication: {n_before} clusters -> {len(clusters)}. Cluster IDs in the order received: "
      f"{', '.join(clusters['label']) or 'none'}.")

features_long = pd.DataFrame(
    [{"cluster_id": cid, "feature": feature, "z": z, "rank_in_cluster": rank}
     for cid, feats in zip(clusters["cluster_id"], clusters["top_features"])
     for rank, (feature, z) in enumerate(feats.items(), start=1)],
    columns=["cluster_id", "feature", "z", "rank_in_cluster"])
features_long["z"] = pd.to_numeric(features_long["z"], errors="coerce")

sector_long = pd.DataFrame(
    [{"cluster_id": cid, "sector": sector, "names": n}
     for cid, mix in zip(clusters["cluster_id"], clusters["sector_mix"]) for sector, n in mix.items()],
    columns=["cluster_id", "sector", "names"])
sector_long["names"] = pd.to_numeric(sector_long["names"], errors="coerce")

print(f"Unpacked {len(features_long)} (cluster, feature) rows covering {features_long['feature'].nunique()} "
      f"distinct features, and {len(sector_long)} (cluster, sector) rows.")

checks = []
if ML_OK:
    sizes = sorted(clusters["ticker_count"].astype(int).tolist(), reverse=True)
    itemised = sector_long.groupby("cluster_id")["names"].sum().reindex(clusters["cluster_id"]).fillna(0)
    checks = [
        ("number of clusters = quality.k", quality["k"], len(clusters)),
        ("sum of ticker_count = run.clustered_ticker_count", run["clustered_ticker_count"],
         int(clusters["ticker_count"].sum())),
        ("ticker_count, largest first = quality.cluster_sizes", quality["cluster_sizes"], sizes),
        ("largest cluster share = quality.realized_max_cluster_share",
         round(quality["realized_max_cluster_share"], 3), round(float(clusters["share"].max()), 3)),
        ("sector_mix never exceeds ticker_count", True,
         bool((itemised.to_numpy() <= clusters["ticker_count"].to_numpy()).all())),
    ]
checks = pd.DataFrame(checks, columns=["check", "api", "ours"])
checks["ok"] = [a == b for a, b in zip(checks["api"], checks["ours"])]
if ML_OK:
    display(checks.astype({"api": str, "ours": str}).style.hide(axis="index"))
if not checks["ok"].all():
    print("Some checks failed: read the clusters with care and compare with the API documentation.")

# %% [markdown]
# **NaN policy for the sector mix.** `sector_mix` lists only each cluster's
# **six largest sectors**, so it adds up to less than `ticker_count`. We do not
# drop the difference. It becomes an explicit **"Not itemised"** bucket, so the
# bars in the next chart still add up to the true cluster sizes. A sector
# called `Unknown` (common in Japan) is a missing classification, not a
# sector, so it gets its own neutral **"Unclassified"** bucket and never takes
# a colour slot. Then we keep the `SECTOR_SLOTS` largest real sectors by name
# and fold the rest into "Other sectors", because more than about seven
# colours stop being readable. Size only decides *which* sectors are named; each
# named sector keeps its own colour from `SECTOR_COLORS`, whatever its rank.

# %%
NOT_ITEMISED, OTHER, UNCLASSIFIED = "Not itemised (outside top 6)", "Other sectors", "Unclassified"
clusters["not_itemised"] = (clusters["ticker_count"]
                            - sector_long.groupby("cluster_id")["names"].sum().reindex(clusters["cluster_id"])
                            .fillna(0).to_numpy())
total_names = clusters["ticker_count"].sum()
print(f"sector_mix itemises {total_names - clusters['not_itemised'].sum():,.0f} of {total_names:,.0f} names; "
      f"{clusters['not_itemised'].sum():,.0f} ({clusters['not_itemised'].sum() / max(total_names, 1):.0%}) "
      "become the 'Not itemised' bucket.")

is_unknown = sector_long["sector"].isna() | sector_long["sector"].astype(str).str.strip().isin(["", "Unknown"])
sector_totals = sector_long[~is_unknown].groupby("sector")["names"].sum().sort_values(ascending=False)
named = set(sector_totals.index[:SECTOR_SLOTS])                 # size picks which sectors get named ...
TOP_SECTORS = ([s for s in SECTOR_COLORS if s in named]          # ... the fixed palette order stacks them
               + sorted(named - set(SECTOR_COLORS)))
sector_long["sector_group"] = (sector_long["sector"].where(sector_long["sector"].isin(TOP_SECTORS), OTHER)
                               .mask(is_unknown, UNCLASSIFIED))
folded = sorted(set(sector_long.loc[~is_unknown, "sector"]) - set(TOP_SECTORS))
if TOP_SECTORS:
    print(f"Named sectors ({len(TOP_SECTORS)}): {', '.join(TOP_SECTORS)}.")
    print(f"Folded into '{OTHER}' ({len(folded)}): {', '.join(folded) if folded else 'none'}.")
print(f"Sector 'Unknown' (shown as '{UNCLASSIFIED}'): {sector_long.loc[is_unknown, 'names'].sum():,.0f} names.")

# %% [markdown]
# ### Chart: what makes each cluster different
#
# Each row is a cluster and each column is a feature. A cell shows the
# cluster's **mean robust z-score** on that feature: how far its average member
# sits from the market's median stock, measured in interquartile ranges (IQR).
# That is the scale SurgeFlow's model itself uses (its methodology note says
# "RobustScaler (median/IQR)"). Robust means the scale uses the median and the
# IQR instead of the mean and standard deviation, so a few extreme stocks cannot
# stretch it. For a bell-shaped feature one IQR is about 1.35 standard
# deviations.
#
# The API publishes only each cluster's **six strongest features**. A blank
# cell means "not among this cluster's top six", **not** zero. Columns are
# grouped into families (returns, risk, price swings, attention, valuation,
# fundamentals, size) so related features sit side by side. The colour scale
# is diverging (blue above the median, red below, grey at zero) and symmetric,
# so equal distances look equally strong.

# %%
if features_long.empty:
    display(Markdown("> No cluster profiles came back, so there is no heatmap."))
else:
    profile = (features_long.pivot(index="cluster_id", columns="feature", values="z")
               .reindex(clusters["cluster_id"]))
    # Columns: by family, then in the vocabulary's order (unknown codes last, alphabetically).
    vocab = list(FEATURES)
    feature_order = sorted(profile.columns, key=lambda f: (FAMILY_ORDER.index(feature_family(f)),
                                                           vocab.index(f) if f in vocab else len(vocab), f))
    profile = profile[feature_order]
    families = pd.Series([feature_family(f) for f in feature_order])

    abs_z = profile.abs().stack()
    R = max(1.0, float(np.ceil(abs_z.quantile(0.9) * 2) / 2))   # symmetric range, rounded up to 0.5
    n_saturated = int((abs_z > R).sum())
    step = 1 if R <= 4 else 2                                       # round colour-bar ticks
    ticks = np.arange(-np.floor(R / step) * step, np.floor(R / step) * step + step / 2, step)
    show_numbers = len(feature_order) <= 20          # with many features the cells get too narrow for text
    cell_text = [["" if pd.isna(v) or not show_numbers else f"{v:+.1f}" for v in row] for row in profile.to_numpy()]
    cell_hover = [[f"<b>{LABEL[cid]} {NAME[cid]}</b><br>{feature_label(f)} (<i>{f}</i>, {feature_family(f).lower()})"
                   + (f"<br><i>{feature_note(f)}</i>" if feature_note(f) else "") + "<br>"
                   + ("not in this cluster's top 6" if pd.isna(v) else f"mean robust z: {v:+.2f} IQR")
                   for f, v in zip(feature_order, row)] for cid, row in zip(profile.index, profile.to_numpy())]

    strongest = features_long.loc[features_long["z"].abs().idxmax()]
    longest = max(len(feature_label(f)) for f in feature_order)
    fig = go.Figure(go.Heatmap(
        z=profile.to_numpy(), x=[feature_label(f) for f in feature_order], y=[TICK[c] for c in profile.index],
        colorscale=DIVERGING, zmin=-R, zmax=R, zmid=0, xgap=2, ygap=2, hoverongaps=False,
        text=cell_text, texttemplate="%{text}", textfont=dict(size=10),
        customdata=cell_hover, hovertemplate="%{customdata}<extra></extra>",
        colorbar=dict(title=dict(text="Mean robust z (IQR)", side="right"), tickvals=ticks,
                      ticktext=[f"{v:+.0f}" if v else "0" for v in ticks], thickness=14, len=0.8,
                      outlinewidth=0)))
    # Family brackets above the columns, with a thin divider between families.
    col_px = 640 / max(len(feature_order), 1)                       # rough width of one column in pixels
    for fam, idx in families.groupby(families, sort=False).groups.items():
        lo, hi = min(idx), max(idx)
        text = fam if (hi - lo + 1) * col_px >= 7 * len(fam) else fam.replace(" ", "<br>")
        fig.add_annotation(x=(lo + hi) / 2, y=1.0, xref="x", yref="paper", yanchor="bottom", yshift=4,
                           text=f"<b>{text}</b>", showarrow=False, font=dict(size=11, color=INK_2))
        fig.add_shape(type="line", x0=lo - 0.4, x1=hi + 0.4, y0=1.0, y1=1.0, xref="x", yref="paper",
                      line=dict(color=AXIS, width=2))
        if lo > 0:
            fig.add_shape(type="line", x0=lo - 0.5, x1=lo - 0.5, y0=0, y1=1, xref="x", yref="paper",
                          line=dict(color=INK_2, width=1, dash="dot"))
    fig.update_xaxes(tickangle=-45, showgrid=False, ticks="", title_text=None)
    fig.update_yaxes(autorange="reversed", showgrid=False, ticks="", title_text=None)
    fig.update_layout(
        title=dict(text=f"Each {MARKET_NAMES[MARKET]} cluster has a signature: the sharpest is "
                        f"{LABEL[strongest['cluster_id']]} at {strongest['z']:+.1f} on "
                        f"{lower_first(feature_label(strongest['feature']))}",
                   subtitle=dict(text=f"Mean robust z-score (IQR units from the median stock) of each cluster's 6 "
                                      f"strongest features · blank = not in that cluster's top 6 · run "
                                      f"{run['as_of_date']}, {run['clustered_ticker_count']:,} stocks")),
        height=230 + 62 * len(profile) + 5 * longest,
        margin=dict(t=150, l=10, r=10, b=40 + 5 * longest), plot_bgcolor=SURFACE)
    fig.show()
    if not show_numbers:
        print(f"{len(feature_order)} features are too many to print values in the cells: hover, or read the table.")
    if n_saturated:
        print(f"{plural(n_saturated, 'cell')} exceed ±{R:g} and show at full colour; "
              "hover or the table gives the exact value.")

    twin = profile.rename(index=LABEL, columns=feature_label)
    twin.columns = pd.MultiIndex.from_arrays([families, twin.columns], names=["family", "feature"])
    twin.index.name = "cluster"
    display(twin.style.format("{:+.2f}", na_rep=""))

# %% [markdown]
# **How to read this.** Read across a row to see what defines a cluster: its
# coloured cells are its strongest traits, and the cluster's name strings the
# top ones together. Read down a column to see which clusters share a trait
# and which sit on opposite sides of it (blue against red). The family labels
# on top show what *kind* of trait it is: a cluster whose colour sits in the
# valuation block is a value or glamour group; one in the risk block is a
# calm or a jumpy group. Deep colours are large distances from the typical
# stock. For an average over hundreds of stocks, ±1 is already a strong tilt:
# for a bell-shaped feature about four stocks in five sit within ±1 IQR of the
# median on their own. The table below the chart holds the same numbers.
#
# **Caveats.**
#
# - A blank cell is unknown, not zero. The API publishes six features per
#   cluster, so you cannot compare two clusters on a feature that only one of
#   them lists.
# - The values are averages. A cluster can be "large cap" on average and still
#   hold some small companies.
# - Signs follow the feature, not good or bad: a positive z on max drawdown or
#   downside excursion means a **shallower** fall, and a positive z on a
#   valuation yield means **cheaper**. Hover over a cell for the reading.
# - "Excursions" are price-swing features: the largest rise and the largest
#   fall within a window, and the balance of the two ("edge"). The attention
#   features borrow the SIR model from epidemiology (susceptible → infectious →
#   recovered): "building" means interest in the stock is spreading now,
#   "spent" means a burst of interest has passed.
# - The model uses 36 features (`model_notes.feature_count`; China leaves it
#   null), several of which no other v1 endpoint carries. Codes this notebook
#   has no plain name for are shown as they are, in an "Other" family.

# %% [markdown]
# ### Chart: how big each cluster is, and which sectors it mixes
#
# Two panels share one row per cluster. The left panel is the cluster's size:
# its number of stocks, a magnitude. The right panel is a part-to-whole view:
# each bar is stretched to 100% of the cluster and split by sector, so a small
# cluster's mix is as easy to read as a large one's. Every sector keeps one
# fixed colour (`SECTOR_COLORS`) in every bar, in every market and on every day,
# so you can follow a sector down the chart.

# %%
if clusters.empty:
    display(Markdown("> No clusters came back, so there is no size chart."))
else:
    mix = (sector_long.groupby(["cluster_id", "sector_group"])["names"].sum().unstack(fill_value=0)
           .reindex(index=clusters["cluster_id"], fill_value=0))
    columns = [s for s in TOP_SECTORS + [OTHER, UNCLASSIFIED] if s in mix.columns]
    mix = mix[columns]
    mix[NOT_ITEMISED] = clusters.set_index("cluster_id")["not_itemised"]
    mix_share = mix.div(mix.sum(axis=1).where(lambda t: t > 0), axis=0)          # each row adds up to 100%
    sector_color = {**{s: SECTOR_COLORS.get(s, MUTED) for s in TOP_SECTORS}, OTHER: MUTED, UNCLASSIFIED: AXIS}

    # How concentrated is the most single-sector cluster? (Real sectors only; the top one is always itemised.)
    top_sector = (sector_long[~is_unknown].sort_values("names", ascending=False).drop_duplicates("cluster_id")
                  .set_index("cluster_id"))
    top_sector["share"] = top_sector["names"] / clusters.set_index("cluster_id")["ticker_count"]
    most = top_sector["share"].idxmax()
    big = clusters.loc[clusters["ticker_count"].idxmax()]
    rows_y = [TICK[c] for c in mix.index]

    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, column_widths=[0.3, 0.7], horizontal_spacing=0.03,
                        subplot_titles=("Size: stocks in the cluster", "Sector mix: share of the cluster's stocks"))
    fig.add_trace(go.Bar(
        y=rows_y, x=clusters["ticker_count"], orientation="h", marker=dict(color=COLOR), showlegend=False,
        text=[f"{n:,.0f} · {sh:.0%}" for n, sh in zip(clusters["ticker_count"], clusters["share"])],
        textposition="outside", cliponaxis=False, textfont=dict(size=11, color=INK_2),
        customdata=np.column_stack([clusters["label"], clusters["share"]]),
        hovertemplate="<b>%{customdata[0]}</b><br>%{x:,} stocks (%{customdata[1]:.1%} of all clustered)"
                      "<extra></extra>"), row=1, col=1)
    for col in mix.columns:
        style = (dict(color=GRID, pattern=dict(shape="/", fgcolor=AXIS, solidity=0.35))
                 if col == NOT_ITEMISED else dict(color=sector_color[col]))
        fig.add_trace(go.Bar(
            y=rows_y, x=mix_share[col], name=col, orientation="h", marker=style,
            customdata=np.column_stack([[LABEL[c] for c in mix.index], mix[col]]),
            hovertemplate=f"<b>%{{customdata[0]}}</b><br>{col}: %{{customdata[1]:,}} stocks (%{{x:.0%}})"
                          "<extra></extra>"), row=1, col=2)
    if top_sector.loc[most, "share"] >= 0.5:
        headline = (f"{LABEL[most]} is the most sector-bound cluster: {top_sector.loc[most, 'share']:.0%} of it "
                    f"is {top_sector.loc[most, 'sector']}")
    else:
        headline = (f"Clusters cut across sectors: no cluster is more than {top_sector['share'].max():.0%} "
                    "one sector")
    fig.update_xaxes(title_text="Stocks (count)", rangemode="tozero",
                     range=[0, float(clusters["ticker_count"].max()) * 1.6], row=1, col=1)
    fig.update_xaxes(title_text="Share of the cluster", range=[0, 1], tickformat=".0%", row=1, col=2)
    fig.update_yaxes(autorange="reversed", ticks="", title_text=None)
    height = 250 + 62 * len(clusters)
    fig.update_layout(
        title=dict(text=headline,
                   subtitle=dict(text=f"Largest cluster {big['label']}: {big['ticker_count']:,.0f} stocks "
                                      f"({big['share']:.0%}; the balance cap is {quality['balance_cap']:.0%}) · "
                                      f"{len(clusters)} clusters, {total_names:,.0f} stocks · "
                                      "each sector keeps one colour in every market")),
        barmode="stack", height=height, bargap=0.3,
        margin=dict(t=120, l=10, r=20, b=130),
        legend=dict(orientation="h", x=0, y=below_plot(height, 120, 130), yanchor="top", traceorder="normal"))
    fig.show()

    twin = mix.rename(index=LABEL)
    twin["total"] = twin.sum(axis=1)
    twin.index.name = "cluster"
    display(twin.style.format("{:,.0f}"))
    display(mix_share.rename(index=LABEL).rename_axis("cluster").style.format("{:.1%}"))

# %% [markdown]
# **How to read this.** In the left panel, longer bars are bigger clusters; the
# number at the end gives the count and the share of all clustered stocks. In
# the right panel every bar is one whole cluster, so wide coloured segments are
# the sectors that cluster draws on most, whatever its size. The hatched
# segment holds the members whose sectors the API did not itemise. The
# subtitle repeats the balance cap: SurgeFlow keeps every cluster below this
# share of the market, so one giant cluster cannot swallow the map. The two
# tables hold the counts and the shares.
#
# The headline measures how sector-bound the clusters are, and the usual lesson
# is that **style clusters are not sectors.** Two banks can land in different
# clusters (one cheap and calm, one volatile and heavily traded), and a cluster
# can hold technology, healthcare and industrial companies that currently
# behave alike.
#
# **Caveats.**
#
# - Sector names come from the data vendor's classification; a company's
#   sector does not change when its cluster does.
# - The "Not itemised" share grows with the number of sectors in a cluster;
#   it is a gap in the data, not a sector. "Unclassified" (grey) is the
#   vendor's `Unknown` sector: listed, but without a classification.
# - A small cluster's 100% bar rests on few stocks. Read its shares together
#   with its size in the left panel.

# %% [markdown]
# ### Representative tickers: the most typical members
#
# For each cluster the API lists **8 representative members**: typical
# examples of the cluster. (SurgeFlow does not document how it picks them; a
# common choice is the members nearest the cluster's centre.) They are the
# best examples to study when you want to understand what a cluster means.
# The table adds the cluster's three strongest traits.

# %%
if clusters.empty:
    display(Markdown("> No clusters came back, so there are no representative tickers."))
else:
    top3 = (features_long[features_long["rank_in_cluster"] <= 3]
            .assign(text=lambda d: d["feature"].map(feature_label) + " " + d["z"].map("{:+.1f}".format))
            .groupby("cluster_id")["text"].agg(" · ".join))
    representatives = pd.DataFrame({
        "cluster": clusters["label"], "name": clusters["cluster_name"], "stocks": clusters["ticker_count"],
        "share": clusters["share"], "strongest traits (mean robust z)": clusters["cluster_id"].map(top3),
        "representative tickers": clusters["representative_tickers"].map(", ".join),
    })
    display(representatives.style.format({"stocks": "{:,.0f}", "share": "{:.0%}"}).hide(axis="index"))

# %% [markdown]
# **How to use this table.** Pick a cluster, look up two or three of its
# representative tickers in the screen endpoint (notebook 01), and check that
# their numbers match the traits listed here. That is the quickest way to make
# a cluster's name concrete. Representatives are typical, not best: being typical
# says nothing about future returns.

# %% [markdown]
# ### Chart: the anomaly watch
#
# **What it is for.** Some stocks fit the map badly. SurgeFlow measures this
# with two "legs":
#
# - **PCA reconstruction error.** PCA describes every stock with a few main
#   patterns. A stock that those patterns cannot reproduce well is unusual in
#   an unusual way: a large error.
# - **Centroid distance.** The distance from the stock to the centre of its own
#   cluster. A stock far from its centre belongs to its group only loosely.
#
# The `anomaly_score` (0 to 1) blends the stock's percentile rank on the two
# legs half and half. A score of 0.99 means that, averaged over the two legs,
# the stock is more extreme than about 99% of the market. The watch list holds
# the most unusual stocks, sorted by score and capped at 40. `anomaly_total`
# (the same number as `model_notes.anomaly_count_p95`) counts every flagged
# stock; the "p95" in that name refers to a 95th-percentile cut-off.
#
# Because the score is a rank *within today's market*, every day has a top 40.
# To ask whether today is unusual as a whole, the run adds
# `quality.anomaly_intensity`: market-wide percentiles of both legs, and
# `pct_vs_trailing`, where today's 95th-percentile reconstruction error ranks
# among the recent runs (1.0 = the most turbulent day on record).
#
# **Cleaning.** The usual steps (documented columns, numbers, one row per
# ticker), plus two specific ones:
#
# - **NaN policy for coverage.** `coverage_ratio` is the share of features the
#   stock had. It is null throughout China, so we show "not reported" rather
#   than guess. `low_coverage` flags stocks with under 80% of their features:
#   a high score built on missing data deserves less trust. When the ratio is
#   not reported we do not read `low_coverage = false` as "fine": those stocks
#   form their own group, "coverage not reported".
# - `top_drivers` lists the four features with the largest absolute z-scores,
#   clipped to ±5. We turn it into readable text. When several drivers tie at
#   the top (often all four at the ±5 clip), no single one is "the" driver, so
#   we name them all.
#
# We deliberately **do not winsorise** here. Winsorising tames outliers, and
# the outliers are exactly what this list is for.

# %%
ANOMALY_COLS = ["ticker", "cluster_id", "cluster_name", "anomaly_score", "pca_reconstruction_error",
                "centroid_distance", "coverage_ratio", "low_coverage", "top_drivers"]
ANOMALY_NUM = ["anomaly_score", "pca_reconstruction_error", "centroid_distance", "coverage_ratio"]

anom = pick(anomalies_raw, ANOMALY_COLS)
anom["ticker"] = anom["ticker"].astype(str)
anom["cluster_id"] = pd.to_numeric(anom["cluster_id"], errors="coerce").astype("Int64")
missing_before = int(anom[ANOMALY_NUM].isna().sum().sum())
for col in ANOMALY_NUM:
    anom[col] = pd.to_numeric(anom[col], errors="coerce")
n_before = len(anom)
anom = anom.drop_duplicates(subset="ticker").sort_values("anomaly_score", ascending=False).reset_index(drop=True)
anom["low_coverage"] = anom["low_coverage"].astype(bool)
anom["coverage_text"] = anom["coverage_ratio"].map(lambda v: "not reported" if pd.isna(v) else f"{v:.0%}")
anom["drivers"] = anom["top_drivers"].map(
    lambda ds: ", ".join(f"{feature_label(d['feature'])} {d['z']:+.1f}" for d in ds))
anom["tied_drivers"] = anom["top_drivers"].map(        # every driver tied at the largest |z| (the clip is ±5)
    lambda ds: [d for d in ds if abs(d["z"]) >= max(abs(e["z"]) for e in ds) - 1e-9] if ds else [])
anom["cluster"] = anom["cluster_id"].map(LABEL)
anom["coverage_group"] = np.select(
    [anom["low_coverage"], anom["coverage_ratio"].isna()],
    ["Low coverage (< 80% of features)", "Coverage not reported"], default="Coverage ≥ 80% of features")

print(f"Anomaly watch: {n_before} rows -> {len(anom)} after de-duplication; "
      f"{int(anom[ANOMALY_NUM].isna().sum().sum()) - missing_before} values became NaN when coerced.")
print(f"coverage_ratio not reported for {int(anom['coverage_ratio'].isna().sum())} of {len(anom)} names; "
      f"{int(anom['low_coverage'].sum())} flagged low_coverage.")
n_tied = int((anom["tied_drivers"].map(len) > 1).sum())
print(f"{n_tied} of {len(anom)} stocks have two or more drivers tied at their largest |z| "
      f"({int((anom['tied_drivers'].map(len) == 4).sum())} with all four tied).")
if ML_OK:
    if len(anom) <= ml["anomaly_total"]:
        print(f"The list shows {len(anom)} of the {ml['anomaly_total']} flagged stocks (anomaly_total).")
    else:
        print(f"The list has {len(anom)} rows but anomaly_total is {ml['anomaly_total']}: some listed stocks sit "
              "below the flag threshold, so read the scores, not just membership of the list.")

# %%
if anom.empty:
    display(Markdown("> The anomaly watch list is empty: no stock stands out on this run."))
else:
    intensity = quality["anomaly_intensity"]
    beyond_both = int(((anom["pca_reconstruction_error"] > intensity["recon_p95"])
                       & (anom["centroid_distance"] > intensity["centroid_p95"])).sum())
    lead = anom.iloc[0]
    tied = lead["tied_drivers"]
    if len(tied) > 1:
        top_z = max(abs(d["z"]) for d in tied)
        lead_text = f"with {len(tied)} features tied at " + ("the ±5 clip" if top_z >= 5 - 1e-9
                                                             else f"|z| {top_z:.1f}")
        lead_note = "<br>tied drivers: " + ", ".join(f"{lower_first(feature_label(d['feature']))} {d['z']:+.1f}"
                                                     for d in tied)
    elif tied:
        lead_text = f"driven by {lower_first(feature_label(tied[0]['feature']))} {tied[0]['z']:+.1f}"
        lead_note = ""
    else:
        lead_text, lead_note = "(no drivers listed)", ""
    colorscale = [[i / (len(SEQUENTIAL) - 1), c] for i, c in enumerate(SEQUENTIAL)]
    cmin = float(np.floor(anom["anomaly_score"].min() * 20) / 20)

    fig = go.Figure()
    for name, symbol in [("Coverage ≥ 80% of features", "circle"),
                         ("Low coverage (< 80% of features)", "circle-open"),
                         ("Coverage not reported", "diamond")]:
        part = anom[anom["coverage_group"] == name]
        if part.empty:
            continue
        low = name.startswith("Low")
        fig.add_trace(go.Scatter(                     # one shared colour axis: one colour bar for every group
            x=part["centroid_distance"], y=part["pca_reconstruction_error"], mode="markers", name=name,
            marker=dict(size=13, symbol=symbol, color=part["anomaly_score"], coloraxis="coloraxis",
                        line=dict(width=1.5 if low else 1, color=INK_2 if low else AXIS)),
            customdata=part[["ticker", "cluster", "anomaly_score", "drivers", "coverage_text"]].to_numpy(),
            hovertemplate=("<b>%{customdata[0]}</b> in cluster %{customdata[1]}<br>Anomaly score: "
                           "%{customdata[2]:.3f}<br>Centroid distance: %{x:.2f}<br>Reconstruction error: "
                           "%{y:.3f}<br>Drivers (robust z): %{customdata[3]}<br>Coverage: %{customdata[4]}"
                           "<extra></extra>")))
    for value, kind, axis in [(intensity["centroid_median"], "median", "x"),
                              (intensity["centroid_p95"], "95th pct", "x"),
                              (intensity["recon_median"], "median", "y"),
                              (intensity["recon_p95"], "95th pct", "y")]:
        line = dict(color=MUTED if kind == "median" else INK_2, width=1, dash="dot" if kind == "median" else "dash")
        if axis == "x":
            fig.add_vline(x=value, line=line, annotation_text=f"market {kind}", annotation_position="top",
                          annotation_font=dict(size=10, color=INK_2))
        else:
            fig.add_hline(y=value, line=line, annotation_text=f"market {kind}", annotation_position="top left",
                          annotation_font=dict(size=10, color=INK_2))
    names = [t if i < LABEL_TOP else None for i, t in enumerate(anom["ticker"])]   # label selectively: top scores
    for spot in place_labels(anom["centroid_distance"], anom["pca_reconstruction_error"], names,
                             x_range=(0, anom["centroid_distance"].max() * 1.05),
                             y_range=(0, anom["pca_reconstruction_error"].max() * 1.05)):
        i = spot.pop("index")
        fig.add_annotation(x=anom["centroid_distance"].iloc[i], y=anom["pca_reconstruction_error"].iloc[i],
                           font=dict(size=11, color=INK), **spot)
    fig.update_xaxes(title_text="Distance to its own cluster centre (scaled-feature units)", rangemode="tozero")
    fig.update_yaxes(title_text="PCA reconstruction error (higher = worse fit)", rangemode="tozero")
    turbulence = intensity.get("pct_vs_trailing")
    day_note = ("" if turbulence is None else
                f" · today's market-wide level beats {turbulence:.0%} of the last {intensity['trailing_runs']} runs")
    fig.update_layout(
        title=dict(text=f"{lead['ticker']} fits the {MARKET_NAMES[MARKET]} map worst, {lead_text}",
                   subtitle=dict(text=f"{len(anom)} listed · {ml['anomaly_total']} flagged in all · {beyond_both} "
                                      "beyond the market's 95th percentile on both legs" + day_note
                                      + f"<br>colour = anomaly score {anom['anomaly_score'].min():.3f}-"
                                        f"{anom['anomaly_score'].max():.3f} · dotted = market median, dashed = "
                                        "market 95th percentile" + lead_note)),
        coloraxis=dict(colorscale=colorscale, cmin=cmin, cmax=1,
                       colorbar=dict(title=dict(text="Anomaly score", side="right"), tickformat=".2f", thickness=14,
                                     len=0.75, outlinewidth=0)),
        height=600, margin=dict(t=150 if lead_note else 130, b=110, r=40),
        legend=dict(orientation="h", x=0, y=-0.16, yanchor="top"))
    fig.show()

    display(anom[["ticker", "cluster", "anomaly_score", "centroid_distance", "pca_reconstruction_error",
                  "coverage_text", "drivers"]]
            .style.format({"anomaly_score": "{:.3f}", "centroid_distance": "{:.2f}",
                           "pca_reconstruction_error": "{:.3f}"}).hide(axis="index"))
    print(f"The two legs overlap: across the whole market their correlation is {intensity['legs_correlation']:+.2f} "
          "(legs_correlation), so the 50/50 blend is partly redundant.")

# %% [markdown]
# **How to read this.** Further right means further from the stock's own
# cluster centre; higher up means the market's main patterns describe the stock
# poorly. The dotted lines mark the typical stock (the median) and the dashed
# lines the 95th percentile of the whole market, both from the API's
# `anomaly_intensity`. Most points lie beyond at least one dashed line: that is
# what makes them unusual. Points beyond both are unusual on both counts.
# Darker points have higher scores; the colour bar on the right gives the
# scale (the range is narrow, because every listed stock is in the market's top
# few percent). Open circles have low feature coverage and diamonds have no
# reported coverage. The labels name the top scorers; hover over a point, or
# read the table (all listed stocks), for its drivers.
#
# **Caveats.**
#
# - An anomaly is a **description**, not a warning or a tip. A stock can be
#   unusual because of a takeover bid, a data error, a stock split or a genuine
#   change in its business. Check the drivers before you read anything into it.
# - The score is a **rank within today's market**. It does not compare one day
#   with another; `anomaly_intensity.pct_vs_trailing` does that for the market
#   as a whole.
# - Driver z-scores are clipped at ±5, so a +5.0 means "at least +5". When
#   several drivers sit at the clip, the data cannot say which one matters
#   most, so the headline names how many tie rather than picking one.
# - The two legs are measured in the model's own scaled units, so read them
#   against the market lines, not as absolute amounts.
# - The methodology note warns that the score is mildly anti-correlated with
#   feature completeness: stocks with missing features reconstruct worse. That
#   is why the chart draws low-coverage stocks as open circles; discount them.

# %% [markdown]
# ### Stability diagnostics: how far can you trust the map?
#
# A clustering always returns groups, even when the data has no real groups.
# The run's diagnostics tell you how solid this one is. They are **descriptive**:
# they say how clear today's structure is, not how well it predicts anything.
#
# - **Silhouette** (−1 to 1). For each stock, compare its average distance to
#   the members of its own cluster (a) with its average distance to the nearest
#   other cluster (b): `s = (b − a) / max(a, b)`. Near 1 the stock clearly
#   belongs; near 0 it sits on a border; below 0 it is closer to another
#   cluster. The run reports the average over all stocks, measured in the
#   model's own feature space. Stock features overlap heavily, so SurgeFlow's
#   own guidance puts cross-sectional equity maps at about 0.1 to 0.3: the
#   clusters are useful summaries, not sharp categories.
# - **k scan.** The run tries several numbers of clusters (k) and records the
#   silhouette and the largest cluster's share for each.
# - **Balance.** When it picks k, no cluster may hold more than `balance_cap`
#   of the stocks.
# - **Effective number of clusters** = exp(entropy of the cluster shares). With
#   k equal clusters it equals k; when one cluster dominates it drops towards 1.

# %%
if not ML_OK:
    display(Markdown("> No run, so there are no stability diagnostics."))
else:
    kscan = pick(pd.DataFrame(quality["k_scan"]), ["k", "silhouette", "max_share"])
    for col in kscan.columns:
        kscan[col] = pd.to_numeric(kscan[col], errors="coerce")
    kscan = kscan.drop_duplicates("k").sort_values("k").reset_index(drop=True)
    cap, k_chosen = quality["balance_cap"], quality["k"]
    kscan["within_cap"] = kscan["max_share"] <= cap
    best_any = int(kscan.loc[kscan["silhouette"].idxmax(), "k"])
    allowed = kscan[kscan["within_cap"]]
    best_cap = int(allowed.loc[allowed["silhouette"].idxmax(), "k"]) if not allowed.empty else None

    if best_cap is None:
        headline = f"No k in the scan keeps every cluster under the {cap:.0%} cap; the run chose k = {k_chosen}"
    elif best_cap == k_chosen:
        headline = (f"k = {k_chosen} gives the best-separated split among those that keep every cluster "
                    f"under the {cap:.0%} balance cap")
    else:
        headline = f"The run chose k = {k_chosen}; the best silhouette within the balance cap is at k = {best_cap}"
    note = ("" if best_any == best_cap else
            f" · k = {best_any} separates slightly better but breaks the cap")

    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.12,
                        subplot_titles=("Silhouette (higher = cleaner separation)",
                                        "Largest cluster's share of stocks"))
    fig.add_trace(go.Scatter(x=kscan["k"], y=kscan["silhouette"], mode="lines", showlegend=False,
                             line=dict(color=AXIS, width=1.5), hoverinfo="skip"), row=1, col=1)
    for ok, name, colour in [(True, "Within the balance cap", COLOR), (False, "Breaks the balance cap", MUTED)]:
        part = kscan[kscan["within_cap"] == ok]
        if part.empty:
            continue
        size = np.where(part["k"] == k_chosen, 17, 10)
        line = [2.5 if k == k_chosen else 1 for k in part["k"]]
        fig.add_trace(go.Scatter(
            x=part["k"], y=part["silhouette"], mode="markers", name=name, legendgroup=name,
            marker=dict(size=size, color=colour, line=dict(width=line, color=INK)),
            hovertemplate="k = %{x}<br>silhouette %{y:.4f}<extra></extra>"), row=1, col=1)
        fig.add_trace(go.Bar(
            x=part["k"], y=part["max_share"], name=name, legendgroup=name, showlegend=False,
            marker=dict(color=colour, line=dict(width=line, color=INK)),
            hovertemplate="k = %{x}<br>largest cluster: %{y:.1%} of stocks<extra></extra>"), row=1, col=2)
    fig.add_hline(y=cap, line=dict(color=INK_2, width=1, dash="dash"), row=1, col=2,
                  annotation_text=f"balance cap {cap:.0%}", annotation_position="top right",
                  annotation_font=dict(size=11, color=INK_2))
    fig.add_annotation(x=k_chosen, y=float(kscan.loc[kscan["k"] == k_chosen, "silhouette"].iloc[0]),
                       text=f"chosen k = {k_chosen}", showarrow=True, arrowhead=0, ax=0, ay=-34,
                       font=dict(size=11, color=INK), row=1, col=1)
    fig.update_xaxes(title_text="Number of clusters (k)", dtick=1)
    fig.update_yaxes(title_text="Mean silhouette", tickformat=".3f", row=1, col=1)
    fig.update_yaxes(title_text="Share of stocks", tickformat=".0%", rangemode="tozero",
                     range=[0, max(cap, kscan["max_share"].max()) * 1.15], row=1, col=2)
    fig.update_layout(
        title=dict(text=headline, subtitle=dict(
            text=f"Silhouette {quality['silhouette']:.3f} at the chosen k{note} · typical for equity maps: about "
                 "0.1-0.3 · left axis zoomed in")),
        height=470, margin=dict(t=120, b=130), legend=dict(orientation="h", x=0, y=-0.3, yanchor="top"))
    fig.show()
    display(kscan.style.format({"silhouette": "{:.4f}", "max_share": "{:.1%}"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** On the left, each dot is one candidate k; higher dots
# separate the stocks more cleanly. On the right, each bar shows how big the
# largest cluster would be at that k; grey bars break the balance cap (dashed
# line). The chosen k is outlined. The left panel's differences are often in
# the third decimal place: the silhouette barely changes with k, which is a
# reminder that the market has no single "true" number of groups. The scan's
# shares come from the selection step; the consensus partition the API serves
# is usually more balanced (its largest share is `realized_max_cluster_share`,
# checked in the table below).
#
# Next we recompute the balance numbers from the cluster sizes, and look for
# the fields that compare this run with the previous one:
#
# - `run.partition_stability` would compare the two partitions as a whole,
#   for example with the **ARI** (adjusted Rand index: 1 = identical, 0 = no
#   more alike than random labels);
# - `jaccard_vs_prior`, `membership_entrants` and `membership_leavers` would
#   do it per cluster (Jaccard = overlap of the member lists, 0 to 1).
#
# The API documents these fields, but they can be null even when
# `run.has_prior_comparison` is true. We report what is there and say so when
# it is not.

# %%
if ML_OK:
    shares = clusters["ticker_count"] / clusters["ticker_count"].sum()
    entropy = float(-(shares * np.log(shares)).sum())
    api = [quality["size_entropy"], quality["effective_clusters"], quality["realized_max_cluster_share"],
           quality["balance_cap_satisfied"], model_notes["avg_confidence"]]
    ours = [round(entropy, 4), round(float(np.exp(entropy)), 2), round(float(shares.max()), 4),
            bool(shares.max() <= quality["balance_cap"]), "n/a (needs per-stock data)"]
    # The API rounds its numbers (effective_clusters to 1 or 2 decimals), so we allow half of its last digit.
    tolerance = [5e-4, 0.05, 5e-4, None, None]
    ok = ["n/a" if isinstance(b, str) else bool(a == b) if t is None else bool(abs(float(a) - float(b)) <= t)
          for a, b, t in zip(api, ours, tolerance)]
    balance = pd.DataFrame({
        "metric": ["size entropy (nats)", "effective clusters = exp(entropy)", "largest cluster share",
                   "balance cap satisfied", "average assignment confidence"],
        "api": api, "recomputed": ours, "ok": ok})
    display(balance.astype({"api": str, "recomputed": str, "ok": str}).style.hide(axis="index"))
    evenness = np.exp(entropy) / len(clusters)
    shape = ("fairly even" if evenness >= 0.8 else "uneven: a few large clusters and a tail of small ones"
             if evenness >= 0.5 else "dominated by one large core plus a thin tail")
    print(f"With {len(clusters)} clusters, {np.exp(entropy):.1f} 'effective' clusters ({evenness:.0%} of k) means the "
          f"sizes are {shape}.")
    display(Markdown(f"> *SurgeFlow's reading guide (`quality.interpretation`):* {quality['interpretation']}"))

    stability = run["partition_stability"]
    per_cluster = ["jaccard_vs_prior", "membership_entrants", "membership_leavers"]
    if stability is None:
        print(f"run.partition_stability is null (has_prior_comparison = {run['has_prior_comparison']}): this run "
              "publishes no whole-partition comparison with the previous one.")
    else:
        display(pd.Series(stability, name="value").to_frame())
    if clusters[per_cluster].isna().all().all():
        print("Per-cluster jaccard_vs_prior, membership_entrants and membership_leavers are null as well. The "
              "switchers below (changed_group) are the only run-to-run comparison in this payload.")
    else:
        display(clusters[["label"] + per_cluster].style.hide(axis="index"))
    print(f"\n{model_notes['disclaimer']}")

# %% [markdown]
# ### Chart: which stocks switched cluster since the last run
#
# `model_notes.changed_count` is the number of stocks whose cluster changed
# since the previous run. `changed_group` lists up to 40 of them: where each
# came from, where it went, and the model's `cluster_confidence` in the new
# assignment (0 to 1).
#
# **Which 40?** SurgeFlow does not document how it picks them, and the list is
# not a random sample. In the live data it holds the switchers with the
# **highest anomaly scores**, in anomaly-score order: many of them are also on
# the anomaly watch above, with the same new cluster. The cleaning cell checks
# this for your run. When it holds, read the list as "the most unusual
# switchers", not as a picture of every switch.
#
# **Cleaning.** IDs become labels as before. **NaN policy:** `from_cluster_name`
# is null when the stock's old cluster is not part of today's map (the run
# dissolved or merged it). We fill the name from today's cluster table when
# the ID still exists, and write "(retired cluster)" otherwise, counting both.
# `anomaly_score` is joined from the anomaly watch; NaN means "not on the
# watch", not a score of zero.

# %%
CHANGED_COLS = ["ticker", "from_cluster_id", "from_cluster_name", "to_cluster_id", "to_cluster_name",
                "cluster_confidence", "days_in_cluster"]
changed = pick(changed_raw, CHANGED_COLS)
changed["ticker"] = changed["ticker"].astype(str)
for col in ["from_cluster_id", "to_cluster_id"]:
    changed[col] = pd.to_numeric(changed[col], errors="coerce").astype("Int64")
for col in ["cluster_confidence", "days_in_cluster"]:
    changed[col] = pd.to_numeric(changed[col], errors="coerce")
n_before = len(changed)
changed = changed.drop_duplicates(subset="ticker").reset_index(drop=True)      # keeps the API's order
no_name = changed["from_cluster_name"].isna()
known = no_name & changed["from_cluster_id"].isin(list(NAME))
changed.loc[known, "from_cluster_name"] = changed.loc[known, "from_cluster_id"].map(NAME)
changed["from_cluster_name"] = changed["from_cluster_name"].fillna("(retired cluster)")
changed["from"] = changed["from_cluster_id"].map(LABEL).fillna("#" + changed["from_cluster_id"].astype(str))
changed["to"] = changed["to_cluster_id"].map(LABEL).fillna("#" + changed["to_cluster_id"].astype(str))
print(f"Changed group: {n_before} rows -> {len(changed)}; from_cluster_name was null in {int(no_name.sum())} "
      f"rows ({int(known.sum())} filled from the cluster table, {int((no_name & ~known).sum())} retired).")

# How was the list picked? Compare it with the anomaly watch.
changed["anomaly_score"] = changed["ticker"].map(dict(zip(anom["ticker"], anom["anomaly_score"])))
changed["on_watch"] = changed["anomaly_score"].notna()
n_watch = int(changed["on_watch"].sum())
watch_cluster = changed.loc[changed["on_watch"], "ticker"].map(dict(zip(anom["ticker"], anom["cluster_id"])))
same_to = int((changed.loc[changed["on_watch"], "to_cluster_id"] == watch_cluster).sum())
in_score_order = n_watch > 1 and changed.loc[changed["on_watch"], "anomaly_score"].is_monotonic_decreasing
watch_first = n_watch > 0 and bool(changed["on_watch"].iloc[:n_watch].all())
MOST_UNUSUAL = in_score_order and watch_first and n_watch >= len(changed) / 4
LISTED = (f"the {len(changed)} most unusual switchers" if MOST_UNUSUAL else f"the {len(changed)} listed switchers")
if changed.empty:
    print("No switchers are listed.")
else:
    print(f"{n_watch} of the {len(changed)} listed switchers {'is' if n_watch == 1 else 'are'} also on the anomaly "
          f"watch ({same_to} of them with "
          f"the same new cluster)" + (", and they come first, in anomaly-score order." if in_score_order and watch_first
                                       else "."))
    print("So the list holds the most unusual switchers (ordered by anomaly score), not a random sample of the "
          f"{model_notes['changed_count']:,} switchers." if MOST_UNUSUAL else
          "The list does not follow the anomaly watch here; SurgeFlow does not document how it picks the 40, "
          "so do not read it as a random sample either.")

# %%
if changed.empty:
    display(Markdown("> No stock changed cluster in this run (or no run exists)."))
else:
    order = [LABEL[c] for c in clusters["cluster_id"]]
    order += sorted(set(changed["from"]).union(changed["to"]) - set(order))
    flows = (pd.crosstab(changed["from"], changed["to"]).reindex(index=order, columns=order, fill_value=0)
             .rename_axis(index="from", columns="to"))
    shown = flows.where(flows > 0)                       # zero cells stay blank, so the moves stand out
    top_flow = flows.stack().idxmax()
    n_top = int(flows.loc[top_flow])
    changed_share = model_notes["changed_count"] / run["clustered_ticker_count"]
    if n_top / len(changed) > 0.5:
        story = f"most of them move {top_flow[0]} → {top_flow[1]} ({n_top} of {len(changed)})"
    else:
        story = f"the most common move is {top_flow[0]} → {top_flow[1]} ({n_top} of {len(changed)})"
    # Confidence: compare listed stocks with each other (median with median), never with the map-wide mean.
    conf_on = changed.loc[changed["on_watch"], "cluster_confidence"].median()
    conf_off = changed.loc[~changed["on_watch"], "cluster_confidence"].median()
    if 0 < n_watch < len(changed):
        conf_note = (f"median cluster_confidence {conf_on:.2f} for the {n_watch} also on the anomaly watch vs "
                     f"{conf_off:.2f} for the other {len(changed) - n_watch}")
    else:
        conf_note = f"median cluster_confidence of the listed stocks {changed['cluster_confidence'].median():.2f}"
    colorscale = [[i / (len(SEQUENTIAL) - 1), c] for i, c in enumerate(SEQUENTIAL)]

    fig = go.Figure(go.Heatmap(
        z=shown.to_numpy(), x=[f"to {c}" for c in order], y=[f"from {c}" for c in order],
        colorscale=colorscale, zmin=0, zmax=max(1, int(flows.to_numpy().max())), xgap=2, ygap=2,
        hoverongaps=False, text=[["" if v == 0 else str(v) for v in row] for row in flows.to_numpy()],
        texttemplate="%{text}", hovertemplate="%{y} %{x}: %{z} listed stocks<extra></extra>",
        colorbar=dict(title=dict(text="Listed stocks", side="right"), thickness=14, len=0.8, outlinewidth=0,
                      dtick=1 if flows.to_numpy().max() <= 6 else None)))
    fig.update_xaxes(side="top", showgrid=False, ticks="")
    fig.update_yaxes(autorange="reversed", showgrid=False, ticks="")
    fig.update_layout(
        title=dict(text=f"{model_notes['changed_count']:,} stocks ({changed_share:.0%}) switched cluster; among "
                        f"{LISTED.replace(' switchers', '')}, {story}",
                   subtitle=dict(text=f"Moves among {LISTED}"
                                      + (" (ordered by anomaly score)" if MOST_UNUSUAL else "")
                                      + f", not all switchers<br>{conf_note}")),
        height=200 + 46 * len(order), margin=dict(t=150, l=10, b=30))
    fig.show()

    flow_table = (flows.stack().rename("stocks").reset_index().query("stocks > 0")
                  .sort_values(["stocks", "from", "to"], ascending=[False, True, True]).reset_index(drop=True))
    flow_table["share of the listed"] = flow_table["stocks"] / len(changed)
    display(flow_table.style.format({"share of the listed": "{:.0%}"}).hide(axis="index"))
    display(changed[["ticker", "from", "from_cluster_name", "to", "to_cluster_name", "cluster_confidence",
                     "days_in_cluster", "on_watch", "anomaly_score"]]
            .style.format({"cluster_confidence": "{:.2f}", "days_in_cluster": "{:.0f}", "anomaly_score": "{:.3f}"},
                          na_rep="not on the watch").hide(axis="index"))

# %% [markdown]
# **How to read this.** Rows are where stocks came from and columns are where
# they went; a number is how many of the listed switchers made that move. The
# diagonal is always empty, because staying put is not a change. A dark cell
# is a move that several listed stocks share. The first table holds the same
# counts; the second lists every listed switcher in the API's order, with its
# anomaly score when it is also on the anomaly watch.
#
# Read every number here as a statement about the **listed stocks only**. The
# check above tells you how they were picked; in the live data they are the
# most unusual switchers, so they say nothing about how the other switchers
# moved or how confident the model is about them. Because the list is a
# selected sample, compare its stocks with each other, not with the map-wide
# `avg_confidence` (a mean over every stock). The subtitle does that: on the
# anomaly watch against off it, median against median. Whether unusual
# switchers are assigned less confidently is an empirical question, not
# something the method guarantees: the methodology note says confidence blends
# how strongly the three clustering methods agree with the Gaussian-mixture
# posterior, and a stock far from its cluster's centre can still have all
# three methods agree and a posterior close to 1. Let the two medians answer
# it for your run; in the live data they have often been equal.
#
# **Caveats.**
#
# - The list is capped at 40 of the `changed_count` switchers and is not a
#   random selection, so the matrix shows only some of the moves.
# - A stock can switch back and forth between runs as its features update
#   daily; `days_in_cluster` tells you how long it has been in its new cluster.
# - None of this predicts returns. It describes how the market's shape changed
#   between two runs.

# %% [markdown]
# ## 4. Whales: the institutional holdings board
#
# **What it is for.** Large investors must disclose what they hold. SurgeFlow
# collects those disclosures for a roster of tracked holders and turns them
# into six **boards**, each a top-20 list of stocks:
#
# | Board | Question it answers | Main fields |
# |---|---|---|
# | `consensus` | Which stocks do many funds own, with large weights? | `consensus_score` (a re-standardised blend of four z-scores), `n_funds_holding` |
# | `conviction` | Where has a single fund made an unusually large bet? | `ticker_conviction_score`, `max_fund_conviction_z`, `top_conviction_fund` |
# | `crowdedness` | What share of the funds counted in `n_funds_total` own the stock? | `crowdedness_pct` (a fraction: `n_funds_holding` ÷ `n_funds_total`), `crowdedness_quintile` (1 = most crowded) |
# | `position_delta` | What did funds buy or sell since their previous filing? | `n_funds_buying`, `n_funds_selling`, share counts (sales are negative), `delta_z` |
# | `network` | Which stocks sit at the centre of the web of shared holders? | `degree`, `eigenvector_centrality`, `community_id` |
# | `ll_predictive` | Which stocks gained the most holders since the previous period? | `n_funds_holding_q`, `n_funds_holding_q_minus_1`, `owner_count_change`, `portfolio_weight_change`, `ll_score_z` |
#
# Who counts as a "fund" depends on the market. In the US the roster is about
# 100 large 13F filers and in China about 100 mutual funds. In Japan and Hong
# Kong it is every holder that has filed a large-shareholding report: about
# two thousand in Hong Kong and over twenty thousand in Japan, from asset
# managers and banks to companies, founders and foundations.
#
# **Two fund counts.** The roster size (`data.funds.count`, charted in 4.3) is
# not the number the boards divide by. The crowdedness board's shares use
# `n_funds_total`, which can be much smaller (in Hong Kong it has been well
# under half the roster). Section 4.5 prints both; every "of N funds" share in
# this notebook names `n_funds_total` so you do not read it as the roster.
#
# The payload also carries `signal_gate_status` (how far each signal has passed
# SurgeFlow's own validation tests), the roster itself (`funds`), and for the
# US only, a filing-speed study (`fund_lead_lag`) and a shareholder-letter tone
# study (`letter_nlp`); both are `null` elsewhere. The sixth board has
# "predictive" in its name; this notebook charts it but never treats it, or any
# other board, as a forecast. Section 4.2 shows how far each board has been
# tested.
#
# **Freshness.** `show_freshness` sees only `market` here. Three dates matter:
# `data.as_of` (when SurgeFlow assembled this response), and on every board row
# `as_of_date` (the date the holdings refer to) and `updated_at` (when the
# computation run wrote the row). Section 4.3 explains why the holdings date
# can be months old.

# %%
wh_payload = sf_get(f"/api/v1/markets/{MARKET}/whales")
show_freshness(wh_payload, "Whales:")
wh = wh_payload["data"]
signals = wh["signal_board"]["signals"]          # a dict: board name -> list of rows
funds_block = wh["funds"]                        # the tracked-holder roster: {"count", "funds": [...]}
us_only = [k for k in ("fund_lead_lag", "letter_nlp") if wh[k]]
print(f"Response assembled {wh['as_of']} · method {wh['method']} · "
      f"signal board as_of {wh['signal_board']['as_of']} · "
      f"{funds_block['count']:,} tracked holders on the roster · "
      f"{len(wh['signal_gate_status']['gates']):,} gate rows for this market · "
      f"US-only studies present: {', '.join(us_only) or 'none'}.")

# %% [markdown]
# **Raw preview.** The boards sit at `data.signal_board.signals`, but they are a
# **dictionary of six lists**, not one list. That is why the helper
# `records(payload, "whales")` returns an empty list here. We look at the
# dictionary directly instead.

# %%
print("records(wh_payload, 'whales') ->", records(wh_payload, "whales"), "(the boards are a dict, not a list)")
display(pd.DataFrame({"board": list(signals), "rows": [len(rows) for rows in signals.values()]}).set_index("board").T)
pd.DataFrame(signals["consensus"]).head()

# %% [markdown]
# ### 4.1 Cleaning: six boards, one function
#
# Every board row carries the same seven common fields (`market`, `ticker`,
# `quarter`, `as_of_date`, `methodology_version`, `updated_at`, `stock_name`)
# plus its own. `clean_board` applies the same steps to each:
#
# 1. keep the documented columns (a missing one raises: contract change);
# 2. keep tickers as text (Hong Kong's `"00700"`, Japan's `"285A"`);
# 3. coerce the numeric fields and count what became NaN;
# 4. parse `as_of_date` and `updated_at` as UTC dates;
# 5. de-duplicate on the natural key, (`ticker`, `quarter`);
# 6. **keep one computation run** (see below);
# 7. **NaN policy for names:** `stock_name` can be null. We keep it null and
#    add a `display_name` that falls back to the ticker, for labels only.
#
# **Why one run?** Each board is rebuilt by a computation run, and every row
# records when its run wrote it (`updated_at`). Rows from an earlier run can
# survive next to today's: the US consensus board has carried a few rows
# written weeks before the rest, and China's boards have interleaved two runs
# with different `quarter` labels. Each run ranks its own rows and computes its
# z-scores against its own universe, so a mixed board shows two "rank 1"s and
# scores that are not comparable. We keep the **newest run**: rows written
# within 24 hours of the board's newest `updated_at` (one run writes all its
# rows within minutes). Rows from earlier runs are counted and listed, then
# left out of the charts.
#
# Two more fields need care. `quarter` has **no single format** (`2026-06-30`,
# `2026-Q2`, even `2026年2季度股票投资明细`, Chinese for "2026 Q2 stock
# investment details"), so we never parse it as a date; we use `as_of_date` for
# time. `components_json` is a **JSON string inside JSON**; we parse it where we
# use it.

# %%
COMMON_COLS = ["market", "ticker", "quarter", "as_of_date", "methodology_version", "updated_at", "stock_name"]
BOARD_COLS = {
    "consensus": ["n_funds_holding", "total_market_value", "aum_weighted_portfolio_pct", "avg_portfolio_pct",
                  "consensus_score", "consensus_percentile", "consensus_rank", "components_json"],
    "conviction": ["n_funds_holding", "ticker_conviction_score", "ticker_conviction_percentile",
                   "ticker_conviction_rank", "max_fund_conviction_z", "top_conviction_fund", "components_json"],
    "crowdedness": ["n_funds_holding", "n_funds_total", "crowdedness_pct", "crowdedness_quintile",
                    "crowdedness_rank"],
    "position_delta": ["n_funds_buying", "n_funds_selling", "net_shares_change", "gross_shares_buying",
                       "gross_shares_selling", "delta_z", "delta_rank", "delta_percentile"],
    "network": ["degree", "weighted_degree", "eigenvector_centrality", "community_id", "n_tickers_in_community",
                "n_communities", "modularity"],
    "ll_predictive": ["n_funds_holding_q", "n_funds_holding_q_minus_1", "owner_count_change",
                      "portfolio_weight_change", "ll_score_z", "ll_rank", "ll_percentile"],
}
RANK_COL = {"consensus": "consensus_rank", "conviction": "ticker_conviction_rank", "crowdedness": "crowdedness_rank",
            "position_delta": "delta_rank", "network": None, "ll_predictive": "ll_rank"}
TEXT_FIELDS = {"top_conviction_fund", "components_json"}
RUN_WINDOW = pd.Timedelta(hours=24)       # rows written this close to the newest row belong to the same run
board_log, earlier_rows = [], []


def clean_board(name: str) -> pd.DataFrame:
    """Documented columns -> tickers as text -> numbers -> UTC dates -> natural key -> newest run only."""
    df = pick(pd.DataFrame(signals[name]), COMMON_COLS + BOARD_COLS[name])   # a missing board raises KeyError
    df["ticker"] = df["ticker"].astype(str)
    numeric = [c for c in BOARD_COLS[name] if c not in TEXT_FIELDS]
    missing_before = int(df[numeric].isna().sum().sum())
    for col in numeric:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    coerced = int(df[numeric].isna().sum().sum()) - missing_before
    df["as_of_date"] = pd.to_datetime(df["as_of_date"], utc=True, errors="coerce")
    df["updated_at"] = pd.to_datetime(df["updated_at"], utc=True, errors="coerce")
    n_raw = len(df)
    df = df.drop_duplicates(subset=["ticker", "quarter"], keep="first")
    newest = df["updated_at"].max()
    df["earlier_run"] = df["updated_at"] < newest - RUN_WINDOW        # NaT compares False: kept, never guessed
    old = df[df["earlier_run"]]
    if not old.empty:
        earlier_rows.append(old.assign(board=name, rank=old[RANK_COL[name]] if RANK_COL[name] else np.nan))
    current = df[~df["earlier_run"]].drop_duplicates(subset="ticker", keep="first").reset_index(drop=True)
    current["display_name"] = current["stock_name"].fillna(current["ticker"])
    current["label"] = np.where(current["stock_name"].isna(), current["ticker"],   # ticker alone when no name
                                current["ticker"] + " · " + current["display_name"].map(shorten))
    board_log.append({"board": name, "rows": n_raw, "unique (ticker, quarter)": len(df),
                      "from earlier runs": int(df["earlier_run"].sum()), "used in charts": len(current),
                      "coerced_to_nan": coerced, "null_stock_name": int(current["stock_name"].isna().sum()),
                      "run written (UTC)": "n/a" if pd.isna(newest) else f"{newest:%Y-%m-%d %H:%M}",
                      "as_of_date": ", ".join(sorted(current["as_of_date"].dt.strftime("%Y-%m-%d").dropna().unique())),
                      "quarter label": ", ".join(sorted(current["quarter"].dropna().astype(str).unique()))})
    return current


boards = {name: clean_board(name) for name in BOARD_COLS}
board_log = pd.DataFrame(board_log).set_index("board")
display(board_log)
earlier_rows = pd.concat(earlier_rows, ignore_index=True) if earlier_rows else pd.DataFrame()
if earlier_rows.empty:
    print("No rows from earlier runs: every board comes from a single run, and nothing was left out.")
else:
    newest_ranks = {name: set(b[RANK_COL[name]].dropna()) for name, b in boards.items() if RANK_COL[name]}
    repeats = int(earlier_rows.apply(lambda r: r["rank"] in newest_ranks.get(r["board"], set()), axis=1).sum())
    print(f"{plural(len(earlier_rows), 'row')} from earlier runs were left out. {repeats} of their "
          f"{len(earlier_rows)} ranks repeat a rank of the newest run on the same board, which is how you can tell "
          "two rankings were mixed:")
    display(earlier_rows[["board", "ticker", "quarter", "rank", "updated_at"]]
            .style.format({"rank": "{:.0f}", "updated_at": "{:%Y-%m-%d %H:%M}"}, na_rep="n/a").hide(axis="index"))

# %% [markdown]
# ### 4.2 Signal gate status: how far has each board been tested?
#
# SurgeFlow runs every whale signal through validation gates (in-sample fit,
# out-of-sample lift, stability, sensitivity tests) and publishes the result:
#
# | `publish_state` | Shown on the website as | Meaning |
# |---|---|---|
# | `publish_tested` | Strong | Passed the gates |
# | `restricted` | Tentative | Partly tested, for example the forward window needed for an out-of-sample test has not passed yet |
# | `draft` | Investigating | Not enough history for a governed test |
#
# `gates` is a history with several dates per signal (thousands of rows in
# Hong Kong). We sort it ourselves (newest first within each `signal_id`) and
# keep the first row, which is the current state. `in_sample_fit` and
# `stability` are SurgeFlow's own test statistics; `oos_lift_pct`
# (out-of-sample lift) stays null until enough time has passed to test the
# signal on data it has not seen. `signal_gate_status.count` is a
# **cross-market** total, so do not compare it with the number of rows you see
# for one market.

# %%
GATE_COLS = ["signal_id", "market", "as_of_date", "publish_state", "in_sample_fit", "oos_lift_pct", "stability",
             "spanning_alpha", "sensitivity_test_pass", "gate_reason"]
GATE_LABEL = {"publish_tested": "Strong", "restricted": "Tentative", "draft": "Investigating"}
BOARD_SIGNAL = {"consensus": "whale_consensus_score", "conviction": "whale_conviction_index",
                "crowdedness": "whale_crowdedness", "position_delta": "whale_position_delta",
                "network": "whale_network", "ll_predictive": "whale_ll_predictive"}

gates = pick(pd.DataFrame(wh["signal_gate_status"]["gates"]), GATE_COLS)
gates = gates[gates["market"].astype(str).str.lower() == MARKET].copy()
gates["as_of_date"] = pd.to_datetime(gates["as_of_date"], utc=True, errors="coerce")
for col in ["in_sample_fit", "oos_lift_pct", "stability", "spanning_alpha"]:
    gates[col] = pd.to_numeric(gates[col], errors="coerce")
current_gates = (gates.sort_values(["signal_id", "as_of_date"], ascending=[True, False])
                 .drop_duplicates(subset="signal_id", keep="first"))
current_gates["shown_as"] = current_gates["publish_state"].map(GATE_LABEL).fillna(current_gates["publish_state"])
board_gates = (pd.DataFrame({"board": list(BOARD_SIGNAL), "signal_id": list(BOARD_SIGNAL.values())})
               .merge(current_gates, on="signal_id", how="left"))
GATE = dict(zip(board_gates["board"], board_gates["shown_as"].fillna("not reported")))
others = current_gates[~current_gates["signal_id"].isin(list(BOARD_SIGNAL.values()))]
print(f"signal_gate_status.count = {wh['signal_gate_status']['count']:,} (all markets); this market has "
      f"{len(gates):,} gate rows for {current_gates['signal_id'].nunique()} signals.")
display(board_gates[["board", "signal_id", "shown_as", "as_of_date", "in_sample_fit", "stability", "oos_lift_pct",
                     "gate_reason"]]
        .style.format({"as_of_date": lambda d: "n/a" if pd.isna(d) else f"{d:%Y-%m-%d}", "in_sample_fit": "{:.3f}",
                       "stability": "{:.2f}", "oos_lift_pct": "{:.2f}"}, na_rep="n/a").hide(axis="index"))
if not others.empty:
    print(f"{plural(len(others), 'more signal')} without a v1 board: "
          + "; ".join(f"{r.signal_id} ({r.shown_as})" for r in others.itertuples()) + ".")

# %% [markdown]
# Read this table before the charts. A "Tentative" board is a well-defined
# description of the filings, but SurgeFlow has not yet shown that it carries
# information about future returns. Even a "Strong" signal is a research
# result about the past, not a recommendation. Every chart subtitle below
# repeats its board's state.

# %% [markdown]
# ### 4.3 Disclosure lags: when were these holdings true?
#
# A whale board is only as fresh as the filings behind it, and each market has
# its own disclosure rules. These are the usual public sources (SurgeFlow does
# not document which filings feed each market, so treat the rules as a guide
# to the lag, not as a description of its pipeline):
#
# | Market | Usual source | When it becomes public |
# |---|---|---|
# | us | **Form 13F**: managers with at least $100 million in US-listed stocks report their long positions as of each quarter end | Within **45 days** after the quarter ends. Positions can be kept confidential longer with SEC approval |
# | cn | **Mutual fund quarterly reports**: each fund's top ten stock holdings (full holdings twice a year) | Within **15 working days** after the quarter ends |
# | jp | **Large shareholding reports**: any holder crossing 5% of a company, and later changes of 1 point or more | Within **5 business days** of the change (institutions can use a twice-monthly special schedule) |
# | hk | **Disclosure of interests** (SFO Part XV): holders of 5% or more, and changes through each whole percentage point | Within **3 business days** of the change |
#
# Quarterly regimes (us, cn) give a complete snapshot that is always **weeks
# to months old**. Event-driven regimes (jp, hk) are fast but cover only large
# stakes. 13F shows long positions only: no short sales, no cash, and few
# non-US holdings. All of them describe what funds **held**, not what they did
# afterwards.

# %%
DISCLOSURE = {
    "us": dict(source="Form 13F (quarterly)", lag=45, business_days=False, quarterly=True),
    "cn": dict(source="Fund quarterly reports", lag=15, business_days=True, quarterly=True),
    "jp": dict(source="Large shareholding reports (5% rule)", lag=5, business_days=True, quarterly=False),
    "hk": dict(source="Disclosure of interests (SFO Part XV)", lag=3, business_days=True, quarterly=False),
}


def add_lag(day: pd.Timestamp, rule: dict, sign: int = 1) -> pd.Timestamp:
    """Move `day` by the rule's filing lag (sign=-1 moves back): calendar days, or business days
    (weekends skipped; public holidays ignored, so the result is approximate)."""
    if not rule["business_days"]:
        return day + sign * pd.Timedelta(days=rule["lag"])
    moved = np.busday_offset(np.datetime64(day.date(), "D"), sign * rule["lag"],
                             roll="forward" if sign > 0 else "backward")
    return pd.Timestamp(moved).tz_localize("UTC")


all_rows = pd.concat([b[["as_of_date", "updated_at"]] for b in boards.values()], ignore_index=True)
rule = DISCLOSURE[MARKET]
if all_rows["as_of_date"].notna().any():
    holdings_date = all_rows["as_of_date"].mode().iloc[0]
    age_days = int((TODAY - holdings_date).days)
    built = all_rows["updated_at"].max()
    if rule["quarterly"]:
        deadline = add_lag(holdings_date, rule)        # quarterly: holdings as of quarter end, filed later
        print(f"Board rows refer to {holdings_date:%Y-%m-%d} ({plural(age_days, 'day')} before today). "
              f"Usual source: {rule['source']}; filings due by about {deadline:%Y-%m-%d}.")
    else:
        earliest = add_lag(holdings_date, rule, sign=-1)   # event-driven: a filing can describe an older change
        print(f"Board rows refer to {holdings_date:%Y-%m-%d} ({plural(age_days, 'day')} before today): the boards "
              f"are rebuilt from every report on file, so this is the date of the rebuild. Usual source: "
              f"{rule['source']}; a change made after about {earliest:%Y-%m-%d} may not be filed yet.")
    if all_rows["as_of_date"].nunique() > 1:
        print(f"Note: board rows carry {all_rows['as_of_date'].nunique()} different as_of_date values; "
              "we use the most common one.")
else:
    holdings_date = None
    print("No board rows, so there is no holdings date to show.")

lead_lag = wh["fund_lead_lag"]          # US only; null in the other markets
speeds = pd.DataFrame()
if lead_lag:
    speeds = pick(pd.DataFrame(lead_lag["funds"]), ["fund_name", "n_quarters_observed", "avg_filing_speed_days",
                                                    "leader_score", "data_depth_caveat"])
    speeds["avg_filing_speed_days"] = pd.to_numeric(speeds["avg_filing_speed_days"], errors="coerce")
    print(f"fund_lead_lag: {len(speeds)} funds take {speeds['avg_filing_speed_days'].min():.0f}-"
          f"{speeds['avg_filing_speed_days'].max():.0f} days to file on average "
          f"(median {speeds['avg_filing_speed_days'].median():.0f}).")

# %% [markdown]
# ### Chart: the disclosure timeline for this market
#
# One line of time around the date the holdings refer to. In a quarterly
# market the shaded span runs from that date to today: it is the age of the
# information you are about to chart. In an event-driven market the boards are
# rebuilt every day, so the shaded span is the filing window instead: the
# recent days whose changes may not be reported yet.

# %%
if holdings_date is None:
    display(Markdown("> No board rows, so there is no timeline to draw."))
else:
    events = [("Holdings date<br>(as_of_date)", holdings_date, COLOR, "circle"),
              ("Board built<br>(updated_at)", built, INK_2, "square-open"),
              ("Today", TODAY, INK, "circle")]
    if rule["quarterly"]:
        next_end = (holdings_date + pd.offsets.QuarterEnd(1)).normalize()
        events += [("Filing deadline<br>(approx.)", deadline, INK_2, "diamond-open"),
                   ("Next quarter<br>ends", next_end, MUTED, "circle-open"),
                   ("Next filings<br>due (approx.)", add_lag(next_end, rule), MUTED, "diamond-open")]
    else:
        events += [("Later changes may<br>be unfiled (approx.)", earliest, INK_2, "diamond-open")]
    band = None
    if not speeds.empty and rule["quarterly"]:
        lo = holdings_date + pd.Timedelta(days=float(speeds["avg_filing_speed_days"].min()))
        hi = holdings_date + pd.Timedelta(days=float(speeds["avg_filing_speed_days"].max()))
        band = (lo, hi)
        events.append((f"Typical filing<br>({len(speeds)} funds, {speeds['avg_filing_speed_days'].min():.0f}-"
                       f"{speeds['avg_filing_speed_days'].max():.0f} d)", lo + (hi - lo) / 2, None, None))
    events = pd.DataFrame(events, columns=["event", "date", "colour", "symbol"]).sort_values("date", kind="stable")
    # Events on the same calendar day share one marker and one label (the first event's marker wins).
    events["day"] = events["date"].dt.normalize()
    events = (events.groupby("day", as_index=False, sort=True)
              .agg(event=("event", lambda e: e.iloc[0] if len(e) == 1
                          else wrap(" · ".join(x.split("<br>")[0] for x in e), 26)),
                   colour=("colour", "first"), symbol=("symbol", "first"))
              .rename(columns={"day": "date"}))
    # Place each label on the first free level (above, below, higher, lower) so that close dates do not collide.
    span = (events["date"].max() - events["date"].min()).days or 1
    levels, last_on = [0.42, -0.42, 0.78, -0.78], {}
    ys = []
    for day in events["date"]:
        free = [lv for lv in levels if lv not in last_on or (day - last_on[lv]).days > 0.16 * span]
        level = free[0] if free else levels[len(ys) % len(levels)]
        last_on[level] = day
        ys.append(level)
    events["y"] = ys

    fig = go.Figure()
    if age_days > 0:                                     # shade the age of the information
        shade, shade_text = (holdings_date, TODAY), f"information age: <b>{plural(age_days, 'day')}</b>"
    else:                                                # rebuilt today: shade the window that may not be filed yet
        shade = (holdings_date, deadline) if rule["quarterly"] else (earliest, holdings_date)
        shade_text = "filing window: <b>changes here may not be public yet</b>"
    fig.add_vrect(x0=shade[0], x1=shade[1], fillcolor=COLOR, opacity=0.09, line_width=0)
    fig.add_annotation(x=shade[0] + (shade[1] - shade[0]) / 2, y=1.0, yanchor="top", showarrow=False,
                       text=shade_text, font=dict(size=13, color=INK))
    if band:
        fig.add_shape(type="rect", x0=band[0], x1=band[1], y0=-0.07, y1=0.07, fillcolor=COLOR, opacity=0.4,
                      line_width=0)
    fig.add_trace(go.Scatter(x=[events["date"].min(), events["date"].max()], y=[0, 0], mode="lines",
                             line=dict(color=AXIS, width=2), hoverinfo="skip", showlegend=False))
    for _, ev in events.iterrows():
        fig.add_trace(go.Scatter(
            x=[ev["date"], ev["date"]], y=[0, ev["y"] * 0.7], mode="lines", line=dict(color=AXIS, width=1),
            hoverinfo="skip", showlegend=False))
        has_marker = pd.notna(ev["colour"])               # the filing band has a label but no marker
        fig.add_annotation(x=ev["date"], y=ev["y"], text=f"{ev['event']}<br><b>{ev['date']:%b %d}</b>"
                           if has_marker else ev["event"], showarrow=False, font=dict(size=11, color=INK_2))
        if not has_marker:
            continue
        fig.add_trace(go.Scatter(
            x=[ev["date"]], y=[0], mode="markers", showlegend=False,
            marker=dict(size=14, color=ev["colour"], symbol=ev["symbol"], line=dict(width=2, color=ev["colour"])),
            hovertemplate=f"{ev['event'].replace('<br>', ' ')}: %{{x|%Y-%m-%d}}<extra></extra>"))
    fig.update_yaxes(visible=False, range=[-1.05, 1.05])
    fig.update_xaxes(showgrid=False, title_text=None, tickformat="%b %d<br>%Y",
                     dtick=86_400_000 if span <= 14 else None)        # short spans: one tick per day
    if rule["quarterly"]:
        headline = (f"The {MARKET_NAMES[MARKET]} whale boards describe holdings from {holdings_date:%d %b %Y}: "
                    f"{plural(age_days, 'day')} ago")
    else:
        headline = (f"The {MARKET_NAMES[MARKET]} whale boards show stakes as known on {holdings_date:%d %b %Y}; "
                    f"changes from the last {rule['lag']} business days may be missing")
    fig.update_layout(
        title=dict(text=headline,
                   subtitle=dict(text=f"Usual source: {rule['source']}, due {rule['lag']} "
                                      f"{'business' if rule['business_days'] else 'calendar'} days after "
                                      f"{'quarter end' if rule['quarterly'] else 'the change'} · holidays ignored")),
        height=380, margin=dict(t=100, b=50, l=40, r=40), showlegend=False)
    fig.show()
    display(events[events["colour"].notna()].assign(date=lambda d: d["date"].dt.strftime("%Y-%m-%d"),
                                                     event=lambda d: d["event"].str.replace("<br>", " "))
            [["event", "date"]].style.hide(axis="index"))
    if not speeds.empty:
        display(speeds.sort_values("avg_filing_speed_days").style.format(
            {"avg_filing_speed_days": "{:.1f}", "leader_score": "{:.3f}"}, na_rep="").hide(axis="index"))

# %% [markdown]
# **How to read this.** The line runs left to right through time, and events
# on the same day share one marker. For quarterly regimes (us, cn) the
# coloured point is the date the holdings refer to, the shaded span up to
# "Today" is how old that information is, and the chart also marks the filing
# deadline, the next quarter end and when its filings are due: that is when
# the board can next change. For event-driven regimes (jp, hk) the holdings
# date is the day the boards were rebuilt from every report on file, and the
# diamond marks the start of the filing window: a stake that changed after it
# may not be reported yet. For the US, the darker band on the line shows when
# the tracked funds typically file (their `avg_filing_speed_days` from
# `fund_lead_lag`, labelled "Typical filing"). Many funds file close to the
# deadline, so a quarter's 13F picture is often five or six weeks old before
# anyone can see it.
#
# **Caveats.**
#
# - Deadlines here skip weekends but ignore public holidays, so they are
#   approximate.
# - A fund can trade the day after its quarter end. Treat a quarterly board as
#   "what funds held then", never "what funds hold now".
# - In Japan and Hong Kong the date is recent, but only large stakes (5% or
#   more) are reported, so the boards see fewer positions, and a holder whose
#   stake has not moved past a threshold files nothing new. The next chart
#   shows how old each holder's latest report is.

# %% [markdown]
# ### Chart: how old is each tracked holder's latest report?
#
# The roster (`data.funds.funds`) lists every tracked holder with
# `latest_quarter`: the period of its most recent disclosure. Its format
# depends on the market: a date (`2026-06-30`, a US quarter end; `2026-06-24`,
# the day of a Japanese report) or, in China, a quarter label (`2026-Q2`,
# `2026年2季度股票投资明细`). We turn all of them into dates (a quarter label
# becomes the quarter's last day). **NaN policy:** a label we cannot read is
# counted and left out, never guessed. Then we sort the holders into age
# buckets.
#
# For quarterly regimes (us, cn) this shows how old the snapshot is. For
# event-driven regimes (jp, hk) an old report does not mean an old position: a
# holder files again only when its stake moves past a threshold, so many
# reports stay valid for years.
#
# The roster also carries `quarters` (reporting periods on file) and
# `total_holdings`. Despite its name, `total_holdings` is best read as the
# number of **holding records on file across all reported periods**, not the
# number of stocks a holder owns today: in the US most funds show exactly 120
# records over 3 periods (about 40 per period, which looks like a cap), and
# State Street shows 100. We divide it by `quarters` to get records per period,
# and check whether many funds share the same maximum before we rank anyone by
# it.

# %%
ROSTER_COLS = ["market", "fund_name", "fund_id", "quarters", "total_holdings", "latest_quarter"]
AGE_BUCKETS = [0, 31, 92, 183, 366, 731, np.inf]
AGE_LABELS = ["under 1 month", "1-3 months", "3-6 months", "6-12 months", "1-2 years", "over 2 years"]


def period_end(label: pd.Series) -> pd.Series:
    """'2026-06-24' -> that day; '2026-Q2' or '2026年2季度...' -> 2026-06-30 (quarter end); else NaT (UTC)."""
    text = label.astype(str).str.strip()
    exact = pd.to_datetime(text.where(text.str.fullmatch(r"\d{4}-\d{2}-\d{2}")), format="%Y-%m-%d",
                           errors="coerce", utc=True)
    yq = text.str.extract(r"^(\d{4})(?:-Q|年)([1-4])").astype(float)        # year and quarter number
    q_end = (pd.to_datetime(pd.DataFrame({"year": yq[0], "month": yq[1] * 3, "day": 1}), errors="coerce")
             + pd.offsets.MonthEnd(0)).dt.tz_localize("UTC")
    return exact.fillna(q_end)


roster = pick(pd.DataFrame(funds_block["funds"]), ROSTER_COLS)
roster["fund_id"] = roster["fund_id"].astype(str)
for col in ["quarters", "total_holdings"]:
    roster[col] = pd.to_numeric(roster[col], errors="coerce")
n_before = len(roster)
roster = roster.drop_duplicates(subset="fund_id").reset_index(drop=True)      # natural key: fund_id
roster["latest_date"] = period_end(roster["latest_quarter"])
roster["report_age_days"] = (TODAY - roster["latest_date"]).dt.days
unreadable = int(roster["latest_date"].isna().sum())
future = int((roster["report_age_days"] < 0).sum())
roster["age_bucket"] = pd.cut(roster["report_age_days"].clip(lower=0), AGE_BUCKETS, right=False, labels=AGE_LABELS)
print(f"Roster: {n_before:,} rows -> {len(roster):,} unique fund_id; latest_quarter unreadable for {unreadable:,}"
      + (f"; {future} dated after today (counted as under 1 month)" if future else "") + ".")
roster["records_per_period"] = roster["total_holdings"] / roster["quarters"].where(roster["quarters"] > 0)
at_max = roster["total_holdings"] == roster["total_holdings"].max()
HOLDINGS_CAPPED = bool(len(roster)) and at_max.mean() > 0.2       # many funds tied at one maximum: a cap, not a ranking
common = roster["total_holdings"].value_counts().head(5)
print("Most common total_holdings values (value: funds): "
      + ", ".join(f"{v:,.0f}: {n:,}" for v, n in common.items()) + ".")
if HOLDINGS_CAPPED:
    print(f"total_holdings is capped or tied: {int(at_max.sum())} of {len(roster)} funds ({at_max.mean():.0%}) "
          f"share the maximum of {roster['total_holdings'].max():,.0f} records (median "
          f"{roster['records_per_period'].median():.0f} per period). It cannot rank funds by breadth, so we do not "
          "list 'the broadest holders'.")

if roster["report_age_days"].notna().sum() == 0:
    display(Markdown("> The roster is empty or carries no readable dates, so there is no age chart."))
else:
    ages = (roster["age_bucket"].value_counts(sort=False).reindex(AGE_LABELS, fill_value=0)
            .rename("holders").to_frame())
    ages["share"] = ages["holders"] / ages["holders"].sum()
    median_age = float(roster["report_age_days"].median())
    top_bucket = ages["holders"].idxmax()
    top_share = float(ages["share"].max())
    group_text = (f"most are {top_bucket} old" if top_share > 0.5 else
                  f"the largest group ({top_share:.0%}) is {top_bucket} old")
    fig = go.Figure(go.Bar(
        x=ages.index.astype(str), y=ages["holders"], marker=dict(color=COLOR),
        text=[f"{n:,} · {sh:.0%}" if n else "" for n, sh in zip(ages["holders"], ages["share"])],
        textposition="outside", cliponaxis=False, textfont=dict(size=11, color=INK_2),
        customdata=ages["share"], hovertemplate="%{x}: %{y:,} holders (%{customdata:.1%})<extra></extra>"))
    fig.update_xaxes(title_text="Age of the holder's latest report (on today's date)", ticks="")
    fig.update_yaxes(title_text="Tracked holders", rangemode="tozero", range=[0, ages["holders"].max() * 1.18])
    fig.update_layout(
        title=dict(text=f"The median {MARKET_NAMES[MARKET]} holder's latest report is "
                        f"{plural(round(median_age), 'day')} old; {group_text}",
                   subtitle=dict(text=f"{len(roster):,} tracked holders · usual source: {rule['source']}"
                                      + (" · an old report can still be current: holders refile only when a stake "
                                         "crosses a threshold" if not rule["quarterly"] else ""))),
        height=420, margin=dict(t=110, b=70), bargap=0.35, showlegend=False)
    fig.show()
    display(ages.style.format({"holders": "{:,}", "share": "{:.1%}"}))
    if not HOLDINGS_CAPPED:
        print("The five holders with the most holding records on file:")
        display(roster.nlargest(5, "total_holdings")
                [["fund_name", "quarters", "total_holdings", "records_per_period", "latest_quarter"]]
                .rename(columns={"total_holdings": "holding records on file"})
                .style.format({"quarters": "{:.0f}", "holding records on file": "{:,.0f}",
                               "records_per_period": "{:,.1f}"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Each bar counts the tracked holders whose most recent
# report falls in that age bucket. In a quarterly market almost every holder
# sits in one bar, because everyone reports the same quarter end: the whole
# board is that old. In an event-driven market the bars spread out over months
# or years. When `total_holdings` can tell holders apart, the small table lists
# the five with the most holding records on file (`quarters` = reporting
# periods on file; records per period = `total_holdings` ÷ `quarters`). When
# many funds share one maximum, as in the US, the cell says so instead and
# shows no ranking.
#
# **Caveats.**
#
# - `latest_quarter` is a period label, not the filing date. A US fund that
#   reported the June quarter filed it up to 45 days later.
# - In Japan many roster entries are one-off filers (a company, a founder, a
#   foundation) with a single holding, so the roster is much larger than the
#   set of investment funds.
# - `total_holdings` counts holding records across all reported periods; in
#   the US it looks capped at about 40 per period. It is not the number of
#   stocks a fund holds now.

# %% [markdown]
# ### 4.4 Chart: consensus, taken apart
#
# The consensus score is built from **four z-scores**, blended with the weights
# stored in each row's `components_json`. A z-score measures how far a stock
# sits from the average stock, in standard deviations. The four parts are:
#
# - **breadth**: how many tracked funds hold the stock (`n_funds_holding`);
# - **AUM-weighted weight**: its average weight in the holders' portfolios,
#   counting big funds more;
# - **position value**: the total market value the funds hold (logged);
# - **average weight**: its average portfolio weight, every holder counting the same.
#
# Each part's **piece** is `weight × z`. A weighted sum of z-scores is not a
# z-score itself (its spread across stocks is below 1), so SurgeFlow
# **re-standardises** it: within one run, the published `consensus_score` is
# the weighted sum times a single constant (one over the sum's standard
# deviation across the market). We check that rule on every row: one ratio for
# the whole board confirms it. Then we scale each piece by that ratio, so the
# bars add up to the published score while every piece keeps its share, and
# draw the pieces as stacked bars.
#
# **NaN policy for money.** `total_market_value` is `0.0` when the filings do
# not disclose position values (some runs do this, for example an earlier China
# run). Zero would be a false number, so it becomes NaN ("not disclosed").

# %%
consensus = boards["consensus"].copy()
COMPONENTS = {"n_funds_holding": "Breadth (funds holding)",
              "aum_weighted_portfolio_pct": "AUM-weighted portfolio weight",
              "log_total_market_value": "Position value (log)",
              "avg_portfolio_pct": "Average portfolio weight"}

if consensus.empty:
    display(Markdown("> The consensus board is empty, so there is nothing to take apart."))
else:
    undisclosed = consensus["total_market_value"] == 0
    consensus["total_market_value"] = consensus["total_market_value"].mask(undisclosed)
    print(f"total_market_value: {int(undisclosed.sum())} of {len(consensus)} rows are 0.0 (not disclosed) -> NaN.")
    parsed = consensus["components_json"].map(json.loads)          # a JSON string inside the JSON
    for part in COMPONENTS:
        consensus[f"w_{part}"] = parsed.map(lambda d: d["weights"][part])
        consensus[f"z_{part}"] = parsed.map(lambda d: d[f"z_{part}"])
        consensus[f"c_{part}"] = consensus[f"w_{part}"] * consensus[f"z_{part}"]
    consensus["sum_of_parts"] = consensus[[f"c_{p}" for p in COMPONENTS]].sum(axis=1)
    # Ratio of the published score to the plain weighted sum (NaN when the sum is ~0 or the signs differ).
    ratio = consensus["consensus_score"] / consensus["sum_of_parts"].where(consensus["sum_of_parts"].abs() > 1e-9)
    consensus["scale"] = ratio.where(ratio > 0)
    r = consensus["scale"]
    one_constant = r.notna().any() and (r.max() - r.min()) / r.median() < 0.01
    # Scale by the board's constant when the rule holds (robust to a row whose sum is ~0); else row by row.
    factor = pd.Series(r.median(), index=r.index) if one_constant else r.fillna(1.0)
    for part in COMPONENTS:
        consensus[f"piece_{part}"] = consensus[f"c_{part}"] * factor
    weights = {p: float(consensus[f"w_{p}"].iloc[0]) for p in COMPONENTS}
    print("Weights: " + ", ".join(f"{COMPONENTS[p]} {w:.0%}" for p, w in weights.items()))
    if one_constant:
        print(f"Published score = {r.median():.3f} × weighted sum on every row, so the run divides the sum by its "
              f"standard deviation across the market (about {1 / r.median():.2f}).")
    else:
        print(f"The ratio of published score to weighted sum varies from {r.min():.2f} to {r.max():.2f} "
              f"({plural(r.isna().sum(), 'row')} without a usable ratio): the bars are rescaled row by row.")
    rank_order = consensus.sort_values("consensus_score", ascending=False)["ticker"].tolist()
    disagree = int((consensus.set_index("ticker").loc[rank_order, "consensus_rank"].diff() < 0).sum())
    print(f"consensus_rank has {plural(consensus['consensus_rank'].duplicated().sum(), 'tie')} and "
          f"{plural(disagree, 'step')} where it disagrees with the score order. We sort by the score we plot.")

# %% [markdown]
# **Sanity check: can a position be bigger than the company?** Filers report
# `total_market_value` themselves, and filer-reported 13F values can carry
# unit errors (thousands of dollars entered as dollars, for example). One test
# catches the worst cases: a position cannot be worth more than the whole
# company. The screen endpoint (notebook 01) lists market caps, largest first,
# so for the US we fetch its first `CAP_CHECK_PAGES` pages (the largest
# companies).
#
# **Two dates.** The position values are as of the holdings date (a quarter
# end, section 4.3); the screen's market caps are as of its own `as_of_date`,
# today or yesterday. That can be three months or more later. A holder that
# owns most of a company (a parent holding a subsidiary, say) can see its
# correct quarter-end value rise above today's market cap after a fall in the
# share price. So we flag a value only when it exceeds the cap by a clear
# margin, `CAP_MARGIN` = 1.5 (50%): even a holder of the whole company would
# need the price to fall by a third for a correct filing to cross that line.
# A consensus row is marked when
#
# - the company is on the fetched pages and the position is worth more than
#   1.5 × its market cap ("above the market cap"), or
# - the company is **not** on the fetched pages, and one or two filers report
#   a position worth more than 1.5 × the smallest cap fetched ("check"). We do
#   not know this company's cap: if the screen lists it, the cap is below the
#   smallest one fetched, but the ticker may also be missing from the screen
#   altogether.
#
# A stock that many funds hold but that is missing from the pages may simply
# be missing from the screen's universe (a new listing, for example), so those
# rows are listed as "not verifiable" rather than marked, and values above
# the cap but within the margin are listed without a mark. The test runs for
# the US only: the screen reports `market_cap_usd`, the other markets' whale
# values are in local currency, and v1 sends no exchange rates. A mark means
# "read this value with care" (possibly a unit error in the filing, or a price
# fall since the holdings date), not "proven wrong".

# %%
CAP_MARGIN = 1.5          # mark a value only above 1.5 x the cap: room for a price fall since the holdings date
consensus["market_cap_usd"] = np.nan
consensus["cap_flag"] = ""                 # "" = not marked; else "above the market cap" or "check" (see above)
consensus["cap_note"] = ""                 # the same, in words, for the chart's hover and table
SCREEN_DATE = None                         # the screen's as_of_date: the date of its market caps
if consensus.empty:
    print("The consensus board is empty: nothing to check.")
elif MARKET != "us" or CAP_CHECK_PAGES < 1:
    print("Market-cap check skipped: " + ("CAP_CHECK_PAGES is 0." if MARKET == "us" else
          f"total_market_value is in {CCY}, the screen's caps are in USD, and v1 sends no exchange rates."))
else:
    cap_rows = []
    for page in range(1, CAP_CHECK_PAGES + 1):
        payload = sf_try(f"/api/v1/markets/{MARKET}/screen", page=page, page_size=100, sort="market_cap_usd")
        if payload is None:                                   # unavailable: the check is optional, carry on
            break
        if page == 1:   # on the screen, data_quality is a dictionary of coverage statistics; we leave it out
            show_freshness({k: v for k, v in payload.items() if k != "data_quality"}, "Screen (market caps):")
            SCREEN_DATE = payload["as_of_date"]
        batch = records(payload, "screen")
        cap_rows += batch
        if not batch or page >= payload["total_pages"]:
            break
    caps = pick(pd.DataFrame(cap_rows), ["ticker", "market_cap_usd"])
    caps["ticker"] = caps["ticker"].astype(str)
    caps["market_cap_usd"] = pd.to_numeric(caps["market_cap_usd"], errors="coerce")
    caps = caps.dropna(subset=["market_cap_usd"]).drop_duplicates(subset="ticker")
    if caps.empty:
        print("No market caps came back, so the check is skipped.")
    else:
        value_dates = consensus["as_of_date"].dropna().dt.strftime("%Y-%m-%d").unique()
        print(f"Positions as of {', '.join(sorted(value_dates)) or 'an unknown date'} (the holdings date); market caps "
              f"as of {SCREEN_DATE} (the screen). A value is marked only above {CAP_MARGIN:g} × the cap, to allow "
              "for price moves between the two dates.")
        smallest = float(caps["market_cap_usd"].min())
        consensus["market_cap_usd"] = consensus["ticker"].map(dict(zip(caps["ticker"], caps["market_cap_usd"])))
        over_cap = consensus["total_market_value"] > CAP_MARGIN * consensus["market_cap_usd"]
        off_page = consensus["market_cap_usd"].isna() & (consensus["total_market_value"] > smallest)
        far_off_page = off_page & (consensus["total_market_value"] > CAP_MARGIN * smallest)
        few = consensus["n_funds_holding"] <= 2                        # one or two filers report the whole value
        consensus.loc[over_cap, "cap_flag"] = "above the market cap"
        consensus.loc[far_off_page & few, "cap_flag"] = "check"
        consensus.loc[over_cap, "cap_note"] = (
            (consensus["total_market_value"] / consensus["market_cap_usd"])[over_cap]
            .map(lambda x: f"check: {x:.1f} × the market cap of {SCREEN_DATE}"))
        consensus.loc[far_off_page & few, "cap_note"] = (f"check: not on the fetched screen pages (cap under "
                                                         f"{money(smallest)} if the screen lists it)")
        flagged = consensus[consensus["cap_flag"] != ""].copy()
        unverifiable = consensus[off_page & ~few]                      # many filers: perhaps not on the screen at all
        # Above the cap (or the smallest cap fetched), but within the margin: a price fall alone could explain these.
        near_cap = ~over_cap & (consensus["total_market_value"] > consensus["market_cap_usd"])
        within = consensus[near_cap | (off_page & few & ~far_off_page)]
        n_above, n_check = int(over_cap.sum()), int((far_off_page & few).sum())
        print(f"Checked {len(consensus)} consensus rows against the {len(caps):,} largest US companies on the screen "
              f"(the smallest is {money(smallest)}): {plural(n_above, 'position value')} above {CAP_MARGIN:g} × the "
              f"company's market cap; {n_check} to check (one or two filers, company not on the fetched pages, value "
              f"above {CAP_MARGIN:g} × {money(smallest)}).")
        if not flagged.empty:
            flagged["position value"] = flagged["total_market_value"].map(money)
            flagged["market cap"] = flagged["market_cap_usd"].map(
                lambda v: f"not on the fetched pages (under {money(smallest)} if the screen lists it)" if pd.isna(v)
                else money(v))
            flagged["value ÷ cap"] = flagged["total_market_value"] / flagged["market_cap_usd"]
            display(flagged[["ticker", "display_name", "n_funds_holding", "position value", "market cap",
                             "value ÷ cap", "cap_flag", "avg_portfolio_pct"]]
                    .rename(columns={"cap_flag": "mark"})
                    .style.format({"n_funds_holding": "{:.0f}", "value ÷ cap": "{:.2f}",
                                   "avg_portfolio_pct": "{:.1f}%"}, na_rep="n/a").hide(axis="index"))
            print("Possibly a unit error in the filing, or a price fall since the holdings date. These values feed the "
                  "'Position value (log)' piece of the score: read that piece with care.")
        if not within.empty:
            listed = ", ".join(f"{r.ticker} ({money(r.total_market_value)}, "
                               + (f"cap {money(r.market_cap_usd)}" if pd.notna(r.market_cap_usd)
                                  else "not on the fetched pages")
                               + f", {plural(r.n_funds_holding, 'filer')})" for r in within.itertuples())
            print(f"Above the market cap (or, off the fetched pages, above {money(smallest)}) but within the "
                  f"{CAP_MARGIN:g}× margin, so not marked; a price fall since the holdings date could explain them: "
                  f"{listed}.")
        if not unverifiable.empty:
            listed = ", ".join(f"{r.ticker} ({r.n_funds_holding:.0f} funds, {money(r.total_market_value)})"
                               for r in unverifiable.itertuples())
            print("Not verifiable (held by several funds, not on the screen's largest pages; perhaps missing from the "
                  f"screen's universe): {listed}.")

# %%
if not consensus.empty:
    bars = consensus.sort_values("consensus_score", ascending=False).reset_index(drop=True)
    # The denominator of the shares: n_funds_total from the crowdedness board (not the roster size; see 4.5).
    if not boards["crowdedness"].empty:
        n_total_funds, denom_words = boards["crowdedness"]["n_funds_total"].mode().iloc[0], "funds in n_funds_total"
    else:
        n_total_funds, denom_words = funds_block["count"], "holders on the roster"
    lead = bars.iloc[0]
    lead_part = max(COMPONENTS, key=lambda p: lead[f"c_{p}"])
    bars["value_text"] = bars["total_market_value"].map(lambda v: "not disclosed" if pd.isna(v) else money(v, CCY))
    marked = bars["cap_flag"] != ""                                  # from the market-cap check above
    bars.loc[marked, "value_text"] += " (" + bars.loc[marked, "cap_note"] + ")"
    bars["label"] = np.where(marked, bars["label"] + " †", bars["label"])
    n_flagged = int(marked.sum())
    n_above, n_check = int((bars["cap_flag"] == "above the market cap").sum()), int((bars["cap_flag"] == "check").sum())
    kinds = ([f"{n_above} above {CAP_MARGIN:g} × the market cap of {SCREEN_DATE}"] if n_above else []) + (
        [f"{n_check} off the fetched screen pages, above {CAP_MARGIN:g} × the smallest cap there"] if n_check else [])
    top_margin = 130 if n_flagged else 110                           # room for one more subtitle line
    # The four pieces are parts of one score: shades of one hue (darkest = largest weight), never market colours.
    # Steps 700, 500, 350 and 250 of the kit's sequential blue ramp (350 and 250 sit between SEQUENTIAL's entries),
    # spaced so that neighbouring pieces stay apart and the lightest still stands out from the background.
    component_colors = dict(zip(COMPONENTS, [SEQUENTIAL[6], SEQUENTIAL[4], "#5598e7", "#86b6ef"]))

    fig = go.Figure()
    for part, name in COMPONENTS.items():
        colour = component_colors[part]
        fig.add_trace(go.Bar(
            y=bars["label"], x=bars[f"piece_{part}"], name=f"{name} ({weights[part]:.0%})", orientation="h",
            marker=dict(color=colour),
            customdata=np.column_stack([bars[f"z_{part}"], bars["display_name"], bars[f"c_{part}"]]),
            hovertemplate=(f"<b>%{{customdata[1]}}</b><br>{name}: z = %{{customdata[0]:+.2f}} × "
                           f"{weights[part]:.0%} = %{{customdata[2]:+.2f}}<br>contribution to the score: %{{x:+.2f}}"
                           "<extra></extra>")))
    fig.add_trace(go.Scatter(
        y=bars["label"], x=bars["consensus_score"], mode="markers", name="Consensus score",
        marker=dict(symbol="diamond", size=11, color=INK, line=dict(width=1.5, color=SURFACE)),
        customdata=bars[["n_funds_holding", "value_text", "consensus_rank", "avg_portfolio_pct"]].to_numpy(),
        hovertemplate=("<b>%{y}</b><br>Consensus score %{x:.2f} (API rank %{customdata[2]})<br>"
                       "Held by %{customdata[0]} funds · value %{customdata[1]}<br>"
                       "Average weight %{customdata[3]:.2f}% of a holder's portfolio<extra></extra>")))
    right = float(np.nanmax([bars[[f"piece_{p}" for p in COMPONENTS]].clip(lower=0).sum(axis=1).max(),
                             bars["consensus_score"].max()]))
    for _, row in bars.iterrows():
        n = int(row["n_funds_holding"])
        fig.add_annotation(x=right, y=row["label"], text=f"{n} fund{'' if n == 1 else 's'}", showarrow=False,
                           xanchor="left", xshift=10, font=dict(size=11, color=INK_2))
    fig.add_vline(x=0, line=dict(color=AXIS, width=1))
    fig.update_xaxes(title_text="Contribution to the consensus score (weight × z-score, scaled to the score)")
    fig.update_yaxes(autorange="reversed", ticks="", title_text=None)
    fig.update_layout(
        title=dict(text=f"{lead['ticker']} tops consensus mainly on {lower_first(COMPONENTS[lead_part])}: "
                        f"{lead['n_funds_holding']:.0f} "
                        + (f"of {n_total_funds:,.0f} {denom_words} " if n_total_funds else "tracked funds ")
                        + f"hold{'s' if lead['n_funds_holding'] == 1 else ''} it",
                   subtitle=dict(text=f"Top {len(bars)} of the consensus board · holdings as of "
                                      f"{holdings_date:%Y-%m-%d} · gate: {GATE['consensus']} · "
                                      "diamond = published score"
                                      + (f"<br>† value to check: {'; '.join(kinds)}<br>possibly a unit error in "
                                         f"the filing, or a price fall since the holdings date "
                                         f"({holdings_date:%Y-%m-%d}), so its value piece is suspect"
                                         if n_flagged else ""))),
        barmode="relative", height=200 + 30 * len(bars), margin=dict(t=top_margin, r=90, l=10, b=130),
        legend=dict(orientation="h", x=0, y=below_plot(200 + 30 * len(bars), top_margin, 130), yanchor="top"))
    fig.show()

    SHORT = {"n_funds_holding": "breadth", "aum_weighted_portfolio_pct": "AUM-weighted",
             "log_total_market_value": "value (log)", "avg_portfolio_pct": "avg weight"}
    twin = bars[["consensus_rank", "ticker", "display_name", "n_funds_holding", "value_text",
                 "aum_weighted_portfolio_pct", "avg_portfolio_pct"]
                + [f"z_{p}" for p in COMPONENTS] + [f"piece_{p}" for p in COMPONENTS]
                + ["consensus_score", "consensus_percentile"]]
    twin = twin.rename(columns={**{f"z_{p}": f"z {SHORT[p]}" for p in COMPONENTS},
                                **{f"piece_{p}": f"piece {SHORT[p]}" for p in COMPONENTS}})
    display(twin.style.format({"n_funds_holding": "{:.0f}", "aum_weighted_portfolio_pct": "{:.2f}%",
                               "avg_portfolio_pct": "{:.2f}%", "consensus_score": "{:.2f}",
                               "consensus_percentile": "{:.1f}",
                               **{f"z {SHORT[p]}": "{:+.2f}" for p in COMPONENTS},
                               **{f"piece {SHORT[p]}": "{:+.2f}" for p in COMPONENTS}}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Each bar is built from four pieces, one per component,
# in shades of one colour (darkest = the component with the largest weight);
# the diamond marks the published consensus score, which the pieces add up to.
# Pieces to the right of zero push the score up; pieces to the left pull it
# down. The label on the right says how many tracked funds hold the stock, and
# the table gives every z-score and piece. Look for *why* a stock ranks high: a
# long darkest piece (breadth) means broad ownership (many funds agree), while
# long weight pieces with few funds mean a
# handful of holders put a lot of their portfolio into it. Those are different
# stories, and the second kind often tops the board: a single fund with most of
# its portfolio in one stock (a parent company holding a subsidiary, say) gets
# a very large weight z-score.
#
# **Caveats.**
#
# - The z-scores are computed across the market's held stocks in one run; they
#   are not comparable between markets, quarters or runs.
# - Within one run `consensus_rank` follows the score. Repeated ranks are the
#   sign of mixed runs (section 4.1), which is why we keep only the newest.
# - `total_market_value` is in local currency (yen in Japan, HK dollars in
#   Hong Kong); the portfolio percentages are in percent (2.5 = 2.5%).
# - Filer-reported 13F values can carry unit errors. The check above marks
#   with † a value above 1.5 × the market cap (or, for a company off the
#   fetched screen pages, above 1.5 × the smallest cap fetched): possibly a
#   unit error in the filing, or a price fall since the holdings date, since
#   the values and the caps are dated months apart. Read the position-value
#   piece of those rows with care.
# - Many funds owning a stock tells you it is popular, not that it will rise.

# %% [markdown]
# ### 4.5 Chart: conviction versus crowdedness
#
# **Conviction** asks whether some fund holds the stock in an unusually large
# size. `max_fund_conviction_z` is the strongest single-fund reading among the
# stock's holders (a z-score), and `top_conviction_fund` names that fund.
# `ticker_conviction_score`, the board's ranking measure, is the same number
# when one fund holds the stock; when several do, it blends their readings and
# can sit well below the strongest one (we count both cases below).
# **Crowdedness** asks what share of the funds counted in `n_funds_total` own
# the stock.
#
# The two boards list different stocks, so we need one shared measure. Every
# conviction row carries `n_funds_holding`, and the crowdedness board defines
# `crowdedness_pct = n_funds_holding / n_funds_total`. We verify that identity
# on the crowdedness board, then place both boards on one axis: **the number of
# tracked funds holding the stock**. The axis is logarithmic, because the
# counts run from 1 to dozens, and the number of funds differs hugely between
# markets (about 100 in the US, over 20,000 large-holding filers in Japan), so
# a raw percentage would squash Japan's points against zero.
#
# **Which denominator?** `n_funds_total` is not the roster size from section
# 4.3 (`data.funds.count`). It is smaller: by one or two funds in the US and
# Japan in the live data, and by more than half in Hong Kong. v1 does not
# document which holders it leaves out. Every share in 4.4 and 4.5 divides by
# `n_funds_total`, as SurgeFlow's own `crowdedness_pct` does, so the charts
# name it ("of N funds in n_funds_total") rather than calling it the tracked
# roster. The cell below prints both numbers.

# %%
conviction, crowded = boards["conviction"].copy(), boards["crowdedness"].copy()
if not crowded.empty:
    identity_gap = (crowded["crowdedness_pct"] - crowded["n_funds_holding"] / crowded["n_funds_total"]).abs().max()
    N_FUNDS = float(crowded["n_funds_total"].mode().iloc[0])
    CUT_N = float(crowded["n_funds_holding"].min())           # where the most-crowded list starts
    DENOM = "funds in n_funds_total"                         # how charts name the denominator of every share
    print(f"crowdedness_pct = n_funds_holding / n_funds_total holds (largest gap {identity_gap:.2e}); "
          f"n_funds_total = {N_FUNDS:,.0f}; the {len(crowded)} most crowded in the newest run start at {CUT_N:.0f} "
          f"holders ({CUT_N / N_FUNDS:.2%} of n_funds_total).")
    print(f"Two fund counts: the roster lists {funds_block['count']:,} tracked holders (section 4.3); the crowdedness "
          f"denominator n_funds_total is {N_FUNDS:,.0f}"
          + (f" ({funds_block['count'] - N_FUNDS:,.0f} fewer; v1 does not document why)"
             if N_FUNDS != funds_block["count"] else " (the same)")
          + ". Shares below use n_funds_total.")
else:
    N_FUNDS, CUT_N = float(funds_block["count"]) or np.nan, np.nan     # NaN, not a division by zero
    DENOM = "holders on the roster"
    print("The crowdedness board is empty; we use the roster count for shares instead: "
          + (f"{N_FUNDS:,.0f} holders." if pd.notna(N_FUNDS) else "it is missing too, so shares are unknown."))
N_CROWDED = len(crowded)                                  # 20, or fewer when rows from an earlier run were dropped
if not conviction.empty:
    conviction["crowdedness"] = conviction["n_funds_holding"] / N_FUNDS
    conviction["on_both"] = conviction["ticker"].isin(crowded["ticker"])
    same = (conviction["ticker_conviction_score"] - conviction["max_fund_conviction_z"]).abs() < 1e-6
    print(f"ticker_conviction_score equals max_fund_conviction_z for {int(same.sum())} of {len(conviction)} stocks; "
          f"for the other {int((~same).sum())} (held by {conviction.loc[~same, 'n_funds_holding'].median():.0f} funds "
          f"on the median) the ticker score blends several holders. "
          f"{plural(conviction['on_both'].sum(), 'stock')} on both boards." if (~same).any() else
          f"ticker_conviction_score equals max_fund_conviction_z for all {len(conviction)} stocks. "
          f"{plural(conviction['on_both'].sum(), 'stock')} on both boards.")

# %%
if conviction.empty:
    display(Markdown("> The conviction board is empty, so there is nothing to plot."))
else:
    below = int((conviction["n_funds_holding"] < CUT_N).sum()) if pd.notna(CUT_N) else None
    single = int((conviction["n_funds_holding"] <= 1).sum())
    counts = pd.concat([conviction["n_funds_holding"], crowded["n_funds_holding"]]).dropna()
    x_lo, x_hi = np.log10(max(counts.min(), 1) * 0.75), np.log10(max(counts.max(), 2) * 1.5)   # log10 units
    tickvals = [v for v in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000)
                if x_lo <= np.log10(v) <= x_hi]
    y_lo = max(0.0, float(conviction["ticker_conviction_score"].min()) - 0.6)
    y_hi = float(conviction["ticker_conviction_score"].max()) + 0.8
    # Precision from the smallest share, so a non-zero share never shows as 0% (1 of 718 funds = 0.14%).
    share = "%{customdata[6]:.2%}" if conviction["crowdedness"].min() < 0.01 else "%{customdata[6]:.0%}"
    conviction["funds_word"] = np.where(conviction["n_funds_holding"] == 1, "fund", "funds")

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.8, 0.2], vertical_spacing=0.05)
    for both, name, colour in [(False, "Conviction board", COLOR), (True, "On both boards", INK)]:
        part = conviction[conviction["on_both"] == both]
        if part.empty:
            continue
        fig.add_trace(go.Scatter(
            x=part["n_funds_holding"], y=part["ticker_conviction_score"], mode="markers", name=name,
            marker=dict(size=12, color=colour, opacity=0.85),
            customdata=part[["display_name", "ticker", "n_funds_holding", "top_conviction_fund",
                             "ticker_conviction_rank", "max_fund_conviction_z", "crowdedness",
                             "funds_word"]].to_numpy(),
            hovertemplate=("<b>%{customdata[0]}</b> (%{customdata[1]})<br>Conviction %{y:.2f} (rank "
                           f"%{{customdata[4]}})<br>Held by %{{x}} %{{customdata[7]}} = {share} of "
                           f"{N_FUNDS:,.0f} {DENOM}"
                           "<br>Top conviction fund: %{customdata[3]} (z %{customdata[5]:.2f})<extra></extra>")),
            row=1, col=1)
    if not crowded.empty:
        strip = crowded.sort_values("n_funds_holding").reset_index(drop=True)
        strip["y"] = [(-1) ** i * 0.25 for i in range(len(strip))]        # alternate up/down to avoid overlap
        fig.add_trace(go.Scatter(
            x=strip["n_funds_holding"], y=strip["y"], mode="markers",
            name=f"{N_CROWDED} most crowded in the newest run (no conviction score)",
            marker=dict(size=9, color=MUTED, symbol="line-ns-open", line=dict(width=2, color=MUTED)),
            customdata=strip[["display_name", "ticker", "crowdedness_pct", "crowdedness_quintile"]].to_numpy(),
            hovertemplate=("<b>%{customdata[0]}</b> (%{customdata[1]})<br>Held by %{x} funds = "
                           f"%{{customdata[2]:.2%}} of {N_FUNDS:,.0f} funds in n_funds_total<br>Crowdedness quintile "
                           "%{customdata[3]} "
                           "(1 = most crowded)<extra></extra>")), row=2, col=1)
        for r, (lo, hi) in [(1, (y_lo, y_hi)), (2, (-0.6, 0.6))]:        # a line trace: shapes are awkward on log axes
            fig.add_trace(go.Scatter(x=[CUT_N, CUT_N], y=[lo, hi], mode="lines", showlegend=False, hoverinfo="skip",
                                     line=dict(color=INK_2, width=1, dash="dash")), row=r, col=1)
        near_right = (np.log10(CUT_N) - x_lo) / (x_hi - x_lo) > 0.65          # keep the note inside the plot
        fig.add_annotation(x=np.log10(CUT_N), y=1, yref="y domain",              # log axis: x in log10 units
                           text=f"most-crowded list starts ({CUT_N:.0f} funds)",
                           showarrow=False, xanchor="right" if near_right else "left", xshift=-6 if near_right else 6,
                           yanchor="top", font=dict(size=11, color=INK_2), row=1, col=1)
        fig.add_annotation(x=x_lo, y=0, text=f"The {N_CROWDED} most crowded stocks →", showarrow=False,
                           xanchor="left", xshift=4, font=dict(size=11, color=INK_2), row=2, col=1)
    conviction = conviction.sort_values("ticker_conviction_score", ascending=False).reset_index(drop=True)
    wanted = conviction.index[:LABEL_TOP].union(conviction.index[conviction["on_both"]])  # label selectively
    names = [t if i in wanted else None for i, t in enumerate(conviction["ticker"])]
    for spot in place_labels(np.log10(conviction["n_funds_holding"]), conviction["ticker_conviction_score"], names,
                             width=880, height=300, x_range=(x_lo, x_hi), y_range=(y_lo, y_hi)):
        i = spot.pop("index")
        fig.add_annotation(x=np.log10(conviction["n_funds_holding"].iloc[i]),
                           y=conviction["ticker_conviction_score"].iloc[i], font=dict(size=11, color=INK_2),
                           row=1, col=1, **spot)
    for r in (1, 2):
        fig.update_xaxes(type="log", range=[x_lo, x_hi], tickvals=tickvals, ticktext=[f"{v:,}" for v in tickvals],
                         row=r, col=1)
    fig.update_xaxes(title_text="Tracked funds holding the stock (log scale)", row=2, col=1)
    fig.update_yaxes(title_text="Conviction score (z)", range=[y_lo, y_hi], row=1, col=1)
    fig.update_yaxes(visible=False, range=[-0.6, 0.6], row=2, col=1)
    if below is None:
        headline = f"The median conviction name is held by {conviction['n_funds_holding'].median():.0f} tracked funds"
    elif below >= len(conviction) / 2:
        headline = (f"High conviction is rarely crowded: {below} of {len(conviction)} conviction names are held "
                    f"by fewer funds than any of the {N_CROWDED} most crowded")
    else:
        headline = f"{len(conviction) - below} of {len(conviction)} conviction names are also widely held"
    fig.update_layout(
        title=dict(text=headline,
                   subtitle=dict(text=(f"{single} held by a single fund · " if single else "")
                                 + f"shares of {N_FUNDS:,.0f} {DENOM} · holdings as of {holdings_date:%Y-%m-%d} · "
                                   f"gates: conviction {GATE['conviction']}, crowdedness {GATE['crowdedness']}")),
        height=580, margin=dict(t=110, b=120), legend=dict(orientation="h", x=0, y=-0.14, yanchor="top"))
    fig.show()

    display(conviction.sort_values("ticker_conviction_rank")[
        ["ticker_conviction_rank", "ticker", "display_name", "ticker_conviction_score", "max_fund_conviction_z",
         "n_funds_holding", "crowdedness", "on_both", "top_conviction_fund"]]
        .style.format({"ticker_conviction_score": "{:.2f}", "max_fund_conviction_z": "{:.2f}",
                       "n_funds_holding": "{:.0f}", "crowdedness": "{:.2%}"})
        .hide(axis="index"))
    if not crowded.empty:
        print(f"The strip: the {N_CROWDED} most crowded stocks in the newest run.")
        display(crowded.sort_values("crowdedness_rank")[["crowdedness_rank", "ticker", "display_name",
                                                         "n_funds_holding", "crowdedness_pct", "crowdedness_quintile"]]
                .style.format({"n_funds_holding": "{:.0f}", "crowdedness_pct": "{:.2%}",
                               "crowdedness_rank": "{:.0f}", "crowdedness_quintile": "{:.0f}"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** In the main panel, each dot is a stock on the conviction
# board: higher means some fund's bet on it is more unusual; further right means
# more of the tracked funds own it (each step on the log axis multiplies the
# count). The strip underneath shows where the N most crowded stocks in the
# newest run sit on the same axis (N is 20, or fewer when rows from an earlier
# run were dropped; they have no conviction score), and the dashed line marks
# where that crowded list begins; the second table lists them. Dots on the
# left are **concentrated bets**: one or a few funds, big positions. Dots on
# the right are the popular names that many funds own. Dark dots appear on
# both boards.
#
# **Caveats.**
#
# - Both boards are top-20 slices. Do not compute a correlation from them: a
#   list cut at the top hides most of the range (statisticians call this range
#   restriction), so any correlation would mislead.
# - A single-fund name can score very high on conviction because that one
#   fund's portfolio is concentrated. Check `n_funds_holding` before you read
#   "conviction" as agreement.
# - Crowdedness counts holders, not money. A stock held by 80% of funds in tiny
#   amounts is "crowded" here.
# - In Japan and Hong Kong "funds" means every large-holding filer, and only
#   stakes of 5% or more are visible, so even the most crowded stock is held by
#   a tiny share of `n_funds_total`. Compare counts within a market, not across.

# %% [markdown]
# ### 4.6 Chart: position deltas, buyers against sellers
#
# The position-delta board compares each fund's latest filing with its previous
# one. For every stock it counts the funds that added shares
# (`n_funds_buying`) and cut shares (`n_funds_selling`), and sums the shares
# bought (`gross_shares_buying`, positive) and sold (`gross_shares_selling`,
# recorded as a **negative** number). So `net_shares_change` is
# `gross_shares_buying + gross_shares_selling`; we check that identity below.
# The board lists the top-20 stocks by `delta_z`, the z-scored net change
# (fewer when rows from an earlier run are dropped), so by construction it
# shows the **most-bought** names.
#
# Share counts cannot be compared across stocks (a share of one company can
# cost a hundred times a share of another). So we add one scale-free measure,
# the **net buying share**: net shares ÷ (shares bought + shares sold), with
# shares sold counted as a positive amount. It runs from −100% (every share
# funds traded was a sale) to +100% (every share was a purchase). **NaN
# policy:** a stock with no shares traded gets NaN, not 0, because "no trading"
# is not "balanced trading".

# %%
delta = boards["position_delta"].copy()
if not delta.empty:
    wrong_sign = int((delta["gross_shares_selling"] > 0).sum())
    delta["shares_bought"] = delta["gross_shares_buying"]
    delta["shares_sold"] = -delta["gross_shares_selling"]          # sales arrive negative; make them a positive amount
    traded = delta["shares_bought"] + delta["shares_sold"]
    delta["net_buying_share"] = (delta["net_shares_change"] / traded).where(traded > 0)
    delta["net_funds"] = delta["n_funds_buying"] - delta["n_funds_selling"]
    gap = (delta["shares_bought"] - delta["shares_sold"] - delta["net_shares_change"]).abs().max()
    print(f"Sign check: {wrong_sign} of {len(delta)} rows have a positive gross_shares_selling (expected 0). "
          f"Identity net = bought − sold: largest gap {big_number(gap)} shares. "
          f"net_buying_share is NaN for {int(delta['net_buying_share'].isna().sum())} of {len(delta)} rows.")
ALL_ZERO = delta.empty or bool((delta[["n_funds_buying", "n_funds_selling", "net_shares_change"]] == 0).all().all())

# %%
if delta.empty:
    display(Markdown("> The position-delta board is empty, so there is nothing to plot."))
elif ALL_ZERO:
    display(Markdown("> Every row on this board is 0 (funds buying, funds selling, net shares, `delta_z`), so its "
                     "ranks are ties and its order means nothing. The board looks **unpopulated** for this period: "
                     "read the zeros as missing, not as \"funds did not trade\". Treat the board as unavailable and "
                     "check again after a later run. There is nothing to chart."))
    holders = boards["ll_predictive"]
    if not holders.empty and (holders["owner_count_change"] != 0).any():
        n_moved = int((holders["owner_count_change"] != 0).sum())
        print(f"Cross-check: the ll_predictive board from the same payload shows {n_moved} of {len(holders)} stocks "
              f"changing their number of holders between periods (largest change "
              f"{holders['owner_count_change'].abs().max():.0f}), so the zeros here are a data gap, not a quiet "
              "quarter.")
    display(delta.sort_values("ticker")[["ticker", "display_name", "n_funds_buying", "n_funds_selling",
                                         "net_shares_change", "delta_z"]].style.hide(axis="index"))
else:
    bars = delta.sort_values("delta_rank").reset_index(drop=True)
    M = float(max(bars["n_funds_buying"].max(), bars["n_funds_selling"].max(), 1)) * 1.12
    blue, red = DIVERGING[3][1], DIVERGING[1][1]
    bars["buy_text"] = bars["gross_shares_buying"].map(big_number)
    bars["sell_text"] = bars["shares_sold"].map(big_number)
    bars["net_text"] = bars["net_shares_change"].map(big_number)
    n_net_buy = int((bars["net_funds"] > 0).sum())
    n_buy_only = int(((bars["shares_sold"] == 0) & (bars["shares_bought"] > 0)).sum())
    lead = (bars.loc[bars["net_buying_share"].abs().idxmax()] if bars["net_buying_share"].notna().any()
            else bars.iloc[0])                                  # the most one-sided flow, buying or selling
    flow_note = (f"{n_buy_only} saw purchases and no sales" if n_buy_only else
                 f"{lead['ticker']} was the most one-sided ({lead['net_buying_share']:+.0%})")

    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, column_widths=[0.56, 0.44], horizontal_spacing=0.03,
                        subplot_titles=("Funds selling  ◀  |  ▶  funds buying",
                                        "Net buying share of shares traded"))
    fig.add_trace(go.Bar(
        y=bars["label"], x=-bars["n_funds_selling"], name="Funds selling", orientation="h", marker=dict(color=red),
        customdata=bars[["n_funds_selling", "sell_text"]].to_numpy(),
        hovertemplate="<b>%{y}</b><br>%{customdata[0]} funds sold %{customdata[1]} shares<extra></extra>"),
        row=1, col=1)
    fig.add_trace(go.Bar(
        y=bars["label"], x=bars["n_funds_buying"], name="Funds buying", orientation="h", marker=dict(color=blue),
        customdata=bars[["n_funds_buying", "buy_text"]].to_numpy(),
        hovertemplate="<b>%{y}</b><br>%{customdata[0]} funds bought %{customdata[1]} shares<extra></extra>"),
        row=1, col=1)
    fig.add_trace(go.Bar(
        y=bars["label"], x=bars["net_buying_share"], orientation="h", showlegend=False,
        marker=dict(color=bars["net_buying_share"], colorscale=DIVERGING, cmin=-1, cmax=1),
        text=bars["net_buying_share"].map(lambda v: "n/a" if pd.isna(v) else f"{v:+.0%}"), textposition="outside",
        cliponaxis=False, textfont=dict(size=11, color=INK_2),
        customdata=bars[["net_text", "delta_z", "delta_rank"]].to_numpy(),
        hovertemplate=("<b>%{y}</b><br>Net buying share %{x:+.0%}<br>Net shares %{customdata[0]}<br>"
                       "delta_z %{customdata[1]:.2f} (rank %{customdata[2]})<extra></extra>")), row=1, col=2)
    for col in (1, 2):
        fig.add_vline(x=0, line=dict(color=INK_2, width=1), row=1, col=col)
    step = 10 if M > 30 else 5 if M > 12 else 2 if M > 5 else 1          # a round tick step
    ticks = np.arange(-np.floor(M / step) * step, np.floor(M / step) * step + step / 2, step)
    fig.update_xaxes(range=[-M, M], title_text="Number of funds", row=1, col=1,
                     tickvals=ticks, ticktext=[f"{abs(v):.0f}" for v in ticks])
    fig.update_xaxes(range=[-1.25, 1.25], tickvals=[-1, -0.5, 0, 0.5, 1], tickformat="+.0%",
                     title_text="Net shares ÷ shares traded", row=1, col=2)
    fig.update_yaxes(autorange="reversed", ticks="")
    fig.update_layout(
        title=dict(text=f"More funds bought than sold in {n_net_buy} of the {len(bars)} names on the board; "
                        f"{flow_note}",
                   subtitle=dict(text=f"Change between the last two filings · holdings as of "
                                      f"{holdings_date:%Y-%m-%d} · gate: {GATE['position_delta']} · "
                                      "blue = buying, red = selling")),
        barmode="relative", height=200 + 30 * len(bars), margin=dict(t=120, l=10, r=40, b=110),
        legend=dict(orientation="h", x=0, y=below_plot(200 + 30 * len(bars), 120, 110), yanchor="top"))
    fig.show()

    display(bars[["delta_rank", "ticker", "display_name", "n_funds_buying", "n_funds_selling", "buy_text",
                  "sell_text", "net_text", "net_buying_share", "delta_z"]]
            .style.format({"net_buying_share": "{:+.0%}", "delta_z": "{:.2f}"}, na_rep="n/a").hide(axis="index"))

# %% [markdown]
# **How to read this.** When the chart is drawn (it is skipped when every
# delta is zero), red bars to the left in the left panel count the funds that
# cut the stock and blue bars to the right count the funds that added to it;
# the axis is symmetric so equal counts look equal. The right panel says how
# one-sided the share flow was, on the same blue-red scale with grey at zero:
# +100% means funds only bought, 0% means buying and selling cancelled out.
# Rows follow the board's own `delta_rank`.
#
# **Caveats.**
#
# - The board is the top 20 by net buying, so it leans to buying by design. The
#   most-sold names are not on it; do not conclude that "funds are bullish".
# - A delta compares two filing dates. It does not say when the trades happened
#   between them, or at what price.
# - Share counts change with splits. A stock split between two filings looks
#   like heavy buying unless the data adjusts for it.
# - A fund that enters or leaves the tracked roster can appear as a buyer or a
#   seller.
# - In Japan and Hong Kong a "buyer" is a holder whose new large-holding report
#   shows a bigger stake. Each stock has only a few such reports, so the
#   most-bought 20 often show no sellers at all and a net buying share of +100%.

# %% [markdown]
# ### 4.7 Network reads: who sits at the centre?
#
# Imagine a graph in which stocks are linked when they share holders: the more
# funds own both, the stronger the link. SurgeFlow publishes per-stock
# **summaries** of that graph, not the links themselves:
#
# - **degree**: how many other stocks this one is linked to;
# - **weighted_degree**: the sum of the link strengths;
# - **eigenvector_centrality**: high when a stock is linked to other
#   well-linked stocks: the core of the shared-ownership web;
# - **community_id**: a group of stocks more tightly linked to each other than
#   to the rest, found by a community-detection algorithm;
# - **modularity**: how clear the community split is for the whole graph. Near
#   0 there is little structure; above about 0.3 the communities are distinct.
#
# The board lists the top-20 stocks by weighted degree (fewer when rows from an
# earlier run are dropped): the most strongly linked ones. The chart asks
# whether "many links" also means "at the core": it plots weighted degree
# against eigenvector centrality and colours each stock by its community.

# %%
net = boards["network"].copy()
if net.empty:
    display(Markdown("> The network board is empty, so there is nothing to plot."))
else:
    net["community"] = "Community " + net["community_id"].astype("Int64").astype(str)
    comm = (net.groupby("community").agg(top20=("ticker", "size"), community_size=("n_tickers_in_community", "first"),
                                         best=("eigenvector_centrality", "max"))
            .sort_values(["top20", "best"], ascending=False))
    # At most three colours: the two communities with most top-20 members, then everything else in grey.
    shown = list(comm.index[:2])
    net["colour_group"] = net["community"].where(net["community"].isin(shown), "Other communities")
    group_colour = {**dict(zip(shown, [COLOR, INK_2])), "Other communities": AXIS}
    net = net.sort_values("eigenvector_centrality", ascending=False).reset_index(drop=True)
    modularity, n_comm = float(net["modularity"].iloc[0]), int(net["n_communities"].iloc[0])
    strength = "weak" if modularity < 0.3 else "clear" if modularity < 0.7 else "very strong"
    lead, top_comm = net.iloc[0], comm.index[0]
    # Two centralities within 0.5% of each other are a tie in practice: name both rather than crown one.
    tied_core = (len(net) > 1 and net["eigenvector_centrality"].iloc[1]
                 >= net["eigenvector_centrality"].iloc[0] * (1 - 0.005))
    core_text = (f"{lead['ticker']} and {net['ticker'].iloc[1]} sit at the core of shared ownership (tied)"
                 if tied_core else f"{lead['ticker']} sits nearest the core of shared ownership")
    rho = net[["weighted_degree", "eigenvector_centrality"]].corr(method="spearman").iloc[0, 1]

    fig = go.Figure()
    for group, colour in group_colour.items():
        part = net[net["colour_group"] == group]
        if part.empty:
            continue
        size = int(comm.loc[group, "community_size"]) if group in comm.index else None
        fig.add_trace(go.Scatter(
            x=part["weighted_degree"], y=part["eigenvector_centrality"], mode="markers",
            name=f"{group} ({size:,} stocks)" if size else group,
            marker=dict(size=13, color=colour, opacity=0.85, line=dict(width=1, color=SURFACE)),
            customdata=part[["display_name", "ticker", "degree", "community", "n_tickers_in_community"]].to_numpy(),
            hovertemplate=("<b>%{customdata[0]}</b> (%{customdata[1]})<br>Eigenvector centrality %{y:.3f}<br>"
                           "Weighted degree %{x:,.0f} · degree %{customdata[2]:,}<br>"
                           "%{customdata[3]} (%{customdata[4]:,} stocks)<extra></extra>")))
    names = [t if i < LABEL_TOP else None for i, t in enumerate(net["ticker"])]      # label the most central few
    for spot in place_labels(net["weighted_degree"], net["eigenvector_centrality"], names, width=820, height=330):
        i = spot.pop("index")
        fig.add_annotation(x=net["weighted_degree"].iloc[i], y=net["eigenvector_centrality"].iloc[i],
                           font=dict(size=11, color=INK_2), **spot)
    fig.update_xaxes(title_text="Weighted degree (sum of shared-holder link strengths)")
    fig.update_yaxes(title_text="Eigenvector centrality")
    fig.update_layout(
        title=dict(text=f"{core_text}; {int(comm.loc[top_comm, 'top20'])} of the {len(net)} best-linked stocks "
                        f"are in {top_comm.lower()}",
                   subtitle=dict(text=f"Top {len(net)} by weighted degree · {n_comm:,} communities in the full "
                                      "graph · "
                                      f"modularity {modularity:.2f} ({strength} community structure) · rank "
                                      f"correlation of the two axes {rho:+.2f} · gate: {GATE['network']}")),
        height=520, margin=dict(t=110, b=110), showlegend=True,
        legend=dict(orientation="h", x=0, y=-0.18, yanchor="top"))
    fig.show()
    display(comm.rename(columns={"top20": "stocks on the board", "community_size": "stocks in the community",
                                 "best": "highest centrality"}).style.format({"highest centrality": "{:.3f}"}))
    display(net[["ticker", "display_name", "degree", "weighted_degree", "eigenvector_centrality", "community"]]
            .style.format({"weighted_degree": "{:,.0f}", "eigenvector_centrality": "{:.4f}"})
            .hide(axis="index"))

# %% [markdown]
# **How to read this.** Each dot is one of the best-linked stocks on the
# board. Further right means stronger links in total; higher up means its
# links lead to other well-linked stocks, i.e. it sits at the core. The two
# often agree (the rank correlation in the subtitle says how closely), but a
# stock can have many weak links on the edge of the web. The colours show communities: when one colour
# dominates, the core of the funds' shared ownership is a single group of
# stocks that many funds hold together, often the market's largest companies.
#
# **Caveats.**
#
# - Community numbers are labels; community 3 is not "bigger" than community 1.
# - The correlation is computed on the board's hand-picked stocks, so treat it as a
#   description of this list, not of the market.
# - A low modularity means the communities overlap heavily. Do not read too
#   much into one stock's community when the split is weak.
# - Centrality measures position in the ownership web, not quality. Popular
#   holdings are central almost by definition.

# %% [markdown]
# ### 4.8 Chart: a holder → stock graph with `networkx`
#
# The network board does not publish its links, and the payload carries no
# fund-by-fund holdings list, so we cannot redraw SurgeFlow's co-holding graph
# or compute a full co-holding matrix. We can still build a **real** graph from
# what the payload does say: each conviction row names its
# `top_conviction_fund`. That gives one link per stock, from the fund with the
# boldest position to the stock.
#
# `networkx` is Python's standard graph library. We build a **bipartite** graph
# (two kinds of node: funds and stocks; links only run between the kinds), then
# ask it simple questions: how many stocks does each fund lead, how many
# separate pieces does the graph have, and which stocks share a lead fund (the
# "projection" onto stocks).

# %%
links = conviction.dropna(subset=["top_conviction_fund"]) if not conviction.empty else conviction
G = nx.Graph()
for _, row in links.iterrows():
    fund, stock = ("fund", row["top_conviction_fund"]), ("stock", row["ticker"])
    G.add_node(fund, kind="fund")
    G.add_node(stock, kind="stock", score=row["ticker_conviction_score"], name=row["display_name"])
    G.add_edge(fund, stock, weight=row["ticker_conviction_score"])

fund_nodes = [n for n, d in G.nodes(data=True) if d["kind"] == "fund"]
stock_nodes = [n for n, d in G.nodes(data=True) if d["kind"] == "stock"]
if G.number_of_nodes():
    projected = nx.bipartite.weighted_projected_graph(G, stock_nodes)   # stocks linked by a shared lead fund
    print(f"Graph: {len(fund_nodes)} funds, {len(stock_nodes)} stocks, {G.number_of_edges()} links, "
          f"{nx.number_connected_components(G)} separate pieces.")
    print(f"Projected onto stocks: {plural(projected.number_of_edges(), 'pair')} of stocks share a lead fund.")
    # The roster (cleaned in 4.3) is keyed by fund_id; a few names repeat (Japan), so keep one row per name.
    by_name = (roster.sort_values("total_holdings", ascending=False)
               .drop_duplicates(subset="fund_name")[["fund_name", "quarters", "records_per_period"]])
    fund_table = (pd.DataFrame({"fund": [f[1] for f in fund_nodes],
                                "stocks led": [G.degree(f) for f in fund_nodes],
                                "stocks": [", ".join(sorted(s[1] for s in G.neighbors(f))) for f in fund_nodes]})
                  .merge(by_name, left_on="fund", right_on="fund_name", how="left", validate="one_to_one")
                  .drop(columns="fund_name")
                  .sort_values(["stocks led", "fund"], ascending=[False, True]).reset_index(drop=True))
    print(f"{int(fund_table['quarters'].notna().sum())} of {len(fund_table)} lead funds are in the "
          "tracked roster (the rest have no roster details).")
else:
    fund_table = pd.DataFrame(columns=["fund", "stocks led", "stocks", "quarters", "records_per_period"])
    print("No conviction links, so the graph is empty.")

# %% [markdown]
# **Layout.** We place funds in a left column and stocks in a right column.
# Each stock has exactly one lead fund, so if we list stocks fund by fund and
# put each fund level with the middle of its stocks, no two links cross. Funds
# that lead several stocks come first.

# %%
if not G.number_of_nodes():
    display(Markdown("> The conviction board is empty, so there is no graph to draw."))
else:
    fund_order = fund_table["fund"].tolist()
    stock_order = [s for f in fund_order
                   for s in sorted((n[1] for n in G.neighbors(("fund", f))),
                                   key=lambda t: -G.nodes[("stock", t)]["score"])]
    n_rows = len(stock_order)
    pos = {("stock", s): (1.0, 1 - i / max(n_rows - 1, 1)) for i, s in enumerate(stock_order)}
    for f in fund_order:
        ys = [pos[n][1] for n in G.neighbors(("fund", f))]
        pos[("fund", f)] = (0.0, float(np.mean(ys)))
    multi = {f for f in fund_order if G.degree(("fund", f)) > 1}

    fig = go.Figure()
    for is_multi, colour, width in [(False, AXIS, 1.2), (True, COLOR, 2.4)]:
        xs, ys = [], []
        for (a, b) in G.edges():
            fund, stock = (a, b) if a[0] == "fund" else (b, a)
            if (fund[1] in multi) == is_multi:
                xs += [pos[fund][0], pos[stock][0], None]
                ys += [pos[fund][1], pos[stock][1], None]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=colour, width=width),
                                 hoverinfo="skip", showlegend=False))
    degree = [G.degree(("fund", f)) for f in fund_order]
    scores = [G.nodes[("stock", s)]["score"] for s in stock_order]
    fund_xy = ([pos[("fund", f)][0] for f in fund_order], [pos[("fund", f)][1] for f in fund_order])
    stock_xy = ([1.0] * n_rows, [pos[("stock", s)][1] for s in stock_order])
    fund_size, stock_size = [8 + 5 * d for d in degree], [8 + 2.2 * v for v in scores]
    # Labels sit in their own traces, kept out of the legend: a legend entry for a trace with text shows an "Aa"
    # sample. Their invisible markers have the real sizes, so Plotly sets each label clear of its marker.
    fig.add_trace(go.Scatter(
        x=fund_xy[0], y=fund_xy[1], mode="markers+text", text=[shorten(f, 30) for f in fund_order],
        textposition="middle left", textfont=dict(size=11, color=INK_2), marker=dict(size=fund_size, opacity=0),
        showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=stock_xy[0], y=stock_xy[1], mode="markers+text", text=[f"{s}  {v:.1f}" for s, v in zip(stock_order, scores)],
        textposition="middle right", textfont=dict(size=11, color=INK_2), marker=dict(size=stock_size, opacity=0),
        showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=fund_xy[0], y=fund_xy[1], mode="markers", name="Fund (size = stocks led)",
        marker=dict(symbol="square", size=fund_size, color=INK_2, line=dict(width=1, color=SURFACE)),
        customdata=np.column_stack([fund_order, degree]),
        hovertemplate="<b>%{customdata[0]}</b><br>Lead fund for %{customdata[1]} stock(s)<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=stock_xy[0], y=stock_xy[1], mode="markers", name="Stock (size = conviction)",
        marker=dict(size=stock_size, color=COLOR, line=dict(width=1, color=SURFACE)),
        customdata=np.column_stack([stock_order, [G.nodes[("stock", s)]["name"] for s in stock_order], scores]),
        hovertemplate=("<b>%{customdata[1]}</b> (%{customdata[0]})<br>Conviction score %{customdata[2]:.2f}"
                       "<extra></extra>")))
    fig.update_xaxes(visible=False, range=[-1.05, 1.45])
    fig.update_yaxes(visible=False, range=[-0.06, 1.06])
    if multi:
        top_fund = fund_table.iloc[0]
        headline = (f"{plural(len(multi), 'fund')} lead{'s' if len(multi) == 1 else ''} more than one "
                    f"high-conviction stock; {shorten(top_fund['fund'], 40)} leads {top_fund['stocks led']}")
    else:
        headline = "Every high-conviction stock has a different lead fund"
    fig.update_layout(
        title=dict(text=headline,
                   subtitle=dict(text="Each link joins a conviction-board stock to its top_conviction_fund · "
                                      "coloured links: funds behind 2+ stocks · number = conviction score")),
        height=170 + 26 * n_rows, margin=dict(t=100, l=10, r=10, b=60), plot_bgcolor=SURFACE,
        legend=dict(orientation="h", x=0, y=-0.02, yanchor="top"))
    fig.show()
    display(fund_table.style.format({"quarters": "{:.0f}", "records_per_period": "{:,.1f}"}, na_rep="not in roster")
            .hide(axis="index"))
    pairs = pd.DataFrame([(a[1], b[1], d["weight"]) for a, b, d in projected.edges(data=True)],
                         columns=["stock A", "stock B", "shared lead funds"])
    if not pairs.empty:
        display(pairs.style.hide(axis="index"))

# %% [markdown]
# **How to read this.** Squares on the left are funds; circles on the right are
# stocks from the conviction board, sized by their conviction score (printed
# next to the ticker). A line means "this fund holds the boldest position in
# this stock". Coloured lines fan out from funds that lead several stocks: those
# funds run concentrated portfolios across more than one name. The table lists
# each fund's stocks and, when the fund is on the tracked roster, its reporting
# periods on file and its holding records per period (a record count, not the
# number of stocks it holds; see 4.3). The second table is the projection: pairs of
# stocks that share a lead fund.
#
# **Caveats.**
#
# - This graph keeps **one** link per stock, the strongest. Other funds hold
#   these stocks too; a full co-holding graph would need every fund's holdings,
#   which v1 does not send.
# - A fund leading two stocks says something about the fund's style, not about
#   a link between the two businesses.
# - A "fund" is whoever filed. In Japan the busiest filers are often custodian
#   trust accounts (names containing 信託口, "trust account") and banks that
#   hold shares for many clients, and the same institution can appear under
#   slightly different spellings. Treat a name as a filing account, not as one
#   decision-maker.

# %% [markdown]
# ### 4.9 Chart: which stocks gained holders?
#
# The `ll_predictive` board ranks stocks by how many holders they gained
# between two reporting periods. For each stock it gives the number of holders
# now (`n_funds_holding_q`) and in the previous period
# (`n_funds_holding_q_minus_1`), the change (`owner_count_change`), SurgeFlow's
# weight-change measure (`portfolio_weight_change`), and `ll_score_z`, the
# z-scored change the board is sorted by. The board's name says "predictive";
# here it is a **description of filings**, and its gate (section 4.2) says how
# little it has been tested.
#
# Three checks before the chart:
#
# - **NaN policy for the previous count.** A previous count of 0 is only
#   believable when every current holder is new, that is when
#   `owner_count_change` equals the current count. When the change is smaller
#   (0 → 5 holders but a change of 4, say), the 0 cannot be a real count: it
#   stands for "not available". We set those previous counts to NaN and count
#   them. Such a stock **did** have earlier holders: the API's own numbers
#   imply now − change of them (5 − 4 = 1 in the example). We add that
#   `implied_previous` as a separate column and draw it as a hollow diamond on
#   a dotted line, labelled as inferred, so every row shows its gain while the
#   0 placeholder is never used as a count. Only a consistent 0 is a start from
#   zero, and even that may mean the stock is new to the data (a recent
#   listing, or a holder roster that only began this period) rather than newly
#   bought.
# - Is `owner_count_change` simply now − before, where a previous count is
#   available? We count the rows where it is not, and keep the API's own
#   number on the table.
# - **What unit is `portfolio_weight_change`?** In the US it behaves like the
#   sum of the holders' weight changes in percentage points (a stock going from
#   0 to 20 holders shows about 20 × its average portfolio weight). Elsewhere it
#   does not: in Japan some stocks with no previous holders show a negative
#   value, which a sum of weight changes starting from zero cannot be, and
#   China's values change scale from run to run. So we treat it as SurgeFlow's
#   weight-change measure, with units confirmed only for the US, and count the
#   rows that break the sum reading.

# %%
gainers = boards["ll_predictive"].copy()
if gainers.empty:
    display(Markdown("> The ll_predictive board is empty, so there is nothing to plot."))
else:
    zero_prev = gainers["n_funds_holding_q_minus_1"] == 0
    prev_missing = zero_prev & (gainers["owner_count_change"] < gainers["n_funds_holding_q"])
    gainers["previous_count"] = gainers["n_funds_holding_q_minus_1"].mask(prev_missing)    # NaN = not available
    gainers["difference"] = gainers["n_funds_holding_q"] - gainers["previous_count"]
    # Inferred, not reported: the previous count the API's own change implies (now - change), only where it is NaN.
    gainers["implied_previous"] = (gainers["n_funds_holding_q"] - gainers["owner_count_change"]).where(prev_missing)
    from_zero, n_missing = int((zero_prev & ~prev_missing).sum()), int(prev_missing.sum())
    print(f"Previous count: {from_zero} of {len(gainers)} stocks start from 0 holders (consistent with their change); "
          f"{n_missing} show 0 but a change smaller than the current count, so their previous count is not "
          "available -> NaN." + (f" Their change implies {gainers['implied_previous'].min():.0f} to "
                                 f"{gainers['implied_previous'].max():.0f} earlier holders (now − change): they were "
                                 "held before, so they are not first appearances." if n_missing else ""))
    has_prev = gainers["previous_count"].notna()
    mismatch = int((has_prev & (gainers["difference"] != gainers["owner_count_change"])).sum())
    print(f"owner_count_change differs from (now − before) on {mismatch} of the {int(has_prev.sum())} rows with a "
          "previous count" + ("; so wherever both counts are reported the change is exactly now − before, which is "
                              "what the implied count assumes." if n_missing and has_prev.any() and not mismatch
                              else "."))
    if mismatch:
        smaller = int((has_prev & (gainers["owner_count_change"] < gainers["difference"])).sum())
        print(f"On {smaller} of those {mismatch} rows the API's change is smaller than the plain difference, so it "
              "does not count every current holder as new. The payload has no holder lists, so we cannot see why; "
              "the table shows both numbers" + (", and the implied previous counts may be too high." if n_missing
                                                 else "."))
    negative = int((zero_prev & (gainers["portfolio_weight_change"] < 0)).sum())
    print(f"portfolio_weight_change: {negative} of the {int(zero_prev.sum())} stocks with no previous holders have a "
          "negative value" + (", which a sum of weight changes starting from zero cannot be: its units are not "
                              "those of a sum here." if negative else "."))
    WEIGHT_UNIT = ("pp, summed over holders" if MARKET == "us" and not negative
                   else "SurgeFlow's measure; units vary by market and run")

    bars = gainers.sort_values("ll_rank").reset_index(drop=True)
    bars["previous_text"] = [f"{p:.0f}" if pd.notna(p) else
                             f"not available; implied {i:.0f} (now − change)" if pd.notna(i) else "not available"
                             for p, i in zip(bars["previous_count"], bars["implied_previous"])]
    lead = bars.iloc[0]
    fig = go.Figure()
    for _, row in bars.iterrows():                       # one connector per stock: before (or implied) -> now
        reported = pd.notna(row["previous_count"])
        fig.add_trace(go.Scatter(x=[row["previous_count"] if reported else row["implied_previous"],
                                    row["n_funds_holding_q"]],
                                 y=[row["label"], row["label"]], mode="lines", hoverinfo="skip", showlegend=False,
                                 line=dict(color=GRID, width=4) if reported else dict(color=MUTED, width=1.5,
                                                                                      dash="dot")))
    known_prev = bars[bars["previous_count"].notna()]
    fig.add_trace(go.Scatter(
        x=known_prev["previous_count"], y=known_prev["label"], mode="markers", name="Previous period",
        marker=dict(size=11, color=SURFACE, line=dict(width=2, color=MUTED)),
        hovertemplate="<b>%{y}</b><br>Previous period: %{x} holders<extra></extra>"))
    implied = bars[bars["implied_previous"].notna()]
    if not implied.empty:
        fig.add_trace(go.Scatter(
            x=implied["implied_previous"], y=implied["label"], mode="markers",
            name="Implied previous (now − change; inferred, not reported)",
            marker=dict(size=11, symbol="diamond", color=SURFACE, line=dict(width=1.5, color=MUTED)),
            hovertemplate=("<b>%{y}</b><br>Implied previous period: %{x} holders<br>(now − owner_count_change; "
                           "the API's previous count is a 0 placeholder)<extra></extra>")))
    fig.add_trace(go.Scatter(
        x=bars["n_funds_holding_q"], y=bars["label"], mode="markers", name="Latest period",
        marker=dict(size=12, color=COLOR),
        customdata=bars[["owner_count_change", "portfolio_weight_change", "ll_score_z", "ll_rank",
                         "previous_text"]].to_numpy(),
        hovertemplate=("<b>%{y}</b><br>Latest period: %{x} holders (previous: %{customdata[4]})<br>"
                       "owner_count_change %{customdata[0]:+.0f}<br>"
                       f"Portfolio weight change %{{customdata[1]:+.2f}} ({WEIGHT_UNIT})<br>"
                       "ll_score_z %{customdata[2]:.2f} (rank %{customdata[3]})<extra></extra>")))
    x_max = float(bars[["n_funds_holding_q", "previous_count", "implied_previous"]].max().max())
    fig.update_xaxes(title_text="Tracked funds holding the stock", range=[-0.04 * x_max - 0.5, x_max * 1.06 + 0.5])
    fig.update_yaxes(autorange="reversed", ticks="", title_text=None)
    # Only a reported 0 that matches the change is a start from zero; a NaN previous count had earlier holders.
    if from_zero >= 0.8 * len(bars):
        headline = (f"{from_zero} of the {len(bars)} top gainers start from 0 holders: "
                    + ("all" if from_zero == len(bars) else "mostly") + " first appearances"
                    + (f" ({n_missing} more were held before, previous count not available)" if n_missing else ""))
    elif n_missing >= len(bars) / 2:
        headline = (f"{n_missing} of the {len(bars)} top gainers have no usable previous count; only {from_zero} "
                    f"verifiably start{'s' if from_zero == 1 else ''} from 0 holders")
    elif pd.notna(lead["previous_count"]):
        headline = (f"{lead['ticker']} gained the most holders: {lead['previous_count']:.0f} → "
                    f"{lead['n_funds_holding_q']:.0f} holders")
    else:
        headline = (f"{lead['ticker']} tops the board: {lead['owner_count_change']:+.0f} holders to "
                    f"{lead['n_funds_holding_q']:.0f} (previous count not available)")
    fig.update_layout(
        title=dict(text=headline,
                   subtitle=dict(text=f"Top {len(bars)} of the ll_predictive board in rank order · holdings as of "
                                      f"{holdings_date:%Y-%m-%d} · gate: {GATE['ll_predictive']}<br>"
                                      "open circle = previous period, filled = latest"
                                      + (f" · diamond on a dotted line = implied previous, now − change "
                                         f"({n_missing} rows whose previous count is not available)"
                                         if n_missing else ""))),
        height=220 + 30 * len(bars), margin=dict(t=130, l=10, r=30, b=120),
        legend=dict(orientation="h", x=0, y=below_plot(220 + 30 * len(bars), 130, 120), yanchor="top"))
    fig.show()
    display(bars[["ll_rank", "ticker", "display_name", "n_funds_holding_q_minus_1", "previous_count",
                  "implied_previous", "n_funds_holding_q", "difference", "owner_count_change",
                  "portfolio_weight_change", "ll_score_z"]]
            .style.format({"previous_count": "{:.0f}", "implied_previous": "{:.0f}", "difference": "{:.0f}",
                           "portfolio_weight_change": "{:+.2f}", "ll_score_z": "{:.2f}"}, na_rep="n/a")
            .hide(axis="index"))

# %% [markdown]
# **How to read this.** Each row is a stock; the open circle is how many
# tracked funds held it in the previous period and the filled circle how many
# hold it now, so a longer connector is a bigger gain in ownership breadth. A
# row with a hollow diamond on a dotted line has no usable previous count (the
# NaN policy above): the diamond is the count implied by now − change, an
# inference from the API's numbers rather than a reported count. The table
# shows the API's raw `n_funds_holding_q_minus_1` next to our `previous_count`
# and `implied_previous`. The headline counts as "first appearances" only the
# rows that verifiably start from 0. Rows follow the board's `ll_rank`. Ties in
# `ll_score_z` are common, because many stocks gain the same whole number of
# holders.
#
# **Caveats.**
#
# - Its gate reason notes that only a few quarter-on-quarter transitions are
#   on file, so SurgeFlow itself treats this board as preliminary.
# - A row that genuinely goes from 0 to n holders (its change equals its
#   current count) may record the arrival of a stock in the data, not new
#   buying. That does not apply to a row whose previous count is not
#   available: its change implies it already had holders.
# - The implied previous count assumes `owner_count_change` = now − before,
#   which the cell checks on the rows where both counts are reported. It is an
#   inference, so it never feeds a ranking here.
# - `portfolio_weight_change` is SurgeFlow's weight-change measure. Only in
#   the US does it behave like a sum of the holders' weight changes in
#   percentage points (so it grows with the number of holders); elsewhere its
#   units vary by market and run, so compare it only within one board.

# %% [markdown]
# ### 4.10 US only: shareholder-letter tone
#
# For the US, the payload adds `letter_nlp`: shareholder letters from
# well-known investment firms, scored for tone in two ways. **Net tone**
# counts words from a finance word list (the Loughran-McDonald lexicon):
# (positive − negative) ÷ (positive + negative). **FinBERT net tone** comes
# from a language model trained on financial text: its positive probability
# minus its negative probability. Both run from −1 (negative) to +1
# (positive). Other markets send `null`, which is normal.

# %%
letters_block = wh["letter_nlp"]
if not letters_block:
    display(Markdown(f"> No shareholder-letter study for {MARKET_NAMES[MARKET]}: `letter_nlp` is "
                     + ("empty right now." if MARKET == "us" else "null outside the US.")
                     + " Nothing to show here."))
else:
    letters = pick(pd.DataFrame(letters_block["letters"]),
                   ["fund_name", "letter_date", "letter_type", "total_tokens", "net_tone", "finbert_net_tone"])
    letters["letter_date"] = pd.to_datetime(letters["letter_date"], utc=True, errors="coerce")
    for col in ["total_tokens", "net_tone", "finbert_net_tone"]:
        letters[col] = pd.to_numeric(letters[col], errors="coerce")
    letters = letters.drop_duplicates(subset=["fund_name", "letter_date", "letter_type"])
    agree = letters[["net_tone", "finbert_net_tone"]].corr(method="spearman").iloc[0, 1]
    print(f"{letters_block['count']} letters from {letters['fund_name'].nunique()} fund(s), "
          f"{letters['letter_date'].min():%Y} to {letters['letter_date'].max():%Y}. The two tone measures have a rank "
          f"correlation of {agree:+.2f} across letters. The five most recent:")
    display(letters.sort_values("letter_date", ascending=False).head(5)
            .style.format({"letter_date": "{:%Y-%m-%d}", "total_tokens": "{:,.0f}", "net_tone": "{:+.3f}",
                           "finbert_net_tone": "{:+.3f}"}).hide(axis="index"))

# %% [markdown]
# ## 5. Extension: four markets side by side
#
# *This section goes beyond a single endpoint call.* We fetch both endpoints for
# the other three markets (6 requests) and compare what matters before any
# analysis: **how old** each map and each whale board is, how old the reports
# behind the boards are, and **how clean** each clustering is. Different
# disclosure rules make the whale ages very different from market to market.
#
# The Japanese and Hong Kong whale responses are several megabytes, mostly the
# holder roster. `market_row` reads only what it needs (run metadata, board
# dates, roster dates) with vectorised pandas operations and keeps one small
# row per market, so the large payloads can be dropped right away. It also
# takes each market's last published session from the health payload of
# section 3 (no extra request) and records whether the ML run covers it
# (`ml_vs_last_session`).

# %%
def newest_run_dates(signals_dict: dict) -> pd.Series:
    """as_of_date of every board row written by its board's newest run (the rule from section 4.1)."""
    keep = []
    for rows in signals_dict.values():
        frame = pick(pd.DataFrame(rows), ["as_of_date", "updated_at"])
        written = pd.to_datetime(frame["updated_at"], utc=True, errors="coerce")
        keep.append(frame.loc[~(written < written.max() - RUN_WINDOW), "as_of_date"])
    return pd.to_datetime(pd.concat(keep, ignore_index=True) if keep else pd.Series(dtype=object),
                          utc=True, errors="coerce").dropna()


def market_row(m: str, ml_p: dict, wh_p: dict) -> dict:
    """One market's freshness and quality, from its two payloads."""
    row = {"market": m}
    d = ml_p["data"]
    if d["available"]:
        r, q = d["run"], d["run"]["quality"]
        row.update({"ml_as_of": r["as_of_date"], "last_session": LAST_SESSION.get(m),
                    "ml_vs_last_session": session_check(r["as_of_date"], LAST_SESSION.get(m)),
                    "ml_age_days": r["age_days"], "ml_stale": r["stale"],
                    "stocks_clustered": r["clustered_ticker_count"], "k": q["k"], "silhouette": q["silhouette"],
                    "effective_clusters": q["effective_clusters"],
                    "anomaly_rate": d["anomaly_total"] / max(r["clustered_ticker_count"], 1),
                    "changed_share": d["model_notes"]["changed_count"] / max(r["clustered_ticker_count"], 1)})
    w = wh_p["data"]
    dates = newest_run_dates(w["signal_board"]["signals"])
    if not dates.empty:
        held = dates.mode().iloc[0]
        row.update({"whale_as_of": f"{held:%Y-%m-%d}", "whale_age_days": int((TODAY - held).days),
                    "whale_source": DISCLOSURE[m]["source"]})
    report_dates = period_end(pd.Series([f["latest_quarter"] for f in w["funds"]["funds"]], dtype=object))
    row.update({"holders": w["funds"]["count"],
                "median_report_age_days": float((TODAY - report_dates).dt.days.median())})
    return row


if COMPARE_MARKETS:
    rows = []
    for m in MARKETS:
        if m == MARKET:
            rows.append(market_row(m, ml_payload, wh_payload))      # reuse: no extra request
            continue
        # This section is an add-on: an unavailable endpoint leaves a blank row instead of stopping the notebook.
        ml_p = sf_try(f"/api/v1/markets/{m}/ml/clusters")
        wh_p = sf_try(f"/api/v1/markets/{m}/whales") if ml_p is not None else None
        if ml_p is None or wh_p is None:
            rows.append({"market": m})                               # NaN row: shown as n/a, left out of charts
            continue
        show_freshness(ml_p, f"{MARKET_NAMES[m]} ML clusters:")
        show_freshness(wh_p, f"{MARKET_NAMES[m]} whales:")
        rows.append(market_row(m, ml_p, wh_p))
        del ml_p, wh_p                                               # free the large payload before the next fetch
    compare = pd.DataFrame(rows).set_index("market")
    for col in ["ml_age_days", "whale_age_days", "median_report_age_days", "silhouette", "effective_clusters",
                "anomaly_rate", "changed_share"]:
        if col in compare:
            compare[col] = pd.to_numeric(compare[col], errors="coerce")
    display(compare.style.format({"silhouette": "{:.3f}", "effective_clusters": "{:.2f}", "anomaly_rate": "{:.1%}",
                                  "changed_share": "{:.0%}", "ml_age_days": "{:.0f}", "whale_age_days": "{:.0f}",
                                  "median_report_age_days": "{:,.0f}", "stocks_clustered": "{:,.0f}",
                                  "holders": "{:,.0f}", "k": "{:.0f}"}, na_rep="n/a"))
else:
    compare = pd.DataFrame()
    print("COMPARE_MARKETS is False: skipped.")

# %%
AGE_PANELS = {"ml_age_days": "ML map: calendar days since<br>the run's session",
              "whale_age_days": "Whale boards: days since the board date<br>(us, cn: quarter end · jp, hk: rebuild)",
              "median_report_age_days": "Holder roster: median age of<br>each holder's latest report"}
AGE_TICKS = {1: "1 d", 7: "1 wk", 30: "1 mo", 90: "3 mo", 365: "1 y", 730: "2 y"}
if compare.empty or compare.reindex(columns=list(AGE_PANELS)).isna().all().all():
    display(Markdown("> Nothing to compare (skipped, or no market returned a run or a board)."))
else:
    # One shared log axis for all three panels: the ages run from 0 to hundreds of days, and the same length must
    # mean the same age in every panel. A log axis has no 0, so "today" (0 days) is drawn at half a day and the
    # connectors start at the left edge.
    fig = make_subplots(rows=1, cols=3, shared_yaxes=True, horizontal_spacing=0.05,
                        subplot_titles=list(AGE_PANELS.values()))
    names = [MARKET_NAMES[m] for m in compare.index]
    for col, field in enumerate(AGE_PANELS, start=1):
        for m, name in zip(compare.index, names):
            value = compare.loc[m, field] if field in compare else np.nan
            if pd.isna(value):
                continue
            flag = compare.loc[m].get("ml_stale")
            stale = field == "ml_age_days" and pd.notna(flag) and bool(flag)
            x = max(float(value), 0.5)
            fig.add_trace(go.Scatter(x=[0.3, x], y=[name, name], mode="lines", line=dict(color=GRID, width=3),
                                     hoverinfo="skip", showlegend=False), row=1, col=col)
            label = ("today" if value < 0.5 else f"{value:,.0f} d") + (" (flagged stale)" if stale else "")
            hover = label
            if field == "ml_age_days":                                   # the check the flag alone does not make
                hover += (f"<br>run session {compare.loc[m].get('ml_as_of')} · last published session "
                          f"{compare.loc[m].get('last_session') or 'n/a'}")
            # Label and marker are separate traces, so the legend shows a plain marker without an "Aa" sample.
            fig.add_trace(go.Scatter(
                x=[x], y=[name], mode="markers+text", text=[label], textposition="middle right",
                textfont=dict(size=11, color=INK_2), cliponaxis=False, marker=dict(size=14, opacity=0),
                showlegend=False, hoverinfo="skip"), row=1, col=col)
            fig.add_trace(go.Scatter(
                x=[x], y=[name], mode="markers", name=name, legendgroup=m, showlegend=(col == 2),
                marker=dict(size=14, color=MARKET_COLORS[m], symbol="circle-open" if stale else "circle",
                            line=dict(width=3, color=MARKET_COLORS[m])),
                customdata=[hover], hovertemplate=f"{name}: %{{customdata[0]}}<extra></extra>"), row=1, col=col)
    fig.update_xaxes(type="log", range=[np.log10(0.3), np.log10(2500)], tickvals=list(AGE_TICKS),
                     ticktext=list(AGE_TICKS.values()), title_text="Age (log scale)")
    for col in (2, 3):
        fig.update_xaxes(matches="x", row=1, col=col)                    # zooming one panel zooms all three
    fig.update_yaxes(autorange="reversed", ticks="")

    def span(values: pd.Series) -> str:
        """'99' when every value is the same, else '7-99' (days, rounded)."""
        v = values.dropna().round()
        return f"{v.min():,.0f}" if v.min() == v.max() else f"{v.min():,.0f}-{v.max():,.0f}"

    quarterly = [m for m in compare.index if DISCLOSURE[m]["quarterly"]]
    event = [m for m in compare.index if not DISCLOSURE[m]["quarterly"]]
    q_age = compare.reindex(quarterly)["whale_age_days"] if "whale_age_days" in compare else pd.Series(dtype=float)
    e_age = (compare.reindex(event)["median_report_age_days"] if "median_report_age_days" in compare
             else pd.Series(dtype=float))
    parts = []
    if q_age.notna().any():
        parts.append(f"{'/'.join(m.upper() for m in q_age.dropna().index)} whale holdings are {span(q_age)} days old")
    if e_age.notna().any():
        parts.append(f"{'/'.join(m.upper() for m in e_age.dropna().index)} boards are rebuilt daily on reports with "
                     f"a median age of {span(e_age)} days")
    headline = "; ".join(parts) or "Whale boards and ML maps by age"
    ma = compare["ml_age_days"] if "ml_age_days" in compare else pd.Series(dtype=float)
    fig.update_layout(
        title=dict(text=headline,
                   subtitle=dict(text=(f"The ML maps are {span(ma)} calendar days old · " if ma.notna().any() else "")
                                 + "one log axis · open circle = ML run flagged stale (a calendar-day count)<br>"
                                   "Quarterly regimes (us, cn) lag by months; event-driven regimes (jp, hk) are "
                                   "rebuilt daily, but many of their reports are old")),
        height=500, margin=dict(t=200, b=110), legend=dict(orientation="h", x=0, y=-0.26, yanchor="top"))
    fig.show()

# %% [markdown]
# **How to read this.** Each row is a market in its usual colour; a longer
# line means older information. All three panels share one logarithmic axis
# (each tick step is a bigger jump in time), so a day, a month and two years
# all fit, and the same length means the same age in every panel. The left
# panel shows the ML map's age in calendar days; an open circle means
# SurgeFlow flagged that run stale. Both the age and the flag count calendar
# days, not trading sessions, so during an exchange holiday (China's National
# Day closure in early October, for example) a correct run can be flagged
# stale; SurgeFlow calls this a labelling issue on its side, and the data
# itself is correct. So check the table's `ml_vs_last_session` column rather
# than the flag alone: "same" means the run's `as_of_date` matches the
# market's last published session (health `published_session_date`, also in
# the hover), so the map is as recent as that market's data, whatever the
# flag says. The middle panel shows the age of the boards' date: the quarter end the holdings refer to in the US and
# China, but only the date of the daily rebuild in Japan and Hong Kong, so
# "today" there says nothing about the holdings' age. The right panel shows
# the median age of each tracked holder's latest report: for event-driven
# markets this is where the age hides, because a board rebuilt today can rest
# on reports filed months or years ago. The
# table above adds each run's quality: cluster count, silhouette, effective
# clusters, the share of stocks flagged as anomalies and the share that
# switched cluster.
#
# **Caveats.**
#
# - Silhouettes are comparable across markets only roughly: each market has its
#   own feature coverage and universe size.
# - A young whale board in Japan or Hong Kong is not "better": it covers only
#   large, reportable stakes, while a 13F snapshot is complete but old.

# %% [markdown]
# ## 6. Extension: joining the map and the whales on `ticker`
#
# *This section goes beyond the raw API.* Every v1 endpoint uses the same
# ticker strings, so you can ask: **where do the whales' names sit on the ML
# map?** The clusters payload gives a per-stock cluster only for some stocks:
# the representatives, the anomaly watch and the switchers (`to_cluster_id`).
# The full per-stock labels are not part of v1. We join on what we have and
# say how much that covers. Expect a small overlap: the whale boards favour
# large, widely held names (or single-owner stakes), while the labelled ML
# stocks are typical members, outliers and switchers.

# %%
labelled = pd.concat([
    pd.DataFrame({"ticker": t, "cluster_id": cid, "role": "representative"}
                 for cid, tickers in zip(clusters["cluster_id"], clusters["representative_tickers"]) for t in tickers),
    anom.assign(role="anomaly")[["ticker", "cluster_id", "role"]],
    changed.assign(role="switched in")[["ticker", "to_cluster_id", "role"]]
    .rename(columns={"to_cluster_id": "cluster_id"}),
], ignore_index=True)
labelled["ticker"] = labelled["ticker"].astype(str)
labelled = labelled.drop_duplicates(subset="ticker", keep="first")      # one label per stock

membership = pd.concat([b[["ticker", "display_name"]].assign(board=name) for name, b in boards.items()],
                       ignore_index=True)
whale_names = (membership.groupby("ticker").agg(name=("display_name", "first"), boards=("board", ", ".join),
                                                n_boards=("board", "size")).reset_index())
joined = whale_names.merge(labelled, on="ticker", how="inner", validate="one_to_one")
joined["cluster"] = joined["cluster_id"].map(LABEL).fillna("(unknown)")
joined["cluster_name"] = joined["cluster_id"].map(NAME)
print(f"{len(whale_names)} distinct stocks appear on the whale boards; {len(labelled)} stocks have an ML label "
      f"in this payload; {len(joined)} {'is' if len(joined) == 1 else 'are'} in both "
      f"({len(joined) / max(len(whale_names), 1):.0%} of the whale names).")
if joined.empty:
    display(Markdown("> No overlap between the whale boards and the labelled ML stocks today. That is common: "
                     "the two lists come from different corners of the market. Placing every whale name on the "
                     "map would need per-stock cluster labels, which v1 does not publish."))
else:
    display(joined.sort_values(["n_boards", "ticker"], ascending=[False, True])
            [["ticker", "name", "boards", "cluster", "cluster_name", "role"]].style.hide(axis="index"))
    display(joined.groupby("cluster")["ticker"].agg(["size", ", ".join])
            .rename(columns={"size": "whale names", "join": "tickers"}))

# %% [markdown]
# **How to read this.** Each row is a stock that is both on at least one whale
# board and labelled on the ML map. "boards" lists where the whales show up;
# "role" says how we know its cluster. The second table counts whale names per
# cluster.
#
# **Caveats.**
#
# - This is a **biased sample**: representatives are the most typical members,
#   anomalies the least typical, and the listed switchers are mostly the most
#   unusual switchers (section 3). Do not read the counts as "whales prefer
#   cluster X".
# - The whale boards are weeks or months old (section 4.3); the cluster labels
#   are from the latest run. The join mixes two dates on purpose, so say so when
#   you report it.

# %% [markdown]
# ## Next steps
#
# - Change `MARKET` to `"cn"` and run again: China's boards can interleave two
#   computation runs with different quarter labels (section 4.1 keeps the
#   newest), and around market holidays (the National Day closure in early
#   October, for example) its ML run can be flagged stale although it covers
#   the last trading session: compare `run.as_of_date` with health's
#   `published_session_date` (section 3) rather than trusting the flag alone.
# - Try `"jp"` or `"hk"`: the holder roster grows to thousands of filers and
#   the disclosure-lag charts change shape completely.
# - Look up the representative tickers in the screen endpoint (notebook 01) and
#   check that their numbers match the cluster's traits.
# - Re-run the clusters cell tomorrow and compare `changed_group` with today's:
#   do the same stocks keep switching?
# - To compare your own clustering with SurgeFlow's, open notebook 05 (ML lab):
#   it clusters the screen's features with k-means and compares the result
#   with the labelled stocks using the adjusted Rand index (ARI), but only when
#   at least `MIN_LABELLED` of them are in its sample. The guard matters: a
#   few pages of the largest companies often share only a handful of tickers
#   with the labelled stocks, and an ARI on a handful of stocks means nothing.
#   The labelled stocks are also a biased sample (representatives, the top
#   anomalies and the most unusual switchers), so any ARI describes those
#   stocks only, not the whole map.
# - Re-run after the next 13F deadline (mid-February, May, August and
#   November) and check whether the position-delta deltas are non-zero.
#
# ---
#
# *Research and education only. Nothing here is investment advice or a
# recommendation to buy or sell any security. The ML clusters describe how
# stocks resemble each other; they do not forecast returns. Whale boards
# reflect disclosure filings that can be weeks or months old. The endpoint name
# `realtime` elsewhere in the API names a current-session board, not a
# live-tick feed, and data cadence varies by market: always check the
# freshness fields.*

# %%
print(f"API requests made in this session: {api_calls_used()}")
