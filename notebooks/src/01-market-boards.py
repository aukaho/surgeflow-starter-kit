# %% [markdown]
# # 01 · Market boards: screen, sector, realtime and hotlist
#
# This notebook reads the four "board" endpoints of the SurgeFlow Public API v1
# for one market. First the end-of-day view: you page through the market
# **screen** to collect the largest companies, then map the day's moves with
# the **sector** snapshot. Then the current session: the **realtime** turnover
# board and the momentum **hotlist**. Along the way you clean the data the way
# an analyst would, learn the unit of every number, and draw one honest chart
# per board.
#
# **What you will learn**
#
# - How to page through a large endpoint safely: a page guard, a stop on an
#   empty page, and de-duplication on the natural key.
# - How to clean API data: coerce types, audit missing values with an explicit
#   policy, winsorise heavy tails and take `log1p` of money amounts.
# - Why two "returns" from the same API must never be mixed: the screen's
#   `change_pct` is a **fraction**, the realtime board's `intraday_return_pct`
#   is a **percent**, and they are not even measured the same way.
# - Why `realtime` is a current-session snapshot, not a tick feed, and what a
#   closed market or an empty board looks like.
# - How to read four chart forms: a treemap, a bubble chart, a ranked dot plot
#   (drawn when the hotlist has two or more names) and small multiples, and
#   when a sentence and a table say more than a chart.
#
# **Endpoints used**
#
# | Method | Path | What it returns |
# |---|---|---|
# | GET | `/api/v1/markets/{market}/screen` | The market screen, paged (at most 100 rows a page): one row per stock with about 20 fields (price, daily change, turnover, market cap, trend, valuation and fundamentals) |
# | GET | `/api/v1/markets/{market}/sector` | The sector snapshot: every stock's one-day change with its sector and industry, plus two market-cap-weighted averages (`sector_mean_1d`, `industry_mean_1d`, as documented in `/api/v1/catalog`), in one unpaged response |
# | GET | `/api/v1/markets/{market}/realtime` | The current-session turnover board: the most-traded names among those its source feed covers (50 by default; pass `limit=1..100`), with turnover so far, a projection for the full session and the pace versus yesterday |
# | GET | `/api/v1/markets/{market}/hotlist` | The momentum hotlist: a short list of the session's momentum names (it can come back empty; section 6 shows how to report that); its `_usd` amounts are in US dollars |
#
# Markets: `us`, `cn`, `jp`, `hk`. The notebook makes about 9 requests (the
# free plan allows 2,000 a day and 180 a minute) and runs in under a minute.

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
# (`sf_get`, `to_frame`, `show_freshness`, ...) and the chart theme. You can run
# it without reading it.

# %% [helpers]

# %% [markdown]
# ## 2. Parameters
#
# Change `MARKET` and run the notebook again to study another market. The other
# values keep the request count small.

# %%
MARKET = "us"          # one of "us", "cn", "jp", "hk"
PAGE_SIZE = 100        # screen rows per page: 1-100 (a larger value is rejected with VALIDATION_ERROR)
MAX_PAGES = 3          # paging guard: the 300 largest companies. The whole US screen is about 33 pages
RT_LIMIT = 50          # realtime board rows: 1-100 (the API's default is 50)
WINSOR_Q = 0.01        # winsorising: clip below the 1st and above the 99th percentile
THIN_RATIO = 0.03      # "thin line": trades less than 3% of the typical turnover for its market cap (see step 6)
PACE_CAP = 4.0         # bubble charts: bubbles stop growing at 4x yesterday's pace (hover shows the true value)

# Facts about each market that the API does not send with the boards.
CURRENCY = {"us": "USD", "cn": "CNY", "jp": "JPY", "hk": "HKD"}
SYMBOL = {"USD": "$", "CNY": "CN¥", "JPY": "¥", "HKD": "HK$"}
SESSION_SECONDS = {"us": 23_400, "cn": 14_400, "jp": 19_800, "hk": 19_800}  # regular trading seconds per day

assert MARKET in MARKETS, f"MARKET must be one of {MARKETS}"
assert 1 <= PAGE_SIZE <= 100, "PAGE_SIZE must be between 1 and 100: the API rejects larger pages."
assert 1 <= RT_LIMIT <= 100, "RT_LIMIT must be between 1 and 100."
CCY = CURRENCY[MARKET]
WHERE = ("the " if MARKET == "us" else "") + MARKET_NAMES[MARKET]   # for titles: "in the United States"
print(f"Studying {MARKET_NAMES[MARKET]} ({MARKET}); local currency {CCY}.")

# %% [markdown]
# A few small utilities keep the later cells short. They are plain code, so read
# them once:
#
# - `pick` keeps exactly the documented columns. If a documented column is
#   missing, it raises a `KeyError`: that means the API contract changed, and
#   you want to know. A board can come back empty, so it returns an empty
#   table with the same columns instead of crashing.
# - `money` turns `19543787185` into `$19.54B`, and `log_ticks` labels a log
#   axis with round amounts ($1B, $2B, $5B, ...).
# - `local_time` shows a timestamp on the exchange's own clock, and
#   `explain_board` turns a board's status fields into one plain sentence.
# - `scroll_table` shows a long table in a scrollable box, so the full data
#   behind a chart stays one scroll away.
#
# The cell also checks your plotly version: the chart subtitles need plotly
# 5.23 or newer. Colab already has it; on an older local install the cell tells
# you what to run.

# %%
import re

import plotly
from IPython.display import HTML
from plotly.subplots import make_subplots
from scipy import stats

PLOTLY_VERSION = tuple(int(part) for part in re.findall(r"\d+", plotly.__version__)[:2])
if PLOTLY_VERSION < (5, 23):
    raise ImportError(f"This notebook needs plotly 5.23 or newer for chart subtitles; you have {plotly.__version__}. "
                      "Run  %pip install -U 'plotly>=5.24'  in a cell, then restart the kernel.")


def pick(raw: pd.DataFrame, columns: list) -> pd.DataFrame:
    """Keep the documented columns. An empty board gives an empty table; a missing column raises KeyError."""
    if raw.empty:
        return pd.DataFrame(columns=columns)
    return raw[columns].copy()


def money(value, ccy: str = "USD", digits: int = 2) -> str:
    """19543787185 -> '$19.54B'. Readable labels for big money amounts."""
    if pd.isna(value):
        return "n/a"
    sign, value = ("-" if value < 0 else ""), abs(float(value))
    for size, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= size:
            return f"{sign}{SYMBOL[ccy]}{value / size:,.{digits}f}{unit}"
    return f"{sign}{SYMBOL[ccy]}{value:,.0f}"


def log_ticks(values, ccy: str = "USD") -> dict:
    """Round tick values (1-2-5 per power of ten) across the data, labelled as money."""
    values = pd.Series(values).dropna()
    values = values[values > 0]
    if values.empty:
        return {}
    lo, hi = np.log10(values.min()), np.log10(values.max())
    steps = ((1, 1.5, 2, 3, 5, 7) if hi - lo <= 1 else (1, 2, 5) if hi - lo <= 2.5
             else (1, 3) if hi - lo <= 4 else (1,))
    ticks = [s * 10.0 ** e for e in range(int(np.floor(lo)), int(np.ceil(hi)) + 1) for s in steps]
    ticks = [t for t in ticks if 10 ** (lo - 0.15) <= t <= 10 ** (hi + 0.15)]

    def label(t):   # one decimal only where a tick needs it ($1.5B), none otherwise ($2B, $15B)
        unit = next((size for size in (1e12, 1e9, 1e6, 1e3) if t >= size), 1)
        return money(t, ccy, digits=0 if float(t / unit).is_integer() else 1)

    return dict(tickvals=ticks, ticktext=[label(t) for t in ticks])


def local_time(stamp) -> str:
    """'2026-10-06T16:00:01-04:00' -> '2026-10-06 16:00 UTC-04:00' (the exchange's local clock)."""
    return pd.Timestamp(stamp).strftime("%Y-%m-%d %H:%M %Z") if stamp else "an unknown time"


def market_closed(meta: dict) -> bool:
    """True when a board's status fields say the market is closed (not merely that the data is stale)."""
    return meta["market_status"] == "CLOSED" or meta["stale_reason"] == "market_closed"


def scroll_table(styler, height: int = 340) -> None:
    """Display a (styled) table in a scrollable box: every row stays available without a page-long output."""
    display(HTML(f'<div style="max-height: {height}px; overflow: auto;">{styler.to_html()}</div>'))


def explain_board(meta: dict, what: str) -> None:
    """One plain sentence about a realtime-style board's status and age."""
    status, quality, reason = meta["market_status"], meta["data_quality"], meta["stale_reason"]
    when = local_time(meta["as_of_local"])
    age = ""
    if meta["as_of_utc"]:
        minutes = (pd.Timestamp.now(tz="UTC") - pd.to_datetime(meta["as_of_utc"], utc=True)).total_seconds() / 60
        if minutes >= 0:
            age = f" ({minutes:,.0f} min ago)" if minutes < 120 else f" ({minutes / 60:,.1f} h ago)"
    if quality == "ok":
        text = f"{what} is current (market status {status}). Snapshot taken {when}{age}."
    elif quality == "stale" and market_closed(meta):
        text = (f"{what} is stale because the market is closed ({reason}; market status {status}). You are "
                f"looking at the last session's board, taken {when}{age}.")
    elif quality == "stale":
        text = (f"{what} is stale for another reason ({reason}; market status {status}). The snapshot was "
                f"taken {when}{age} and may lag the live session.")
    elif quality == "empty" and market_closed(meta):
        text = (f"{what} is empty ({reason}; market status {status}). That is expected while the market is "
                "closed: outside a session the board has no rows.")
    elif quality == "empty":
        text = (f"{what} is empty right now (data_quality: {quality}, stale_reason: {reason}; market status "
                f"{status}). Snapshot taken {when}{age}.")
    else:
        text = f"{what} reports data_quality = {quality!r} (market status {status}). Treat the numbers with care."
    display(Markdown(f"> {text}"))

# %% [markdown]
# ## 3. Screen: the market's largest companies, page by page
#
# **What it is for.** The screen is the market's master table: one row per stock
# in SurgeFlow's universe, with about 20 fields (price, daily change, turnover,
# market cap, trend, valuation and fundamentals). Use it whenever you need
# "many stocks, many columns".
#
# **Paging.** The US screen has about 3,300 rows, far too many for one
# response, so the API splits them into pages. Every page tells you where you
# are:
#
# - `count` is the total number of rows in the screen (not the rows on this page);
# - `page` and `page_size` echo your request (at most 100 rows a page; asking
#   for more is rejected with `VALIDATION_ERROR`);
# - `total_pages` is `ceil(count / page_size)`;
# - a page past the end comes back with `rows: []`.
#
# Fetching all 33 US pages would spend 33 requests for a few columns. Instead
# we ask for the rows **sorted by market cap, largest first**
# (`sort="market_cap_usd"`), so a short loop collects the companies that make
# up most of the market's value. The loop stops at the first of three events:
# the last page, an empty page, or the guard `MAX_PAGES`.
#
# The screen keeps its rows at the top level of the response
# (`payload["rows"]`), not under `data` like the other boards.

# %%
screen_rows, page_log, first_page = [], [], None
stop_reason = f"the MAX_PAGES guard ({MAX_PAGES} pages)"

for page in range(1, MAX_PAGES + 1):
    payload = sf_get(f"/api/v1/markets/{MARKET}/screen", page=page, page_size=PAGE_SIZE, sort="market_cap_usd")
    if page == 1:
        first_page = payload
        # On the screen, data_quality is a dictionary of coverage statistics: we show it as a table below.
        show_freshness({k: v for k, v in payload.items() if k != "data_quality"}, "Screen:")
    batch = records(payload, "screen")
    page_log.append({"page": payload["page"], "rows": len(batch), "count": payload["count"],
                     "total_pages": payload["total_pages"], "as_of_date": payload["as_of_date"],
                     "generated_at": payload["generated_at"]})
    screen_rows.extend(batch)
    if not batch:
        stop_reason = "an empty page (past the last page)"
        break
    if page >= payload["total_pages"]:
        stop_reason = "the last page"
        break

page_log = pd.DataFrame(page_log)
page_log["generated_at"] = pd.to_datetime(page_log["generated_at"], utc=True)   # parse timestamps as UTC
display(page_log)
total = int(first_page["count"])
print(f"Stopped at {stop_reason}. Fetched {len(screen_rows):,} rows of {total:,} "
      f"({len(screen_rows) / max(total, 1):.0%} of the names in the screen).")
if page_log["as_of_date"].nunique() > 1:
    print("Warning: as_of_date changed while paging, so the pages describe different sessions. Re-run the loop.")
else:
    print(f"Every page describes the session of {first_page['as_of_date']}.")

# %% [markdown]
# Look at `generated_at`: each page is cached on its own, so pages can be built
# minutes apart. That is fine. What must match is `as_of_date`, the trading
# session the numbers describe, and the cell above checks it.
#
# The screen also reports how complete its inputs are. On this endpoint
# `data_quality` is a dictionary of coverage statistics, and they do not all
# measure the same thing, so read the `unit` column and the names:
#
# - `basis_population` is a **count** of names: the population the
#   percentages are measured over. It can differ from the screen's `count`.
# - The `*_populated_pct`, `*_governed_pct` and `*_aligned_pct` measures (and
#   `per_share_currency_pct`) are the share of that population with a usable
#   value for each input. For example, a low
#   `dividend_yield_currency_aligned_pct` means many empty `dividend_yield`
#   values. Keep them in mind for the missing-value audit below.
# - `validated_market_cap_pct` is the one that says market caps are present.
# - `market_cap_information_pit_pct` measures something else: whether the share
#   count behind each market cap is strictly point-in-time (dated no later than
#   the session it is used for), as the API's `basis_coverage_note` explains.
#   A low value is fine for this one-day snapshot of the market and does not
#   mean the market caps are empty.

# %%
dq = first_page["data_quality"]
display(Markdown(f"**Coverage:** {dq.get('coverage', 'n/a')}. {dq.get('basis_coverage_note') or ''}"
                 + (f" **Limitation:** {dq['limitation']}" if dq.get("limitation") else "")))
caps_ok, pit = dq.get("validated_market_cap_pct"), dq.get("market_cap_information_pit_pct")
if caps_ok is not None and pit is not None and pit < caps_ok:
    display(Markdown(f"> Market caps: {caps_ok:g}% of the names have a validated market cap, so the caps are there. "
                     f"Only {pit:g}% of them rest on a strictly point-in-time share count. That clock matters when "
                     "you test a rule on past dates (it guards against look-ahead); for today's sort, treemap and "
                     "sector weights, the validated caps are what count."))
pd.DataFrame([(k, v, "names" if k == "basis_population" else "%" if k.endswith("_pct") else "")
              for k, v in dq.items() if isinstance(v, (int, float)) and not isinstance(v, bool)],
             columns=["measure", "value", "unit"]).set_index("measure").style.format({"value": "{:,g}"})

# %% [markdown]
# **Raw preview.** This is the data exactly as it arrived, before any cleaning.

# %%
screen_raw = pd.DataFrame(screen_rows)
print(f"{screen_raw.shape[0]:,} rows x {screen_raw.shape[1]} columns")
if screen_raw.empty:
    display(Markdown("> The screen returned no rows. That can happen briefly while a new day's data is being "
                     "built; the cells below still run and say so. Try again later."))
screen_raw.head() if not screen_raw.empty else None

# %% [markdown]
# ### The fields and their units
#
# Units are the most common source of mistakes with financial data. Read this
# table once; every later cell relies on it.
#
# | Field | Meaning | Unit |
# |---|---|---|
# | `price` | last price | local currency |
# | `change_pct` | one-day change: the session's close versus the previous close | **fraction**: 0.0142 = +1.42% |
# | `turnover`, `previous_day_turnover` | money traded in the session, and in the session before | local currency |
# | `turnover_vs_10d` | turnover relative to its 10-day average | ratio: 1.0 = a normal day |
# | `market_cap_usd` | market value of the company | US dollars |
# | `ma10_excess`, `ma50_excess`, `ma200_excess` | price above (+) or below (−) its 10-, 50- and 200-day moving average | fraction: 0.05 = 5% above |
# | `ep`, `bp`, `sp` | earnings, book value and sales per unit of price (the inverses of P/E, P/B and P/S) | fraction |
# | `profit_margin`, `revenue_growth`, `dividend_yield` | profitability, growth and payout | fraction |
# | `ratio_quality` | SurgeFlow's grade of the valuation ratios: `good`, `acceptable`, `suspect`, `unusable` | label |
# | `institutional_default` | in SurgeFlow's default institutional universe | true / false |
#
# ### Cleaning the screen
#
# Real API data needs a few careful steps before you analyse it. We do each one
# in the open and count what it changed.
#
# 1. **Keep the documented columns.** `pick` raises if one is missing.
# 2. **Keep tickers as text, and treat empty text as missing.** Tickers are
#    labels, not numbers: Hong Kong's `"00700"` would lose its zeros as an
#    integer, and some Japanese codes (`"285A"`) contain letters. We use
#    pandas' text type, `astype("string")`, because it keeps a missing value
#    missing (`<NA>`); plain `astype(str)` would turn it into the text
#    `"None"`, which looks like a real ticker. An empty string (`""`) in a name
#    or a sector is a missing value in disguise, so we turn it into a real
#    missing value that the audit below can count.
# 3. **De-duplicate on `ticker`.** `ticker` is the natural key: one row per
#    stock. If the data refreshes while you page, a stock can move from page 2
#    to page 3 and arrive twice. A row without a ticker cannot be identified or
#    joined to anything, so we count such rows and drop them first (otherwise
#    de-duplication would fold them all into one row).
# 4. **Coerce to numbers.** `pd.to_numeric(errors="coerce")` turns anything that
#    is not a number into `NaN` ("not a number", pandas' marker for a missing
#    value). We count how many values that created.

# %%
ID_COLS = ["ticker", "company_name", "sector", "industry"]
NUM_COLS = ["price", "change_pct", "turnover", "previous_day_turnover", "turnover_vs_10d", "market_cap_usd",
            "ma10_excess", "ma50_excess", "ma200_excess", "ep", "bp", "sp",
            "profit_margin", "revenue_growth", "dividend_yield"]
FLAG_COLS = ["ratio_quality", "institutional_default"]

screen = pick(screen_raw, ID_COLS + NUM_COLS + FLAG_COLS)  # step 1
for col in ID_COLS:                                        # step 2: text that keeps <NA>; "" -> <NA>
    screen[col] = screen[col].astype("string").str.strip().replace("", pd.NA)

n_before, no_ticker = len(screen), screen["ticker"].isna()  # step 3
screen = screen[~no_ticker].drop_duplicates(subset="ticker", keep="first").reset_index(drop=True)
print(f"De-duplication: {n_before:,} rows -> {len(screen):,} ({int(no_ticker.sum())} without a ticker dropped, "
      f"{n_before - int(no_ticker.sum()) - len(screen)} duplicates removed).")

missing_before = screen[NUM_COLS].isna().sum()             # step 4
for col in NUM_COLS:
    screen[col] = pd.to_numeric(screen[col], errors="coerce")
made_by_coercion = screen[NUM_COLS].isna().sum() - missing_before
print(f"Coercion: {int(made_by_coercion.sum())} values were not numbers and became NaN.")
print("ratio_quality:", screen["ratio_quality"].value_counts(dropna=False).to_dict())

# %% [markdown]
# 5. **Audit missing values, then set a policy.** Some gaps are normal. A
#    young company has no 200-day average yet, a loss-maker or a bank may have
#    no meaningful margin, and a stock that pays nothing, or whose dividend
#    currency cannot be checked, has no dividend yield. But the identity of a
#    row (ticker, name, sector), its price and its market cap (the sort key)
#    should never be empty. A gap there is unexpected and worth investigating.
#
# Our policy is explicit: **keep NaN in the table, never fill it with 0, and let
# each analysis drop only the rows it needs (and say how many).** A column that
# is empty for every row is simply not provided for this market (for example
# `previous_day_turnover` on the China screen), so we note it and leave it alone.

# %%
REQUIRED = {"ticker", "company_name", "sector", "price", "market_cap_usd"}

audit = pd.DataFrame({
    "dtype": screen.dtypes.astype(str),
    "missing": screen.isna().sum(),
    "made_by_coercion": made_by_coercion.reindex(screen.columns).fillna(0).astype(int),
})
audit["missing_pct"] = audit["missing"] / max(len(screen), 1)
audit["required"] = audit.index.isin(sorted(REQUIRED))
audit["policy"] = np.select(
    [audit["missing"].eq(0), audit["required"], audit["missing"].eq(len(screen))],
    ["complete", "UNEXPECTED: investigate", "empty in this market: do not use"],
    default="keep NaN; drop per analysis",
)
gaps = audit[audit["missing"] > 0].sort_values("missing", ascending=False)
n_unexpected = int((audit["policy"] == "UNEXPECTED: investigate").sum())
print(f"{(audit['missing'] == 0).sum()} of {len(audit)} columns are complete; "
      f"{len(gaps)} have gaps; unexpected gaps: {n_unexpected}.")
display(gaps.style.format({"missing_pct": "{:.1%}"}))

if n_unexpected:   # show the rows behind an unexpected gap, so you can look them up
    odd = screen[screen[sorted(REQUIRED)].isna().any(axis=1)]
    display(Markdown(f"**{len(odd)} row(s) have a gap in a required column.** Look the ticker up on the "
                     "exchange's website. A blank name or sector usually means a listing SurgeFlow has not "
                     "classified yet; a blank price or market cap means the row cannot be sized. The rows "
                     "stay in the table; do not rely on their missing labels."))
    display(odd[ID_COLS + ["price", "market_cap_usd"]].style.format(
        {"price": "{:,.2f}", "market_cap_usd": lambda v: money(v)}, na_rep="(missing)").hide(axis="index"))

# %% [markdown]
# 6. **Flag rows that need care.** A missing value is easy to spot; a
#    misleading one is not. We check two things and **flag** the rows (we do not
#    delete them):
#
#    - **Thin lines.** Some rows are secondary lines of a company that is
#      already listed: a preferred share, a listed note, a second share class,
#      or a Hong Kong RMB counter (tickers starting with 8, names ending in
#      `-R`). They can report the **whole company's** market cap while trading
#      almost nothing. Summing their market cap would count the company twice.
#      We compare each row's turnover with its market cap: a row that trades
#      less than `THIN_RATIO` (3%) of the market's typical turnover per unit of
#      market cap, i.e. more than thirty times less than usual for its size, is
#      flagged `thin_line`. (Turnover is in local currency and market cap in
#      USD, but within one market the exchange rate cancels out of this
#      comparison.)
#    - **Possible splits.** A stock almost never trades more than 50% away from
#      its own 10-day average. When the data says it does, the usual cause is a
#      stock split that reached the price but not yet the history, or a data
#      error. Everything built on that price is then suspect: the ratios
#      (`ep`, `bp`, `sp`, `dividend_yield`) and the **market cap** too, since a
#      post-split price times a pre-split share count understates the company.
#      So its place in the market-cap sort and its turnover-per-cap ratio
#      (`turnover_vs_typical`) are suspect as well.
#
#    Policy: flagged rows stay in the table. Both kinds are left out of this
#    notebook's own market-cap-weighted estimates later on (the movers list and
#    the treemap), and each of those cells says how many it left out. The one
#    exception is the check of the API's `sector_mean_1d` in section 4: it tries
#    to reproduce the API's own number, the API averages these rows too, so the
#    check keeps them.

# %%
turnover_per_cap = screen["turnover"] / screen["market_cap_usd"]
screen["thin_line"] = turnover_per_cap < THIN_RATIO * turnover_per_cap.median()
screen["suspect_split"] = screen["ma10_excess"].abs() > 0.5
screen["turnover_vs_typical"] = turnover_per_cap / turnover_per_cap.median()
flagged = screen[screen["thin_line"] | screen["suspect_split"]].copy()
print(f"Thin lines: {int(screen['thin_line'].sum())}. Possible splits or data errors: "
      f"{int(screen['suspect_split'].sum())}.")
if flagged.empty:
    print("Nothing to flag.")
else:
    flagged["flag"] = [" + ".join(name for name, on in (("thin line", thin), ("possible split", split)) if on)
                       for thin, split in zip(flagged["thin_line"], flagged["suspect_split"])]
    display(flagged[["ticker", "company_name", "flag", "market_cap_usd", "turnover", "turnover_vs_typical",
                     "price", "ma10_excess"]]
            .style.format({"market_cap_usd": lambda v: money(v), "turnover": lambda v: money(v, CCY),
                           "turnover_vs_typical": "{:.3f}×", "price": "{:,.2f}", "ma10_excess": "{:+.1%}"},
                          na_rep="n/a").hide(axis="index"))

# %% [markdown]
# 7. **Winsorise heavy tails.** A few stocks always have extreme values: a
#    turnover three times its usual level, revenue that quadrupled. A handful of
#    such points can dominate a mean, a regression or a colour scale.
#    Winsorising clips every value below the 1st percentile up to it, and every
#    value above the 99th percentile down to it. The stock stays in the data;
#    only its extreme value is tamed. We keep the raw column and add a `_w`
#    version, so you can always report the true number.
#
# The table shows the clip points, how many values were clipped, and the
# skewness before and after. Skewness measures lopsidedness: 0 is symmetric,
# and large positive values mean a long right tail.

# %%
WINSOR_COLS = ["change_pct", "turnover_vs_10d", "ma50_excess", "revenue_growth"]

winsor_report = []
for col in WINSOR_COLS:
    low, high = screen[col].quantile([WINSOR_Q, 1 - WINSOR_Q])
    screen[f"{col}_w"] = screen[col].clip(low, high)
    winsor_report.append({
        "column": col, "non_missing": int(screen[col].notna().sum()), "clip_low": low, "clip_high": high,
        "n_clipped_low": int((screen[col] < low).sum()), "n_clipped_high": int((screen[col] > high).sum()),
        "max_raw": screen[col].max(), "skew_raw": screen[col].skew(), "skew_winsorised": screen[f"{col}_w"].skew(),
    })
winsor_report = pd.DataFrame(winsor_report).set_index("column")
winsor_report.style.format("{:.3f}").format("{:d}", subset=["non_missing", "n_clipped_low", "n_clipped_high"])

# %% [markdown]
# Compare the two skew columns. Winsorising tames a few wild points, but it
# cannot fix a column whose whole shape leans right. Clipping both tails can
# also **raise** the skew: when the left tail held the more extreme values,
# cutting it back leaves the right side more lopsided by comparison. So read
# the numbers rather than assume. Money amounts lean right as a whole, and they
# call for a logarithm.
#
# 8. **Take `log1p` of money amounts.** Turnover and market cap span several
#    orders of magnitude: even among the largest companies, one can trade a
#    hundred times more than another. `np.log1p(x)` is `log(1 + x)`. It turns
#    multiplication into addition, so a 10x gap becomes a constant step, and
#    unlike `log` it gives 0 (not minus infinity) for a stock with zero
#    turnover.

# %%
LOG_COLS = ["turnover", "market_cap_usd"]
for col in LOG_COLS:
    screen[f"log1p_{col}"] = np.log1p(screen[col].where(screen[col] >= 0))   # a negative amount would be an error

pd.DataFrame({
    "unit": [CCY, "USD"],
    "skew_raw": [screen[c].skew() for c in LOG_COLS],
    "skew_log1p": [screen[f"log1p_{c}"].skew() for c in LOG_COLS],
}, index=LOG_COLS).round(2)

# %% [markdown]
# ### Chart: why turnover needs a log scale
#
# The same turnover numbers, twice: raw on the left, after `log1p` on the right.

# %%
tv = screen["turnover"].dropna()
tv = tv[tv >= 0]
if tv.empty:
    display(Markdown("> No screen turnover came back, so there is nothing to chart."))
else:
    log_tv = np.log1p(tv)
    top10_share = tv.nlargest(10).sum() / tv.sum()
    scale, unit = (1e9, "B") if tv.max() >= 1e9 else (1e6, "M")
    raw_counts, raw_edges = np.histogram(tv, bins=40)        # 40 equal-width bins of money
    log_counts, log_edges = np.histogram(log_tv, bins=40)    # 40 equal-width bins of log1p(money)
    first_two = raw_counts[:2].sum() / len(tv)

    def money_bins(edges):
        """Hover text: each bin as a range of money, whatever scale the bins were cut on."""
        return [f"{money(lo, CCY)} to {money(hi, CCY)}" for lo, hi in zip(edges[:-1], edges[1:])]

    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.09, subplot_titles=(
        f"Raw turnover: skew {tv.skew():.1f}", f"After log1p: skew {log_tv.skew():.1f}"))
    fig.add_trace(go.Bar(
        x=(raw_edges[:-1] + raw_edges[1:]) / 2 / scale, y=raw_counts, width=np.diff(raw_edges) / scale,
        customdata=money_bins(raw_edges), marker_color=MARKET_COLORS[MARKET],
        hovertemplate="%{customdata}<br>%{y} stocks<extra></extra>"), row=1, col=1)
    fig.add_trace(go.Bar(
        x=(log_edges[:-1] + log_edges[1:]) / 2, y=log_counts, width=np.diff(log_edges),
        customdata=money_bins(np.expm1(log_edges)), marker_color=MARKET_COLORS[MARKET],
        hovertemplate="%{customdata}<br>%{y} stocks<extra></extra>"), row=1, col=2)

    ticks = [10.0 ** k for k in range(3, 15) if log_tv.min() - 1 <= np.log1p(10.0 ** k) <= log_tv.max() + 1]
    fig.update_xaxes(title_text=f"Turnover ({CCY}, {'billions' if unit == 'B' else 'millions'})",
                     tickprefix=SYMBOL[CCY], ticksuffix=unit, row=1, col=1)
    fig.update_xaxes(title_text=f"Turnover ({CCY}, log1p scale)", tickvals=np.log1p(ticks),
                     ticktext=[money(t, CCY, digits=0) for t in ticks], row=1, col=2)
    fig.update_yaxes(title_text="Number of stocks")    # each panel keeps its own count scale
    fig.update_layout(
        title=dict(text=f"{first_two:.0%} of the {len(tv):,} largest companies sit in the first 2 of 40 raw "
                        "bars; log1p spreads them out",
                   subtitle=dict(text=f"{MARKET_NAMES[MARKET]} screen, session {first_page['as_of_date']}, sorted "
                                      f"by market cap · 10 stocks carry {top10_share:.0%} of this turnover")),
        showlegend=False, height=430, margin=dict(t=110))
    fig.show()

    quantiles = [0, 0.25, 0.5, 0.75, 0.9, 0.99, 1]
    twin = pd.DataFrame({"turnover": tv.quantile(quantiles).values,
                         "log1p_turnover": log_tv.quantile(quantiles).values},
                        index=pd.Index([f"p{int(q * 100)}" for q in quantiles], name="quantile"))
    twin["readable"] = twin["turnover"].map(lambda v: money(v, CCY))
    display(twin.style.format({"turnover": "{:,.0f}", "log1p_turnover": "{:.2f}"}))

# %% [markdown]
# **How to read this.** On the left, most stocks sit in the first few bars and
# a few giants stretch the axis far to the right. You cannot see how the
# typical stock behaves. On the right, each step along the axis is ten times
# more money, and the same stocks form a readable hump. That is why this kit
# always puts turnover and market cap on a log axis. The log view also reveals
# what the raw view hides: any bars far to the left of the hump are the thin
# lines flagged in step 6. Hover over a bar in either panel to see its range in
# money. Each panel has its own count scale. The table below the chart lists
# the same distribution as numbers.
#
# **Caveats.**
#
# - The chart covers only the pages you fetched: the largest companies by
#   market cap. Smaller, quieter names are missing. Raise `MAX_PAGES` to see
#   more of the market (each page costs one request).
# - `turnover` is in **local currency** while `market_cap_usd` is in US
#   dollars. Convert turnover before you compare markets.
# - `change_pct` and the other ratios are **fractions** (0.05 = +5%).
# - The winsorised (`_w`) columns are what you would feed to a colour scale or
#   a model. This notebook's charts tame extremes in other ways (log axes, a
#   capped bubble size, a symmetric colour range) and its tables quote the raw
#   values, so the `_w` columns are not used again here. Quote the raw value
#   when you report a number.

# %% [markdown]
# ## 4. Sector: where the day's moves happened
#
# **What it is for.** The sector snapshot lists **every** stock in the screen's
# universe, in one unpaged response (about 3,300 US rows, roughly 1 MB), with
# its one-day `change_pct` (the same fraction as on the screen), its sector and
# industry, and two market-cap-weighted averages that SurgeFlow computes for
# you, `sector_mean_1d` and `industry_mean_1d`, as documented in
# `/api/v1/catalog`. It is called without parameters. A whale overlay
# (`whale_trend`, `whale_fund_count`, `whale_confidence`) is filled only for
# names that big funds report holding.
#
# The snapshot carries no market cap, so we join the screen's `market_cap_usd`
# on `ticker` to size the treemap. That covers the largest companies only.

# %%
sec_payload = sf_get(f"/api/v1/markets/{MARKET}/sector")
show_freshness(sec_payload, "Sector snapshot:")
sec_as_of = dig(sec_payload, "data", "as_of_date")
if sec_as_of != first_page["as_of_date"]:
    print(f"Note: sector as_of_date {sec_as_of} differs from the screen's {first_page['as_of_date']}.")

# %% [markdown]
# **Raw preview.**

# %%
sec_raw = to_frame(sec_payload, "sector")
if sec_raw.empty:
    display(Markdown("> The sector snapshot came back empty. Try again after the next end-of-day update."))
sec_raw.head() if not sec_raw.empty else None

# %% [markdown]
# ### Cleaning the sector snapshot
#
# - Keep the documented columns, coerce the numbers and de-duplicate on `ticker`.
# - **NaN policy for the hierarchy.** A treemap needs a label at every level,
#   so a missing `industry` becomes the explicit label `"(no industry)"`. A
#   missing `change_pct` (a suspended stock, for example) stays NaN and is left
#   out of every average. We count both.
# - Compute each stock's **excess move**, `change_pct - sector_mean_1d`: its
#   move relative to its own sector.
# - Join the screen's `market_cap_usd`. `validate="one_to_one"` makes pandas
#   raise if either side still has duplicate tickers. Both endpoints report
#   `change_pct`, so we also check that they agree. We also carry over the
#   screen's two flags from step 6 (thin lines and possible splits), because
#   both make a market cap unreliable as a weight in our own estimates.

# %%
SEC_COLS = ["ticker", "name", "sector", "industry", "change_pct", "sector_mean_1d",
            "industry_mean_1d", "is_microcap"]
sec = pick(sec_raw, SEC_COLS)
sec["ticker"] = sec["ticker"].astype("string").str.strip().replace("", pd.NA)   # text that keeps <NA>
for col in ["change_pct", "sector_mean_1d", "industry_mean_1d"]:
    sec[col] = pd.to_numeric(sec[col], errors="coerce")
n_before, no_ticker = len(sec), sec["ticker"].isna()
sec = sec[~no_ticker].drop_duplicates(subset="ticker", keep="first").reset_index(drop=True)
print(f"De-duplication: {n_before:,} rows -> {len(sec):,} ({int(no_ticker.sum())} without a ticker dropped).")

n_no_industry = int(sec["industry"].isna().sum())
sec["industry"] = sec["industry"].fillna("(no industry)")
print(f"Missing industry: {n_no_industry} rows labelled '(no industry)'. "
      f"Missing change_pct: {int(sec['change_pct'].isna().sum())} rows, kept as NaN.")
print(f"The sector mean repeats on every row of its sector: {bool(sec.groupby('sector')['sector_mean_1d'].nunique().le(1).all())}.")

sec["excess_1d"] = sec["change_pct"] - sec["sector_mean_1d"]
sec = sec.merge(screen[["ticker", "market_cap_usd", "change_pct"]].rename(columns={"change_pct": "screen_change_pct"}),
                on="ticker", how="left", validate="one_to_one")
sec["thin_line"] = sec["ticker"].isin(screen.loc[screen["thin_line"], "ticker"])
sec["suspect_split"] = sec["ticker"].isin(screen.loc[screen["suspect_split"], "ticker"])
sec["weight_ok"] = ~sec["thin_line"] & ~sec["suspect_split"]    # may this row's market cap act as a weight?
n_cap = int(sec["market_cap_usd"].notna().sum())
shared = sec.dropna(subset=["change_pct", "screen_change_pct"])
n_agree = int(np.isclose(shared["change_pct"], shared["screen_change_pct"], rtol=0, atol=1e-9).sum())
print(f"Market cap known for {n_cap:,} of {len(sec):,} names ({n_cap / max(len(sec), 1):.0%}): "
      f"the {len(screen):,} largest companies fetched from the screen. {int(sec['thin_line'].sum())} thin "
      f"lines and {int(sec['suspect_split'].sum())} possible splits among them are left out of the movers "
      "list and the treemap (the check of the API's sector mean keeps them, because the API averages them too).")
print(f"change_pct agrees between the screen and the sector snapshot for {n_agree} of {len(shared)} shared names.")

# %% [markdown]
# **Checking the documented weighting.** The catalog says `sector_mean_1d` is
# a **market-cap-weighted** mean over the whole sector. We cannot reproduce it
# exactly, because we hold market caps only for the companies on the first
# `MAX_PAGES` pages of the screen. But we can check whether weighting matters.
# For each sector we compute three candidates and compare each with the API's
# `sector_mean_1d`:
#
# - **equal-weighted, every name**: the plain mean of `change_pct` over every
#   stock in the sector (each stock counts once);
# - **equal-weighted, largest names**: the plain mean over the companies whose
#   market cap (and one-day change) we hold;
# - **cap-weighted, largest names**: the same companies, each weighted by its
#   market cap (big companies count for more).
#
# This check tries to reproduce the API's own number, so it uses **every** row
# that has a market cap and a change, including the thin lines and possible
# splits flagged in step 6: the API averages them too, and dropping them would
# open a gap of our own making. (The movers list and the treemap below are our
# own estimates, and they still leave the flagged rows out.)
#
# The first two candidates differ only in **which** stocks are included; the
# last two differ only in **how** they are weighted. So the fair test of
# weighting is the last pair, on the same names, compared **sector by sector**.
# We use only sectors with at least `MIN_NAMES` such companies. In each one,
# the improvement is how many bp closer to the API cap weighting lands than
# equal weighting (positive = closer). We credit cap weighting only when it is
# clearly closer on both counts:
#
# - a **median improvement of at least 5 bp**; and
# - closer in more sectors than chance would give. If weighting did not matter,
#   each sector would be a coin flip. A one-sided **sign test**
#   (`stats.binomtest`) gives the probability of at least this many "closer"
#   sectors under that coin flip, and we require p < 0.05. With 11 sectors,
#   that means closer in at least 9.
#
# `share_up` is the sector's **breadth**: the share of its stocks that rose. A
# sector can be up on average (its big names rose) while most of its stocks
# fell; breadth shows that. Gaps are in basis points (1 bp = 0.01%).

# %%
MIN_NAMES = 5          # a sector needs this many companies with a market cap and a change to enter the weighting check

sec["up"] = sec["change_pct"].gt(0).astype(float).where(sec["change_pct"].notna())
# Reproducing the API's number: keep every row it averages, flagged or not (weight_ok is for our own estimates).
covered = sec.dropna(subset=["change_pct", "market_cap_usd"])
sector_table = sec.groupby("sector").agg(
    names=("ticker", "size"), share_up=("up", "mean"), api_mean_1d=("sector_mean_1d", "first"),
    equal_weighted_all_1d=("change_pct", "mean"))
sector_table["names_with_cap"] = covered.groupby("sector")["ticker"].size().reindex(sector_table.index).fillna(0).astype(int)
sector_table["equal_weighted_largest_1d"] = covered.groupby("sector")["change_pct"].mean()
sector_table["cap_weighted_largest_1d"] = ((covered["change_pct"] * covered["market_cap_usd"]).groupby(covered["sector"]).sum()
                                           / covered.groupby("sector")["market_cap_usd"].sum())
for candidate, gap in [("equal_weighted_all_1d", "ew_all_gap_bp"), ("equal_weighted_largest_1d", "ewl_gap_bp"),
                       ("cap_weighted_largest_1d", "cw_gap_bp")]:
    sector_table[gap] = (sector_table[candidate] - sector_table["api_mean_1d"]) * 1e4
sector_table = sector_table.sort_values("api_mean_1d", ascending=False)
display(sector_table.style.format({
    "share_up": "{:.0%}", "api_mean_1d": "{:+.2%}", "equal_weighted_all_1d": "{:+.2%}",
    "equal_weighted_largest_1d": "{:+.2%}", "cap_weighted_largest_1d": "{:+.2%}",
    "ew_all_gap_bp": "{:+.0f}", "ewl_gap_bp": "{:+.0f}", "cw_gap_bp": "{:+.0f}"}, na_rep="n/a"))

testable = sector_table[sector_table["names_with_cap"] >= MIN_NAMES]
if len(testable) < 3:
    display(Markdown(f"> Only {len(testable)} sector(s) have {MIN_NAMES} or more companies with a usable market "
                     "cap: too few to check the weighting. Raise `MAX_PAGES` to hold more market caps."))
else:
    med = testable[["ew_all_gap_bp", "ewl_gap_bp", "cw_gap_bp"]].abs().median()
    # Paired, sector by sector: how many bp closer to the API each step lands (+ = closer).
    by_names_bp = testable["ew_all_gap_bp"].abs() - testable["ewl_gap_bp"].abs()   # the choice of names
    d = testable["ewl_gap_bp"].abs() - testable["cw_gap_bp"].abs()                 # weighting the same names
    n_closer = int((d > 0).sum())
    p_sign = stats.binomtest(n_closer, len(d), alternative="greater").pvalue        # better than a coin flip?
    clearly = d.median() >= 5 and p_sign < 0.05

    # What the check cannot see, in the sectors it tests: names without a cap, and rows it had to leave out.
    in_test = sec[sec["sector"].isin(testable.index)]
    n_no_cap = int(in_test["market_cap_usd"].isna().sum())
    n_left_out = int((in_test["market_cap_usd"].notna() & in_test["change_pct"].isna()).sum())
    n_flagged_in = int((~covered["weight_ok"] & covered["sector"].isin(testable.index)).sum())
    sources = (f"the {n_no_cap:,} of the {len(in_test):,} names in these sectors whose market cap we do not hold "
               f"(they sit beyond the {MAX_PAGES} screen pages fetched)"
               + (f", and the {n_left_out} row(s) with a cap that the check left out for lack of a one-day change"
                  if n_left_out else ""))

    numbers = (f"Median gap to the API mean over the {len(testable)} sectors with {MIN_NAMES}+ such companies: "
               f"equal-weighted over every name **{med['ew_all_gap_bp']:.0f} bp**, equal-weighted over the largest "
               f"names **{med['ewl_gap_bp']:.0f} bp**, cap-weighted over the same names **{med['cw_gap_bp']:.0f} bp**. "
               f"Sector by sector, cap weighting lands closer in **{n_closer} of {len(d)}** (sign test p = "
               f"{p_sign:.3f}), by a median of **{d.median():+.0f} bp**."
               + (f" The {n_flagged_in} row(s) flagged in step 6 are included, as the API includes them."
                  if n_flagged_in else ""))
    if clearly:
        verdict = ("On the same names, cap weighting lands clearly closer, which is consistent with the documented "
                   f"market-cap weighting. It cannot match exactly; the gap that remains comes from {sources}.")
    else:
        lead = ("Most of the gap closes just by looking at the largest names, not by weighting them"
                if by_names_bp.median() > 0 and by_names_bp.median() > d.median()
                else "Weighting does not clearly close the gap")
        verdict = (f"{lead}: on the same names, cap weighting is not clearly closer today. This partial sample "
                   "cannot confirm the weighting, so rely on the documented definition (cap-weighted over the "
                   f"whole sector). The gap that remains comes from {sources}.")
    display(Markdown(f"{numbers} {verdict}"))

# %% [markdown]
# The biggest moves **relative to their own sector** are often more interesting
# than the biggest raw moves, because they strip out what the whole sector did.
# We list them among the largest companies, where a move is not just noise in a
# thinly traded stock, leaving out the rows flagged in step 6:

# %%
movers = sec[sec["weight_ok"]].dropna(subset=["excess_1d", "market_cap_usd"])
print(f"Movers ranked among {len(movers):,} companies ({int((~sec['weight_ok'] & sec['market_cap_usd'].notna()).sum())} "
      "flagged rows left out).")
cols = ["ticker", "name", "sector", "market_cap_usd", "change_pct", "sector_mean_1d", "excess_1d"]
display(pd.concat([movers.nlargest(5, "excess_1d"), movers.nsmallest(5, "excess_1d")])[cols]
        .style.format({"market_cap_usd": lambda v: money(v), "change_pct": "{:+.2%}",
                       "sector_mean_1d": "{:+.2%}", "excess_1d": "{:+.2%}"})
        .hide(axis="index"))

# %% [markdown]
# ### Chart: a sector → industry treemap
#
# A treemap splits a rectangle into tiles. Here the rectangle is the largest
# companies we fetched. Each sector gets a block sized by the total market cap
# of its companies, and each block splits into its industries. Click an
# industry to see its companies.
#
# Colour shows the one-day change on a **diverging** scale: blue for up, red for
# down and grey at zero, with the same range on both sides so equal moves look
# equally strong. A sector or industry tile is coloured by the **cap-weighted**
# mean change of the companies inside it, the same companies that set its size,
# so big tiles and colours always tell one consistent story. Hover over a tile
# to see the API's own whole-sector mean as well.

# %%
tm = sec[sec["weight_ok"]].dropna(subset=["change_pct", "market_cap_usd"]).copy()
tm = tm[tm["market_cap_usd"] > 0]
n_thin, n_split = int(sec["thin_line"].sum()), int((sec["suspect_split"] & ~sec["thin_line"]).sum())
print(f"Treemap: {len(tm):,} companies. Left out: {n_thin} thin lines, {n_split} possible splits (their market "
      f"cap is suspect) and {len(sec) - len(tm) - n_thin - n_split:,} names without a market cap from the pages "
      "fetched (or without a change).")

if tm.empty:
    display(Markdown("> No stock has both a one-day change and a market cap, so there is no treemap."))
else:
    tm["cap"] = tm["market_cap_usd"].round().astype("int64")   # whole dollars, so parent sums are exact
    tm["cap_x_change"] = tm["cap"] * tm["change_pct"]
    total_cap = tm["cap"].sum()

    industries = tm.groupby(["sector", "industry"], as_index=False).agg(
        names=("ticker", "size"), cap=("cap", "sum"), cap_x_change=("cap_x_change", "sum"),
        api_mean_1d=("industry_mean_1d", "first"))
    industries["move"] = industries["cap_x_change"] / industries["cap"]
    sectors = tm.groupby("sector", as_index=False).agg(
        names=("ticker", "size"), cap=("cap", "sum"), cap_x_change=("cap_x_change", "sum"),
        api_mean_1d=("sector_mean_1d", "first"))
    sectors["move"] = sectors["cap_x_change"] / sectors["cap"]
    sectors["cap_share"] = sectors["cap"] / total_cap
    # Each sector's contribution to the overall move: its share of the value times its move.
    # The contributions add up exactly to the cap-weighted move of all the companies shown.
    sectors["contribution_pp"] = sectors["cap_share"] * sectors["move"] * 100
    market_move = tm["cap_x_change"].sum() / total_cap
    best, worst = sectors.loc[sectors["move"].idxmax()], sectors.loc[sectors["move"].idxmin()]

    # The title names the biggest contribution, and says whether it went with the day's move or against it.
    direction = 1 if market_move >= 0 else -1
    push = "lift" if direction > 0 else "pull down"
    driver = sectors.loc[sectors["contribution_pp"].abs().idxmax()]
    along = sectors[np.sign(sectors["contribution_pp"]) == direction]
    if np.sign(driver["contribution_pp"]) == direction:
        headline = (f"{driver['sector']} did most to {push} the largest companies in {WHERE}: "
                    f"{driver['contribution_pp']:+.2f} pp of a {market_move:+.2%} move")
        counter = ""
    else:
        headline = (f"{driver['sector']} was the biggest {'drag' if direction > 0 else 'support'} "
                    f"({driver['contribution_pp']:+.2f} pp) on a {market_move:+.2%} day for the largest companies "
                    f"in {WHERE}")
        lead = along.loc[along["contribution_pp"].abs().idxmax()] if not along.empty else None
        counter = (f" · {lead['sector']} did most to {push} them ({lead['contribution_pp']:+.2f} pp)"
                   if lead is not None else "")

    # A symmetric colour range: the 95th percentile of the industry moves, rounded up to 0.5%.
    R = max(0.01, float(np.ceil(industries["move"].abs().quantile(0.95) / 0.005) * 0.005))
    colour_ticks = [-R, -R / 2, 0.0, R / 2, R]

    def api_text(value, level):
        return f"API whole-{level} mean: {value:+.2%}" if pd.notna(value) else f"API whole-{level} mean: n/a"

    root = MARKET_NAMES[MARKET]
    nodes = pd.concat([
        pd.DataFrame({"id": [root], "parent": [""], "label": [root], "value": [total_cap],
                      "colour": [market_move], "full_name": [f"{root}: the {len(tm):,} largest companies"],
                      "detail": ["Cap-weighted move of every company shown"]}),
        pd.DataFrame({"id": sectors["sector"], "parent": root, "label": sectors["sector"],
                      "value": sectors["cap"], "colour": sectors["move"], "full_name": sectors["sector"],
                      "detail": [f"Sector · {n} companies · {api_text(a, 'sector')}"
                                 for n, a in zip(sectors["names"], sectors["api_mean_1d"])]}),
        pd.DataFrame({"id": industries["sector"] + " || " + industries["industry"], "parent": industries["sector"],
                      "label": industries["industry"], "value": industries["cap"], "colour": industries["move"],
                      "full_name": industries["industry"] + " (" + industries["sector"] + ")",
                      "detail": [f"Industry · {n} companies · {api_text(a, 'industry')}"
                                 for n, a in zip(industries["names"], industries["api_mean_1d"])]}),
        pd.DataFrame({"id": tm["sector"] + " || " + tm["industry"] + " || " + tm["ticker"],
                      "parent": tm["sector"] + " || " + tm["industry"], "label": tm["ticker"],
                      "value": tm["cap"], "colour": tm["change_pct"], "full_name": tm["name"],
                      "detail": tm["excess_1d"].map(lambda e: f"Company · {e * 100:+.2f} pp vs its sector's API mean")}),
    ], ignore_index=True)
    nodes["cap_text"] = nodes["value"].map(money)

    fig = go.Figure(go.Treemap(
        ids=nodes["id"], parents=nodes["parent"], labels=nodes["label"], values=nodes["value"],
        branchvalues="total", maxdepth=3, sort=True,
        marker=dict(colors=nodes["colour"], colorscale=DIVERGING, cmin=-R, cmax=R,
                    # visible seams between tiles (grey on a near-grey quiet day); the outer frame stays paper-coloured
                    line=dict(width=1, color=[SURFACE] + [AXIS] * (len(nodes) - 1)), pad=dict(t=24, l=3, r=3, b=3),
                    colorbar=dict(title=dict(text="1-day change", side="right"), tickvals=colour_ticks,
                                  ticktext=[f"{v * 100:+g}%" if v else "0%" for v in colour_ticks],
                                  thickness=14, len=0.8, outlinewidth=0)),
        customdata=nodes[["full_name", "cap_text", "colour", "detail"]].to_numpy(),
        texttemplate="<b>%{label}</b><br>%{customdata[2]:+.1%}",
        hovertemplate=("<b>%{customdata[0]}</b><br>Market cap: %{customdata[1]}"
                       "<br>1-day change: %{customdata[2]:+.2%}<br>%{customdata[3]}<extra></extra>"),
        pathbar=dict(visible=True, thickness=22, textfont=dict(color=INK)), tiling=dict(pad=2)))
    fig.update_layout(
        title=dict(text=headline,
                   subtitle=dict(text=f"Session {sec_as_of}{counter} · "
                                      + (f"{len(tm):,} of the {len(screen):,} largest companies (flagged rows left out)"
                                         if len(tm) < len(screen) else f"the {len(tm):,} largest companies")
                                      + f"<br>Best sector {best['sector']} {best['move']:+.1%} · worst "
                                      f"{worst['sector']} {worst['move']:+.1%} · area = market cap (USD) · "
                                      "click a tile to zoom")),
        height=680, margin=dict(t=120, l=10, r=10, b=10), uniformtext=dict(minsize=10, mode="hide"))
    fig.show()

    display(sectors.sort_values("contribution_pp", key=abs, ascending=False)
            .assign(cap_usd=lambda d: d["cap"].map(money))
            [["sector", "names", "cap_usd", "cap_share", "move", "contribution_pp", "api_mean_1d"]]
            .style.format({"cap_share": "{:.0%}", "move": "{:+.2%}", "contribution_pp": "{:+.2f}",
                           "api_mean_1d": "{:+.2%}"}, na_rep="n/a").hide(axis="index"))
    display(industries.sort_values("cap", ascending=False).head(12)
            .assign(cap_usd=lambda d: d["cap"].map(money))
            [["sector", "industry", "names", "cap_usd", "move", "api_mean_1d"]]
            .style.format({"move": "{:+.2%}", "api_mean_1d": "{:+.2%}"}, na_rep="n/a").hide(axis="index"))

# %% [markdown]
# **How to read this.** Big tiles are where the market's value sits, so a big
# blue block means large companies rose and a big red block means they fell.
# Grey tiles barely moved. The colour range is the same on both sides of zero
# (printed on the colour bar), so a strong red and a strong blue stand for
# moves of equal size; anything beyond the range shows at full colour, and
# hovering gives the exact number. Click a sector or industry to zoom in and
# see each company; click the path bar at the top to zoom back out.
#
# The title names the sector with the **biggest contribution**: its share of
# the value times its move, in percentage points (pp) of the overall move. A
# small sector with a big move can top the "best sector" list and still matter
# less than a giant sector with a modest move. The biggest contribution can
# also go **against** the day: a sector that fell hard on an up day is the
# biggest drag, and the title says so; the subtitle then names the sector that
# did most in the day's direction. The first table under the chart lists every
# sector's contribution (they add up to the overall move); the second lists the
# 12 largest industries.
#
# This kit uses blue for up and red for down in every market. Local screens in
# China and Hong Kong often use the opposite convention.
#
# **Caveats.**
#
# - The treemap shows only the largest companies (the screen pages you
#   fetched). It describes the big end of the market, not every stock; the
#   breadth column in the sector table covers every stock.
# - Thin lines are left out so a company is not counted twice, and possible
#   splits are left out because their market cap is suspect (step 6). Share
#   classes that both trade actively (for example two classes of the same
#   company) stay in, each with the market cap the screen reports for it.
# - This is one day's move. One day says little about a trend.
# - Check `as_of_date`: on a market holiday the snapshot still shows the last
#   session (China's Golden Week holiday, for example, leaves it unchanged for
#   several days).
# - Some stocks have no industry. They appear under "(no industry)".

# %% [markdown]
# ## 5. Realtime: the current-session turnover board
#
# **What it is for.** The realtime board lists the most-traded names, among
# those its source feed covers, in the current session (or the last one, if the
# market is closed), ranked by projected turnover: 50 names by default, or pass
# `limit` (1 to 100; we use the `RT_LIMIT` parameter). For each name it shows
# the money traded so far, the session return, and a projection of the full
# day's turnover compared with yesterday's.
#
# **Which names?** The board ranks the names its source feed (`source`)
# covers, and that is not always the whole market. The China board, for
# example, can list STAR Market names only: Shanghai's technology board (codes
# starting 688 or 689), where the daily price limit is ±20% instead of the
# main boards' ±10%. So the cleaning cell below measures the China board's
# composition instead of assuming it.
#
# **A board, not a tick feed.** Despite the name, `realtime` does not stream
# trades. Each call returns one snapshot of the board, refreshed about once a
# minute (`cache_ttl_seconds` is 60), and the source feed and cadence vary by
# market. To follow a session, call it again a minute later. When a market is
# closed you get its **last session's board**, marked `data_quality: "stale"`
# with `stale_reason: "market_closed"`. A stale board with another
# `stale_reason` during an open session means the feed is lagging, and the
# snapshot may trail the live session. Always read the status line before the
# numbers.

# %%
rt_payload = sf_get(f"/api/v1/markets/{MARKET}/realtime", limit=RT_LIMIT)
show_freshness(rt_payload, "Realtime board:")
rt_meta = rt_payload["data"]
explain_board(rt_meta, f"The {MARKET_NAMES[MARKET]} realtime board")
print(f"Source feed: {rt_meta['source']}; cache TTL: {rt_meta['cache_ttl_seconds']} s.")

# %% [markdown]
# **Raw preview.**

# %%
rt_raw = to_frame(rt_payload, "realtime")
if rt_raw.empty:
    display(Markdown("> The realtime board has no rows right now. That is normal before the open or on a holiday."))
rt_raw.head() if not rt_raw.empty else None

# %% [markdown]
# ### Cleaning the realtime board
#
# We wrap the cleaning in a small, visible function because section 7 reuses it
# for all four markets. It keeps the documented columns, keeps tickers as text,
# coerces numbers, de-duplicates on `ticker` and prints what it changed. A
# second function, `board_universe`, measures which part of the market a board
# covers: for China it counts the STAR Market codes, and when they make up most
# of the board it returns a label that the chart titles carry.
#
# Then we check what "projected" means. The board projects the full day by
# assuming the current pace continues: `projected_turnover = turnover_per_second
# × session seconds`. Dividing it back out should give the session length, and
# `accumulated_turnover / turnover_per_second` tells us how far into the
# session the snapshot was taken. `projected_vs_yesterday` should equal
# `projected_turnover / previous_day_turnover`.

# %%
RT_COLS = ["rank", "ticker", "company_name", "price", "intraday_return_pct", "turnover_per_second",
           "accumulated_turnover", "projected_turnover", "projected_vs_yesterday", "previous_day_turnover"]
RT_NUM = [c for c in RT_COLS if c not in ("ticker", "company_name")]


def clean_realtime(raw: pd.DataFrame, label: str) -> pd.DataFrame:
    """Documented columns -> tickers as text -> numbers -> one row per ticker, in board order."""
    df = pick(raw, RT_COLS)
    df["ticker"] = df["ticker"].astype("string").str.strip().replace("", pd.NA)   # text that keeps <NA>
    missing_before = int(df[RT_NUM].isna().sum().sum())
    for col in RT_NUM:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    coerced = int(df[RT_NUM].isna().sum().sum()) - missing_before
    n_raw, no_ticker = len(df), df["ticker"].isna()
    df = df[~no_ticker].drop_duplicates(subset="ticker", keep="first").sort_values("rank").reset_index(drop=True)
    print(f"{label}: {n_raw} rows -> {len(df)} ({int(no_ticker.sum())} without a ticker dropped, then "
          f"de-duplicated); {coerced} values became NaN when coerced.")
    return df


STAR_PREFIXES = ["688", "689"]   # Shanghai STAR Market codes: a ±20% daily price limit (main boards: ±10%)


def board_universe(board: pd.DataFrame, m: str) -> str:
    """Measure which part of the market a board covers. Returns a short label for titles ('' = no narrow segment)."""
    if m != "cn" or board.empty:
        return ""
    star = float(board["ticker"].str[:3].isin(STAR_PREFIXES).mean())
    if star >= 0.8:
        label = "STAR Market" if star == 1 else "mostly STAR Market"
        print(f"The China board currently lists {'STAR Market names only' if star == 1 else 'mostly STAR Market names'} "
              f"({star:.0%} of its {len(board)} names have a 688/689 code). It describes the STAR Market (±20% daily "
              "limit), not the whole A-share market.")
        return label
    print(f"China board composition: {star:.0%} of its {len(board)} names are STAR Market codes (688/689); the rest "
          "come from the other A-share boards.")
    return ""


rt = clean_realtime(rt_raw, f"Realtime {MARKET}")
RT_UNIVERSE = board_universe(rt, MARKET)

if not rt.empty:
    per_second = rt["turnover_per_second"].where(rt["turnover_per_second"] > 0)   # avoid dividing by zero
    implied_session = (rt["projected_turnover"] / per_second).median()
    elapsed = (rt["accumulated_turnover"] / per_second).median()
    pace_gap = (rt["projected_turnover"] / rt["previous_day_turnover"] - rt["projected_vs_yesterday"]).abs().max()
    display(pd.DataFrame({
        "check": ["Implied session length (s)", "Expected session length (s)",
                  "Seconds elapsed at the snapshot", "Share of the session elapsed",
                  "Largest gap: projected / yesterday vs projected_vs_yesterday",
                  "Board sorted by projected turnover?"],
        "value": [f"{implied_session:,.0f}", f"{SESSION_SECONDS[MARKET]:,}", f"{elapsed:,.0f}",
                  f"{elapsed / SESSION_SECONDS[MARKET]:.0%}", f"{pace_gap:.6f}",
                  str(bool(rt["projected_turnover"].is_monotonic_decreasing))],
    }).set_index("check"))

# %% [markdown]
# ### Chart: money traded versus the session's return
#
# Each bubble is one stock on the board. Left to right is the turnover traded
# so far (log scale, local currency). Up and down is the session return.
# Bubble **area** shows the pace versus yesterday (capped at `PACE_CAP` so one
# extreme name cannot shrink all the others), and colour picks out the names on
# course for at least twice yesterday's turnover.

# %%
if rt.empty:
    display(Markdown("> The realtime board is empty, so there is nothing to plot. Try again during the session."))
else:
    plot = rt.dropna(subset=["accumulated_turnover", "intraday_return_pct", "projected_vs_yesterday"]).copy()
    plot = plot[(plot["accumulated_turnover"] > 0) & (plot["projected_vs_yesterday"] > 0)]
    print(f"Plotting {len(plot)} of {len(rt)} names ({len(rt) - len(plot)} dropped for missing or non-positive "
          "turnover or pace: a log axis and a bubble size need positive numbers).")
    plot["fast"] = plot["projected_vs_yesterday"] >= 2
    plot["size"] = plot["projected_vs_yesterday"].clip(upper=PACE_CAP)
    for col in ["accumulated_turnover", "projected_turnover", "previous_day_turnover"]:
        plot[f"{col}_text"] = plot[col].map(lambda v: money(v, CCY))
    MAX_D, MIN_R = 34, 4                               # diameter (px) of a bubble at PACE_CAP; smallest radius (px)
    sizeref = 2 * PACE_CAP / MAX_D ** 2                # plotly's area-mode rule: radius = sqrt(size / 2 / sizeref)

    def radius_px(size):
        """The radius plotly draws for a marker size (sizemin is a radius too)."""
        return np.maximum(np.sqrt(np.asarray(size, dtype=float) / 2 / sizeref), MIN_R)

    plot["radius_px"] = radius_px(plot["size"])
    n_fast = int(plot["fast"].sum())
    finished = market_closed(rt_meta)                  # closed market: the board is the whole last session

    fig = go.Figure()
    for fast, name, colour, opacity in [(False, "Below 2× yesterday's pace", MUTED, 0.45),
                                        (True, "2× yesterday's pace or more", MARKET_COLORS[MARKET], 0.85)]:
        part = plot[plot["fast"] == fast]
        fig.add_trace(go.Scatter(
            x=part["accumulated_turnover"], y=part["intraday_return_pct"], mode="markers", name=name,
            marker=dict(size=part["size"], sizemode="area", sizeref=sizeref, sizemin=MIN_R,
                        color=colour, opacity=opacity, line=dict(width=1.5, color=SURFACE)),
            customdata=part[["company_name", "ticker", "rank", "accumulated_turnover_text", "projected_turnover_text",
                             "previous_day_turnover_text", "projected_vs_yesterday"]].to_numpy(),
            hovertemplate=("<b>%{customdata[0]}</b> (%{customdata[1]})<br>Board rank: %{customdata[2]}"
                           "<br>Session return: %{y:+.2f}%<br>Traded so far: %{customdata[3]}"
                           "<br>Projected for the session: %{customdata[4]}<br>Yesterday: %{customdata[5]}"
                           "<br>Pace vs yesterday: %{customdata[6]:.2f}×<extra></extra>")))

    labelled = plot[plot["fast"]].nlargest(5, "projected_vs_yesterday")    # label selectively
    if labelled.empty:
        labelled = plot.nlargest(1, "projected_vs_yesterday")
    for _, row in labelled.iterrows():
        fig.add_annotation(x=np.log10(row["accumulated_turnover"]), y=row["intraday_return_pct"],
                           text=f"{row['ticker']} {row['projected_vs_yesterday']:.1f}×", showarrow=True,
                           arrowhead=0, arrowwidth=1, arrowcolor=MUTED, ax=30, ay=-30,
                           standoff=row["radius_px"] + 2, font=dict(size=11, color=INK_2),
                           bgcolor="rgba(252,252,251,0.85)")
    fig.add_hline(y=0, line=dict(color=AXIS, width=1))
    # Size key in the right margin: circles drawn at exactly the pixel size of a 1x, 2x and 4x bubble.
    fig.add_annotation(xref="paper", yref="paper", x=1.02, y=1.0, xanchor="left", yanchor="top", showarrow=False,
                       align="left", text="Bubble area =<br>pace vs<br>yesterday", font=dict(size=11, color=INK_2))
    key_paces = sorted({min(p, PACE_CAP) for p in (1.0, 2.0, PACE_CAP)}, reverse=True)
    for y_key, pace in zip([0.72, 0.52, 0.36], key_paces):
        r = float(radius_px(pace))
        fig.add_shape(type="circle", xref="paper", yref="paper", xsizemode="pixel", ysizemode="pixel",
                      xanchor=1.05, yanchor=y_key, x0=-r, x1=r, y0=-r, y1=r,
                      fillcolor=MUTED, opacity=0.45, line=dict(color=INK_2, width=1))
        fig.add_annotation(xref="paper", yref="paper", x=1.05, y=y_key, xshift=20, xanchor="left",
                           showarrow=False, text=f"{pace:g}×", font=dict(size=11, color=INK_2))
    fig.update_xaxes(type="log", title_text=f"Turnover traded so far ({CCY}, log scale)",
                     **log_ticks(plot["accumulated_turnover"], CCY))
    fig.update_yaxes(title_text="Session return (%)", ticksuffix="%", zeroline=False)
    verb = "finished the session at" if finished else "are on course for"
    headline = (f"{n_fast} of {len(plot)} names on the {MARKET_NAMES[MARKET]} board {verb} "
                "2× yesterday's turnover or more" if n_fast else
                f"No name on the {MARKET_NAMES[MARKET]} board is at 2× yesterday's pace; "
                f"the median is {plot['projected_vs_yesterday'].median():.2f}×")
    fig.update_layout(
        title=dict(text=headline,
                   subtitle=dict(text=f"Market {rt_meta['market_status']} · data_quality {rt_meta['data_quality']}"
                                      + (f" ({rt_meta['stale_reason']})" if rt_meta["stale_reason"] else "")
                                      + f" · snapshot {local_time(rt_meta['as_of_local'])}<br>"
                                      + (f"Board lists {RT_UNIVERSE} names, not the whole market · " if RT_UNIVERSE else "")
                                      + f"Bubble area = pace vs yesterday, capped at {PACE_CAP:g}× (key on the right)")),
        height=540, margin=dict(t=120, b=90, r=120),
        legend=dict(orientation="h", x=0, y=-0.2, yanchor="top", itemsizing="constant"))
    fig.show()

    # Table twin: every plotted name, fastest first, so the labelled names lead the table.
    scroll_table(plot.sort_values("projected_vs_yesterday", ascending=False)
                 [["rank", "ticker", "company_name", "intraday_return_pct", "accumulated_turnover",
                   "projected_turnover", "previous_day_turnover", "projected_vs_yesterday"]]
                 .style.format({"intraday_return_pct": "{:+.2f}%", "accumulated_turnover": "{:,.0f}",
                                "projected_turnover": "{:,.0f}", "previous_day_turnover": "{:,.0f}",
                                "projected_vs_yesterday": "{:.2f}×"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Further right means more money has changed hands; each
# gridline step on a log axis is a multiple, not a fixed amount. Above the grey
# line the stock is up on the session, below it is down. Big coloured bubbles
# are the unusual ones: heavy trading compared with yesterday. A big bubble high
# up is a name rising on unusually heavy trading; a big bubble low down is
# heavy selling. The key on the right shows the bubble size of 1×, 2× and 4×
# yesterday's pace. The fastest names are labelled with their pace, and the
# table (scroll it) lists every plotted name, fastest first. Hover over a
# bubble for the details.
#
# **Caveats.**
#
# - Money on this board is in **local currency** and no currency field is
#   sent. Do not compare turnover across markets without converting it.
# - The projection assumes today's pace continues. Trading is heavier near the
#   open and the close, so early in the session the projection is noisy and
#   often too high. Japan, Hong Kong and China also pause for lunch.
# - On a closed market the board shows the full last session, so the
#   "projection" is simply the day's final turnover.
# - The board holds only the top names by projected turnover among the names
#   its feed covers. It describes the busiest stocks, not the whole market.
# - The China board currently covers the **STAR Market** (codes 688/689,
#   ±20% daily limit), not the whole A-share market. The composition line
#   printed by the cleaning cell says whether that still holds when you run
#   it. Comparing that board with another market's board, or with the China
#   screen and sector snapshot, compares different sets of stocks.

# %% [markdown]
# ### Units lesson: two "returns" that must not be mixed
#
# The screen and the realtime board both report how a stock moved, but:
#
# | Field | Endpoint | Unit | Measured |
# |---|---|---|---|
# | `change_pct` | screen, sector | **fraction**: 0.0142 = +1.42% | the session's close versus the previous close, for `as_of_date` |
# | `intraday_return_pct` | realtime, hotlist | **percent**: 1.42 = +1.42% | the board's own session return, at the snapshot time |
#
# The unit trap is a factor of 100: read `0.0142` as a percent and you get
# 0.0142%, not 1.42%. So **convert units explicitly** (`change_pct * 100` is
# in percent), but **never compare or combine the two fields** in an analysis:
# the API documents them as different measurements. The side-by-side below
# only demonstrates that they differ, and it only makes sense when the board
# and the screen describe the **same session**, which is after the close. While
# a market is open, the board is today's session and the screen is the
# previous one, so the cell prints the unit example and skips the comparison.

# %%
both = rt.merge(screen[["ticker", "price", "change_pct"]].rename(columns={"price": "screen_price"}),
                on="ticker", how="inner", validate="one_to_one")
both["change_pct_x100"] = both["change_pct"] * 100
both["gap_pp"] = both["intraday_return_pct"] - both["change_pct_x100"]
board_session = str(pd.Timestamp(rt_meta["as_of_local"]).date()) if rt_meta["as_of_local"] else "unknown"
same_session = board_session == first_page["as_of_date"]
print(f"{len(both)} of {len(rt)} board names are among the {len(screen):,} screen rows fetched. "
      f"Board session: {board_session}; screen session: {first_page['as_of_date']}.")
if RT_UNIVERSE:   # a board limited to one segment can only overlap the screen pages on that segment
    n_star_screen = int(screen["ticker"].str[:3].isin(STAR_PREFIXES).sum())
    print(f"Few matches are expected: the board lists {RT_UNIVERSE} names, while the screen pages hold the largest "
          f"companies of every A-share board ({n_star_screen} of the {len(screen):,} are STAR Market names).")

example = both.dropna(subset=["change_pct", "intraday_return_pct"]).head(1)
for _, first in example.iterrows():   # the unit lesson itself: how to read each number
    print(f"{first['ticker']}: change_pct = {first['change_pct']:.4f} means {first['change_pct']:+.2%} "
          f"(misread as a percent it would be {first['change_pct']:+.4f}%); "
          f"intraday_return_pct = {first['intraday_return_pct']:.4f} means {first['intraday_return_pct']:+.2f}%.")

paired = both.dropna(subset=["change_pct_x100", "intraday_return_pct"])   # explicit NaN policy: pairs only
if not same_session:
    display(Markdown(f"> The board is the session of {board_session} and the screen is the session of "
                     f"{first_page['as_of_date']}: two different days, so there is nothing to compare. The "
                     "side-by-side only makes sense after the close, when both describe the same session."))
elif len(paired) < 5:
    display(Markdown("> Too few names appear on both the board and the fetched screen pages to compare. "
                     "Raise `MAX_PAGES` or try another market."))
else:
    price_gap = ((paired["price"] / paired["screen_price"] - 1).abs() * 100).median()
    rho = stats.spearmanr(paired["change_pct_x100"], paired["intraday_return_pct"]).statistic
    median_gap = paired["gap_pp"].abs().median()
    close = (paired["gap_pp"].abs() < 0.1).mean()
    display(pd.DataFrame({"value": [
        f"{len(paired)} ({len(both) - len(paired)} with a missing return left out)", f"{price_gap:.2f}%",
        f"{median_gap:.2f} pp", f"{close:.0%}", f"{rho:+.2f}"]},
        index=pd.Index(["Names compared", "Median price gap (board vs screen)",
                        "Median gap between the two returns (after ×100)",
                        "Share agreeing within 0.1 pp", "Spearman rank correlation"], name="check")))

    lim = float(np.ceil(max(paired["change_pct_x100"].abs().max(), paired["intraday_return_pct"].abs().max()) + 0.5))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[-lim, lim], y=[-lim, lim], mode="lines", name="Identical returns (y = x)",
                             line=dict(color=MUTED, width=1.5, dash="dash"), hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=paired["change_pct_x100"], y=paired["intraday_return_pct"], mode="markers", name="One stock",
        marker=dict(color=MARKET_COLORS[MARKET], size=9, opacity=0.85),
        customdata=paired[["ticker", "company_name", "change_pct", "gap_pp"]].to_numpy(),
        hovertemplate=("<b>%{customdata[1]}</b> (%{customdata[0]})<br>Screen change_pct: %{customdata[2]:.4f} "
                       "= %{x:+.2f}%<br>Board intraday_return_pct: %{y:+.2f}%<br>Gap: %{customdata[3]:+.2f} pp"
                       "<extra></extra>")))
    for _, row in paired.reindex(paired["gap_pp"].abs().nlargest(3).index).iterrows():   # label the 3 biggest gaps
        fig.add_annotation(x=row["change_pct_x100"], y=row["intraday_return_pct"], text=row["ticker"],
                           showarrow=True, arrowhead=0, arrowwidth=1, arrowcolor=MUTED, ax=24, ay=-22,
                           font=dict(size=11, color=INK_2), bgcolor="rgba(252,252,251,0.85)")
    # Equal scales on both axes, so y = x runs at 45 degrees and a gap looks as big as it is.
    fig.update_xaxes(range=[-lim, lim], title_text="Screen change_pct × 100 (%)", ticksuffix="%", constrain="domain")
    fig.update_yaxes(range=[-lim, lim], title_text="Realtime intraday_return_pct (%)", ticksuffix="%",
                     scaleanchor="x", scaleratio=1, constrain="domain")
    fig.update_layout(
        title=dict(text=f"Same session, yet the two returns differ by a median {median_gap:.2f} pp",
                   subtitle=dict(text=f"Session {board_session} · {len(paired)} names on both the board and the "
                                      "screen pages<br>Points on the dashed line would mean identical measurements")),
        width=680, height=660, margin=dict(t=110, b=90),
        legend=dict(orientation="h", x=0, y=-0.14, yanchor="top"))
    fig.show()

    # Table twin: every plotted name, biggest gap first (the labelled names lead the table).
    scroll_table(paired.reindex(paired["gap_pp"].abs().sort_values(ascending=False).index)
                 [["rank", "ticker", "screen_price", "price", "change_pct", "change_pct_x100",
                   "intraday_return_pct", "gap_pp"]]
                 .style.format({"screen_price": "{:,.2f}", "price": "{:,.2f}", "change_pct": "{:.4f}",
                                "change_pct_x100": "{:+.2f}%", "intraday_return_pct": "{:+.2f}%",
                                "gap_pp": "{:+.2f}"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** If the two fields measured the same thing, every point
# would sit on the dashed line, which runs at 45 degrees because both axes use
# the same scale. They do not. Check the price gap in the table above: when it
# is tiny, the board and the screen agree on the price, yet the returns still
# differ, so they must start from different reference prices. They are
# different measurements. (While a market is open, the cell above skips this
# comparison, because the board and the screen then describe different days.)
# The table under the chart lists every name, biggest gap first.
#
# **The rule:** keep `change_pct` (fraction, close-to-close) and
# `intraday_return_pct` (percent, the board's session return) in separate
# columns, convert units explicitly, never compare or combine the two in an
# analysis, and say which one a chart shows.

# %% [markdown]
# ## 6. Hotlist: the session's momentum names
#
# **What it is for.** The hotlist is SurgeFlow's short momentum list for the
# current session. Each name comes with its projected turnover, its pace
# versus yesterday (`projected_vs_yesterday`) and its session return. Each row
# also carries a seven-part `factor_style` label: SurgeFlow's reading of how the
# stock's behaviour leans on the classic factors (market, size, value,
# momentum, quality, investment and liquidity).
#
# Two details matter. The amounts whose names end in `_usd` (`market_cap_usd`,
# `projected_turnover_usd`, `previous_day_turnover_usd`) are in **US dollars**;
# `price` stays in the local currency, and `turnover_per_second` carries no
# currency label (on the realtime board, all money is local currency). And
# **the hotlist can come back empty**: you get `count: 0` with
# `data_quality: "empty"` and `stale_reason: "no_current_hotlist_members"`.
# While the market is closed, that is expected. During an open session, report
# it as the API states it, with those two fields, and do not guess at a reason.
# The realtime board in section 5 still covers the session.

# %%
hot_payload = sf_get(f"/api/v1/markets/{MARKET}/hotlist")
show_freshness(hot_payload, "Hotlist:")
explain_board(hot_payload["data"], f"The {MARKET_NAMES[MARKET]} hotlist")

# %% [markdown]
# **Raw preview.**

# %%
hot_raw = to_frame(hot_payload, "hotlist")
if hot_raw.empty:
    display(Markdown("> No rows to preview: the hotlist is empty right now. The cells below handle that "
                     "and simply say so. Try again later in a session, or another market."))
hot_raw.head() if not hot_raw.empty else None

# %% [markdown]
# ### Cleaning the hotlist
#
# The same steps as before, plus three that are specific to this board:
#
# - The hotlist sends `market` in upper case (`"US"`). We lower it to match
#   every other endpoint.
# - `factor_style` packs seven labels into one string, in the order ERP
#   (market), SMB (size), HML (value), WML (momentum), RMW (profitability),
#   CMA (investment) and LIQ (liquidity). We split it into seven columns. A
#   different number of parts would mean the contract changed, so we raise.
# - We join the realtime board on `ticker` to see each name's realtime rank.
#   A missing rank (`NaN`) just means the name is not among the busiest names
#   that the realtime board returned.
# - The size label (SMB) is a factor **lean**, not a size fact, so we check it
#   against the market cap and print a note when a large company is labelled
#   "Small Cap".

# %%
HOT_COLS = ["hotlist_rank", "market", "ticker", "company_name", "industry", "factor_style", "price",
            "intraday_return_pct", "turnover_per_second", "market_cap_usd", "projected_turnover_usd",
            "projected_vs_yesterday", "previous_day_turnover_usd"]
HOT_NUM = ["hotlist_rank", "price", "intraday_return_pct", "turnover_per_second", "market_cap_usd",
           "projected_turnover_usd", "projected_vs_yesterday", "previous_day_turnover_usd"]
FACTORS = ["ERP", "SMB", "HML", "WML", "RMW", "CMA", "LIQ"]

hot = pick(hot_raw, HOT_COLS)
hot["ticker"] = hot["ticker"].astype("string").str.strip().replace("", pd.NA)   # text that keeps <NA>
for col in HOT_NUM:
    hot[col] = pd.to_numeric(hot[col], errors="coerce")
n_before, no_ticker = len(hot), hot["ticker"].isna()
hot = hot[~no_ticker].drop_duplicates(subset="ticker", keep="first").sort_values("hotlist_rank").reset_index(drop=True)
print(f"De-duplication: {n_before} rows -> {len(hot)} ({int(no_ticker.sum())} without a ticker dropped).")

if hot.empty:
    print("Nothing to clean: the hotlist has no names right now.")
else:
    hot["market"] = hot["market"].str.lower()
    styles = hot["factor_style"].str.split(" / ", expand=True)
    if styles.shape[1] != len(FACTORS):
        raise ValueError(f"factor_style has {styles.shape[1]} parts, expected {len(FACTORS)}: contract change?")
    hot[FACTORS] = styles.to_numpy()

    hot = hot.merge(rt[["ticker", "rank"]].rename(columns={"rank": "realtime_rank"}),
                    on="ticker", how="left", validate="one_to_one")
    print(f"{hot['realtime_rank'].notna().sum()} of {len(hot)} hotlist names are among the {len(rt)} names "
          f"on the realtime board; {hot['realtime_rank'].isna().sum()} are not.")
    display(hot[["hotlist_rank", "ticker"] + FACTORS].head(10).style.hide(axis="index"))

    big_small = hot[(hot["SMB"] == "Small Cap") & (hot["market_cap_usd"] > 10e9)]
    if not big_small.empty:
        biggest = big_small.loc[big_small["market_cap_usd"].idxmax()]
        print(f"Note: {len(big_small)} of {len(hot)} hotlist names are labelled 'Small Cap' with a market cap above "
              f"$10B (the largest: {biggest['ticker']} at {money(biggest['market_cap_usd'])}). factor_style "
              "describes a factor lean, not the company's size: use market_cap_usd for size.")

# %% [markdown]
# ### Chart: the hotlist ranked
#
# A **ranked dot plot**: one row per name, in the hotlist's own order (rank 1
# at the top). The dot sits at the projected session turnover in USD, on a log
# axis because turnover spans multiples; the label beside it is the pace versus
# yesterday. It is a dot, not a bar, on purpose: a log axis has no zero, so a
# bar's length would mean nothing. Read each dot against the gridlines.
#
# A ranking needs at least two names. With a single name, one sentence and a
# table say it better; with none, one sentence does. So when the hotlist has
# fewer than two names, the cell draws no chart. It does not borrow other names
# to fill the space either: the realtime board's busiest and fastest names are
# already charted and listed in section 5.

# %%
def ranked_dots(rows: pd.DataFrame, value: str, ccy: str, x_title: str) -> go.Figure:
    """One dot per row (top row first) on a log money axis; the text beside each dot is its pace vs yesterday."""
    fig = go.Figure(go.Scatter(
        x=rows[value], y=rows["label"], mode="markers+text",
        marker=dict(color=MARKET_COLORS[MARKET], size=12, line=dict(width=1, color=SURFACE)),
        text=rows["projected_vs_yesterday"].map(lambda v: f"{v:.1f}× yesterday"), textposition="middle right",
        textfont=dict(color=INK_2, size=12), cliponaxis=False,
        customdata=rows["hover"], hovertemplate="%{customdata}<extra></extra>"))
    fig.update_xaxes(type="log", title_text=x_title, **log_ticks(rows[value], ccy))
    fig.update_yaxes(title_text=None, ticks="", autorange="reversed", showgrid=True)   # row guides to each dot
    fig.update_layout(showlegend=False, height=190 + 34 * len(rows), margin=dict(t=110, r=130, l=20))
    return fig


def short_name(names: pd.Series, width: int = 26) -> pd.Series:
    return names.where(names.str.len() <= width, names.str.slice(0, width - 1) + "…")


hot_status = hot_payload["data"]["market_status"]
HOT_TABLE = ["hotlist_rank", "ticker", "company_name", "industry", "projected_turnover_usd",
             "previous_day_turnover_usd", "projected_vs_yesterday", "intraday_return_pct", "realtime_rank"]
HOT_FORMAT = {"projected_turnover_usd": "${:,.0f}", "previous_day_turnover_usd": "${:,.0f}",
              "projected_vs_yesterday": "{:.2f}×", "intraday_return_pct": "{:+.2f}%", "realtime_rank": "{:.0f}"}

if hot.empty:
    hot_meta = hot_payload["data"]
    display(Markdown(f"> The {MARKET_NAMES[MARKET]} hotlist is empty right now (data_quality: "
                     f"{hot_meta['data_quality']}, stale_reason: {hot_meta['stale_reason']}; market {hot_status}), "
                     "so there is nothing to rank and no chart. "
                     + ("That is expected while the market is closed. The realtime board's names from the last "
                        "session are charted and listed in section 5." if market_closed(hot_meta) else
                        "The realtime board still covers the session: its busiest and fastest names are charted "
                        "and listed in section 5.")))
elif len(hot) == 1:
    one = hot.iloc[0]
    rank_text = (f"realtime board rank {one['realtime_rank']:.0f}" if pd.notna(one["realtime_rank"])
                 else "not among the realtime board's names")
    display(Markdown(
        f"**{one['ticker']}** ({one['company_name']}, {one['industry']}) is the only name on the "
        f"{MARKET_NAMES[MARKET]} hotlist: projected turnover **{money(one['projected_turnover_usd'])}**, "
        f"**{one['projected_vs_yesterday']:.1f}×** yesterday's {money(one['previous_day_turnover_usd'])}, "
        f"session return **{one['intraday_return_pct']:+.2f}%**, market cap {money(one['market_cap_usd'])}, "
        f"{rank_text}. One name is not a ranking, so there is no chart"
        + (f"; section 5's bubble chart shows where {one['ticker']} sits on the realtime board."
           if pd.notna(one["realtime_rank"]) else ".")))
    display(hot[HOT_TABLE].style.format(HOT_FORMAT, na_rep="not on board").hide(axis="index"))
else:
    dots = hot.dropna(subset=["projected_turnover_usd"])
    dots = dots[dots["projected_turnover_usd"] > 0].sort_values("hotlist_rank").copy()
    print(f"Plotting {len(dots)} of {len(hot)} hotlist names ({len(hot) - len(dots)} without a positive "
          "projected turnover left out).")
    if len(dots) < 2:
        display(Markdown("> Fewer than two hotlist names have a positive projected turnover, so there is no "
                         "ranking to draw. The table lists every name."))
    else:
        dots["label"] = ("#" + dots["hotlist_rank"].map("{:.0f}".format) + " " + dots["ticker"] + " · "
                         + short_name(dots["company_name"]))
        dots["hover"] = [f"<b>{r.company_name}</b> ({r.ticker})<br>{r.industry if pd.notna(r.industry) else '(no industry)'}"
                         f"<br>Hotlist rank: {r.hotlist_rank:.0f}"
                         f"<br>Projected turnover: {money(r.projected_turnover_usd)} ({r.projected_vs_yesterday:.2f}× "
                         f"yesterday's {money(r.previous_day_turnover_usd)})<br>Session return: "
                         f"{r.intraday_return_pct:+.2f}%<br>Market cap: {money(r.market_cap_usd)}"
                         f"<br>Factor lean: {r.factor_style}" for r in dots.itertuples()]
        lead = dots.loc[dots["projected_turnover_usd"].idxmax()]
        fig = ranked_dots(dots, "projected_turnover_usd", "USD", "Projected session turnover (USD, log scale)")
        fig.update_layout(title=dict(
            text=(f"{lead['ticker']} carries the most money on the {MARKET_NAMES[MARKET]} hotlist: "
                  f"{money(lead['projected_turnover_usd'])} projected, {lead['projected_vs_yesterday']:.1f}× yesterday"),
            subtitle=dict(text=f"{len(dots)} names in hotlist order · pace vs yesterday from "
                               f"{dots['projected_vs_yesterday'].min():.1f}× to {dots['projected_vs_yesterday'].max():.1f}× "
                               f"· market {hot_status}")))
        fig.show()
    display(hot[HOT_TABLE].style.format(HOT_FORMAT, na_rep="not on board").hide(axis="index"))

# %% [markdown]
# **How to read this.** On the hotlist, rows run in the hotlist's own order,
# so the dot furthest to the right need not be at the top: `hotlist_rank` is a
# momentum ranking, not a turnover ranking. The axis is logarithmic, so each
# gridline is a multiple; read each dot's position against the gridlines. The
# label beside each dot says how today's projected turnover compares with
# yesterday's: "3.5× yesterday" means three and a half times as much money is
# on course to trade. Hover for the session return, the market cap and the
# factor lean. With fewer than two names there is no chart: read the sentence
# and the table instead.
#
# **Caveats.**
#
# - The hotlist's `_usd` columns are in US dollars; the realtime board's money
#   columns are in local currency. Never mix the two in one calculation. The
#   hotlist's `price` is in local currency too.
# - `intraday_return_pct` is in percent, like the realtime board's.
# - `factor_style` gives SurgeFlow's relative factor-lean labels (how the
#   stock's behaviour leans on each factor), not absolute facts. The method is
#   not documented: a company worth more than $200B can be labelled "Small
#   Cap". Use `market_cap_usd` and turnover for size and liquidity. The labels
#   are not a rating or a recommendation.
# - Early in a session the pace multiple is noisy, for the same reason as the
#   realtime projection.

# %% [markdown]
# ## 7. Extension: the four realtime boards side by side
#
# *This section goes beyond a single endpoint call.* We fetch the realtime
# board for every market (reusing the one we already have) and compare them
# with **small multiples**: the same chart repeated for each market, with
# shared axes, so your eye compares like with like. We use two currency-free
# measures, the pace versus yesterday (×) and the session return (%), because
# turnover in yen and turnover in dollars cannot be compared directly. The
# chart plots the **size** of each move, `|return|`, because the question is
# whether busier names move more in either direction; the table keeps the
# signed return.
#
# Markets keep different hours, so at any moment some boards are live and
# others are stale. Read the status and date in each panel title before
# comparing. The boards also cover different sets of stocks: when the China
# board lists STAR Market names only, its panel title says so, and its numbers
# describe the STAR Market, not the whole A-share market.

# %%
board_frames, board_meta, universe = [], [], {}
for m in MARKETS:
    payload = rt_payload if m == MARKET else sf_get(f"/api/v1/markets/{m}/realtime", limit=RT_LIMIT)
    show_freshness(payload, f"{MARKET_NAMES[m]}:")
    meta = payload["data"]
    board_meta.append({"market": m, "status": meta["market_status"], "data_quality": meta["data_quality"],
                       "stale_reason": meta["stale_reason"], "as_of_local": meta["as_of_local"]})
    board = clean_realtime(to_frame(payload, "realtime"), f"Realtime {m}")
    universe[m] = board_universe(board, m)          # e.g. "STAR Market" when the China board covers one segment
    if not board.empty:
        board_frames.append(board.assign(market=m))

board_meta = pd.DataFrame(board_meta).set_index("market")
boards = (pd.concat(board_frames, ignore_index=True) if board_frames
          else pd.DataFrame(columns=RT_COLS + ["market"]))
keep = boards["projected_vs_yesterday"] > 0          # a log scale needs positive values (a missing pace fails too)
left_out = (~keep).groupby(boards["market"]).sum().reindex(list(MARKETS), fill_value=0)
boards = boards[keep].copy()
boards["log2_pace"] = np.log2(boards["projected_vs_yesterday"].astype(float))
boards["abs_return_pct"] = boards["intraday_return_pct"].abs()
print(f"{len(boards)} rows across {boards['market'].nunique()} non-empty boards. Left out for a missing or "
      "non-positive pace: " + ", ".join(f"{m} {int(n)}" for m, n in left_out.items()) + ".")

# %% [markdown]
# **Statistics behind the chart.** For each board we report the median (the
# middle value) and the interquartile range (IQR, the spread of the middle
# half) of the session return, the share of names that are up, the median pace,
# and two **Spearman rank correlations** with the pace:
#
# - with the return: do faster-trading names tend to **rise** more?
# - with the absolute return `|return|`, the size of the move whichever way it
#   went: do faster-trading names tend to **move** more?
#
# Spearman's ρ (rho) uses ranks, so a few extreme values cannot dominate it. It
# runs from -1 to +1, and 0 means no relationship. The 95% interval uses the
# Fisher z-transform with the Bonett-Wright standard error. With about 50 names
# per board (`RT_LIMIT`) the interval is wide: read ρ as a rough description of
# today's board, not a law. Missing values are left out of each statistic
# (each share counts only the names that have the value), and `names_in_rho`
# says how many names each ρ rests on.

# %%
def spearman_ci(x: pd.Series, y: pd.Series, level: float = 0.95):
    """Spearman's rho with a Fisher-z confidence interval (Bonett & Wright, 2000)."""
    ok = x.notna() & y.notna()
    n = int(ok.sum())
    if n < 10:
        return n, np.nan, np.nan, np.nan
    rho = float(stats.spearmanr(x[ok], y[ok]).statistic)
    z, se = np.arctanh(np.clip(rho, -0.9999, 0.9999)), np.sqrt((1 + rho ** 2 / 2) / (n - 3))
    q = stats.norm.ppf(0.5 + level / 2)
    return n, rho, float(np.tanh(z - q * se)), float(np.tanh(z + q * se))


summary_rows = []
for m in MARKETS:
    b = boards[boards["market"] == m]
    ret, pace = b["intraday_return_pct"], b["projected_vs_yesterday"]
    _, rho_ret, _, _ = spearman_ci(b["log2_pace"], ret)
    n, rho_abs, lo, hi = spearman_ci(b["log2_pace"], b["abs_return_pct"])
    summary_rows.append({       # NaN policy: each share is taken over the names that have the value
        "market": m, "status": board_meta.loc[m, "status"], "data_quality": board_meta.loc[m, "data_quality"],
        "names": len(b), "median_return_pct": ret.median(), "iqr_return_pp": ret.quantile(0.75) - ret.quantile(0.25),
        "share_up": ret.dropna().gt(0).mean() if ret.notna().any() else np.nan, "median_pace": pace.median(),
        "share_2x_pace": pace.dropna().ge(2).mean() if pace.notna().any() else np.nan, "rho_pace_return": rho_ret,
        "names_in_rho": n, "rho_pace_size": rho_abs, "rho_size_ci_low": lo, "rho_size_ci_high": hi,
    })
board_summary = pd.DataFrame(summary_rows).set_index("market")
board_summary.style.format({
    "median_return_pct": "{:+.2f}%", "iqr_return_pp": "{:.2f} pp", "share_up": "{:.0%}", "median_pace": "{:.2f}×",
    "share_2x_pace": "{:.0%}", "rho_pace_return": "{:+.2f}", "rho_pace_size": "{:+.2f}",
    "rho_size_ci_low": "{:+.2f}", "rho_size_ci_high": "{:+.2f}"}, na_rep="n/a")

# %%
if boards.empty:
    display(Markdown("> Every board is empty right now, so there is nothing to compare."))
else:
    titles = []
    for m in MARKETS:
        status, quality, stamp = board_meta.loc[m, ["status", "data_quality", "as_of_local"]]
        day = pd.Timestamp(stamp).date() if stamp else "date unknown"
        rho, lo_m, hi_m = board_summary.loc[m, ["rho_pace_size", "rho_size_ci_low", "rho_size_ci_high"]]
        name = MARKET_NAMES[m] + (f" · {universe[m]}" if universe[m] else "")   # say when a board is one segment
        titles.append(f"<b>{name}</b><br>{status}" + ("" if quality == "ok" else f" ({quality}, {day})")
                      + (f"<br>ρ = {rho:+.2f} [{lo_m:+.2f}, {hi_m:+.2f}]" if pd.notna(rho)
                         else "<br>board empty" if board_summary.loc[m, "names"] == 0 else "<br>too few names for ρ"))
    fig = make_subplots(rows=1, cols=4, subplot_titles=titles, shared_yaxes=True, horizontal_spacing=0.03)
    fig.update_annotations(font_size=12)      # the panel titles: smaller than the chart title
    trend_shown = False
    for col, m in enumerate(MARKETS, start=1):
        b = boards[boards["market"] == m]
        fig.add_trace(go.Scatter(
            x=b["projected_vs_yesterday"], y=b["abs_return_pct"], mode="markers", name=MARKET_NAMES[m],
            marker=dict(color=MARKET_COLORS[m], size=8, opacity=0.8, line=dict(width=1, color=SURFACE)),
            customdata=b[["ticker", "company_name", "rank", "intraday_return_pct"]].to_numpy(),
            hovertemplate=(f"{MARKET_NAMES[m]}<br><b>%{{customdata[1]}}</b> (%{{customdata[0]}})"
                           "<br>Board rank: %{customdata[2]}<br>Pace vs yesterday: %{x:.2f}×"
                           "<br>Session return: %{customdata[3]:+.2f}%<extra></extra>")), row=1, col=col)
        fig.add_vline(x=1, line=dict(color=AXIS, width=1), row=1, col=col)
        rated_b = b.dropna(subset=["abs_return_pct"])
        if len(rated_b) >= 10:   # the typical move within each fifth of the names, ranked by pace
            fifth = pd.qcut(rated_b["log2_pace"].rank(method="first"), 5, labels=False)
            trend = rated_b.groupby(fifth).agg(pace=("projected_vs_yesterday", "median"),
                                               size=("abs_return_pct", "median"))
            fig.add_trace(go.Scatter(
                x=trend["pace"], y=trend["size"], mode="lines+markers", name="Median |return| per fifth by pace",
                legendgroup="trend", legendrank=2000, showlegend=not trend_shown, line=dict(color=INK, width=2),
                marker=dict(color=INK, size=6), hovertemplate=("Median pace %{x:.2f}×<br>median |return| "
                                                               "%{y:.2f}%<extra></extra>")), row=1, col=col)
            trend_shown = True
        if not b.empty:                                                   # label one name per panel: the fastest
            top = b.loc[b["projected_vs_yesterday"].idxmax()]
            fig.add_annotation(x=np.log10(top["projected_vs_yesterday"]), y=top["abs_return_pct"],
                               text=f"{top['ticker']} {top['projected_vs_yesterday']:.1f}×", showarrow=True,
                               arrowhead=0, arrowwidth=1, arrowcolor=MUTED, ax=-30, ay=-24,
                               font=dict(size=11, color=INK_2), bgcolor="rgba(252,252,251,0.85)", row=1, col=col)

    lo, hi = boards["projected_vs_yesterday"].min(), boards["projected_vs_yesterday"].max()
    pace_ticks = [t for t in (0.25, 0.5, 1, 2, 5, 10, 25, 50) if lo / 1.3 <= t <= hi * 1.3]
    fig.update_xaxes(type="log", range=[np.log10(lo / 1.3), np.log10(hi * 1.3)], tickvals=pace_ticks,
                     ticktext=[f"{t:g}×" for t in pace_ticks], tickfont_size=10,
                     title_text="Pace vs yesterday (×, log)", title_font_size=11)
    ylim = float(np.ceil(boards["abs_return_pct"].max() + 0.5))
    fig.update_yaxes(range=[0, ylim], ticksuffix="%", zeroline=False)
    fig.update_yaxes(title_text="Size of the move, |return| (%)", row=1, col=1)

    rated = board_summary.dropna(subset=["rho_pace_size"])
    n_pos, n_sig = int((rated["rho_pace_size"] > 0).sum()), int((rated["rho_size_ci_low"] > 0).sum())
    if len(rated) and n_sig > len(rated) / 2:          # a strong claim needs intervals, not just point estimates
        headline = (f"Names trading faster than yesterday moved further: the 95% interval for ρ(pace, |return|) "
                    f"lies above zero in {n_sig} of {len(rated)} markets")
    elif len(rated) and n_pos > len(rated) / 2:
        sig_text = ("no interval excludes zero" if n_sig == 0 else "only 1 interval excludes zero" if n_sig == 1
                    else f"only {n_sig} intervals exclude zero")
        headline = f"Faster-trading names moved further in {n_pos} of {len(rated)} markets, but {sig_text}"
    else:
        headline = "No consistent link between pace and the size of the move across the boards"
    live = [MARKET_NAMES[m] for m in MARKETS if board_meta.loc[m, "data_quality"] == "ok"]
    fig.update_layout(
        title=dict(text=headline, y=0.98, yanchor="top",      # pinned to the top: the panel titles need the room below
                   subtitle=dict(text=(f"Panel titles: ρ(pace, |return|) with its 95% interval. Live now: "
                                       f"{', '.join(live) if live else 'none'}; other boards show their last "
                                       "session (date in the panel title)<br>Grey line: 1× yesterday's pace · "
                                       "black line: median |return| within each fifth of the names by pace"))),
        height=540, margin=dict(t=165, b=100),
        legend=dict(orientation="h", x=0, y=-0.2, yanchor="top"))
    fig.show()

    # Table twin: every plotted name, fastest first within each market (the labelled names lead each block).
    order = {m: i for i, m in enumerate(MARKETS)}
    scroll_table(boards.assign(market_order=boards["market"].map(order))
                 .sort_values(["market_order", "projected_vs_yesterday"], ascending=[True, False])
                 [["market", "rank", "ticker", "company_name", "intraday_return_pct", "abs_return_pct",
                   "projected_vs_yesterday"]]
                 .style.format({"intraday_return_pct": "{:+.2f}%", "abs_return_pct": "{:.2f}%",
                                "projected_vs_yesterday": "{:.2f}×"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Each panel is one market, in its own colour, and every
# dot is one name on its board. Further right means trading faster than
# yesterday; higher means a bigger move in the session, up or down (hover for
# the signed return). The axes are shared, so you can compare panels directly.
# If the busier names are the ones moving most, the dots rise from left to
# right, and so does the black line (the median move within each fifth of the
# names, ranked by pace). That is what ρ(pace, |return|) in each panel title
# measures. The bracket is its 95% interval: when it includes zero, the board
# cannot tell the link from noise, and the chart title only makes the strong
# claim when most intervals lie above zero. The statistics table above is the
# numeric twin of this chart; the table below it lists every plotted name,
# fastest first within each market.
#
# **Caveats.**
#
# - A live board and a stale board are not the same thing. A live board
#   projects a partial session; a stale board shows a finished one. Compare
#   shapes, not levels, across them.
# - Each board holds only the busiest names that its feed covers, so these
#   are the patterns of the busiest names, not of the whole market. The China
#   board currently covers the STAR Market only (see the composition line
#   printed above and the panel title). Its median return, breadth and ρ
#   describe STAR Market names, a different universe from the other three
#   boards and from the broad A-share market (run the notebook with
#   `MARKET = "cn"` to see the whole market's breadth in the sector table).
# - Spearman's ρ here describes how stocks on today's board differ from each
#   other. It does not forecast returns and is not a trading signal.
# - Daily price limits cut off China's return distribution: ±10% on the main
#   boards, ±20% on the STAR Market and ChiNext. Every name on a STAR-only
#   board has the ±20% limit.

# %% [markdown]
# ## Next steps
#
# - Change `MARKET` to `"jp"` or `"hk"` and run again. During the Tokyo or Hong
#   Kong session those boards are live.
# - Run the realtime cell again a minute later and compare the two snapshots.
# - Raise `RT_LIMIT` (up to 100) to see more of each realtime board.
# - Raise `MAX_PAGES` to cover more of the screen, then rebuild the treemap:
#   more of the market gets a tile (each page costs one request).
# - Join other endpoints on `ticker`. Every v1 endpoint uses the same ticker
#   strings, so news, whale signals and ML clusters line up with these boards.
#
# ---
#
# *Research and education only. Nothing here is investment advice. The
# `realtime` endpoint names a current-session board, not a live-tick feed, and
# its update cadence varies by market. Check `as_of` and `data_quality` before
# you rely on any number.*

# %%
print(f"API requests made in this session: {api_calls_used()}")
