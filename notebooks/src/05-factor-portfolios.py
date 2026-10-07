# %% [markdown]
# # 05 · Factor portfolios: pure-factor returns, risk and holdings
#
# A **factor** is a simple rule for sorting stocks: by size, by how cheap they
# look, by how they did last year. Stocks on the same side of a rule tend to
# move together. A **factor portfolio** turns the rule into a return you can
# measure. It buys the stocks at one end of the sort, sells short the stocks at
# the other end, and records what the pair earns each day. SurgeFlow defines
# seven of them per market, from **ERP** (the market itself) to **LIQ**
# (liquidity), and publishes the returns and holdings of each one only after it
# passes a set of statistical tests (its **gates**). This notebook downloads
# them, reads the gates, cleans the data, checks it against the API's own
# statistics, and measures growth, risk, tail losses and holdings.
#
# Everything here is **descriptive and in-sample**. It shows what these rules
# earned over the last trading year, before costs. It does not forecast what
# they will earn next.
#
# **Empty is normal here.** When this notebook was last checked against the
# live API (7 October 2026), every factor in all four markets was withheld, so
# the API sent gate reasons but no returns or holdings. If that is still true
# when you run it, sections 3.1, 3.2 and 4 tell the story, and the return and
# holdings sections print a short note instead of a chart. They fill in by
# themselves on a day when a factor is published.
#
# **What you will learn**
#
# - What the seven pure factors buy and sell, and what a **signed weight** means.
# - Why SurgeFlow **discloses** each factor's publication gate instead of hiding
#   withheld factors, and how to tell a failed test from a test that has not
#   run yet.
# - How to turn nested return lists into one aligned date × factor table, what
#   to do about gaps, and why you never forward-fill a return.
# - How to reproduce the API's statistics (volatility, Sharpe-like ratio,
#   maximum drawdown, value at risk, expected shortfall) from the raw series.
# - How to chart growth of 100, drawdowns, rolling volatility, correlations,
#   tail losses and holdings honestly.
# - How much one year of data can tell you: a confidence interval for a
#   Sharpe-like ratio, and an autocorrelation-robust (HAC) t-statistic.
# - Which factors pass their gates in each of the four markets, how one factor
#   behaves across them, and why another market's holiday is not a gap.
#
# **Endpoint used**
#
# | Method | Path | What it returns |
# |---|---|---|
# | GET | `/api/v1/markets/{market}/factor-portfolios` | The seven canonical pure-factor portfolios (ERP, SMB, HML, WML, RMW, CMA, LIQ) for one market: each factor's gate state, statistics, signed holdings preview and daily return series, plus aligned correlations and an equal-weight mix. No query parameters |
#
# Markets: `us`, `cn`, `jp`, `hk`. The notebook makes 1 request for your market
# plus 3 for the four-market comparison in section 4 (4 in total; the free plan
# allows 2,000 a day). It runs in under a minute.
#
# **The seven factors**
#
# | Code | Name | Long leg (bought) | Short leg (sold short) | Usual ranking signal |
# |---|---|---|---|---|
# | ERP | Market: the equity risk premium | The market's main index (S&P 500, CSI 300, Nikkei 225 or Hang Seng) | Cash at the risk-free rate | None: index weights |
# | SMB | Size: Small Minus Big | The smallest companies | The largest companies | Market cap |
# | HML | Value: High Minus Low | High book-to-price ("cheap") | Low book-to-price ("expensive") | Book-to-price |
# | WML | Momentum: Winners Minus Losers | Best 12-month return, skipping the last month | Worst 12-month return | 12-month-minus-1-month return |
# | RMW | Profitability: Robust Minus Weak | Highly profitable companies | Weakly profitable companies | Profitability, such as profit margin |
# | CMA | Investment: Conservative Minus Aggressive | Slow growers | Fast growers | Asset or revenue growth |
# | LIQ | Liquidity | Less liquid stocks | More liquid stocks | Illiquidity, such as price impact per unit traded |
#
# These are the **textbook** directions. The API names the factors and their
# legs, but describes the signal only as "canonical factor signal" (in
# `research_passport.ranking_variable`). So section 3.11 checks each direction
# against the `signal_value` of the holdings, and you do not have to take this
# table on trust.
#
# **Words used in this notebook**
#
# | Word | Meaning |
# |---|---|
# | long / short | Long: you buy a stock and gain when it rises. Short: you borrow a stock, sell it, and gain when it falls |
# | leg | One side of a long-short portfolio: the long leg or the short leg |
# | signed weight | A holding's share of capital, with a sign: +0.94% is bought, −0.94% is sold short |
# | pure factor | A portfolio built to track one rule. Here: 50% of capital long, 50% short, equal weights inside each leg, so the market's overall move largely cancels out |
# | excess return | A return minus the risk-free rate (what cash would have earned). ERP is an excess return |
# | index = 100 | A cumulative return drawn as the value of 100 invested at the start |
# | drawdown | How far a portfolio sits below its previous peak |
# | volatility | How much daily returns swing: their standard deviation × √252, in % a year |
# | Sharpe-like ratio | Average yearly return ÷ yearly volatility: return per unit of risk |
# | VaR 95% | Value at risk: the daily loss that only the worst 5% of days exceed |
# | expected shortfall (ES) 95% | The average loss on those worst 5% of days. It describes the tail that VaR ignores |
# | gate | A statistical test that a factor must pass before SurgeFlow publishes its returns and holdings |
# | blocked / published | A factor's `publish_state`. Blocked factors are still listed, with the reason, but carry no returns or holdings |

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
# `FOCUS_FACTOR` picks the factor for the holdings chart (section 3.11) and for
# the four-market comparison (section 4).

# %%
MARKET = "us"            # one of "us", "cn", "jp", "hk"
FOCUS_FACTOR = "wml"     # one of "erp", "smb", "hml", "wml", "rmw", "cma", "liq"
COMPARE_MARKETS = True   # section 4 fetches the other three markets (3 more requests); False skips it
ROLL_DAYS = 63           # rolling-volatility window in trading days (63 ≈ 3 months, 21 ≈ 1 month)
TAIL = 0.95              # confidence level for VaR and expected shortfall (the API uses 0.95)
TRADING_DAYS = 252       # trading days in a year, used to annualise
MAX_ABS_DAILY = 0.5      # a factor return beyond ±50% in one day is treated as a data error
MAX_TYPICAL_DAILY = 0.02 # a median absolute daily return above 2% means the API sent percent: the units check stops

# Facts the API does not send with this endpoint.
CURRENCY = {"us": "USD", "cn": "CNY", "jp": "JPY", "hk": "HKD"}
SYMBOL = {"USD": "$", "CNY": "CN¥", "JPY": "¥", "HKD": "HK$"}

assert MARKET in MARKETS, f"MARKET must be one of {MARKETS}"
FOCUS_FACTOR = FOCUS_FACTOR.lower()
CCY = CURRENCY[MARKET]
TODAY = pd.Timestamp.now(tz="UTC").normalize()     # ages below are measured against today (UTC)
print(f"Studying {MARKET_NAMES[MARKET]} ({MARKET}); focus factor {FOCUS_FACTOR.upper()}; "
      f"today is {TODAY:%Y-%m-%d} UTC.")

# %% [markdown]
# A few small utilities keep the later cells short. They are plain code, so read
# them once:
#
# - `FACTOR_COLORS` gives each factor a fixed colour, in the API's contract
#   order (ERP first, LIQ last). It is used only where several factors share
#   one chart as lines (growth of 100), so a factor keeps its colour even when
#   another factor is withheld. Charts that name each factor on an axis or in a
#   panel title use one neutral colour instead: the same palette also colours
#   the markets and the long and short legs, and one hue should not mean two
#   things side by side.
# - `GATE_CODES` translates the gate codes in `gate_reason` into plain English.
#   It also records which test (or tests) each code belongs to, and whether the
#   code means the test **failed** or is still **pending** (not run yet, or too
#   little history to run it). `verdict` sums up a factor in one phrase, such
#   as "failed a test". `GATE_STYLE` gives each outcome a fixed colour *and* a
#   symbol, so the gate charts never rely on colour alone.
# - `risk_stats` recomputes the API's `stats` block from a daily return series
#   (section 3.4 lists the definitions).
# - `sharpe_interval` and `hac_test` say how precise a Sharpe-like ratio and an
#   average return are (section 3.10 explains both).
# - `add_end_labels` writes each line's name at its right end. It nudges the
#   labels apart so they never overlap, and ties each one to its line with a
#   thin leader in the line's colour.
# - `pick`, `pct`, `money`, `shorten`, `plural`, `rgba`, `grid_shape` and
#   `hide_unused_panels` are small formatting helpers. `note` prints a friendly
#   sentence when there is nothing to show.
#
# The chart subtitles need Plotly 5.23 or newer (Colab already has it). The
# cell checks the version first, so an older local install stops here with
# a one-line fix instead of failing in the middle of the notebook.

# %%
import re
import textwrap
from itertools import combinations

import plotly
import statsmodels.api as sm
from plotly.subplots import make_subplots
from scipy import stats

if tuple(int(p) for p in re.findall(r"\d+", plotly.__version__)[:2]) < (5, 23):
    raise ImportError(f"The charts here need plotly 5.23 or newer (title subtitles); you have {plotly.__version__}. "
                      "Run  pip install -U 'plotly>=5.23'  and restart the kernel.")

CANONICAL = ["erp", "smb", "hml", "wml", "rmw", "cma", "liq"]      # the API's contract order: ERP .. LIQ
FACTOR_COLORS = dict(zip(CANONICAL, SERIES))                        # colour follows the factor, never its rank
SIDE = {"long": "LONG", "short": "SHORT", "index": "LONG"}           # ERP's "index" leg is a long position
BOTTOM_LEGEND = dict(orientation="h", x=0, xanchor="left", y=0.01, yref="container", yanchor="bottom")
TEXTBOOK_LONG_HIGH = {"smb": False, "hml": True, "wml": True, "rmw": True, "cma": False, "liq": True}
STAT_KEYS = ["n_obs", "mean_annual", "vol_annual", "sharpe", "max_dd", "var_95_252d", "es_95_252d"]

SIGNALS = {   # top_holdings[].signal_value: the API does not name its unit, so labels stay generic. Label, format, noun
    "smb": ("Size signal (unit not documented)", ".3g", "size signals"),   # section 3.11 checks its scale
    "hml": ("Value signal (book-to-price)", ".2f", "book-to-price signals"),
    "wml": ("Momentum signal (12-1 month return)", ".2f", "momentum signals"),
    "rmw": ("Profitability signal", ".2f", "profitability signals"),
    "cma": ("Growth signal", ".2f", "growth signals"),
    "liq": ("Illiquidity signal", ".2f", "illiquidity signals"),
}
TEXTBOOK_LEGS = {   # the textbook long and short legs (the notebook's reading of each code, not sent by the API)
    "erp": ("the market's main index", "cash at the risk-free rate"),
    "smb": ("small companies", "large companies"),
    "hml": ("cheap stocks (high book-to-price)", "expensive stocks (low book-to-price)"),
    "wml": ("past winners (12-1 month return)", "past losers"),
    "rmw": ("highly profitable companies", "weakly profitable companies"),
    "cma": ("slow growers (conservative)", "fast growers (aggressive)"),
    "liq": ("less liquid stocks", "more liquid stocks"),
}
EVIDENCE = {  # evidence_status codes seen live, in plain English. "pit" = point-in-time: no look-ahead.
    "official_index_and_governed_risk_free": "official index returns minus a risk-free rate",
    "governed_pit": "point-in-time company fundamentals",
    "governed_pit_assets": "point-in-time balance-sheet (asset) data",
    "governed_market_data": "price history",
    "governed_turnover_history": "trading-turnover history",
}

GATE_TESTS = ["1 year of history", "Premium (HAC t-test)", "Spanning alpha", "Not redundant",
              "Correlation triangle", "Stock residuals"]
GATE_CODES = {   # gate code seen in gate_reason -> (the test or tests it covers, outcome, plain English)
    "factor_sample_below_252": (("1 year of history",), "pending",
                                "fewer than 252 daily returns (one trading year) so far"),
    "premium_hac_not_tested": (("Premium (HAC t-test)",), "pending",
                               "average return not yet tested with autocorrelation-robust (HAC) errors"),
    "premium_not_significant_5pct": (("Premium (HAC t-test)",), "failed",
                                     "average return not significantly different from zero (5% level)"),
    # The redundancy verdict comes out of the same spanning regression (live payloads send factor_redundant_5pct
    # only together with spanning_alpha_not_significant_5pct), so an untested spanning test leaves both pending.
    "spanning_not_tested": (("Spanning alpha", "Not redundant"), "pending",
                            "not yet tested against the other factors (can they explain it? is it redundant?)"),
    "spanning_alpha_not_significant_5pct": (("Spanning alpha",), "failed",
                                            "adds no significant return beyond the other factors (5% level)"),
    "factor_redundant_5pct": (("Not redundant",), "failed",
                              "redundant: the other factors already explain it (5% level)"),
    "correlation_triangle_not_tested": (("Correlation triangle",), "pending",
                                        "consistency of its correlations with the other factors not yet checked"),
    "stock_residual_diagnostics_not_tested": (("Stock residuals",), "pending",
                                              "stock-level residual diagnostics not yet run"),
}
VERDICTS = ["published", "failed a test", "under a year of history", "checks not yet run", "withheld, reason unknown"]
GATE_STYLE = {   # outcome -> legend text, marker symbol, colour, size. Status colours: never reused for a series.
    "failed": ("Failed", "x", "#d03b3b", 16),
    "pending": ("Pending: not run yet, or too little history", "circle-open", MUTED, 16),
    "unreported": ("No code reported (not necessarily run)", "circle", MUTED, 7),
    "passed": ("Passed (the factor is published)", "circle", "#0ca30c", 10),
}
GATE_MARK = {"failed": "✕ failed", "pending": "○ pending", "unreported": "· not reported", "passed": "✓ passed"}
VERDICT_STYLE = {   # the same visual language for whole factors (section 4)
    "published": ("Published", "circle", "#0ca30c"),
    "failed a test": ("Withheld: failed a test", "x", "#d03b3b"),
    "under a year of history": ("Withheld: under a year of history", "hourglass", MUTED),
    "checks not yet run": ("Withheld: checks not yet run", "circle-open", MUTED),
    "withheld, reason unknown": ("Withheld: reason unknown", "square-open", MUTED),
}


def pick(raw: pd.DataFrame, columns: list) -> pd.DataFrame:
    """Keep the documented columns. Empty is normal; a missing column raises KeyError (a contract change)."""
    if raw.empty:
        return pd.DataFrame(columns=columns)
    return raw[columns].copy()


def pct(value, digits: int = 1, signed: bool = False) -> str:
    """0.0123 -> '1.2%' (or '+1.2%' when signed). Missing values print as 'n/a'."""
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:+.{digits}%}" if signed else f"{value:.{digits}%}"


def signed(value, digits: int = 2) -> str:
    """-0.0048 -> '+0.00', not '-0.00': round first, so a tiny negative number does not print as minus zero."""
    return f"{round(float(value), digits) + 0.0:+.{digits}f}"


def money(value, ccy: str = "USD", digits: int = 2) -> str:
    """4621704856204 -> '$4.62T' (a big number with its currency symbol)."""
    if value is None or pd.isna(value):
        return "n/a"
    sign, value = ("-" if value < 0 else ""), abs(float(value))
    for size, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= size:
            return f"{sign}{SYMBOL[ccy]}{value / size:,.{digits}f}{unit}"
    return f"{sign}{SYMBOL[ccy]}{value:,.0f}"


def shorten(text, width: int = 24) -> str:
    """Cut a long name to `width` characters, with an ellipsis."""
    text = str(text)
    return text if len(text) <= width else text[: width - 1] + "…"


def plural(n, word: str, many: str = None) -> str:
    """plural(1, 'day') -> '1 day'; plural(3, 'day') -> '3 days'."""
    n = int(n)
    return f"{n:,} {word if n == 1 else (many or word + 's')}"


def rgba(hex_color: str, alpha: float) -> str:
    """'#2a78d6', 0.12 -> 'rgba(42,120,214,0.12)': a light wash of a series colour for area fills."""
    h = hex_color.lstrip("#")
    return "rgba({},{},{},{})".format(*(int(h[i:i + 2], 16) for i in (0, 2, 4)), alpha)


def grid_shape(n: int, max_cols: int = 3) -> tuple:
    """Rows and columns for a grid of n small panels."""
    cols = max(1, min(max_cols, n))
    return int(np.ceil(n / cols)), cols


def hide_unused_panels(fig, n_panels: int, rows: int, cols: int) -> None:
    """A grid of 7 panels has 9 cells: hide the axes of the cells that hold no panel, so they draw nothing."""
    for k in range(n_panels, rows * cols):
        r, c = k // cols + 1, k % cols + 1
        fig.update_xaxes(visible=False, row=r, col=c)
        fig.update_yaxes(visible=False, row=r, col=c)


def label_lowest_panels(fig, filled: list, rows: int, cols: int) -> None:
    """Shared x-axes are labelled on the bottom row only. If a column's bottom panel is empty,
    label the lowest filled panel instead. `filled` lists the (row, col) panels that hold data."""
    for c in range(1, cols + 1):
        rows_with_data = [r for r, cc in filled if cc == c]
        if rows_with_data and max(rows_with_data) < rows:
            fig.update_xaxes(showticklabels=True, row=max(rows_with_data), col=c)


def note(text: str) -> None:
    """A friendly one-line note in place of a chart or table (empty is normal)."""
    display(Markdown(f"> {text}"))


def gate_codes(reason) -> list:
    """'factor_sample_below_252; spanning_not_tested' -> ['factor_sample_below_252', 'spanning_not_tested']."""
    if reason is None or (isinstance(reason, float) and np.isnan(reason)):
        return []
    return [code.strip() for code in str(reason).split(";") if code.strip()]


def gate_outcome(code: str) -> tuple:
    """(tests, 'failed' or 'pending', plain English) for one gate code. A code the notebook does not know yet
    is shown under 'Other': pending if it ends in _not_tested or mentions 'below', otherwise failed."""
    if code in GATE_CODES:
        return GATE_CODES[code]
    pending = code.endswith("_not_tested") or "below" in code
    return ("Other",), "pending" if pending else "failed", code.replace("_", " ")


def explain_gates(reason) -> str:
    """Plain English for every code in gate_reason. An empty reason means no failed gate is reported."""
    codes = gate_codes(reason)
    return "; ".join(gate_outcome(c)[2] for c in codes) if codes else "none reported"


def verdict(state, reason) -> str:
    """One phrase per factor: published, failed a test, under a year of history, or checks not yet run."""
    codes = gate_codes(reason)
    if state == "published":
        return "published"
    if any(gate_outcome(c)[1] == "failed" for c in codes):
        return "failed a test"
    if "factor_sample_below_252" in codes:
        return "under a year of history"
    return "checks not yet run" if codes else "withheld, reason unknown"


def main_reason(reason) -> str:
    """The most decisive gate in plain English: a failed test first, then missing history, then a pending check."""
    codes = gate_codes(reason)
    rank = {"failed": 0, "pending": 2}
    codes = sorted(codes, key=lambda c: 1 if c == "factor_sample_below_252" else rank[gate_outcome(c)[1]])
    return gate_outcome(codes[0])[2] if codes else "no reason given"


def and_list(items) -> str:
    """['HML', 'RMW', 'CMA'] -> 'HML, RMW and CMA'."""
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else "none"


def risk_stats(r: pd.Series, level: float = TAIL) -> dict:
    """The API's `stats` block, recomputed from daily returns (decimals). Missing days are dropped first."""
    r = r.dropna()
    if r.empty:
        return {key: (0 if key == "n_obs" else np.nan) for key in STAT_KEYS}
    wealth = (1 + r).cumprod()                         # value of 1 invested, compounded daily
    drawdown = wealth / wealth.cummax() - 1            # distance below the running peak (always <= 0)
    cutoff = r.quantile(1 - level)                     # the 5th-percentile day
    vol = r.std(ddof=1) * np.sqrt(TRADING_DAYS)        # yearly volatility
    mean = r.mean() * TRADING_DAYS                     # yearly arithmetic mean
    return {"n_obs": len(r), "mean_annual": mean, "vol_annual": vol,
            "sharpe": mean / vol if vol > 0 else np.nan, "max_dd": drawdown.min(),
            "var_95_252d": -cutoff, "es_95_252d": -r[r <= cutoff].mean()}


def sharpe_interval(r: pd.Series, z: float = 1.96) -> tuple:
    """Yearly Sharpe-like ratio, its standard error and a 95% interval.

    Uses the Mertens (2002) standard error, which allows for skew and fat tails but
    assumes that days are independent. As a rule of thumb it is 1 / sqrt(years of data).
    """
    r = r.dropna()
    daily = r.mean() / r.std(ddof=1)
    skew, excess_kurt = stats.skew(r, bias=False), stats.kurtosis(r, fisher=True, bias=False)
    se = np.sqrt((1 + 0.5 * daily**2 - skew * daily + excess_kurt / 4 * daily**2) / len(r))
    k = np.sqrt(TRADING_DAYS)                          # daily -> yearly
    return daily * k, se * k, (daily - z * se) * k, (daily + z * se) * k


def newey_west_lags(n: int) -> int:
    """The usual rule of thumb for how many lags a HAC (Newey-West) standard error should allow."""
    return int(np.floor(4 * (n / 100) ** (2 / 9)))


def hac_test(r: pd.Series) -> dict:
    """Is the average daily return different from zero? OLS on a constant with Newey-West (HAC) errors."""
    r = r.dropna()
    lags = newey_west_lags(len(r))
    fit = sm.OLS(r.to_numpy(), np.ones(len(r))).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return {"t": float(fit.tvalues[0]), "p": float(fit.pvalues[0]), "lags": lags}


def spread_labels(values, min_gap: float) -> np.ndarray:
    """Move label positions apart until neighbours are at least `min_gap` apart, keeping their order.

    Labels that would collide are merged into a cluster, and each cluster is centred on the
    average of its own lines, so a label moves only as far as it has to.
    """
    v = np.asarray(values, dtype=float)
    clusters = [[i] for i in np.argsort(v)]

    def place(cluster):
        return v[cluster].mean() + (np.arange(len(cluster)) - (len(cluster) - 1) / 2) * min_gap

    merged = True
    while merged:
        merged = False
        for k in range(len(clusters) - 1):
            if place(clusters[k + 1])[0] - place(clusters[k])[-1] < min_gap - 1e-12:
                clusters[k:k + 2] = [clusters[k] + clusters[k + 1]]
                merged = True
                break
    out = np.empty_like(v)
    for cluster in clusters:
        out[cluster] = place(cluster)
    return out


def add_end_labels(fig, ends: pd.DataFrame, y_range: list, plot_px: float, min_px: float = 17) -> None:
    """Label each line at its right end, at least `min_px` pixels apart, with a thin leader to the line.

    `ends` has one row per line: x and y (the line's last point), text and color. `plot_px` is the
    height of the plot area in pixels, so we can convert pixels into data units. The text stays in
    ink; only the leader carries the series colour.
    """
    gap = min_px * (y_range[1] - y_range[0]) / plot_px
    label_y = spread_labels(ends["y"].to_numpy(dtype=float), gap)
    for (_, end), y_label in zip(ends.iterrows(), label_y):
        fig.add_annotation(x=end["x"], y=end["y"], ax=26, ay=y_label, axref="pixel", ayref="y",
                           text=end["text"], showarrow=True, arrowhead=0, arrowwidth=1.2,
                           arrowcolor=end["color"], standoff=2, xanchor="left", yanchor="middle",
                           font=dict(size=12, color=INK_2))

# %% [markdown]
# ## 3. Factor portfolios: `/api/v1/markets/{market}/factor-portfolios`
#
# **What it is for.** SurgeFlow builds seven "canonical" factor portfolios per
# market (the `release_id` starts with `factor_daily_`, which suggests a daily
# build). For each factor that passes its gates it publishes the daily returns
# over the last trading year, risk statistics and a preview of the holdings;
# for the others it publishes the reasons. You use them to see
# which investment styles have been paying, how risky each one is, how they move
# together and which stocks sit on each side.
#
# The records live at **`data.data.factors`**. The API wraps its internal
# response (`{ok, data}`) in its own envelope, so `data` appears twice. The
# helper's `RESPONSE_SHAPES["factor_portfolios"]` already knows this path. Next
# to the factors you find:
#
# | Part | What it holds |
# |---|---|
# | `data.data.as_of`, `.release_id`, `.n_active`, `.n_risk_ready` | Which session the data describes, which build produced it, how many factors are published |
# | `data.data.contract_factors[]`, `.factor_contract_sha256` | The seven factor ids in their fixed order, and a fingerprint of the factor contract (equal across markets built from one contract) |
# | `data.data.research_passport` | Provenance: how the portfolios are built, weighted, rebalanced and costed, and whether results are in-sample |
# | `data.data.factors[]` | One record per factor, always all seven: gate state, `stats`, `holdings_metrics`, `top_holdings[]`, `return_series[]` |
# | `data.data.raw_survivors_summary[]` | A compact second listing of each factor's state, used below as a cross-check |
# | `data.data.aggregate` | The equal-weight mix of the published factors, their correlation matrix and the aligned date window |
# | `data.data.disclosure` | A one-paragraph construction note |
# | `data.data.word_cloud[]`, `.narrative_coverage` | Text features for the holdings (empty when nothing is published) |
#
# **Gate state is disclosed, not filtered.** A factor that fails SurgeFlow's
# publication tests still appears. It has `publish_state = "blocked"`, the
# reasons in `gate_reason`, `stats` full of nulls, and empty
# `return_series` and `top_holdings`. You always see all seven rows, and you
# always see *why* one is missing. **Empty is normal:** on some days every
# factor in a market is blocked. Then `as_of` is null, and the charts below
# print a note instead.
#
# **Freshness lives in `data.data`.** `show_freshness` reads only the top level
# and the first `data` level, so here it finds just `market`. We print
# `as_of`, `release_id` and the counts ourselves.
#
# This is the notebook's only endpoint, so we fetch it with `sf_try`: if it is
# temporarily down (an HTTP 500, or an error wrapped inside a 200 response),
# you get a short note and the notebook stops here instead of a long traceback.
# Try again a little later.

# %%
fp_payload = sf_try(f"/api/v1/markets/{MARKET}/factor-portfolios")
if fp_payload is None:
    raise SystemExit("Factor portfolios are unavailable right now, so the rest of the notebook has nothing to show. "
                     "Try again later.")
show_freshness(fp_payload, "Factor portfolios:")
fp = fp_payload["data"]["data"]          # a missing key here is a contract change: let it raise
agg = fp["aggregate"]

as_of = pd.to_datetime(fp["as_of"], utc=True) if fp["as_of"] else None
stamp = re.search(r"(\d{8}t\d{6})", str(fp["release_id"]))          # the id appears to encode its build time
built = pd.to_datetime(stamp.group(1), format="%Y%m%dt%H%M%S", utc=True) if stamp else None

as_of_text = (f"{as_of:%Y-%m-%d} ({plural((TODAY - as_of).days, 'day')} before today)"
              if as_of is not None else "**null**: no factor is published today")
built_text = f"{built:%Y-%m-%d %H:%M} UTC" if built is not None else "time not encoded"
window_text = (f"{agg['correlation_start']} to {agg['correlation_as_of']}, {agg['n_aligned_dates']} dates"
               if agg["n_aligned_dates"] else "none: no factor is published")
facts = [
    ("market", f"`{fp['market']}`"),
    ("as_of: the last session in the data", as_of_text),
    ("release_id", f"`{fp['release_id']}` (built {built_text})"),
    ("factor contract", f"{len(fp['contract_factors'])} factors, fingerprint `{str(fp['factor_contract_sha256'])[:12]}…`"),
    ("published factors (`n_active`)", f"{fp['n_active']} of {len(fp['factors'])}"),
    ("risk-ready factors (`n_risk_ready`)", str(fp["n_risk_ready"])),
    ("aligned window (`aggregate`)", window_text),
]
display(Markdown("| Field | Value |\n|---|---|\n" + "\n".join(f"| {k} | {v} |" for k, v in facts)))

passport = fp["research_passport"]
cost = passport["cost_model"]
provenance = pd.DataFrame([
    ("Weighting", passport["weighting_method"]),
    ("Rebalancing", passport["rebalance_rule"]),
    ("Costs", f"returns are {cost['gross_or_net']} of costs (cost model `{cost['cost_model_version']}`)"),
    ("Test type", passport["test_type"]),
    ("Point in time", passport["point_in_time_status"]),
    ("Out-of-sample status", f"evidence: {passport['source_evidence_oos_status']}; this surface: "
                             f"{passport['surface_oos_status']}"),
    ("Benchmark", passport["benchmark_id"]),
    ("Universe version", passport["universe_version"]),
], columns=["research passport", "value"])
display(provenance.style.hide(axis="index"))
display(Markdown(f"> *{fp['disclosure']}*"))

# %% [markdown]
# **Raw preview.** `to_frame` flattens each factor record. The nested `stats`
# and `holdings_metrics` objects become dotted columns such as `stats.sharpe`.
# Three columns still hold lists: `return_series`, `top_holdings` and
# `distribution_series`. We show their lengths here and unpack them below.
# (`distribution_series` has been an empty list in every response seen so
# far; the daily returns are in `return_series`.)

# %%
factors_raw = to_frame(fp_payload, "factor_portfolios")
LIST_COLS = ["return_series", "top_holdings", "distribution_series"]
preview = factors_raw.copy()
for col in LIST_COLS:
    if col in preview:
        preview[col] = preview[col].map(lambda v: f"[{len(v)} items]" if isinstance(v, list) else v)
print(f"{len(factors_raw)} factor records, {factors_raw.shape[1]} columns after flattening.")
preview.head(7)

# %% [markdown]
# ### 3.1 Cleaning the factor records, and what each factor is
#
# 1. **Keep the documented columns.** `pick` raises a `KeyError` if one is
#    missing, because that would be a contract change.
# 2. **Coerce numbers** with `pd.to_numeric(errors="coerce")`: the statistics,
#    the counts and the scores.
# 3. **De-duplicate on `factor_id`**, the natural key.
# 4. **Order the factors** as the API's `contract_factors` list does, so every
#    table and chart reads ERP → LIQ.
# 5. **Name them.** `factor_name_published` is `SMB_FF3` for size (the
#    Fama–French three-factor version), so we keep the part before `_` as a
#    short code.
# 6. **Check `effective_sign`.** 1 means the factor runs in its usual
#    direction. The API does not document −1, but it would most likely mean
#    SurgeFlow flipped the factor (the legs swapped), so you would read its
#    returns with the opposite meaning. Every factor showed 1 when this
#    notebook was written.
# 7. **Sum up the gates.** `verdict` turns `publish_state` and `gate_reason`
#    into one phrase per factor (section 3.2 explains the gates).

# %%
IDENTITY = ["factor_id", "factor_label", "factor_name_published", "side_displayed", "effective_sign",
            "semantic_label"]
GATE_COLS = ["publish_state", "evidence_status", "gate_reason", "agreement_score", "is_risk_ready",
             "risk_ready_reason"]
HOLDING_META = ["n_holdings_active_leg", "holdings_as_of", "holdings_weighting", "holdings_preview_count",
                "holdings_complete", "benchmark_id", "benchmark_name", "constituent_source", "return_construction"]
HOLDING_METRICS = [f"holdings_metrics.{k}" for k in ("ep_mcap_weighted", "dy_mcap_weighted", "tot_market_cap",
                                                     "n_constituents_total", "n_constituents_with_mcap",
                                                     "n_constituents_with_ep", "n_constituents_with_dy")]
STAT_COLS = [f"stats.{k}" for k in STAT_KEYS]

factors = pick(factors_raw, IDENTITY + GATE_COLS + HOLDING_META + HOLDING_METRICS + STAT_COLS + LIST_COLS)
for col in STAT_COLS + HOLDING_METRICS + ["agreement_score", "effective_sign", "n_holdings_active_leg",
                                         "holdings_preview_count"]:
    factors[col] = pd.to_numeric(factors[col], errors="coerce")
n_before = len(factors)
factors = factors.drop_duplicates(subset="factor_id", keep="first")
contract_order = {fid: i for i, fid in enumerate(fp["contract_factors"])}
factors = (factors.assign(order=factors["factor_id"].map(contract_order))
           .sort_values("order", na_position="last").drop(columns="order").reset_index(drop=True))
factors["code"] = factors["factor_name_published"].str.split("_").str[0]
factors["name"] = factors["code"] + " · " + factors["factor_label"]
factors["n_returns"] = factors["return_series"].map(lambda v: len(v) if isinstance(v, list) else 0)
factors["verdict"] = [verdict(s, r) for s, r in zip(factors["publish_state"], factors["gate_reason"])]

NAME = dict(zip(factors["factor_id"], factors["name"]))      # 'smb' -> 'SMB · Size'
CODE = dict(zip(factors["factor_id"], factors["code"]))      # 'smb' -> 'SMB'
for fid in factors["factor_id"]:                             # a factor added to the contract gets the next free slot
    FACTOR_COLORS.setdefault(fid, SERIES[min(len(FACTOR_COLORS), len(SERIES) - 1)])

flipped = factors.loc[factors["effective_sign"] == -1, "code"].tolist()
print(f"De-duplication: {n_before} factor records -> {len(factors)}.")
print(f"Order: {' → '.join(factors['code'])}.")
print(f"Flipped factors (effective_sign = -1): {', '.join(flipped) if flipped else 'none'}.")

# %% [markdown]
# **Definitions: what the payload says each factor is.** Every factor record
# describes itself, published or not: a label, a published name, how it is
# built (`side_displayed`), its direction (`effective_sign`) and the data it
# rests on (`evidence_status`). Published factors also say how their return is
# constructed and weighted; blocked factors leave those fields null. The table
# puts the API's own fields next to the textbook legs from the introduction,
# which come from this notebook, not from the API.

# %%
definitions = pd.DataFrame({
    "code": factors["code"],
    "name (factor_label)": factors["factor_label"],
    "published as": factors["factor_name_published"],
    "built as (side_displayed)": factors["side_displayed"],
    "sign": factors["effective_sign"].map(lambda v: "–" if pd.isna(v) else f"{v:+.0f}"),
    "rests on (evidence_status)": factors["evidence_status"].map(lambda v: EVIDENCE.get(v, v)),
    "return construction": factors["return_construction"].fillna("– (withheld)"),
    "long leg (textbook)": factors["factor_id"].map(lambda f: TEXTBOOK_LEGS.get(f, ("?", "?"))[0]),
    "short leg (textbook)": factors["factor_id"].map(lambda f: TEXTBOOK_LEGS.get(f, ("?", "?"))[1]),
})
display(definitions.style.hide(axis="index"))

passport_defs = passport.get("factor_definitions") or []
if passport_defs:
    display(Markdown("The research passport also sends its own `factor_definitions`:"))
    display(pd.json_normalize(passport_defs))
else:
    print("research_passport.factor_definitions is empty in this release, so the factor records above "
          "are the API's definitions.")
print(f"Ranking variable (research_passport): {passport['ranking_variable']}.")

# %% [markdown]
# ### 3.2 Gate state: disclosed, not filtered
#
# Before SurgeFlow publishes a factor's returns and holdings, the factor must
# pass a set of statistical **gates**. Six kinds appear in `gate_reason`. The
# API sends only the codes; the questions below are our reading of the code
# names, not SurgeFlow documentation.
#
# | Test | Question it asks |
# |---|---|
# | 1 year of history | Are there at least 252 daily returns (one trading year)? |
# | Premium (HAC t-test) | Is the average return reliably different from zero, with errors that allow both for days of different size and for returns that are correlated from one day to the next (HAC)? |
# | Spanning alpha | Does it earn something the *other* factors cannot explain? |
# | Not redundant | Or do the other factors already explain it? |
# | Correlation triangle | Are its correlations with the other factors mutually consistent? |
# | Stock residuals | Do stock-level diagnostics look sane? |
#
# Each code in `gate_reason` names one test and one of two outcomes:
#
# - **failed**: the test ran and the factor did not pass (for example
#   `premium_not_significant_5pct`);
# - **pending**: the test has not run yet (`..._not_tested`), or there is not
#   yet enough history to run it (`factor_sample_below_252`). One code can
#   cover two tests: the redundancy check comes out of the same spanning
#   regression, so `spanning_not_tested` leaves both pending.
#
# Any code at all blocks the factor. The tables keep all seven rows: a factor
# missing from a chart below is missing *for the reason shown here*, not
# because of a bug.

# %%
gate_table = pd.DataFrame({
    "factor": factors["name"],
    "state": factors["publish_state"],
    "verdict": factors["verdict"],
    "risk-ready": factors["is_risk_ready"].map({True: "yes", False: "no"}),
    "agreement score": factors["agreement_score"],
    "return days": factors["n_returns"],
    "every gate reason, in plain English": factors["gate_reason"].map(explain_gates),
})
display(gate_table.style.format({"agreement score": "{:.2f}"}, na_rep="–").hide(axis="index")
        .set_properties(subset=["every gate reason, in plain English"],
                        **{"white-space": "normal", "min-width": "340px"}))

N_PUBLISHED = int((factors["n_returns"] > 0).sum())
states = ", ".join(f"{n} {state}" for state, n in factors["publish_state"].value_counts().items())
print(f"States: {states}. {N_PUBLISHED} of {len(factors)} factors carry a return series.")
counts = {"n_active": (fp["n_active"], int((factors["publish_state"] == "published").sum()), "published rows"),
          "n_risk_ready": (fp["n_risk_ready"], int(factors["is_risk_ready"].eq(True).sum()), "rows with is_risk_ready")}
for field, (sent, counted, rows_word) in counts.items():
    print(f"{field} = {sent}; {rows_word} above: {counted} -> "
          f"{'consistent' if sent == counted else 'DIFFERENT: read the counts with care'}.")

# Cross-check: raw_survivors_summary lists each factor's state a second time, keyed by its short code.
survivors = pick(pd.DataFrame(fp["raw_survivors_summary"]),
                 ["factor_name", "publish_state", "evidence_status", "effective_sign"])
both = factors[["code", "publish_state", "evidence_status", "effective_sign"]].merge(
    survivors, left_on="code", right_on="factor_name", how="outer", suffixes=("", " (summary)"), indicator=True)
mismatch = both[(both["_merge"] != "both")
                | (both["publish_state"] != both["publish_state (summary)"])
                | (both["evidence_status"] != both["evidence_status (summary)"])
                | (both["effective_sign"] != pd.to_numeric(both["effective_sign (summary)"], errors="coerce"))]
if mismatch.empty:
    print(f"raw_survivors_summary agrees with factors[] on state, evidence and sign for all {len(both)} factors.")
else:
    print(f"raw_survivors_summary disagrees with factors[] on {len(mismatch)} factors; factors[] is used below:")
    display(mismatch.drop(columns="_merge"))
if N_PUBLISHED == 0:
    note(f"All {len(factors)} factors are withheld in {MARKET_NAMES[MARKET]} today, so sections 3.3–3.11 "
         "print notes instead of charts. Section 4 shows whether another market publishes; set `MARKET` "
         "to that market and run the notebook again.")

# %% [markdown]
# **Chart: the gate checklist.** One row per factor and one column per test.
# A red ✕ is a failed test and a grey ○ a pending one. A green dot (✓ in the
# table) appears only for a **published** factor, which passed every test. For
# a withheld factor, a test with no code gets a small grey dot ("· not
# reported" in the table): the API listed no problem with it, but it does not
# say that the test ran. Each mark has its own symbol, so the chart still reads
# in black and white.

# %%
cells = []
for _, f in factors.iterrows():
    found = {}                                          # test -> (outcome, text); a failure outranks a pending check
    for code in gate_codes(f["gate_reason"]):
        tests_hit, outcome, text = gate_outcome(code)
        for test in tests_hit:
            if found.get(test, ("", ""))[0] != "failed":
                found[test] = (outcome, text)
    for test, (outcome, text) in found.items():
        cells.append({"factor_id": f["factor_id"], "factor": f["name"], "test": test, "outcome": outcome,
                      "detail": text})
    published = f["publish_state"] == "published"
    for test in GATE_TESTS:                             # no code for this test: passed only if the factor is published
        if test not in found:
            cells.append({"factor_id": f["factor_id"], "factor": f["name"], "test": test,
                          "outcome": "passed" if published else "unreported",
                          "detail": "passed (the factor is published)" if published else
                                    "no code reported; the API does not say whether this test ran"})
checklist = pd.DataFrame(cells)
tests = GATE_TESTS + sorted(set(checklist["test"]) - set(GATE_TESTS))      # 'Other' only for codes not seen before
rows = [f"{n}  ({v})" for n, v in zip(factors["name"], factors["verdict"])]
row_of = dict(zip(factors["name"], rows))


def wrap(text: str, width: int = 12) -> str:
    """Break a column label onto short lines for a Plotly axis."""
    return textwrap.fill(text, width).replace("\n", "<br>")


fig = go.Figure()
for outcome, (label, symbol, color, size) in GATE_STYLE.items():
    part = checklist[checklist["outcome"] == outcome]
    if part.empty:
        continue
    fig.add_trace(go.Scatter(
        x=part["test"].map(wrap), y=part["factor"].map(row_of), mode="markers", name=label,
        marker=dict(symbol=symbol, color=color, size=size,
                    line=dict(width=2.5 if outcome == "pending" else 0, color=color)),
        customdata=part[["detail", "test"]].to_numpy(),            # the unwrapped test name, for the hover
        hovertemplate="<b>%{y}</b><br>%{customdata[1]}: %{customdata[0]}<extra></extra>"))

groups = {v: [CODE[f] for f in factors.loc[factors["verdict"] == v, "factor_id"]] for v in VERDICTS}
n_f, n_pub = len(factors), len(groups["published"])
withheld = [c for v in VERDICTS[1:] for c in groups[v]]
n_fail = len(groups["failed a test"])
if n_pub == n_f:
    title = f"{MARKET_NAMES[MARKET]}: all {n_f} factors passed their gates and are published"
elif n_pub == 0:
    title = (f"{MARKET_NAMES[MARKET]}: all {n_f} factors are withheld; "
             + (f"{n_fail} failed a test, the other {n_f - n_fail} are pending" if 0 < n_fail < n_f else
                "every one failed at least one test" if n_fail == n_f else "none failed a test, all are pending"))
else:
    title = (f"{MARKET_NAMES[MARKET]}: {n_pub} of {n_f} factors are published; "
             f"{and_list(withheld)} {'is' if len(withheld) == 1 else 'are'} withheld")
subtitle = " · ".join(f"{v.capitalize()}: {and_list(groups[v])}" for v in VERDICTS if groups[v])
fig.update_layout(
    title=dict(text=title, subtitle=dict(text=subtitle)),
    height=230 + 46 * n_f, margin=dict(t=150, b=80, l=270, r=30), legend=BOTTOM_LEGEND, hovermode="closest",
    xaxis=dict(categoryorder="array", categoryarray=[wrap(t) for t in tests], side="top", showgrid=False,
               ticks="", tickangle=0, tickfont=dict(size=12, color=INK_2), range=[-0.6, len(tests) - 0.4]),
    yaxis=dict(categoryorder="array", categoryarray=rows, autorange="reversed", gridcolor=GRID, ticks="",
               range=[n_f - 0.5, -0.5]))
fig.show()

twin = (checklist.assign(mark=checklist["outcome"].map(GATE_MARK))
        .pivot(index="factor", columns="test", values="mark").reindex(index=factors["name"], columns=tests))
display(twin.rename_axis(index="factor", columns=None))

# %% [markdown]
# **How to read this.** The first table has one row per factor. `verdict`
# sums up its gates: *published*, *failed a test* (at least one test ran and
# failed), *under a year of history* (it cannot be tested yet), or *checks not
# yet run*. `return days` is how many daily returns the payload carries (0
# when withheld), and the last column spells out every code in `gate_reason`.
# The printed lines check the counts `n_active` and `n_risk_ready`, and the
# second listing in `raw_survivors_summary`, against those rows.
#
# In the checklist chart, read across a row to see what stands between that
# factor and publication. A row of grey circles and no red crosses is a factor
# that is waiting, not one that failed. A column full of grey circles is a test
# that SurgeFlow has not run for any factor yet. The table under the chart is
# the same grid in text.
#
# **Caveats.**
#
# - A blocked factor is not a "bad" factor. Often it simply has less than one
#   trading year of history so far, or a check has not run yet.
# - "No code reported" is not the same as "passed". For a blocked factor the
#   API lists the reasons it is blocked; it does not say which other tests were
#   run. That is why only published factors get a green ✓.
# - A published factor passed SurgeFlow's gates on in-sample evidence. That
#   makes it worth studying; it does not make it profitable in future.
# - `agreement_score` (0–1) is part of the gate evidence, but its exact formula
#   is not documented. Use it only to compare factors within one release.

# %% [markdown]
# ### 3.3 Cleaning the return series: from nested lists to one aligned table
#
# Each published factor carries `return_series`: a list of `{date, ret}`
# points, one per trading day. `ret` should be a **decimal** (0.01 = +1%), like
# every return fraction in this API. Live responses have carried empty lists
# so far (every factor was blocked), so the shape of these points and their
# unit are **not yet confirmed live**. The same is true of `top_holdings`
# (section 3.11) and `aggregate.factor_correlation` (section 3.8). The units
# check below is there to catch a surprise. We turn the lists into one **long**
# table (factor, date, ret) and then into one **wide** table: one row per
# date, one column per factor.
#
# Cleaning, in the open:
#
# 1. `pd.to_numeric(errors="coerce")` on `ret`: unreadable values become NaN.
# 2. UTC parsing of `date`. These are trading-session dates, not instants, so
#    we drop the time-zone label after parsing (Plotly draws plain dates more
#    reliably).
# 3. Drop rows whose date or return is missing, and count them.
# 4. **Units check, on the raw values.** For a factor, the typical (median)
#    absolute daily move should be well under 1% (0.01). If it is above 2%,
#    the API has almost certainly switched to percent (0.3 meaning 0.3%), and
#    the cell stops with a clear error. It must run *before* step 5: otherwise
#    the ±50% filter would quietly cut every percent-sized day and leave a
#    truncated series.
# 5. Flag impossible values. A daily factor return beyond ±`MAX_ABS_DAILY`
#    (50%) is almost certainly a data error, such as 5 (meaning 5%) sent where
#    0.05 was expected. We drop and count them.
# 6. De-duplicate on the natural key **(factor_id, date)**, keeping the last copy.
# 7. Pivot to the wide table. The pivot is an **outer join**: its rows are all
#    dates on which *any* factor has a return. A factor with no return on such
#    a date gets NaN. That NaN is a **gap**.

# %%
points = pd.DataFrame(
    [{"factor_id": fid, "date": p["date"], "ret": p["ret"]}       # p["ret"] raises if the key disappears
     for fid, series in zip(factors["factor_id"], factors["return_series"]) for p in (series or [])],
    columns=["factor_id", "date", "ret"])
n_raw = len(points)
points["ret"] = pd.to_numeric(points["ret"], errors="coerce")
points["date"] = pd.to_datetime(points["date"], utc=True, errors="coerce").dt.tz_localize(None)
missing = points["ret"].isna() | points["date"].isna()
points = points[~missing]


def units_check(ret: pd.Series, where: str) -> float:
    """Median absolute daily return of the raw values. Above MAX_TYPICAL_DAILY it is percent, not decimals: stop."""
    typical = float(ret.abs().median()) if len(ret) else np.nan
    if typical > MAX_TYPICAL_DAILY:
        raise ValueError(f"{where}: the typical (median) absolute daily return is {typical:.4g}. That looks like "
                         "percent (0.3 = 0.3%), not decimals (0.003 = 0.3%): the API's unit has changed. Check the "
                         "API docs before going on; the ±50% filter would otherwise cut the series.")
    return typical


typical = units_check(points["ret"], f"{MARKET_NAMES[MARKET]} return_series")      # before the ±50% filter
wild = points["ret"].abs() > MAX_ABS_DAILY
points = points[~wild]
n_dupes = int(points.duplicated(subset=["factor_id", "date"]).sum())
points = points.drop_duplicates(subset=["factor_id", "date"], keep="last").sort_values(["factor_id", "date"])

IDS = [fid for fid in factors["factor_id"] if fid in set(points["factor_id"])]     # published, in contract order
returns = points.pivot(index="date", columns="factor_id", values="ret").reindex(columns=IDS)
returns.columns.name = None
HAVE_RETURNS = len(IDS) > 0

print(f"{n_raw:,} return points from {plural(N_PUBLISHED, 'factor')}.")
print(f"Dropped: {int(missing.sum())} with a missing or unreadable date/return, {int(wild.sum())} beyond "
      f"±{MAX_ABS_DAILY:.0%} in one day, {n_dupes} duplicate (factor, date) rows.")
print(f"Wide table: {returns.shape[0]} dates × {returns.shape[1]} factors.")
if HAVE_RETURNS:
    print(f"Units check (raw values, before the ±{MAX_ABS_DAILY:.0%} filter): the typical (median) absolute daily "
          f"return is {typical:.2%}, below the {MAX_TYPICAL_DAILY:.0%} that would mean percent, so `ret` is a decimal.")
returns.head()

# %% [markdown]
# **Gaps and the NaN policy.** Two different things can make a date look
# "missing":
#
# - **A market holiday.** No factor has a return because the market was
#   closed. That is not a gap. The date has no row at all, and we must not
#   invent one: a zero-return row on a holiday would make the factor look
#   calmer than it is.
# - **A real gap.** Other factors have a return on that date and this one does
#   not, or a factor starts later or stops earlier than the others.
#
# Our policy, counted below:
#
# - **Never fill a missing return with 0, and never forward-fill a return.** A 0
#   claims the factor did not move. Forward-filling repeats yesterday's move
#   (section 4.1 shows how much damage that does). Forward-filling an index
#   *level* over a holiday is fine, because the value really did not change.
# - **Each factor's own statistics use all of its own days**, as the API does.
# - **Comparisons between factors** (correlations, the equal-weight mix, the
#   regressions) use only the dates on which **every** published factor has a
#   return: the "complete-case" window. The API reports the same idea as
#   `aggregate.n_aligned_dates`.

# %%
if not HAVE_RETURNS:
    aligned = returns.copy()
    note("No published factor has a return series today, so there are no gaps to count.")
else:
    gap_rows = []
    for fid in IDS:
        s = returns[fid]
        first, last = s.first_valid_index(), s.last_valid_index()
        inside = s.loc[first:last]
        gap_rows.append({"factor": NAME[fid], "first date": f"{first:%Y-%m-%d}", "last date": f"{last:%Y-%m-%d}",
                         "days with a return": int(s.notna().sum()),
                         "gaps inside its span": int(inside.isna().sum()),
                         "dates before its start or after its end": int(s.isna().sum() - inside.isna().sum())})
    display(pd.DataFrame(gap_rows).style.hide(axis="index"))

    aligned = returns.dropna(how="any")              # the complete-case window
    print(f"Union calendar: {len(returns)} dates. Complete-case window: {len(aligned)} dates "
          f"({len(returns) - len(aligned)} dropped because at least one factor had no return).")
    print(f"The API's aggregate.n_aligned_dates is {agg['n_aligned_dates']}: "
          f"{'the same' if agg['n_aligned_dates'] == len(aligned) else 'different, so read comparisons with care'}.")
    breaks = returns.index.to_series().diff().dt.days.iloc[1:]
    if not breaks.empty:
        after = breaks.idxmax()
        before = returns.index[returns.index.get_loc(after) - 1]
        print(f"Longest break between sessions: {int(breaks.max())} calendar days ({before:%Y-%m-%d} → "
              f"{after:%Y-%m-%d}). Weekends give 3; more means a holiday, which is not a gap.")

# %% [markdown]
# **Winsorising: shown, not applied.** For heavy-tailed data, a common
# cleaning step is quantile clipping (winsorising). It pulls every value below
# the 1st percentile up to that percentile, and every value above the 99th
# down to it. Here the extreme days are not noise: they *are* the risk we want
# to measure. So we keep the raw returns everywhere, and use winsorising only as
# a **sensitivity check**: how much do the most extreme 2% of days drive each
# number?

# %%
if not HAVE_RETURNS:
    note("No returns to winsorise today.")
else:
    low, high = returns.quantile(0.01), returns.quantile(0.99)            # per factor
    clipped = returns.clip(lower=low, upper=high, axis=1)
    k = np.sqrt(TRADING_DAYS)
    sensitivity = pd.DataFrame({
        "factor": [NAME[f] for f in IDS],
        "days clipped": [int(((returns[f] < low[f]) | (returns[f] > high[f])).sum()) for f in IDS],
        "volatility, raw": (returns.std() * k).to_numpy(),
        "volatility, winsorised": (clipped.std() * k).to_numpy(),
        "mean a year, raw": (returns.mean() * TRADING_DAYS).to_numpy(),
        "mean a year, winsorised": (clipped.mean() * TRADING_DAYS).to_numpy(),
    })
    cut = 1 - sensitivity["volatility, winsorised"] / sensitivity["volatility, raw"]
    display(sensitivity.style.format({c: "{:.1%}" for c in sensitivity.columns[2:]}).hide(axis="index"))
    n_lo, n_hi = int(sensitivity["days clipped"].min()), int(sensitivity["days clipped"].max())
    days = plural(n_hi, "day") if n_lo == n_hi else f"{n_lo} to {n_hi} days"
    by = f"{cut.min():.0%}" if f"{cut.min():.0%}" == f"{cut.max():.0%}" else f"{cut.min():.0%} to {cut.max():.0%}"
    print(f"Clipping {days} per factor lowers volatility by {by}"
          + (": a handful of extreme days carries a visible share of the risk." if cut.max() > 0.05 else
             ": the extreme days do not drive the volatility much."))

# %% [markdown]
# ### 3.4 Check: can we reproduce the API's statistics?
#
# The `stats` block summarises `return_series`, so we should be able to
# recompute every number from the series. The field names say what each one
# is; `risk_stats` uses the standard definitions:
#
# | Field | Definition |
# |---|---|
# | `mean_annual` | Average daily return × 252 (an arithmetic mean) |
# | `vol_annual` | Standard deviation of daily returns (with n − 1) × √252 |
# | `sharpe` | `mean_annual` ÷ `vol_annual`. No risk-free rate is subtracted: ERP is already an excess return, and a 50/50 long-short portfolio pays for its longs with its shorts |
# | `max_dd` | The lowest value of (value ÷ running peak − 1); always ≤ 0 |
# | `var_95_252d` | Minus the 5th percentile of daily returns: a positive loss |
# | `es_95_252d` | Minus the average of the returns at or below that percentile |
#
# Small differences are expected if `ret` arrives rounded while `stats` is
# computed before rounding. (No live response has carried a return series yet,
# so how many decimals `ret` keeps is not confirmed.) A difference far beyond
# the tolerance means a definition differs: for example a different quantile
# rule for VaR, or a risk-free rate subtracted in `sharpe`.

# %%
TOLERANCE = {"n_obs": 0, "mean_annual": 5e-4, "vol_annual": 5e-4, "sharpe": 5e-3, "max_dd": 5e-4,
             "var_95_252d": 5e-4, "es_95_252d": 5e-4}
if not HAVE_RETURNS:
    note("No published factor today, so there are no statistics to check.")
else:
    ours = pd.DataFrame({fid: risk_stats(returns[fid], level=0.95) for fid in IDS}).T.astype(float)  # API: 95%
    api = factors.set_index("factor_id").loc[IDS, STAT_COLS].set_axis(STAT_KEYS, axis=1)
    check = pd.DataFrame({"statistic": STAT_KEYS,
                          "largest |API − ours|": [float((api[k] - ours[k]).abs().max()) for k in STAT_KEYS],
                          "tolerance": [TOLERANCE[k] for k in STAT_KEYS]})
    check["ok"] = check["largest |API − ours|"] <= check["tolerance"]
    display(check.style.format({"largest |API − ours|": "{:.6f}", "tolerance": "{:g}"}).hide(axis="index"))
    print("Every statistic reproduces." if check["ok"].all() else
          "Some statistics differ beyond rounding: the API may have changed a definition. Compare before you rely on them.")

# %% [markdown]
# ### 3.5 Chart: growth of 100
#
# To compare returns over time, we **compound** each factor's daily returns
# into the value of 100 invested at the start:
# value = 100 × (1 + r₁) × (1 + r₂) × … Each line starts at exactly 100 on the
# session before its first return, so a loss on the very first day shows up
# (in the chart and in the drawdowns of section 3.6). All the factors then
# share **one axis** in the same unit. A line at 110 means +10% since the
# start. If the factors start or end on different dates, the title ranks them
# over the window they all share, not on final values from different windows.

# %%
if not HAVE_RETURNS:
    level = returns.copy()
    note("No published factor has a return series today, so there is nothing to chart.")
else:
    level = 100 * (1 + returns).cumprod()       # cumprod skips NaN, so a gap leaves a break in the line
    # A base row of 100 on the session before each factor's first return, so a first-day loss is visible.
    # (risk_stats, like the API's max_dd, starts from the first day's close; it is left unchanged.)
    level = level.reindex(level.index.insert(0, returns.index[0] - pd.offsets.BDay(1)))
    for fid in IDS:
        level.loc[level.index[level.index.get_loc(returns[fid].first_valid_index()) - 1], fid] = 100.0
    final = level.ffill().iloc[-1]              # each factor's last level (carrying a level forward is fine)
    firsts = pd.Series({f: returns[f].first_valid_index() for f in IDS})
    lasts = pd.Series({f: returns[f].last_valid_index() for f in IDS})
    shared_from, shared_to = firsts.max(), lasts.min()
    same_window = firsts.nunique() == 1 and lasts.nunique() == 1
    if same_window or shared_from >= shared_to:
        rank = final                            # one window for all (or no overlap: then the title says so)
    else:                                       # rebase to the window every factor covers before ranking
        rank = 100 * (1 + returns.loc[shared_from:shared_to, IDS]).prod()
    best, worst = rank.idxmax(), rank.idxmin()
    lo_y, hi_y = float(np.nanmin(level.to_numpy())), float(np.nanmax(level.to_numpy()))
    pad = (hi_y - lo_y) * 0.06 + 0.5
    y_range = [lo_y - pad, hi_y + pad]
    HEIGHT, TOP, BOTTOM = 540, 115, 100

    fig = go.Figure()
    fig.add_hline(y=100, line=dict(color=AXIS, width=1), layer="below")
    for fid in IDS:
        fig.add_trace(go.Scatter(x=level.index, y=level[fid], mode="lines", name=NAME[fid],
                                 line=dict(color=FACTOR_COLORS[fid], width=2),
                                 hovertemplate=f"{CODE[fid]}: %{{y:.1f}}<extra></extra>"))
    ends = pd.DataFrame({"x": [level[f].last_valid_index() for f in IDS], "y": [final[f] for f in IDS],
                         "text": [f"{CODE[f]} {final[f]:.0f}" for f in IDS],
                         "color": [FACTOR_COLORS[f] for f in IDS]})
    add_end_labels(fig, ends, y_range, HEIGHT - TOP - BOTTOM)

    above = int((rank > 100).sum())
    start, end = level.index.min(), returns.index.max()
    if len(IDS) == 1:
        title = f"{NAME[best]} finished at {final[best]:.0f}"
    elif same_window:
        title = (f"{above} of {len(IDS)} factors finished above 100: {CODE[best]} led at {final[best]:.0f}, "
                 f"{CODE[worst]} trailed at {final[worst]:.0f}")
    elif shared_from < shared_to:
        title = (f"Over the window all {len(IDS)} share, {above} gained: {CODE[best]} led at {rank[best]:.0f}, "
                 f"{CODE[worst]} trailed at {rank[worst]:.0f}")
    else:
        title = f"The {len(IDS)} factors cover different windows, so their final values are not ranked"
    window = ("" if same_window else       # a second subtitle line when the windows differ
              f"<br>The factors start or end on different dates (section 3.3): the title ranks 100 invested over "
              f"{shared_from:%b %d, %Y} to {shared_to:%b %d, %Y}, the window all share; end labels show each line's "
              "own final value" if shared_from < shared_to else "<br>The factors' windows do not overlap")
    fig.update_layout(
        title=dict(text=title, subtitle=dict(
            text=f"Value of 100 invested in each published factor, {start:%b %d, %Y} to {end:%b %d, %Y} · "
                 f"daily compounding, before costs · ERP is measured in excess of cash{window}")),
        height=HEIGHT + (20 if window else 0), margin=dict(t=TOP + (20 if window else 0), b=BOTTOM, r=105),
        hovermode="x unified",
        legend=dict(BOTTOM_LEGEND, itemclick=False, itemdoubleclick=False),   # the end labels cannot hide with a line
        xaxis=dict(hoverformat="%b %d, %Y", range=[start - pd.Timedelta(days=2), end + pd.Timedelta(days=2)]),
        yaxis=dict(title="Value of 100 invested (index)", range=y_range))
    fig.show()
    monthly = level.groupby(level.index.to_period("M")).last().rename(columns=CODE)
    monthly.index = monthly.index.strftime("%Y-%m")
    display(monthly.rename_axis("month-end level").style.format("{:.1f}", na_rep="–"))

# %% [markdown]
# **How to read this.** Each line is one factor, in its fixed colour. The label
# at its right end gives its final value; the grey horizontal line marks 100
# (break-even). Hover to see every factor's value on one date. (The legend is
# for reference only: clicking it would hide a line but leave its end label
# behind, so it is switched off.) A steady climb
# means steady gains; a jagged line means large daily swings (section 3.7
# measures them). The table gives each factor's value at the end of each month.
#
# **Caveats.**
#
# - **Before costs.** The research passport says the returns are gross. A real
#   long-short portfolio pays trading costs and a fee to borrow the stocks it
#   sells short, so its returns would be lower, especially for factors that
#   trade a lot, such as momentum.
# - **Daily compounding** assumes the portfolio is reset to its weights every
#   day. The real rebalancing calendar is "factor-specific" (see the passport).
# - A long-short line at 105 means the *spread* between the two legs earned 5%
#   on the capital behind the position. ERP is the index minus cash, so a line
#   at 105 means the index beat cash by 5%.
# - One year is a short window. A different start date can change the ranking.

# %% [markdown]
# ### 3.6 Chart: drawdowns
#
# A **drawdown** is how far a portfolio sits below its own best value so far.
# It answers the question investors feel most: "how much did I lose from the
# top, and for how long?" We compute it from the same index levels:
# drawdown = level ÷ running peak − 1. Its lowest point is the **maximum
# drawdown**. It equals the API's `max_dd` except when the first day was a
# loss: the levels start from 100 the session before the first return, so they
# count that loss, while `max_dd` (and `risk_stats`) start from the first
# day's close. Each factor gets its own small panel, named in its title, and
# all the panels share one y-axis, so depths compare directly.

# %%
if not HAVE_RETURNS:
    note("No published factor has a return series today, so there are no drawdowns to chart.")
else:
    drawdown = level / level.cummax() - 1              # level includes the base row of 100 (section 3.5)
    rows, cols = grid_shape(len(IDS))
    fig = make_subplots(rows=rows, cols=cols, shared_xaxes="all", shared_yaxes="all",
                        subplot_titles=[NAME[f] for f in IDS], horizontal_spacing=0.04, vertical_spacing=0.14)
    fig.update_annotations(font=dict(size=13, color=INK))
    dd_rows = []
    for k, fid in enumerate(IDS):
        r, c = k // cols + 1, k % cols + 1
        s, lv = drawdown[fid].dropna(), level[fid].dropna()
        trough = s.idxmin()
        peak = lv.loc[:trough].idxmax()
        back = lv.loc[trough:]
        recovered = back[back >= lv.loc[peak]].first_valid_index()
        fig.add_trace(go.Scatter(x=s.index, y=s, mode="lines", name=NAME[fid], legendgroup=fid, showlegend=False,
                                 fill="tozeroy", fillcolor=rgba(INK_2, 0.12), line=dict(color=INK_2, width=1.5),
                                 hovertemplate=f"{CODE[fid]}: %{{y:.1%}} below its peak<extra></extra>"), row=r, col=c)
        fig.add_trace(go.Scatter(x=[trough], y=[s.min()], mode="markers+text", legendgroup=fid, showlegend=False,
                                 hoverinfo="skip", marker=dict(size=8, color=INK, line=dict(width=2, color=SURFACE)),
                                 text=[f"{s.min():.1%}"], textposition="bottom center", cliponaxis=False,
                                 textfont=dict(size=11, color=INK_2)), row=r, col=c)
        dd_rows.append({"factor": NAME[fid], "peak": f"{peak:%Y-%m-%d}", "trough": f"{trough:%Y-%m-%d}",
                        "max drawdown": s.min(), "trading days, peak to trough": int(lv.loc[peak:trough].size - 1),
                        "recovered on": f"{recovered:%Y-%m-%d}" if recovered is not None else "not yet",
                        "drawdown today": s.iloc[-1]})
    dd_table = pd.DataFrame(dd_rows)
    deep = dd_table.loc[dd_table["max drawdown"].idxmin()]
    shallow = dd_table.loc[dd_table["max drawdown"].idxmax()]
    title = (f"{deep['factor'].split(' · ')[0]} fell furthest from a peak ({deep['max drawdown']:.1%}); "
             f"{shallow['factor'].split(' · ')[0]}'s worst fall was {shallow['max drawdown']:.1%}"
             if len(IDS) > 1 else f"{deep['factor']}'s worst fall from a peak was {deep['max drawdown']:.1%}")
    fig.update_yaxes(tickformat=".0%", range=[float(dd_table["max drawdown"].min()) * 1.3, 0.004])
    fig.update_yaxes(title_text="Below peak (%)", col=1)
    label_lowest_panels(fig, [(k // cols + 1, k % cols + 1) for k in range(len(IDS))], rows, cols)
    hide_unused_panels(fig, len(IDS), rows, cols)
    fig.update_layout(title=dict(text=title, subtitle=dict(
                          text="Distance below each factor's running peak · dot = maximum drawdown · shared y-axis")),
                      height=250 * rows + 200, margin=dict(t=120, b=70), showlegend=False, hovermode="x")
    fig.show()
    display(dd_table.style.format({"max drawdown": "{:.1%}", "drawdown today": "{:.1%}"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Each panel is one factor. The shaded area shows how far
# the factor sits below its best value so far: 0% means a new high, and deeper
# means a bigger loss from the top. The dot marks the deepest point, the maximum
# drawdown. The table adds when each fall started and ended, and whether the
# factor has climbed back to its old peak.
#
# **Caveats.**
#
# - Maximum drawdown depends on the window. Over one year it can only see the
#   falls inside that year.
# - It comes from a single episode, so it is a noisy measure of risk. Two
#   factors with the same volatility can show very different drawdowns by luck.

# %% [markdown]
# ### 3.7 Chart: rolling volatility
#
# Volatility (the yearly size of daily swings) is not constant. A **rolling**
# volatility recomputes it every day from only the last `ROLL_DAYS` trading days
# (63 ≈ 3 months), so you can see calm and stormy stretches. We annualise it
# with √252 so it reads in the same unit as `vol_annual`. The dashed line in
# each panel is the whole-period figure, which is also printed in the panel
# title.

# %%
if not HAVE_RETURNS:
    note("No published factor has a return series today, so there is no volatility to chart.")
else:
    roll = pd.DataFrame({fid: returns[fid].dropna().rolling(ROLL_DAYS, min_periods=ROLL_DAYS).std()
                         * np.sqrt(TRADING_DAYS) for fid in IDS}).reindex(returns.index)
    full = returns.std() * np.sqrt(TRADING_DAYS)
    if roll.dropna(how="all").empty:
        note(f"Every series is shorter than ROLL_DAYS = {ROLL_DAYS} trading days. Lower ROLL_DAYS and run again.")
    else:
        rows, cols = grid_shape(len(IDS))
        fig = make_subplots(rows=rows, cols=cols, shared_xaxes="all", shared_yaxes="all",
                            subplot_titles=[f"{NAME[f]} · whole period {full[f]:.1%}" for f in IDS],
                            horizontal_spacing=0.04, vertical_spacing=0.14)
        fig.update_annotations(font=dict(size=13, color=INK))
        for k, fid in enumerate(IDS):
            r, c = k // cols + 1, k % cols + 1
            fig.add_trace(go.Scatter(x=roll.index, y=roll[fid], mode="lines", name=NAME[fid], showlegend=False,
                                     line=dict(color=INK_2, width=2),
                                     hovertemplate=f"{CODE[fid]}: %{{y:.1%}} a year<extra></extra>"), row=r, col=c)
            fig.add_hline(y=full[fid], line=dict(color=MUTED, width=1.2, dash="dash"), layer="below", row=r, col=c)
        swing = (roll.max() / roll.min()).dropna()
        most = swing.idxmax()
        title = (f"Risk is not constant: {CODE[most]}'s {ROLL_DAYS}-day volatility ranged from "
                 f"{roll[most].min():.1%} to {roll[most].max():.1%} a year")
        fig.update_yaxes(tickformat=".0%", rangemode="tozero")
        fig.update_yaxes(title_text="Volatility (% a year)", col=1)
        label_lowest_panels(fig, [(k // cols + 1, k % cols + 1) for k in range(len(IDS))], rows, cols)
        hide_unused_panels(fig, len(IDS), rows, cols)
        fig.update_layout(title=dict(text=title, subtitle=dict(
                              text=f"Standard deviation of the last {ROLL_DAYS} daily returns × √252 · "
                                   "dashed line = whole-period volatility · shared y-axis")),
                          height=250 * rows + 200, margin=dict(t=120, b=70), showlegend=False, hovermode="x")
        fig.show()
        vol_table = pd.DataFrame({"factor": [NAME[f] for f in IDS], "whole period": full[IDS].to_numpy(),
                                  "rolling low": roll[IDS].min().to_numpy(), "rolling high": roll[IDS].max().to_numpy(),
                                  "latest": roll[IDS].ffill().iloc[-1].to_numpy()})
        display(vol_table.style.format({c: "{:.1%}" for c in vol_table.columns[1:]}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Each panel shows one factor's volatility over the
# previous `ROLL_DAYS` trading days, expressed per year. The lines start late
# because the first window needs `ROLL_DAYS` days to fill. When a line climbs
# above its dashed whole-period line, the factor is in a stormier stretch than
# usual. ERP (the whole market) usually swings more than the long-short
# factors, because their two legs cancel much of the market's move.
#
# **Caveats.**
#
# - Neighbouring points share all but one day of their window, so the lines are
#   smooth by construction. Do not count each wiggle as a separate event.
# - Volatility treats a big gain as "risk" too. Section 3.9 looks only at losses.
# - Multiplying by √252 assumes that days are independent of each other.

# %% [markdown]
# ### 3.8 Chart: how the factors move together
#
# A **correlation** measures how two return series move together, from −1
# (always opposite) through 0 (unrelated) to +1 (always together). We compute
# it on the complete-case window, so every pair uses the same dates. Low or
# negative correlations are what make a mix of factors less risky than its
# parts (section 5.1).

# %%
if len(IDS) < 2:
    corr = pd.DataFrame()
    note("Fewer than two published factors today, so there is no correlation matrix.")
else:
    corr = aligned.corr()
    n_al = len(aligned)
    t_crit = stats.t.ppf(0.975, n_al - 2)
    r_crit = t_crit / np.sqrt(n_al - 2 + t_crit**2)        # |r| above this is significant at the 5% level
    codes = [CODE[f] for f in IDS]
    lower = corr.to_numpy().copy()
    lower[np.triu_indices_from(lower)] = np.nan             # keep the lower triangle, without the diagonal
    z = lower[1:, :-1]
    text = [["" if np.isnan(v) else signed(v) for v in row] for row in z]
    below = np.tril_indices(len(IDS), k=-1)                 # every pair once: (row, column) below the diagonal
    pairs = pd.Series(corr.to_numpy()[below], index=pd.MultiIndex.from_arrays([corr.index[below[0]],
                                                                              corr.columns[below[1]]]))
    strongest = pairs.abs().idxmax()
    n_sig = int((pairs.abs() > r_crit).sum())

    fig = go.Figure(go.Heatmap(
        z=z, x=codes[:-1], y=codes[1:], text=text, texttemplate="%{text}", textfont=dict(size=13),
        colorscale=DIVERGING, zmin=-1, zmax=1, zmid=0, xgap=2, ygap=2, hoverongaps=False,
        hovertemplate="%{y} vs %{x}: %{z:+.2f}<extra></extra>",
        colorbar=dict(title=dict(text="Correlation"), tickvals=[-1, -0.5, 0, 0.5, 1], len=0.85, thickness=14)))
    fig.update_layout(
        title=dict(text=f"{CODE[strongest[0]]} and {CODE[strongest[1]]} are the most linked ({signed(pairs[strongest])}); "
                        f"{n_sig} of {len(pairs)} pairs lie outside the ±{r_crit:.2f} noise band",
                   subtitle=dict(text=f"Correlation of daily returns over {n_al} aligned days · blue = move together, "
                                      "red = move opposite, grey ≈ unrelated")),
        height=150 + 66 * len(codes), margin=dict(t=110, l=70, r=40, b=60),
        xaxis=dict(side="bottom", showgrid=False, ticks="", constrain="domain"),
        yaxis=dict(autorange="reversed", showgrid=False, ticks="", scaleanchor="x", constrain="domain"))
    fig.show()
    display(corr.rename(index=CODE, columns=CODE).style.format(signed))

    api_corr = agg["factor_correlation"]
    if api_corr:
        api_c = pd.DataFrame(api_corr["values"], index=api_corr["factor_ids"], columns=api_corr["factor_ids"])
        common = [f for f in IDS if f in api_c.index]
        diff = float((api_c.loc[common, common] - corr.loc[common, common]).abs().to_numpy().max())
        print(f"Largest difference from the API's aggregate.factor_correlation ({len(common)} factors): {diff:.4f}"
              f"{' (rounding only)' if diff < 0.005 else ' - check the alignment window'}.")
    else:
        print("aggregate.factor_correlation is null today, so there is no API matrix to compare with.")

# %% [markdown]
# **How to read this.** Each cell is the correlation between the factor on its
# row and the factor on its column. Blue cells move together, red cells move in
# opposite directions, and pale grey cells are close to unrelated. The matrix is
# symmetric (HML vs CMA equals CMA vs HML), so we show only the lower half. The
# printed line checks our numbers against the API's own matrix.
#
# **Caveats.**
#
# - With about one year of data, any correlation inside the ±noise band in the
#   title cannot be told apart from zero at the 5% level.
# - Correlations drift over time, and they often jump towards ±1 in a crisis,
#   just when diversification is needed most.
# - A few extreme days can move a correlation a lot. A rank (Spearman)
#   correlation is a useful robustness check: `aligned.corr(method="spearman")`.

# %% [markdown]
# ### 3.9 Chart: tail risk, value at risk and expected shortfall
#
# Volatility describes typical days. **Tail risk** describes the bad ones. Two
# standard measures:
#
# - **VaR 95%** (value at risk): the loss that only the worst 5% of days exceed.
#   It says where the tail *starts*.
# - **ES 95%** (expected shortfall): the *average* loss on those worst 5% of
#   days. It says how bad the tail is, which VaR ignores.
#
# Both are daily, positive loss fractions (0.02 = a 2% loss), like the API's
# `var_95_252d` and `es_95_252d`. We also show the ES that a **normal** (bell
# curve) distribution with the same mean and volatility would give. If the
# real ES is clearly larger, the factor has **fat tails**: bad days are worse
# than the bell curve predicts. "Clearly" matters: the ES averages only about
# 13 days, so a ratio of 1.05 is well inside sampling noise. We count a factor
# only when its ES is more than `FAT_TAIL` (1.1×) the normal-curve ES, and the
# table adds a Jarque–Bera test of normality (a p-value below 0.05 rejects the
# bell curve).

# %%
if not HAVE_RETURNS:
    note("No published factor has a return series today, so there is no tail to measure.")
else:
    z_tail = stats.norm.ppf(1 - TAIL)                       # -1.645 at the 95% level
    FAT_TAIL = 1.1                                          # ES ÷ normal ES above this counts as a fatter tail
    tail_rows = []
    for fid in IDS:
        r = returns[fid].dropna()
        cutoff = r.quantile(1 - TAIL)
        mu, sd = r.mean(), r.std(ddof=1)
        tail_rows.append({"factor_id": fid, "factor": NAME[fid], "VaR": -cutoff, "ES": -r[r <= cutoff].mean(),
                          "days in the tail": int((r <= cutoff).sum()),
                          "VaR if normal": -(mu + z_tail * sd),
                          "ES if normal": -(mu - sd * stats.norm.pdf(z_tail) / (1 - TAIL)),
                          "skew": stats.skew(r, bias=False), "excess kurtosis": stats.kurtosis(r, bias=False),
                          "Jarque–Bera p": stats.jarque_bera(r).pvalue})
    tail = pd.DataFrame(tail_rows)
    tail["ES ÷ normal ES"] = tail["ES"] / tail["ES if normal"]
    tail = tail.sort_values("ES").reset_index(drop=True)            # biggest tail drawn at the top
    top = tail.iloc[-1]
    fat = tail["ES ÷ normal ES"] > FAT_TAIL
    n_fat = int(fat.sum())

    fig = go.Figure()
    for is_fat, label, color in ((True, f"Fatter tail: ES more than {FAT_TAIL:.1f}× the normal-curve ES",
                                  rgba(SERIES[0], 0.55)),
                                 (False, f"ES within {FAT_TAIL:.1f}× the normal-curve ES", AXIS)):
        part = tail[fat == is_fat]
        if part.empty:
            continue
        fig.add_trace(go.Bar(
            x=part["ES"], y=part["factor"], orientation="h", name=label, width=0.56, marker=dict(color=color),
            customdata=part[["days in the tail", "skew", "excess kurtosis", "ES ÷ normal ES"]].to_numpy(),
            hovertemplate=("<b>%{y}</b><br>Expected shortfall: %{x:.2%} a day (average of %{customdata[0]} worst "
                           "days)<br>%{customdata[3]:.2f}× the normal-curve ES · skew %{customdata[1]:+.2f} · "
                           "excess kurtosis %{customdata[2]:.1f}<extra></extra>")))
    fig.add_trace(go.Scatter(
        x=tail["VaR"], y=tail["factor"], mode="markers", name=f"VaR {TAIL:.0%}: where the worst {1 - TAIL:.0%} of days begin",
        marker=dict(symbol="line-ns", size=20, line=dict(width=3, color=INK)),
        hovertemplate="VaR: %{x:.2%}<extra>%{y}</extra>"))
    fig.add_trace(go.Scatter(
        x=tail["ES if normal"], y=tail["factor"], mode="markers", name="ES if returns followed a normal curve",
        marker=dict(symbol="diamond-open", size=11, color=INK_2, line=dict(width=2, color=INK_2)),
        hovertemplate="Normal-curve ES: %{x:.2%}<extra>%{y}</extra>"))
    fig.add_trace(go.Scatter(                                       # the ES value, just past the bar or the diamond
        x=tail[["ES", "ES if normal"]].max(axis=1), y=tail["factor"], mode="text", showlegend=False,
        text=["   " + pct(v, 2) for v in tail["ES"]], textposition="middle right", textfont=dict(size=12, color=INK_2),
        hoverinfo="skip", cliponaxis=False))
    title = (f"On its worst {1 - TAIL:.0%} of days, {top['factor'].split(' · ')[0]} lost {top['ES']:.2%} a day on "
             f"average; in this sample, {n_fat} of {len(tail)} lost over {FAT_TAIL - 1:.0%} more than a normal curve "
             "predicts")
    fig.update_layout(
        title=dict(text=title, subtitle=dict(
            text=f"Bars: expected shortfall ({TAIL:.0%}), the average daily loss on the worst "
                 f"{1 - TAIL:.0%} of days · tick: VaR · diamond: the normal-curve ES")),
        height=210 + 52 * len(tail), margin=dict(t=110, b=130, r=60), legend=BOTTOM_LEGEND,
        xaxis=dict(title="Daily loss (% of capital)", tickformat=".1%", rangemode="tozero",
                   range=[0, float(tail[["ES", "ES if normal"]].to_numpy().max()) * 1.2]),
        yaxis=dict(ticks="", categoryorder="array", categoryarray=tail["factor"].tolist()))
    fig.show()
    display(tail.drop(columns="factor_id").style.format(
        {"VaR": "{:.2%}", "ES": "{:.2%}", "VaR if normal": "{:.2%}", "ES if normal": "{:.2%}", "skew": "{:+.2f}",
         "excess kurtosis": "{:.1f}", "Jarque–Bera p": "{:.3f}", "ES ÷ normal ES": "{:.2f}×"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Each bar is one factor's expected shortfall: its
# average daily loss on its worst 5% of days, with the biggest at the top. The
# black tick is the VaR, the loss at which that worst 5% begins, so the bar
# always reaches past it. The open diamond is what a normal curve would predict.
# A blue bar reaches more than 10% past its diamond: the real bad days were
# clearly worse than the bell curve suggests. A grey bar is within 10%, which
# one year of data cannot tell apart from a bell curve. The table adds **skew**
# (negative: the big moves are mostly losses), **excess kurtosis** (above 0:
# fat tails) and the **Jarque–Bera p-value** (below 0.05: the returns are
# unlikely to come from a normal curve).
#
# **Caveats.**
#
# - At 95% with one year of data, the ES averages only about 13 days. One more
#   crash day would change it a lot.
# - The normal-curve benchmark uses the sample volatility, which fat tails
#   themselves inflate. That makes the diamonds a little generous, so the
#   ratio understates fat tails rather than overstating them.
# - These are one-day losses. A run of bad days (section 3.6) can lose far more.
# - The numbers describe the past year, before costs. Tails in the next year
#   can be fatter.

# %% [markdown]
# ### 3.10 Annualised return, volatility and a Sharpe-like ratio, with honest error bars
#
# Three yearly numbers summarise each factor:
#
# - **Mean (arithmetic)** = average daily return × 252. It is what the API
#   calls `mean_annual`.
# - **CAGR (compound annual growth rate)** = the yearly rate that turns 100
#   into the factor's final value: what the factor actually earned per year.
#   Two effects separate it from the arithmetic mean. Compounding (gains earn
#   gains) pushes it up. **Volatility drag** pulls it down by about
#   volatility² ÷ 2 a year, because a fall needs a bigger rise to recover
#   (−10% then +10% leaves you at 99). A good approximation:
#   CAGR ≈ e^(mean − volatility² ÷ 2) − 1.
# - **Sharpe-like ratio** = mean ÷ volatility: return per unit of risk. We call
#   it "Sharpe-*like*" because no risk-free rate is subtracted from the
#   long-short factors and because the returns are before costs.
#
# **How precise is a Sharpe-like ratio?** Not very. Its standard error is about
# 1 ÷ √(years of data), so with one year the 95% interval is roughly ±2. We
# compute it with `sharpe_interval`, which also allows for skew and fat tails.
# We also test whether the average return differs from zero with a **HAC
# t-statistic**. HAC (heteroskedasticity- and autocorrelation-consistent,
# Newey–West) standard errors stay honest in two situations: when some days
# are bigger than others (including calm and stormy spells), and when returns
# are correlated from one day to the next, a move that tends to carry on or to
# reverse. The plain t-test assumes neither. SurgeFlow's own gates run the same
# kind of test (see the gate code `premium_hac_not_tested`). A t-statistic grows with √years, so the last column
# says roughly how many years of data you would need for t ≈ 2 at today's ratio.

# %%
if not HAVE_RETURNS:
    note("No published factor has a return series today, so there is nothing to annualise.")
else:
    score_rows = []
    for fid in IDS:
        r = returns[fid].dropna()
        years = len(r) / TRADING_DAYS
        s = risk_stats(r)
        sr, se, lo, hi = sharpe_interval(r)
        test = hac_test(r)
        score_rows.append({
            "factor_id": fid, "factor": NAME[fid], "days": len(r),
            "mean a year": s["mean_annual"], "CAGR": (1 + r).prod() ** (1 / years) - 1,
            "volatility a year": s["vol_annual"], "volatility drag": s["vol_annual"] ** 2 / 2,
            "Sharpe-like": sr, "standard error": se,
            "95% low": lo, "95% high": hi, "HAC t": test["t"], "p-value": test["p"],
            "years for t ≈ 2": (2 / abs(sr)) ** 2 if sr != 0 else np.inf, "max drawdown": s["max_dd"]})
    score = pd.DataFrame(score_rows)
    years_used = score["days"].median() / TRADING_DAYS
    clear = score[(score["95% low"] > 0) | (score["95% high"] < 0)]

    fig = go.Figure()
    fig.add_vline(x=0, line=dict(color=AXIS, width=1), layer="below")
    excludes = score["factor_id"].isin(clear["factor_id"])
    for is_clear, label, color in ((True, "95% interval excludes 0", SERIES[0]),
                                   (False, "Cannot be told from 0", INK_2)):
        part = score[excludes == is_clear]
        if part.empty:
            continue
        fig.add_trace(go.Scatter(
            x=part["Sharpe-like"], y=part["factor"], mode="markers+text", name=label,
            marker=dict(size=11, color=color, line=dict(width=2, color=SURFACE)),
            error_x=dict(type="data", symmetric=False, array=part["95% high"] - part["Sharpe-like"],
                         arrayminus=part["Sharpe-like"] - part["95% low"], color=color, thickness=2, width=0),
            text=part["Sharpe-like"].map(signed), textposition="top center", textfont=dict(size=11, color=INK_2),
            customdata=part[["95% low", "95% high", "HAC t", "p-value"]].to_numpy(),
            hovertemplate=("<b>%{y}</b><br>Sharpe-like ratio %{x:+.2f}<br>95% interval %{customdata[0]:+.2f} to "
                           "%{customdata[1]:+.2f}<br>HAC t %{customdata[2]:+.2f} (p = %{customdata[3]:.2f})"
                           "<extra></extra>")))
    span = "one year" if abs(years_used - 1) < 0.05 else f"{years_used:.1f} years"
    title = (f"With {span} of data, no Sharpe-like ratio is clearly different from zero: every interval crosses 0"
             if clear.empty else
             f"With {span} of data, only {len(clear)} of {len(score)} Sharpe-like ratios are clearly different "
             "from zero")
    fig.update_layout(
        title=dict(text=title, subtitle=dict(
            text="Dot: yearly mean ÷ yearly volatility, before costs · whisker: 95% interval "
                 "(Mertens standard error, about ±2 ÷ √years)")),
        height=190 + 58 * len(score), margin=dict(t=110, b=110, r=40), legend=BOTTOM_LEGEND, showlegend=True,
        xaxis=dict(title="Sharpe-like ratio (yearly)", zeroline=False),
        yaxis=dict(ticks="", categoryorder="array", categoryarray=score["factor"].tolist()[::-1]))   # ERP at the top
    fig.show()
    display(score.drop(columns="factor_id").style.format({
        "mean a year": "{:+.1%}", "CAGR": "{:+.1%}", "volatility a year": "{:.1%}", "volatility drag": "{:.2%}",
        "Sharpe-like": "{:+.2f}",
        "standard error": "{:.2f}", "95% low": "{:+.2f}", "95% high": "{:+.2f}", "HAC t": "{:+.2f}",
        "p-value": "{:.2f}", "max drawdown": "{:.1%}",
        "years for t ≈ 2": lambda v: "more than 100" if v > 100 else f"{v:.0f}"}).hide(axis="index"))
    print(f"HAC t-statistics use {hac_test(returns[IDS[0]])['lags']} Newey-West lags.")

# %% [markdown]
# **How to read this.** Each dot is a factor's Sharpe-like ratio; the whisker
# is its 95% interval. A grey whisker crosses the zero line: the data cannot
# tell that factor's true ratio apart from zero. A blue one stays clear of it. The table adds the
# arithmetic mean, the CAGR and the volatility drag between them (largest for
# the most volatile factor), the HAC t-statistic and its p-value, and the years
# of data you would need for t ≈ 2 at the current ratio.
#
# **Caveats.**
#
# - **One year is very little.** Even a true Sharpe ratio of 0.5, which is good
#   for a factor, needs about 16 years of data to reach t ≈ 2.
# - **Before costs and before borrowing fees.** Real returns would be lower.
# - **In-sample.** The passport says the evidence is in-sample: these
#   portfolios were defined, gated and measured on the same history.
# - **Selection.** Only factors that passed their gates carry data, and seven
#   factors in four markets is 28 tries. By luck alone, some ratios look good.
# - The interval assumes independent days. The HAC t-statistic relaxes that,
#   so trust it when the two disagree.

# %% [markdown]
# ### 3.11 Chart: what the focus factor holds, with signed weights
#
# `top_holdings` is a **preview** of a factor's portfolio, not the whole thing:
# `holdings_preview_count` rows in total (split between the two legs), out of
# `n_holdings_active_leg` names in each leg. Only published factors carry it;
# a blocked factor's list is empty. Like `return_series`, its item shape has
# not been confirmed live yet (every live list so far was empty). Each row has:
#
# - `weight`: the **signed** share of capital. The disclosure and the passport
#   both say the long-short factors are "+50% convention-long and −50%
#   convention-short with equal-weighted legs". So each long name gets
#   +0.5 ÷ n and each short name −0.5 ÷ n, where n is the number of names per
#   leg. The full long leg adds up to +50% of capital and the full short leg to
#   −50%: the net exposure is zero and the gross exposure (longs plus shorts,
#   ignoring signs) is 100%.
# - `leg_weight`: the weight inside its own leg, 1 ÷ n.
# - `signal_value`: the ranking signal that put the stock in its leg. The API
#   does not state its unit, so we read only its direction (high or low). The
#   chart switches to a log axis when a signal is positive and spans more than
#   a factor of 100 (a size signal sent as raw market cap would).
#
# For ERP the "leg" is `index` and the weights are the index's own weights,
# all positive. The cleaning cell checks every one of these rules.

# %%
by_id = factors.set_index("factor_id")
with_holdings = [f for f in by_id.index if isinstance(by_id.at[f, "top_holdings"], list) and by_id.at[f, "top_holdings"]]
if FOCUS_FACTOR in with_holdings:
    focus = FOCUS_FACTOR
else:
    focus = next((f for f in with_holdings if f != "erp"), with_holdings[0] if with_holdings else None)
    state = by_id.at[FOCUS_FACTOR, "verdict"] if FOCUS_FACTOR in by_id.index else "not in the payload"
    print(f"{FOCUS_FACTOR.upper()} has no holdings in {MARKET_NAMES[MARKET]} today ({state})."
          + (f" Showing {CODE[focus]} instead." if focus else ""))

if focus is None:
    holdings_raw = pd.DataFrame()
    note(f"No factor in {MARKET_NAMES[MARKET]} carries holdings today (every top_holdings list is empty), "
         "so there is no portfolio to show.")
else:
    holdings_raw = pd.DataFrame(by_id.at[focus, "top_holdings"])
    print(f"Raw preview of {NAME[focus]}: {len(holdings_raw)} rows.")
holdings_raw.head() if not holdings_raw.empty else None

# %% [markdown]
# **Cleaning the holdings.** Keep the documented columns; keep `ticker` as a
# string (Hong Kong codes such as `"00700"` lose their leading zeros as numbers);
# coerce the numbers; de-duplicate on the natural key (leg, ticker); and map
# each leg to the shared `SIDE_COLORS`. Then check the weights against the rules
# above.

# %%
HOLD_COLS = ["leg", "ticker", "name", "sector", "market_cap", "latest_price", "weight", "leg_weight",
             "signal_value", "weight_source"]
hold = pick(holdings_raw, HOLD_COLS)
long_is_high = None
if focus is not None:
    hold["ticker"] = hold["ticker"].astype(str)
    for col in ["market_cap", "latest_price", "weight", "leg_weight", "signal_value"]:
        hold[col] = pd.to_numeric(hold[col], errors="coerce")
    n_before = len(hold)
    hold = hold.drop_duplicates(subset=["leg", "ticker"], keep="first").reset_index(drop=True)
    hold["side"] = hold["leg"].map(SIDE).fillna("HOLD")             # an unknown leg is shown in neutral grey
    meta = by_id.loc[focus]
    n_leg = int(meta["n_holdings_active_leg"])
    is_index = bool((hold["leg"] == "index").all())
    longs, shorts = hold[hold["leg"] == "long"], hold[hold["leg"] == "short"]
    print(f"De-duplication: {n_before} -> {len(hold)} rows. Unknown legs: {int((hold['side'] == 'HOLD').sum())}.")

    def yes(flag) -> str:
        return "yes" if flag else "no"

    checks = [("preview rows = holdings_preview_count", f"{meta['holdings_preview_count']:.0f}", f"{len(hold)}")]
    if is_index:
        checks += [("every weight = its leg_weight (index weights)", "yes",
                    yes(np.allclose(hold["weight"], hold["leg_weight"])))]
    else:
        checks += [
            ("leg_weight = 1 ÷ n_holdings_active_leg", f"{1 / n_leg:.6f}", f"{hold['leg_weight'].median():.6f}"),
            ("every long weight = +0.5 × leg_weight", "yes",
             yes(np.allclose(longs["weight"], 0.5 * longs["leg_weight"], atol=2e-6))),
            ("every short weight = −0.5 × leg_weight", "yes",
             yes(np.allclose(shorts["weight"], -0.5 * shorts["leg_weight"], atol=2e-6))),
            ("full long leg = n × weight", "+50.0%", f"{n_leg * longs['weight'].mean():+.1%}"),
            ("full short leg = n × weight", "-50.0%", f"{n_leg * shorts['weight'].mean():+.1%}"),
        ]
    checks = pd.DataFrame(checks, columns=["check", "expected", "found"])
    checks["ok"] = checks["expected"] == checks["found"]
    display(checks.style.hide(axis="index"))

    sig_label, sig_fmt, sig_noun = SIGNALS.get(focus, ("Signal value", ".2f", "signal values"))
    if not is_index and hold["signal_value"].notna().any():
        med_long, med_short = longs["signal_value"].median(), shorts["signal_value"].median()
        long_is_high = bool(med_long > med_short)
        textbook = TEXTBOOK_LONG_HIGH.get(focus)
        direction = ("" if textbook is None else " This matches the textbook direction." if long_is_high == textbook
                     else " This is the opposite of the textbook direction: check effective_sign in section 3.1.")
        print(f"Median signal ({sig_label}): long leg {format(med_long, sig_fmt)}, short leg "
              f"{format(med_short, sig_fmt)}. The long leg holds the {'high' if long_is_high else 'low'} end.{direction}")
    scope = "All index constituents" if is_index else "Both legs together"
    hm = {k.split(".", 1)[1]: meta[k] for k in HOLDING_METRICS}           # holdings_metrics, cleaned in 3.1

    def known(field: str) -> str:
        """'(EP known for 372 of 400)': how many constituents a cap-weighted average actually covers."""
        n_known, n_all = hm[f"n_constituents_with_{field}"], hm["n_constituents_total"]
        return "" if pd.isna(n_known) else f" ({field.upper()} known for {n_known:,.0f} of {n_all:,.0f})"

    print(f"{scope} ({hm['n_constituents_total']:,.0f} stocks): cap-weighted earnings yield "
          f"{pct(hm['ep_mcap_weighted'])}{known('ep')}, dividend yield {pct(hm['dy_mcap_weighted'])}{known('dy')}, "
          f"total market cap {money(hm['tot_market_cap'], CCY)} ({hm['n_constituents_with_mcap']:,.0f} with a cap).")
    coverage = fp["narrative_coverage"]
    print(f"narrative_coverage: {coverage['holdings_with_narrative']} of {coverage['holdings_total']} preview holdings "
          f"in this market carry a text narrative (coverage_pct = {coverage['coverage_pct']}).")

# %%
if focus is None:
    note("No holdings to chart today.")
else:
    has_signal = bool(hold["signal_value"].notna().any())
    show = hold.sort_values(["weight", "signal_value"], ascending=False).reset_index(drop=True)
    show["label"] = show["ticker"] + " · " + show["name"].map(lambda s: shorten(s, 24))
    sig = show["signal_value"].dropna()
    wide_signal = has_signal and bool((sig > 0).all()) and float(sig.max() / sig.min()) > 100   # log axis needed
    axis_label = ("Size signal (looks like market cap, log scale)" if wide_signal and focus == "smb" else
                  f"{sig_label}, log scale" if wide_signal else sig_label)
    right_title = axis_label if has_signal else f"Market cap ({CCY}, log scale)"
    money_dots = (wide_signal and focus == "smb") or not has_signal    # dots read as money: $ in hover and ticks

    def money_ticks(values) -> tuple:
        """Readable 1-2-5 ticks for a log axis of money values, such as $500B, $1T, $2T."""
        v = pd.Series(values).dropna()
        ticks = [m * 10.0**e for e in range(3, 16) for m in (1, 2, 5) if v.min() / 1.5 <= m * 10.0**e <= v.max() * 1.5]
        return ticks, [money(t, CCY, 0) for t in ticks]

    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, column_widths=[0.56, 0.44], horizontal_spacing=0.04,
                        subplot_titles=["Signed weight (% of capital)", right_title])
    fig.update_annotations(font=dict(size=13, color=INK))
    legend_name = {"LONG": "Long leg (bought)" if not is_index else "Index weight (bought)",
                   "SHORT": "Short leg (sold short)", "HOLD": "Other leg"}
    for side in ("LONG", "SHORT", "HOLD"):
        part = show[show["side"] == side]
        if part.empty:
            continue
        custom = np.column_stack([part["name"], part["sector"], part["market_cap"].map(lambda v: money(v, CCY)),
                                  part["latest_price"], part["leg_weight"]])
        fig.add_trace(go.Bar(
            x=part["weight"], y=part["label"], orientation="h", name=legend_name[side], legendgroup=side,
            marker=dict(color=SIDE_COLORS[side]), width=0.62, customdata=custom,
            hovertemplate=("<b>%{customdata[0]}</b> · %{customdata[1]}<br>Signed weight %{x:+.2%} "
                           "(%{customdata[4]:.2%} of its leg)<br>Market cap %{customdata[2]} · last price "
                           f"{SYMBOL[CCY]}%{{customdata[3]:,.2f}}<extra></extra>")), row=1, col=1)
        dot_x = part["signal_value"] if has_signal else part["market_cap"]
        dot_name = (("Size signal (looks like market cap)" if money_dots else sig_label) if has_signal
                    else "Market cap")
        fig.add_trace(go.Scatter(
            x=dot_x, y=part["label"], mode="markers", legendgroup=side, showlegend=False,
            marker=dict(size=10, color=SIDE_COLORS[side], line=dict(width=2, color=SURFACE)),
            customdata=dot_x.map(lambda v: money(v, CCY)).to_numpy()[:, None],
            hovertemplate=(f"%{{y}}<br>{dot_name}: %{{customdata[0]}}<extra></extra>" if money_dots else
                           f"%{{y}}<br>{dot_name}: %{{x:{sig_fmt}}}<extra></extra>")), row=1, col=2)
    reach = float(show["weight"].abs().max()) * 1.18
    fig.update_xaxes(tickformat=".1%", range=[0 if is_index else -reach, reach], zeroline=True,
                     zerolinecolor=AXIS, row=1, col=1)
    if money_dots:                              # market cap (or a size signal that is one): log axis, $ ticks
        ticks, labels = money_ticks(show["signal_value"] if has_signal else show["market_cap"])
        fig.update_xaxes(type="log", tickvals=ticks, ticktext=labels, row=1, col=2)
    elif wide_signal:
        fig.update_xaxes(type="log", row=1, col=2)
    else:
        fig.update_xaxes(tickformat=sig_fmt, row=1, col=2)
    fig.update_yaxes(categoryorder="array", categoryarray=show["label"].tolist()[::-1], ticks="")

    if is_index:
        title = (f"{CODE[focus]} holds the {meta['benchmark_name']} at index weights; these {len(show)} names make "
                 f"up {show['weight'].sum():.0%} of it")
    else:
        w = float(longs["weight"].mean())
        if long_is_high is None:
            title = f"{CODE[focus]} holds each name at ±{w:.2%} of capital"
        else:
            buy, sell = ("highest", "lowest") if long_is_high else ("lowest", "highest")
            title = f"{CODE[focus]} buys the {buy} {sig_noun} and shorts the {sell}, at ±{w:.2%} of capital each"
    fig.update_layout(
        title=dict(text=title, subtitle=dict(
            text=f"{NAME[focus]} · preview of {len(longs) or len(show)} of the {n_leg:,} names "
                 f"{'in the index' if is_index else 'in each leg'} · holdings as of {meta['holdings_as_of']} · "
                 "bars: signed weight · "
                 f"dots: {'the ranking signal' if has_signal else 'market cap'}")),
        height=170 + 27 * len(show), margin=dict(t=120, b=90, l=230), legend=BOTTOM_LEGEND, bargap=0.3,
        showlegend=show["side"].nunique() > 1)            # one leg needs no legend: the title names it
    fig.show()
    display(show[["side", "ticker", "name", "sector", "weight", "leg_weight", "signal_value", "market_cap",
                  "latest_price"]].style.format({"weight": "{:+.3%}", "leg_weight": "{:.3%}", "signal_value": "{:.4g}",
                                                 "market_cap": lambda v: money(v, CCY),
                                                 "latest_price": lambda v: f"{SYMBOL[CCY]}{v:,.2f}"},
                                                na_rep="–").hide(axis="index"))

# %% [markdown]
# **How to read this.** Each row is one stock. In the left panel, bars to the
# right (blue) are bought and bars to the left (red) are sold short. In a
# long-short factor every bar has the same length, because each leg gives all
# its names equal weight. The right panel shows *why* each stock is in its leg:
# its ranking signal. The long dots and the short dots should sit at opposite
# ends; if they do not, the factor is flipped or the signal is mislabelled.
#
# **Caveats.**
#
# - This is a **preview**: `holdings_preview_count` rows in total, split
#   between the legs, out of `n_holdings_active_leg` names in each leg. Never
#   rebuild a factor's returns from it.
# - The holdings are the latest snapshot (`holdings_as_of`). The return series
#   covers a whole year in which the membership changed at every rebalance.
# - Equal weights give a tiny company the same weight as a giant, and small
#   stocks cost more to trade. That is one reason real-world factor returns
#   fall short of paper ones.
# - Short-selling is restricted or expensive in some markets (mainland China in
#   particular), so a short leg can be a research construct rather than
#   something an investor could hold.
# - The API does not state the unit of `signal_value`, and it differs by
#   factor. Compare dots within one chart, never across factors.
# - The cap-weighted yields in the printed line cover only the constituents
#   whose earnings or dividends are known (the counts in brackets).

# %% [markdown]
# ## 4. Four markets: who publishes what, and one factor across them
#
# *This section calls the same endpoint for the other three markets (3 more
# requests).* Each market builds its factors inside its own stock universe and
# on its own trading calendar. Comparing markets answers two questions: which
# factors pass their gates where, and whether one style paid everywhere or
# only locally. It also shows a practical cleaning problem: **the calendars do
# not line up**.
#
# The extra markets are optional, so we fetch them with `sf_try`: if one is
# unavailable, it prints a note and the section carries on with the others.
# The first table checks that all the markets come from the same build: the
# same `release_id` and the same factor-contract fingerprint.

# %%
fp_by_market = {MARKET: fp}
if COMPARE_MARKETS:
    for m in MARKETS:
        if m == MARKET:
            continue
        payload = sf_try(f"/api/v1/markets/{m}/factor-portfolios")
        if payload is None:                     # unavailable right now: sf_try already printed a note
            continue
        show_freshness(payload, f"{MARKET_NAMES[m]}:")
        fp_by_market[m] = payload["data"]["data"]
else:
    note("COMPARE_MARKETS is False, so this section uses only your own market.")

fetched = [m for m in MARKETS if m in fp_by_market]
releases = pd.DataFrame([{
    "market": f"{MARKET_NAMES[m]} ({m})",
    "as_of": fp_by_market[m]["as_of"] or "null",
    "published": f"{fp_by_market[m]['n_active']} of {len(fp_by_market[m]['factors'])}",
    "risk-ready": fp_by_market[m]["n_risk_ready"],
    "benchmark": fp_by_market[m]["research_passport"]["benchmark_id"],
    "release_id": fp_by_market[m]["release_id"],
    "contract fingerprint": str(fp_by_market[m]["factor_contract_sha256"])[:12] + "…",
} for m in fetched])
display(releases.style.hide(axis="index"))
same_release = releases["release_id"].nunique() == 1
same_contract = len({fp_by_market[m]["factor_contract_sha256"] for m in fetched}) == 1
print(f"{len(fetched)} markets fetched. Release: {'one build for all' if same_release else 'different builds'}; "
      f"factor contract: {'identical' if same_contract else 'different, so compare factors with care'}.")

# %% [markdown]
# **Chart: the gate state in every market.** One row per market and one column
# per factor. The marks reuse the language of the checklist in section 3.2: a
# green dot is published, a red ✕ failed a test, and a grey hourglass or
# circle is still pending (too little history, or checks not yet run).

# %%
grid = pd.DataFrame([{
    "market": MARKET_NAMES[m], "factor_id": f["factor_id"], "code": f["factor_name_published"].split("_")[0],
    "verdict": verdict(f["publish_state"], f["gate_reason"]), "reason": main_reason(f["gate_reason"]),
    "return days": len(f["return_series"] or [])} for m in fetched for f in fp_by_market[m]["factors"]])
codes_order = [c for c in factors["code"]] + sorted(set(grid["code"]) - set(factors["code"]))
market_rows = [MARKET_NAMES[m] for m in fetched]

fig = go.Figure()
for v, (label, sym, color) in VERDICT_STYLE.items():
    part = grid[grid["verdict"] == v]
    if part.empty:
        continue
    fig.add_trace(go.Scatter(
        x=part["code"], y=part["market"], mode="markers", name=label,
        marker=dict(symbol=sym, color=color, size=13 if v == "published" else 17,
                    line=dict(width=2.5 if sym.endswith("open") else 0, color=color)),
        customdata=part[["verdict", "reason", "return days"]].to_numpy(),
        hovertemplate=("<b>%{x} in %{y}</b>: %{customdata[0]}<br>%{customdata[2]} return days"
                       + ("" if v == "published" else "<br>Main reason: %{customdata[1]}") + "<extra></extra>")))

n_pairs, n_pub = len(grid), int((grid["verdict"] == "published").sum())
per_market = grid.assign(pub=grid["verdict"] == "published").groupby("market", sort=False)["pub"].sum()
everywhere = [c for c in codes_order if (grid.loc[grid["code"] == c, "verdict"] == "published").all()]
if n_pub == 0:
    n_fail = int((grid["verdict"] == "failed a test").sum())
    where = "in any market" if len(fetched) > 1 else f"in {MARKET_NAMES[fetched[0]]}"
    title = (f"No factor is published {where} today: {n_fail} of {n_pairs} failed a test, "
             f"{n_pairs - n_fail} are pending")
    subtitle = "Gate verdict of each factor in each market · hover a mark for its main reason"
elif len(fetched) == 1:
    title = (f"{MARKET_NAMES[fetched[0]]}: {n_pub} of {n_pairs} factors are published "
             "(set COMPARE_MARKETS = True to add the other markets)")
    subtitle = "Gate verdict of each factor · hover a mark for its main reason"
else:
    top = per_market[per_market == per_market.max()].index.tolist()
    none_in = per_market[per_market == 0].index.tolist()
    title = (f"{n_pub} of {n_pairs} factor-market pairs are published; most in {and_list(top)} "
             f"({per_market.max()} of {len(factors)}{' each' if len(top) > 1 else ''})"
             + (f", none in {and_list(none_in)}" if none_in else ""))
    subtitle = f"Gate verdict of each factor in each market · published in every market: {and_list(everywhere)}"
fig.update_layout(
    title=dict(text=title, subtitle=dict(text=subtitle)),
    height=200 + 52 * len(fetched), margin=dict(t=120, b=80, l=130, r=30), legend=BOTTOM_LEGEND,
    hovermode="closest",
    xaxis=dict(categoryorder="array", categoryarray=codes_order, side="top", showgrid=False, ticks="",
               tickfont=dict(size=13, color=INK), range=[-0.6, len(codes_order) - 0.4]),
    yaxis=dict(categoryorder="array", categoryarray=market_rows, autorange="reversed", gridcolor=GRID, ticks="",
               range=[len(market_rows) - 0.5, -0.5]))
fig.show()
display(grid.pivot(index="market", columns="code", values="verdict").reindex(index=market_rows, columns=codes_order)
        .rename_axis(index="market", columns=None))

# %% [markdown]
# **How to read this.** Read along a row to see one market's factors, and down
# a column to see one factor in every market. A column of green dots is a style
# you can compare across all the markets today; the table under the chart is
# the same grid in words. Hover over a mark for its main reason, chosen in this
# order: a failed test first, then missing history, then a check not yet run.
#
# **Caveats.**
#
# - Gate state can change from one release to the next. A factor that is
#   withheld today can be published tomorrow, and the other way round.
# - The gates run separately in each market, on that market's own history, so a
#   factor can pass in one market and fail in another.

# %% [markdown]
# **Cleaning each market's series.** `factor_series` repeats the steps from
# section 3.3 for one factor in one payload: numeric coercion, UTC date
# parsing, dropping missing values, the units check on the raw values,
# dropping impossible values, and de-duplicating on the date. It is written
# out here, not hidden in a helper, so you can check it. It also counts every
# row it drops, and the table below prints those counts for each market.

# %%
def factor_series(payload_data: dict, fid: str, where: str) -> tuple:
    """One factor's cleaned daily returns (decimals, indexed by session date) from a factor-portfolios payload,
    plus the number of rows dropped at each step."""
    rec = next((f for f in payload_data["factors"] if f["factor_id"] == fid), None)
    dropped = {"missing": 0, "impossible": 0, "duplicate": 0}
    if rec is None or not rec["return_series"]:
        return pd.Series(dtype=float), dropped
    s = pd.DataFrame([{"date": p["date"], "ret": p["ret"]} for p in rec["return_series"]], columns=["date", "ret"])
    s["ret"] = pd.to_numeric(s["ret"], errors="coerce")
    s["date"] = pd.to_datetime(s["date"], utc=True, errors="coerce").dt.tz_localize(None)
    dropped["missing"] = int(s.isna().any(axis=1).sum())
    s = s.dropna()
    units_check(s["ret"], where)                        # stops if the API sent percent (before the ±50% filter)
    dropped["impossible"] = int((s["ret"].abs() > MAX_ABS_DAILY).sum())
    s = s[s["ret"].abs() <= MAX_ABS_DAILY]
    dropped["duplicate"] = int(s.duplicated(subset="date").sum())
    s = s.drop_duplicates(subset="date", keep="last").sort_values("date")
    return s.set_index("date")["ret"], dropped


def why_withheld(payload_data: dict, fid: str) -> str:
    """Why a factor has no returns in one market: its verdict and its most decisive gate, in plain English."""
    rec = next((f for f in payload_data["factors"] if f["factor_id"] == fid), None)
    if rec is None:
        return "not in the payload: the factor is missing from this market's contract"
    return f"{verdict(rec['publish_state'], rec['gate_reason'])}: {main_reason(rec['gate_reason'])}"


CROSS = FOCUS_FACTOR
cleaned = {m: factor_series(fp_by_market[m], CROSS, f"{MARKET_NAMES[m]} {CROSS.upper()}") for m in fetched}
cross = {m: series for m, (series, _) in cleaned.items()}
live = [m for m in fetched if not cross[m].empty]
summary = pd.DataFrame([{
    "market": MARKET_NAMES[m], "state": "published" if m in live else "withheld",
    "days": len(cross[m]), "first": f"{cross[m].index.min():%Y-%m-%d}" if m in live else "–",
    "last": f"{cross[m].index.max():%Y-%m-%d}" if m in live else "–",
    "total return": (1 + cross[m]).prod() - 1 if m in live else np.nan,
    "volatility a year": cross[m].std() * np.sqrt(TRADING_DAYS) if m in live else np.nan,
    "dropped: missing / beyond ±50% / duplicate": " / ".join(str(n) for n in cleaned[m][1].values()),
    "reason if withheld": "" if m in live else why_withheld(fp_by_market[m], CROSS)} for m in fetched])
display(summary.style.format({"total return": "{:+.1%}", "volatility a year": "{:.1%}"}, na_rep="–")
        .hide(axis="index"))

# %%
if not live:
    published_somewhere = [c for c in codes_order if (grid.loc[grid["code"] == c, "verdict"] == "published").any()]
    note(f"{CROSS.upper()} is withheld in every fetched market today, so there is nothing to compare. "
         + (f"Factors published somewhere today: {and_list(published_somewhere)}. Set FOCUS_FACTOR to one of them."
            if published_somewhere else "No factor is published in any fetched market, so try again on another day."))
else:
    code = CODE.get(CROSS, CROSS.upper())
    rows, cols = grid_shape(len(fetched), max_cols=2)                 # one panel per fetched market
    titles = [f"{MARKET_NAMES[m]} · {(1 + cross[m]).prod() - 1:+.1%} over {plural(len(cross[m]), 'day')}"
              if m in live else f"{MARKET_NAMES[m]} · withheld today" for m in fetched]
    fig = make_subplots(rows=rows, cols=cols, shared_xaxes="all", shared_yaxes="all", subplot_titles=titles,
                        horizontal_spacing=0.05, vertical_spacing=0.14)
    fig.update_annotations(font=dict(size=13, color=INK))
    levels = {m: pd.concat([pd.Series([100.0], index=[cross[m].index[0] - pd.offsets.BDay(1)]),   # start at 100
                            100 * (1 + cross[m]).cumprod()]) for m in live}
    lo_y = min(float(v.min()) for v in levels.values())
    hi_y = max(float(v.max()) for v in levels.values())
    pad = (hi_y - lo_y) * 0.08 + 0.5
    filled = []
    for k, m in enumerate(fetched):
        r, c = k // cols + 1, k % cols + 1
        if m in live:
            lv = levels[m]
            filled.append((r, c))
            fig.add_trace(go.Scatter(x=lv.index, y=lv, mode="lines", name=MARKET_NAMES[m], legendgroup=m,
                                     line=dict(color=MARKET_COLORS[m], width=2),
                                     hovertemplate=f"{MARKET_NAMES[m]}: %{{y:.1f}}<extra></extra>"), row=r, col=c)
            fig.add_trace(go.Scatter(x=[lv.index[-1]], y=[lv.iloc[-1]], mode="markers", legendgroup=m,
                                     showlegend=False, hoverinfo="skip",
                                     marker=dict(size=8, color=MARKET_COLORS[m], line=dict(width=2, color=SURFACE))),
                          row=r, col=c)
            fig.add_hline(y=100, line=dict(color=AXIS, width=1), layer="below", row=r, col=c)
        else:
            # An empty panel has no data to anchor "x domain" coordinates, so place the note on the page
            # (paper coordinates) at the centre of the panel's own domain.
            panel_axes = fig.get_subplot(r, c)
            why, reason = why_withheld(fp_by_market[m], CROSS).split(": ", 1)
            reason = "<br>".join(textwrap.wrap(f"({reason})", 36))
            fig.add_annotation(text=f"Withheld: {why}<br>{reason}", xref="paper", yref="paper", showarrow=False,
                               x=float(np.mean(panel_axes.xaxis.domain)), y=float(np.mean(panel_axes.yaxis.domain)),
                               font=dict(size=12, color=MUTED))
    totals = pd.Series({m: (1 + cross[m]).prod() - 1 for m in live})
    shared_from = max(cross[m].index.min() for m in live)
    shared_to = min(cross[m].index.max() for m in live)
    same_window = len({(cross[m].index.min(), cross[m].index.max()) for m in live}) == 1
    if len(live) >= 2 and same_window:
        title = (f"{code} across markets: best in {MARKET_NAMES[totals.idxmax()]} ({totals.max():+.1%}), "
                 f"weakest in {MARKET_NAMES[totals.idxmin()]} ({totals.min():+.1%})")
        window = "Same window in every market · "
    elif len(live) >= 2 and shared_from < shared_to:
        # The markets start or end on different dates: rank them over the window they all cover.
        shared = pd.Series({m: (1 + cross[m].loc[shared_from:shared_to]).prod() - 1 for m in live})
        title = (f"{code} across markets, over the window all share: best in {MARKET_NAMES[shared.idxmax()]} "
                 f"({shared.max():+.1%}), weakest in {MARKET_NAMES[shared.idxmin()]} ({shared.min():+.1%})")
        window = f"Title ranked over {shared_from:%b %d, %Y} to {shared_to:%b %d, %Y}, the dates all markets cover · "
    elif len(live) >= 2:
        title = f"{code} is published in {len(live)} markets whose windows do not overlap, so they are not ranked"
        window = "No shared window · "
    elif len(fetched) == 1:
        title = (f"{code} in {MARKET_NAMES[live[0]]}: {totals.iloc[0]:+.1%} "
                 "(set COMPARE_MARKETS = True to add the other markets)")
    else:
        title = f"{code} is published only in {MARKET_NAMES[live[0]]} today ({totals.iloc[0]:+.1%})"
    if len(live) < 2:
        window = "One market only · "
    fig.update_yaxes(range=[lo_y - pad, hi_y + pad])
    fig.update_yaxes(title_text="Value of 100", col=1)
    fig.update_xaxes(type="date")                     # an empty panel cannot guess its axis type
    label_lowest_panels(fig, filled, rows, cols)
    hide_unused_panels(fig, len(fetched), rows, cols)
    fig.update_layout(title=dict(text=title, subtitle=dict(
                          text=f"{NAME.get(CROSS, code)}: value of 100 invested, each market on its own trading "
                               "calendar · line colour = market · before costs · shared axes"
                               f"<br>{window}panel titles: each market's own window")),
                      height=250 * rows + 210, margin=dict(t=140, b=80), hovermode="x", legend=BOTTOM_LEGEND,
                      showlegend=len(live) >= 2)              # one series needs no legend: the title names it
    fig.show()

# %% [markdown]
# **How to read this.** Each panel is one market, in its fixed market colour
# (from here on, line colour means market, not factor), with its total return
# over its own window in the panel title. When the markets' windows differ,
# the chart title ranks them over the dates they all cover instead. All the panels share both axes, so
# heights and dates compare directly. A panel that says "withheld today" is a
# market where this factor did not pass its gates; the panel prints why.
#
# **Caveats.**
#
# - Each market sorts its *own* stocks. "Value" in Japan and "value" in the US
#   are the same rule applied to very different universes.
# - The windows differ slightly: a market on holiday stops earlier (the `last`
#   column above).
# - Long-short returns are in local terms. Because the two legs are in the same
#   currency, the currency's own move largely cancels; ERP does not cancel.

# %% [markdown]
# ### 4.1 Different calendars: aligning returns across markets
#
# Markets close on different holidays. If we join the markets' series on the
# date (an outer join), each market gets NaN on the days when *another* market
# traded but it did not. Those NaNs are **holidays**, not gaps: as section 3.3
# says, a market holiday is not a gap. (A gap is a missing return on a day the
# market was open.) There are three ways to treat these holiday NaNs, and two
# are wrong:
#
# 1. **Right:** keep each market's statistics on its own trading days, and
#    compare markets only on the dates they share (the complete case).
# 2. **Wrong:** forward-fill the return. That repeats the previous day's move,
#    as if it happened twice.
# 3. **Wrong:** fill with 0. The total return survives, but the extra zero days
#    make the factor look calmer than it was.
#
# The table below measures the damage on the market with the most holidays
# inside its span.

# %%
if len(live) < 2:
    note("This needs the focus factor in at least two markets; today it has fewer.")
else:
    panel = pd.DataFrame({m: cross[m] for m in live})        # outer join on the union of all trading dates
    common = panel.dropna()
    calendar = pd.DataFrame({
        "market": [MARKET_NAMES[m] for m in live],
        "trading days": [int(panel[m].notna().sum()) for m in live],
        "holidays: dates another market traded but this one did not": [int(panel[m].isna().sum()) for m in live],
        "its holidays inside its span": [int(panel[m].loc[cross[m].index.min():cross[m].index.max()].isna().sum())
                                         for m in live]})
    display(calendar.style.hide(axis="index"))
    print(f"Union of all calendars: {len(panel)} dates. Dates on which every market traded: {len(common)}.")

    victim = max(live, key=lambda m: panel[m].loc[cross[m].index.min():cross[m].index.max()].isna().sum())
    inside = panel[victim].loc[cross[victim].index.min():cross[victim].index.max()]
    k = np.sqrt(TRADING_DAYS)
    demo = pd.DataFrame([
        ("Right: its own trading days", int(inside.notna().sum()), (1 + inside.dropna()).prod() - 1, inside.dropna().std() * k),
        ("Wrong: forward-fill the return", int(inside.ffill().notna().sum()), (1 + inside.ffill()).prod() - 1,
         inside.ffill().std() * k),
        ("Wrong: fill with 0", len(inside), (1 + inside.fillna(0)).prod() - 1, inside.fillna(0).std() * k),
    ], columns=[f"{MARKET_NAMES[victim]}: method", "days used", "total return", "volatility a year"])
    display(demo.style.format({"total return": "{:+.2%}", "volatility a year": "{:.2%}"}).hide(axis="index"))

    start = max(cross[m].index.min() for m in live)
    end = min(cross[m].index.max() for m in live)
    weekly = (1 + panel.loc[start:end]).groupby(pd.Grouper(freq="W-FRI")).prod(min_count=1) - 1
    pair_rows = []
    for a, b in combinations(live, 2):
        daily_ab = panel[[a, b]].dropna()
        weekly_ab = weekly[[a, b]].dropna()
        pair_rows.append({"pair": f"{MARKET_NAMES[a]} – {MARKET_NAMES[b]}", "shared days": len(daily_ab),
                          "daily correlation": daily_ab[a].corr(daily_ab[b]), "weeks": len(weekly_ab),
                          "weekly correlation": weekly_ab[a].corr(weekly_ab[b])})
    display(pd.DataFrame(pair_rows).style.format({"daily correlation": "{:+.2f}", "weekly correlation": "{:+.2f}"})
            .hide(axis="index"))

# %% [markdown]
# **How to read this.** The first table counts, for each market, the dates on
# which another market traded but it did not: its holidays. The second applies
# the three treatments to the market with the most holidays inside its span. With the right treatment the
# total return and volatility are the market's own. Forward-filling changes
# both; filling with 0 keeps the total but understates volatility. The third
# table correlates the factor across markets two ways: on shared trading days,
# and on weekly returns (compounded from Monday to Friday).
#
# **Caveats.**
#
# - **Same date, different hours.** Tokyo, Hong Kong and Shanghai close before
#   New York opens, so "Tuesday" in Asia and "Tuesday" in the US are different
#   24-hour windows. Same-day correlations across those markets understate the
#   link. Weekly returns soften this problem, at the cost of far fewer points.
# - With about 50 weeks, a weekly correlation needs to exceed roughly ±0.28 to
#   be distinguishable from zero.

# %% [markdown]
# ## 5. Extensions (beyond the raw API)
#
# *These sections go beyond the raw API.* They use the cleaned tables from
# section 3 to answer two follow-up questions: how much does mixing the factors
# reduce risk, and how "pure" are the long-short factors really?

# %% [markdown]
# ### 5.1 The equal-weight mix: diversification in one number
#
# If you hold all the published factors in equal weights, rebalanced every day,
# the mix's daily return is the plain average of the factors' returns. The API
# sends this series as `aggregate.return_series` and its statistics as
# `aggregate.equal_weight_stats`. We rebuild it on the complete-case window and
# check it. Because the factors are only weakly correlated, the mix should swing
# far less than the average factor. That reduction is **diversification**. With
# N uncorrelated factors of *equal* risk, the average volatility ÷ the mix's
# volatility would be √N. Here the risks are not equal (ERP swings much more
# than the long-short factors), so the uncorrelated benchmark is
# Σσ ÷ √(Σσ²), where σ is each factor's volatility. A mix that beats this
# number gained more than zero correlation would give, which needs some
# negative correlations.

# %%
if len(IDS) < 2:
    note("The mix needs at least two published factors.")
else:
    ew = aligned.mean(axis=1)                                   # equal weights, rebalanced daily
    api_points = pd.DataFrame([{"date": p["date"], "ret": p["ret"]} for p in agg["return_series"]],
                              columns=["date", "ret"])
    api_points["ret"] = pd.to_numeric(api_points["ret"], errors="coerce")
    api_points["date"] = pd.to_datetime(api_points["date"], utc=True, errors="coerce").dt.tz_localize(None)
    api_ew = api_points.dropna().drop_duplicates(subset="date", keep="last").set_index("date")["ret"]
    both = pd.concat([ew.rename("ours"), api_ew.rename("api")], axis=1, sort=True).dropna()
    if both.empty:
        print("The API sends no equal-weight series to compare with.")
    else:
        print(f"Our mix vs aggregate.return_series: {len(both)} shared dates, largest difference "
              f"{(both['ours'] - both['api']).abs().max():.6f} (the API rounds its returns).")
    ours_ew, api_ew_stats = risk_stats(ew, level=0.95), agg["equal_weight_stats"]
    display(pd.DataFrame({"API equal_weight_stats": api_ew_stats, "ours": ours_ew}).loc[STAT_KEYS]
            .style.format("{:.4f}", na_rep="–").format("{:.0f}", subset=pd.IndexSlice[["n_obs"], :]))

    vols = aligned.std() * np.sqrt(TRADING_DAYS)
    ew_vol = float(ew.std() * np.sqrt(TRADING_DAYS))
    avg_vol = float(vols.mean())
    bench = float(vols.sum() / np.sqrt((vols**2).sum()))        # average ÷ mix volatility if uncorrelated
    zero_corr_vol = float(np.sqrt((vols**2).sum()) / len(IDS))  # the mix's volatility if uncorrelated
    reached = avg_vol / ew_vol
    sr, se, lo, hi = sharpe_interval(ew)
    names = [NAME[f] for f in IDS] + ["Equal-weight mix"]
    values = list(vols[IDS]) + [ew_vol]
    fig = go.Figure(go.Bar(
        x=values, y=names, orientation="h", width=0.56, showlegend=False, cliponaxis=False,
        marker=dict(color=[AXIS] * len(IDS) + [INK]),                # the factors in grey, the mix stands out
        text=[pct(v) for v in values], textposition="outside", textfont=dict(size=12, color=INK_2),
        hovertemplate="%{y}: %{x:.1%} a year<extra></extra>"))
    fig.add_vline(x=avg_vol, line=dict(color=INK_2, width=1, dash="dot"),
                  annotation_text=f"average factor {avg_vol:.1%}", annotation_position="top",
                  annotation_font=dict(size=11, color=INK_2))
    verdict_text = ("better than" if reached > bench * 1.02 else "short of" if reached < bench * 0.98 else "about")
    fig.update_layout(
        title=dict(text=f"Mixing {len(IDS)} factors cut volatility to {ew_vol:.1%} a year, against {avg_vol:.1%} "
                        f"for the average factor ({reached:.2f}× less)",
                   subtitle=dict(text=f"Yearly volatility over the {len(aligned)} aligned days · the mix holds every "
                                      f"published factor in equal weights<br>{bench:.2f}× if they were uncorrelated "
                                      f"(√N = {np.sqrt(len(IDS)):.2f}× only when risks are equal), so the mix did "
                                      f"{verdict_text} that")),
        height=190 + 50 * len(names), margin=dict(t=140, b=60, r=60),
        xaxis=dict(title="Volatility (% a year)", tickformat=".0%", rangemode="tozero",
                   range=[0, max(values) * 1.18]),
        yaxis=dict(autorange="reversed", ticks=""))
    fig.show()
    display(pd.DataFrame({"portfolio": names, "volatility a year": values,
                          "Sharpe-like": [sharpe_interval(aligned[f])[0] for f in IDS] + [sr]})
            .style.format({"volatility a year": "{:.1%}", "Sharpe-like": "{:+.2f}"}).hide(axis="index"))
    print(f"Mix volatility {ew_vol:.2%} a year; if the factors were uncorrelated it would be {zero_corr_vol:.2%} "
          f"(√(Σσ²) ÷ N). Average ÷ mix: {reached:.2f}× actual vs {bench:.2f}× uncorrelated.")
    print(f"The mix's Sharpe-like ratio: {sr:+.2f} (95% interval {lo:+.2f} to {hi:+.2f}).")

# %% [markdown]
# **How to read this.** Each grey bar is a factor's yearly volatility on the
# shared window; the black bar at the bottom is the equal-weight mix, and the
# dotted line marks the average factor. The gap between the line and the black
# bar is what diversification bought. The subtitle compares it with the
# benchmark for uncorrelated factors, Σσ ÷ √(Σσ²); the printed line gives the
# mix's volatility under zero correlation next to the actual one.
#
# **Caveats.**
#
# - The mix is chosen after the fact: it holds the factors that passed today's
#   gates, measured on the same year. That flatters it.
# - Diversification depends on correlations, and correlations rise in a crisis
#   (section 3.8), so the mix can be riskier than this exactly when it matters.
# - Lower volatility is not higher return. The mix's Sharpe-like ratio still
#   has an interval about ±2 wide.

# %% [markdown]
# ### 5.2 How pure are the long-short factors? Their market beta
#
# A "pure" long-short factor should not care which way the market goes: its
# long and short legs should cancel the market's move. We check that with a
# time-series regression on the complete-case window:
#
# factor return = α + β × ERP return + noise
#
# **β (beta)** is how much the factor moves, on average, when the market moves
# by 1%. A pure factor has β near 0. **α (alpha)** is the average return that
# the market does not explain, shown per year. This regression *describes* the
# past year. It does not forecast returns and it does not recommend trades.
#
# We report two kinds of robust standard errors. **HC3** is robust to noise
# that is bigger on some days than others, including calm and stormy spells.
# **HAC** (Newey–West) is robust to that too, and also to returns that are
# correlated from one day to the next (a move that tends to carry on, or to
# reverse). Daily factor returns can be, so we use HAC for the intervals.

# %%
others = [f for f in IDS if f != "erp"]
if "erp" not in IDS or not others:
    note("This needs ERP and at least one long-short factor published in the same market.")
else:
    X = sm.add_constant(aligned["erp"].rename("ERP"))
    lags = newey_west_lags(len(aligned))
    beta_rows = []
    for fid in others:
        hac = sm.OLS(aligned[fid], X).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
        hc3 = sm.OLS(aligned[fid], X).fit(cov_type="HC3")
        lo, hi = hac.conf_int().loc["ERP"]
        beta_rows.append({"factor_id": fid, "factor": NAME[fid], "beta": hac.params["ERP"],
                          "SE (HAC)": hac.bse["ERP"], "SE (HC3)": hc3.bse["ERP"], "95% low": lo, "95% high": hi,
                          "t (HAC)": hac.tvalues["ERP"], "alpha a year": hac.params["const"] * TRADING_DAYS,
                          "alpha t (HAC)": hac.tvalues["const"], "R²": hac.rsquared})
    betas = pd.DataFrame(beta_rows)
    clear = betas[(betas["95% low"] > 0) | (betas["95% high"] < 0)]
    biggest = betas.loc[betas["beta"].abs().idxmax()]

    fig = go.Figure()
    fig.add_vline(x=0, line=dict(color=AXIS, width=1), layer="below")
    excludes = betas["factor_id"].isin(clear["factor_id"])
    for is_clear, label, color in ((True, "95% interval excludes 0", SERIES[0]),
                                   (False, "Cannot be told from 0", INK_2)):
        part = betas[excludes == is_clear]
        if part.empty:
            continue
        fig.add_trace(go.Scatter(
            x=part["beta"], y=part["factor"], mode="markers+text", name=label,
            marker=dict(size=11, color=color, line=dict(width=2, color=SURFACE)),
            error_x=dict(type="data", symmetric=False, array=part["95% high"] - part["beta"],
                         arrayminus=part["beta"] - part["95% low"], color=color, thickness=2, width=0),
            text=part["beta"].map(signed), textposition="top center", textfont=dict(size=11, color=INK_2),
            customdata=part[["95% low", "95% high", "R²"]].to_numpy(),
            hovertemplate=("<b>%{y}</b><br>beta %{x:+.2f} (95%: %{customdata[0]:+.2f} to %{customdata[1]:+.2f})"
                           "<br>R² %{customdata[2]:.2f}<extra></extra>")))
    title = ("No long-short factor has a market beta clearly different from zero: they are close to market-neutral"
             if clear.empty else
             f"{len(clear)} of {len(betas)} long-short factors carry a clear market beta; "
             f"{biggest['factor'].split(' · ')[0]}'s is the strongest ({signed(biggest['beta'])})")
    fig.update_layout(
        title=dict(text=title, subtitle=dict(
            text=f"Slope of each factor's daily return on ERP's, {len(aligned)} aligned days · whisker: 95% interval "
                 f"with HAC (Newey–West, {lags} lags) standard errors")),
        height=190 + 58 * len(betas), margin=dict(t=110, b=110, r=40), legend=BOTTOM_LEGEND, showlegend=True,
        xaxis=dict(title="Market beta (factor move per 1% market move)", zeroline=False),
        yaxis=dict(ticks="", categoryorder="array", categoryarray=betas["factor"].tolist()[::-1]))
    fig.show()
    display(betas.drop(columns="factor_id").style.format({
        "beta": "{:+.3f}", "SE (HAC)": "{:.3f}", "SE (HC3)": "{:.3f}", "95% low": "{:+.3f}", "95% high": "{:+.3f}",
        "t (HAC)": "{:+.2f}", "alpha a year": "{:+.1%}", "alpha t (HAC)": "{:+.2f}", "R²": "{:.2f}"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Each dot is a factor's market beta, with its 95%
# interval. A grey whisker crosses zero: the factor is market-neutral as far
# as one year of data can tell. A blue one stays clear of zero. A clearly positive beta means the factor
# tends to rise with the market: its long leg amplifies the market's moves more
# than its short leg does (for SMB, that would be small stocks moving more than
# the giants they are paired against). The table adds both standard errors.
# HC3 and HAC are usually close. When HAC is bigger, the regression's surprises
# (each day's residual times the market's move) are positively correlated from
# one day to the next; when it is smaller, they tend to reverse. The table
# also gives the yearly alpha with its t-statistic, and R², the share of the
# factor's daily variance that the market explains.
#
# **Caveats.**
#
# - Descriptive and in-sample: β describes the last year, and it drifts.
# - A beta near zero does not mean the factor is safe. It can still have large
#   swings and drawdowns of its own (sections 3.6–3.9).
# - The regression explains co-movement on the same day. It does not forecast
#   tomorrow's factor return from today's market.

# %% [markdown]
# ## Next steps
#
# - Change `MARKET` and compare which factors pass their gates there (the
#   tables in sections 3.2 and 4).
# - Set `FOCUS_FACTOR = "smb"` and, on a day when SMB is published, look at the
#   short leg: it holds the market's largest companies.
# - Re-run the notebook tomorrow. Expect a new `release_id`, one more day in each
#   series, and perhaps a factor that passes its gates for the first time.
# - Join the holdings preview to the screen endpoint (notebook 01) on `ticker`,
#   and check each stock's `bp`, `profit_margin` or `ma200_excess` (a rough
#   momentum proxy) against its leg.
# - Set `ROLL_DAYS = 21` for a twitchier one-month volatility, or `TAIL = 0.99`
#   for a deeper tail (and see how few days that averages).
# - Notebook 03's ML clusters describe similar styles (momentum, value, size)
#   from the stocks' side: compare a cluster's members with a factor's legs.
#
# ---
#
# *Research and education only. Nothing here is investment advice or a
# recommendation to buy or sell any security. The factor portfolios are
# in-sample research constructs, shown before trading costs and borrowing fees;
# past factor returns do not predict future ones. The endpoint name `realtime`
# elsewhere in the API names a current-session board, not a live-tick feed, and
# data cadence varies by market: always check `as_of` and the freshness fields.*

# %%
print(f"API requests made in this session: {api_calls_used()}")
