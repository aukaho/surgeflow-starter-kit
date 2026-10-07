# %% [markdown]
# # 06 · ML lab: cleaning, regression, PCA and clustering on one day's snapshot
#
# This is the capstone of the series. You take the **~300 largest listings** of
# one market from the SurgeFlow screen, cut them to one line per company, attach
# whale signals and SurgeFlow's own cluster labels, clean the result in the
# open, and then put three classic tools to work:
#
# 1. **Regression.** Which stock characteristics go with the day's differences in
#    return *between* stocks?
# 2. **PCA** (principal component analysis). What are the few main directions in
#    which these stocks differ? And how much do SurgeFlow's factor returns
#    overlap?
# 3. **Clustering.** Do the stocks fall into a few styles, and do those styles
#    match sectors or SurgeFlow's own groups? SurgeFlow's groups are compared
#    at the cluster level (their sector mix) on every run; the stock-by-stock
#    comparison needs enough SurgeFlow-labelled stocks among the largest names,
#    and at the time of writing only `jp` comes close.
#
# Everything here is **cross-sectional and descriptive**. Cross-sectional means
# we compare many stocks on one day, not one stock over time. The regression
# explains how one day's stocks differ from one another. It does **not**
# forecast tomorrow's returns, and it does not recommend trades.
#
# **What you will learn**
#
# - How to page through a large screen efficiently, and join three more
#   endpoints onto it with left joins whose match rates you report.
# - A complete, explicit cleaning pipeline: types, duplicates, a counted NaN
#   policy, log transforms, winsorising, and a before/after audit.
# - How to spot and remove **leakage**: a feature that secretly contains the
#   answer.
# - Ordinary least squares (OLS) with robust HC3 standard errors, variance
#   inflation factors (VIF), a coefficient plot with 95% confidence intervals,
#   and residual diagnostics.
# - Ridge and lasso inside a scikit-learn `Pipeline`, scored by k-fold
#   cross-validation against a do-nothing baseline.
# - PCA on standardised features: scree plot, parallel analysis, loadings and
#   score maps. Then a second PCA on daily factor returns, when they are
#   published.
# - k-means (elbow and silhouette), Ward hierarchical clustering (dendrogram),
#   the adjusted Rand index (ARI) to compare two clusterings, and a
#   cluster-level comparison of sector mixes when stock labels are too few.
#
# **Endpoints used**
#
# | Method | Path | What it returns | Role in this lab |
# |---|---|---|---|
# | GET | `/api/v1/markets/{market}/screen` | The paged market screen: one row per stock, about 20 fields, largest market cap first | The base table and most features |
# | GET | `/api/v1/markets/{market}/realtime` | The current-session turnover board (50 names) | Optional: the busiest names' session return, for exploring only |
# | GET | `/api/v1/markets/{market}/whales` | Six top-20 institutional-holdings boards | A whale signal per stock |
# | GET | `/api/v1/markets/{market}/ml/clusters` | SurgeFlow's latest clustering run | Labels and sector mixes to compare our clusters with |
# | GET | `/api/v1/markets/{market}/factor-portfolios` | Pure-factor portfolios with daily return series (when published) | Input for a second PCA |
#
# Markets: `us`, `cn`, `jp`, `hk`. With the default settings the notebook makes
# 7 requests, plus up to 3 more when your market publishes fewer than 3 factor
# return series (at the time of writing no market does, so expect 10 in total;
# the free plan allows 2,000 a day). It runs in about two minutes.
#
# **Words used in this notebook**
#
# | Word | Meaning |
# |---|---|
# | feature | A column that describes each stock: size, valuation, trend, ... |
# | target | The column we try to explain. Here: the day's change of each stock, in percent |
# | left join | Keep every row of the base table and attach the other table's columns where the key matches |
# | NaN | "Not a number": pandas' marker for a missing value |
# | leakage | A feature that contains the target itself, so the model "explains" the answer with the answer |
# | winsorise | Clip the most extreme values to a percentile (here the 1st and 99th) while keeping the stock |
# | z-score | (value − mean) ÷ standard deviation: how many standard deviations a value sits from average |
# | robust z-score | The same idea built from the median and the median absolute deviation, so outliers cannot stretch the scale |
# | OLS | Ordinary least squares: the classic straight-line (linear) regression |
# | HC3 | Standard errors that stay valid when the scatter of errors differs from stock to stock |
# | VIF | Variance inflation factor: how much one feature overlaps with the others |
# | cross-validation | Fit on part of the data, score on the part held out, rotate, and average |
# | R² | The share of the target's variation a model explains. 0 = none, 1 = all; out of sample it can go negative |
# | PCA | Principal component analysis: rewrites many correlated features as a few uncorrelated directions |
# | loading | How strongly a feature lines up with a principal component (a correlation, −1 to 1) |
# | k-means | Splits stocks into k groups so that each stock is close to its group's centre |
# | silhouette | How cleanly clusters separate, from −1 to 1. Higher is cleaner |
# | ARI | Adjusted Rand index: agreement between two clusterings. 1 = identical, about 0 = chance |

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
# (`sf_get`, `sf_try`, `records`, `dig`, `show_freshness`, ...) and the chart
# theme. You can run it without reading it.

# %% [helpers]

# %% [markdown]
# ## 2. Parameters
#
# Change `MARKET` and run the notebook again to study another market. The other
# settings are the knobs of the cleaning and modelling steps. Each one is
# explained where it is used.

# %%
MARKET = "us"              # one of "us", "cn", "jp", "hk"
SCREEN_PAGES = 3           # screen pages to fetch, largest market cap first: 3 x 100 = the ~300 largest names
PAGE_SIZE = 100            # screen rows per page: 1-100 (a larger value is rejected with VALIDATION_ERROR)
FACTOR_FALLBACK = True     # fewer than 3 factor return series for MARKET? try the other markets (up to 3 more requests)

WINSOR_Q = 0.01            # winsorise at the 1st and 99th percentiles (0 switches winsorising off)
OUTLIER_Z = 3.5            # a value counts as an outlier when its robust z-score is above this
MAX_MISSING_SHARE = 0.40   # a feature missing for more stocks than this is dropped as a column, not stock by stock
FLAG_MIN_SHARE = 0.05      # the "fundamentals filled" flag enters the regression only if at least this share carry it
MIN_ROWS = 40              # the modelling sections need at least this many complete stocks
MIN_LABELLED = 10          # SurgeFlow-labelled stocks needed in the sample before we compare clusterings with them
VIF_LIMIT = 10.0           # variance inflation factor above which a regression feature is dropped
CV_FOLDS = 5               # k-fold cross-validation folds
K_RANGE = range(2, 11)     # k values that k-means scans
BALANCE_CAP = 0.40         # largest cluster share allowed when choosing k (used if the SurgeFlow run sends none)
N_PERMUTATIONS = 200       # shuffles for parallel analysis (PCA) and for the chance level of the ARI
DENDRO_MAX_LEAVES = 300    # the dendrogram draws at most this many stocks (a fixed random sample)
RANDOM_STATE = 42          # fixes every random choice: CV folds, k-means starts, shuffles, samples
LABEL_TOP = 3              # charts label at most this many points; hover shows the rest

assert MARKET in MARKETS, f"MARKET must be one of {MARKETS}"
assert 1 <= PAGE_SIZE <= 100, "PAGE_SIZE must be between 1 and 100"
COLOR = MARKET_COLORS[MARKET]                      # this market's colour in every chart of the kit
TODAY = pd.Timestamp.now(tz="UTC").normalize()
print(f"Studying {MARKET_NAMES[MARKET]} ({MARKET}). Today is {TODAY:%Y-%m-%d} UTC.")

# %% [markdown]
# **Libraries and small utilities.** Colab already has every library used here
# (`statsmodels`, `scikit-learn`, `scipy`, `plotly`). The utilities below are
# plain code, so read them once:
#
# - `pick` keeps exactly the documented columns. If one is missing it raises a
#   `KeyError`: the API contract changed, and you want to know. An empty list is
#   normal, so it returns an empty table instead of crashing.
# - `money` turns `25968124707` into `$25.97B`.
# - `label` translates a column code such as `ma50_gap_prev` into words.
# - `robust_z` measures how unusual a value is, using the median and the median
#   absolute deviation (MAD). We use it only to *count* outliers.
# - `trait` turns a feature and a sign into words ("cheap on earnings",
#   "trading below its 50-day average").
# - `lower_triangle` blanks the upper half of a correlation matrix, which only
#   repeats the lower half, and the diagonal, where every feature correlates
#   +1 with itself.
# - `UNITS` records how each model column is measured; the API sends several
#   of them as fractions (0.05 = 5%).
# - `chart_title`, `legend_below` and `label_points` handle chart layout: they
#   wrap long titles, keep the legend clear of the axis title, and stack point
#   labels so they do not overlap.
#
# The cell also checks two library versions. Chart subtitles need plotly 5.23 or
# newer, and `DataFrame.map` needs pandas 2.1 or newer. Colab has both; an older
# local install stops here with the upgrade command instead of failing mid-way.

# %%
import re
import textwrap

import plotly
import plotly.figure_factory as ff
import statsmodels.api as sm
from plotly.subplots import make_subplots
from scipy import stats
from scipy.cluster import hierarchy as sch
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.decomposition import PCA
from sklearn.dummy import DummyRegressor
from sklearn.linear_model import LassoCV, LinearRegression, RidgeCV
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.model_selection import KFold, cross_validate
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from statsmodels.nonparametric.smoothers_lowess import lowess
from statsmodels.stats.diagnostic import het_breuschpagan
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.outliers_influence import OLSInfluence, variance_inflation_factor
from statsmodels.stats.stattools import jarque_bera


def version_tuple(text: str) -> tuple:
    """'5.24.1' -> (5, 24): enough to compare major and minor versions."""
    return tuple(int(part) for part in re.findall(r"\d+", text)[:2])


assert version_tuple(plotly.__version__) >= (5, 23), "Chart subtitles need plotly 5.23+: pip install -U 'plotly>=5.24'"
assert version_tuple(pd.__version__) >= (2, 1), "DataFrame.map needs pandas 2.1+: pip install -U 'pandas>=2.1'"

pd.set_option("styler.html.mathjax", False)        # a "$" in a table is money, not mathematics
pd.set_option("display.html.use_mathjax", False)

FEATURE_LABELS = {
    "y_change": "Daily change (%)",
    "log_mcap": "Market cap (log USD)",
    "log_turnover": "Turnover (log, local currency)",
    "log_turnover_vs_10d": "Turnover vs 10-day average (log)",
    "ma10_excess": "Gap to 10-day average (%)",
    "ma50_excess": "Gap to 50-day average (%)",
    "ma200_excess": "Gap to 200-day average (%)",
    "ep": "Earnings yield E/P (%)",
    "log_bp": "Book-to-price (log B/P)",
    "log_sp": "Sales-to-price (log S/P)",
    "profit_margin": "Profit margin (%)",
    "log_revenue_growth": "Revenue growth (log of 1 + g)",
    "dividend_yield": "Dividend yield (%)",
    "log_mcap_prev": "Market cap (log USD, prior close)",
    "ma10_gap_prev": "Gap to 10-day average (prior close, %)",
    "ma50_gap_prev": "Gap to 50-day average (prior close, %)",
    "ma200_gap_prev": "Gap to 200-day average (prior close, %)",
    "ep_prev": "Earnings yield E/P (prior close, %)",
    "log_bp_prev": "Book-to-price (log B/P, prior close)",
    "log_sp_prev": "Sales-to-price (log S/P, prior close)",
    "dividend_yield_prev": "Dividend yield (prior close, %)",
    "whale_boards": "Whale boards listing it (0-6)",          # the upper bound is updated in section 5
    "fundamentals_filled": "Fundamentals median-filled (0/1)",
}
# How each model column is measured. The API sends the "%" columns as fractions (0.05 = 5%): charts and tables
# show them as percentages, so always multiply by 100 (or use a "%" format) before you compare them with y_change.
UNITS = {"y_change": "percent",
         **dict.fromkeys(["ma10_excess", "ma50_excess", "ma200_excess", "ma10_gap_prev", "ma50_gap_prev",
                          "ma200_gap_prev", "ep", "ep_prev", "profit_margin", "dividend_yield",
                          "dividend_yield_prev"], "fraction"),
         **dict.fromkeys(["log_mcap", "log_mcap_prev", "log_turnover", "log_turnover_vs_10d", "log_bp", "log_sp",
                          "log_bp_prev", "log_sp_prev", "log_revenue_growth"], "log"),
         "whale_boards": "count", "fundamentals_filled": "flag"}
UNIT_AXIS = {"percent": "% (daily change)", "fraction": "% (sent as a fraction)", "log": "natural log units",
             "count": "boards (count)", "flag": "0 = no, 1 = yes"}
TRAITS = {  # feature: (words for a high value, words for a low value)
    "log_mcap": ("larger cap", "smaller cap"),
    "log_turnover": ("heavily traded", "lightly traded"),
    "log_turnover_vs_10d": ("busier than its 10-day pace", "quieter than its 10-day pace"),
    "ma10_excess": ("trading above its 10-day average", "trading below its 10-day average"),
    "ma50_excess": ("trading above its 50-day average", "trading below its 50-day average"),
    "ma200_excess": ("trading above its 200-day average", "trading below its 200-day average"),
    "ep": ("cheap on earnings", "dear on earnings"),
    "log_bp": ("high book/price", "low book/price"),
    "log_sp": ("high sales/price", "low sales/price"),
    "profit_margin": ("high margin", "low margin"),
    "log_revenue_growth": ("fast revenue growth", "slow revenue growth"),
    "dividend_yield": ("high dividend yield", "low or no dividend"),
}


def pick(raw: pd.DataFrame, columns: list) -> pd.DataFrame:
    """Keep the documented columns. Empty is normal; a missing column raises KeyError."""
    if raw.empty:
        return pd.DataFrame(columns=columns)
    return raw[columns].copy()


def money(value, digits: int = 2) -> str:
    """25968124707 -> '$25.97B'."""
    if pd.isna(value):
        return "n/a"
    sign, value = ("-" if value < 0 else ""), abs(float(value))
    for size, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= size:
            return f"{sign}${value / size:,.{digits}f}{unit}"
    return f"{sign}${value:,.0f}"


def label(code: str) -> str:
    """Plain-English name for a column code; unknown codes are shown as they are."""
    return FEATURE_LABELS.get(code, code)


def lower_first(text: str) -> str:
    """'Market cap (log USD)' -> 'market cap (log USD)', for use mid-sentence ('E/P' stays as it is)."""
    text = str(text)
    return text[0].lower() + text[1:] if len(text) > 1 and text[1].islower() else text


def trait(feature: str, value: float) -> str:
    """Words for a high (value > 0) or low (value < 0) reading of a feature."""
    high, low = TRAITS.get(feature, (f"high {lower_first(label(feature))}", f"low {lower_first(label(feature))}"))
    return high if value > 0 else low


def wrap(text: str, width: int = 30) -> str:
    """Break a long label into lines of at most `width` characters (Plotly uses <br> for a new line)."""
    return "<br>".join(textwrap.wrap(str(text), width)) or str(text)


def shorten(text, width: int = 26) -> str:
    """Cut a long name to `width` characters, with an ellipsis."""
    text = "" if pd.isna(text) else str(text)
    return text if len(text) <= width else text[: width - 1] + "…"


def plural(n, word: str, many: str = None) -> str:
    """plural(1, 'stock') -> '1 stock'; plural(3, 'stock') -> '3 stocks'."""
    n = int(n)
    return f"{n:,} {word if n == 1 else (many or word + 's')}"


def fmt_p(p: float) -> str:
    """A p-value for humans: '<0.001' or '0.042'."""
    return "n/a" if pd.isna(p) else ("<0.001" if p < 0.001 else f"{p:.3f}")


def p_text(p: float) -> str:
    """'p < 0.001' or 'p = 0.042', for sentences."""
    return "p n/a" if pd.isna(p) else ("p < 0.001" if p < 0.001 else f"p = {p:.3f}")


def fmt_perm_p(p: float, n_perm: int) -> str:
    """A permutation p-value: with n shuffles it cannot go below 1/(n + 1), so that floor prints as '<0.005'."""
    floor = 1 / (n_perm + 1)
    return "n/a" if pd.isna(p) else (f"<{floor:.3f}" if p <= floor * (1 + 1e-9) else f"{p:.3f}")


def robust_z(values: pd.Series) -> pd.Series:
    """0.6745 x (value - median) / MAD (Iglewicz & Hoaglin). NaN when the MAD is 0 (a mostly constant column)."""
    x = pd.to_numeric(values, errors="coerce").astype(float)
    median = x.median()
    mad = (x - median).abs().median()
    if not mad or pd.isna(mad):
        return pd.Series(np.nan, index=x.index)
    return 0.6745 * (x - median) / mad


def lower_triangle(matrix: pd.DataFrame) -> pd.DataFrame:
    """Each pair once: the upper triangle and the diagonal (a feature with itself, always +1) set to NaN. The first
    row and the last column are then empty, so they are dropped."""
    values = matrix.to_numpy(dtype=float).copy()
    values[np.triu_indices_from(values, k=0)] = np.nan
    return pd.DataFrame(values, index=matrix.index, columns=matrix.columns).iloc[1:, :-1]


def chart_title(title: str, subtitle: str = "", width: int = 90) -> tuple:
    """Wrap a long title and subtitle onto several lines, pin them to the top of the figure, and return
    Plotly's title dict plus the top margin (pixels) that keeps them clear of the plot."""
    head = "<br>".join(textwrap.wrap(title, width))
    sub = "<br>".join(textwrap.wrap(subtitle, int(width * 1.45))) if subtitle else ""
    n_head, n_sub = head.count("<br>") + 1, (sub.count("<br>") + 1 if sub else 0)
    top = 40 + 23 * n_head + 18 * n_sub
    return dict(text=head, subtitle=dict(text=sub), y=1, yref="container", yanchor="top",
                pad=dict(t=12 + 22 * (n_head > 1))), top


def legend_below(height: int, top: int, bottom: int, gap: int = 62) -> dict:
    """A horizontal legend `gap` pixels under the plot area (clear of the x-axis title), at any chart height."""
    return dict(orientation="h", x=0, xanchor="left", y=-gap / max(height - top - bottom, 120), yanchor="top")


def label_points(fig, xs, ys, texts, dx: int = -42, **cell) -> None:
    """Label a few points with thin leader lines, stacking the labels so that they do not overlap."""
    for k, i in enumerate(np.argsort(-np.asarray(ys, dtype=float))):         # the highest point first
        fig.add_annotation(x=xs[i], y=ys[i], text=texts[i], showarrow=True, arrowhead=0, arrowwidth=1,
                           arrowcolor=MUTED, ax=dx, ay=-30 + 24 * k, font=dict(size=11, color=INK_2), **cell)


NOT_ENOUGH = (f"> Fewer than {MIN_ROWS} complete stocks came back, so this step is skipped. That is normal "
              "for a closed or brand-new session; try another market or run again later.")

# %% [markdown]
# ## 3. Screen: the base table, one row per stock
#
# **What it is for.** The screen is the market's master table: one row per stock
# in SurgeFlow's institutional universe, with about 20 fields covering price,
# the day's change, turnover (the money traded), market cap, trend, valuation
# and fundamentals. It is the **base** of our feature table. Every other
# endpoint is joined onto it by `ticker`.
#
# **Paging, and why we stop at three pages.** The live US screen has about
# 3,300 rows, far too many for one response, so the API splits them into pages
# of at most 100 rows. `count` is the total number of rows and `total_pages =
# ceil(count / page_size)`; a page past the end comes back with `rows: []`.
# Fetching every page would spend 33 requests on the US alone. We ask for the
# rows **sorted by market cap, largest first** (`sort="market_cap_usd"`) and
# keep `SCREEN_PAGES = 3` pages: the **~300 largest listings**, cut to one line
# per company in the cleaning step below. They hold a large share of the
# market's value. Remember that throughout: **the sample is the large-cap end of
# the market**, not the whole of it.
#
# The screen keeps its rows at the top level of the response
# (`payload["rows"]`), not under `data` like the other boards.

# %%
screen_rows, page_log, first_page = [], [], None
stop_reason = f"the SCREEN_PAGES setting ({SCREEN_PAGES} pages)"

for page in range(1, SCREEN_PAGES + 1):
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
SCREEN_AS_OF = first_page["as_of_date"]
print(f"Stopped at {stop_reason}. Fetched {len(screen_rows):,} rows of {total:,} "
      f"({len(screen_rows) / max(total, 1):.0%} of the screened names), largest market cap first.")
if page_log["as_of_date"].nunique() > 1:
    print("Warning: as_of_date changed while paging, so the pages describe different sessions. Re-run the loop.")
else:
    print(f"Every page describes the session of {SCREEN_AS_OF}.")

# %% [markdown]
# The screen also reports how complete its inputs are. On this endpoint
# `data_quality` is a dictionary of coverage percentages: the share of the
# universe with a usable value for each input. A low
# `dividend_yield_currency_aligned_pct`, for example, warns you that many
# `dividend_yield` values will be empty.

# %%
dq = first_page["data_quality"]
display(Markdown(f"**Coverage:** {dq.get('coverage', 'n/a')}. {dq.get('basis_coverage_note') or ''}"
                 + (f" **Limitation:** {dq['limitation']}" if dq.get("limitation") else "")))
pd.DataFrame([(k, f"{v:,g}") for k, v in dq.items() if isinstance(v, (int, float)) and not isinstance(v, bool)],
             columns=["measure", "value"]).set_index("measure")

# %% [markdown]
# **Raw preview.** The data exactly as it arrived, before any cleaning.

# %%
screen_raw = pd.DataFrame(screen_rows)
print(f"{screen_raw.shape[0]:,} rows x {screen_raw.shape[1]} columns")
if screen_raw.empty:
    display(Markdown("> The screen returned no rows. That can happen briefly while a new day's data is being "
                     "built; the cells below still run and say so. Try again later."))
screen_raw.head()

# %% [markdown]
# ### The fields and their units
#
# Units are the most common source of mistakes with financial data. Every later
# cell relies on this table.
#
# | Field | Meaning | Unit |
# |---|---|---|
# | `price` | last price | local currency |
# | `change_pct` | the day's change: the session's close versus the previous close | **fraction**: 0.0142 = +1.42% |
# | `turnover`, `previous_day_turnover` | money traded in the session, and in the one before | local currency |
# | `turnover_vs_10d` | turnover relative to its 10-day average | ratio: 1.0 = a normal day |
# | `market_cap_usd` | market value of the company | US dollars |
# | `ma10_excess`, `ma50_excess`, `ma200_excess` | price above (+) or below (−) its 10-, 50- and 200-day moving average, **including today's price** | fraction: 0.05 = 5% above |
# | `ep`, `bp`, `sp` | earnings, book value and sales per unit of price (the inverses of P/E, P/B and P/S) | fraction |
# | `profit_margin`, `revenue_growth`, `dividend_yield` | profitability, growth and payout. An exact `0.0` in `revenue_growth` is a placeholder for "not computed" (seen on the US screen, mostly for fiscal years that do not end in December), not zero growth | fraction |
# | `ratio_quality` | SurgeFlow's grade of the valuation ratios (`good`, `acceptable`, ...) | label |
# | `institutional_default` | in SurgeFlow's default institutional universe | true / false |
#
# ### Cleaning the screen
#
# 1. **Keep the documented columns** (`pick` raises if one is missing).
# 2. **Keep tickers as text, and treat empty text as missing.** Hong Kong's
#    `"00700"` would lose its zeros as a number, and some Japanese codes
#    (`"285A"`) contain letters.
# 3. **De-duplicate on `ticker`**, the natural key. If the data refreshes while
#    you page, a stock can slide from page 2 to page 3 and arrive twice.
# 4. **Coerce to numbers** with `pd.to_numeric(errors="coerce")`, and count how
#    many values that turned into NaN.
# 5. **One line per company.** A ticker is a *listing*, not a company. The
#    screen can list one company several times, and every line carries the
#    company's market cap and fundamentals: two share classes (`GOOGL` and
#    `GOOG`, `BRK-A` and `BRK-B`), Hong Kong's renminbi counters (`80700`
#    "腾讯控股-R" beside `00700`), and preferred shares or notes that trade like
#    bonds. Left in, they count one company twice and add near-copies to every
#    model. Two counted rules:
#    - (a) **same company name** (after removing Hong Kong's `-R` counter
#      suffix): keep the line with the largest turnover, the main share;
#    - (b) **a liquidity floor**: a line whose turnover is below 1% of the
#      sample's median is a preferred share, a note or a secondary counter,
#      not the company's main share. We drop it.
# 6. **Placeholder zeros.** An exact `0.0` in `revenue_growth` means "not
#    computed", not "no growth" (see the units table). We count those values and
#    turn them into NaN, so the NaN policy (section 8) can fill and flag them.
# 7. **Suspect splits and bad prices.** After a stock split, a moving average
#    that is not adjusted still holds the old, higher prices, so the price
#    looks far *below* it, and per-share ratios can mix old and new units. We
#    flag a row when
#    - (a) on a day that moved less than 10%, it sits more than 20% below its
#      10-day average *and* more than 40% below its 50-day average: a recent
#      split pulls the price below every average at once, a real slide rarely
#      does so for one of the largest companies;
#    - (b) it sits more than 50% below its 50- or 200-day average with an E/P
#      above 0.5 (a P/E under 2); or
#    - (c) it sits more than 50% below its 200-day average but within 10% of
#      its 50-day average: the whole fall would have to have happened 50 to
#      200 days ago, followed by a flat stretch, which is far rarer among the
#      largest companies than a split the 200-day average has not caught up
#      with.
#
#    We blank its moving-average gaps and valuation ratios, list the tickers,
#    and the NaN policy then leaves the stock out of the models. Winsorising
#    alone would not help: a few broken rows *are* the extreme tail. A real
#    crash can trip these rules too, so read the list.
# 8. **Distrust graded ratios.** `ratio_quality` grades the valuation ratios.
#    If a row is graded anything other than `good` or `acceptable`, we blank its
#    `ep`, `bp` and `sp` (and count them) rather than feed doubtful numbers to a
#    model.
#
# The full NaN policy comes in section 8, once every endpoint is joined. Here
# we list the gaps and check them against the field reference: many fields are
# nullable by contract (a young listing has no 200-day average yet; the China
# screen never sends `previous_day_turnover`; the Hong Kong screen never sends
# `dividend_yield`). A gap in a field that should always be there is reported
# as unexpected.

# %%
ID_COLS = ["ticker", "company_name", "sector", "industry"]
NUM_COLS = ["price", "change_pct", "turnover", "previous_day_turnover", "turnover_vs_10d", "market_cap_usd",
            "ma10_excess", "ma50_excess", "ma200_excess", "ep", "bp", "sp",
            "profit_margin", "revenue_growth", "dividend_yield"]
FLAG_COLS = ["ratio_quality", "institutional_default"]
NULLABLE = {"industry", "change_pct", "previous_day_turnover", "ma10_excess", "ma50_excess", "ma200_excess",
            "ep", "bp", "sp", "profit_margin", "revenue_growth", "dividend_yield"}
TRUSTED_RATIOS = {"good", "acceptable"}
CURRENCY = {"us": "USD", "cn": "CNY", "jp": "JPY", "hk": "HKD"}[MARKET]     # the unit of turnover and price


def local(value, digits: int = 2) -> str:
    """An amount in the market's own currency: 2417869721 -> '2.42B CNY'."""
    return "n/a" if pd.isna(value) else money(value, digits).replace("$", "") + f" {CURRENCY}"


PRICE_FIELDS = ["ma10_excess", "ma50_excess", "ma200_excess", "ep", "bp", "sp"]   # blanked by step 7
LIQUIDITY_FLOOR = 0.01     # step 5b: a line trading under 1% of the median turnover is not a company's main share

screen = pick(screen_raw, ID_COLS + NUM_COLS + FLAG_COLS)               # step 1
screen["ticker"] = screen["ticker"].astype(str)                         # step 2
for col in ID_COLS:
    screen[col] = screen[col].where(screen[col].astype(str).str.strip() != "")   # "" -> NaN
n_screen_rows = len(screen)                                             # step 3
screen = screen.drop_duplicates(subset="ticker", keep="first").reset_index(drop=True)
n_tickers = len(screen)
missing_before = screen[NUM_COLS].isna().sum()                          # step 4
for col in NUM_COLS:
    screen[col] = pd.to_numeric(screen[col], errors="coerce")
coerced = screen[NUM_COLS].isna().sum() - missing_before

# Step 5a: one line per company. "腾讯控股-R" -> "腾讯控股", "阿里巴巴-WR" -> "阿里巴巴-W" (Hong Kong RMB counters).
company_key = (screen["company_name"].astype("string").str.strip()
               .str.replace(r"-(S?W?)R$", r"-\1", regex=True).str.rstrip("-").str.casefold())
named = company_key.notna()                                             # a missing name never matches another
keep = (screen[named].assign(key=company_key[named])
        .sort_values("turnover", ascending=False, kind="stable", na_position="last")   # the most traded line first
        .drop_duplicates(subset="key", keep="first").index)
same_company = screen[named & ~screen.index.isin(keep)]
screen = screen[~named | screen.index.isin(keep)]                       # the original (market cap) order is kept
n_companies = len(screen)
# Step 5b: the liquidity floor, relative to this sample's median turnover.
floor = LIQUIDITY_FLOOR * screen["turnover"].median()
thin = screen[screen["turnover"] < floor]
screen = screen.drop(index=thin.index).reset_index(drop=True)
dropped_lines = pd.concat([same_company.assign(reason="another line of the same company"),
                           thin.assign(reason=f"turnover below {LIQUIDITY_FLOOR:.0%} of the median")])

placeholder = screen["revenue_growth"].eq(0)                            # step 6
N_PLACEHOLDER = int(placeholder.sum())
screen.loc[placeholder, "revenue_growth"] = np.nan

split_a = ((screen["ma10_excess"] < -0.20) & (screen["ma50_excess"] < -0.40)               # step 7
           & (screen["change_pct"].abs() < 0.10))
split_b = (screen[["ma50_excess", "ma200_excess"]].min(axis=1) < -0.50) & (screen["ep"] > 0.50)
split_c = (screen["ma200_excess"] < -0.50) & (screen["ma50_excess"].abs() < 0.10)
suspect = split_a | split_b | split_c
SUSPECT_SPLIT = screen.loc[suspect, ["ticker", "company_name", "change_pct", *PRICE_FIELDS]].assign(
    rule=["+".join(r for r, hit in zip("abc", hits) if hit) for hits in zip(split_a[suspect], split_b[suspect],
                                                                           split_c[suspect])])
screen.loc[suspect, PRICE_FIELDS] = np.nan

doubtful = ~screen["ratio_quality"].isin(TRUSTED_RATIOS)                # step 8
screen.loc[doubtful, ["ep", "bp", "sp"]] = np.nan

print(f"Funnel: {n_screen_rows:,} rows -> {n_tickers:,} tickers -> {n_companies:,} companies (one line each) -> "
      f"{len(screen):,} after the liquidity floor (median turnover {local(screen['turnover'].median())}, "
      f"floor {local(floor)}).")
print(f"Coercion: {int(coerced.sum())} values were not numbers and became NaN. "
      f"Placeholder zeros: {N_PLACEHOLDER} revenue_growth values of exactly 0.0 became NaN. "
      f"Suspect splits or bad prices: {len(SUSPECT_SPLIT)} rows had their moving-average gaps and ratios blanked. "
      f"Ratio grades: {screen['ratio_quality'].value_counts().to_dict()}; {int(doubtful.sum())} rows had their "
      "ratios blanked.")
if len(screen) > 1:
    print("Rows arrive largest market cap first:", bool(screen["market_cap_usd"].is_monotonic_decreasing))
if not dropped_lines.empty:
    print(f"Lines dropped in step 5 ({len(dropped_lines)}):")
    display(dropped_lines[["ticker", "company_name", "reason", "market_cap_usd", "turnover"]]
            .style.format({"market_cap_usd": money, "turnover": local}).hide(axis="index"))
if not SUSPECT_SPLIT.empty:
    print(f"Suspect splits or bad prices in step 7 ({len(SUSPECT_SPLIT)}), values as published:")
    display(SUSPECT_SPLIT.style.format({c: "{:+.1%}" for c in ["change_pct", "ma10_excess", "ma50_excess",
                                                              "ma200_excess"]}
                                       | {c: "{:.3f}" for c in ["ep", "bp", "sp"]}, na_rep="n/a").hide(axis="index"))

gaps = screen.isna().sum()
gaps = pd.DataFrame({"missing": gaps, "missing_share": gaps / max(len(screen), 1),
                     "nullable_by_contract": gaps.index.isin(sorted(NULLABLE))})
gaps = gaps[gaps["missing"] > 0].sort_values("missing", ascending=False)
unexpected = gaps.index[~gaps["nullable_by_contract"]].tolist()
print(f"{len(gaps)} columns have gaps; unexpected gaps: {', '.join(unexpected) if unexpected else 'none'}.")
display(gaps.style.format({"missing_share": "{:.1%}"}))

# %% [markdown]
# ### Chart: among the largest companies, does size go with trading?
#
# Turnover and market cap span orders of magnitude, so both axes are
# logarithmic: each gridline is ten times the one before. The dashed line is the
# least-squares fit in log-log space. Its slope is an *elasticity*: a slope of
# 0.8 means that a company 10× larger trades about 10^0.8 ≈ 6× more.

# %%
size = screen.dropna(subset=["market_cap_usd", "turnover"])
size = size[(size["market_cap_usd"] > 0) & (size["turnover"] > 0)].copy()
if len(size) < 3:
    display(Markdown("> Too few stocks with both market cap and turnover to draw this chart."))
else:
    lx, ly = np.log10(size["market_cap_usd"]), np.log10(size["turnover"])
    r_size = float(np.corrcoef(lx, ly)[0, 1])
    slope, intercept = np.polyfit(lx, ly, 1)
    grid = np.linspace(lx.min(), lx.max(), 50)
    custom = np.column_stack([size["ticker"], size["company_name"].map(shorten),
                              size["market_cap_usd"].map(money), size["turnover"].map(local)])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=size["market_cap_usd"], y=size["turnover"], mode="markers", name="One stock",
        marker=dict(color=COLOR, size=7, opacity=0.65), customdata=custom,
        hovertemplate="<b>%{customdata[0]}</b> %{customdata[1]}<br>Market cap %{customdata[2]}"
                      "<br>Turnover %{customdata[3]}<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=10 ** grid, y=10 ** (intercept + slope * grid), mode="lines", name=f"Least-squares fit (slope {slope:.2f})",
        line=dict(color=INK, dash="dash", width=2), hoverinfo="skip"))
    resid = ly - (intercept + slope * lx)                             # distance above (+) or below (-) the line
    top_names = size.loc[resid.abs().nlargest(LABEL_TOP).index]          # the stocks furthest from the fit
    label_points(fig, np.log10(top_names["market_cap_usd"]).to_numpy(), np.log10(top_names["turnover"]).to_numpy(),
                 top_names["ticker"].to_numpy())                     # annotations on log axes take log10 positions
    fig.update_xaxes(type="log", title_text="Market cap (USD, log scale)", tickprefix="$", exponentformat="B")
    fig.update_yaxes(type="log", title_text=f"Turnover in the session ({CURRENCY}, log scale)", exponentformat="B")
    if r_size >= 0.3:
        headline = f"Bigger companies trade more: log turnover and log market cap correlate at r = {r_size:.2f}"
    elif r_size >= 0.1:
        headline = f"Among the largest companies, size only loosely predicts trading (r = {r_size:.2f})"
    else:
        headline = f"Among the largest companies, size says little about trading (r = {r_size:.2f})"
    title, top = chart_title(
        headline, f"{len(size):,} largest companies, one line each · screen session {SCREEN_AS_OF} · on the fitted "
                  f"line, a company 10× larger trades about {10 ** slope:.1f}× more · labels: the {LABEL_TOP} stocks "
                  "furthest from the line")
    fig.update_layout(title=title, height=520, margin=dict(t=top, b=110), legend=legend_below(520, top, 110))
    fig.show()

    twin = size[["ticker", "company_name", "sector", "market_cap_usd", "turnover"]].assign(
        turnover_vs_fit=10 ** resid)                                   # 2.0 = twice the turnover the line predicts
    print(f"Table twin: the {len(twin):,} stocks behind the chart, largest first (first 10 shown).")
    display(twin.head(10).style.format({"market_cap_usd": money, "turnover": local, "turnover_vs_fit": "{:.2f}×"})
            .hide(axis="index"))

# %% [markdown]
# **How to read this.** Each dot is a company (its main line). Further right
# means a bigger company; higher up means more money traded in the session.
# Across a whole market the cloud rises steeply, because big companies trade
# more almost by definition. Inside the largest ~300 the range of sizes is
# narrower, so the link is weaker. The labelled dots sit furthest from the
# dashed line: far above it, a company traded much more than its size suggests
# (news, index events, heavy attention); far below, it was quiet for its size.
# Step 5 of the cleaning matters here: second share classes, renminbi counters,
# preferreds and notes carry the parent's market cap but trade a sliver of its
# volume, so left in they would sit far below the line and weaken the link
# without saying anything about trading in companies. The table twin's
# `turnover_vs_fit` column is the same distance as a multiple (2.0× = twice the
# turnover the line predicts).
#
# This picture matters later. Two features that move together closely fight
# over the same information in a regression. Section 10 measures that overlap
# with the VIF.
#
# **Caveats.**
#
# - The chart covers only the largest names of the market, by design.
# - Turnover is in the market's **local currency** and market cap in **US
#   dollars**. Within one market that is harmless (the exchange rate is the same
#   for every stock, so on a log scale it only shifts the cloud); across markets,
#   compare turnover only after converting it.
# - One session's turnover is noisy. A stock can trade ten times its usual
#   amount on a single news day; `turnover_vs_10d` measures exactly that.

# %% [markdown]
# ## 4. Realtime: the session board (optional)
#
# **What it is for.** The realtime board lists the 50 most-traded names of the
# current session, or of the last one when the market is closed, with each
# name's session return so far and its projected turnover. "Realtime" names a
# current-session board, not a tick-by-tick feed.
#
# **Its role in this lab is small, on purpose.** Fifty rows cannot feed a model
# of 300 stocks, so the board is only *left-joined* for exploring. It also
# teaches a lesson about units and definitions: the board's
# `intraday_return_pct` is a **percent** (−1.19 = −1.19%), measured differently
# from the screen's `change_pct` (a **fraction**, close versus previous close).
# Never mix the two in one column. The chart below shows why.
#
# This section is optional, so it uses `sf_try`: if the board is unavailable,
# the notebook prints a note and carries on without it.

# %%
RT_COLS = ["rank", "ticker", "company_name", "price", "intraday_return_pct", "turnover_per_second",
           "accumulated_turnover", "projected_turnover", "projected_vs_yesterday", "previous_day_turnover"]
rt_payload = sf_try(f"/api/v1/markets/{MARKET}/realtime")
rt_meta, RT_SESSION = {}, None
if rt_payload is not None:
    show_freshness(rt_payload, "Realtime:")
    rt_meta = rt_payload["data"]
    if rt_meta["as_of_local"]:
        RT_SESSION = str(pd.Timestamp(rt_meta["as_of_local"]).date())       # the session date in local time
        as_of_utc = pd.to_datetime(rt_meta["as_of_utc"], utc=True)          # parse timestamps as UTC
        print(f"Board session {RT_SESSION} (snapshot {as_of_utc:%Y-%m-%d %H:%M} UTC, market "
              f"{rt_meta['market_status']}) vs screen session {SCREEN_AS_OF}: "
              f"{'the same session' if RT_SESSION == SCREEN_AS_OF else 'different sessions'}.")
SAME_SESSION = RT_SESSION == SCREEN_AS_OF

# %% [markdown]
# **Raw preview.**

# %%
rt_raw = to_frame(rt_payload, "realtime") if rt_payload is not None else pd.DataFrame()
print(f"{len(rt_raw)} rows")
rt_raw.head()

# %% [markdown]
# ### Cleaning the realtime board
#
# Documented columns, tickers as text, numbers coerced (and counted), one row
# per ticker. An empty board is normal (before a session's first trades, or
# when the endpoint is unavailable): the table simply stays empty.

# %%
RT_NUM = [c for c in RT_COLS if c not in ("ticker", "company_name")]
rt = pick(rt_raw, RT_COLS)
rt["ticker"] = rt["ticker"].astype(str)
missing_before = rt[RT_NUM].isna().sum()
for col in RT_NUM:
    rt[col] = pd.to_numeric(rt[col], errors="coerce")
coerced = int((rt[RT_NUM].isna().sum() - missing_before).sum())
n_before = len(rt)
rt = rt.drop_duplicates(subset="ticker", keep="first").reset_index(drop=True)
in_screen = int(rt["ticker"].isin(screen["ticker"]).sum())
print(f"{n_before} rows -> {len(rt)} after de-duplication; {coerced} values became NaN; "
      f"{in_screen} of {len(rt)} board names are among the {len(screen):,} largest stocks.")

# %% [markdown]
# ### Chart: the board's session return is not the screen's daily change
#
# For the names on both tables we plot the screen's `change_pct` (times 100,
# so both axes are in percent) against the board's `intraday_return_pct`. If
# the two measured the same thing, every dot would sit on the dashed diagonal.

# %%
both = rt.merge(screen[["ticker", "change_pct"]], on="ticker", how="inner", validate="one_to_one")
both = both.dropna(subset=["intraday_return_pct", "change_pct"])
both["screen_change_pct"] = 100 * both["change_pct"]                     # fraction -> percent
both["difference_pp"] = both["intraday_return_pct"] - both["screen_change_pct"]
if len(both) < 5:
    display(Markdown(f"> Only {len(both)} board names are among the largest stocks with both returns (market status "
                     f"{rt_meta.get('market_status', 'n/a')}, data quality {rt_meta.get('data_quality', 'n/a')}). "
                     "That is normal for an empty board or a quiet session; there is nothing to compare."))
else:
    r_rt = float(np.corrcoef(both["screen_change_pct"], both["intraday_return_pct"])[0, 1])
    typical = float(both["difference_pp"].abs().median())
    if SAME_SESSION:
        headline = (f"Same session, two measurements: on a typical name the board's session return differs from the "
                    f"screen's daily change by {typical:.1f} pp (r = {r_rt:.2f})")
    else:
        headline = (f"Different sessions: the board shows {RT_SESSION}, the screen {SCREEN_AS_OF}, so the two returns "
                    f"describe different days (r = {r_rt:.2f})")
    lo = float(min(both["screen_change_pct"].min(), both["intraday_return_pct"].min())) - 0.5
    hi = float(max(both["screen_change_pct"].max(), both["intraday_return_pct"].max())) + 0.5
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode="lines", name="Equal values (y = x)",
                             line=dict(color=INK, dash="dash", width=1.5), hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=both["screen_change_pct"], y=both["intraday_return_pct"], mode="markers", name="One stock on both tables",
        marker=dict(color=COLOR, size=9, opacity=0.75),
        customdata=np.column_stack([both["ticker"], both["company_name"].map(shorten), both["rank"],
                                    both["difference_pp"]]),
        hovertemplate="<b>%{customdata[0]}</b> %{customdata[1]} (board rank %{customdata[2]})<br>Screen daily change "
                      "%{x:+.2f}%<br>Board session return %{y:+.2f}%<br>Difference %{customdata[3]:+.2f} pp"
                      "<extra></extra>"))
    far = both.loc[both["difference_pp"].abs().nlargest(LABEL_TOP).index]
    label_points(fig, far["screen_change_pct"].to_numpy(), far["intraday_return_pct"].to_numpy(),
                 far["ticker"].to_numpy())
    fig.update_xaxes(title_text="Screen daily change, change_pct × 100 (%)", ticksuffix="%", range=[lo, hi])
    fig.update_yaxes(title_text="Board session return (%)", ticksuffix="%", range=[lo, hi])
    title, top = chart_title(headline, f"{len(both)} names on the realtime board and in the screen sample · screen "
                                       f"session {SCREEN_AS_OF}, board session {RT_SESSION} (status "
                                       f"{rt_meta['market_status']}, quality {rt_meta['data_quality']}) · mean "
                                       f"difference {both['difference_pp'].mean():+.2f} pp")
    fig.update_layout(title=title, height=540, margin=dict(t=top, b=110), legend=legend_below(540, top, 110))
    fig.show()
    display(both[["rank", "ticker", "company_name", "screen_change_pct", "intraday_return_pct", "difference_pp"]]
            .sort_values("rank").head(10).style.format({"screen_change_pct": "{:+.2f}%",
                                                         "intraday_return_pct": "{:+.2f}%",
                                                         "difference_pp": "{:+.2f}"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Dots on the diagonal would mean "same number". When the
# board and the screen describe the same session, the dots line up roughly
# along the diagonal but scatter around it, often shifted to one side: the two
# returns are computed differently, so they rarely agree exactly. When the board
# already describes a newer session (an open market), the two returns belong to
# different days and the cloud has no reason to follow the diagonal at all.
#
# **Caveats.**
#
# - Use one definition of "return" per analysis. This lab models the screen's
#   `change_pct`; the board's columns stay in the feature table for exploring
#   only (section 8).
# - The board is a top 50 by projected turnover, so every name on it is busy:
#   these dots are not a random sample of the market.
# - Money columns on the board are in local currency, like the screen's
#   turnover.

# %% [markdown]
# ## 5. Whales: from six boards to one signal per stock
#
# **What it is for.** Large investors must disclose what they hold. SurgeFlow
# turns those filings into six top-20 **boards**: consensus (many funds own it),
# conviction (one fund bet big), crowdedness (share of funds that own it),
# position delta (bought or sold since the last filing), network (centrality in
# the web of shared holders) and lead-lag (`ll_predictive`: gained owners and
# weight). Notebook 02 explores each board in depth. Here we turn them into one
# simple **per-stock feature**: on how many boards does the stock appear?
#
# **Freshness.** `show_freshness` only sees `market` here. The dates that matter
# are `data.as_of` (when SurgeFlow built the bundle) and each row's
# `as_of_date`, the date the holdings refer to. US 13F filings arrive up to 45
# days after quarter end, so whale holdings are usually weeks or months older
# than the prices. The whale section is not essential to the lab, so it uses
# `sf_try`: if the endpoint is unavailable, every stock simply gets 0 boards.

# %%
wh_payload = sf_try(f"/api/v1/markets/{MARKET}/whales")
signals = {}
if wh_payload is not None:
    show_freshness(wh_payload, "Whales:")
    wh = wh_payload["data"]
    board_block = wh["signal_board"]
    signals = board_block["signals"]
    print(f"Bundle built {wh['as_of']} · method {wh['method']} · signal board as of {board_block['as_of']}.")

# %% [markdown]
# **Raw preview.** The boards are a **dictionary of six lists**, not one list.
# That is why the helper `records(payload, "whales")` returns an empty list
# here; we loop over the boards instead.

# %%
if wh_payload is not None:
    print("records(wh_payload, 'whales') ->", records(wh_payload, "whales"), "(the boards are a dict, not a list)")
    display(pd.DataFrame({"board": list(signals), "rows": [len(rows) for rows in signals.values()]})
            .set_index("board").T)
pd.DataFrame(signals.get("consensus", [])).head()

# %% [markdown]
# ### Cleaning: six boards into one row per stock
#
# For each board we keep the common fields plus its headline score, keep
# tickers as text, coerce the score to a number, parse `as_of_date` as UTC, and
# de-duplicate on `ticker` within the board. Then we **pivot**: one row per
# stock, one column per board score, plus `whale_boards`, the number of boards
# that list the stock.
#
# **A board must rank something to count.** A top 20 is only a signal if its
# score differs between the rows. When every score on a board is the same (for
# example a position-delta board where every `delta_z` is 0 because no fund
# bought or sold), its "top 20" is an arbitrary tie order. We keep such a
# board's scores for exploring, but leave it out of `whale_boards` and say so.
# `whale_boards` therefore runs from 0 to the number of *informative* boards
# today (at most 6).

# %%
COMMON_COLS = ["market", "ticker", "quarter", "as_of_date", "methodology_version", "updated_at", "stock_name"]
BOARD_SCORE = {"consensus": "consensus_score", "conviction": "ticker_conviction_score",
               "crowdedness": "crowdedness_pct", "position_delta": "delta_z",
               "network": "eigenvector_centrality", "ll_predictive": "ll_score_z"}

parts, board_check = [], []
for board_name, score in (BOARD_SCORE.items() if wh_payload is not None else []):
    part = pick(pd.DataFrame(signals[board_name]), COMMON_COLS + [score])   # a missing board is a contract change
    part["ticker"] = part["ticker"].astype(str)
    part["value"] = pd.to_numeric(part[score], errors="coerce")
    part["as_of_date"] = pd.to_datetime(part["as_of_date"], utc=True, errors="coerce")
    part = part.drop_duplicates(subset="ticker", keep="first")
    distinct = int(part["value"].nunique(dropna=True))
    informative = distinct > 1 and float(part["value"].abs().sum()) > 0     # all-equal or all-zero scores rank nothing
    if not part.empty and not informative:
        print(f"{board_name}: every {score} is {part['value'].iloc[0]:g} today, so its top {len(part)} is an "
              "arbitrary tie order. It is left out of whale_boards (its scores stay in the table for exploring).")
    board_check.append({"board": board_name, "score": score, "rows": len(part), "distinct_scores": distinct,
                        "counted_in_whale_boards": informative})
    parts.append(part.assign(board=board_name, score=score, informative=informative)
                 [["board", "score", "ticker", "stock_name", "as_of_date", "value", "informative"]])
whale_long = (pd.concat(parts, ignore_index=True) if parts else
              pd.DataFrame(columns=["board", "score", "ticker", "stock_name", "as_of_date", "value", "informative"]))
board_check = pd.DataFrame(board_check, columns=["board", "score", "rows", "distinct_scores",
                                                 "counted_in_whale_boards"])
INFORMATIVE_BOARDS = board_check.loc[board_check["counted_in_whale_boards"], "board"].tolist()
N_BOARDS = len(INFORMATIVE_BOARDS)
FEATURE_LABELS["whale_boards"] = f"Whale boards listing it (0-{N_BOARDS})"

if whale_long.empty:
    whale_wide = pd.DataFrame(columns=["ticker", *BOARD_SCORE.values(), "whale_boards"])
else:
    whale_wide = (whale_long.pivot(index="ticker", columns="score", values="value")
                  .reindex(columns=list(BOARD_SCORE.values())))
    counted = whale_long[whale_long["informative"].astype(bool)]
    whale_wide["whale_boards"] = counted.groupby("ticker")["board"].nunique().reindex(whale_wide.index).fillna(0)
    whale_wide = whale_wide.reset_index()
whale_wide["ticker"] = whale_wide["ticker"].astype(str)

held = whale_long["as_of_date"].dropna()
HELD_AS_OF = held.mode().iloc[0] if not held.empty else None
in_screen = int(whale_wide["ticker"].isin(screen["ticker"]).sum())
display(board_check.set_index("board"))
print(f"{len(whale_long)} board rows -> {len(whale_wide)} distinct stocks; {in_screen} of them are among the "
      f"{len(screen):,} largest companies. whale_boards counts {N_BOARDS} of {len(board_check)} boards "
      f"({', '.join(INFORMATIVE_BOARDS) or 'none'}), so it runs from 0 to {N_BOARDS}.")
if HELD_AS_OF is not None:
    print(f"Holdings refer to {HELD_AS_OF:%Y-%m-%d}: {(TODAY - HELD_AS_OF).days} days before today.")
whale_wide.head()

# %% [markdown]
# ### Chart: are the whales' names the biggest of the big?
#
# Each box summarises the market caps of the stocks listed on 0, 1, 2 or 3+
# boards. The box spans the middle half of the stocks, the line inside is the
# median, and the dots are the stocks themselves. The y-axis is logarithmic.

# %%
wb = screen[["ticker", "company_name", "market_cap_usd"]].merge(
    whale_wide[["ticker", "whale_boards"]], on="ticker", how="left", validate="one_to_one")
wb["whale_boards"] = pd.to_numeric(wb["whale_boards"], errors="coerce").fillna(0)   # not on a top-20 board: 0
wb = wb[wb["market_cap_usd"] > 0]
GROUPS = ["0 boards", "1 board", "2 boards", "3+ boards"]
wb["group"] = pd.cut(wb["whale_boards"], [-0.5, 0.5, 1.5, 2.5, 6.5], labels=GROUPS).astype(str)
on_boards = wb[wb["whale_boards"] > 0]
if on_boards.empty or len(on_boards) == len(wb):
    display(Markdown("> Every stock sits in the same group (no whale-board names among the largest stocks, or only "
                     "those), so there is nothing to compare."))
else:
    med_on, med_off = on_boards["market_cap_usd"].median(), wb.loc[wb["whale_boards"] == 0, "market_cap_usd"].median()
    fig = go.Figure(go.Box(
        x=wb["group"], y=wb["market_cap_usd"], boxpoints="all", jitter=0.45, pointpos=0, name="Stocks",
        marker=dict(color=COLOR, size=5, opacity=0.55), line=dict(color=INK_2, width=1.5),
        fillcolor="rgba(0,0,0,0)", showlegend=False,
        customdata=np.column_stack([wb["ticker"], wb["company_name"].map(shorten), wb["market_cap_usd"].map(money)]),
        hovertemplate="<b>%{customdata[0]}</b> %{customdata[1]}<br>%{x}<br>Market cap %{customdata[2]}"
                      "<extra></extra>"))
    fig.update_xaxes(title_text="Number of whale boards listing the stock",
                     categoryorder="array", categoryarray=GROUPS)
    fig.update_yaxes(type="log", title_text="Market cap (USD, log scale)", tickprefix="$", exponentformat="B")
    ratio = med_on / med_off if med_off > 0 else np.nan
    # One "$" per title: notebook front ends that load MathJax read text between two "$" signs as maths.
    headline = (f"Even among the largest companies, whale-board names are bigger: median {money(med_on, 1)}, "
                f"{ratio:.1f}× the rest" if ratio >= 1.25 else
                f"Among the largest companies, whale-board names are about as big as the rest (median "
                f"{money(med_on, 1)}, {ratio:.1f}× the others)")
    title, top = chart_title(
        headline,
        f"{len(on_boards)} of {len(wb):,} stocks appear on at least one of the {N_BOARDS} informative top-20 "
        f"boards · holdings dated " + (f"{HELD_AS_OF:%Y-%m-%d}" if HELD_AS_OF is not None else "n/a")
        + f" · bundle {wh['as_of']}")
    fig.update_layout(title=title, height=470, margin=dict(t=top))
    fig.show()
    display(wb.groupby("group").agg(stocks=("ticker", "size"), median_market_cap=("market_cap_usd", "median"))
            .reindex(GROUPS).dropna().style.format({"stocks": "{:,.0f}", "median_market_cap": money}))

# %% [markdown]
# **How to read this.** Compare the median lines from left to right. If they
# climb, the stocks that whales agree on, crowd into or trade are mostly the
# very largest companies. That is a warning for the regression: a "whale
# effect" can simply be a size effect in disguise. Putting market cap in the
# same regression lets us separate the two.
#
# **Caveats.**
#
# - Each board is a top 20 of the whole market. "0 boards" means "not in any top
#   20", not "no institutional owners".
# - Only boards whose scores differ count (see the board table above). A board
#   left out today, such as a position-delta board on which no fund bought or
#   sold, can count again after the next filings.
# - Holdings refer to the report date shown in the subtitle (a quarter end for
#   US 13F); filings arrive up to 45 days later, so they are often months old.
# - Read notebook 02 before you trust any single board: each one has its own
#   validation status (`signal_gate_status`).

# %% [markdown]
# ## 6. ML clusters: SurgeFlow's own labels
#
# **What it is for.** Once a day per market, SurgeFlow describes every stock with
# a few dozen features (returns, volatility, drawdowns, valuation, growth,
# leverage, ...), compresses them with PCA, and groups the stocks with a
# consensus of three clustering algorithms. The result is a map of which stocks
# behave alike right now. In this lab it is a **reference**: in section 12 we
# build our own clusters and compare.
#
# **Per-stock labels are sparse.** The v1 payload names the cluster of only a
# few stocks: the 8 **representative** tickers of each cluster (the most typical
# members), the **anomaly** watch list (the least typical) and the stocks that
# **switched** cluster since the last run. That is a little over a hundred
# names out of thousands, and they are spread over the whole market, small
# companies included. So we must **measure how many land among our largest
# companies** before we compare stock by stock. In practice that comparison
# (an ARI on shared stocks, section 12.5) is rarely possible: at the time of
# writing only `jp` comes close, and for the other markets just a handful of
# labelled stocks are large caps.
#
# **Every cluster also discloses its `sector_mix`**: the member counts of its
# largest sectors. That needs no per-stock labels, so section 12.6 always
# compares SurgeFlow's clusters with ours at the cluster level, by sector mix.
#
# **Freshness lives in `data.run`.** `show_freshness` only finds `market`, so
# we print the run's date, age and `stale` flag ourselves. `run.stale` and
# `run.age_days` count **calendar days**, not trading sessions. During an
# exchange holiday (China's National Day closure, 1-7 October 2026, reopening
# on 8 October, for example) a correct run can be flagged stale; SurgeFlow
# calls this a labelling issue on its side, and the data itself is correct.
# So do not trust the flag alone: compare `run.as_of_date` with the market's
# last trading session. Here that is the screen's session (`SCREEN_AS_OF`,
# section 3), at no extra request; health's
# `markets.<market>.published_session_date` (notebook 02) gives the same check.
# **Empty is normal**: before a market's first run, `data.available` is
# `false`. The endpoint is optional for the lab, so it uses `sf_try`.

# %%
ml_payload = sf_try(f"/api/v1/markets/{MARKET}/ml/clusters")
ml = ml_payload["data"] if ml_payload is not None else {"available": False}
ML_OK = bool(ml["available"])
run, quality = {}, {}
if ml_payload is not None:
    show_freshness(ml_payload, "ML clusters:")
if ML_OK:
    run, quality = ml["run"], ml["run"]["quality"]
    finished = pd.to_datetime(run["run_finished_at"], utc=True)
    # The yardstick for the run's date is the market's last session (the screen's), not the calendar-day flag.
    run_day, last_day = pd.to_datetime(run["as_of_date"], errors="coerce"), pd.to_datetime(SCREEN_AS_OF, errors="coerce")
    if pd.isna(run_day) or pd.isna(last_day):
        dated = "Compare `as_of_date` with the market's last trading session before you trust the flag."
    elif run_day == last_day:
        dated = ("That is the screen's session, the market's last published one, so the map is as recent as our "
                 "sample" + ("; the flag reflects the calendar days since then (an exchange holiday, for example), "
                             "not a missing session." if run["stale"] else "."))
    elif run_day < last_day:
        dated = f"The screen already describes a later session ({SCREEN_AS_OF}), so the map is older than our sample."
    else:
        dated = f"The screen describes an earlier session ({SCREEN_AS_OF}); check both dates before you compare."
    display(Markdown(
        f"> Run of **{run['as_of_date']}** ({plural(run['age_days'], 'calendar day')} ago), finished "
        f"{finished:%Y-%m-%d %H:%M} UTC. SurgeFlow {'flags it **stale**' if run['stale'] else 'does not flag it stale'}; "
        f"`stale` and `age_days` count calendar days, not trading sessions. {dated} "
        f"k = {quality['k']} clusters over {run['clustered_ticker_count']:,} stocks; silhouette "
        f"{quality['silhouette']:.3f} in the model's own feature space; balance cap {quality['balance_cap']:.0%}."))
elif ml_payload is not None:
    display(Markdown(f"> No ML run for {MARKET_NAMES[MARKET]} yet ({ml.get('message') or 'no message'}). "
                     "The comparisons with SurgeFlow in section 12 will be skipped."))

# %% [markdown]
# **Raw preview.**

# %%
clusters_raw = pd.DataFrame(records(ml_payload, "ml_clusters") if ML_OK else [])
anomalies_raw = pd.DataFrame(records(ml_payload, "ml_anomalies") if ML_OK else [])
changed_raw = pd.DataFrame(ml["changed_group"] if ML_OK else [])
print(f"{len(clusters_raw)} clusters, {len(anomalies_raw)} anomaly-watch rows, {len(changed_raw)} switchers.")
clusters_raw.head()

# %% [markdown]
# ### Cleaning: one label per stock
#
# 1. Keep the documented columns and treat `cluster_id` as a **label, not a
#    position**: SurgeFlow keeps IDs stable between runs, so they skip numbers
#    (0, 3, 2, 9, ...). We write them as `#3`.
# 2. Collect labelled tickers from the three sources into one long table.
# 3. A ticker can appear twice (a representative that is also an anomaly). We
#    keep one label per ticker, by precedence: representative, then anomaly,
#    then switcher. We also count conflicts (the same ticker with two different
#    clusters); there should be none.

# %%
clusters = pick(clusters_raw, ["cluster_id", "cluster_name", "ticker_count", "sector_mix", "representative_tickers"])
clusters["cluster_id"] = pd.to_numeric(clusters["cluster_id"], errors="coerce").astype("Int64")
clusters["ticker_count"] = pd.to_numeric(clusters["ticker_count"], errors="coerce")
clusters = clusters.drop_duplicates(subset="cluster_id").sort_values("ticker_count", ascending=False)
clusters = clusters.reset_index(drop=True)
clusters["label"] = "#" + clusters["cluster_id"].astype(str)
NAME = dict(zip(clusters["cluster_id"], clusters["cluster_name"]))      # id -> name
LABEL = dict(zip(clusters["cluster_id"], clusters["label"]))            # id -> "#3"

anomalies = pick(anomalies_raw, ["ticker", "cluster_id", "anomaly_score"])
changed = pick(changed_raw, ["ticker", "from_cluster_id", "to_cluster_id", "cluster_confidence"])
SOURCES = ["representative", "anomaly", "switched"]
sf_long = pd.concat([
    pd.DataFrame([{"ticker": str(t), "sf_cluster_id": cid, "sf_source": "representative"}
                  for cid, tickers in zip(clusters["cluster_id"], clusters["representative_tickers"])
                  for t in tickers], columns=["ticker", "sf_cluster_id", "sf_source"]),
    anomalies.assign(sf_source="anomaly").rename(columns={"cluster_id": "sf_cluster_id"})
    [["ticker", "sf_cluster_id", "sf_source"]],
    changed.assign(sf_source="switched").rename(columns={"to_cluster_id": "sf_cluster_id"})
    [["ticker", "sf_cluster_id", "sf_source"]],
], ignore_index=True)
sf_long["ticker"] = sf_long["ticker"].astype(str)
sf_long["sf_cluster_id"] = pd.to_numeric(sf_long["sf_cluster_id"], errors="coerce")
conflicts = int((sf_long.groupby("ticker")["sf_cluster_id"].nunique() > 1).sum())
sf_labels = sf_long.dropna(subset=["sf_cluster_id"]).drop_duplicates(subset="ticker", keep="first")
sf_labels = sf_labels[sf_labels["sf_cluster_id"].isin(list(LABEL))].reset_index(drop=True)   # a retired id is no label
sf_labels["in_sample"] = sf_labels["ticker"].isin(screen["ticker"])
N_LABELLED_IN_SAMPLE = int(sf_labels["in_sample"].sum())
verb = "is" if N_LABELLED_IN_SAMPLE == 1 else "are"
print(f"{len(sf_long)} label rows -> {len(sf_labels)} labelled tickers ({conflicts} conflicting). "
      f"{N_LABELLED_IN_SAMPLE} of them {verb} among the {len(screen):,} largest companies "
      f"({N_LABELLED_IN_SAMPLE / max(len(screen), 1):.1%} of our sample).")
display(sf_labels.groupby("sf_source")["in_sample"].agg(labelled="size", in_our_sample="sum")
        .reindex(SOURCES).fillna(0).astype(int).T)

# %% [markdown]
# ### Chart: how many SurgeFlow labels reach our sample?
#
# One row per SurgeFlow cluster, largest first. The grey bar counts the stocks
# whose cluster the v1 payload names; the coloured bar counts those that are
# also among our largest companies. Hover a row for the cluster's full size.

# %%
if clusters.empty:
    display(Markdown("> No clusters came back, so there is nothing to chart."))
else:
    named = (sf_labels.groupby("sf_cluster_id")
             .agg(labelled=("ticker", "size"), in_sample=("in_sample", "sum"))
             .reindex(clusters["cluster_id"].astype(float), fill_value=0))
    named.index = clusters["cluster_id"]
    named["cluster_size"] = clusters.set_index("cluster_id")["ticker_count"]
    ticks = ["<b>" + LABEL[c] + "</b> " + wrap(NAME[c], 34) for c in named.index]
    seen, total_members = int(named["labelled"].sum()), float(clusters["ticker_count"].sum())

    fig = go.Figure()
    for column, name, colour in (("labelled", "Named in the v1 payload", MUTED),
                                 ("in_sample", f"... and among our {len(screen):,} largest stocks", COLOR)):
        fig.add_trace(go.Bar(
            y=ticks, x=named[column], orientation="h", name=name, marker_color=colour,
            customdata=named["cluster_size"],
            hovertemplate="%{y}<br>" + name + ": %{x} stocks<br>cluster size %{customdata:,} stocks<extra></extra>"))
    fig.update_xaxes(title_text="Labelled stocks (count)", rangemode="tozero")
    fig.update_yaxes(autorange="reversed", ticks="", title_text=None)
    verdict = ("enough for a stock-by-stock comparison in section 12 if they survive cleaning"
               if N_LABELLED_IN_SAMPLE >= MIN_LABELLED
               else f"too few for a stock-by-stock comparison (we need {MIN_LABELLED}), so section 12 compares "
                    "sector mixes")
    title, top = chart_title(
        f"SurgeFlow names the cluster of {seen:,} stocks; {N_LABELLED_IN_SAMPLE} of them {verb} among our "
        f"{len(screen):,} largest, {verdict}",
        f"{len(clusters)} SurgeFlow clusters with {total_members:,.0f} members in all · run "
        f"{run.get('as_of_date', 'n/a')} · labels from representatives, the anomaly watch and switchers")
    height = 230 + 58 * len(clusters)
    fig.update_layout(title=title, barmode="group", height=height, margin=dict(t=top, l=10, r=30, b=110),
                      legend=legend_below(height, top, 110) | dict(traceorder="normal"))
    fig.show()
    twin = named.rename(index=LABEL)
    twin.index.name = "cluster"
    twin.insert(0, "name", [NAME[c] for c in named.index])
    display(twin)

# %% [markdown]
# **How to read this.** Grey bars show how much of each cluster the payload
# reveals at all: a handful of names per cluster, out of hundreds or
# thousands of members. Coloured bars show how many of those are big enough to
# be in our sample. Representatives are chosen for being *typical*, not for
# being large, so with a sample of the largest companies the coloured bars are
# often short or missing. That is not a bug in the join; it is the limit of
# what v1 reveals, and the reason section 12.6 compares sector mixes instead.
#
# **Caveats.**
#
# - The full per-stock labels are not part of v1. This lab uses only what v1
#   gives you, and says so when it is not enough.
# - The labelled stocks are not a random sample: representatives are the most
#   typical members, anomalies the least typical.
# - The run date can differ from the screen session (see `run.as_of_date` and
#   the session check above; `run.stale` alone counts calendar days, not
#   trading sessions). A stock can change cluster between the two.
# - Cluster IDs are labels. Never use them as numbers or array positions.

# %% [markdown]
# ## 7. Factor portfolios: daily factor returns
#
# **What it is for.** A *factor* is a characteristic that tends to explain why
# groups of stocks move together: the market (ERP), size (SMB), value (HML),
# momentum (WML), profitability (RMW), investment (CMA) and liquidity (LIQ).
# SurgeFlow builds a portfolio for each one and, once a factor passes its
# publication gates, publishes a year of **daily returns** (`return_series`, a
# list of `{date, ret}` with `ret` a daily **fraction**). In this lab they feed
# a second PCA (section 11): do these return streams carry separate
# information, or mostly the same?
#
# A factor that fails the gates is `blocked`: it is still listed (gate state is
# disclosed, not used as a filter) but its return series is empty. **An
# all-blocked market is normal.** When `FACTOR_FALLBACK` is on and the market
# has fewer than 3 published series, the cell tries the other markets (at most 3
# more requests) and says which one it used. The section is optional, so every
# request uses `sf_try`.

# %%
def published_series(payload) -> int:
    """How many factors in this payload carry a return series (0 for an unavailable payload)."""
    if payload is None:
        return 0
    return sum(1 for factor in records(payload, "factor_portfolios") if factor["return_series"])


fp_payload = sf_try(f"/api/v1/markets/{MARKET}/factor-portfolios")
if fp_payload is not None:
    show_freshness(fp_payload, "Factor portfolios:")
FACTOR_MARKET = MARKET
tried = {MARKET: published_series(fp_payload)}
if tried[MARKET] < 3 and FACTOR_FALLBACK:
    print(f"{MARKET_NAMES[MARKET]} publishes {tried[MARKET]} factor return series; trying the other markets.")
    for m in MARKETS:
        if m == MARKET:
            continue
        candidate = sf_try(f"/api/v1/markets/{m}/factor-portfolios")
        if candidate is not None:
            show_freshness(candidate, f"Factor portfolios ({m}):")
        tried[m] = published_series(candidate)
        if tried[m] >= 3:
            fp_payload, FACTOR_MARKET = candidate, m
            break
display(pd.DataFrame({"factors with a return series": tried}).T)
fp = fp_payload["data"]["data"] if fp_payload is not None else {}
if fp:
    print(f"Using {MARKET_NAMES[FACTOR_MARKET]} factors: as of {fp['as_of'] or 'n/a (nothing published)'}, release "
          f"{fp['release_id']}, {fp['n_active']} active, {fp['n_risk_ready']} risk-ready.")

# %% [markdown]
# **Raw preview.** `to_frame` flattens the nested `stats` block into dotted
# columns (`stats.vol_annual`, ...). The return series stay as lists for now.
# This table is also the gate report: `publish_state` and `gate_reason` say
# why a factor is held back.

# %%
factors_raw = to_frame(fp_payload, "factor_portfolios") if fp_payload is not None else pd.DataFrame()
PREVIEW = ["factor_id", "factor_label", "publish_state", "is_risk_ready", "stats.n_obs", "stats.vol_annual",
           "gate_reason"]
factors_raw[PREVIEW] if not factors_raw.empty else factors_raw

# %% [markdown]
# ### Cleaning: from nested lists to a date × factor table
#
# 1. Unpack each factor's `return_series` into a long table (factor, date,
#    return).
# 2. Parse dates as UTC and coerce returns to numbers.
# 3. De-duplicate on the natural key (factor, date).
# 4. Pivot to one column per factor and keep only the dates every published
#    factor shares (the *aligned* dates), counting what that drops.
# 5. Check our numbers against the API's own: the aligned-date count and each
#    factor's annualised volatility (daily standard deviation × √252).

# %%
factors = pick(pd.DataFrame(records(fp_payload, "factor_portfolios") if fp_payload is not None else []),
               ["factor_id", "factor_label", "publish_state", "gate_reason", "stats", "return_series"])
FACTOR_ORDER = factors["factor_id"].tolist()                       # contract order: ERP ... LIQ
FACTOR_COLOR = dict(zip(FACTOR_ORDER, SERIES))                      # colour follows the factor, never its rank
FACTOR_NAME = {f: f"{lab} ({f.upper()})" for f, lab in zip(factors["factor_id"], factors["factor_label"])}

series_long = pd.DataFrame(
    [{"factor_id": fid, "date": point["date"], "ret": point["ret"]}
     for fid, series in zip(factors["factor_id"], factors["return_series"]) for point in (series or [])],
    columns=["factor_id", "date", "ret"])
series_long["date"] = pd.to_datetime(series_long["date"], utc=True, errors="coerce")
series_long["ret"] = pd.to_numeric(series_long["ret"], errors="coerce")
n_raw = len(series_long)
series_long = series_long.dropna(subset=["date"]).drop_duplicates(subset=["factor_id", "date"])
returns_wide = (series_long.pivot(index="date", columns="factor_id", values="ret").sort_index()
                if not series_long.empty else pd.DataFrame())
returns_wide = returns_wide[[f for f in FACTOR_ORDER if f in returns_wide.columns]]
aligned = returns_wide.dropna()

blocked = factors[factors["return_series"].map(lambda s: len(s or [])) == 0]
print(f"{n_raw} (factor, date) points -> {len(series_long)} after cleaning; {returns_wide.shape[1]} factors with "
      f"data; {len(returns_wide)} dates, of which {len(aligned)} are shared by all of them "
      f"({len(returns_wide) - len(aligned)} dropped).")
for _, row in blocked.iterrows():
    print(f"  blocked: {FACTOR_NAME[row['factor_id']]} - {row['gate_reason'] or 'no reason given'}")

if not aligned.empty:
    checks = pd.DataFrame({
        "api_vol_annual": [row["stats"]["vol_annual"] for _, row in factors.iterrows()],
        "our_vol_annual": [returns_wide[f].dropna().std(ddof=1) * np.sqrt(252) if f in returns_wide else np.nan
                           for f in factors["factor_id"]],
    }, index=[FACTOR_NAME[f] for f in factors["factor_id"]])
    api_aligned = fp["aggregate"]["n_aligned_dates"]
    print(f"Aligned dates: API {api_aligned}, ours {len(aligned)} -> "
          f"{'match' if api_aligned == len(aligned) else 'DIFFER'}.")
    display(checks.dropna(how="all").style.format("{:.2%}", na_rep="n/a"))

# %% [markdown]
# ### Chart: how each factor portfolio compounded
#
# Each line starts at 1.00 and multiplies by (1 + daily return) every day: the
# value of one unit invested in the portfolio. Lines keep the same colour for
# the same factor everywhere in this notebook.

# %%
if factors.empty:
    display(Markdown("> The factor-portfolio endpoint is unavailable right now (see the note above), so there is "
                     "nothing to chart, and the factor PCA in section 11 will be skipped. Try again later."))
elif aligned.empty:
    reasons = sorted({token.strip() for text in blocked["gate_reason"].dropna() for token in str(text).split(";")
                      if token.strip()})
    display(Markdown(
        f"> No published factor return series came back ({len(blocked)} of {len(factors)} factors blocked in "
        f"{MARKET_NAMES[FACTOR_MARKET]}; other markets tried: {', '.join(m for m in tried if m != MARKET) or 'none'}). "
        "There is nothing to chart, and the factor PCA in section 11 will be skipped. This is normal while "
        "SurgeFlow's publication gates hold the factors back."
        + (f" Gate reasons today: {', '.join(f'`{r}`' for r in reasons)}." if reasons else "")))
else:
    growth = (1 + aligned).cumprod()
    final = growth.iloc[-1].sort_values(ascending=False)
    best, worst = final.index[0], final.index[-1]
    fig = go.Figure()
    for f in aligned.columns:
        fig.add_trace(go.Scatter(
            x=growth.index, y=growth[f], mode="lines", name=FACTOR_NAME[f], line=dict(color=FACTOR_COLOR[f], width=2),
            hovertemplate=f"{FACTOR_NAME[f]}<br>%{{x|%Y-%m-%d}}: %{{y:.3f}}<extra></extra>"))
    # End labels, nudged apart vertically when two lines finish close together.
    min_gap = 0.045 * float(growth.max().max() - growth.min().min())
    placed = []
    for f, value in final.sort_values().items():
        y_label = max(value, placed[-1] + min_gap) if placed else value
        placed.append(y_label)
        fig.add_annotation(x=growth.index[-1], y=y_label, text=f"{f.upper()} {value - 1:+.0%}", showarrow=False,
                           xanchor="left", xshift=6, font=dict(size=11, color=FACTOR_COLOR[f]))
    fig.add_hline(y=1, line=dict(color=AXIS, width=1))
    fig.update_xaxes(title_text="Date (UTC)")
    fig.update_yaxes(title_text="Value of 1 unit invested (×)")
    blocked_text = (", ".join(FACTOR_NAME[f] for f in blocked["factor_id"]) + " blocked (no series)"
                    if len(blocked) else "no factor blocked")
    title, top = chart_title(
        f"Over {len(aligned)} trading days, {FACTOR_NAME[best]} compounded most ({final[best] - 1:+.0%}) and "
        f"{FACTOR_NAME[worst]} least ({final[worst] - 1:+.0%})",
        f"{MARKET_NAMES[FACTOR_MARKET]} pure-factor portfolios, daily, {aligned.index[0]:%Y-%m-%d} to "
        f"{aligned.index[-1]:%Y-%m-%d} · {blocked_text}")
    fig.update_layout(title=title, height=500, margin=dict(t=top, r=90, b=120),
                      legend=legend_below(500, top, 120))
    fig.show()
    display(pd.DataFrame({"growth_of_1": final, "daily_mean": aligned.mean(), "daily_sd": aligned.std()})
            .rename(index=FACTOR_NAME).style.format({"growth_of_1": "{:.3f}", "daily_mean": "{:+.3%}",
                                                     "daily_sd": "{:.3%}"}))

# %% [markdown]
# **How to read this.** A line above 1.00 made money over the window, below lost
# it. Steep stretches are strong runs; jagged stretches are volatile ones. The
# ending values are labelled on the right. When every factor is blocked, the
# gate report above is the whole story for today: read `gate_reason` to see
# which test a factor has not passed yet.
#
# **Caveats.**
#
# - These are research portfolios, before trading costs. They are not funds
#   you can buy.
# - `effective_sign` tells you when SurgeFlow flipped a factor's direction; the
#   series are used exactly as published.
# - One year is a short window for factor returns, and the window ends on the
#   factor release's `as_of` date, not necessarily on the screen session.

# %% [markdown]
# ## 8. Extension: one feature table, cleaned in the open
#
# *From here on, the notebook goes beyond the raw API.* We join every endpoint
# onto the screen, engineer the features, apply an explicit NaN policy,
# winsorise heavy tails, and audit the result before and after.
#
# ### 8.1 Join on `ticker`, and report the match rates
#
# The screen is the base: one row per stock. Every other source is attached
# with a **left join**, which keeps every screen stock and adds the other
# columns where the ticker matches. `validate="one_to_one"` makes pandas raise if
# a ticker appears twice on either side, which would silently multiply rows.
#
# A join is only as useful as its **match rate**, so we report two shares per
# source: how many of the source's tickers found a partner among our stocks, and
# how many of our stocks received a value.

# %%
rt_join = (rt[["ticker", "intraday_return_pct", "projected_vs_yesterday"]]
           .add_prefix("rt_").rename(columns={"rt_ticker": "ticker"}))
sf_join = sf_labels[["ticker", "sf_cluster_id", "sf_source"]]
feat = (screen
        .merge(rt_join, on="ticker", how="left", validate="one_to_one")
        .merge(whale_wide, on="ticker", how="left", validate="one_to_one")
        .merge(sf_join, on="ticker", how="left", validate="one_to_one"))
for col in ["rt_intraday_return_pct", "rt_projected_vs_yesterday", "whale_boards", *BOARD_SCORE.values()]:
    feat[col] = pd.to_numeric(feat[col], errors="coerce")

coverage = pd.DataFrame([
    {"source": "screen (base)", "endpoint": "/screen", "tickers": len(screen), "matched": len(screen)},
    {"source": "realtime board", "endpoint": "/realtime", "tickers": len(rt),
     "matched": int(feat["rt_intraday_return_pct"].notna().sum())},
    {"source": "whale boards", "endpoint": "/whales", "tickers": len(whale_wide),
     "matched": int(feat["whale_boards"].notna().sum())},
    {"source": "SurgeFlow cluster labels", "endpoint": "/ml/clusters", "tickers": len(sf_labels),
     "matched": int(feat["sf_cluster_id"].notna().sum())},
]).set_index("source")
coverage["share_of_source_matched"] = coverage["matched"] / coverage["tickers"].clip(lower=1)
coverage["share_of_sample_covered"] = coverage["matched"] / max(len(screen), 1)
print(f"Feature table: {feat.shape[0]:,} stocks x {feat.shape[1]} columns.")
display(coverage.style.format({"share_of_source_matched": "{:.0%}", "share_of_sample_covered": "{:.0%}"}))

# %% [markdown]
# **How to read the coverage table.** "share of source matched" says how many of
# a source's tickers are among our largest stocks; below 100% means the source
# names smaller companies too. "share of sample covered" says how many of our
# stocks received a value. The realtime board (50 names) and the whale boards
# (six top 20s) are short lists by design, so they cover only part of the
# sample. SurgeFlow's cluster labels reach very few large caps (section 6).
# Those low numbers are facts about the sources, not join failures.
#
# ### 8.2 Engineer the features
#
# The recipe table below lists every model column, the raw API column it
# starts from, the transform, the NaN rule and whether it is winsorised. Four
# choices deserve a word.
#
# - **The target is the day's change in percent.** `y_change = 100 ×
#   change_pct`. The API sends a fraction (0.0142); percent (1.42) is easier to
#   read in tables and coefficients.
# - **Logs for money, multiples and skewed ratios.** `log1p` (log of 1 + x) for
#   market cap and turnover; plain `log` for the turnover multiple and for B/P
#   and S/P, which have long right tails; `log1p` for revenue growth (a growth
#   of −40% becomes −0.51, +300% becomes 1.39). A tenfold gap becomes a
#   constant step.
# - **No leakage in the regression.** A feature must not contain the target.
#   `ma10_excess = price ÷ 10-day average − 1` is computed with *today's* price,
#   so a stock that jumped today automatically shows a bigger gap: the
#   regression would "explain" today's move with today's move. We therefore
#   roll every feature that divides by (or into) today's price back to the
#   **prior close** (the close before the day being explained). With
#   `r = change_pct`, the price at the prior close is today's price ÷ (1 + r),
#   so: market cap ÷ (1 + r); E/P and dividend yield × (1 + r); log B/P and
#   log S/P + log(1 + r); and for an N-day average with today's gap `e`, the
#   prior-close gap is `(1 + e)(N − 1) ÷ ((1 + r)(N − 1 − e)) − 1`. That last
#   formula also removes today's price from the average itself, assuming the
#   price that left the window equals the average. Section 10.3 shows how much
#   leakage this removes. One small leak remains on purpose: **turnover** is
#   money traded at today's prices, so it shares a small, mechanical part of
#   today's move (and big news moves both). We keep it, because trading
#   activity is part of what we want to describe; read its coefficient with
#   that in mind.
# - **PCA and clustering use the fields as published.** They have no target,
#   so there is nothing to leak: they describe each stock's style as the screen
#   shows it.

# %%
r = feat["change_pct"]
prev = 1 + r                                                       # today's price ÷ the price at the prior close
feat["y_change"] = 100 * r                                         # the target, fraction -> percent
feat["log_mcap"] = np.log1p(feat["market_cap_usd"].where(feat["market_cap_usd"] > 0))
feat["log_turnover"] = np.log1p(feat["turnover"].where(feat["turnover"] >= 0))
feat["log_turnover_vs_10d"] = np.log(feat["turnover_vs_10d"].where(feat["turnover_vs_10d"] > 0))
feat["log_bp"] = np.log(feat["bp"].where(feat["bp"] > 0))
feat["log_sp"] = np.log(feat["sp"].where(feat["sp"] > 0))          # no reported sales (0) -> NaN
feat["log_revenue_growth"] = np.log1p(feat["revenue_growth"].where(feat["revenue_growth"] > -1))
# The regression versions, rolled back to the prior close so that none contains the day's move.
feat["log_mcap_prev"] = np.log1p((feat["market_cap_usd"] / prev).where(feat["market_cap_usd"] > 0))
feat["ep_prev"] = feat["ep"] * prev
feat["dividend_yield_prev"] = feat["dividend_yield"] * prev          # dividend per share ÷ the prior-close price
feat["log_bp_prev"] = feat["log_bp"] + np.log(prev)
feat["log_sp_prev"] = feat["log_sp"] + np.log(prev)
for n in (10, 50, 200):
    e = feat[f"ma{n}_excess"]
    feat[f"ma{n}_gap_prev"] = (1 + e) * (n - 1) / (prev * (n - 1 - e)) - 1
ENGINEERED = ["y_change", "log_mcap", "log_turnover", "log_turnover_vs_10d", "log_bp", "log_sp", "log_revenue_growth",
              "log_mcap_prev", "ep_prev", "dividend_yield_prev", "log_bp_prev", "log_sp_prev", "ma10_gap_prev",
              "ma50_gap_prev", "ma200_gap_prev"]
feat[ENGINEERED] = feat[ENGINEERED].replace([np.inf, -np.inf], np.nan)   # a change of -100% would divide by 0

DROP, MEDIAN = "drop the stock", "fill the median + flag"
REG, STYLE, BOTH = "regression", "PCA, clustering", "regression, PCA, clustering"
SPEC = pd.DataFrame([
    # feature, raw source column, transform, NaN rule, winsorise, used in
    ("y_change", "change_pct", "100 × change_pct (fraction -> percent)", DROP, True, "target"),
    ("log_mcap_prev", "market_cap_usd", "log1p(market cap ÷ (1 + r))", DROP, True, REG),
    ("log_turnover", "turnover", "log1p", DROP, True, BOTH),
    ("log_turnover_vs_10d", "turnover_vs_10d", "log", DROP, True, BOTH),
    ("ma10_gap_prev", "ma10_excess", "gap at the prior close (formula above, N = 10)", DROP, True, REG),
    ("ma50_gap_prev", "ma50_excess", "gap at the prior close (N = 50)", DROP, True, REG),
    ("ma200_gap_prev", "ma200_excess", "gap at the prior close (N = 200)", DROP, True, REG),
    ("ep_prev", "ep", "E/P × (1 + r)", DROP, True, REG),
    ("log_bp_prev", "bp", "log B/P + log(1 + r)", DROP, True, REG),
    ("log_sp_prev", "sp", "log S/P + log(1 + r)", DROP, True, REG),
    ("profit_margin", "profit_margin", "as is", MEDIAN, True, BOTH),
    ("log_revenue_growth", "revenue_growth", "log1p", MEDIAN, True, BOTH),
    ("dividend_yield_prev", "dividend_yield", "DY × (1 + r)", MEDIAN, True, REG),
    ("whale_boards", "whale_boards", f"informative boards listing the stock, 0-{N_BOARDS}",
     "not listed → 0 (a true zero)", False, REG),
    ("fundamentals_filled", "profit_margin", "1 if any fundamental was median-filled, else 0", "none (it is the flag)",
     False, REG),
    ("log_mcap", "market_cap_usd", "log1p", DROP, True, STYLE),
    ("ma10_excess", "ma10_excess", "as published", DROP, True, STYLE),
    ("ma50_excess", "ma50_excess", "as published", DROP, True, STYLE),
    ("ma200_excess", "ma200_excess", "as published", DROP, True, STYLE),
    ("ep", "ep", "as published", DROP, True, STYLE),
    ("log_bp", "bp", "log", DROP, True, STYLE),
    ("log_sp", "sp", "log", DROP, True, STYLE),
    ("dividend_yield", "dividend_yield", "as published", MEDIAN, True, STYLE),
], columns=["feature", "source", "transform", "nan_rule", "winsorise", "used_in"]).set_index("feature")

# Fixed starting lists (tuples, so no later cell can change them). Section 8.3 rebuilds REG_CANDIDATES and
# STYLE_FEATURES from them on every run, so you can change a knob and re-run without stale lists.
REG_BASE = ("log_mcap_prev", "log_turnover", "log_turnover_vs_10d", "ma10_gap_prev", "ma50_gap_prev",
            "ma200_gap_prev", "ep_prev", "log_bp_prev", "log_sp_prev", "profit_margin", "log_revenue_growth",
            "dividend_yield_prev", "whale_boards", "fundamentals_filled")
STYLE_BASE = ("log_mcap", "log_turnover", "log_turnover_vs_10d", "ma10_excess", "ma50_excess", "ma200_excess",
              "ep", "log_bp", "log_sp", "profit_margin", "log_revenue_growth", "dividend_yield")
EXPLORE_ONLY = ["rt_intraday_return_pct", "rt_projected_vs_yesterday", *BOARD_SCORE.values()]
display(SPEC.style.set_properties(**{"text-align": "left"}))

# %% [markdown]
# ### 8.3 The NaN policy, step by step
#
# A missing value has a *reason*, and the reason decides the rule:
#
# 1. **No target, no lesson.** A stock without the day's change cannot teach
#    the regression anything: drop it.
# 2. **True zeros.** A stock that no whale board lists sits on 0 boards. That is
#    a fact, not a gap: fill 0.
# 3. **Mostly missing columns.** A feature missing for more than
#    `MAX_MISSING_SHARE` of stocks (for example `dividend_yield` on the Hong
#    Kong screen, which is always empty) would cost too many stocks under any
#    row rule: drop the *column* and say so.
# 4. **Nullable fundamentals.** `profit_margin`, `revenue_growth` and
#    `dividend_yield` are nullable by contract and often missing for banks,
#    young companies or unverifiable dividends; `revenue_growth` also carries
#    the placeholder zeros that screen step 6 turned into NaN. Dropping those
#    stocks would bias the sample, so we fill the median **and** record a 0/1
#    flag, `fundamentals_filled`. The flag enters the regression when at least
#    `FLAG_MIN_SHARE` of stocks carry it, so the model can tell "filled" from
#    "typical"; with fewer, a handful of stocks would get a coefficient of
#    their own.
# 5. **Anything else**: drop the stock (a "complete case" analysis) and count.
#    This includes the suspect splits whose moving-average gaps and ratios
#    screen step 7 blanked.
#
# The table starts with the two screen steps that *created* gaps on purpose, so
# every blanked value is accounted for. Columns that only a short list fills
# (the realtime board and the whale board scores) stay in the table for
# exploring, never as model inputs.

# %%
model = feat.copy()
policy = [("Screen step 6. Placeholder zero", "revenue_growth", "0.0 → NaN, then rule 4", N_PLACEHOLDER,
           "values blanked"),
          ("Screen step 7. Suspect split / bad price", ", ".join(PRICE_FIELDS), "blank, then rule 5 drops the stock",
           len(SUSPECT_SPLIT), "stocks blanked" + (f" ({', '.join(SUSPECT_SPLIT['ticker'])})" if len(SUSPECT_SPLIT)
                                                    else ""))]

n0 = len(model)                                                                     # rule 1
model = model[model["y_change"].notna()]
policy.append(("1. No target", "y_change", DROP, n0 - len(model), "stocks dropped"))

n = int(model["whale_boards"].isna().sum())                                         # rule 2
model["whale_boards"] = model["whale_boards"].fillna(0)
policy.append(("2. True zero", "whale_boards", "fill 0", n, "values filled"))

candidates = [c for c in SPEC.index if c not in ("y_change", "whale_boards", "fundamentals_filled")]
too_sparse = [c for c in candidates if len(model) and model[c].isna().mean() > MAX_MISSING_SHARE]   # rule 3
REG_CANDIDATES = [c for c in REG_BASE if c not in too_sparse]       # rebuilt from the fixed lists of 8.2 every run
STYLE_FEATURES = [c for c in STYLE_BASE if c not in too_sparse]
policy.append(("3. Mostly missing", ", ".join(too_sparse) or "none", "drop the column", len(too_sparse),
               "columns dropped"))

FILL = [c for c in SPEC.index[SPEC["nan_rule"] == MEDIAN] if c not in too_sparse]   # rule 4
model["fundamentals_filled"] = model[FILL].isna().any(axis=1).astype(int)
for col in FILL:
    n, median = int(model[col].isna().sum()), model[col].median()
    model[col] = model[col].fillna(median)
    policy.append(("4. Nullable fundamental", col, f"fill median ({median:.4g}) + flag", n, "values filled"))

USED = list(dict.fromkeys(["y_change", *REG_CANDIDATES, *STYLE_FEATURES]))
n0 = len(model)                                                                     # rule 5
model = model.dropna(subset=USED).reset_index(drop=True)
policy.append(("5. Any other gap", "all model columns", DROP, n0 - len(model), "stocks dropped"))

FLAG_SHARE = float(model["fundamentals_filled"].mean()) if len(model) else 0.0
if FLAG_SHARE < FLAG_MIN_SHARE:
    REG_CANDIDATES = [c for c in REG_CANDIDATES if c != "fundamentals_filled"]
print(f"fundamentals_filled flags {FLAG_SHARE:.1%} of the stocks: "
      + ("it enters the regression." if "fundamentals_filled" in REG_CANDIDATES
         else f"below {FLAG_MIN_SHARE:.0%}, so it stays out of the regression."))

policy = pd.DataFrame(policy, columns=["step", "columns", "rule", "count", "what the count means"])
display(policy.style.hide(axis="index"))
sparse = pd.DataFrame({"missing_share": feat[EXPLORE_ONLY].isna().mean()}) if len(feat) else pd.DataFrame()
if not sparse.empty:
    sparse["use"] = "explore only (a short list fills it)"
    display(sparse.style.format({"missing_share": "{:.0%}"}))
ENOUGH = len(model) >= MIN_ROWS
print(f"Sample funnel: {n_screen_rows:,} screen rows -> {n_tickers:,} tickers -> {n_companies:,} companies -> "
      f"{len(screen):,} after the liquidity floor -> {len(model):,} complete stocks for modelling."
      f"{'' if ENOUGH else ' Too few for the modelling sections.'}")

# %% [markdown]
# ### 8.4 Winsorise heavy tails
#
# Even after logs, a few stocks sit far from the rest: a +14% day, a stock 80%
# below its 200-day average. One such point can tilt a regression line or
# stretch a PCA axis. **Winsorising** clips every value below the 1st percentile
# up to it, and every value above the 99th down to it. The stock stays; only its
# extreme value is tamed. We do it for the target too. `feat` keeps the raw
# values, so you can always report the true number.

# %%
clip_log = []
for col in [c for c in SPEC.index[SPEC["winsorise"]] if c in USED]:
    if WINSOR_Q <= 0 or model.empty:
        break
    low, high = model[col].quantile([WINSOR_Q, 1 - WINSOR_Q])
    clip_log.append({"feature": col, "clip_low": low, "clip_high": high,
                     "clipped_low": int((model[col] < low).sum()), "clipped_high": int((model[col] > high).sum())})
    model[col] = model[col].clip(low, high)
clip_log = pd.DataFrame(clip_log, columns=["feature", "clip_low", "clip_high", "clipped_low", "clipped_high"])
print(f"Winsorised {len(clip_log)} columns at the {WINSOR_Q:.0%} / {1 - WINSOR_Q:.0%} quantiles; "
      f"{int(clip_log[['clipped_low', 'clipped_high']].to_numpy().sum())} values clipped in total.")
display(clip_log.set_index("feature").style.format("{:.4g}").format("{:d}", subset=["clipped_low", "clipped_high"]))

# %% [markdown]
# ### 8.5 The before/after audit
#
# For every model column we compare the **raw API column** it came from
# (before) with the **model-ready** column (after):
#
# - **gaps**: the share of NaN;
# - **outliers**: the share of values whose robust z-score is above
#   `OUTLIER_Z` (3.5, the Iglewicz–Hoaglin rule). Robust z-scores use the median
#   and the median absolute deviation, so the outliers cannot hide by inflating
#   the scale. Counts and 0/1 flags are not checked;
# - **skew**: lopsidedness, 0 for a symmetric shape.

# %%
AUDITED = [f for f in SPEC.index if f in USED and f != "fundamentals_filled"]   # the flag has no raw column
audit = []
for feature in AUDITED:
    source = SPEC.loc[feature, "source"]
    before = pd.to_numeric(feat[source], errors="coerce")
    after = model[feature]
    continuous = before.nunique() > 10 and after.nunique() > 10       # flags and counts are not outlier-checked
    rz_before, rz_after = robust_z(before).abs(), robust_z(after).abs()
    audit.append({
        "feature": feature, "source": source,
        "gaps_before": before.isna().mean() if len(before) else np.nan,
        "gaps_after": after.isna().mean() if len(after) else np.nan,
        "outliers_before": (rz_before > OUTLIER_Z).mean() if continuous else np.nan,
        "outliers_after": (rz_after > OUTLIER_Z).mean() if continuous else np.nan,
        "max_robust_z_before": rz_before.max() if continuous else np.nan,
        "max_robust_z_after": rz_after.max() if continuous else np.nan,
        "skew_before": before.skew(), "skew_after": after.skew()})
audit = pd.DataFrame(audit, columns=["feature", "source", "gaps_before", "gaps_after", "outliers_before",
                                     "outliers_after", "max_robust_z_before", "max_robust_z_after", "skew_before",
                                     "skew_after"]).set_index("feature")

if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    rows = audit.index[::-1]                                  # first feature at the top of the chart
    ylabels = [label(f) for f in rows]
    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.04,
                        subplot_titles=("Missing values (share of stocks)",
                                        f"Outliers (share with robust |z| > {OUTLIER_Z:g})"))
    for col, metric in enumerate(["gaps", "outliers"], start=1):
        b, a = audit.loc[rows, f"{metric}_before"], audit.loc[rows, f"{metric}_after"]
        for y, vb, va in zip(ylabels, b, a):
            if pd.notna(vb) and pd.notna(va):
                fig.add_trace(go.Scatter(x=[vb, va], y=[y, y], mode="lines", line=dict(color=GRID, width=3),
                                         hoverinfo="skip", showlegend=False), row=1, col=col)
        fig.add_trace(go.Scatter(
            x=b, y=ylabels, mode="markers", name="Before: raw API column", legendgroup="before",
            showlegend=(col == 1), marker=dict(symbol="circle-open", size=10, color=MUTED, line=dict(width=2)),
            customdata=audit.loc[rows, "source"],
            hovertemplate="%{y}<br>before (%{customdata}): %{x:.1%}<extra></extra>"), row=1, col=col)
        fig.add_trace(go.Scatter(
            x=a, y=ylabels, mode="markers", name="After: model-ready column", legendgroup="after",
            showlegend=(col == 1), marker=dict(size=10, color=COLOR),
            hovertemplate="%{y}<br>after: %{x:.1%}<extra></extra>"), row=1, col=col)
    fig.update_xaxes(tickformat=".0%", rangemode="tozero", title_text="Share of stocks (%)")
    fig.update_yaxes(ticks="", title_text=None)
    gaps_before = int(feat[audit["source"].unique()].isna().sum().sum())
    ob = audit["outliers_before"].mean() * 100
    oa = audit["outliers_after"].mean() * 100
    title, top = chart_title(
        f"Cleaning closed every gap and cut the average outlier share from {ob:.1f}% to {oa:.1f}%",
        f"{len(feat):,} stocks before, {len(model):,} after · {gaps_before:,} raw gaps handled by the NaN policy · "
        f"logs, then winsorising at {WINSOR_Q:.0%}/{1 - WINSOR_Q:.0%} · hollow = before, filled = after")
    top += 30                                                         # room for the two panel titles
    height = 240 + 26 * len(rows)
    fig.update_layout(title=title, height=height, margin=dict(t=top, l=10, b=110),
                      legend=legend_below(height, top, 110))
    fig.show()
    display(audit.style.format({c: "{:.1%}" for c in audit.columns if c.startswith(("gaps", "outliers"))}
                               | {c: "{:.2f}" for c in audit.columns if c.startswith(("max", "skew"))},
                               na_rep="n/a"))

# %% [markdown]
# **How to read this.** Each row is a model column. The hollow dot is the raw
# API column, the filled dot the model-ready version, and the grey bar shows how
# far cleaning moved it. On the left, every filled dot should sit at 0%: no gaps
# survive (the whale-board row falls from most stocks to none because "not on
# any board" became a true zero). On the right, look at the money and ratio
# columns: raw market cap, turnover and S/P are full of "outliers" because
# their scale is multiplicative; after the log and winsorising, few remain. A
# few filled dots above 0% are fine. They are real, extreme stocks that were
# tamed, not removed.
#
# **Caveats.**
#
# - The audit compares *shares*, because the after-sample can be smaller (rules
#   1 and 5 drop stocks).
# - Winsorising uses quantiles of the whole sample. Inside cross-validation
#   (section 10) that leaks a tiny amount of information from the test folds;
#   exercise 1 shows how to move it inside the `Pipeline`.
# - The median fill in rule 4 shrinks the spread of the filled columns a
#   little, and the `fundamentals_filled` flag absorbs the level difference.

# %%
if ENOUGH:
    print(f"Model-ready table: {len(model):,} stocks x {len(USED)} model columns (first rows shown).")
    display(model[["ticker", "company_name", "sector", *USED]].head())

# %% [markdown]
# ## 9. Extension: explore before you model
#
# Exploratory data analysis (EDA) means looking at the data before fitting
# anything. Two questions: what does each column look like on its own
# (distributions), and which columns move together (correlations)?
#
# ### Chart: one histogram per regression column

# %%
EDA_COLS = ["y_change", *REG_CANDIDATES]
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    grid_cols = 4
    grid_rows = int(np.ceil(len(EDA_COLS) / grid_cols))
    skews = model[EDA_COLS].skew()
    fig = make_subplots(rows=grid_rows, cols=grid_cols, horizontal_spacing=0.06, vertical_spacing=0.15,
                        subplot_titles=[f"{wrap(label(c), 26)}<br><sup>skew {skews[c]:+.1f}</sup>" for c in EDA_COLS])
    HOVER_X = {"percent": ".2f", "fraction": ".1%", "log": ".2f", "count": ".0f", "flag": ".0f"}  # bin edges
    for i, col in enumerate(EDA_COLS):
        r_, c_ = divmod(i, grid_cols)
        unit = UNITS[col]
        fig.add_trace(go.Histogram(x=model[col], nbinsx=30, marker_color=COLOR, showlegend=False,
                                   xhoverformat=HOVER_X[unit],          # formats the bin's range in the hover
                                   hovertemplate=f"{label(col)}: %{{x}}<br>%{{y}} stocks<extra></extra>"),
                      row=r_ + 1, col=c_ + 1)
        fig.add_vline(x=float(model[col].median()), line=dict(color=INK, dash="dash", width=1.5),
                      row=r_ + 1, col=c_ + 1)
        fig.update_xaxes(title_text=UNIT_AXIS[unit], title_font=dict(size=11), row=r_ + 1, col=c_ + 1,
                         **({"tickformat": ".0%"} if unit == "fraction" else
                            {"ticksuffix": "%"} if unit == "percent" else {}))
    for r_ in range(1, grid_rows + 1):
        fig.update_yaxes(title_text="Stocks", row=r_, col=1)
    fig.update_annotations(font_size=12)
    continuous = [c for c in EDA_COLS if model[c].nunique() > 10]
    lean = [lower_first(label(c)) for c in continuous if abs(skews[c]) >= 1]
    title, top = chart_title(
        f"After cleaning, {len(continuous) - len(lean)} of {len(continuous)} continuous columns are roughly "
        "symmetric (|skew| < 1)",
        "Model-ready values in each column's own unit (x-axis titles; fractions are shown as %) · dashed line = "
        "median · " + (f"still lopsided: {', '.join(lean)}" if lean else "none stays lopsided"))
    top += 62                                                         # room for the first row of panel titles
    fig.update_layout(title=title, height=270 * grid_rows + top, margin=dict(t=top), bargap=0.05)
    fig.show()
    summary = model[EDA_COLS].describe().T
    as_pct = [c for c in EDA_COLS if UNITS[c] == "fraction"]          # shown in %, like the chart
    summary.loc[as_pct, summary.columns.drop("count")] *= 100
    summary.insert(0, "unit", [("%" if UNITS[c] in ("fraction", "percent") else UNITS[c]) for c in summary.index])
    display(summary.rename(index=label).style.format("{:.3g}", subset=summary.columns.drop("unit")))

# %% [markdown]
# **How to read this.** Each panel counts how many stocks fall in each bin of
# one column; the dashed line is its median. Read each panel's x-axis title
# for its unit: the API sends the moving-average gaps, E/P, the margin and the
# dividend yield as fractions, which the chart and its table show as percent,
# like the daily change. A symmetric hump is the easiest shape for a linear
# model. The whale-board count and the 0/1 flag are lumpy by nature (most
# stocks sit at 0), so skew means little for them. Dividend yield piles up at
# 0 for companies that pay nothing. The table twin lists the same columns'
# summary statistics, with a unit column.
#
# ### Chart: which columns move together?
#
# A correlation `r` runs from −1 (perfect opposite) through 0 (unrelated) to +1
# (perfect together). Only the lower triangle is shown, because the upper half
# repeats it; the diagonal (each column with itself, always +1) is left out
# too. Blue is positive, red negative; the scale is symmetric around 0.

# %%
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    corr = model[EDA_COLS].corr()
    pairs = corr.where(np.tril(np.ones(corr.shape, dtype=bool), k=-1)).stack()
    top_pair = pairs.abs().idxmax()
    target_pair = corr["y_change"].drop("y_change").abs().idxmax()
    tri = lower_triangle(corr)
    values = tri.to_numpy()
    fig = go.Figure(go.Heatmap(
        z=values, x=[label(c) for c in tri.columns], y=[label(c) for c in tri.index], colorscale=DIVERGING,
        zmin=-1, zmax=1, zmid=0, xgap=2, ygap=2,
        hoverongaps=False, text=[["" if np.isnan(v) else f"{v:+.2f}" for v in row] for row in values],
        texttemplate="%{text}", textfont=dict(size=10),
        hovertemplate="%{y}<br>%{x}<br>r = %{z:+.2f}<extra></extra>",
        colorbar=dict(title=dict(text="Pearson r", side="right"), thickness=14, len=0.8, outlinewidth=0)))
    fig.update_xaxes(tickangle=-40, showgrid=False, ticks="")
    fig.update_yaxes(autorange="reversed", showgrid=False, ticks="")
    title, top = chart_title(
        f"{label(top_pair[0])} and {lower_first(label(top_pair[1]))} overlap most (r = {corr.loc[top_pair]:+.2f}); "
        f"the day's change moves most with {lower_first(label(target_pair))} "
        f"(r = {corr.loc['y_change', target_pair]:+.2f})",
        f"Pearson correlations of the model-ready regression columns · {len(model):,} stocks · lower triangle only")
    fig.update_layout(title=title, height=640 + top, margin=dict(t=top, l=10, b=10), plot_bgcolor=SURFACE)
    fig.show()
    display(corr.rename(index=label, columns=label).style.format("{:+.2f}"))

# %% [markdown]
# **How to read this.** Find the deepest colours. Pairs above about |r| = 0.7
# carry much the same information, which makes a regression unsure which one
# deserves the credit: section 10 measures that with the VIF. The three
# moving-average gaps usually correlate with each other (a stock above its
# 10-day average is often above its 50-day one too). Then read the first column,
# the target: those are one-at-a-time associations with the day's change. The
# regression will ask the sharper question: does a feature still matter *when
# the others are held fixed*?
#
# Correlation is not causation, and Pearson's r only sees straight-line
# relationships. Every continuous column here is winsorised, so a single wild
# stock cannot create a strong r on its own.

# %% [markdown]
# ## 10. Extension: what explains one day's differences between stocks?
#
# > **Descriptive, not a forecast.** The target is the change of each stock over
# > one session, and the features describe the stocks at (or during) that same
# > session. The regression describes how one day's stocks differ from one
# > another. It cannot tell you what any stock will do tomorrow, and it is not a
# > trading signal. With a single day, it cannot even tell you whether the
# > pattern repeats.
#
# **The model.** Ordinary least squares fits
#
# `daily change (%) = b0 + b1 × feature1 + b2 × feature2 + ... + error`
#
# choosing the `b`s that make the squared errors as small as possible. Each `b`
# answers: *holding the other features fixed*, how much higher is the day's
# change for a stock that is higher on this feature?
#
# ### 10.1 Check the overlap first: VIF
#
# The **variance inflation factor** of a feature is 1 ÷ (1 − R²), where R² comes
# from regressing that feature on all the others. A VIF of 1 means no overlap.
# A VIF of 10 means 90% of the feature is explained by the rest, and its
# coefficient's variance is inflated tenfold: the estimate becomes unstable.
# Common rules of thumb: above 5, watch; above 10, act. Here, any feature above
# `VIF_LIMIT` is dropped, worst first, and the VIFs are recomputed after each
# drop. The three moving-average gaps are the usual suspects.

# %%
def vif_table(X: pd.DataFrame) -> pd.Series:
    """VIF of each column of X, computed with an intercept in the design (as in the regression)."""
    design = sm.add_constant(X, has_constant="add").to_numpy(dtype=float)
    return pd.Series([variance_inflation_factor(design, i) for i in range(1, design.shape[1])],
                     index=X.columns, name="VIF")


REG_FEATURES = list(REG_CANDIDATES)
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    constant = [c for c in REG_CANDIDATES if model[c].nunique() <= 1]
    if constant:                       # e.g. every stock has 0 whale boards when the whale endpoint is unavailable
        print(f"Dropping columns with no variation (nothing to learn from): {', '.join(constant)}.")
    REG_FEATURES = [c for c in REG_CANDIDATES if c not in constant]
    vif_before = vif_table(model[REG_FEATURES])
    vif_after, dropped_vif = vif_before.copy(), []
    while vif_after.max() > VIF_LIMIT and len(REG_FEATURES) > 2:
        worst = vif_after.idxmax()
        print(f"Dropping {worst} (VIF {vif_after.max():.1f} > {VIF_LIMIT:g}).")
        dropped_vif.append(worst)
        REG_FEATURES.remove(worst)
        vif_after = vif_table(model[REG_FEATURES])
    vif = pd.DataFrame({"candidates": vif_before, "used": vif_after})
    print(f"Regression features ({len(REG_FEATURES)}): {', '.join(REG_FEATURES)}.")

    order = vif.max(axis=1).sort_values().index
    fig = go.Figure()
    if dropped_vif:
        fig.add_trace(go.Bar(y=[label(c) for c in order], x=vif.loc[order, "candidates"], orientation="h",
                             name="Before: all candidates", marker_color=MUTED,
                             hovertemplate="%{y}<br>VIF before %{x:.1f}<extra></extra>"))
    fig.add_trace(go.Bar(y=[label(c) for c in order], x=vif.loc[order, "used"], orientation="h",
                         name="Features used" if dropped_vif else "VIF", marker_color=COLOR,
                         showlegend=bool(dropped_vif), hovertemplate="%{y}<br>VIF %{x:.1f}<extra></extra>"))
    for x, text in ((5, "5: watch"), (VIF_LIMIT, f"{VIF_LIMIT:g}: act")):
        fig.add_vline(x=x, line=dict(color=MUTED, dash="dot", width=1.5), annotation_text=text,
                      annotation_position="top", annotation_font=dict(size=11, color=INK_2))
    headline = (f"Dropping {', '.join(lower_first(label(c)) for c in dropped_vif)} brings every VIF under "
                f"{VIF_LIMIT:g} (largest now {vif['used'].max():.1f})" if dropped_vif
                else f"No feature overlaps too much: the largest VIF is {vif['used'].max():.1f}, "
                     f"under the limit of {VIF_LIMIT:g}")
    fig.update_xaxes(title_text="Variance inflation factor (×)", rangemode="tozero")
    fig.update_yaxes(ticks="", title_text=None)
    title, top = chart_title(headline, f"VIF = 1 ÷ (1 − R² of the feature on all the others) · {len(model):,} "
                                       "stocks" + (" · a missing coloured bar = dropped" if dropped_vif else ""))
    top += 20                                                         # room for the threshold labels
    height = 190 + 34 * len(order)
    fig.update_layout(title=title, barmode="group", height=height, margin=dict(t=top, l=10, b=110), bargap=0.25,
                      legend=legend_below(height, top, 110))
    fig.show()
    display(vif.rename(index=label).style.format("{:.2f}", na_rep="dropped"))

# %% [markdown]
# **How to read this.** Each bar is one feature's VIF. Bars past the dotted line
# at 10 would make their coefficients unreliable and are dropped; between 5 and
# 10 they deserve a look. Size, turnover and valuation share some information
# (big companies trade more and are often priced richly), which shows up as
# moderate VIFs well under the limit.
#
# ### 10.2 OLS with robust (HC3) standard errors
#
# We **standardise** every feature first (z-scores), so each coefficient means
# "percentage points (pp) of daily change per one standard deviation of the
# feature". That puts all features on one scale, so you can compare them.
#
# A coefficient is an estimate; its **standard error** (SE) says how uncertain
# it is. Classic OLS assumes every stock's error has the same spread. On a
# stock market that is rarely true (volatile names scatter more), so we use
# **HC3** standard errors, which stay valid when the spread differs. The 95%
# confidence interval is roughly the estimate ± 2 SE.
#
# **Many features, many tests.** Each interval is a separate test at the 5%
# level, so with a dozen features about one can exclude zero by luck alone.
# Two checks guard against that. The robust **F-test** asks whether the features
# describe the day's differences *jointly*, better than chance. The **Holm
# adjustment** raises each p-value to account for the number of tests
# (`p_holm`). We name a leading feature only when both checks pass.

# %%
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    X, y = model[REG_FEATURES], model["y_change"]
    scaler = StandardScaler().fit(X)                                # z-scores: mean 0, standard deviation 1
    Xz = pd.DataFrame(scaler.transform(X), index=X.index, columns=REG_FEATURES)
    design = sm.add_constant(Xz)
    ols = sm.OLS(y, design).fit(cov_type="HC3")                     # robust standard errors
    ols_classic = sm.OLS(y, design).fit()                           # same coefficients, classic standard errors
    ci = ols.conf_int(alpha=0.05)
    coef = pd.DataFrame({
        "coef_pp_per_sd": ols.params, "se_hc3": ols.bse, "se_classic": ols_classic.bse,
        "z": ols.tvalues, "p": ols.pvalues, "ci_low": ci[0], "ci_high": ci[1]}).drop(index="const")
    coef["1 sd equals"] = [f"{sd:.1%}" if UNITS[c] == "fraction" else f"{sd:.3g}"   # in the feature's own unit
                           for c, sd in zip(REG_FEATURES, scaler.scale_)]
    coef["ci_excludes_0"] = (coef["ci_low"] > 0) | (coef["ci_high"] < 0)    # one test at a time (unadjusted)
    coef["p_holm"] = multipletests(coef["p"], method="holm")[1]             # adjusted for testing every feature
    JOINT_OK = ols.f_pvalue < 0.05                                          # do the features matter at all, jointly?
    display(Markdown(
        f"> **N = {int(ols.nobs):,} stocks · R² = {ols.rsquared:.3f} (adjusted {ols.rsquared_adj:.3f}) · "
        f"robust F-test {p_text(ols.f_pvalue)}.** R² is the share of the day's differences in return that the "
        f"features describe, *in this sample, on this day*. The F-test asks whether the features *jointly* describe "
        f"more than chance. The average stock moved "
        f"{ols.params['const']:+.2f}% (the intercept, since every feature is centred). HC3 standard errors range "
        f"from {(coef['se_hc3'] / coef['se_classic']).min():.2f}× to "
        f"{(coef['se_hc3'] / coef['se_classic']).max():.2f}× the classic ones. {int(coef['ci_excludes_0'].sum())} of "
        f"{len(coef)} unadjusted 95% intervals exclude zero; {int((coef['p_holm'] < 0.05).sum())} p-values stay "
        f"below 0.05 after a Holm adjustment for {len(coef)} tests (`p_holm`)."))
    display(coef.rename(index=label).style.format(
        {"coef_pp_per_sd": "{:+.3f}", "se_hc3": "{:.3f}", "se_classic": "{:.3f}", "z": "{:+.2f}", "p": fmt_p,
         "p_holm": fmt_p, "ci_low": "{:+.3f}", "ci_high": "{:+.3f}"}))

# %% [markdown]
# ### Chart: the coefficient plot
#
# One row per feature, sorted by coefficient (the same order as the shrinkage
# chart in 10.5). The dot is the coefficient; the bar is its 95% confidence
# interval. Blue and red rows have intervals that exclude zero (positive and
# negative); grey rows are compatible with "no association". The intervals are
# unadjusted, one test at a time: the headline names a leading feature only
# when the joint F-test and the Holm-adjusted p-value both agree.

# %%
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    plot = coef.sort_values("coef_pp_per_sd")
    status = np.where(~plot["ci_excludes_0"], "CI includes 0",
                      np.where(plot["coef_pp_per_sd"] > 0, "Positive, CI excludes 0", "Negative, CI excludes 0"))
    STATUS_COLORS = {"Positive, CI excludes 0": DIVERGING[-1][1], "Negative, CI excludes 0": DIVERGING[0][1],
                     "CI includes 0": MUTED}
    fig = go.Figure()
    for name, colour in STATUS_COLORS.items():
        part = plot[status == name]
        if part.empty:
            continue
        fig.add_trace(go.Scatter(
            x=part["coef_pp_per_sd"], y=[label(c) for c in part.index], mode="markers", name=name,
            marker=dict(color=colour, size=11),
            error_x=dict(type="data", symmetric=False, array=part["ci_high"] - part["coef_pp_per_sd"],
                         arrayminus=part["coef_pp_per_sd"] - part["ci_low"], color=colour, thickness=2.5, width=0),
            customdata=np.column_stack([part["ci_low"], part["ci_high"], part["p"].map(fmt_p),
                                        part["p_holm"].map(fmt_p)]),
            hovertemplate="%{y}<br>%{x:+.3f} pp per 1 SD<br>95% CI %{customdata[0]:+.3f} to %{customdata[1]:+.3f}"
                          "<br>p = %{customdata[2]} (Holm-adjusted %{customdata[3]})<extra></extra>"))
    fig.add_vline(x=0, line=dict(color=INK_2, width=1))
    sig = coef[coef["ci_excludes_0"]]                                 # unadjusted: one test at a time
    holm = coef[coef["p_holm"] < 0.05]                                # survives the adjustment for every test
    n_tests = len(coef)
    if JOINT_OK and not holm.empty:                                   # both checks pass: name the leading feature
        lead = holm["coef_pp_per_sd"].abs().idxmax()
        headline = (f"{label(lead)} goes with the largest difference: {coef.loc[lead, 'coef_pp_per_sd']:+.2f} pp of "
                    f"daily change per 1 SD (95% CI {coef.loc[lead, 'ci_low']:+.2f} to "
                    f"{coef.loc[lead, 'ci_high']:+.2f}; Holm-adjusted {p_text(coef.loc[lead, 'p_holm'])})")
    elif JOINT_OK:
        headline = (f"Jointly the features describe the day's movers (robust F-test {p_text(ols.f_pvalue)}), but no "
                    f"single one stands out after adjusting for {n_tests} tests")
    else:
        if sig.empty:
            detail = "every 95% interval includes zero"
        elif len(sig) == 1 and holm.empty:
            detail = f"the one interval that excludes zero is about what {n_tests} tests give by chance"
        else:
            detail = (f"{len(sig)} of {n_tests} intervals exclude zero ({len(holm)} after a Holm adjustment), so read "
                      "any single one with caution")
        headline = (f"Jointly, the features do not separate the day's movers (robust F-test {p_text(ols.f_pvalue)}); "
                    f"{detail}")
    fig.update_xaxes(title_text="Daily change (percentage points) per 1 standard deviation of the feature",
                     zeroline=False)
    # One trace per colour would stack the rows trace by trace; fix the order: sorted by coefficient, as in 10.5.
    fig.update_yaxes(categoryorder="array", categoryarray=[label(c) for c in plot.index], ticks="", title_text=None)
    title, top = chart_title(headline, f"{len(sig)} of {n_tests} unadjusted 95% intervals exclude zero, {len(holm)} "
                                       f"after a Holm adjustment for {n_tests} tests · robust F-test "
                                       f"{p_text(ols.f_pvalue)} · OLS with HC3 robust standard errors · "
                                       f"N = {int(ols.nobs):,} · R² = {ols.rsquared:.2f} · session {SCREEN_AS_OF} · "
                                       "descriptive, not a forecast")
    height = 200 + 34 * len(coef)
    fig.update_layout(title=title, height=height, margin=dict(t=top, l=10, b=110),
                      legend=legend_below(height, top, 110))
    fig.show()

# %% [markdown]
# **How to read this.** Look for bars that do not cross the vertical zero line.
# A blue dot at +0.5 means: among stocks that are alike on every other feature,
# one standard deviation more of this feature went with a daily change about
# 0.5 percentage points higher *on this day*. Grey bars straddle zero: the data
# cannot tell their sign. The table above lists the exact numbers, including
# what one standard deviation equals in each feature's own unit.
#
# **Caveats.**
#
# - A dozen tests at the 5% level produce about one "significant" result by
#   luck alone. That is why the headline checks the joint F-test and the
#   Holm-adjusted p-values (hover a row, or read `p_holm` in the table above)
#   before it names a feature. Treat a single borderline interval with
#   suspicion, even when it is coloured.
# - Coefficients describe association, not cause. Turnover and return are both
#   driven by news; neither causes the other. Heavy trading goes with *big*
#   moves in either direction, which a straight line in the signed return only
#   partly sees.
# - Much of one day's cross-section is **sector** news (a rally in chips lifts
#   every chip maker). Exercise 2 adds sector fixed effects.
# - One day is one draw. Run the notebook on another day and the coefficients
#   will move.
#
# ### 10.3 How much did the leakage fix matter?
#
# Section 8.2 rolled every feature built on today's price back to the prior
# close. To see why, we refit the same regression with the **as-published**
# versions (today's moving-average gaps, E/P, B/P, S/P, dividend yield and
# market cap) and compare R², in sample and in 5-fold cross-validation. A big
# jump means the "explanation" came from the target hiding inside the
# features.

# %%
SWAP = {"log_mcap_prev": "log_mcap", "ma10_gap_prev": "ma10_excess", "ma50_gap_prev": "ma50_excess",
        "ma200_gap_prev": "ma200_excess", "ep_prev": "ep", "log_bp_prev": "log_bp", "log_sp_prev": "log_sp",
        "dividend_yield_prev": "dividend_yield"}
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    leaky_features = [SWAP.get(c, c) for c in REG_FEATURES]
    cv5 = KFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    ols_pipe = Pipeline([("scale", StandardScaler()), ("model", LinearRegression())])
    leak = []
    for name, cols in (("Prior-close features (used)", REG_FEATURES), ("As-published features (leaky)",
                                                                       leaky_features)):
        fit = sm.OLS(y, sm.add_constant(model[cols])).fit()
        cv_r2 = cross_validate(ols_pipe, model[cols], y, cv=cv5, scoring="r2")["test_score"].mean()
        leak.append({"feature set": name, "in-sample R²": fit.rsquared, "cross-validated R²": cv_r2})
    leak = pd.DataFrame(leak).set_index("feature set")
    swapped = [c for c in REG_FEATURES if c in SWAP]
    r_today = model["y_change"].corr(model["ma10_excess"]) if "ma10_excess" in model else np.nan
    r_prev = model["y_change"].corr(model["ma10_gap_prev"]) if "ma10_gap_prev" in model else np.nan
    gain = leak["in-sample R²"].iloc[1] - leak["in-sample R²"].iloc[0]
    if gain >= 0.10:
        verb, verdict = "raises the in-sample R² a lot", "That gain is the target leaking in, not knowledge."
    elif gain >= 0.02:
        verb, verdict = ("raises the in-sample R² a little", "Today the leak is modest, but the gain is still the "
                         "target leaking in, not knowledge; on a day with bigger moves it can dominate.")
    elif gain > -0.02:
        verb, verdict = ("barely changes the in-sample R²", "Today the leak happens to add almost nothing, but the "
                         "as-published features still contain the target, so the rule stands.")
    else:
        verb, verdict = ("lowers the in-sample R²", "Today the as-published versions fit worse, but they still "
                         "contain the target, so the rule stands.")
    display(Markdown(
        f"> Swapping {len(swapped)} features for their as-published versions {verb}, from "
        f"**{leak['in-sample R²'].iloc[0]:.2f} to {leak['in-sample R²'].iloc[1]:.2f}** ({gain:+.2f}). "
        f"The day's change correlates at r = {r_today:+.2f} with today's 10-day gap but r = {r_prev:+.2f} with the "
        f"prior-close gap. {verdict}"))
    display(leak.style.format("{:.3f}"))

# %% [markdown]
# **How to read this.** Read the two rows top to bottom. On most days the
# leaky row looks like a much better model; on a quiet day the gap can be
# small, as the sentence above says. Whatever its size, the leak survives
# cross-validation, because every fold leaks in the same way. That is why
# cross-validation alone cannot catch leakage: you must reason about *when* each
# feature was measured. Keep this table in mind whenever a model looks too good.
#
# ### 10.4 Diagnostics: are the model's assumptions reasonable?
#
# A **residual** is a stock's actual change minus the model's fitted value. Two
# pictures check the residuals:
#
# - **Residuals vs fitted.** If the model captured the straight-line structure,
#   the cloud is a shapeless band around 0. A curve means a missing nonlinear
#   effect; a funnel means the spread changes (which HC3 already handles). The
#   dark line is a LOWESS smoother: a local average that follows the cloud.
# - **QQ plot.** It sorts the standardised residuals and plots them against the
#   values a normal (bell-curve) distribution would give. Points on the
#   diagonal mean "normal"; ends that curl away mean fat tails.

# %%
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    fitted, resid = ols_classic.fittedvalues, ols_classic.resid
    influence = OLSInfluence(ols_classic)
    student = pd.Series(influence.resid_studentized_internal, index=resid.index)
    smooth = lowess(resid, fitted, frac=0.6, return_sorted=True)
    (theoretical, ordered), _ = stats.probplot(student, dist="norm")
    order = np.argsort(student.to_numpy())
    qq_tickers = model["ticker"].to_numpy()[order]
    bp_p = het_breuschpagan(resid, design)[1]
    jb_stat, jb_p, resid_skew, resid_kurt = jarque_bera(resid)
    hover = np.column_stack([model["ticker"], model["company_name"].map(shorten)])

    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.1,
                        subplot_titles=("Residuals vs fitted values", "Normal QQ plot of studentised residuals"))
    fig.add_trace(go.Scatter(x=fitted, y=resid, mode="markers", name="One stock",
                             marker=dict(color=COLOR, size=6, opacity=0.6), customdata=hover,
                             hovertemplate="<b>%{customdata[0]}</b> %{customdata[1]}<br>fitted %{x:+.2f}%"
                                           "<br>residual %{y:+.2f} pp<extra></extra>"), row=1, col=1)
    fig.add_trace(go.Scatter(x=smooth[:, 0], y=smooth[:, 1], mode="lines", name="LOWESS smoother",
                             line=dict(color=INK, width=2.5), hoverinfo="skip"), row=1, col=1)
    fig.add_hline(y=0, line=dict(color=AXIS, width=1), row=1, col=1)
    fig.add_trace(go.Scatter(x=theoretical, y=ordered, mode="markers", name="Studentised residual",
                             marker=dict(color=COLOR, size=6, opacity=0.6), showlegend=False,
                             customdata=qq_tickers,
                             hovertemplate="<b>%{customdata}</b><br>normal quantile %{x:+.2f}"
                                           "<br>residual %{y:+.2f} SD<extra></extra>"), row=1, col=2)
    line = np.array([theoretical.min(), theoretical.max()])
    fig.add_trace(go.Scatter(x=line, y=line, mode="lines", name="Normal reference (y = x)",
                             line=dict(color=INK, dash="dash", width=2), hoverinfo="skip"), row=1, col=2)
    n_tail = max(1, LABEL_TOP // 2 + 1)                               # label the most extreme residuals at each end
    for end, dx in ((slice(-n_tail, None), -46), (slice(0, n_tail), 46)):
        label_points(fig, theoretical[end], ordered[end], qq_tickers[end], dx=dx, row=1, col=2)
    fig.update_xaxes(title_text="Fitted daily change (%)", row=1, col=1)
    fig.update_yaxes(title_text="Residual (pp)", row=1, col=1)
    fig.update_xaxes(title_text="Normal quantile (SD)", row=1, col=2)
    fig.update_yaxes(title_text="Studentised residual (SD)", row=1, col=2)
    tails = "fat-tailed" if jb_p < 0.05 else "close to normal"
    spread = "changes with the features" if bp_p < 0.05 else "is stable across the features"
    title, top = chart_title(
        f"Residuals are {tails} (Jarque–Bera {p_text(jb_p)}), and their spread {spread} "
        f"(Breusch–Pagan {p_text(bp_p)})",
        f"Residual skew {resid_skew:+.2f}, kurtosis {resid_kurt:.1f} (a normal distribution has 3) · labels mark "
        "the most extreme residuals")
    top += 30                                                         # room for the two panel titles
    fig.update_layout(title=title, height=500, margin=dict(t=top, b=110), legend=legend_below(500, top, 110))
    fig.show()

    cooks = pd.Series(influence.cooks_distance[0], index=resid.index)
    influential = (model.loc[cooks.nlargest(5).index, ["ticker", "company_name", "sector", "y_change"]]
                   .rename(columns={"y_change": "target_winsorised"})
                   .assign(fitted=fitted, residual=resid, cooks_distance=cooks))
    raw_change = 100 * feat.set_index("ticker").loc[influential["ticker"], "change_pct"].to_numpy()
    influential.insert(3, "daily_change_raw", raw_change)                # the true change, from feat (section 8.4)
    print(f"Most influential stocks (Cook's distance; a common alert level is 4 / N = {4 / len(model):.3f}). "
          "daily_change_raw is the true change; target_winsorised is the clipped value the model saw:")
    display(influential.style.format({"daily_change_raw": "{:+.2f}%", "target_winsorised": "{:+.2f}%",
                                      "fitted": "{:+.2f}%", "residual": "{:+.2f}", "cooks_distance": "{:.3f}"})
            .hide(axis="index"))

# %% [markdown]
# **How to read this.** On the left, a flat smoother hugging zero is good news:
# no obvious curve was missed. On the right, stock returns almost always curl
# away from the diagonal at both ends. Big surprises happen more often than a
# bell curve allows. With a few hundred stocks the coefficient estimates still
# work, but individual p-values near 0.05 deserve caution. The Breusch–Pagan
# test checks whether the residual spread depends on the features: when it
# does, classic standard errors are wrong and HC3 is the right choice.
#
# **Cook's distance** measures how much the coefficients would move if one stock
# were left out. A stock far above the alert level deserves a look: is it a data
# error or a real event? The table shows both the true daily change
# (`daily_change_raw`) and the winsorised target the model saw; when they
# differ, the stock sat beyond the clip point. We keep them; winsorising already
# limited their pull.
#
# ### 10.5 Regularisation and cross-validation: does the description generalise?
#
# R² measured on the same stocks the model was fitted to is optimistic: with
# enough features, a model can "explain" noise. **Cross-validation** checks
# that. `KFold` splits the stocks into 5 folds; the model is fitted on 4 and
# scored on the fifth, in rotation. Every stock is scored exactly once by a
# model that never saw it. (It checks generalisation to *other stocks on the
# same day*, not to other days.)
#
# We compare four models, each a scikit-learn `Pipeline`, so that scaling is
# learned from the training folds only:
#
# | Model | What it does |
# |---|---|
# | Baseline | Predicts the training mean for every stock. Any useful model must beat it |
# | OLS | `StandardScaler` → `LinearRegression`: the regression above |
# | Ridge | `StandardScaler` → `RidgeCV`: shrinks the coefficients as a whole toward 0 (a single one can still grow when features overlap); picks the shrinkage strength (alpha) by internal cross-validation |
# | Lasso | `StandardScaler` → `LassoCV`: shrinks too, and can set coefficients exactly to 0, which selects features |
#
# Because `RidgeCV` and `LassoCV` tune alpha *inside* each training fold, the
# outer score is honest (this is called nested cross-validation).
#
# **Shuffle every split.** `model` is still sorted by market cap, largest
# first. Unshuffled folds would be contiguous size bands, so each fold would ask
# the model to extrapolate from one band of company sizes to another. Both the
# outer `KFold` and the inner folds that `LassoCV` uses to pick alpha are
# therefore shuffled with `RANDOM_STATE`. `LassoCV(cv=5)` alone would *not*
# shuffle, and its own `random_state` argument does not change the folds.
# `RidgeCV` picks alpha by an efficient leave-one-out, where order plays no role.

# %%
# The shrinkage chart's three series. Not market colours: in this kit blue, orange, green and gold mean us, cn, jp, hk.
MODEL_STYLE = {"OLS": (INK_2, "circle"), "Ridge": (MUTED, "square"), "Lasso": (SERIES[6], "diamond")}
ALPHAS = np.logspace(-3, 3, 61)
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    cv = KFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    models = {
        "Baseline (mean)": DummyRegressor(strategy="mean"),
        "OLS": Pipeline([("scale", StandardScaler()), ("model", LinearRegression())]),
        "Ridge": Pipeline([("scale", StandardScaler()), ("model", RidgeCV(alphas=ALPHAS))]),
        # cv=CV_FOLDS alone would mean unshuffled folds: contiguous size bands, because `model` is sorted by
        # market cap. Pass shuffled folds explicitly (LassoCV's own random_state does not shuffle anything).
        "Lasso": Pipeline([("scale", StandardScaler()),
                           ("model", LassoCV(cv=KFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE),
                                             max_iter=50_000))]),
    }
    cv_rows = []
    for name, estimator in models.items():
        scores = cross_validate(estimator, X, y, cv=cv,
                                scoring={"r2": "r2", "rmse": "neg_root_mean_squared_error"})
        for fold, (r2, rmse) in enumerate(zip(scores["test_r2"], -scores["test_rmse"]), start=1):
            cv_rows.append({"model": name, "fold": fold, "r2": r2, "rmse_pp": rmse})
    cv_scores = pd.DataFrame(cv_rows)
    cv_summary = cv_scores.groupby("model", sort=False).agg(
        r2_mean=("r2", "mean"), r2_sd=("r2", "std"), r2_min=("r2", "min"), rmse_pp=("rmse_pp", "mean"))
    best = cv_summary.drop(index="Baseline (mean)")["r2_mean"].idxmax()
    base_r2 = cv_summary.loc["Baseline (mean)", "r2_mean"]

    fig = go.Figure()
    for fold, part in cv_scores.groupby("fold"):
        fig.add_trace(go.Scatter(x=part["model"], y=part["r2"], mode="lines", line=dict(color=GRID, width=1),
                                 hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(                                       # the x position names the model: one colour
        x=cv_scores["model"], y=cv_scores["r2"], mode="markers", name="One fold's score",
        marker=dict(color=COLOR, size=10, opacity=0.8), customdata=cv_scores["fold"],
        hovertemplate="%{x}<br>fold %{customdata}: R² %{y:.3f}<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=cv_summary.index, y=cv_summary["r2_mean"], mode="markers+text", name="Mean over folds",
        marker=dict(symbol="line-ew", size=34, line=dict(width=3, color=INK)),
        text=[f"{v:.1%}" for v in cv_summary["r2_mean"]], textposition="middle right",
        textfont=dict(size=12, color=INK), hovertemplate="%{x}<br>mean R² %{y:.3f}<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=AXIS, width=1))
    fig.update_yaxes(title_text="Out-of-fold R² (%)", tickformat=".0%")
    fig.update_xaxes(title_text=None)
    best_r2 = cv_summary.loc[best, "r2_mean"]
    best_folds = cv_scores.loc[cv_scores["model"] == best, "r2"]
    spread = f"folds {best_folds.min():.0%} to {best_folds.max():.0%}"
    if best_r2 > 0.01 and best_r2 > base_r2:                        # a real, positive out-of-fold R²
        headline = (f"Out of sample, the best model ({best}) describes {'only ' if best_r2 < 0.1 else ''}"
                    f"{best_r2:.1%} of the day's differences between stocks ({spread}); the mean-only baseline "
                    f"scores {base_r2:.1%}")
    else:
        headline = (f"Out of sample, no model describes the day's differences: the best ({best}) scores "
                    f"{best_r2:.1%} ({spread}), the mean-only baseline {base_r2:.1%}")
    title, top = chart_title(headline, f"{CV_FOLDS}-fold cross-validation, shuffled with random_state "
                                       f"{RANDOM_STATE} · grey lines join the same fold · N = {len(model):,} · "
                                       f"session {SCREEN_AS_OF} · descriptive, not a forecast")
    fig.update_layout(title=title, height=480, margin=dict(t=top, b=90), legend=legend_below(480, top, 90, gap=40))
    fig.show()
    folds = cv_scores.pivot(index="fold", columns="model", values="r2")[list(models)]
    display(pd.concat([folds, folds.agg(["mean", "std"])]).style.format("{:.3f}"))
    display(cv_summary.style.format({"r2_mean": "{:.3f}", "r2_sd": "{:.3f}", "r2_min": "{:.3f}",
                                     "rmse_pp": "{:.3f}"}))

# %% [markdown]
# **How to read this.** Each dot is one fold's score; the black bar is the
# average, also printed as a percentage. Grey lines join the same fold across
# models, so you can see that a hard fold is hard for every model. The baseline
# sits near zero (slightly below, because the training mean is not quite the
# test mean). A gap between OLS's in-sample R² (section 10.2) and its
# out-of-fold R² is the optimism that cross-validation removes. RMSE, in the
# table, is the typical miss in percentage points.
#
# Do not expect a high R². Most of what makes one stock beat another on a given
# day is news that no table of characteristics can see.
#
# ### Chart: how ridge and lasso shrink the coefficients
#
# We refit ridge and lasso on all stocks and compare their coefficients with
# OLS, all per one standard deviation of the feature.

# %%
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    ridge = models["Ridge"].fit(X, y)
    lasso = models["Lasso"].fit(X, y)
    comparison = pd.DataFrame({
        "OLS": coef["coef_pp_per_sd"],
        "Ridge": pd.Series(ridge.named_steps["model"].coef_, index=REG_FEATURES),
        "Lasso": pd.Series(lasso.named_steps["model"].coef_, index=REG_FEATURES),
    }).loc[coef.sort_values("coef_pp_per_sd").index]
    zeroed = comparison.index[comparison["Lasso"].abs() < 1e-10].tolist()
    ridge_alpha = ridge.named_steps["model"].alpha_
    lasso_alpha = lasso.named_steps["model"].alpha_

    n_feat = len(comparison)
    toward = int((comparison["Ridge"].abs() < comparison["OLS"].abs()).sum())
    flipped = int(((np.sign(comparison["Ridge"]) != np.sign(comparison["OLS"]))
                   & (comparison["OLS"].abs() > 1e-10)).sum())
    ols_norm = float(np.linalg.norm(comparison["OLS"]))
    shrink = 1 - float(np.linalg.norm(comparison["Ridge"])) / ols_norm if ols_norm > 0 else np.nan

    fig = go.Figure()
    for offset, name in zip((-0.22, 0.0, 0.22), ["OLS", "Ridge", "Lasso"]):
        ypos = np.arange(n_feat) + offset
        colour, symbol = MODEL_STYLE[name]
        fig.add_trace(go.Scatter(
            x=comparison[name], y=ypos, mode="markers", name=name,
            marker=dict(color=colour, size=10, symbol=symbol),
            customdata=[label(c) for c in comparison.index],
            hovertemplate=f"{name}<br>%{{customdata}}: %{{x:+.3f}} pp per 1 SD<extra></extra>"))
    fig.add_vline(x=0, line=dict(color=INK_2, width=1))
    fig.update_yaxes(tickvals=np.arange(len(comparison)), ticktext=[label(c) for c in comparison.index],
                     ticks="", title_text=None, showgrid=False, zeroline=False)
    fig.update_xaxes(title_text="Daily change (percentage points) per 1 standard deviation", zeroline=False)
    title, top = chart_title(
        f"Lasso keeps {n_feat - len(zeroed)} of {n_feat} features; ridge shrinks the coefficients by {shrink:.0%} "
        f"overall ({toward} of {n_feat} {'moves' if toward == 1 else 'move'} toward zero, {flipped} "
        f"{'flips' if flipped == 1 else 'flip'} sign)",
        f"Ridge alpha {ridge_alpha:.3g}, lasso alpha {lasso_alpha:.3g}, both chosen by internal cross-validation · "
        "overall = length of the coefficient vector · a diamond on the zero line = a feature lasso dropped")
    height = 200 + 36 * n_feat
    fig.update_layout(title=title, height=height, margin=dict(t=top, l=10, b=110),
                      legend=legend_below(height, top, 110))
    fig.show()
    print("Lasso set to exactly 0: " + (", ".join(label(c) for c in zeroed) if zeroed else "nothing") + ".")
    moved = comparison.assign(ridge_toward_zero=comparison["Ridge"].abs() < comparison["OLS"].abs(),
                              ridge_flips_sign=(np.sign(comparison["Ridge"]) != np.sign(comparison["OLS"]))
                              & (comparison["OLS"].abs() > 1e-10))
    display(moved.rename(index=label).style.format("{:+.3f}", subset=["OLS", "Ridge", "Lasso"]))

# %% [markdown]
# **How to read this.** For each feature, three markers: OLS (dark circle),
# ridge (grey square) and lasso (diamond). Ridge shrinks the coefficient
# **vector as a whole**: its overall length, given in the title, is always
# shorter than OLS's, which is the price ridge pays for stability. A single
# coefficient need not shrink, though. When features overlap (the
# moving-average gaps, size and turnover), ridge shares the credit among them,
# so one coefficient can grow or even flip sign while the group shrinks; the
# title and the table count how many did. Lasso's diamonds sit exactly at zero
# for the features it judged not worth their noise. Features that keep a clear
# coefficient of the same sign under all three methods are the robust part of
# the story. Remember the headline of this
# section: **this describes how one day's stocks differ. It does not forecast.**

# %% [markdown]
# ## 11. Extension: PCA, the main directions in the data
#
# Many stock characteristics move together: cheap stocks tend to pay
# dividends, and a stock far above its 10-day average is often above its
# 50-day one too. **PCA** rotates the data so that the first new axis (principal
# component 1, PC1) points along the direction of greatest spread, PC2 along the
# greatest remaining spread at right angles to PC1, and so on. Each component
# is a weighted mix of the original features. If a few components hold most of
# the spread, the stocks differ along a few main "styles".
#
# ### 11.1 PCA on the style features
#
# We use the **style features** as published: size, turnover and its pace,
# the three moving-average gaps, E/P, B/P, S/P, margin, growth and dividend
# yield.
#
# **Standardise first.** PCA chases variance. Without z-scores, a feature with
# big numbers (log market cap spans several units) would dominate one with
# small numbers (a 10-day gap of ±0.05) just because of its unit. The
# `Pipeline` below scales, then rotates.
#
# **How many components matter?** We use *parallel analysis*: shuffle every
# column independently (destroying all real correlation), run PCA on the noise,
# and repeat. A real component must explain more variance than the 95th
# percentile of the shuffled ones.

# %%
def parallel_analysis(Z: np.ndarray, n_perm: int, seed: int) -> np.ndarray:
    """95th percentile of each component's variance share when every column is shuffled independently."""
    gen = np.random.default_rng(seed)
    shares = [PCA().fit(np.column_stack([gen.permutation(Z[:, j]) for j in range(Z.shape[1])]))
              .explained_variance_ratio_ for _ in range(n_perm)]
    return np.percentile(shares, 95, axis=0)


def scree_figure(evr: np.ndarray, null95: np.ndarray, n_keep: int, headline: str, subtitle: str) -> go.Figure:
    """Bars: variance share per component (kept ones in colour). Dashed: noise level. The cumulative share is in
    the table twin and one annotation, so the bars-versus-noise comparison can fill the plot."""
    pcs = [f"PC{i}" for i in range(1, len(evr) + 1)]
    cumulative = np.cumsum(evr)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=pcs[:n_keep], y=evr[:n_keep], name="Component beats shuffled data", marker_color=COLOR,
                         customdata=cumulative[:n_keep],
                         hovertemplate="%{x}: %{y:.1%} of the variance (PC1 to %{x}: %{customdata:.1%})"
                                       "<extra></extra>"))
    fig.add_trace(go.Bar(x=pcs[n_keep:], y=evr[n_keep:], name="Component within noise", marker_color=MUTED,
                         customdata=cumulative[n_keep:],
                         hovertemplate="%{x}: %{y:.1%} of the variance (PC1 to %{x}: %{customdata:.1%})"
                                       "<extra></extra>"))
    fig.add_trace(go.Scatter(x=pcs, y=null95, mode="lines+markers", name="Shuffled data, 95th percentile",
                             line=dict(color=INK, dash="dash", width=2), marker=dict(size=5, color=INK),
                             hovertemplate="%{x}: noise reaches %{y:.1%}<extra></extra>"))
    top = 1.15 * float(max(evr.max(), null95.max()))
    if n_keep:
        fig.add_annotation(x=pcs[n_keep - 1], y=float(evr[n_keep - 1]), yshift=4,
                           text=f"PC1-PC{n_keep} together: {cumulative[n_keep - 1]:.0%}", showarrow=True,
                           arrowhead=0, arrowcolor=MUTED, ax=60, ay=-28, font=dict(size=12, color=INK))
    fig.update_yaxes(title_text="Share of total variance (%)", tickformat=".0%", range=[0, top])
    fig.update_xaxes(title_text="Principal component")
    title, top = chart_title(headline, subtitle)
    fig.update_layout(title=title, barmode="overlay", height=460, margin=dict(t=top, b=110),
                      legend=legend_below(460, top, 110))
    return fig


def oriented_loadings(Z: np.ndarray, scores: np.ndarray, n: int) -> tuple:
    """Loadings as correlations (feature x component), each component flipped so its largest loading is positive."""
    p = Z.shape[1]
    load = np.corrcoef(Z.T, scores[:, :n].T)[:p, p:]
    sign = np.sign(load[np.abs(load).argmax(axis=0), np.arange(n)])
    sign[sign == 0] = 1
    return load * sign, scores[:, :n] * sign


def describe_pc(load: pd.Series, n: int = 3, cut: float = 0.3) -> str:
    """What a high score on one component means: the traits of its strongest loadings, e.g. 'cheap on earnings'."""
    top = load[load.abs() >= cut].abs().sort_values(ascending=False).index[:n]
    words = [trait(f, load[f]) for f in top]
    if not words:
        return "no single feature (every loading is below 0.3)"
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    STYLE_USED = [c for c in STYLE_FEATURES if model[c].nunique() > 1]       # a constant column has no direction
    if len(STYLE_USED) < len(STYLE_FEATURES):
        print(f"Left out (no variation): {', '.join(sorted(set(STYLE_FEATURES) - set(STYLE_USED)))}.")
    pca_pipe = Pipeline([("scale", StandardScaler()), ("pca", PCA(random_state=RANDOM_STATE))])
    scores_all = pca_pipe.fit_transform(model[STYLE_USED])
    Zs = pca_pipe.named_steps["scale"].transform(model[STYLE_USED])              # z-scores, reused in section 12
    evr = pca_pipe.named_steps["pca"].explained_variance_ratio_
    null95 = parallel_analysis(Zs, N_PERMUTATIONS, RANDOM_STATE)
    beats = evr > null95
    N_KEEP = int(np.argmin(beats)) if not beats.all() else len(evr)        # the leading run of real components
    N_SHOW = int(min(max(N_KEEP, 3), 6))
    fig = scree_figure(
        evr, null95, N_KEEP,
        headline=(f"{N_KEEP} components beat shuffled noise; together they hold {np.cumsum(evr)[N_KEEP - 1]:.0%} of "
                  f"the variance in {len(STYLE_USED)} style features" if N_KEEP > 1
                  else f"Only PC1 beats shuffled noise; it holds {evr[0]:.0%} of the variance" if N_KEEP == 1
                  else "No component beats shuffled noise: these features share little structure today"),
        subtitle=f"PCA on z-scored style features · {len(model):,} largest stocks · noise level from "
                 f"{N_PERMUTATIONS} shuffles (parallel analysis) · PC1 alone: {evr[0]:.0%}")
    fig.show()
    display(pd.DataFrame({"variance_share": evr, "cumulative": np.cumsum(evr), "noise_95th": null95},
                         index=[f"PC{i}" for i in range(1, len(evr) + 1)]).head(N_SHOW + 2)
            .style.format("{:.1%}"))

# %% [markdown]
# **How to read this.** Coloured bars are components that explain more variance
# than shuffled noise (the dashed line); grey bars do not. The annotation and
# the table twin add the kept bars up (cumulative share). A steep first bar means one dominant style; a gentle staircase
# means the stocks differ along many directions at once. If the features were
# unrelated, every component would hold about 1 ÷ (number of features) of the
# variance, about 8% for 12 features; a PC1 holding several times that is a
# clear shared direction. The table twin lists the shares.
#
# ### Chart: what each component means (loadings)
#
# A **loading** is the correlation between a feature and a component's score.
# +0.8 means stocks high on that component are high on that feature. The sign of
# a component is arbitrary (PCA cannot tell "up" from "down"), so we flip each
# one to make its strongest loading positive.

# %%
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    load, pc_scores = oriented_loadings(Zs, scores_all, max(N_SHOW, 3))
    PC_NAMES = [f"PC{i + 1} ({evr[i]:.0%})" for i in range(load.shape[1])]
    loadings = pd.DataFrame(load, index=STYLE_USED, columns=[f"PC{i + 1}" for i in range(load.shape[1])])
    shown = loadings.iloc[:, :N_SHOW]
    home = shown.abs().idxmax(axis=1)                                     # each feature's strongest component
    feature_order = sorted(STYLE_USED, key=lambda f: (list(shown.columns).index(home[f]), -shown.loc[f].abs().max()))
    shown = shown.loc[feature_order]
    story = {pc: describe_pc(loadings[pc], n=4) for pc in shown.columns}

    fig = go.Figure(go.Heatmap(
        z=shown.to_numpy(), x=PC_NAMES[:N_SHOW], y=[label(f) for f in feature_order], colorscale=DIVERGING,
        zmin=-1, zmax=1, zmid=0, xgap=2, ygap=2, text=shown.map(lambda v: f"{v:+.2f}").to_numpy(),
        texttemplate="%{text}", textfont=dict(size=11),
        hovertemplate="%{y}<br>%{x}<br>loading %{z:+.2f}<extra></extra>",
        colorbar=dict(title=dict(text="Loading (r)", side="right"), thickness=14, len=0.8, outlinewidth=0)))
    fig.update_xaxes(side="top", ticks="", showgrid=False)
    fig.update_yaxes(autorange="reversed", ticks="", showgrid=False)
    title, top = chart_title(
        f"A high PC1 score ({evr[0]:.0%} of the variance) means {describe_pc(loadings['PC1'])}; a high PC2 score "
        f"({evr[1]:.0%}) means {describe_pc(loadings['PC2'], n=2)}",
        "Loading = correlation of each z-scored feature with each component's score · features grouped by their "
        "strongest component")
    top += 30                                                         # room for the component names on top
    fig.update_layout(title=title, height=top + 40 + 32 * len(feature_order), margin=dict(t=top, l=10, b=20),
                      plot_bgcolor=SURFACE)
    fig.show()
    display(Markdown("\n".join(f"- **{name}**: a high score means {story[pc]}; a low score means the opposite."
                               for pc, name in zip(shown.columns, PC_NAMES))))
    display(shown.rename(index=label).style.format("{:+.2f}"))

# %% [markdown]
# **How to read this.** Read down a column to name a component: its deep cells
# are the features it is made of. Blue features rise with the component's score,
# red ones fall. The sentences above the table give each component a plain
# summary. Typical patterns among large caps: a **trend** axis (the three
# moving-average gaps load together), a **value** axis (E/P, B/P, S/P and
# dividend yield against growth), and a **size and trading** axis. Let the
# numbers, not this sentence, tell you about today's market.
#
# **Caveats.** Components are statistical directions, not economic laws. They
# change from day to day, and a component that barely beats the noise line can
# swap places with its neighbour on a new sample. The map of each stock's
# scores comes in section 12.3, coloured by cluster.
#
# ### 11.2 A second PCA: do the factor returns overlap?
#
# Now we apply PCA to a different kind of data: the **daily returns** of the
# factor portfolios from section 7. Each column is a factor, each row a day.
# Standardising puts the volatile market factor on the same footing as the
# calmer long-short factors. If one component held most of the variance, the
# factors would mostly be one bet in several disguises. If the variance spreads
# out, each factor brings its own information, which is what "pure" factors are
# designed to do.
#
# We also check our correlation matrix against the one the API publishes
# (`data.data.aggregate.factor_correlation`). This part needs at least 3
# published factors with 30 shared days; when SurgeFlow's gates hold the
# factors back, it says so and moves on.

# %%
FACTOR_OK = aligned.shape[1] >= 3 and len(aligned) >= 30
if not FACTOR_OK:
    display(Markdown(f"> Only {aligned.shape[1]} factors with aligned return series came back (market "
                     f"{FACTOR_MARKET}; at least 3 with 30 shared days are needed), so there is no factor PCA today. "
                     "This is normal while the factors are blocked: re-run on another day, or see notebook 04."))
else:
    f_corr = aligned.corr()
    api_corr = fp["aggregate"]["factor_correlation"]
    if api_corr:
        api = pd.DataFrame(api_corr["values"], index=api_corr["factor_ids"], columns=api_corr["factor_ids"])
        common = [f for f in f_corr.columns if f in api.columns]
        gap = float((f_corr.loc[common, common] - api.loc[common, common]).abs().max().max())
        print(f"Our factor correlations vs the API's: largest difference {gap:.4f} over {len(common)} factors "
              f"({'match' if gap < 0.01 else 'check the alignment window'}).")
    f_pipe = Pipeline([("scale", StandardScaler()), ("pca", PCA(random_state=RANDOM_STATE))])
    f_scores = f_pipe.fit_transform(aligned)
    fZ = f_pipe.named_steps["scale"].transform(aligned)
    f_evr = f_pipe.named_steps["pca"].explained_variance_ratio_
    f_null = parallel_analysis(fZ, N_PERMUTATIONS, RANDOM_STATE)
    f_beats = f_evr > f_null
    F_KEEP = int(np.argmin(f_beats)) if not f_beats.all() else len(f_evr)
    equal_share = 1 / len(f_evr)
    fig = scree_figure(
        f_evr, f_null, F_KEEP,
        headline=f"The factors carry mostly separate information: PC1 holds {f_evr[0]:.0%} of the variance, against "
              f"{equal_share:.0%} if all {len(f_evr)} were unrelated" if f_evr[0] < 0.5
              else f"One direction dominates the factors: PC1 holds {f_evr[0]:.0%} of the variance",
        subtitle=f"PCA on z-scored daily returns of {len(f_evr)} {MARKET_NAMES[FACTOR_MARKET]} factor portfolios · "
                 f"{len(aligned)} aligned days · noise level from {N_PERMUTATIONS} shuffles")
    fig.show()
    display(pd.DataFrame({"variance_share": f_evr, "cumulative": np.cumsum(f_evr), "noise_95th": f_null},
                         index=[f"PC{i}" for i in range(1, len(f_evr) + 1)]).style.format("{:.1%}"))

# %% [markdown]
# **How to read this.** Same reading as the first scree plot. With unrelated
# factors every component would hold about 1 ÷ (number of factors) of the
# variance. The closer the bars are to that flat level, the more independent
# the factors. Shuffling ignores day-to-day patterns such as volatility
# clustering, so treat the noise line as a rough guide here.
#
# ### Chart: factor correlations and loadings side by side

# %%
if not FACTOR_OK:
    display(Markdown("> No factor PCA today (see the previous cell), so there is nothing to chart."))
else:
    f_load, _ = oriented_loadings(fZ, f_scores, len(f_evr))
    f_load = pd.DataFrame(f_load, index=aligned.columns, columns=[f"PC{i + 1}" for i in range(len(f_evr))])
    f_names = [FACTOR_NAME[f] for f in aligned.columns]
    pc1 = f_load["PC1"]
    together = [FACTOR_NAME[f] for f in pc1[pc1 >= 0.3].sort_values(ascending=False).index]
    against = [FACTOR_NAME[f] for f in pc1[pc1 <= -0.3].sort_values().index]
    f_story = (f"pits {' and '.join(together)} against {' and '.join(against)}" if together and against
               else f"moves {' and '.join(together)} together" if together else "has no dominant factor")
    pairs = f_corr.where(np.tril(np.ones(f_corr.shape, dtype=bool), k=-1)).stack()
    top_pair = pairs.abs().idxmax()
    f_tri = lower_triangle(f_corr)
    corr_values = f_tri.to_numpy()

    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.16, column_widths=[0.5, 0.5],
                        subplot_titles=("Correlation of daily returns", "Loadings on each component"))
    fig.add_trace(go.Heatmap(
        z=corr_values, x=[FACTOR_NAME[f] for f in f_tri.columns], y=[FACTOR_NAME[f] for f in f_tri.index],
        coloraxis="coloraxis", xgap=2, ygap=2, hoverongaps=False,
        text=[["" if np.isnan(v) else f"{v:+.2f}" for v in row] for row in corr_values], texttemplate="%{text}",
        hovertemplate="%{y}<br>%{x}<br>r = %{z:+.2f}<extra></extra>"), row=1, col=1)
    fig.add_trace(go.Heatmap(
        z=f_load.to_numpy(), x=[f"PC{i + 1} ({v:.0%})" for i, v in enumerate(f_evr)], y=f_names,
        coloraxis="coloraxis", xgap=2, ygap=2, text=f_load.map(lambda v: f"{v:+.2f}").to_numpy(),
        texttemplate="%{text}", hovertemplate="%{y}<br>%{x}<br>loading %{z:+.2f}<extra></extra>"), row=1, col=2)
    fig.update_layout(coloraxis=dict(colorscale=DIVERGING, cmin=-1, cmax=1, cmid=0,
                                     colorbar=dict(title=dict(text="r", side="right"), thickness=14, len=0.8,
                                                   outlinewidth=0)))
    fig.update_xaxes(tickangle=-35, ticks="", showgrid=False)
    fig.update_yaxes(autorange="reversed", ticks="", showgrid=False)
    title, top = chart_title(
        f"{FACTOR_NAME[top_pair[0]]} and {FACTOR_NAME[top_pair[1]]} are the most linked pair "
        f"(r = {f_corr.loc[top_pair]:+.2f}); PC1 {f_story}",
        f"{MARKET_NAMES[FACTOR_MARKET]} factors · {len(aligned)} days to {aligned.index[-1]:%Y-%m-%d} · "
        "loadings are correlations with each component's score")
    top += 30                                                         # room for the two panel titles
    fig.update_layout(title=title, height=top + 420, margin=dict(t=top, l=10, b=10), plot_bgcolor=SURFACE)
    fig.show()
    display(f_corr.rename(index=FACTOR_NAME, columns=FACTOR_NAME).style.format("{:+.2f}"))
    display(f_load.rename(index=FACTOR_NAME).style.format("{:+.2f}"))

# %% [markdown]
# **How to read this.** On the left, deep colours mark pairs of factors that
# tend to win or lose on the same days. A familiar pattern is value (HML) moving
# with investment (CMA) and against momentum (WML). On the right, each column
# is a component: factors with deep cells in the same column move together, and
# opposite colours mean they move in opposite directions. PC1 sums up the
# biggest shared swing; later columns are smaller, more specific ones.
#
# **Caveats.** Correlations between factors change over time; one year is a
# single regime. The market factor (ERP) is an index excess return, the others
# are long-short, so ERP's correlations mean something slightly different.

# %% [markdown]
# ## 12. Extension: clustering, our own map of styles
#
# ### 12.1 k-means, and how to choose k
#
# **k-means** places k centres, assigns every stock to its nearest centre,
# moves each centre to the average of its stocks, and repeats until nothing
# changes. It needs **z-scores** (the same standardised style features as the
# PCA): it measures straight-line distance, so an unscaled feature would
# dominate. Results depend on the random starting centres, so we run 20 starts
# (`n_init=20`) and fix `random_state`.
#
# **Choosing k.** Two pieces of evidence:
#
# - the **elbow**: inertia (the total squared distance of stocks to their
#   centres) always falls as k grows; we look for the k after which it falls
#   much more slowly;
# - the **silhouette**: for each stock, how much closer it is to its own
#   cluster than to the next nearest one, averaged (−1 to 1).
#
# Silhouette often favours k = 2, a coarse split that leaves one cluster with
# most of the stocks. SurgeFlow guards against that with a **balance cap**: no
# cluster may hold more than a set share of stocks (its run discloses it as
# `run.quality.balance_cap`). We apply the same rule: **the highest silhouette
# among the k whose largest cluster stays under the cap.**

# %%
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    CAP = float(quality["balance_cap"]) if ML_OK else BALANCE_CAP     # SurgeFlow's own cap when its run exists
    fits, scan = {}, []
    for k in K_RANGE:
        if k >= len(Zs):
            break
        km = KMeans(n_clusters=k, n_init=20, random_state=RANDOM_STATE).fit(Zs)
        fits[k] = km
        scan.append({"k": k, "inertia": km.inertia_, "silhouette": silhouette_score(Zs, km.labels_),
                     "largest_share": np.bincount(km.labels_).max() / len(Zs)})
    scan = pd.DataFrame(scan).set_index("k")
    scan["balanced"] = scan["largest_share"] <= CAP
    ks, inertia = scan.index.to_numpy(float), scan["inertia"].to_numpy()
    span = (ks - ks.min()) / max(ks.max() - ks.min(), 1)
    drop = (inertia - inertia.min()) / max(inertia.max() - inertia.min(), 1e-12)
    K_ELBOW = int(ks[np.argmax((1 - span) - drop)])       # farthest point below the straight line joining the ends
    pool = scan[scan["balanced"]] if scan["balanced"].any() else scan
    K = int(pool["silhouette"].idxmax())
    K_SF = int(quality["k"]) if ML_OK else None

    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.1,
                        subplot_titles=("Elbow: inertia falls as k grows", "Silhouette: higher is cleaner"))
    fig.add_trace(go.Scatter(x=scan.index, y=scan["inertia"], mode="lines+markers", name="Inertia",
                             line=dict(color=COLOR, width=2), marker=dict(size=8, color=COLOR),
                             showlegend=False, hovertemplate="k = %{x}<br>inertia %{y:,.0f}<extra></extra>"),
                  row=1, col=1)
    fig.add_annotation(x=K_ELBOW, y=scan.loc[K_ELBOW, "inertia"], text=f"elbow k = {K_ELBOW}", showarrow=True,
                       arrowhead=0, arrowcolor=MUTED, ax=40, ay=-40, font=dict(size=12, color=INK), row=1, col=1)
    fig.add_trace(go.Scatter(x=scan.index, y=scan["silhouette"], mode="lines", line=dict(color=GRID, width=2),
                             hoverinfo="skip", showlegend=False), row=1, col=2)
    for balanced, name, marker in ((True, f"Balanced: largest cluster ≤ {CAP:.0%}", dict(color=COLOR, size=10)),
                                   (False, f"Unbalanced: largest cluster > {CAP:.0%}",
                                    dict(color=MUTED, size=10, symbol="circle-open", line=dict(width=2)))):
        part = scan[scan["balanced"] == balanced]
        if part.empty:
            continue
        fig.add_trace(go.Scatter(x=part.index, y=part["silhouette"], mode="markers", name=name, marker=marker,
                                 customdata=part["largest_share"],
                                 hovertemplate="k = %{x}<br>silhouette %{y:.3f}<br>largest cluster "
                                               "%{customdata:.0%}<extra></extra>"), row=1, col=2)
    fig.add_trace(go.Scatter(x=[K], y=[scan.loc[K, "silhouette"]], mode="markers", name=f"Chosen k = {K}",
                             marker=dict(size=22, color="rgba(0,0,0,0)", line=dict(width=2.5, color=INK)),
                             hoverinfo="skip"), row=1, col=2)
    fig.update_xaxes(title_text="Number of clusters k", dtick=1)
    fig.update_yaxes(title_text="Inertia (sum of squared z-distances)", row=1, col=1)
    fig.update_yaxes(title_text="Mean silhouette (−1 to 1)", row=1, col=2)
    title, top = chart_title(
        f"k = {K}: the cleanest split (silhouette {scan.loc[K, 'silhouette']:.2f}) that keeps every cluster under "
        f"{CAP:.0%} of stocks",
        f"k-means on {len(STYLE_USED)} z-scored style features · {len(model):,} stocks · elbow at k = {K_ELBOW} · "
        f"SurgeFlow's run uses k = {K_SF or 'n/a'} on its whole market, with silhouettes in its own feature space")
    top += 30                                                         # room for the two panel titles
    fig.update_layout(title=title, height=500, margin=dict(t=top, b=110), legend=legend_below(500, top, 110))
    fig.show()
    twin = scan.copy()
    if ML_OK:
        sf_scan = pd.DataFrame(quality["k_scan"]).set_index("k").add_prefix("surgeflow_")
        twin = twin.join(sf_scan, how="left")
    display(twin.style.format({"inertia": "{:,.0f}", "silhouette": "{:.3f}", "largest_share": "{:.0%}",
                               "surgeflow_silhouette": "{:.3f}", "surgeflow_max_share": "{:.0%}"}, na_rep="—"))

# %% [markdown]
# **How to read this.** On the left, look for the bend: before it, each extra
# cluster removes a lot of distance; after it, little. On the right, filled dots
# are allowed by the balance cap, hollow ones are not; the ring marks our
# choice. Silhouettes this low are normal for stock features: the styles blend
# into each other rather than forming separate islands. The table twin adds
# SurgeFlow's own k-scan for reference. Its silhouettes come from a different
# feature space and a much larger universe, so compare their *shape*, not their
# level.
#
# ### 12.2 What our clusters look like
#
# Each row is one of our clusters, each column a feature; a cell is the
# cluster centre in z-score units. We number our clusters K1, K2, ... from the
# largest, and name them after their two most distinctive features.

# %%
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    km = fits[K]
    by_size = np.argsort(-np.bincount(km.labels_, minlength=K))
    renumber = {old: new for new, old in enumerate(by_size, start=1)}
    model["km_cluster"] = [f"K{renumber[c]}" for c in km.labels_]
    centres = pd.DataFrame(km.cluster_centers_[by_size], columns=STYLE_USED,
                           index=[f"K{i}" for i in range(1, K + 1)])
    KM_NAME = {cl: " · ".join(trait(f, row[f]) for f in row.abs().sort_values(ascending=False).index[:2])
               for cl, row in centres.iterrows()}                     # named after the two most distinctive traits
    sizes = model["km_cluster"].value_counts()
    R = max(1.0, float(np.ceil(centres.abs().stack().quantile(0.95) * 2) / 2))
    sharpest = centres.abs().stack().idxmax()

    fig = go.Figure(go.Heatmap(
        z=centres.to_numpy(), x=[label(f) for f in STYLE_USED],
        y=[f"<b>{cl}</b> {wrap(KM_NAME[cl], 36)} ({sizes[cl]})" for cl in centres.index],
        colorscale=DIVERGING, zmin=-R, zmax=R, zmid=0, xgap=2, ygap=2,
        text=centres.map(lambda v: f"{v:+.1f}").to_numpy(), texttemplate="%{text}", textfont=dict(size=10),
        hovertemplate="%{y}<br>%{x}<br>centre %{z:+.2f} SD<extra></extra>",
        colorbar=dict(title=dict(text="Centre (SD)", side="right"), thickness=14, len=0.85, outlinewidth=0)))
    fig.update_xaxes(tickangle=-40, ticks="", showgrid=False)
    fig.update_yaxes(autorange="reversed", ticks="", showgrid=False)
    title, top = chart_title(
        f"Our sharpest cluster trait: {sharpest[0]} sits {centres.loc[sharpest]:+.1f} SD from the average stock on "
        f"{lower_first(label(sharpest[1]))}",
        f"k-means centres (k = {K}) in z-score units · number of stocks in brackets · 0 = the average stock")
    fig.update_layout(title=title, height=top + 200 + 70 * K, margin=dict(t=top, l=10, b=10), plot_bgcolor=SURFACE)
    fig.show()
    display(centres.rename(columns=label).style.format("{:+.2f}"))

# %% [markdown]
# **How to read this.** Read across a row to see what defines a cluster: its
# deepest cells. Read down a column to see which clusters sit on opposite sides
# of a feature. The names are generated from the two deepest cells, so check
# them against the colours rather than taking them on trust.
#
# ### 12.3 Our clusters on the PCA map
#
# Every stock has a **score** on each principal component: its coordinates in
# the new axes. Plotting PC1 against PC2 gives a map of the stocks. With more
# clusters than a scatter can show in distinct colours, we use **small
# multiples**: each panel highlights one cluster's stocks over the grey cloud of
# all stocks. The title reports **η² (eta squared)**: the share of a component's
# spread that lies *between* clusters rather than within them. Because k-means
# used the same features, a high η² is expected; it tells you which components
# the clusters line up with.

# %%
def eta_squared(values: pd.Series, groups: pd.Series) -> float:
    """Between-group sum of squares / total sum of squares."""
    grand = values.mean()
    total = ((values - grand) ** 2).sum()
    between = sum(len(g) * (g.mean() - grand) ** 2 for _, g in values.groupby(groups))
    return float(between / total) if total else np.nan


if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    pcs = pd.DataFrame(pc_scores[:, :3], columns=["PC1", "PC2", "PC3"], index=model.index)
    eta = {pc: eta_squared(pcs[pc], model["km_cluster"]) for pc in pcs}
    km_order = list(centres.index)
    grid_cols = K if K <= 4 else int(np.ceil(K / 2))                  # a grid that fits K: 5 -> 3 x 2, 7 -> 4 x 2
    grid_rows = int(np.ceil(K / grid_cols))

    def panel_title(cl: str) -> str:
        traits = "<br>".join(wrap(t, 32) for t in KM_NAME[cl].split(" · "))   # one trait per line, never cut
        return f"<b>{cl}</b> {traits}<br><sup>{sizes[cl]} stocks</sup>"

    titles = [panel_title(cl) for cl in km_order]
    title_lines = max(t.count("<br>") + 1 for t in titles)
    fig = make_subplots(rows=grid_rows, cols=grid_cols, shared_xaxes=True, shared_yaxes=True, subplot_titles=titles,
                        horizontal_spacing=0.03,
                        vertical_spacing=(0.1 + 0.03 * title_lines) if grid_rows > 1 else 0.1)
    sf_text = model["sf_cluster_id"].map(lambda c: "no SurgeFlow label" if pd.isna(c) else f"SurgeFlow {LABEL[c]}")
    hover = np.column_stack([model["ticker"], model["company_name"].map(shorten), model["sector"].fillna("n/a"),
                             sf_text])
    for i, cl in enumerate(km_order):
        r_, c_ = divmod(i, grid_cols)
        member = model["km_cluster"].eq(cl).to_numpy()
        fig.add_trace(go.Scatter(x=pcs["PC1"], y=pcs["PC2"], mode="markers", name="All stocks",
                                 legendgroup="all", showlegend=(i == 0), hoverinfo="skip",
                                 marker=dict(color=GRID, size=4, line=dict(width=0))), row=r_ + 1, col=c_ + 1)
        fig.add_trace(go.Scatter(
            x=pcs.loc[member, "PC1"], y=pcs.loc[member, "PC2"], mode="markers", name="Stocks of the panel's cluster",
            legendgroup="member", showlegend=(i == 0),
            marker=dict(color=COLOR, size=6, line=dict(width=0.5, color=SURFACE)), customdata=hover[member],
            hovertemplate="<b>%{customdata[0]}</b> %{customdata[1]}<br>%{customdata[2]} · %{customdata[3]}"
                          "<br>PC1 %{x:+.2f} · PC2 %{y:+.2f}<extra></extra>"),
            row=r_ + 1, col=c_ + 1)
    fig.update_annotations(font_size=11)
    for i in range(K, grid_rows * grid_cols):                         # hide the empty cells of the grid
        r_, c_ = divmod(i, grid_cols)
        fig.update_xaxes(visible=False, row=r_ + 1, col=c_ + 1)
        fig.update_yaxes(visible=False, row=r_ + 1, col=c_ + 1)
    for c_ in range(grid_cols):                                       # x ticks and title under each column's last panel
        lowest = max(r_ for r_ in range(grid_rows) if r_ * grid_cols + c_ < K)
        fig.update_xaxes(title_text=f"PC1 score ({evr[0]:.0%})", showticklabels=True, row=lowest + 1, col=c_ + 1)
    for r_ in range(1, grid_rows + 1):
        fig.update_yaxes(title_text=f"PC2 score ({evr[1]:.0%})", row=r_, col=1)
    title, top = chart_title(
        f"Our {K} clusters line up with the first components: the cluster explains {eta['PC1']:.0%} of PC1's "
        f"spread, {eta['PC2']:.0%} of PC2's and {eta['PC3']:.0%} of PC3's",
        f"PC scores of {len(model):,} stocks (grey) · each panel highlights one k-means cluster · hover for sector and "
        "SurgeFlow label")
    top += 16 * title_lines                                           # room for the first row of panel titles
    height = top + 110 + (240 + 16 * title_lines) * grid_rows
    fig.update_layout(title=title, height=height, margin=dict(t=top, b=110), legend=legend_below(height, top, 110))
    fig.show()
    centroids = pcs.groupby(model["km_cluster"]).mean().reindex(km_order)
    centroids["stocks"] = sizes.reindex(km_order)
    centroids.insert(0, "name", [KM_NAME[cl] for cl in km_order])
    display(centroids.style.format({"PC1": "{:+.2f}", "PC2": "{:+.2f}", "PC3": "{:+.2f}"}))

# %% [markdown]
# **How to read this.** Compare where the coloured dots sit in each panel. A
# compact patch in one corner means the cluster is a clear style on these two
# components; a patch spread over the cloud means the cluster is defined by
# something PC1 and PC2 do not capture (a later component). The table twin
# lists each cluster's average position.
#
# ### Chart: the same map in 3D
#
# Adding PC3 can separate clusters that overlap in two dimensions. Use the menu
# to highlight one cluster at a time; drag to rotate, scroll to zoom. At most
# three colours are used: the highlighted cluster, the other stocks and, as
# open diamonds, the few stocks whose SurgeFlow cluster we know.

# %%
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    text = (model["ticker"] + " · " + model["company_name"].map(shorten) + " · " + model["km_cluster"]
            + " · " + sf_text).to_numpy()

    def xyz(mask):
        return [pcs.loc[mask, pc].round(3).tolist() for pc in ("PC1", "PC2", "PC3")]

    first = km_order[0]
    hi = model["km_cluster"].eq(first).to_numpy()
    fig = go.Figure()
    for mask, name, colour, size in ((~hi, "Other stocks", MUTED, 3), (hi, f"{first} (highlighted)", COLOR, 5)):
        x3, y3, z3 = xyz(mask)
        fig.add_trace(go.Scatter3d(x=x3, y=y3, z=z3, mode="markers", name=name, hovertext=text[mask].tolist(),
                                   hoverinfo="text", marker=dict(size=size, color=colour, line=dict(width=0))))
    labelled = model["sf_cluster_id"].notna().to_numpy()
    if labelled.any():
        x3, y3, z3 = xyz(labelled)
        fig.add_trace(go.Scatter3d(x=x3, y=y3, z=z3, mode="markers", name="Has a SurgeFlow label",
                                   hovertext=text[labelled].tolist(), hoverinfo="text",
                                   marker=dict(size=6, color=INK, symbol="diamond-open")))
    buttons = []
    for cl in km_order:
        hi = model["km_cluster"].eq(cl).to_numpy()
        (ox, oy, oz), (hx, hy, hz) = xyz(~hi), xyz(hi)
        buttons.append(dict(label=f"{cl} {shorten(KM_NAME[cl], 34)}", method="restyle",
                            args=[{"x": [ox, hx], "y": [oy, hy], "z": [oz, hz],
                                   "hovertext": [text[~hi].tolist(), text[hi].tolist()],
                                   "name": ["Other stocks", f"{cl} (highlighted)"]}, [0, 1]]))
    fig.update_layout(
        updatemenus=[dict(buttons=buttons, direction="down", x=0, xanchor="left", y=1.0, yanchor="top",
                          showactive=True, bgcolor="white", bordercolor=GRID, font=dict(size=12))],
        scene=dict(xaxis_title=f"PC1 ({evr[0]:.0%})", yaxis_title=f"PC2 ({evr[1]:.0%})",
                   zaxis_title=f"PC3 ({evr[2]:.0%})", aspectmode="cube"),
        title=chart_title(f"PC1-PC3 hold {np.cumsum(evr)[2]:.0%} of the variance: pick a cluster to see where it "
                          "sits", f"PC scores of {len(model):,} stocks · drag to rotate · "
                          f"{plural(labelled.sum(), 'stock')} with a SurgeFlow label shown as open diamonds")[0],
        height=660, margin=dict(t=110, l=0, r=0, b=0), legend=dict(orientation="h", x=0, y=0, yanchor="top",
                                                                   itemsizing="constant"))
    fig.show()

# %% [markdown]
# **How to read this.** Pick a cluster and rotate the cube. If its dots form a
# compact blob away from the rest, the first three components describe that
# style well. The table twin is the same as for the 2D map above.
#
# ### 12.4 Ward hierarchical clustering, the dendrogram
#
# A second, different algorithm. **Agglomerative** clustering starts with every
# stock on its own and repeatedly merges the two closest groups. **Ward's**
# rule merges the pair whose union increases the within-group variance the
# least, the same objective k-means minimises, reached by a different route.
# The full merge history is a tree, the **dendrogram**: the height of each join
# is how dissimilar the two merged groups were. Cutting the tree horizontally
# gives clusters; we cut it into the same k as k-means.

# %%
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    ward_labels = AgglomerativeClustering(n_clusters=K, linkage="ward").fit_predict(Zs)
    idx = np.arange(len(Zs))
    if len(idx) > DENDRO_MAX_LEAVES:
        idx = np.sort(np.random.default_rng(RANDOM_STATE).choice(len(Zs), DENDRO_MAX_LEAVES, replace=False))
    Zd = Zs[idx]
    tickers = model["ticker"].to_numpy()[idx]
    fig = ff.create_dendrogram(Zd, labels=list(tickers), linkagefun=lambda d: sch.linkage(d, method="ward"))

    link = sch.linkage(Zd, method="ward")                       # the same tree, to read heights and groups
    cut = (link[-K, 2] + link[-(K - 1), 2]) / 2                 # between the merges that leave K and K - 1 groups
    groups = sch.fcluster(link, K, criterion="maxclust")        # group of each sampled stock
    leaves = sch.dendrogram(link, no_plot=True)["leaves"]       # left-to-right order of the stocks
    leaf_group = np.array([groups[i] for i in leaves])
    order_seen = list(dict.fromkeys(leaf_group))                # groups numbered left to right: W1, W2, ...
    W_NAME = {g: f"W{i}" for i, g in enumerate(order_seen, start=1)}
    # Not market colours (SERIES[0:4] mean us, cn, jp, hk in this kit). With more groups than colours, the colours
    # repeat (neighbours always differ), the legend is hidden, and the W labels under the leaves name each group.
    W_PALETTE = SERIES[4:] + [INK_2]
    W_COLOR = {g: W_PALETTE[i % len(W_PALETTE)] for i, g in enumerate(order_seen)}
    W_LEGEND = len(order_seen) <= len(W_PALETTE)
    for trace in fig.data:                                      # recolour: below the cut by group, above in grey
        xs, ys = np.asarray(trace.x, float), np.asarray(trace.y, float)
        if ys.max() > cut:
            colour = MUTED
        else:
            position = int(np.clip(round((xs.mean() - 5) / 10), 0, len(leaves) - 1))
            colour = W_COLOR[leaf_group[position]]
        trace.update(line=dict(color=colour, width=1.4), marker=dict(color=colour), hoverinfo="skip",
                     showlegend=False)
    leaf_rows = idx[leaves]
    for g in order_seen:
        pos = np.where(leaf_group == g)[0]
        fig.add_annotation(x=5 + 10 * pos.mean(), y=0, yshift=-14, text=f"<b>{W_NAME[g]}</b>", showarrow=False,
                           font=dict(size=11, color=W_COLOR[g]))
        fig.add_trace(go.Scatter(
            x=5 + 10 * pos, y=np.zeros(len(pos)), mode="markers", name=f"{W_NAME[g]} ({len(pos)} stocks)",
            showlegend=W_LEGEND,
            marker=dict(color=W_COLOR[g], size=5, symbol="line-ns", line=dict(width=1.5, color=W_COLOR[g])),
            customdata=np.column_stack([model["ticker"].to_numpy()[leaf_rows[pos]],
                                        model["company_name"].map(shorten).to_numpy()[leaf_rows[pos]],
                                        model["km_cluster"].to_numpy()[leaf_rows[pos]],
                                        model["sector"].fillna("n/a").to_numpy()[leaf_rows[pos]]]),
            hovertemplate="<b>%{customdata[0]}</b> %{customdata[1]}<br>%{customdata[3]} · Ward " + W_NAME[g]
                          + " · k-means %{customdata[2]}<extra></extra>"))
    fig.add_hline(y=cut, line=dict(color=INK_2, dash="dash", width=1.5),
                  annotation_text=f"cut for k = {K}", annotation_position="top right",
                  annotation_font=dict(size=12, color=INK_2))
    shares = pd.Series(leaf_group).value_counts(normalize=True)
    fig.update_xaxes(showticklabels=False, ticks="", title_text=f"Stocks (leaves), {len(idx)} shown",
                     title_standoff=24, showgrid=False)                # room for the W labels under the leaves
    fig.update_yaxes(title_text="Ward merge height (z-score distance)", showgrid=True, gridcolor=GRID)
    title, top = chart_title(
        f"Cutting Ward's tree at height {cut:.1f} gives {K} groups; the largest holds {shares.max():.0%} of the "
        "stocks shown",
        ("All " if len(idx) == len(Zs) else f"A fixed random sample of {len(idx)} of ")
        + f"{len(Zs):,} stocks · Ward linkage on the {len(STYLE_USED)} z-scored style features · hover a leaf "
          "for the stock")
    fig.update_layout(width=None, autosize=True, height=540, showlegend=True, hovermode="closest", title=title,
                      margin=dict(t=top, b=110), legend=legend_below(540, top, 110, gap=48))
    fig.show()
    check = adjusted_rand_score(ward_labels[idx], groups) if len(idx) == len(Zs) else np.nan
    if not np.isnan(check):
        print(f"scikit-learn's AgglomerativeClustering and scipy's tree agree: ARI = {check:.2f}.")
    display(pd.DataFrame({"stocks": pd.Series(leaf_group).map(W_NAME).value_counts()}).sort_index().T)

# %% [markdown]
# **How to read this.** Each leaf at the bottom is a stock; follow the branches
# up to see when it joins others. Low joins are close look-alikes; the tall
# joins near the top merge very different groups. The dashed line is the cut:
# every branch it crosses becomes one cluster, coloured below the line (grey
# above it) and labelled W1, W2, ... under its leaves, left to right. With more
# groups than the chart has colours (five), the colours repeat and the labels
# tell the groups apart. Long vertical stems just below the cut mean
# well-separated groups; a cut through a dense thicket means the boundary is
# fuzzy.
#
# ### 12.5 Compare clusterings: the adjusted Rand index
#
# The **adjusted Rand index (ARI)** looks at every *pair* of stocks and asks: do
# both clusterings put this pair together, or both apart? It then subtracts the
# agreement expected by pure chance. **ARI = 1** means identical groupings (the
# labels' names do not matter); **ARI ≈ 0** means no better than random. It
# works even when the two clusterings use different numbers of clusters.
#
# We compare our k-means clusters with three references:
#
# 1. **Ward's clusters** (same features, different algorithm): is our grouping
#    stable?
# 2. **Sectors** from the screen, available for every stock: are our styles
#    just industries in disguise?
# 3. **SurgeFlow's clusters**, on the stocks whose SurgeFlow label we know
#    (section 6), when at least `MIN_LABELLED` of them survive the cleaning.
#    That is rare (at the time of writing only `jp` comes close); section 12.6
#    adds a cluster-level comparison that works for every market.
#
# To judge each score we also **shuffle** the reference labels many times and
# record the ARI of each shuffle: that is what "chance" looks like for this
# sample. With `N_PERMUTATIONS = 200` shuffles a p-value cannot go below
# 1 ÷ 201 ≈ 0.005, so "<0.005" means that no shuffle came close.

# %%
SF_OK = False
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    gen = np.random.default_rng(RANDOM_STATE)

    def compare(name: str, reference: np.ndarray, ours: np.ndarray) -> dict:
        """ARI between a reference labelling and ours, plus the chance level from shuffled reference labels."""
        observed = adjusted_rand_score(reference, ours)
        null = np.array([adjusted_rand_score(gen.permutation(reference), ours) for _ in range(N_PERMUTATIONS)])
        return {"comparison": name, "stocks": len(reference), "ARI": observed, "chance_95th": np.percentile(null, 95),
                "p_value": (1 + (null >= observed).sum()) / (1 + N_PERMUTATIONS)}

    km_labels = fits[K].labels_
    has_sector = model["sector"].notna().to_numpy()
    sector = model.loc[has_sector, "sector"].astype(str).to_numpy()
    rows = [
        compare(f"k-means vs Ward, both k = {K}", ward_labels, km_labels),
        compare(f"k-means (k = {K}) vs sectors", sector, km_labels[has_sector]),
        compare(f"Ward (k = {K}) vs sectors", sector, ward_labels[has_sector]),
    ]
    lab = model["sf_cluster_id"].notna().to_numpy()
    SF_OK = ML_OK and lab.sum() >= MIN_LABELLED and model.loc[lab, "sf_cluster_id"].nunique() >= 2
    if SF_OK:
        sf = model.loc[lab, "sf_cluster_id"].astype(int).to_numpy()
        km_sf_k = (fits[K_SF] if K_SF in fits else
                   KMeans(n_clusters=K_SF, n_init=20, random_state=RANDOM_STATE).fit(Zs)).labels_
        rows += [compare(f"k-means (k = {K}) vs SurgeFlow", sf, km_labels[lab]),
                 compare(f"k-means (k = {K_SF}, SurgeFlow's k) vs SurgeFlow", sf, km_sf_k[lab]),
                 compare(f"Ward (k = {K}) vs SurgeFlow", sf, ward_labels[lab])]
    ari = pd.DataFrame(rows).set_index("comparison")
    display(ari.style.format({"ARI": "{:.3f}", "chance_95th": "{:.3f}",
                              "p_value": lambda p: fmt_perm_p(p, N_PERMUTATIONS)}, na_rep="—"))
    if not SF_OK and not ML_OK:
        display(Markdown(f"> **No comparison with SurgeFlow's clusters today:** its ML run for "
                         f"{MARKET_NAMES[MARKET]} is unavailable (section 6). The sector comparison still stands."))
    elif not SF_OK:
        lost = sorted(set(sf_labels.loc[sf_labels["in_sample"], "ticker"]) - set(model["ticker"]))
        display(Markdown(
            f"> **No stock-by-stock comparison with SurgeFlow's clusters today:** only {int(lab.sum())} of our "
            f"{len(model):,} stocks {'carries' if lab.sum() == 1 else 'carry'} a SurgeFlow label (at least "
            f"{MIN_LABELLED} in two or more clusters are needed)"
            + (f"; {plural(len(lost), 'labelled stock')} ({', '.join(lost)}) left the sample during cleaning"
               if lost else "")
            + ". The v1 payload names a few typical, unusual or switching members per cluster, and few of them are "
            "among the largest companies. Section 12.6 compares the clusters by sector mix instead; for a "
            "stock-by-stock ARI " + ("try `MARKET = \"jp\"`, or " if MARKET != "jp" else "")
            + "raise `SCREEN_PAGES` to reach further down the market."))
    else:
        by_source = []
        for source in SOURCES:
            mask = (model.loc[lab, "sf_source"] == source).to_numpy()
            if mask.sum() >= 8 and len(set(sf[mask])) > 1:
                by_source.append({"labels from": source, "stocks": int(mask.sum()),
                                  "ARI (k-means, ours)": adjusted_rand_score(sf[mask], km_labels[lab][mask])})
        if by_source:
            print("The k-means ARI with SurgeFlow, split by where the SurgeFlow label came from:")
            display(pd.DataFrame(by_source).set_index("labels from").style.format({"ARI (k-means, ours)": "{:.3f}"}))

# %% [markdown]
# **How to read this.** Compare each ARI with its `chance_95th` column: an ARI
# above it beats 95% of random relabellings, and `p_value` says how often chance
# did as well. k-means and Ward usually agree well above chance (first row) but
# not perfectly: two routes to the same objective can still draw different
# borders. Against sectors, an ARI near 0 says our style clusters cut
# across industries: a bank and a utility can share a style. An ARI of 0.2-0.5
# against SurgeFlow would mean clearly more than chance, yet far from
# identical: two maps of the same market drawn from different features.
#
# ### Chart: the contingency table, who went where
#
# Rows are the reference groups, columns our clusters; each cell counts the
# stocks in both and says what **share of its row** that is. The colour shows
# the share, not the count, so a small sector that lands in one cluster is as
# dark as a large one; empty cells stay blank. We reorder our columns so that
# each one sits under the reference group it overlaps most (an optimal
# matching, the Hungarian algorithm), so agreement shows up along the diagonal.
# The first table uses sectors (every stock has one); a second one uses
# SurgeFlow's clusters when enough labels reach our sample.

# %%
def contingency(reference: pd.Series, ours: pd.Series) -> tuple:
    """Cross-tabulate a reference labelling (rows, largest first) against our clusters (columns, matched to rows
    by the Hungarian algorithm so that agreement lies on the diagonal). Returns counts and row shares."""
    table = pd.crosstab(reference, ours)
    table = table.loc[table.sum(axis=1).sort_values(ascending=False).index]
    rows_i, cols_i = linear_sum_assignment(-table.to_numpy())
    matched = [table.columns[j] for _, j in sorted(zip(rows_i, cols_i))]
    table = table[matched + [c for c in table.columns if c not in matched]]
    return table, table.div(table.sum(axis=1), axis=0)


def contingency_figure(table: pd.DataFrame, share: pd.DataFrame, row_names: dict, headline: str,
                       subtitle: str) -> go.Figure:
    """Heatmap of the contingency table: one row per reference group, one column per cluster of ours. The colour is
    the row share (0-100%), the text the count and the share; empty cells stay blank."""
    counts = table.to_numpy()
    z = np.where(counts > 0, share.to_numpy(dtype=float), np.nan)     # "none" is blank, not the palette's first step
    fig = go.Figure(go.Heatmap(
        z=z, x=[f"<b>{c}</b>" for c in table.columns], y=[row_names[i] for i in table.index],
        colorscale=[[i / 6, c] for i, c in enumerate(SEQUENTIAL)], zmin=0, zmax=1, xgap=2, ygap=2,
        hoverongaps=False,
        text=[[f"{n} ({v:.0%})" if n else "" for n, v in zip(cr, sr)] for cr, sr in zip(counts, z)],
        texttemplate="%{text}", textfont=dict(size=11),
        customdata=np.dstack([counts.astype(str), np.tile([KM_NAME[c] for c in table.columns], (len(table), 1))]),
        hovertemplate="%{y}<br>%{x} %{customdata[1]}<br>%{customdata[0]} stocks (%{z:.0%} of the row)"
                      "<extra></extra>",
        colorbar=dict(title=dict(text="Share of the row (%)", side="right"), tickformat=".0%", thickness=14,
                      len=0.85, outlinewidth=0)))
    fig.update_xaxes(side="top", ticks="", showgrid=False, title_text=f"Our k-means clusters (k = {K})")
    fig.update_yaxes(autorange="reversed", ticks="", showgrid=False, title_text=None)
    title, top = chart_title(headline, subtitle)
    top += 50                                                         # room for the axis title and labels on top
    fig.update_layout(title=title, height=top + 60 + 44 * len(table), margin=dict(t=top, l=10, b=10),
                      plot_bgcolor=SURFACE)
    return fig


if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
else:
    sec = model.loc[has_sector, "sector"].astype(str)
    a_sec = ari.loc[f"k-means (k = {K}) vs sectors"]
    sec_sizes = sec.value_counts()
    table, share = contingency(sec, model.loc[has_sector, "km_cluster"])
    big = share[table.sum(axis=1) >= 5]                               # judge "cleanest" on sectors of 5+ stocks
    top_row = (big if not big.empty else share).max(axis=1).idxmax()
    verdict = ("mostly cut across sectors" if a_sec["ARI"] < 0.1 else "partly follow sectors"
               if a_sec["ARI"] < 0.3 else "largely follow sectors")
    fig = contingency_figure(
        table, share, {s: f"{s} ({sec_sizes[s]})" for s in sec_sizes.index},
        f"Our style clusters {verdict} (ARI {a_sec['ARI']:.2f}, chance level {a_sec['chance_95th']:.2f}); "
        f"{top_row} is the most concentrated sector, {share.loc[top_row].max():.0%} of it in one cluster",
        f"{len(sec):,} stocks · rows: screen sectors with their size · columns ordered by an optimal matching · "
        "hover for our cluster's name")
    fig.show()
    twin = table.copy()
    twin.columns = [f"{c} {KM_NAME[c]}" for c in table.columns]
    display(twin.style.format("{:d}"))

    if SF_OK:
        a_sf = ari.loc[f"k-means (k = {K}) vs SurgeFlow"]
        table, share = contingency(pd.Series(sf, index=model.index[lab]), model.loc[lab, "km_cluster"])
        big = share[table.sum(axis=1) >= 5]                           # judge "cleanest" on clusters of 5+ stocks
        verdict = "well above" if a_sf["p_value"] < 0.05 else "not clearly above"
        purity = table.max(axis=1).sum() / table.to_numpy().sum()
        if big.empty:
            detail = f"with only {plural(lab.sum(), 'labelled stock')}, read the table as a sketch"
        else:
            top_row = big.max(axis=1).idxmax()
            detail = f"{LABEL[top_row]} lands most cleanly, {big.loc[top_row].max():.0%} of it in one of our clusters"
        fig = contingency_figure(
            table, share, {c: f"<b>{LABEL[c]}</b> {wrap(NAME[c], 36)}" for c in table.index},
            f"Our k = {K} map agrees with SurgeFlow's clusters {verdict} chance (ARI {a_sf['ARI']:.2f}); {detail}",
            f"{int(lab.sum())} stocks with a SurgeFlow label · {purity:.0%} of them sit in the column where their "
            "SurgeFlow cluster is most common · columns ordered by an optimal matching")
        fig.show()
        twin = table.rename(index=LABEL)
        twin.columns = [f"{c} {KM_NAME[c]}" for c in table.columns]
        display(twin.style.format("{:d}"))
    else:
        display(Markdown("> The SurgeFlow contingency table is skipped for the same reason as the SurgeFlow "
                         "comparison above."))

# %% [markdown]
# **How to read this.** Each row adds up to 100%, and the colour shows each
# cell's share of its row, so small and large groups are read alike. A row with
# one dark cell is a group our k-means recovered in one piece; a row spread
# across several pale cells is a group our features split up. Blank cells hold
# no stock. With fewer clusters
# than rows, some of our columns must gather several rows: read which ones go
# together, because they are neighbouring styles on our features. Sectors with
# a distinctive style (utilities and banks pay dividends and trade cheaply;
# chip makers trend and trade heavily) concentrate; broad sectors scatter.
#
# **Caveats.**
#
# - SurgeFlow clusters its whole market on its own feature set (volatility,
#   drawdowns, leverage and more, many of them not on the screen), with a
#   consensus of three algorithms and its own scaling. Perfect agreement is
#   neither expected nor the goal.
# - The SurgeFlow-labelled stocks are not a random sample: representatives are
#   the most typical members, anomalies the least typical.
# - k-means prefers round, similar-sized groups. A different algorithm
#   (exercise 5) can find differently shaped clusters.
# - The sample is the largest companies only; a different slice of the market
#   would cluster differently.

# %% [markdown]
# ### 12.6 Cluster-level comparison with SurgeFlow: sector mixes
#
# The stock-by-stock ARI needs SurgeFlow labels on our stocks, and v1 rarely
# names enough of the largest companies. Every SurgeFlow cluster, however,
# discloses its `sector_mix`: how many of its members sit in each of its
# largest sectors. We can describe each of our k-means clusters the same way and
# compare the two **profiles**, cluster by cluster:
#
# 1. Turn each cluster's sector counts into a profile (shares of its members).
# 2. Measure how alike two profiles are with **cosine similarity**: 1 = the same
#    sector proportions, 0 = no sector in common.
# 3. Pair our clusters with SurgeFlow's so that the total similarity is as high
#    as possible (the Hungarian algorithm again).
# 4. Use a **yardstick**: the similarity of each SurgeFlow cluster with the
#    sector mix of our *whole sample*. A pair only tells us something when it
#    beats that yardstick; otherwise our cluster simply looks like the large-cap
#    market as a whole.
#
# This is a coarse comparison. It sees sectors only, not the styles inside them,
# and it is the part of the comparison that works with v1 data on every run.

# %%
SECTOR_SKIP = {"Unknown", "Unclassified"}       # "no sector" says nothing about a profile, so it is left out
LIFT_MIN = 0.05                                 # a pair must beat the whole-sample yardstick by this much to count
if not ENOUGH:
    display(Markdown(NOT_ENOUGH))
elif not ML_OK or clusters.empty:
    display(Markdown("> SurgeFlow's ML run is unavailable (section 6), so there are no sector mixes to compare."))
else:
    sf_mix = pd.DataFrame([dict(mix or {}) for mix in clusters["sector_mix"]], index=clusters["cluster_id"])
    sf_mix = sf_mix.apply(pd.to_numeric, errors="coerce").fillna(0)
    named_share = sf_mix.sum(axis=1) / clusters.set_index("cluster_id")["ticker_count"]   # members the mix names
    ours_mix = pd.crosstab(model["km_cluster"], model["sector"]).reindex(km_order).fillna(0)
    sample_mix = model["sector"].value_counts().to_frame().T
    sectors = sorted((set(sf_mix.columns) | set(ours_mix.columns)) - SECTOR_SKIP)

    def profiles(counts: pd.DataFrame) -> np.ndarray:
        """Sector counts -> unit-length rows over `sectors` (cosine similarity is then a dot product)."""
        m = counts.reindex(columns=sectors, fill_value=0).to_numpy(dtype=float)
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        return np.divide(m, norms, out=np.zeros_like(m), where=norms > 0)

    sf_p, ours_p, sample_p = profiles(sf_mix), profiles(ours_mix), profiles(sample_mix)[0]
    sim = pd.DataFrame(sf_p @ ours_p.T, index=sf_mix.index, columns=km_order)
    yardstick = pd.Series(sf_p @ sample_p, index=sf_mix.index)
    rows_i, cols_i = linear_sum_assignment(-sim.to_numpy())
    pairs = pd.DataFrame({"surgeflow": [LABEL[c] for c in sim.index[rows_i]],
                          "surgeflow_name": [NAME[c] for c in sim.index[rows_i]],
                          "ours": sim.columns[cols_i], "our_name": [KM_NAME[c] for c in sim.columns[cols_i]],
                          "cosine": sim.to_numpy()[rows_i, cols_i], "whole_sample": yardstick.iloc[rows_i].to_numpy()})
    pairs["lift"] = pairs["cosine"] - pairs["whole_sample"]
    n_beat = int((pairs["lift"] >= LIFT_MIN).sum())

    matched = {sim.index[i]: sim.columns[j] for i, j in zip(rows_i, cols_i)}
    row_order = [c for c in sim.index if c in matched] + [c for c in sim.index if c not in matched]
    col_order = list(dict.fromkeys([matched[c] for c in row_order if c in matched] + km_order))
    shown = sim.loc[row_order, col_order].assign(whole_sample=yardstick)          # the pairs form the diagonal
    is_pair = np.array([[matched.get(r) == c for c in shown.columns] for r in shown.index])
    text = [[f"<b>{v:.2f}</b>" if pair else f"{v:.2f}" for v, pair in zip(row, prow)]
            for row, prow in zip(shown.to_numpy(), is_pair)]
    fig = go.Figure(go.Heatmap(
        z=shown.to_numpy(), x=[f"<b>{c}</b>" for c in col_order] + ["<i>whole sample</i>"],
        y=[f"<b>{LABEL[c]}</b> {wrap(NAME[c], 36)}" for c in shown.index],
        colorscale=[[i / 6, c] for i, c in enumerate(SEQUENTIAL)], zmin=0, zmax=1, xgap=2, ygap=2,
        text=text, texttemplate="%{text}", textfont=dict(size=11),
        customdata=np.tile([KM_NAME[c] for c in col_order] + ["all our stocks (the yardstick)"], (len(shown), 1)),
        hovertemplate="%{y}<br>%{x} %{customdata}<br>cosine similarity of sector mixes %{z:.2f}<extra></extra>",
        colorbar=dict(title=dict(text="Cosine similarity", side="right"), thickness=14, len=0.85, outlinewidth=0)))
    fig.update_xaxes(side="top", ticks="", showgrid=False, title_text=f"Our k-means clusters (k = {K})")
    fig.update_yaxes(autorange="reversed", ticks="", showgrid=False, title_text=None)
    headline = (f"By sector mix, {n_beat} of {len(pairs)} paired SurgeFlow clusters resemble one of ours clearly "
                f"better than our whole sample (mean cosine {pairs['cosine'].mean():.2f} vs "
                f"{pairs['whole_sample'].mean():.2f})")
    title, top = chart_title(headline, (
        f"Clearly better = a cosine at least {LIFT_MIN:.2f} above the yardstick · "
        f"rows: SurgeFlow's {len(sim)} clusters (its whole market), paired ones first · columns: our {K} clusters, "
        f"in pairing order (pairs in bold) · last column: our whole sample, the yardstick · SurgeFlow's sector_mix "
        f"names {named_share.min():.0%}-{named_share.max():.0%} of each cluster's members · "
        f"{', '.join(sorted(SECTOR_SKIP))} left out"))
    top += 50                                                         # room for the axis title and labels on top
    fig.update_layout(title=title, height=top + 60 + 44 * len(shown), margin=dict(t=top, l=10, b=10),
                      plot_bgcolor=SURFACE)
    fig.show()
    display(pairs.style.format({"cosine": "{:.2f}", "whole_sample": "{:.2f}", "lift": "{:+.2f}"})
            .hide(axis="index"))

# %% [markdown]
# **How to read this.** Read each row: the bold cell is the cluster of ours
# paired with that SurgeFlow cluster, and the last column is the yardstick. A
# bold cell clearly above the yardstick (the `lift` column in the table) means
# the two clusters lean towards the same sectors more than the market does: a
# shared, sector-flavoured style. A bold cell at or below the yardstick means
# the pairing is only as good as comparing with the whole sample. When our
# clusters cut across sectors (a low ARI with sectors in section 12.5), expect
# few clear pairs: our styles then differ inside sectors, which a sector profile
# cannot see.
#
# **Caveats.**
#
# - SurgeFlow's `sector_mix` lists only each cluster's largest sectors (six at
#   the time of writing; the subtitle gives the share of members they cover).
#   The members it does not name count as 0 here, which favours the big
#   sectors.
# - SurgeFlow clusters its whole market, small caps included; we cluster the
#   largest companies. The same style can have a different sector mix in the
#   two universes.
# - Cosine similarity ignores cluster size: a cluster of 8 stocks and one of
#   800 can share a profile.
# - Sector profiles are coarse. A match says the two clusters lean towards the
#   same sectors, not that they hold the same stocks; only the stock-by-stock
#   ARI can say that.

# %% [markdown]
# ## 13. Exercises for the reader
#
# Each exercise changes one thing. Re-run the affected cells and compare.
#
# 1. **Move winsorising inside the `Pipeline`.** Write a small transformer
#    (`sklearn.preprocessing.FunctionTransformer` or a class with `fit` and
#    `transform`) that learns the 1%/99% clip points on the training folds
#    only. Does the cross-validated R² of section 10.5 change?
# 2. **Add sector fixed effects.** One-hot encode `sector`
#    (`pd.get_dummies(model["sector"], drop_first=True)`) and add the dummies to
#    the regression. How much does R² rise? Which feature coefficients survive
#    once each stock is compared only with its own sector?
# 3. **Leakage, by hand.** Replace `ma10_gap_prev` with `ma10_excess` in the
#    cross-validated `Pipeline` of section 10.5. Cross-validation does not
#    catch the leak; draw a timeline of when each number is measured and
#    explain why.
# 4. **Fat tails.** Fit `statsmodels.formula.api.quantreg` at the median
#    (q = 0.5) with the same features. Which coefficients survive when extreme
#    stocks lose their pull?
# 5. **Another clustering algorithm.** Try `sklearn.mixture.GaussianMixture`
#    and choose the number of components by BIC (`.bic(Zs)`). Compare its ARI
#    with sectors to the k-means one.
# 6. **Cluster in PCA space.** Run k-means on the first `N_KEEP` PC scores
#    instead of all z-scores. Does dropping the noise components change the
#    silhouette or the ARI?
# 7. **Bootstrap the agreement.** Resample the stocks with replacement 500 times
#    and recompute the k-means ARI with sectors each time. How wide is the 95%
#    interval?
# 8. **Another market or a wider sample.** Set `MARKET = "jp"` (more SurgeFlow
#    labels reach its largest names, screen step 7 may flag recent stock
#    splits, and its market may be open: check the session dates in section 4)
#    or `"hk"` (watch step 5 remove the renminbi counters and rule 3 drop the
#    dividend-yield columns).
#    Or raise `SCREEN_PAGES` to 5 and see whether the coefficients and clusters
#    hold beyond the largest 300 names (two more requests).

# %% [markdown]
# ## Next steps
#
# - Notebook 01 explains the screen, realtime, hotlist and sector boards field
#   by field; notebook 02 explores the ML clusters and every whale board;
#   notebook 04 covers the factor portfolios and their gates.
# - Run the notebook on another day. The coefficients will move: that is the
#   honest lesson of a cross-sectional, same-day description.
#
# ---
#
# *Research and education only. Nothing here is investment advice or a
# recommendation to buy or sell any security. The regression, PCA and clusters
# describe how one day's stocks differ from each other; they do not forecast
# returns. The endpoint name `realtime` names a current-session board, not a
# live-tick feed, and data cadence varies by market: always check the
# freshness fields. Whale boards reflect disclosure filings that can be weeks or
# months old.*

# %%
print(f"API requests made in this session: {api_calls_used()}")
