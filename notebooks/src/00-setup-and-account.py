# %% [markdown]
# # 00 · Setup and account: your key, API health, and the endpoint map
#
# This is the first notebook of the SurgeFlow starter kit. It connects you safely, then
# uses four small endpoints to answer the questions to ask before any analysis:
# **Is the API up? What can I call? What does my key allow? How fresh is each market?**
#
# **What you will learn**
#
# - How to create an API key and keep it out of your notebook with a Colab secret.
# - The base-URL rule and the authentication header that the catalogue recommends.
# - How to read health market by market, and why the overall status can read "degraded"
#   while most markets are healthy.
# - Where each endpoint keeps its records, checked against the live catalogue.
# - How to read your plan, scopes, rate limits and usage from `/api/v1/me`, without showing
#   anything that identifies you.
# - How to keep going when an endpoint is temporarily unavailable (`sf_try`).
#
# | Method | Path | Key needed? | What it returns |
# |---|---|---|---|
# | GET | `/api/v1/health` | no (open) | Operational health and data-quality disclosures, per market |
# | GET | `/api/v1/catalog` | no (open) | Base URL, auth options, plans and limits, every endpoint, response shapes |
# | GET | `/api/v1/me` | yes (any scope) | Your key's plan, scopes, rate-limit counters and rolling usage. Never the secret itself |
# | GET | `/api/v1/summary` | yes (`summary` scope) | Four-market market-watch summary, freshness metadata and FX context |
#
# **Budget:** about 6 requests. The free plan allows 2,000 a day.

# %% [markdown]
# ## 1. Connect
#
# ### Get a free API key (once)
#
# 1. Open **https://surgeflows.capital/membership#api-key**.
# 2. Enter your email, agree to the terms (a name is optional), and create the key.
# 3. Copy the key straight away. It starts with `sf_live_` and is **shown once**. SurgeFlow
#    stores only a hash of it, so nobody can show it to you again. If you lose it, create a new one.
#
# ### Store it as a Colab secret
#
# 1. In Colab, click the **key icon (Secrets)** in the left sidebar.
# 2. Click **Add new secret**. Name: `SURGEFLOW_API_KEY`. Value: your key.
# 3. Switch on **Notebook access** for this notebook.
#
# Secrets belong to your Google account, not to the notebook file. Sharing the notebook does
# not share the key.
#
# **Never paste the key into a code cell, a text cell, a chat or a URL.** Notebooks get shared,
# copied to Drive and pushed to GitHub, and a pasted key travels with them. If a key leaks, stop
# using it, create a new one, and email support@surgeflows.capital so the old one can be revoked.
#
# ### What the next cell does
#
# The shared helper cell looks for your key in three places, in this order:
#
# 1. the environment variable `SURGEFLOW_API_KEY` (for local Jupyter);
# 2. the Colab secret `SURGEFLOW_API_KEY`;
# 3. a hidden prompt, where your typing is not shown.
#
# It never prints the key. It also defines `sf_get` (a polite GET with retries), `sf_try` (the
# same, but when a request fails it prints a short note and returns `None`), `records`, `dig`,
# `show_freshness` and the chart colours used in every notebook of the kit.

# %% [helpers]

# %% [markdown]
# ## 2. Parameters
#
# Change these and re-run the notebook. The other cells read them.

# %%
MARKETS_SHOWN = ["us", "cn", "jp", "hk"]  # any of "us", "cn", "jp", "hk"; tw, kr, uk and in were retired
NOTEBOOK_BUDGET = 80                      # requests one notebook of this kit aims to stay under

unknown = sorted(set(MARKETS_SHOWN) - set(MARKETS))
if unknown:
    raise ValueError(f"Unknown or retired market(s) {unknown}. Use any of {MARKETS}.")
print(f"Markets shown: {', '.join(MARKET_NAMES[m] for m in MARKETS_SHOWN)}")

# %% [markdown]
# ### Check your key
#
# Health and the catalogue (sections 3 and 4) are open endpoints, so they answer even when the key
# is wrong. This is the first call that needs your key: `GET /api/v1/me`, the cheapest way to check
# that a key works. If the key is mistyped, revoked or not reaching the notebook, the cell stops
# here with a short explanation, before any other cell can blame something else. It prints only
# your plan and the number of scopes. Section 5 reads the same response in detail.

# %%
try:
    me = sf_get("/api/v1/me")  # section 5 reuses this response; nothing that identifies you is shown
except SurgeFlowError as err:
    if err.status in (401, 403):  # the key is never echoed, only the status and code
        raise SystemExit(
            f"Your key was rejected (HTTP {err.status} {err.code}). Check that the Colab secret is named "
            "SURGEFLOW_API_KEY and has Notebook access switched on (or that the environment variable holds the "
            "whole key), then re-run the Connect cell and this one. Lost or revoked key? Create a new one at "
            "https://surgeflows.capital/membership#api-key."
        ) from None
    raise
print(f"Key accepted: plan “{me['plan']}”, {len(me['scopes'])} scopes. Section 5 shows what it allows.")

# %% [markdown]
# A few small formatting tools keep labels readable. They are plain Python, so you can reuse them.

# %%
import re
import textwrap
from collections import defaultdict

from plotly.subplots import make_subplots


def compact(value) -> str:
    """207743595389 -> '207.7B'. Short labels for big numbers."""
    if value is None or pd.isna(value):
        return "n/a"
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= size:
            return f"{value / size:,.1f}{suffix}"
    return f"{value:,.0f}"


def day(value) -> str:
    """A date as YYYY-MM-DD, or 'n/a' when it is missing (NaT)."""
    return "n/a" if value is None or pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d")


def text_or(value, default: str = "none") -> str:
    """A non-empty string, or the default (None and NaN both count as missing)."""
    return value if isinstance(value, str) and value.strip() else default


def share(value) -> str:
    """0.0009 -> '0.09%', 0.0225 -> '2.3%', 0.42 -> '42%'. Small shares keep more decimals."""
    if value is None or pd.isna(value):
        return "n/a"
    if abs(value) < 0.01:
        return f"{value:.2%}"
    return f"{value:.1%}" if abs(value) < 0.1 else f"{value:.0%}"


def ink_on(fill_hex: str) -> str:
    """Pick white or ink text for a label inside a coloured mark (whichever contrasts more)."""
    def luminance(hex_color):
        channels = [int(hex_color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    fill = luminance(fill_hex)
    on_white = (1.05) / (fill + 0.05)
    on_ink = (fill + 0.05) / (luminance(INK) + 0.05)
    return "#ffffff" if on_white >= on_ink else INK


def chart_title(takeaway: str, subtitle: str) -> dict:
    """Chart title = the takeaway; a smaller grey line says what is plotted. Works on any Plotly 5+."""
    return dict(text=f"{takeaway}<br><span style='font-size:13px;color:{INK_2}'>{subtitle}</span>",
                y=1, yanchor="top", pad=dict(t=16, l=8))


def market_order(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep only MARKETS_SHOWN, in that order. A stable sort keeps each market's rows in their order."""
    rank = {m: i for i, m in enumerate(MARKETS_SHOWN)}
    kept = frame[frame["market"].isin(rank)]
    return kept.sort_values("market", key=lambda s: s.map(rank), kind="stable").reset_index(drop=True)

# %% [markdown]
# ## 3. Health: is the API up, market by market?
#
# `GET /api/v1/health` is **open**: it needs no key. It reports whether each market's data
# pipeline has published its latest session, and it discloses data-quality limits.
# Check it first when numbers look odd.
#
# The status words have an order of severity. We give each one an **icon and a word**, both drawn
# in ink, so the meaning never depends on colour. The status gets **no colour of its own**: in this
# kit hue means market (China is orange, Hong Kong amber, Japan green), so a green, amber or orange
# status mark beside a market's name would read as that market's identity, not its state.

# %%
STATUS_ICONS = {"good": "✓", "warning": "!", "serious": "▲", "critical": "✕", "unknown": "?"}
STATUS_LEVEL = {
    "healthy": "good", "full": "good", "ready": "good",
    "degraded": "warning", "limited": "warning", "partial": "warning", "ready_with_disclosures": "warning",
    "stale": "serious", "not_ready": "serious",
    "error": "critical", "down": "critical", "unavailable": "critical", "failed": "critical",
}


def status_level(value) -> str:
    """'healthy' -> 'good', 'stale' -> 'serious'. Unknown words map to 'unknown'."""
    return STATUS_LEVEL.get(str(value).lower(), "unknown")


def status_chip(value) -> str:
    """Icon + word for tables, e.g. '✓ healthy'."""
    return f"{STATUS_ICONS[status_level(value)]} {value}"

# %% [markdown]
# Open endpoints really are open. Here is a plain request with **no key at all**:

# %%
no_key = requests.get(f"{BASE_URL}/api/v1/health", timeout=30)
print(f"GET /api/v1/health with no key -> HTTP {no_key.status_code}")
print("(This plain request is not counted by api_calls_used(), and no key was sent.)")

# %% [markdown]
# Now the same call through the helper. Its payload is what we analyse.

# %%
health = sf_get("/api/v1/health")
show_freshness(health, "Health:")

STALE_HOURS = float(health["stale_threshold_hours"])
health_built = pd.to_datetime(health["timestamp"], utc=True)
print(f"Health built {health_built:%Y-%m-%d %H:%M} UTC | stale threshold: {STALE_HOURS:g} hours | ok: {health['ok']}")

overall_checks = ["status", "operational_status", "data_quality_status", "release_status"]
overall = pd.DataFrame({"check": overall_checks, "value": [health[c] for c in overall_checks]})
overall["reads as"] = overall["value"].map(status_chip)
overall

# %% [markdown]
# `show_freshness` looks for common names such as `as_of_utc` and `market_status`. Health uses
# its own names (`timestamp`, `hours_ago`), so it found nothing, and we printed them ourselves.
#
# **Raw preview.** The `markets` block holds one record per market:

# %%
health_raw = pd.DataFrame.from_dict(health["markets"], orient="index")
print(f"{len(health_raw)} markets x {health_raw.shape[1]} fields")
health_raw.head()

# %% [markdown]
# **Cleaning.** Pick the fields we use (a missing one raises a `KeyError`, which means the
# API contract changed), fix the types, keep one row per market, and count the gaps.

# %%
HEALTH_FIELDS = ["status", "data_quality_status", "release_status", "publish_state", "hours_ago",
                 "published_session_date", "expected_trading_day", "published_session_complete",
                 "tickers", "closes_rows", "last_full_ready_at", "reason", "data_quality_reason"]
mh = health_raw.loc[:, HEALTH_FIELDS].rename_axis("market").reset_index()

# 1. Numbers: errors="coerce" turns a stray string into NaN instead of breaking the maths.
for col in ["hours_ago", "tickers", "closes_rows"]:
    mh[col] = pd.to_numeric(mh[col], errors="coerce")
# 2. Times: timestamps to UTC; session dates to plain calendar dates.
mh["last_full_ready_at"] = pd.to_datetime(mh["last_full_ready_at"], utc=True, errors="coerce")
for col in ["published_session_date", "expected_trading_day"]:
    mh[col] = pd.to_datetime(mh[col], errors="coerce")
# 3. One row per market: "market" is the natural key.
mh = mh.drop_duplicates(subset="market", keep="first")
# 4. Keep the chosen markets, in a fixed order. Health could still list a retired market.
retired = sorted(set(mh["market"]) - set(MARKETS))
mh = market_order(mh)
# 5. Derived columns.
mh["market_name"] = mh["market"].map(MARKET_NAMES)
mh["level"] = mh["status"].map(status_level)
mh["past_threshold"] = mh["hours_ago"] > STALE_HOURS
mh["calendar_days_behind"] = (mh["expected_trading_day"] - mh["published_session_date"]).dt.days
# Weekdays after the published session, up to and including the expected day. Exchange holidays are
# NOT removed, so this is an upper bound on missed sessions, not a count of them.
both_days = mh["published_session_date"].notna() & mh["expected_trading_day"].notna()
mh["weekdays_behind"] = np.nan
mh.loc[both_days, "weekdays_behind"] = np.busday_count(
    (mh.loc[both_days, "published_session_date"] + pd.Timedelta(days=1)).values.astype("datetime64[D]"),
    (mh.loc[both_days, "expected_trading_day"] + pd.Timedelta(days=1)).values.astype("datetime64[D]"))
# 6. NaN policy: count every gap. Rows are kept; a market without hours_ago is left off the chart.
gaps = mh[["hours_ago", "tickers", "closes_rows", "published_session_date", "expected_trading_day"]].isna().sum()
print("Missing values per column:", gaps.to_dict())
if retired:
    print(f"Ignored retired market(s) still listed by health: {retired}")
if mh.empty:
    print("Health lists none of the markets in MARKETS_SHOWN, so there is nothing to show below.")

# %% [markdown]
# **Chart: the status strip.** One row per market. The dot shows how many hours have passed
# since that market's latest published session. The chip on the right gives the status as an
# icon and a word. The y-axis already names each market, so every dot is the same neutral grey:
# a coloured dot would be read as a status.

# %%
plot_h = mh.dropna(subset=["hours_ago"]).copy()
if plot_h.empty:
    print("No market reported hours_ago, so there is nothing to plot.")
else:
    plot_h["hours_plot"] = plot_h["hours_ago"].clip(lower=0.1)  # a log axis cannot show 0
    plot_h["age_label"] = [f"{h:.1f} h" if h < 48 else f"{h / 24:.1f} days" for h in plot_h["hours_ago"]]
    n_good, n_all = int((mh["level"] == "good").sum()), len(mh)
    not_plotted = n_all - len(plot_h)
    x_hi = max(plot_h["hours_plot"].max(), STALE_HOURS) * 2.5
    x_lo = min(plot_h["hours_plot"].min(), 1.0) * 0.6

    if health["status"] == "healthy":
        title = f"All {n_all} markets are healthy"
    else:
        title = f"{n_good} of {n_all} markets are healthy, yet the overall status reads “{health['status']}”"

    fig = go.Figure()
    fig.add_vrect(x0=STALE_HOURS, x1=x_hi, fillcolor=GRID, opacity=0.5, layer="below", line_width=0)
    fig.add_vline(x=STALE_HOURS, line=dict(color=MUTED, width=1, dash="dot"))
    fig.add_annotation(x=np.log10(STALE_HOURS), y=1.0, yref="paper", yanchor="bottom", xanchor="left",
                       text=f" older than the {STALE_HOURS:g} h stale threshold", showarrow=False,
                       font=dict(size=12, color=INK_2))
    fig.add_trace(go.Scatter(
        x=plot_h["hours_plot"], y=plot_h["market_name"], mode="markers+text", cliponaxis=False,
        marker=dict(size=16, color=INK_2, line=dict(width=2, color=SURFACE)),
        text=["  " + a for a in plot_h["age_label"]], textposition="middle right", textfont=dict(color=INK_2, size=12),
        customdata=np.stack([plot_h["status"], plot_h["published_session_date"].map(day),
                             plot_h["expected_trading_day"].map(day), plot_h["reason"].map(text_or)], axis=-1),
        hovertemplate=("<b>%{y}</b><br>Hours since published session: %{x:.1f}<br>Status: %{customdata[0]}"
                       "<br>Published session: %{customdata[1]}<br>Expected trading day: %{customdata[2]}"
                       "<br>Reason: %{customdata[3]}<extra></extra>"),
        showlegend=False,
    ))
    for row in plot_h.itertuples():
        icon = STATUS_ICONS[row.level]
        detail = f"session {day(row.published_session_date)}"
        if row.data_quality_status != "full":  # a data-quality disclosure gets its own icon + word
            detail += f" · {STATUS_ICONS[status_level(row.data_quality_status)]} data {row.data_quality_status}"
        fig.add_annotation(  # icon and word in ink: no status colour, because hue belongs to the markets
            x=1.02, xref="paper", xanchor="left", y=row.market_name, yref="y", showarrow=False, align="left",
            text=(f"<b>{icon} {row.status}</b>"
                  f"<br><span style='color:{INK_2}'>{detail}</span>"),
            font=dict(size=12, color=INK),
        )
    fig.update_xaxes(type="log", range=[np.log10(x_lo), np.log10(x_hi)],
                     tickvals=[1, 3, 6, 12, 24, 48, 96, 168, 336, 720],
                     ticktext=["1 h", "3 h", "6 h", "12 h", "1 day", "2 days", "4 days", "1 week", "2 weeks", "30 days"],
                     title="Hours since the latest published session (hours_ago, log scale)", showgrid=True)
    fig.update_yaxes(categoryorder="array", categoryarray=list(plot_h["market_name"])[::-1], title=None,
                     ticks="", showline=False, ticksuffix="  ")
    fig.update_layout(
        title=chart_title(title, f"Health built {health_built:%Y-%m-%d %H:%M} UTC. "
                                 "Dot = hours since the latest session. Status = the chip on the right (icon + word)."
                                 + (f" {not_plotted} market(s) without hours_ago not plotted." if not_plotted else "")),
        height=360, margin=dict(l=120, r=260, t=95, b=60),
    )
    fig.show()

# %% [markdown]
# **Table twin.** The same data as a table, with the status written out. `last full publish` is
# the last time every part of that market's pipeline was ready at once.

# %%
health_table = mh.assign(
    status_shown=mh["status"].map(status_chip),
    data_quality=mh["data_quality_status"].map(status_chip),
    publish=mh["publish_state"].map(status_chip),
    published=mh["published_session_date"].map(day),
    expected=mh["expected_trading_day"].map(day),
    last_full=mh["last_full_ready_at"].map(lambda t: "n/a" if pd.isna(t) else f"{t:%Y-%m-%d %H:%M} UTC"),
)[["market_name", "status_shown", "data_quality", "publish", "release_status", "hours_ago", "published",
   "expected", "calendar_days_behind", "weekdays_behind", "last_full", "tickers", "reason"]]
health_table.rename(columns={"market_name": "market", "status_shown": "status", "last_full": "last full publish"})

# %% [markdown]
# **How to read this**
#
# - Each row is one market. Further right means older data. The axis is logarithmic: each step
#   doubles or triples the age, so hours and days fit on one line.
# - The grey zone is older than the stale threshold that health itself reports.
# - The **status comes from the chip**, not from the dot's position. A market is "healthy" when it
#   has published the session its exchange calendar expects. The hour count also includes
#   nights and weekends, so a healthy market can sit past the line.
# - The overall `status` is a **roll-up** that follows `operational_status`: one stale market makes
#   it read "degraded" even when the other markets are fine. Data-quality limits are reported
#   separately, in `data_quality_status` (when this kit was checked: "limited", because of Hong
#   Kong's disclosures). The next cell checks that `status` still matches `operational_status`.
# - `calendar_days_behind` counts calendar days, and `weekdays_behind` counts Monday to Friday.
#   Neither removes exchange holidays, so neither is a count of missed sessions.
#
# The next cell writes these points out for today's data, so they stay true when the data changes.

# %%
lines = []
for row in mh.itertuples():
    if row.status != "healthy":
        gap = ("" if pd.isna(row.calendar_days_behind) else
               f" ({row.calendar_days_behind:.0f} calendar days, {row.weekdays_behind:.0f} weekdays behind; holidays are "
               "not subtracted, so check the exchange calendar: the gap may hold no trading session at all)")
        lines.append(f"- **{row.market_name}** is **{row.status}**: published session {day(row.published_session_date)}, "
                     f"expected {day(row.expected_trading_day)}{gap}. Reason given: {text_or(row.reason)}.")
    elif row.past_threshold and row.published_session_date == row.expected_trading_day:
        lines.append(f"- **{row.market_name}** is {row.hours_ago:.1f} h old, past the {STALE_HOURS:g} h line, yet "
                     f"**healthy**: it has published the session the calendar expects ({day(row.expected_trading_day)}).")
    elif row.past_threshold:
        lines.append(f"- **{row.market_name}** is marked **healthy**, but it is {row.hours_ago:.1f} h old and its "
                     f"published session ({day(row.published_session_date)}) is behind the expected trading day "
                     f"({day(row.expected_trading_day)}). Treat its numbers with care.")
    if row.data_quality_status != "full":
        lines.append(f"- **{row.market_name}** data quality is **{row.data_quality_status}** "
                     f"(release: {row.release_status}): {text_or(row.data_quality_reason, 'no reason given')}.")
healthy = mh.loc[mh["status"] == "healthy", "market_name"].tolist()
if health["status"] == health["operational_status"]:
    lines.append(f"- Overall status **{health['status']}** follows `operational_status` (pipeline freshness). "
                 f"Data quality is reported separately: `data_quality_status` is **{health['data_quality_status']}**.")
else:
    lines.append(f"- Overall status **{health['status']}** differs from `operational_status` "
                 f"(**{health['operational_status']}**) today, so the roll-up rule above may have changed. "
                 f"`data_quality_status` is **{health['data_quality_status']}**.")
lines.append(f"- Individually healthy: {', '.join(healthy) or 'none'}. Check the market you need, not only the headline.")
display(Markdown("\n".join(lines)))

# %% [markdown]
# Health also lists the **data-quality disclosures** (why a market is "limited") and five
# readiness flags per market. Both are worth a glance before a research run.

# %%
disclosures = pd.DataFrame(health["data_quality_disclosures"])
if disclosures.empty:
    print("No data-quality disclosures today.")
else:
    disclosures = disclosures.explode("partial_reasons").rename(columns={"partial_reasons": "reason"})
    display(disclosures[["market", "publish_state", "data_quality_status", "research_status", "reason"]])

flags = pd.DataFrame({m: v["publish_flags"] for m, v in health["markets"].items() if m in MARKETS_SHOWN}).T
flags = flags.reindex([m for m in MARKETS_SHOWN if m in flags.index])
flags.apply(lambda col: col.map(lambda ok: "✓ ready" if ok else "✕ not ready")).rename(index=MARKET_NAMES)

# %% [markdown]
# **Caveats**
#
# - Health answers HTTP 200 with `"ok": false` when it is degraded. That is information, not an
#   error, so `sf_get` returns it instead of raising.
# - `hours_ago` counts from the published session, not from your clock. Weekends and exchange
#   holidays inflate it. In early October, for example, mainland China closes for the National
#   Day holiday, so there may be no newer session to publish even when the expected trading day
#   says otherwise. Read `reason` and compare the published session with the exchange calendar
#   before you call data broken.
# - Reason codes are terse. Read them word by word: `legacy_pre2020_price_proxy_unadjusted`, for
#   example, says that prices before 2020 come from a proxy source and are not adjusted.
# - Health says when it was built (`timestamp`). If your analysis runs much later, call it again.
#   It describes the data pipeline, not the speed of your own requests.

# %% [markdown]
# ## 4. Catalogue: what can you call, and how?
#
# `GET /api/v1/catalog` is **open** too. It is the API describing itself: the base URL, how to
# send your key, the plans and their limits, every endpoint, and where each response keeps its
# records. When this kit and the catalogue disagree, **the catalogue wins**.

# %%
catalog = sf_get("/api/v1/catalog")
show_freshness(catalog, "Catalogue:")
print(f"API status: {catalog['status']} | schema: {catalog['schema_version']} | markets: {', '.join(catalog['markets'])}")

# %% [markdown]
# The catalogue is not market data, so it has no as-of date. **Raw preview:** its table of contents.

# %%
contents = pd.DataFrame(
    [(key, type(value).__name__, len(value) if isinstance(value, (list, dict)) else str(value))
     for key, value in catalog.items()],
    columns=["key", "type", "items or value"],
)
contents

# %% [markdown]
# ### 4.1 The base-URL rule
#
# Send every script and notebook request to the catalogue's `base_url`. The website
# (`website_proxy_url`) forwards API calls only for SurgeFlow's own pages, and it may not send
# the CORS headers that other apps need.

# %%
print(f"Catalogue base_url : {catalog['base_url']}")
print(f"Website proxy      : {catalog['website_proxy_url']}  (same-origin SurgeFlow pages only)")
print(f"This notebook calls: {BASE_URL}")
print()
print(textwrap.fill(catalog["website_proxy_release_note"], 100))
if BASE_URL.rstrip("/") != catalog["base_url"].rstrip("/"):
    print(f"\nWarning: BASE_URL differs from the catalogue. Unset SURGEFLOW_BASE_URL to use {catalog['base_url']}.")

# %% [markdown]
# ### 4.2 Sending your key
#
# The catalogue lists four ways to send a key. Use the first one. The helper already does.

# %%
auth = catalog["authentication"]


def advice(option: str) -> str:
    if option == auth["recommended"]:
        return "Yes. Recommended, and what sf_get sends."
    if "query" in option.lower():
        return "Quick tests only: URLs end up in logs and browser history."
    return "Only if a tool cannot send an Authorization header."


auth_options = pd.DataFrame({"option": [auth["recommended"]] + auth["also_supported"]})
auth_options["use it?"] = auth_options["option"].map(advice)
print("Catalogue note:", auth["note"])
auth_options

# %% [markdown]
# Outside Python, the same request with `curl` reads the key from an environment variable that
# you fill from a hidden prompt, so the key stays out of the command line and your shell history.
# (Typing `export SURGEFLOW_API_KEY=sf_live_...` would save the key in `~/.bash_history` or
# `~/.zsh_history`.)
#
# ```bash
# read -rs SURGEFLOW_API_KEY && export SURGEFLOW_API_KEY   # paste the key, press Enter: nothing is shown
# curl -H "Authorization: Bearer $SURGEFLOW_API_KEY" https://stock-api-c4qdowjxva-uc.a.run.app/api/v1/me
# ```
#
# Without a key, an authenticated endpoint answers HTTP 401 with this body:
#
# ```json
# {"ok": false, "error": {"code": "API_KEY_REQUIRED",
#  "message": "Provide a SurgeFlow API key with `Authorization: Bearer sf_live_...`."}}
# ```

# %% [markdown]
# ### 4.3 Plans and free limits

# %%
plans = pd.DataFrame.from_dict(catalog["plans"], orient="index").rename_axis("plan").reset_index()
plans["scopes_granted"] = plans["scopes"].map(len)
display(plans[["plan", "daily_limit", "minute_limit", "scopes_granted", "issuance_state"]])

free = catalog["plans"]["free"]
print(f"Free plan: {free['daily_limit']:,} requests per day and {free['minute_limit']} per minute, per key.")
print(f"sf_get waits about 0.4 s between calls, so it peaks near {60 / 0.4:.0f} per minute: under the limit.")
print(f"A kit notebook stays under ~{NOTEBOOK_BUDGET} requests, so the free plan covers about "
      f"{free['daily_limit'] // NOTEBOOK_BUDGET} full runs a day.")

# %% [markdown]
# Scopes are permissions. A key can call an endpoint only if its plan grants that endpoint's scope.

# %%
all_scopes = sorted({s for p in catalog["plans"].values() for s in p["scopes"]})
scope_matrix = pd.DataFrame({name: ["✓" if s in p["scopes"] else "·" for s in all_scopes]
                             for name, p in catalog["plans"].items()}, index=all_scopes).rename_axis("scope")
scope_matrix.T

# %% [markdown]
# ### 4.4 The authenticated endpoints (tidy table)
#
# `KIT_MAP` records which notebook of this kit teaches each endpoint (the first name in each
# list) and which notebooks use it again. We join it to the catalogue, so a new endpoint shows up
# as "not in the kit yet". `RETIRED` marks endpoints the kit no longer calls: the AI research
# committee is paused, and its two endpoints answer HTTP 410.

# %%
KIT_MAP = {
    "/api/v1/health": ["00-setup-and-account", "02-ml-map-and-whales"],
    "/api/v1/catalog": ["00-setup-and-account"],
    "/api/v1/me": ["00-setup-and-account"],
    "/api/v1/summary": ["00-setup-and-account"],
    "/api/v1/markets/{market}/screen": ["01-market-boards", "02-ml-map-and-whales", "05-ml-lab"],
    "/api/v1/markets/{market}/realtime": ["01-market-boards", "05-ml-lab"],
    "/api/v1/markets/{market}/hotlist": ["01-market-boards"],
    "/api/v1/markets/{market}/sector": ["01-market-boards", "03-news-notes-macro-bonds"],
    "/api/v1/markets/{market}/ml/clusters": ["02-ml-map-and-whales", "05-ml-lab"],
    "/api/v1/markets/{market}/whales": ["02-ml-map-and-whales", "05-ml-lab"],
    "/api/v1/markets/{market}/news": ["03-news-notes-macro-bonds"],
    "/api/v1/notes/daily": ["03-news-notes-macro-bonds"],
    "/api/v1/macro/calendar": ["03-news-notes-macro-bonds"],
    "/api/v1/bond/etfs": ["03-news-notes-macro-bonds"],
    "/api/v1/markets/{market}/factor-portfolios": ["04-factor-portfolios", "05-ml-lab"],
    "/api/v1/markets/{market}/factor-portfolios/meta": ["04-factor-portfolios", "05-ml-lab"],
}
RETIRED = {
    "/api/v1/ai/ratings": "retired: AI committee paused (HTTP 410)",
    "/api/v1/ai/grade-book": "retired: AI committee paused (HTTP 410)",
}

# %% [markdown]
# **Cleaning.** Keep four columns: `method`, `path`, `scope` and `description` (a missing one
# raises, which means the catalogue changed). De-duplicate on the natural key, (`method`, `path`).
# Shorten long descriptions for display. The cell counts what each step changes.

# %%
DESCRIPTION_CHARS = 110  # display width only; the catalogue keeps the full text

endpoints = pd.DataFrame(catalog["authenticated_endpoints"]).loc[:, ["method", "path", "scope", "description"]]
n_listed = len(endpoints)
endpoints = endpoints.drop_duplicates(subset=["method", "path"]).reset_index(drop=True)
n_long = int((endpoints["description"].str.len() > DESCRIPTION_CHARS).sum())
endpoints["description"] = endpoints["description"].str.slice(0, DESCRIPTION_CHARS)
endpoints["taught in"] = endpoints["path"].map(lambda p: KIT_MAP[p][0] if p in KIT_MAP else RETIRED.get(p, "not in the kit yet"))
print(f"Listed: {n_listed} | duplicate (method, path) rows dropped: {n_listed - len(endpoints)} | "
      f"descriptions shortened to {DESCRIPTION_CHARS} characters: {n_long}")
print(f"{len(endpoints)} authenticated endpoints; methods: {sorted(endpoints['method'].unique())}")
with pd.option_context("display.max_colwidth", 120):
    display(endpoints)

# %% [markdown]
# The open endpoints, for completeness. `POST /api/v1/keys` is what the membership form uses to
# issue keys. Do not call it from a notebook; create keys on the website.

# %%
pd.DataFrame(catalog["open_endpoints"])[["method", "path", "auth", "description"]]

# %% [markdown]
# **Endpoints per scope: which permission unlocks what.** Each scope unlocks only one or two
# endpoints, so bar lengths would say almost nothing here. A stat line and a table do this job
# better than a chart.

# %%
free_scopes = set(free["scopes"])
scope_view = endpoints.assign(
    short=endpoints["path"].str.replace("/api/v1/", "", regex=False).str.replace("markets/{market}/", "{m}/", regex=False),
    in_free=endpoints["scope"].isin(free_scopes | {"any"}),
    retired=endpoints["path"].isin(RETIRED),
)
by_scope = (scope_view.groupby("scope", as_index=False)
            .agg(endpoints=("path", "size"), names=("short", " · ".join), in_free=("in_free", "all"),
                 retired=("retired", "all"))
            .sort_values(["endpoints", "scope"], ascending=[False, True]).reset_index(drop=True))
n_retired = int(scope_view["retired"].sum())
n_free = int((scope_view["in_free"] & ~scope_view["retired"]).sum())
print(f"Free keys can call {n_free} of {len(endpoints) - n_retired} current authenticated endpoints, "
      f"spread over {int((~by_scope['retired']).sum())} scopes. /me accepts any valid key (scope “any”).")
if n_retired:
    print(f"Not counted: {n_retired} retired AI endpoints (AI committee paused, HTTP 410; the kit no longer calls them).")
not_free = by_scope.loc[~by_scope["in_free"] & ~by_scope["retired"], "scope"].tolist()
print("Scopes not on the free plan:", ", ".join(not_free) if not_free else "none")
(by_scope.assign(free=[("retired (HTTP 410)" if r else "✓ free" if f else "✕ not on free")
                       for f, r in zip(by_scope["in_free"], by_scope["retired"])])
 [["scope", "endpoints", "free", "names"]]
 .rename(columns={"names": "endpoint paths ({m} = market)"}))

# %% [markdown]
# **How to read this**
#
# - Each row is a scope (a permission) and the endpoints it unlocks. `{m}` stands for a market code.
# - Most scopes unlock one endpoint. `screen` also covers `sector`, `macro` covers the calendar
#   and bond ETFs, and `factors` covers the factor portfolios and their `/meta` route. The paused
#   AI committee's endpoints are retired (HTTP 410); if the catalogue still lists them, or an `ai`
#   scope, they are marked retired and not counted.
# - The `free` column says whether a free key holds that scope. Section 5 checks the scopes of your
#   own key.

# %% [markdown]
# ### 4.5 Where the records live
#
# Every response is a JSON object, and the rows you want sit at a **path** inside it.
# The catalogue says where in words (`response_shapes`). The helper says the same thing as a
# tuple of keys (`RESPONSE_SHAPES`), and `records(payload, shape)` follows that path for you:

# %%
example = {"ok": True, "data": {"rows": [{"ticker": "AAA"}, {"ticker": "BBB"}]}}  # a made-up payload
print("RESPONSE_SHAPES['realtime'] =", RESPONSE_SHAPES["realtime"])
print("records(example, 'realtime') ->", records(example, "realtime"))
print("dig(example, 'data', 'rows') ->", dig(example, "data", "rows"), "(the same walk, by hand)")

# %% [markdown]
# Now compare the two sources, key by key. One helper key is a companion of a catalogue entry:
# `ml_anomalies` is the second list in the `ml/clusters` response.
#
# Some catalogue entries name two kinds of path. The factor portfolios' entries read like
# "state at payload.data.status; per-factor portfolios at payload.data.portfolios": the **state**
# says whether there is anything to read, and the **records** are the list itself. The cell keeps
# the two apart, so only record paths are compared with `RESPONSE_SHAPES`.

# %%
def catalogue_paths(sentence: str) -> tuple[list[tuple], list[tuple]]:
    """Split a response_shapes sentence into (record paths, state paths).

    'state at payload.data.status; publications at payload.data.publications'
    -> ([('data', 'publications')], [('data', 'status')])
    """
    record_paths, state_paths = [], []
    for clause in re.split(r"[;,]", sentence):
        found = [tuple(p.split(".")) for p in re.findall(r"payload\.([A-Za-z_][\w.]*\w)", clause)]
        (state_paths if clause.strip().lower().startswith("state") else record_paths).extend(found)
    return record_paths, state_paths


def dotted(paths: list[tuple]) -> str:
    return " + ".join("payload." + ".".join(p) for p in paths) or "-"


COMPANION = {"ml_anomalies": "ml_clusters"}
helper_groups = defaultdict(list)
for key, path in RESPONSE_SHAPES.items():
    helper_groups[COMPANION.get(key, key)].append((key, path))

shape_rows = []
for shape in sorted(set(catalog["response_shapes"]) | set(helper_groups)):
    from_catalog, state_at = catalogue_paths(catalog["response_shapes"].get(shape, ""))
    from_helper = [path for _, path in helper_groups.get(shape, [])]
    if not from_helper:
        verdict = "catalogue only"
    elif not from_catalog:
        verdict = "helper only"
    else:
        verdict = "✓ match" if set(from_catalog) == set(from_helper) else "✕ differs"
    shape_rows.append({
        "shape": shape,
        "catalogue: records at": dotted(from_catalog),
        "catalogue: state at": dotted(state_at),
        "RESPONSE_SHAPES": " + ".join(f"{k}: {'.'.join(p)}" for k, p in helper_groups.get(shape, [])) or "-",
        "verdict": verdict,
    })
shapes = pd.DataFrame(shape_rows)
print(shapes["verdict"].value_counts().to_string())
with_state = shapes.loc[shapes["catalogue: state at"] != "-", "shape"].tolist()
print("Shapes that also name a state path:", ", ".join(with_state) or "none")
shapes

# %% [markdown]
# What the comparison teaches:
#
# - **Depth varies.** `screen` keeps rows at the top level (`payload.rows`). Most endpoints use
#   `payload.data.<list>`, and so do the factor portfolios: one book per factor at
#   `payload.data.portfolios`, and the publication list of `/factor-portfolios/meta` at
#   `payload.data.publications`. The macro calendar and bond ETFs wrap twice
#   (`payload.data.data.<list>`). Always use the documented path; never guess.
# - **Read the state before the records.** Both factor-portfolio shapes also name
#   `payload.data.status`: `"available"`, or `"empty"` when there is nothing to read, for example
#   a market without a publication. An empty answer is still HTTP 200 with `"ok": true`; it
#   carries a `reason_code` and a `message` instead of records, so show the message.
# - **Not every main block is a list.** The factor portfolios' weekly returns sit beside the
#   books at `payload.data.returns`, a *dict keyed by factor* (each value a list of weekly rows).
#   For `whales`, `payload.data.signal_board.signals` is a *dict of six boards*. So
#   `records(payload, "whales")` returns `[]`, and the whales notebook loops over the boards instead.
# - **`addin` is not a v1 endpoint.** It describes the keyless Google Sheets add-on namespace
#   (`/api/addin/...`), whose rows sit at `payload.rows`. The v1 helper does not need it.
# - **Retired endpoints drop out.** The paused AI committee's endpoints answer HTTP 410
#   (`ENDPOINT_RETIRED`), and the helper dropped their shapes. If the catalogue still lists one
#   when you run this, it reads "catalogue only" in the table.
# - **Two endpoints have no entry at all.** `/api/v1/me` is one flat object. `/api/v1/summary`
#   keeps one record per market at `payload.data.markets`, a path checked against a live response.
#   Section 6 still checks it before using it, because the summary can be unavailable now and then.

# %% [markdown]
# ### 4.6 Markets, and what an error looks like
#
# The catalogue lists the supported markets. A retired market is refused, and `sf_get` raises
# `SurgeFlowError` with the HTTP status and SurgeFlow's error code. Catch it like this:

# %%
if set(catalog["markets"]) == set(MARKETS):
    print(f"Catalogue markets match the helper's MARKETS: {', '.join(MARKETS)}")
else:
    print(f"Markets differ. Catalogue: {catalog['markets']} | helper: {list(MARKETS)}. Trust the catalogue.")

try:
    sf_get("/api/v1/markets/tw/hotlist")  # Taiwan was retired
    print("tw answered without an error. Check the catalogue: the market list may have changed.")
except SurgeFlowError as err:
    if err.status in (401, 403):  # the key failed before the market was even checked
        print(f"Key problem (HTTP {err.status} {err.code}), not a market problem: see “Check your key” in section 2.")
    elif err.status in (400, 404, 422) or "MARKET" in err.code:
        print(f"tw -> HTTP {err.status}, code {err.code}. Use one of: {', '.join(catalog['markets'])}.")
    else:  # a server-side failure, for example: say what it is rather than blame the market
        print(f"tw -> HTTP {err.status}, code {err.code}. That is not the usual market refusal: {err}")

# %% [markdown]
# Errors come in three forms. `sf_get` turns each one into a `SurgeFlowError`:
#
# | What you get back | Example | What `sf_get` does |
# |---|---|---|
# | An HTTP error with an error envelope | `401 API_KEY_REQUIRED`; a 4xx `VALIDATION_ERROR` when a parameter is out of range, such as `page_size` above 100 on the screen; `400 INVALID_FACTOR`, `INVALID_DATE` or `INVALID_MARKET` from the factor portfolios; `410 ENDPOINT_RETIRED` from the retired AI endpoints | raises at once |
# | **HTTP 200** with a failure inside `data` | `{"ok": true, "data": {"ok": false, "error": {"code": "INTERNAL_ERROR", "message": "news feed temporarily unavailable"}}}` | raises: the outer `ok` is not the whole story |
# | A server error | `HTTP 500 Internal Server Error` with a plain-text body; `HTTP 503` when the factor portfolios cannot be read | retries, then raises (code `NON_JSON` for a plain-text body) |
#
# One more answer looks like a problem but is not: an **empty state**. The factor portfolios answer
# HTTP 200 with `{"ok": true, "data": {"status": "empty", "reason_code": ..., "message": ...}}` for a
# market without a publication (`no_publication_for_market`) or a `formation_date` that was not
# published (`formation_date_not_published`). `sf_get` returns it like any other payload; check
# `data.status` and show `data.message`.
#
# For an optional section, use `sf_try` instead of `sf_get`. It prints a short note and returns
# `None`, so the rest of the notebook keeps running. The note says which kind of failure it was: a
# retired endpoint (410), a rejected request (another 4xx, such as a 400 for a bad parameter: fix
# the call, because retrying will not help) or an endpoint that is unavailable right now (a 5xx, or
# an error inside a 200: try again later). Section 6 uses it.

# %% [markdown]
# **Caveats**
#
# - The catalogue is in **beta** (`status`). Read it at the start of a project, not on every run.
# - Descriptions are short summaries and can run ahead of, or behind, the data. The responses
#   carry their own labels, states and freshness fields; read those too.
# - Some parameter limits appear only in descriptions (news `limit` up to 50, macro `days` up to
#   60, factor-portfolio `weeks` up to 1000 and `holdings` 0 to 5000) and some not at all (screen
#   `page_size` up to 100). The notebook for each endpoint states them.
# - The admin endpoints listed in the catalogue need an admin token. They are not for members.

# %% [markdown]
# ## 5. Your key: plan, scopes, limits and usage
#
# `GET /api/v1/me` describes **the key you are using**: its plan, its scopes, its rate-limit
# counters and how much it has been used. It never returns the secret, and it is the cheapest
# way to check that a key works.
#
# **Privacy first.** `/me` also returns fields that identify you: the start of your key
# (`key_prefix`), your member ID, your referral code and invite link, your referral counts, when
# your key was created (`key_created_at`), and your founding-analyst flag and number.
# Screenshots and shared notebooks travel, so this notebook **never displays them**. It shows an
# allow-list of four fields instead: `plan`, `scopes`, `rate_limit` and `usage`. Every other field,
# including any new one, stays hidden. (The usage chart uses `key_created_at` only to work out the
# key's age in whole days. The timestamp itself is never shown.)
#
# The key check in section 2 already made this call (`me = sf_get("/api/v1/me")`), so this section
# reads that response instead of spending another request. Its counters are therefore a snapshot from
# that moment, a few requests ago. If the key had been rejected, the check would have stopped there.

# %%
show_freshness(me, "Key:")

SAFE_TO_SHOW = ["plan", "scopes", "rate_limit", "usage"]  # an allow-list: any new field stays hidden
me_view = {k: me[k] for k in SAFE_TO_SHOW}               # a missing one raises: the contract changed
print(f"Showing {len(me_view)} of {len(me)} top-level fields. The other {len(me) - len(me_view)} stay hidden on purpose.")

# %% [markdown]
# `/me` is about your key, not about markets, so there is no as-of date. The times that matter are
# the moment `/me` answered (its counters are a snapshot) and `usage.last_used_at`.
#
# **Raw preview** of the four allowed fields:

# %%
me_preview = pd.json_normalize(me_view, sep=".").T.rename(columns={0: "value"})
me_preview["value"] = me_preview["value"].map(lambda v: ", ".join(map(str, v)) if isinstance(v, list) else str(v))
with pd.option_context("display.max_colwidth", 90):
    display(me_preview)

# %% [markdown]
# **Cleaning.** `rate_limit` arrives as text, with keys named like HTTP rate-limit headers
# (`"X-RateLimit-Daily-Limit": "2000"`). We convert the values to numbers.
#
# | `rate_limit` key | Meaning |
# |---|---|
# | `X-RateLimit-Limit` | requests allowed per minute |
# | `X-RateLimit-Remaining` | requests left in the current minute |
# | `X-RateLimit-Daily-Limit` | requests allowed per day |
# | `X-RateLimit-Daily-Remaining` | requests left in the current daily window |
# | `X-SurgeFlow-RateLimit-Store` | where the counter is kept (a backend detail) |
#
# The counters already include the `/me` request itself. The usage counters become numbers and
# `last_used_at` becomes a UTC time. If `/me` ever stops reporting a limit, the code takes it from
# the catalogue's plan table and says so.
#
# **Key age.** A key created two days ago cannot have used 7 days of capacity. So the per-day
# averages and the capacity of the 7- and 30-day windows use the days the key actually existed in
# each window: `min(window, key age)`, with the age rounded up to whole days. A brand-new key, the
# usual case for this first notebook, counts as 1 day old.

# %%
plan = me["plan"]
key_scopes = sorted(me["scopes"])
usage = me["usage"]
rate = {key: pd.to_numeric(value, errors="coerce") for key, value in me["rate_limit"].items()}

used_7d = pd.to_numeric(usage["used_7d"], errors="coerce")
used_30d = pd.to_numeric(usage["used_30d"], errors="coerce")
last_used = pd.to_datetime(usage.get("last_used_at"), utc=True, errors="coerce")
# Key age in whole days, rounded up (at least 1). key_created_at is used here only; it is never displayed.
key_created = pd.to_datetime(me.get("key_created_at"), utc=True, errors="coerce")
if pd.isna(key_created):
    age_days = np.inf
    print("/me did not report key_created_at, so the 7- and 30-day windows assume a key at least 30 days old.")
else:
    age_days = max(1, int(np.ceil((pd.Timestamp.now(tz="UTC") - key_created).total_seconds() / 86400)))
days_7, days_30 = min(7, age_days), min(30, age_days)


def key_age_note(window: int) -> str:
    """'' when the key is at least as old as the window, else ' (key is 2 days old)'."""
    return "" if age_days >= window else f" (key is {age_days} day{'s' if age_days != 1 else ''} old)"


plan_row = catalog["plans"].get(plan)
if plan_row is None:
    print(f"The catalogue does not list plan '{plan}'. Limits below come from /me only.")


def limit_from(rate_key: str, plan_key: str) -> tuple:
    """A limit from /me rate_limit when it is reported, else from the catalogue's plan table."""
    value = rate.get(rate_key)
    if value is not None and pd.notna(value):
        return int(value), "/me rate_limit"
    if plan_row is None:
        raise KeyError(f"Neither /me ({rate_key}) nor the catalogue reports this key's {plan_key}.")
    return int(plan_row[plan_key]), "catalogue plan table"


daily_limit, daily_source = limit_from("X-RateLimit-Daily-Limit", "daily_limit")
minute_limit, minute_source = limit_from("X-RateLimit-Limit", "minute_limit")
daily_left = rate.get("X-RateLimit-Daily-Remaining", np.nan)
minute_left = rate.get("X-RateLimit-Remaining", np.nan)
used_today = daily_limit - daily_left if pd.notna(daily_left) else np.nan

counters = {"used_7d": used_7d, "used_30d": used_30d, "daily remaining": daily_left, "minute remaining": minute_left}
print("Counters that are missing or not numeric:", [k for k, v in counters.items() if pd.isna(v)] or "none")

key_card = pd.Series({
    "plan": plan,
    "scopes": f"{len(key_scopes)}: {', '.join(key_scopes)}",
    "daily limit": f"{daily_limit:,} requests (from {daily_source})",
    "minute limit": f"{minute_limit:,} requests (from {minute_source})",
    "used in the current daily window": "not reported" if pd.isna(used_today)
                                        else f"{used_today:,.0f} ({daily_left:,.0f} left)",
    "left in the current minute": "not reported" if pd.isna(minute_left) else f"{minute_left:,.0f} of {minute_limit:,}",
    "used, last 7 days": f"{used_7d:,.0f} (about {used_7d / days_7:.1f} per day){key_age_note(7)}",
    "used, last 30 days": f"{used_30d:,.0f} (about {used_30d / days_30:.1f} per day){key_age_note(30)}",
    "days with member-data use, last 30": str(usage.get("value_days_30d", "not reported")),
    "last used (UTC)": "never" if pd.isna(last_used) else f"{last_used:%Y-%m-%d %H:%M}",
    "this notebook so far": f"{api_calls_used()} requests through sf_get",
}, name="your key")
display(key_card.to_frame())
if pd.notna(used_today) and pd.notna(used_7d) and used_today > used_7d:
    print(f"Today's live counter ({used_today:,.0f}) is above the 7-day total ({used_7d:,.0f}). That is expected: "
          "the usage ledger is updated in batches, so it can lag by a few minutes (see usage['note']).")

# %% [markdown]
# **Chart: usage against your limits.** A progress bar per time window. The pale track is the
# most you could use in that window: the daily limit times the number of days the key existed in
# it. The fill is what you used. Today's bar comes from the live counter; the 7- and 30-day bars
# come from the usage ledger.

# %%
windows = pd.DataFrame({
    "window": ["Today (daily window)", "Last 7 days" + key_age_note(7), "Last 30 days" + key_age_note(30)],
    "used": [used_today, used_7d, used_30d],
    "capacity": [daily_limit, days_7 * daily_limit, days_30 * daily_limit],
    "counted by": ["rate_limit counter (live)", "usage.used_7d (ledger)", "usage.used_30d (ledger)"],
})
if pd.isna(used_today):  # /me did not report the daily counter: show this session instead
    windows.loc[0, ["window", "used", "counted by"]] = ["This notebook so far", api_calls_used(), "api_calls_used()"]
missing_windows = windows.loc[windows["used"].isna(), "window"].tolist()
windows = windows.dropna(subset=["used"]).reset_index(drop=True)
windows["share"] = windows["used"] / windows["capacity"]


def meter_level(fraction: float) -> str:
    """Severity of a usage share: below 70% is fine, 70-90% is a warning, 90% and above is critical."""
    return "good" if fraction < 0.7 else "warning" if fraction < 0.9 else "critical"


# Neutral ink while there is room; a magenta ramp only when there is a state to signal. Magenta is
# outside every market's hue family (ΔE76 above 50 from all four MARKET_COLORS), so it never reads as
# a market, and both shades stay visible on the pale track (3.7:1 and 7.1:1 against GRID).
METER_COLORS = {"good": INK_2, "warning": "#b5459b", "critical": "#7a1f6e"}
windows["level"] = windows["share"].map(meter_level)
windows["fill"] = windows["level"].map(METER_COLORS)
# A tiny share (0.3% is about 1 px) would look like "unused". Draw any use as at least a short stub;
# the label and the hover keep the exact share.
MIN_VISIBLE = 0.012
windows["drawn"] = np.where(windows["used"] > 0, np.maximum(windows["share"], MIN_VISIBLE), 0.0)
windows["label"] = [f"{u:,.0f} of {c:,.0f}  ({share(s)})" + ("" if lv == "good" else f"  {STATUS_ICONS[lv]} near the limit")
                    for u, c, s, lv in zip(windows["used"], windows["capacity"], windows["share"], windows["level"])]

first = windows.iloc[0]
headline = {"good": "Plenty of headroom", "warning": "Watch your budget", "critical": "Almost out of requests"}[first["level"]]
if first["window"].startswith("Today"):
    title = f"{headline}: {first['used']:,.0f} of {daily_limit:,} requests used today ({share(first['share'])})"
else:
    title = f"{headline}: this notebook has used {first['used']:,.0f} of today's {daily_limit:,} requests"

fig = go.Figure()
fig.add_trace(go.Bar(y=windows["window"], x=[1.0] * len(windows), orientation="h", width=0.5,
                     marker=dict(color=GRID, line=dict(width=0)), hoverinfo="skip", showlegend=False))
fig.add_trace(go.Bar(y=windows["window"], x=windows["drawn"], orientation="h", width=0.5,
                     marker=dict(color=windows["fill"], line=dict(width=0)), showlegend=False,
                     customdata=list(zip(windows["used"], windows["capacity"], windows["counted by"], windows["share"])),
                     hovertemplate="<b>%{y}</b><br>%{customdata[0]:,.0f} of %{customdata[1]:,.0f} requests"
                                   "<br>%{customdata[3]:.2%} of capacity<br>Counted by: %{customdata[2]}<extra></extra>"))
for row in windows.itertuples():  # the numbers, to the right of each track
    fig.add_annotation(x=1.02, xref="paper", xanchor="left", y=row.window, showarrow=False, align="left",
                       text=row.label, font=dict(color=INK, size=12))
next_run = (first["used"] + NOTEBOOK_BUDGET) / daily_limit  # where one more kit notebook would take today's bar
if next_run <= 1:
    fig.add_trace(go.Scatter(x=[next_run], y=[first["window"]], mode="markers", showlegend=False,
                             marker=dict(symbol="line-ns", size=26, line=dict(width=2, color=INK_2)),
                             hovertemplate=f"After one more kit notebook (about {NOTEBOOK_BUDGET} requests): "
                                           f"{next_run:.0%} of the day<extra></extra>"))
    fig.add_annotation(x=next_run, y=first["window"], yshift=20, showarrow=False, xanchor="left",
                       text=f" + one kit notebook (≈{NOTEBOOK_BUDGET} requests)", font=dict(color=INK_2, size=11))
fig.update_layout(
    barmode="overlay", barcornerradius=2, height=300, margin=dict(l=230, r=210, t=85, b=55),
    title=chart_title(title, f"Plan “{plan}”: {daily_limit:,} requests a day, {minute_limit:,} a minute. "
                             "Track = the window's capacity; fill = what you used."),
    xaxis=dict(range=[0, 1], tickformat=".0%", title="Share of the window's capacity (%)", showgrid=True),
    yaxis=dict(categoryorder="array", categoryarray=list(windows["window"])[::-1], title=None, ticks="",
               ticksuffix="  "),
)
fig.show()
if missing_windows:
    print(f"Not plotted (counter missing): {', '.join(missing_windows)}")
if pd.notna(daily_left):
    print(f"{daily_left:,.0f} requests left today: room for about {daily_left // NOTEBOOK_BUDGET:.0f} more kit notebooks.")
windows[["window", "used", "capacity", "share", "counted by"]]

# %% [markdown]
# **How to read this**
#
# - Each bar is a time window. A full bar would mean you used your whole daily limit on every day
#   the key existed in that window. A key younger than the window gets a shorter track, and the
#   window's name says how old the key is.
# - Any use is drawn as at least a short stub, so a tiny share does not look like "unused". The
#   numbers on the right are exact.
# - The thin mark on the top bar shows where one more kit notebook (`NOTEBOOK_BUDGET`) would take you.
# - The fill is grey while there is plenty of room. It turns magenta with a "!" above 70% and deep
#   magenta with a "✕" above 90%. On the free plan that is rare. (Magenta, because the other hues
#   in this kit name markets.)
#
# **Which endpoints can this key call?** Join your scopes to the catalogue:

# %%
access = endpoints[["path", "scope"]].copy()
access["your key"] = ["retired (HTTP 410)" if p in RETIRED
                      else "✓ allowed" if s == "any" or s in key_scopes else "✕ missing scope"
                      for p, s in zip(access["path"], access["scope"])]
n_access_retired = int(access["path"].isin(RETIRED).sum())
print(f"This key can call {access['your key'].str.startswith('✓').sum()} of {len(access) - n_access_retired} "
      "current authenticated endpoints.")
if n_access_retired:
    print(f"{n_access_retired} retired AI endpoints answer HTTP 410 (AI committee paused) and are not counted.")
access

# %% [markdown]
# **Caveats**
#
# - `used_7d` and `used_30d` count requests over the last 7 and 30 days. They are rolling windows,
#   so they shrink again as old requests age out. The ledger behind them is updated in batches.
# - The `rate_limit` counters are a snapshot from the moment `/me` answered. Every later request
#   lowers the "remaining" numbers.
# - The daily limit applies per key. Several notebooks using the same key share it.
# - An HTTP 429 means "slow down". `sf_get` waits as the `Retry-After` header asks, then retries.
# - `first_value_reached`, `value_days_30d` and `repeat_value_reached` describe activity. They are
#   not limits.
# - If support asks for your member ID, print it in a scratch cell, copy it, and clear that cell's
#   output before you save or share the notebook.

# %% [markdown]
# ## 6. Four-market summary (optional section)
#
# `GET /api/v1/summary` (scope `summary`) is a market-watch overview: one record per market,
# with its last end-of-day (EOD) session, breadth counts, turnover and FX rates.
#
# **This section can be skipped.** The summary answers normally, and the fields used below have
# been checked against a live response. It can still fail now and then: an
# `HTTP 500 Internal Server Error` with a plain-text body can happen. So we call it with `sf_try`,
# which prints a note and returns `None` when the endpoint is unavailable, and allow a single
# retry. Every later cell that needs the summary checks `summary_ready` first.

# %%
summary = sf_try("/api/v1/summary", retries=1)  # optional section: one retry, then move on
summary_markets = dig(summary, "data", "markets")
summary_ready = isinstance(summary, dict) and summary.get("ok") is True and isinstance(summary_markets, list)
summary_built = pd.NaT
if summary_ready:
    show_freshness(summary, "Summary:")
    summary_built = pd.to_datetime(dig(summary, "data", "timestamp"), utc=True, errors="coerce")
    built = "build time not given" if pd.isna(summary_built) else f"built {summary_built:%Y-%m-%d %H:%M} UTC"
    print(f"Summary {built} | {len(summary_markets)} market records")
    if not summary_markets:
        summary_ready = False
        print("The summary returned no markets right now. That can happen during a rebuild; try again in a few minutes.")
elif summary is not None:
    received = ", ".join(f"`{k}`" for k in summary) or "nothing"
    display(Markdown("**The summary answered, but without `\"ok\": true` and a `data.markets` list**, so this "
                     f"section is skipped (top-level keys received: {received})."))
if not summary_ready:
    print("Sections 6 and 7.2-7.3 will skip their cells. Everything else in this notebook still runs.")

# %% [markdown]
# Summary keeps its freshness per market (`as_of_date`), so `show_freshness` finds little at the
# top. We print the dates in the table below. **Raw preview** (scalar fields only; several fields
# are nested objects). The cell also checks that the fields this section needs are present.

# %%
SUMMARY_FIELDS = ["market", "as_of_date", "eod_session_complete", "institutional_count", "surge_count",
                  "above_ma10_count", "avg_change_pct", "total_turnover", "surge_definition"]
if not summary_ready:
    print("Skipped: the summary is unavailable right now.")
else:
    summary_raw = pd.DataFrame(summary_markets)
    scalar_cols = [c for c in summary_raw.columns if not summary_raw[c].map(lambda v: isinstance(v, (dict, list))).any()]
    print(f"{summary_raw.shape[1]} fields per market; {len(scalar_cols)} are scalars.")
    display(summary_raw[scalar_cols].head())
    missing_fields = [c for c in SUMMARY_FIELDS if c not in summary_raw.columns]
    if missing_fields:
        summary_ready = False
        print(f"These expected fields are missing: {missing_fields}. The summary's shape differs from the one this "
              "kit was checked against, so its charts are skipped. The preview above shows what arrived.")

# %% [markdown]
# **Cleaning.**
#
# - `total_turnover` is in **local currency**: each exchange trades in its own currency. We write
#   that down once (`LOCAL_CURRENCY`) and check it with no extra request: every `market_cap_history`
#   row states its `currency`. If that currency agrees with `LOCAL_CURRENCY`, we convert. If it
#   disagrees, `total_turnover_usd` is left blank (NaN) for that market and the cell says so,
#   because a yen/dollar mix-up is a 150x error. With no stated currency the check cannot run, so the
#   cell uses `LOCAL_CURRENCY` and marks the turnover "unverified". The FX table gives **local units
#   per USD**, so dividing converts to USD.
# - The history row for the summary's own session (`as_of_date`) also carries a
#   `total_turnover_local`. It sums a different set of names (its `covered_tickers`), so it is not
#   expected to equal `total_turnover`; the cell reports the gap (`gap_vs_history`) as information.
#   Only a gap of more than 2x, the size of a unit or currency mix-up, blanks the USD turnover.
# - `avg_change_pct` is a **decimal** (0.01 means +1%), like `change_pct` on the screen. Checked
#   against a live response, it is the plain mean of the day's `change_pct` over the market screen's
#   names (`institutional_count` of them), every name counting equally. The realtime board's
#   `intraday_return_pct`, by contrast, is a percent. So the cell keeps a guard against a unit
#   change: a market-wide *average* daily move above 20% is implausible, so a larger value means
#   the field has become a percent, and panel 2 is then left blank. (The guard only catches a day
#   on which some market's average moved at least 0.2%.)
# - Breadth counts become shares of `institutional_count`. This kit takes that as the universe that
#   `surge_count` and `above_ma10_count` are counted over; the summary does not name the
#   denominator, and a record also carries larger counts (`screen_eligible_tickers`,
#   `ticker_count`). The cell checks that no count exceeds `institutional_count`. If one does, the
#   shares are left blank.

# %%
LOCAL_CURRENCY = {"us": "USD", "cn": "CNY", "jp": "JPY", "hk": "HKD"}

if not summary_ready:
    print("Skipped: no summary to clean.")
else:
    fx = pd.Series(dig(summary, "data", "fx_rates", default={}) or {}, dtype=float)
    if not fx.empty:
        fx.index = fx.index.astype(str).str.replace("PerUsd", "", regex=False).str.upper()  # 'jpyPerUsd' -> 'JPY'
    fx["USD"] = 1.0

    def history_currencies(record: dict) -> list:
        """The distinct currencies that the record's market_cap_history rows state."""
        history = record.get("market_cap_history")
        rows = history if isinstance(history, list) else []
        return sorted({str(h["currency"]) for h in rows if isinstance(h, dict) and h.get("currency")})

    def same_session_row(record: dict):
        """The market_cap_history row dated as_of_date (the summary's own session), or None."""
        as_of = pd.to_datetime(record.get("as_of_date"), errors="coerce")
        history = record.get("market_cap_history")
        if pd.isna(as_of) or not isinstance(history, list):
            return None
        rows = [h for h in history if isinstance(h, dict) and pd.to_datetime(h.get("date"), errors="coerce") == as_of]
        return rows[-1] if rows else None

    MIXUP_RATIO = 2.0  # amounts this far apart point to a unit or currency mix-up, not to a different set of names

    mk = summary_raw.loc[:, SUMMARY_FIELDS].copy()
    for col in ["institutional_count", "surge_count", "above_ma10_count", "avg_change_pct", "total_turnover"]:
        mk[col] = pd.to_numeric(mk[col], errors="coerce")

    # Currency check: the market_cap_history rows state the currency of this market's amounts.
    currencies = [history_currencies(r) for r in summary_markets]  # same order as summary_raw and mk
    mk["reported_currency"] = [c[0] if len(c) == 1 else None for c in currencies]
    expected_currency = mk["market"].map(LOCAL_CURRENCY)
    # The same session's total_turnover_local sums a different set of names, so it is compared, not required to match.
    session_rows = [same_session_row(r) for r in summary_markets]
    history_turnover = pd.to_numeric(pd.Series([r.get("total_turnover_local") if r else None for r in session_rows],
                                               index=mk.index), errors="coerce")
    ratio = mk["total_turnover"] / history_turnover.where(history_turnover > 0)  # NaN without that session's row
    mk["gap_vs_history"] = ratio - 1
    mk["turnover_check"] = np.select(
        [mk["total_turnover"].isna(),
         np.array([len(c) > 1 for c in currencies], dtype=bool),
         mk["reported_currency"].isna(),
         mk["reported_currency"] != expected_currency,
         (ratio > MIXUP_RATIO) | (ratio < 1 / MIXUP_RATIO)],
        ["n/a: total_turnover is missing",
         "✕ market_cap_history states more than one currency",
         "unverified: market_cap_history states no currency",
         "✕ currency differs from LOCAL_CURRENCY",
         f"✕ more than {MIXUP_RATIO:g}x away from that session's total_turnover_local"],
        default="✓ currency matches LOCAL_CURRENCY")
    mk["currency"] = mk["reported_currency"].fillna(expected_currency)
    failed_currency = mk["turnover_check"].str.startswith("✕")
    for row in mk[failed_currency].itertuples():
        print(f"WARNING: {row.market}: {row.turnover_check} (history currency: {text_or(row.reported_currency)}, "
              f"expected {LOCAL_CURRENCY.get(row.market)}). Its USD turnover is left blank rather than converted "
              "with a currency or unit that may be wrong.")
    unverified = mk.loc[mk["turnover_check"].str.startswith("unverified"), "market"].tolist()
    if unverified:
        print(f"Turnover currency unverified for {', '.join(unverified)}: converted with LOCAL_CURRENCY, unchecked.")
    compared = mk.dropna(subset=["gap_vs_history"])
    if not compared.empty:
        print("total_turnover against the same session's total_turnover_local (a different set of names, so a gap is "
              "normal): " + ", ".join(f"{r.market} {r.gap_vs_history:+.1%}" for r in compared.itertuples()))

    # Plausibility checks: a guard against a unit change, and the denominator the summary does not name.
    # A failed check blanks that measure (NaN) and says so, rather than charting numbers that may be 100x off.
    biggest_avg = mk["avg_change_pct"].abs().max()
    units_ok = pd.isna(biggest_avg) or biggest_avg <= 0.2
    if not units_ok:
        print(f"WARNING: avg_change_pct reaches {biggest_avg:,.2f}. Read as a decimal, that is a {biggest_avg:.0%} "
              "average daily move, which is implausible: the field has probably become a percent. Panel 2 is left "
              "blank. Check the units before you use this field.")
        mk["avg_change_pct"] = np.nan
    over = mk[(mk["surge_count"] > mk["institutional_count"]) | (mk["above_ma10_count"] > mk["institutional_count"])]
    denominator_ok = over.empty
    if not denominator_ok:
        print("WARNING: surge_count or above_ma10_count exceeds institutional_count for "
              f"{', '.join(over['market'])}, so institutional_count is not their denominator. The breadth shares "
              "are left blank.")
    if units_ok and denominator_ok and not failed_currency.any():
        print("Checks passed: no turnover failed its currency or size check, avg_change_pct looks like a decimal, "
              "and no breadth count exceeds institutional_count.")
    mk["as_of_date"] = pd.to_datetime(mk["as_of_date"], errors="coerce")
    mk = market_order(mk.drop_duplicates(subset="market", keep="first"))

    mk["market_name"] = mk["market"].map(MARKET_NAMES)
    mk["fx_per_usd"] = mk["currency"].map(fx)
    # A failed currency or size check blanks that market's USD turnover (panel 4 and the FX chart skip it).
    mk["total_turnover_usd"] = (mk["total_turnover"] / mk["fx_per_usd"]).where(~mk["turnover_check"].str.startswith("✕"))
    universe = mk["institutional_count"].where(mk["institutional_count"] > 0)  # 0 names -> NaN, not a division error
    if not denominator_ok:
        universe = universe * np.nan  # the denominator is wrong, so no share is shown
    mk["surge_share"] = mk["surge_count"] / universe
    mk["above_ma10_share"] = mk["above_ma10_count"] / universe
    reference_day = (summary_built if pd.notna(summary_built) else health_built).tz_convert(None).normalize()
    mk["days_old"] = (reference_day - mk["as_of_date"]).dt.days

    gaps = mk[["as_of_date", "currency", "fx_per_usd", "total_turnover_usd", "surge_share"]].isna().sum()
    print("Missing values per column:", gaps.to_dict(), "- a market with a gap is left out of that panel only.")
    print("Surge definition(s):", ", ".join(mk["surge_definition"].dropna().astype(str).unique()) or "not given")
    complete = mk["eod_session_complete"].map(lambda v: bool(v) if pd.notna(v) else False)  # missing = not complete
    loading = mk.loc[~complete, "market_name"].tolist()
    print("Every session is fully loaded." if not loading else f"Session still loading for: {', '.join(loading)}")
    display(mk[["market_name", "as_of_date", "days_old", "eod_session_complete", "currency", "turnover_check",
                "gap_vs_history", "fx_per_usd", "total_turnover", "total_turnover_usd", "avg_change_pct",
                "surge_share", "above_ma10_share"]])

# %% [markdown]
# **Chart: four markets at a glance.** Four small panels share one row per market. Read the
# first panel before the others: it says how old each market's numbers are.

# %%
if not summary_ready:
    print("Skipped: no summary to chart.")
elif mk.empty:
    print("The summary lists none of the markets in MARKETS_SHOWN, so there is nothing to chart.")
else:
    stale_mk = mk[mk["days_old"] > 3]
    n_usd = int(mk["total_turnover_usd"].notna().sum())
    leader = mk.loc[mk["total_turnover_usd"].idxmax(), "market_name"] if n_usd else None
    leads = "leads turnover in USD" + ("" if n_usd == len(mk) else f" among the {n_usd} markets converted")
    if not stale_mk.empty:
        worst = stale_mk.loc[stale_mk["days_old"].idxmax()]
        title = f"{worst['market_name']}'s figures are {worst['days_old']:.0f} days old; {leader or 'no market'} {leads}"
    else:
        title = f"Every market is on a recent session; {leader or 'no market'} {leads}"

    # Panel 3 names what surge_count counts. The friendly words fit one known definition only; any
    # other (or a mix) is shown as the raw surge_definition rather than under a label that may be wrong.
    SURGE_WORDS = {"turnover_today_gt_turnover_ma10": "Turnover above 10-day average"}
    definitions = mk["surge_definition"].dropna().astype(str).unique().tolist()
    if len(definitions) == 1 and definitions[0] in SURGE_WORDS:
        surge_title = f"{SURGE_WORDS[definitions[0]]}<br><sup>% of institutional_count names</sup>"
        surge_hover = "%{x:.1%} of the institutional_count universe traded above their 10-day average turnover"
    else:
        raw = " / ".join(definitions) or "definition not given"
        wrapped = [line.replace("_ ", "_") for line in textwrap.wrap(raw.replace("_", "_ "), 26)]
        surge_title = "surge_count share<br><sup>" + "<br>".join(wrapped) + "</sup>"
        surge_hover = "%{x:.1%} of the institutional_count universe met surge_definition %{customdata}"
    extra_lines = surge_title.count("<br>") - 1  # a long raw definition needs more room above the panels

    panels = [
        ("days_old", "Data age<br><sup>days since the last EOD session</sup>"),
        ("avg_change_pct", "Average 1-day change<br><sup>%, every name counting equally</sup>"),
        ("surge_share", surge_title),
        ("total_turnover_usd", "Total turnover<br><sup>USD, log scale</sup>"),
    ]
    fig = make_subplots(rows=1, cols=4, shared_yaxes=True, horizontal_spacing=0.045,
                        subplot_titles=[p[1] for p in panels])
    colors = mk["market"].map(MARKET_COLORS)
    MARKET_SYMBOLS = {"us": "circle", "cn": "square", "jp": "diamond", "hk": "triangle-up"}  # second encoding for dots
    labels = {
        "days_old": ["n/a" if pd.isna(d) else f"{d:.0f} d" for d in mk["days_old"]],
        "avg_change_pct": ["n/a" if pd.isna(v) else f"{v:+.2%}" for v in mk["avg_change_pct"]],
        "surge_share": ["n/a" if pd.isna(v) else f"{v:.0%}" for v in mk["surge_share"]],
        "total_turnover_usd": [f"${compact(v)}" for v in mk["total_turnover_usd"]],
    }
    hover = {
        "days_old": "Last EOD session %{customdata}<br>%{x} days before the summary build",
        "avg_change_pct": ("Average 1-day change: %{x:+.2%} (avg_change_pct as reported)"
                           "<br>The plain mean of the day's change_pct, every name counting equally"),
        "surge_share": surge_hover,
        "total_turnover_usd": "Turnover: %{customdata} (converted at the summary FX rate)",
    }
    custom = {"days_old": mk["as_of_date"].map(day), "total_turnover_usd": [f"${compact(v)}" for v in mk["total_turnover_usd"]],
              "surge_share": mk["surge_definition"].map(lambda v: text_or(v, "(not given)"))}
    for col_i, (col, _) in enumerate(panels, start=1):
        common = dict(y=mk["market_name"], x=mk[col], text=labels[col], showlegend=False, cliponaxis=False,
                      customdata=custom.get(col), textfont=dict(color=INK_2, size=12),
                      hovertemplate="<b>%{y}</b><br>" + hover[col] + "<extra></extra>")
        if col == "total_turnover_usd":  # log scale: dots, because bar length means nothing on a log axis
            fig.add_trace(go.Scatter(mode="markers+text", textposition="top center",
                                     marker=dict(size=14, color=colors, symbol=mk["market"].map(MARKET_SYMBOLS),
                                                 line=dict(width=2, color=SURFACE)), **common),
                          row=1, col=col_i)
        else:
            fig.add_trace(go.Bar(orientation="h", width=0.5, marker=dict(color=colors), textposition="outside",
                                 **common), row=1, col=col_i)

    biggest_move = mk["avg_change_pct"].abs().max()
    span = (biggest_move if pd.notna(biggest_move) and biggest_move > 0 else 0.01) * 1.6
    oldest = mk["days_old"].max()
    usd = mk["total_turnover_usd"].dropna()
    usd = usd[usd > 0]
    fig.update_xaxes(range=[0, (max(oldest, 1) if pd.notna(oldest) else 1) * 1.35], title="days", row=1, col=1)
    fig.update_xaxes(range=[-span, span], tickformat=".1%", zeroline=True, zerolinecolor=AXIS, title="% change",
                     row=1, col=2)
    fig.update_xaxes(range=[0, 1.15], tickvals=[0, 0.5, 1], tickformat=".0%", title="% of institutional_count",
                     row=1, col=3)
    if not usd.empty:
        lo, hi = np.floor(np.log10(usd.min() / 2)), np.ceil(np.log10(usd.max() * 2))
        decades = [10 ** k for k in range(int(lo), int(hi) + 1)]  # one tick per power of ten
        fig.update_xaxes(type="log", range=[lo, hi], tickvals=decades, title="USD (log)", row=1, col=4,
                         ticktext=["$" + compact(v).replace(".0", "") for v in decades])  # $1B, $10B, ...
    fig.update_xaxes(title_font=dict(size=12, color=INK_2))
    fig.update_yaxes(categoryorder="array", categoryarray=list(mk["market_name"])[::-1], ticks="", ticksuffix="  ")
    fig.update_annotations(font=dict(size=13, color=INK_2), yshift=6)
    built = "build time not given" if pd.isna(summary_built) else f"built {summary_built:%Y-%m-%d %H:%M} UTC"
    fig.update_layout(
        title=chart_title(title, f"Summary {built}. Colour = market (turnover dots also differ in shape). "
                                 "Each panel has its own scale."),
        height=400 + 14 * extra_lines, margin=dict(l=115, r=40, t=125 + 14 * extra_lines, b=60), barcornerradius=4,
    )
    fig.show()

# %% [markdown]
# **How to read this**
#
# - **Data age first.** One day is normal: the summary is built after the session ends. A
#   larger number means a holiday, a weekend or a stale feed. Read that market's other panels
#   as of its own date, not as of today.
# - **Average 1-day change** is `avg_change_pct` as reported: the plain mean of the one-day
#   changes of the market screen's names, with every name counting equally, so it can differ from a
#   cap-weighted index. A blank panel means the units guard above failed.
# - **Turnover above its 10-day average** is a breadth measure: `surge_count` divided by
#   `institutional_count`, the share of names trading more than usual. That denominator is the
#   kit's reading, because the summary does not name it, and it is **not** the larger
#   `screen_eligible_tickers` that a record also carries (1,220 against 1,000 in this kit's sample). The
#   panel's title comes from `surge_definition`. If the summary reports a definition other than
#   `turnover_today_gt_turnover_ma10`, the panel shows that raw string instead of the friendly words.
#   If the counts cover the **whole** universe rather than a sample, there is no sampling error to
#   put a confidence interval on. The real uncertainty is about freshness and definitions.
# - **Turnover in USD** uses a log axis, because markets differ by orders of magnitude. Equal
#   gaps mean equal *ratios*.
#
# **FX context: convert before you compare.** Adding raw local amounts mixes dollars, yuan, yen
# and Hong Kong dollars. The next chart shows how wrong that gets.

# %%
if not summary_ready:
    print("Skipped: no summary turnover to convert.")
else:
    fx_view = mk.dropna(subset=["total_turnover", "total_turnover_usd"]).copy()
    if fx_view.empty or fx_view["total_turnover_usd"].sum() <= 0:
        print("No turnover with a known currency, so there is nothing to convert.")
    else:
        fx_view["raw_share"] = fx_view["total_turnover"] / fx_view["total_turnover"].sum()
        fx_view["usd_share"] = fx_view["total_turnover_usd"] / fx_view["total_turnover_usd"].sum()
        gap_row = fx_view.loc[(fx_view["raw_share"] - fx_view["usd_share"]).abs().idxmax()]
        rows_y = ["Raw local units (wrong)", "Converted to USD (right)"]

        fig = go.Figure()
        for r in fx_view.itertuples():
            values = [r.raw_share, r.usd_share]
            fig.add_trace(go.Bar(
                name=r.market_name, y=rows_y, x=values, orientation="h", width=0.55,
                marker=dict(color=MARKET_COLORS[r.market], line=dict(width=2, color=SURFACE)),
                text=[f"{r.market.upper()} {v:.0%}" if v >= 0.08 else "" for v in values],
                textposition="inside", insidetextanchor="middle",
                textfont=dict(color=ink_on(MARKET_COLORS[r.market]), size=12),
                customdata=[f"{compact(r.total_turnover)} {r.currency}", f"${compact(r.total_turnover_usd)}"],
                hovertemplate=f"<b>{r.market_name}</b><br>%{{customdata}}<br>%{{x:.1%}} of the total<extra></extra>",
            ))
        fig.update_layout(
            barmode="stack", height=320, margin=dict(l=190, r=30, t=100, b=55),
            title=chart_title(f"Convert before you compare: {gap_row['market_name']} looks like {gap_row['raw_share']:.0%} "
                              f"of turnover in raw units, but is {gap_row['usd_share']:.0%} in USD",
                              "Share of the markets' total turnover. Rates: summary fx_rates (local units per USD)."),
            xaxis=dict(range=[0, 1], tickformat=".0%", title="Share of total turnover (%)"),
            yaxis=dict(categoryorder="array", categoryarray=rows_y[::-1], title=None, ticks="", ticksuffix="  "),
            legend=dict(orientation="h", y=1.03, yanchor="bottom", x=0, traceorder="normal"),
        )
        fig.show()
        fx_view["1 USD buys"] = [f"{v:,.2f} {c}" for v, c in zip(fx_view["fx_per_usd"], fx_view["currency"])]
        display(fx_view[["market_name", "currency", "1 USD buys", "total_turnover", "total_turnover_usd",
                         "raw_share", "usd_share"]])

    retired_fx = sorted(set(fx.index) - set(LOCAL_CURRENCY.values()))
    if retired_fx:
        print(f"The FX table also carries {', '.join(retired_fx)}: currencies of retired markets. Ignore them.")

# %% [markdown]
# **How to read this**
#
# - Both bars show the same turnover numbers as shares of their total.
# - The top bar adds raw local amounts. A market with a "small" currency unit, such as the yen,
#   looks enormous there.
# - The bottom bar converts each market to USD first. Only that bar is a fair comparison.
#
# **Caveats**
#
# - The FX rates are a snapshot taken when the summary was built. They are fine for context, not
#   for accounting.
# - A stale market's numbers come from its last published session, so its turnover is from that day.
# - The summary also carries factor leaders, factor premiums, macro-cycle scores and market-cap
#   histories. Section 7.3 uses the market-cap history.

# %% [markdown]
# ## 7. Extensions (beyond the raw API)
#
# These cells go past what the endpoints return directly. They combine fields and endpoints and
# add a little statistics.
#
# ### 7.1 How big is each market, and how deep is its history?
#
# Health reports two counts per market: `tickers` (names tracked) and `closes_rows` (daily closing
# prices stored). Dividing them gives the **average number of daily closes per ticker**. Dividing
# again by the number of trading sessions in a year turns that into rough **years of history**.
# Exchanges have different holiday calendars, so we use a typical session count for each market.

# %%
SESSIONS_PER_YEAR = {"us": 252, "cn": 242, "jp": 245, "hk": 247}  # typical trading sessions a year (approximate)

depth = mh[["market", "market_name", "tickers", "closes_rows"]].copy()
depth["closes_per_ticker"] = depth["closes_rows"] / depth["tickers"].where(depth["tickers"] > 0)
depth["sessions_per_year"] = depth["market"].map(SESSIONS_PER_YEAR)
depth["years_of_history"] = depth["closes_per_ticker"] / depth["sessions_per_year"]
n_gaps = int(depth["years_of_history"].isna().sum())
print(f"{n_gaps} market(s) lack a count, so their depth is NaN and they are left off the chart." if n_gaps
      else "Every market reports both counts.")
depth.round({"closes_per_ticker": 0, "years_of_history": 1})

# %% [markdown]
# **Chart: universe size and history depth.** Two panels share one row per market, so each
# measure keeps its own scale (no second y-axis).

# %%
dp = depth.dropna(subset=["tickers", "years_of_history"])
if dp.empty:
    print("Health did not report ticker and row counts, so there is nothing to chart.")
else:
    biggest = dp.loc[dp["tickers"].idxmax()]
    deepest = dp.loc[dp["years_of_history"].idxmax()]
    shallowest = dp.loc[dp["years_of_history"].idxmin()]
    title = (f"{biggest['market_name']} tracks the most names; {deepest['market_name']} has the longest "
             f"history (about {deepest['years_of_history']:.0f} years per ticker)")
    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.1,
                        subplot_titles=["Tickers tracked<br><sup>count</sup>",
                                        "Average history per ticker<br><sup>years of daily closes</sup>"])
    bar = dict(y=dp["market_name"], orientation="h", width=0.5, marker=dict(color=dp["market"].map(MARKET_COLORS)),
               textposition="outside", cliponaxis=False, textfont=dict(color=INK_2, size=12), showlegend=False)
    fig.add_trace(go.Bar(x=dp["tickers"], text=[f"{v:,.0f}" for v in dp["tickers"]],
                         hovertemplate="<b>%{y}</b><br>%{x:,.0f} tickers tracked<extra></extra>", **bar), row=1, col=1)
    fig.add_trace(go.Bar(x=dp["years_of_history"], text=[f"{v:.1f} years" for v in dp["years_of_history"]],
                         customdata=np.stack([dp["closes_per_ticker"], dp["closes_rows"], dp["sessions_per_year"]], axis=-1),
                         hovertemplate=("<b>%{y}</b><br>About %{x:.1f} years per ticker<br>"
                                        "%{customdata[0]:,.0f} daily closes per ticker on average<br>"
                                        "(%{customdata[1]:,.0f} rows, %{customdata[2]} sessions a year)<extra></extra>"),
                         **bar), row=1, col=2)
    fig.update_xaxes(title="tickers (count)", range=[0, dp["tickers"].max() * 1.3], tickformat=",", row=1, col=1)
    fig.update_xaxes(title="years (average per ticker)", range=[0, dp["years_of_history"].max() * 1.35], row=1, col=2)
    fig.update_xaxes(title_font=dict(size=12, color=INK_2))
    fig.update_yaxes(categoryorder="array", categoryarray=list(dp["market_name"])[::-1], ticks="", ticksuffix="  ")
    fig.update_annotations(font=dict(size=13, color=INK_2), yshift=6)
    fig.update_layout(
        title=chart_title(title, f"From /api/v1/health, built {health_built:%Y-%m-%d %H:%M} UTC. Colour = market. "
                                 "History = closes_rows ÷ tickers ÷ sessions a year."),
        height=360, margin=dict(l=115, r=40, t=120, b=60), barcornerradius=4,
    )
    fig.show()
    print(f"Spread: {deepest['market_name']} averages {deepest['years_of_history']:.1f} years per ticker, "
          f"{shallowest['market_name']} {shallowest['years_of_history']:.1f} "
          f"({deepest['years_of_history'] / shallowest['years_of_history']:.1f}x as deep).")

# %% [markdown]
# **How to read this**
#
# - The left panel is the size of each market's universe. The right panel is how far back its
#   daily prices go, on average.
# - Depth matters for research: a 200-day moving average or a one-year volatility needs at least
#   that much history per name. A shallow market leaves fewer names with a full window.
#
# **Caveats**
#
# - This is an **average**. It cannot tell a market where every name has 10 years from one where
#   half have 20 and half have none. Health does not report the spread.
# - `closes_rows` may include names that have since delisted, while `tickers` counts the current
#   universe. That would make the depth look longer than it is, so treat it as a rough gauge.
# - Depth is not quality. Hong Kong's disclosure, for example, says its older prices come from a
#   proxy source.
#
# ### 7.2 Do health and summary agree on freshness?
#
# Two endpoints, one truth: each market's latest session should be the same in both.

# %%
if not summary_ready:
    print("Skipped: the summary is unavailable, so there is nothing to compare with health.")
else:
    agree = mh[["market", "market_name", "published_session_date", "status"]].merge(
        mk[["market", "as_of_date"]], on="market", how="outer")
    both = agree["published_session_date"].notna() & agree["as_of_date"].notna()
    agree["agree"] = np.select(
        [both & (agree["published_session_date"] == agree["as_of_date"]), both],
        ["✓ same session", "✕ different"], default="? missing in one endpoint")
    agree["published_session_date"] = agree["published_session_date"].map(day)
    agree["as_of_date"] = agree["as_of_date"].map(day)
    print(f"{(agree['agree'] == '✓ same session').sum()} of {len(agree)} markets agree.")
    display(agree.rename(columns={"published_session_date": "health: published session",
                                  "as_of_date": "summary: as_of_date"}))

# %% [markdown]
# If a market disagrees, one endpoint was rebuilt before the other. Wait a few minutes and re-run.
#
# ### 7.3 Market-cap index over the last sessions
#
# Each summary record carries `market_cap_history`: the total market cap of the
# covered names for recent sessions, in local currency. Shares are held constant, so it moves
# with prices. We index every market to **100 on a common start date**. That removes both the
# currency and the size of each market, so all four fit on one axis without a second y-axis.

# %%
hist = pd.DataFrame()
if not summary_ready:
    print("Skipped: no summary, so no market-cap history.")
else:
    parts = [pd.DataFrame(r["market_cap_history"]).assign(market=r["market"]) for r in summary_markets
             if isinstance(r.get("market_cap_history"), list) and r["market_cap_history"]]
    hist = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if hist.empty:
        print("No market-cap history today.")

if not hist.empty:
    hist["date"] = pd.to_datetime(hist["date"], errors="coerce")
    hist["total_market_cap_local"] = pd.to_numeric(hist["total_market_cap_local"], errors="coerce")
    n_before = len(hist)
    hist = hist.dropna(subset=["date", "total_market_cap_local"])
    hist = hist[hist["total_market_cap_local"] > 0].drop_duplicates(subset=["market", "date"])
    hist = market_order(hist.sort_values("date"))  # dates ascending inside each market
    print(f"Dropped {n_before - len(hist)} rows with a missing or non-positive value, or a duplicate (market, date).")

if not hist.empty:
    base_date = hist.groupby("market")["date"].min().max()  # first date every market has reached
    idx_parts = []
    for market, g in hist.groupby("market", sort=False):
        start = g.loc[g["date"] <= base_date, "date"].max()
        g = g[g["date"] >= start].copy()
        g["index"] = 100 * g["total_market_cap_local"] / g["total_market_cap_local"].iloc[0]
        idx_parts.append(g)
    idx = market_order(pd.concat(idx_parts, ignore_index=True))
    print(f"Common start date: {day(base_date)}")
    display(idx[[c for c in ["market", "date", "currency", "total_market_cap_local", "index", "coverage_pct"]
                 if c in idx.columns]].head())

# %% [markdown]
# **Statistics, done carefully.** For each market: the change over the window, and the realised
# volatility (how much the index moves day to day, scaled to a year).
#
# - Daily log change: $r_t = \ln(I_t / I_{t-1})$.
# - Annualised volatility: $\hat\sigma = \text{sd}(r_t) \times \sqrt{N}$, where $N$ is the market's typical
#   number of trading sessions a year (`SESSIONS_PER_YEAR` from section 7.1, 242 to 252).
# - With only $n$ daily changes the estimate is rough. If returns were normal, its standard error
#   would be about $\hat\sigma / \sqrt{2(n-1)}$. We report it next to the estimate.
# - A market whose history stops early (a holiday or a stale feed) covers a shorter window. To
#   compare like with like, the cell also measures every market's change up to the **common end
#   date**: the last date that every market has reached.

# %%
if hist.empty:
    print("Skipped: no market-cap history.")
else:
    last_dates = idx.groupby("market", sort=False)["date"].max()
    common_end = last_dates.min()          # the last date every market has reached
    same_end = last_dates.nunique() == 1
    to_common = f"change to {day(common_end)}"
    stats_rows = []
    for market, g in idx.groupby("market", sort=False):
        r = np.log(g["index"]).diff().dropna()
        n = len(r)
        vol = r.std(ddof=1) * np.sqrt(SESSIONS_PER_YEAR[market]) if n > 1 else np.nan
        upto = g.loc[g["date"] <= common_end, "index"]
        stats_rows.append({
            "market": MARKET_NAMES[market], "sessions": len(g), "from": day(g["date"].iloc[0]), "to": day(g["date"].iloc[-1]),
            "change": g["index"].iloc[-1] / 100 - 1,
            to_common: upto.iloc[-1] / 100 - 1 if len(upto) else np.nan,
            "ann. volatility": vol, "± std. error": vol / np.sqrt(2 * (n - 1)) if n > 1 else np.nan,
        })
    idx_stats = pd.DataFrame(stats_rows)
    if same_end:
        idx_stats = idx_stats.drop(columns=to_common)  # identical to "change" when every market ends together
    else:
        print(f"End dates differ ({', '.join(f'{MARKET_NAMES[m]} {day(d)}' for m, d in last_dates.items())}), "
              f"so markets are ranked by their change to {day(common_end)}.")
    display(idx_stats.style.format({"change": "{:+.1%}", to_common: "{:+.1%}", "ann. volatility": "{:.1%}",
                                    "± std. error": "{:.1%}"}, na_rep="n/a").hide(axis="index"))

# %% [markdown]
# **Chart: the indexed market caps.** One line per market, labelled at its end.

# %%
if hist.empty:
    print("Skipped: no market-cap history to chart.")
else:
    rank_col = "change" if same_end else to_common  # rank over the dates every market covers
    ranked = idx_stats.dropna(subset=[rank_col])
    if ranked.empty:
        title = f"Market caps indexed to 100 on {day(base_date)}"
    else:
        best = ranked.loc[ranked[rank_col].idxmax()]
        move = best[rank_col]
        verb = "rose most" if move > 0 else "fell least" if move < 0 else "did best (flat)"
        window = f"since {day(base_date)}" if same_end else f"from {day(base_date)} to {day(common_end)}"
        title = f"{best['market']} {verb} {window} ({move:+.1%}, in local currency)"
    subtitle = ("Total market cap of covered names, indexed to 100 on the common start date. "
                "Shares held constant, so moves come from prices.")
    if not same_end:
        subtitle += f" Ranked to {day(common_end)}, the last date every market has; each line runs to its own last session."
    currency = idx["currency"] if "currency" in idx.columns else idx["market"].map(LOCAL_CURRENCY)
    fig = go.Figure()
    for market, g in idx.groupby("market", sort=False):
        fig.add_trace(go.Scatter(
            x=g["date"], y=g["index"], mode="lines", name=MARKET_NAMES[market],
            line=dict(color=MARKET_COLORS[market], width=2),
            customdata=np.stack([g["total_market_cap_local"].map(compact), currency.loc[g.index]], axis=-1),
            hovertemplate=(f"<b>{MARKET_NAMES[market]}</b><br>%{{x|%Y-%m-%d}}<br>Index %{{y:.1f}}"
                           "<br>Market cap %{customdata[0]} %{customdata[1]}<extra></extra>"),
        ))
    ends = idx.groupby("market", sort=False).tail(1).sort_values("index")
    y_lo, y_hi = idx["index"].min(), idx["index"].max()
    gap = (y_hi - y_lo) * 0.07 or 0.5
    label_y = []
    for value in ends["index"]:  # push end labels apart so they never overlap
        label_y.append(max(value, label_y[-1] + gap) if label_y else value)
    for (_, row), ly in zip(ends.iterrows(), label_y):
        fig.add_trace(go.Scatter(x=[row["date"]], y=[row["index"]], mode="markers", showlegend=False, hoverinfo="skip",
                                 marker=dict(size=9, color=MARKET_COLORS[row["market"]], line=dict(width=2, color=SURFACE))))
        fig.add_annotation(x=row["date"], y=row["index"], ax=28, axref="pixel", ay=ly, ayref="y",
                           text=f"{MARKET_NAMES[row['market']]} {row['index']:.1f}", xanchor="left", showarrow=True,
                           arrowhead=0, arrowwidth=1, arrowcolor=MUTED, standoff=5, font=dict(color=INK_2, size=12))
    fig.add_hline(y=100, line=dict(color=AXIS, width=1))
    fig.update_layout(
        title=chart_title(title, subtitle),
        xaxis=dict(title=None, range=[idx["date"].min() - pd.Timedelta(days=1), idx["date"].max() + pd.Timedelta(days=1)]),
        yaxis=dict(title="Index (start = 100)"), height=440,
        margin=dict(l=70, r=160, t=100, b=50), legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0),
        hovermode="closest",
    )
    fig.show()
    # Table twin: the index by session (last 10 sessions; NaN = that market had no session that day).
    display(idx.pivot(index="date", columns="market", values="index").rename(columns=MARKET_NAMES)
            .round(2).tail(10).rename_axis(None, axis=1))

# %% [markdown]
# **How to read this**
#
# - Every line starts at 100 on the common start date. A value of 103 means +3% since then.
# - A line that stops early belongs to a market that has not traded since (a holiday or a stale
#   feed). Health and the summary's data age explain why. The title then ranks every market only
#   up to the last date they all share, so a short window is not compared with a longer one.
# - The volatility table says how bumpy each line is. With about 30 sessions the standard error
#   is about 13% of the estimate ($1/\sqrt{2 \cdot 28}$). Treat small differences between markets as noise.
#
# **Caveats**
#
# - This is description, not a forecast. It says nothing about the next session.
# - The history covers only part of each universe (`coverage_pct`), and some prices can be up to
#   `max_price_age_days` old. Stale prices make the index look calmer than the market.
# - Daily returns have fat tails, so the true uncertainty is larger than this normal-theory
#   standard error.

# %% [markdown]
# ## 8. Which notebook teaches which endpoint
#
# The map below joins the catalogue to `KIT_MAP`. Each notebook opens in Colab. The original
# 60-second quick-start, `surgeflow-realtime-hotlist-60s`, also shows `me`, `realtime` and `hotlist`.

# %%
COLAB = "https://colab.research.google.com/github/aukaho/surgeflow-starter-kit/blob/main/notebooks/{}.ipynb"
catalogue_gets = pd.concat([
    pd.DataFrame(catalog["open_endpoints"]).query("method == 'GET'")[["path"]],
    endpoints[["path"]],
], ignore_index=True)
listed = set(catalogue_gets["path"])


def code_list(paths: list) -> str:
    return "<br>".join(f"`{p}`" for p in paths) or "-"


lines = ["| Notebook | Teaches | Uses again |", "|---|---|---|"]
for notebook in sorted({nb for nbs in KIT_MAP.values() for nb in nbs}):
    teaches = [p for p, nbs in KIT_MAP.items() if nbs[0] == notebook and p in listed]
    reuses = [p for p, nbs in KIT_MAP.items() if notebook in nbs[1:] and p in listed]
    lines.append(f"| [{notebook}]({COLAB.format(notebook)}) | {code_list(teaches)} | {code_list(reuses)} |")
display(Markdown("\n".join(lines)))

retired_listed = sorted(listed & set(RETIRED))
untaught = sorted(listed - set(KIT_MAP) - set(RETIRED))
gone = sorted(set(KIT_MAP) - listed)
print(f"{len(listed) - len(untaught) - len(retired_listed)} of {len(listed) - len(retired_listed)} "
      "current GET endpoints in the catalogue have a notebook.")
if untaught:
    print("New in the catalogue, not in the kit yet:", ", ".join(untaught))
if retired_listed:
    print("Still listed but retired (AI committee paused, HTTP 410; the kit no longer calls them):",
          ", ".join(retired_listed))
if gone:
    print("In the kit, but no longer in the catalogue:", ", ".join(gone))

# %% [markdown]
# ## Next steps
#
# - Open `01-market-boards` next. Each notebook starts with the same Connect cell.
# - Re-run this notebook whenever numbers look odd: health and your key's counters explain most surprises.
# - If section 6 was skipped, try it again later. The summary also carries parts this notebook did
#   not use: `factor_leaders`, `factor_premiums` and `macro_cycle`.
#
# Requests used by this notebook:

# %%
print(f"api_calls_used() = {api_calls_used()} requests through sf_get (plus 1 keyless health check).")

# %% [markdown]
# ---
#
# *Research and education only. Nothing here is investment advice or a recommendation to buy or
# sell any security. The endpoint name `realtime` describes a current-session board, not a
# live-tick feed. Data cadence varies by market and source: always check the freshness fields.*
