# %% [markdown]
# # 04 · Factor portfolios: weekly long-only style books, their exposures and returns
#
# A **style** (also called a factor) is a stock characteristic that many stocks
# share and that tends to move their prices together: company size, value (how
# cheap a stock looks), momentum (how it did recently), profitability,
# investment (how fast a company grows its assets) and liquidity (how easily it
# trades). SurgeFlow publishes one weekly **long-only pure factor portfolio**
# per style, plus a MARKET portfolio. We call each one a **book**. A book only
# buys stocks (no short selling), is fully invested (its weights sum to 1) and
# is rebuilt every week so that its **exposure** is about 1 to its own style
# and about 0 to the other styles.
#
# There is one consequence to learn before anything else. Every long-only,
# fully invested book also has a **market exposure of 1**, by construction. So
# all seven books rise and fall with the market, and their raw returns look
# alike. The style shows up in the **difference**: a style book's weekly return
# minus the MARKET book's return. Both carry the market once, so the market
# cancels, and what is left is about one unit of the style (plus the noise of
# holding different stocks). This notebook reads the publication metadata,
# downloads the books, checks their exposures and holdings, cleans the weekly
# return series, and measures those style-minus-MARKET spreads.
#
# Everything here is **research and education**: a retrospective, in-sample
# measurement, gross of costs. In the API's own words: *"Model candidates, not
# recommendations; no accuracy or performance claim is made."*
#
# **What you will learn**
#
# - What a pure long-only factor book is, and why its market exposure is 1 by
#   construction.
# - How to read the publication metadata first: publications, universe size,
#   hold-out, cost basis, and the freshness block exactly as the API reports it.
# - How to tell an **empty state** (HTTP 200, `data.status` = `"empty"`, with a
#   `reason_code` and a `message`) from an **error** (HTTP 400 or 503), with Hong
#   Kong as the example.
# - How to check a book: its exposure matrix, the API's own checks, and its
#   holdings, whose weights sum to 1.
# - How to turn the `returns` dictionary into one tidy table, handle week
#   statuses (ok, degraded, unavailable, no holdings) and calendar gaps, and
#   count everything you drop.
# - Why raw long-only returns all move together, and how each style appears as
#   **book minus MARKET**: growth, drawdowns, annualised mean and volatility with
#   honest error bars, and correlations.
# - How a long-only spread compares with SurgeFlow's Fama-French 2×3
#   long-short **measurement twin**.
# - How the query parameters work: `factor`, `formation_date`, `weeks`,
#   `holdings` and `measurement`, and what each error code means.
# - PCA both ways: on raw returns (one market component dominates) and on the
#   style-minus-MARKET spreads.
#
# **Endpoints used**
#
# | Method | Path | What it returns |
# |---|---|---|
# | GET | `/api/v1/markets/{market}/factor-portfolios/meta` | Publication metadata: the publications, each model's state, the universe size, the hold-out, the cost basis and its label, the freshness block, caveats and the return basis. No query parameters |
# | GET | `/api/v1/markets/{market}/factor-portfolios` | The seven weekly long-only books for one market: each book's exposures, checks and largest holdings, the weekly return series of every book, status counts, labels, caveats, freshness and (optionally) the Fama-French 2×3 measurement twins. Query parameters below |
#
# | Query parameter | Allowed values | Default | What it does |
# |---|---|---|---|
# | `factor` | `MARKET`, `SIZE`, `VALUE`, `MOMENTUM`, `PROFITABILITY`, `INVESTMENT`, `LIQUIDITY` | all seven | Return one book only |
# | `formation_date` | `YYYY-MM-DD` | the latest | The week whose books you want |
# | `weeks` | 1 to 1000 | 52 | How many weeks of returns to include |
# | `holdings` | 0 to 5000 | 25 | Largest holdings to include per book (0 = none) |
# | `measurement` | `true`, `false` | `true` | Include the Fama-French 2×3 measurement twins |
#
# Markets: `us`, `cn`, `jp`, `hk`. The notebook makes about 8 requests (the
# free plan allows 2,000 a day and 180 a minute): 1 for the metadata, 1 for the
# books, 1 for Hong Kong's empty state, 3 to show the query parameters and up
# to 3 for the four-market comparison. It runs in about a minute.
#
# **The seven books**
#
# | Book | Exposure key | What the style measures |
# |---|---|---|
# | MARKET | `market` | The whole universe: exposure 1 to the market and about 0 to every style. It is the reference for the other six |
# | SIZE | `size` | Company size |
# | VALUE | `value` | How cheap a stock looks against its fundamentals |
# | MOMENTUM | `momentum` | How a stock's price has moved over the past months |
# | PROFITABILITY | `profitability` | How profitable the company is |
# | INVESTMENT | `investment` | How fast the company grows its assets |
# | LIQUIDITY | `liquidity` | How easily the stock trades |
#
# In the textbook versions of these styles, SIZE favours small companies, VALUE
# cheap ones, MOMENTUM recent winners, PROFITABILITY profitable ones and
# INVESTMENT slow growers. The API names the styles but does not document which
# end of each score is positive, so treat those directions as a reading to
# check (Next steps), not as a fact the API states.
#
# **Words used in this notebook**
#
# | Word | Meaning |
# |---|---|
# | book | One of the seven weekly portfolios |
# | long-only | The book only buys stocks: every weight is 0 or more |
# | exposure | How strongly a book leans on a style, in units of the style's score: about 0 is the MARKET book's level, 1 is one unit of tilt. Section 5 checks whether it equals the weighted average of the holdings' scores |
# | formation date | The date that names a week's formation: the first session of the holding week. The holdings are formed at the close of the session before it (`labels.timing`) |
# | `week_start` | The Monday that names a holding week |
# | spread | A style book's weekly return minus the MARKET book's return |
# | measurement twin | A Fama-French 2×3 long-short portfolio for the same style, served as a yardstick for comparison. It is not one of the books |
# | index = 100 | A cumulative return drawn as the value of 100 invested at the start |
# | drawdown | How far a book sits below its previous peak |
# | annualised | A weekly figure scaled to a year: the mean × 52, the volatility × √52 |
# | degraded week | A week in which too much of a book could not be measured cleanly (the API's degraded rule, quoted in section 4.2). It keeps its label and is left out of statistics |

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
# (`sf_get`, `sf_try`, `records`, `to_frame`, `dig`, `show_freshness`, ...) and
# the chart theme. You can run it without reading it.

# %% [helpers]

# %% [markdown]
# ## 2. Parameters
#
# Change `MARKET` and run the notebook again to study another market. `FOCUS`
# picks the book for the holdings chart, the measurement-twin comparison and
# the four-market panel. The other values keep the downloads small and set the
# rules for the statistics.

# %%
MARKET = "us"              # one of "us", "cn", "jp", "hk" ("hk" has no publication yet: you will see its empty state)
FOCUS = "MOMENTUM"         # "MARKET", "SIZE", "VALUE", "MOMENTUM", "PROFITABILITY", "INVESTMENT" or "LIQUIDITY"
WEEKS = 156                # weeks of returns to request: 1-1000 (API default 52). 156 weeks is about 3 years
HOLDINGS = 25              # largest holdings per book: 0-5000 (API default 25; 0 = no holdings)
MEASUREMENT = True         # also fetch the Fama-French 2x3 measurement twins (API default true)
TWIN = "s3b_ff_2x3_ew"     # twin for section 4.12: "s3b_ff_2x3_ew" (equal weight) or "s3b_ff_2x3_rp126"
COMPARE_MARKETS = True     # section 6 fetches the other markets (up to 3 more requests); False skips it
COVERAGE_MIN = 0.9         # a book enters the growth, drawdown, correlation and PCA charts only when at least
                           # 90% of its served weeks are "ok"; the others are listed, never silently dropped
MIN_WEEKS = 26             # a series needs at least 26 clean weeks (half a year) for statistics
WEEKS_PER_YEAR = 52        # annualising: mean x 52, volatility x sqrt(52)
MAX_ABS_WEEKLY = 0.5       # a book return beyond ±50% in one week is treated as a data error

FACTORS = ["MARKET", "SIZE", "VALUE", "MOMENTUM", "PROFITABILITY", "INVESTMENT", "LIQUIDITY"]  # contract order

assert MARKET in MARKETS, f"MARKET must be one of {MARKETS}"
FOCUS = FOCUS.upper()
assert FOCUS in FACTORS, f"FOCUS must be one of {FACTORS}"
assert 1 <= WEEKS <= 1000, "WEEKS must be between 1 and 1000."
assert 0 <= HOLDINGS <= 5000, "HOLDINGS must be between 0 and 5000."
assert TWIN in ("s3b_ff_2x3_ew", "s3b_ff_2x3_rp126"), "TWIN must be 's3b_ff_2x3_ew' or 's3b_ff_2x3_rp126'."
print(f"Studying {MARKET_NAMES[MARKET]} ({MARKET}); focus book {FOCUS}; "
      f"{WEEKS} weeks of returns and up to {HOLDINGS} holdings per book.")

# %% [markdown]
# A few small utilities keep the later cells short. They are plain code, so read
# them once:
#
# - `STYLES` are the exposure keys (`market`, `size`, ...), in the same order as
#   `FACTORS`, so the book on row *i* of a matrix has its own style in column *i*.
# - `FACTOR_COLORS` gives each book a fixed colour: MARKET is drawn in ink as
#   the reference line, and the six style books take the theme's categorical
#   colours in contract order. A book keeps its colour even when another book is
#   missing. Charts that name each book on an axis or in a panel title use one
#   neutral colour instead.
# - `CHECKS` lists the API's five per-book checks with this notebook's reading
#   of each name.
# - `state_of` and `show_state` read `data.status`, `data.reason_code` and
#   `data.message`: the empty state is data, not an error.
# - `freshness_frame` and `styled_freshness` show a freshness block exactly as
#   the API sends it. The only formatting is that a `state` of `behind` is
#   printed in bold.
# - `quote` prints one of the API's labels verbatim, with the field it came
#   from, so you read SurgeFlow's wording instead of a paraphrase.
# - `growth_index` compounds weekly returns into the value of 100;
#   `annual_stats` annualises a weekly series and adds a 95% interval with
#   autocorrelation-robust (HAC) standard errors; `pca_fit` runs a standardised
#   PCA inside a scikit-learn `Pipeline`.
# - `chart_title` wraps a long chart title and subtitle and returns the top
#   margin they need (Plotly never wraps a title). `add_end_labels` writes each
#   line's name at its right end without overlaps. `corr_trace` draws the lower
#   half of a correlation matrix on the diverging scale.
#
# The chart subtitles need Plotly 5.23 or newer (Colab already has it). The cell
# checks the version first, so an older local install stops here with a
# one-line fix instead of failing in the middle of the notebook.

# %%
import re
import textwrap

import plotly
import statsmodels.api as sm
from plotly.subplots import make_subplots
from sklearn.decomposition import PCA
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

if tuple(int(p) for p in re.findall(r"\d+", plotly.__version__)[:2]) < (5, 23):
    raise ImportError(f"The charts here need plotly 5.23 or newer (title subtitles); you have {plotly.__version__}. "
                      "Run  pip install -U 'plotly>=5.23'  and restart the kernel.")

STYLES = [f.lower() for f in FACTORS]                    # exposure keys, same order as FACTORS
STYLE_BOOKS = FACTORS[1:]                                # the six style books; MARKET is the reference
FACTOR_COLORS = {"MARKET": INK, **dict(zip(STYLE_BOOKS, SERIES))}   # colour follows the book, never its rank
CHECKS = {   # data.portfolios[].checks: the API's names, and this notebook's reading of them
    "sum_ok": "weights sum to 1",
    "own_ok": "own-style exposure is about 1",
    "others_ok": "other-style exposures are about 0",
    "bounds_ok": "every weight is inside its bounds",
    "matches_published": "served exposures match the published ones",
}
BOTTOM_LEGEND = dict(orientation="h", x=0, xanchor="left", y=0.01, yref="container", yanchor="bottom")


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


def plural(n, word: str, many: str = None) -> str:
    """plural(1, 'week') -> '1 week'; plural(3, 'week') -> '3 weeks'."""
    n = int(n)
    return f"{n:,} {word if n == 1 else (many or word + 's')}"


def and_list(items) -> str:
    """['SIZE', 'VALUE', 'MOMENTUM'] -> 'SIZE, VALUE and MOMENTUM'."""
    items = [str(i) for i in items]
    if not items:
        return "none"
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def note(text: str) -> None:
    """A friendly one-line note in place of a chart or table (empty is normal)."""
    display(Markdown(f"> {text}"))


def quote(field: str, text) -> None:
    """Show one of the API's labels verbatim, with the field it came from."""
    display(Markdown(f"**`{field}`**\n\n> {text if text else '(not sent in this response)'}"))


def state_of(payload: dict) -> tuple:
    """(status, reason_code, message) from payload.data. 'available' or 'empty'; empty is HTTP 200, not an error."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return data.get("status"), data.get("reason_code"), data.get("message")


def show_state(payload: dict, label: str) -> None:
    """One line for an available response; the reason code and the API's own message for an empty one."""
    status, code, message = state_of(payload)
    if status == "available":
        display(Markdown(f"**{label}:** `data.status` = `available`"))
    else:
        display(Markdown(f"**{label}:** `data.status` = `{status}` · `reason_code` = `{code}`\n\n> {message}"))


def freshness_frame(block: dict, label: str) -> pd.DataFrame:
    """A freshness block as a one-row table, values exactly as the API sent them."""
    return pd.DataFrame([{"source": label, **(block or {})}])


def styled_freshness(frame: pd.DataFrame):
    """Print a 'behind' state in bold. Nothing else is changed or added."""
    columns = [c for c in frame.columns if c == "state" or c.endswith("freshness.state")]
    mark = lambda value: "font-weight: 700; color: #b3261e" if value == "behind" else ""
    return frame.style.map(mark, subset=columns).hide(axis="index") if columns else frame.style.hide(axis="index")


def newey_west_lags(n: int) -> int:
    """The usual rule of thumb for how many lags a HAC (Newey-West) standard error should allow."""
    return int(np.floor(4 * (n / 100) ** (2 / 9)))


def annual_stats(r: pd.Series) -> dict:
    """Weekly returns (fractions) -> weeks used, years, annualised mean and volatility, a 95% interval for the
    annualised mean and a t-statistic, both from HAC standard errors (they allow for autocorrelation)."""
    r = r.dropna()
    n = len(r)
    out = {"weeks": n, "years": n / WEEKS_PER_YEAR}
    if n < 3:
        return out | {k: np.nan for k in ("mean / year", "vol / year", "95% low", "95% high", "t (HAC)")}
    fit = sm.OLS(r.to_numpy(), np.ones(n)).fit(cov_type="HAC", cov_kwds={"maxlags": newey_west_lags(n)})
    mean, se = float(fit.params[0]), float(fit.bse[0])
    return out | {"mean / year": mean * WEEKS_PER_YEAR, "vol / year": r.std(ddof=1) * np.sqrt(WEEKS_PER_YEAR),
                  "95% low": (mean - 1.96 * se) * WEEKS_PER_YEAR, "95% high": (mean + 1.96 * se) * WEEKS_PER_YEAR,
                  "t (HAC)": mean / se if se > 0 else np.nan}


def growth_index(weekly: pd.DataFrame) -> pd.DataFrame:
    """Weekly returns (rows = week_start) -> the value of 100 at the start of each week.

    The first row is 100 at the start of the first week; the value after week t is placed at the start of
    week t + 1. A missing week stays missing (a break in the line) and adds nothing to the product."""
    level = 100 * (1 + weekly).cumprod()
    level.index = level.index + pd.Timedelta(weeks=1)
    start = pd.DataFrame(100.0, index=weekly.index[:1], columns=weekly.columns)
    return pd.concat([start, level])


def pca_fit(frame: pd.DataFrame) -> tuple:
    """Standardised PCA in a Pipeline. Returns explained-variance shares, loadings and scores.
    A component's sign is arbitrary, so each is flipped to make the sum of its loadings positive."""
    pipe = Pipeline([("scale", StandardScaler()), ("pca", PCA(random_state=0))]).fit(frame)
    pca = pipe.named_steps["pca"]
    names = [f"PC{i + 1}" for i in range(pca.n_components_)]
    flip = np.where(pca.components_.sum(axis=1) < 0, -1.0, 1.0)
    loadings = pd.DataFrame((pca.components_ * flip[:, None]).T, index=frame.columns, columns=names)
    scores = pd.DataFrame(pipe.transform(frame) * flip, index=frame.index, columns=names)
    return pd.Series(pca.explained_variance_ratio_, index=names), loadings, scores


def mean_pair(corr: pd.DataFrame) -> float:
    """Average correlation over the distinct pairs (the lower triangle, without the diagonal)."""
    values = corr.to_numpy()
    return float(values[np.tril_indices_from(values, k=-1)].mean())


def corr_trace(corr: pd.DataFrame, showscale: bool = True) -> go.Heatmap:
    """The lower half of a correlation matrix (no diagonal) on the diverging scale, centred at 0, from -1 to 1."""
    names = list(corr.columns)
    z = corr.to_numpy().copy()
    z[np.triu_indices_from(z)] = np.nan
    z = z[1:, :-1]
    text = [["" if np.isnan(v) else signed(v) for v in row] for row in z]
    return go.Heatmap(z=z, x=names[:-1], y=names[1:], text=text, texttemplate="%{text}", textfont=dict(size=12),
                      colorscale=DIVERGING, zmin=-1, zmax=1, zmid=0, xgap=2, ygap=2, hoverongaps=False,
                      hovertemplate="%{y} vs %{x}: %{z:+.2f}<extra></extra>", showscale=showscale,
                      colorbar=dict(title=dict(text="Correlation"), tickvals=[-1, -0.5, 0, 0.5, 1], len=0.85,
                                    thickness=14))


def grid_shape(n: int, max_cols: int = 3) -> tuple:
    """Rows and columns for a grid of n small panels."""
    cols = max(1, min(max_cols, n))
    return int(np.ceil(n / cols)), cols


def hide_unused_panels(fig, n_panels: int, rows: int, cols: int) -> None:
    """A grid of 7 panels has 9 cells: hide the axes of the cells that hold no panel."""
    for k in range(n_panels, rows * cols):
        fig.update_xaxes(visible=False, row=k // cols + 1, col=k % cols + 1)
        fig.update_yaxes(visible=False, row=k // cols + 1, col=k % cols + 1)


def chart_title(title: str, subtitle: str = "", extra_top: int = 0, width: int = 80) -> tuple:
    """Wrap a long title (about `width` characters a line) and subtitle (about 1.45 × `width`, broken at its
    ' · ' separators where possible; '<br>' still forces a new line), pin them to the top of the figure, and
    return Plotly's title dict plus the top margin in pixels that keeps them clear of the plot. `extra_top`
    reserves room for anything else above the plot area, such as panel titles."""
    def pack(line: str, limit: int) -> list:
        lines = []
        for piece in line.split(" · "):
            if lines and len(lines[-1]) + 3 + len(piece) <= limit:
                lines[-1] += " · " + piece
            else:
                lines += textwrap.wrap(piece, limit, break_on_hyphens=False)
        return lines

    head = textwrap.wrap(title, width, break_on_hyphens=False)
    sub = [line for part in subtitle.split("<br>") for line in pack(part, int(width * 1.45))] if subtitle else []
    top = 40 + 23 * len(head) + 18 * len(sub) + extra_top
    return dict(text="<br>".join(head), subtitle=dict(text="<br>".join(sub)), y=1, yref="container",
                yanchor="top", pad=dict(t=12 + 22 * (len(head) > 1))), top


def spread_labels(values, min_gap: float) -> np.ndarray:
    """Move label positions apart until neighbours are at least `min_gap` apart, keeping their order."""
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
    """Label each line at its right end, at least `min_px` pixels apart, with a thin leader in the line's colour.
    `ends` has one row per line: x, y (the line's last point), text and color. The text stays in ink."""
    gap = min_px * (y_range[1] - y_range[0]) / plot_px
    for (_, end), y_label in zip(ends.iterrows(), spread_labels(ends["y"].to_numpy(dtype=float), gap)):
        fig.add_annotation(x=end["x"], y=end["y"], ax=26, ay=y_label, axref="pixel", ayref="y",
                           text=end["text"], showarrow=True, arrowhead=0, arrowwidth=1.2,
                           arrowcolor=end["color"], standoff=2, xanchor="left", yanchor="middle",
                           font=dict(size=12, color=INK_2))


def date_axis(index) -> dict:
    """An x-axis for weekly dates: the data's own range with a few days of padding, dates in the hover."""
    lo, hi = pd.Timestamp(index.min()), pd.Timestamp(index.max())
    return dict(range=[lo - pd.Timedelta(days=5), hi + pd.Timedelta(days=5)], hoverformat="%b %d, %Y",
                title="Start of week")


def padded_range(values, pad_share: float = 0.06) -> list:
    """A y-range around the data with a little room above and below."""
    values = np.asarray(values, dtype=float)
    lo, hi = float(np.nanmin(values)), float(np.nanmax(values))
    pad = (hi - lo) * pad_share + 0.5
    return [lo - pad, hi + pad]

# %% [markdown]
# ## 3. Publication metadata: `/api/v1/markets/{market}/factor-portfolios/meta`
#
# **What it is for.** Read this small response before you download any
# returns. It tells you whether the market has a publication at all, which
# formation weeks the publication covers, how many stocks are in the universe,
# whether part of the history is a hold-out, what the returns include and what
# they leave out (the cost basis), and how current the latest formation is.
#
# **State lives at `data.status`.** It is `"available"` or `"empty"`. An empty
# state still answers HTTP 200 with `"ok": true`, plus a `data.reason_code`
# and a `data.message` that you should show as they are. It is not an error.

# %%
meta = sf_get(f"/api/v1/markets/{MARKET}/factor-portfolios/meta")
show_freshness(meta, "Metadata response:")
mdata = meta["data"]
META_AVAILABLE = mdata["status"] == "available"
print(f"schema_version: {meta['schema_version']}")
show_state(meta, f"{MARKET_NAMES[MARKET]} metadata")

pubs_raw = to_frame(meta, "factor_portfolios_meta")       # data.publications, one row per publication
if pubs_raw.empty:
    note(f"No publication is listed for {MARKET_NAMES[MARKET]}. The rest of the metadata section has nothing "
         "to show; the books section below shows the same empty state.")
else:
    display(pubs_raw.head())

# %% [markdown]
# ### 3.1 Cleaning the publication list
#
# The publication rows are small, but the same cleaning habits apply. We keep
# the documented columns (a missing one raises a `KeyError`, because that would
# be a contract change), parse `published_at` as a UTC timestamp and the
# formation dates as plain calendar dates (they are exchange sessions, with no
# time of day), turn the `kinds` list into text, and de-duplicate on the
# natural key, `publication_id`.

# %%
PUB_COLS = ["publication_id", "phase", "kinds", "published_at", "first_formation", "last_formation",
            "data_through_session"]
pubs = pick(pubs_raw, PUB_COLS)
pubs["published_at"] = pd.to_datetime(pubs["published_at"], utc=True, errors="coerce")
for col in ["first_formation", "last_formation", "data_through_session"]:
    pubs[col] = pd.to_datetime(pubs[col], format="%Y-%m-%d", errors="coerce")
pubs["kinds"] = pubs["kinds"].map(lambda k: ", ".join(k) if isinstance(k, list) else k)
before = len(pubs)
pubs = pubs.drop_duplicates("publication_id", keep="last").sort_values("published_at").reset_index(drop=True)
print(f"{plural(len(pubs), 'publication')} after de-duplication ({before - len(pubs)} duplicate rows removed); "
      f"unparseable dates: {int(pubs[['published_at', 'first_formation', 'last_formation']].isna().sum().sum())}.")
if not pubs.empty:
    display(pubs.style.format({"published_at": "{:%Y-%m-%d %H:%M} UTC", "first_formation": "{:%Y-%m-%d}",
                               "last_formation": "{:%Y-%m-%d}", "data_through_session": "{:%Y-%m-%d}"},
                              na_rep="–").hide(axis="index"))

# %% [markdown]
# ### 3.2 The fact sheet, the labels and the freshness block
#
# Here a table beats a chart: the metadata is a handful of facts, not a series.
# The cell builds a short fact sheet (model states, universe, hold-out, cost
# basis), then quotes the API's own labels verbatim, then shows the freshness
# block.
#
# Publications are weekly, and the API reports how many weeks the latest
# formation is behind the current week, together with a state (it counts one
# week behind as `current`).

# %%
if not META_AVAILABLE:
    note(f"{MARKET_NAMES[MARKET]}: `{mdata.get('reason_code')}`. {mdata.get('message')}")
else:
    universe = mdata["universe"]
    hold = dig(mdata, "holdout", "portfolios", default={}) or {}
    facts = pd.DataFrame([
        ("Model states (portfolios / pick / product)",
         " / ".join(str(dig(mdata, "models", m, "state")) for m in ("portfolios", "pick", "product"))),
        ("Publications", mdata["n_publications"]),
        ("Universe: stocks in / evaluated",
         f"{universe['n_in_universe']:,} of {universe['n_evaluated']:,} "
         f"({universe['n_in_universe'] / universe['n_evaluated']:.0%})"),
        ("Universe rule and state", f"{universe['rule']} · {universe['measured_state']}"),
        ("Hold-out start", hold.get("start") or "none set (see the rule below)"),
        ("Cost basis", ", ".join(mdata["cost_basis"])),
    ], columns=["item", "value"])
    display(facts.style.hide(axis="index"))

    quote("meta: data.cost_label", mdata["cost_label"])
    quote("meta: data.return_basis.returns_label", dig(mdata, "return_basis", "returns_label"))
    quote("meta: data.holdout_label", mdata.get("holdout_label"))
    quote("meta: data.holdout.portfolios.rule", hold.get("rule"))
    quote("meta: data.labels.universe", dig(mdata, "labels", "universe"))
    quote("meta: data.survivorship.estimate_label", dig(mdata, "survivorship", "estimate_label"))

    fresh = {k: v for k, v in (mdata.get("freshness") or {}).items() if v}   # one block per published model
    if fresh:
        display(styled_freshness(pd.concat([freshness_frame(block, f"meta · freshness.{model}")
                                            for model, block in fresh.items()], ignore_index=True)))
    else:
        note("The metadata carries no freshness block for this market.")

# %% [markdown]
# **How to read this.** The fact sheet says which models are published (only
# the `portfolios` model is used in this notebook), how many stocks passed the
# universe rule out of those evaluated, and whether a hold-out start is set.
# The quoted labels are SurgeFlow's own wording: the cost label tells you what
# the returns leave out, the returns label says what one weekly number
# measures, and the survivorship label gives a first-order estimate of how
# much the history may be flattered by companies that survived. The freshness
# table repeats the API's block unchanged: `state` and `weeks_behind` are the
# fields to read.
#
# **Caveats.**
#
# - The metadata describes the latest publication. How current it is, is what
#   the freshness block reports.
# - The return basis can differ between markets (for example a price return in
#   one market and a total return in another). Compare markets only after you
#   have read each one's label.
# - "Gross of costs" means no trading cost, spread or tax is deducted. Any real
#   portfolio would earn less than these measurements.

# %% [markdown]
# ## 4. The books: `/api/v1/markets/{market}/factor-portfolios`
#
# **What it is for.** This is the main response: for each of the seven books,
# its latest exposures, the API's checks, its largest holdings, and its weekly
# return series. We ask for `WEEKS` weeks of returns, `HOLDINGS` holdings per
# book and, with `MEASUREMENT`, the Fama-French 2×3 measurement twins. Ask only
# for what you need: the full history with every holding is a large download.
#
# **Errors versus empty.** A market without a publication answers HTTP 200 with
# `data.status` = `"empty"` (section 4.3). A bad parameter answers HTTP 400
# (`INVALID_FACTOR`, `INVALID_DATE` or `INVALID_MARKET`), and HTTP 503 means
# the data could not be read. `sf_get` retries a 503 a few times, then raises
# `SurgeFlowError`; `sf_try` prints a note and returns `None` instead (section
# 5 shows both kinds of answer).
#
# ### 4.1 The call, the publication and the freshness block

# %%
fp = sf_get(f"/api/v1/markets/{MARKET}/factor-portfolios", weeks=WEEKS, holdings=HOLDINGS,
            measurement=str(MEASUREMENT).lower())
show_freshness(fp, "Factor-portfolios response:")
data = fp["data"]
AVAILABLE = data["status"] == "available"
print(f"schema_version: {fp['schema_version']}")
show_state(fp, MARKET_NAMES[MARKET])
if AVAILABLE:
    publication = data["publication"]
    display(pd.DataFrame([{k: publication[k] for k in ("publication_id", "phase", "published_at",
                                                          "first_formation", "last_formation",
                                                          "data_through_session")}]).style.hide(axis="index"))
    display(styled_freshness(freshness_frame(data["freshness"], "data.freshness")))
    window = {k: data[k] for k in ("formation_date", "week_start", "week_state", "return_state", "open_week",
                                   "n_weeks", "in_holdout", "holdout_start")}
    display(pd.DataFrame([window]).style.hide(axis="index"))

# %% [markdown]
# **How to read this.** The first table names the publication these books come
# from. The second is the response's own freshness block, unchanged. The third
# describes the latest formation week: `formation_date` and `week_start` name
# it, `week_state` and `return_state` say whether its return is realised, and
# `open_week` is filled only when the coming week's candidates are already
# formed. `n_weeks` counts every week in the publication's history, while the
# return series below holds only the `WEEKS` you asked for.

# %% [markdown]
# ### 4.2 Before any number: the API's labels and caveats
#
# Every served history comes with its own fine print. We print it verbatim,
# before looking at a single return: what a book is (`labels.product`), what
# one weekly return measures (`return_basis.returns_label`), what is left out
# (the metadata's `cost_label`), what the numbers are not (`labels.candidates`),
# when the books are formed, how degraded weeks and calendar gaps are handled,
# and the market's served caveats with the survivorship estimate.

# %%
if not AVAILABLE:
    note(f"No labels or caveats to show: {MARKET_NAMES[MARKET]} has no publication "
         f"(`{data.get('reason_code')}`).")
else:
    labels = data["labels"]
    RETURNS_LABEL = data["return_basis"]["returns_label"]
    COST_LABEL = mdata["cost_label"] if META_AVAILABLE else labels["cost"]
    quote("data.labels.product", labels["product"])
    quote("data.return_basis.returns_label", RETURNS_LABEL)
    quote("meta: data.cost_label", COST_LABEL)
    quote("data.labels.candidates", labels["candidates"])
    quote("data.labels.timing", labels["timing"])
    quote("data.labels.holdout", labels["holdout"])
    quote("data.degraded_rule.label", data["degraded_rule"]["label"])
    quote("data.calendar_grid.label", data["calendar_grid"]["label"])

    caveats = data["served_caveats"]
    items = caveats.get("items") or []
    lines = [f"- **{item['key']}** (`{item['state']}`): {item['text']}" for item in items]
    display(Markdown(f"**`data.served_caveats`** ({plural(len(items), 'item')}): {caveats.get('label') or ''}"
                     "\n\n" + ("\n".join(lines) if lines else "> No caveat items in this response.")))
    surv = data["survivorship"]
    display(Markdown(f"**`data.survivorship`**: state `{surv['state']}`, bound `{surv.get('bound')}`, "
                     f"`points_per_year` = {surv.get('points_per_year')}\n\n> {surv['estimate_label']}"))

# %% [markdown]
# **How to read this.** `labels.product` is the definition this whole notebook
# builds on: exposure 1 to the book's own style, 0 to the other styles, and
# market exposure 1 by construction. The returns label and the cost label say
# exactly what a weekly number includes, so you never have to guess whether
# dividends or costs are in it. The served caveats are specific to this
# market's history (data vintages, coverage, which books could not always be
# formed); read them before you trust any one week. The survivorship estimate
# is a lower bound on how much an equal-weight universe is flattered per year.
#
# **Caveats.**
#
# - These labels are part of the data. If a label changes, the meaning of the
#   numbers changed with it: re-read them whenever the `publication_id` does.
# - The survivorship estimate is for an equal-weight universe, not for any one
#   book: a small-company book can be affected more than the average.

# %% [markdown]
# ### 4.3 The empty state: Hong Kong
#
# Hong Kong had no publication when this notebook was written, which makes it
# the clean example of an empty state. The request is the same; the answer is
# HTTP 200 with `"ok": true`, `data.status` = `"empty"`, a machine-readable
# `data.reason_code` and a sentence for people in `data.message`. Your code
# should show the message and carry on, not raise. (If Hong Kong has published
# by the time you run this, the cell says so.)

# %%
EMPTY_DEMO = "hk"
hk = fp if MARKET == EMPTY_DEMO else sf_get(f"/api/v1/markets/{EMPTY_DEMO}/factor-portfolios", weeks=1,
                                            holdings=0, measurement="false")
show_freshness(hk, "Hong Kong response:")
hk_status, hk_code, hk_message = state_of(hk)
print(f"ok: {hk['ok']} | data.status: {hk_status!r} | data.reason_code: {hk_code!r}")
if hk_status == "empty":
    display(Markdown(f"> **{MARKET_NAMES[EMPTY_DEMO]}:** {hk_message}"))
else:
    print(f"{MARKET_NAMES[EMPTY_DEMO]} now reports data.status = {hk_status!r}; section 6 includes its books.")
PAYLOADS = {MARKET: fp}                        # reused by the four-market comparison in section 6
if hk_status != "available":                   # (an available Hong Kong is fetched again there, with its weeks)
    PAYLOADS[EMPTY_DEMO] = hk

# %% [markdown]
# Two `reason_code` values are worth knowing: `no_publication_for_market` (the
# market has no publication at all, as here) and `formation_date_not_published`
# (you asked for a `formation_date` that has no published books; section 5
# shows it). In both cases print `data.message` and move on.

# %% [markdown]
# ### 4.4 The books: raw preview and cleaning
#
# `data.portfolios` holds one record per book. `to_frame` flattens the nested
# objects into dotted columns: `exposures.size`, `checks.sum_ok`, and so on. A
# book that could not be formed this week (for example because its exposure
# targets could not all be met) is still listed, with `status` = `"infeasible"`,
# the constraint that failed in `infeasible_constraint`, and no exposures or
# holdings. We keep it in the table, so the gap is visible instead of silently
# missing.

# %%
books_raw = to_frame(fp, "factor_portfolios")
if books_raw.empty:
    note(f"No books in this response: {MARKET_NAMES[MARKET]} is `{data['status']}`.")
else:
    display(books_raw.drop(columns=["holdings"], errors="ignore").head(7))

# %% [markdown]
# **Cleaning.**
#
# 1. Keep the documented columns. The core ones are always there; the
#    exposure, check and holding fields exist only on a formed book, so they
#    may be absent when no book is formed, but a formed book without them raises.
# 2. Coerce the numbers with `pd.to_numeric(errors="coerce")`. `week_return` is
#    a **fraction** (0.01 = 1%).
# 3. De-duplicate on the natural key, `factor`, and sort the books in the
#    contract order (MARKET first).
# 4. Count what is missing and say why: a book that was not formed has no
#    exposures, and that is the API telling us something, not a hole to fill.

# %%
CORE = ["factor", "status", "state", "n_holdings", "universe_n", "week_return"]
FORMED_FIELDS = (["own_exposure", "max_abs_other_style", "sum_weight", "turnover_one_way", "holdings_truncated",
                  "infeasible_constraint"] + [f"exposures.{s}" for s in STYLES] + [f"checks.{c}" for c in CHECKS])
books = pick(books_raw, CORE)
if not books_raw.empty and books_raw["status"].eq("available").any():
    missing = [c for c in FORMED_FIELDS if c not in books_raw.columns]
    if missing:
        raise KeyError(f"Formed books are missing documented fields: {missing}")
books = books.join(books_raw.reindex(columns=FORMED_FIELDS))      # absent only when no book is formed
NUMERIC = (["n_holdings", "universe_n", "week_return", "own_exposure", "max_abs_other_style", "sum_weight",
            "turnover_one_way"] + [f"exposures.{s}" for s in STYLES])
for col in NUMERIC:
    books[col] = pd.to_numeric(books[col], errors="coerce")
before = len(books)
books = books.drop_duplicates("factor", keep="last")
rank = {f: i for i, f in enumerate(FACTORS)}
books = books.sort_values("factor", key=lambda s: s.map(rank).fillna(len(FACTORS))).reset_index(drop=True)
books["held_share"] = books["n_holdings"] / books["universe_n"]

FORMED = books.loc[books["status"].eq("available"), "factor"].tolist()
NOT_FORMED = books.loc[~books["status"].eq("available"), ["factor", "status", "infeasible_constraint"]]
print(f"{plural(len(books), 'book')} ({before - len(books)} duplicates removed); formed: {and_list(FORMED)}.")
for _, row in NOT_FORMED.iterrows():
    print(f"  {row['factor']}: status {row['status']!r}, failed constraint {row['infeasible_constraint']!r} "
          "- no exposures, holdings or return this week.")
if not books.empty:
    display(books[["factor", "status", "n_holdings", "universe_n", "held_share", "week_return", "own_exposure",
                   "max_abs_other_style", "sum_weight", "turnover_one_way"]].style.format(
        {"n_holdings": "{:,.0f}", "universe_n": "{:,.0f}", "held_share": "{:.1%}", "week_return": "{:+.2%}",
         "own_exposure": "{:.4f}", "max_abs_other_style": "{:.2e}", "sum_weight": "{:.4f}",
         "turnover_one_way": "{:.1%}"}, na_rep="–").hide(axis="index"))

# %% [markdown]
# **How to read this.** Each row is one book in its latest formation week.
# `n_holdings` is how many stocks it holds out of `universe_n`, and
# `held_share` is that ratio. `week_return` is the book's return in that week
# (a fraction, shown in %). `own_exposure` should be about 1 and
# `max_abs_other_style` (the largest absolute exposure to any other style)
# about 0. `sum_weight` should be 1: a long-only book is fully invested.
# `turnover_one_way` is the share of the book that changed hands at the latest
# rebalance (a dash where the API reports none).

# %% [markdown]
# ### 4.5 Chart: the exposure matrix, and the API's checks
#
# The matrix below has one row per book and one column per style, in the same
# order, so each book's own style sits on the **diagonal** (outlined). Read it
# against `labels.product`: the diagonal should be about 1, every other style
# cell about 0, and the whole `market` column exactly 1, because a long-only
# book whose weights sum to 1 always carries the market once. The colours use
# the diverging scale: blue is positive, red is negative, grey is about 0.

# %%
if not FORMED:
    note("No formed book in this response, so there is no exposure matrix to draw.")
else:
    shown = books["factor"].tolist()
    exposure = books.set_index("factor")[[f"exposures.{s}" for s in STYLES]]
    exposure.columns = STYLES
    z = exposure.to_numpy(dtype=float)
    text = [["" if np.isnan(v) else signed(v) for v in row] for row in z]
    fig = go.Figure(go.Heatmap(
        z=z, x=[s.capitalize() for s in STYLES], y=shown, text=text, texttemplate="%{text}",
        textfont=dict(size=12), colorscale=DIVERGING, zmin=-1, zmax=1, zmid=0, xgap=2, ygap=2,
        hoverongaps=False, hovertemplate="%{y} book · exposure to %{x}: %{z:+.4f}<extra></extra>",
        colorbar=dict(title=dict(text="Exposure"), tickvals=[-1, -0.5, 0, 0.5, 1], len=0.85, thickness=14)))
    for i, book in enumerate(shown):
        if book in FORMED and book in FACTORS:             # outline each formed book's own style
            j = FACTORS.index(book)
            fig.add_shape(type="rect", x0=j - 0.5, x1=j + 0.5, y0=i - 0.5, y1=i + 0.5,
                          line=dict(color=INK, width=2))
        elif book not in FORMED:                           # a book that was not formed: say so across its row
            why = books.loc[books["factor"].eq(book), "infeasible_constraint"].iloc[0]
            fig.add_annotation(x=(len(STYLES) - 1) / 2, y=i, showarrow=False, font=dict(size=12, color=MUTED),
                               text="not formed this week"
                               + (f" (failed constraint: {why})" if isinstance(why, str) else ""))
    formed = books[books["factor"].isin(FORMED)]
    passed = formed["checks.own_ok"].eq(True) & formed["checks.others_ok"].eq(True)
    market_one = bool((formed["exposures.market"] - 1).abs().max() < 0.01)
    title = (f"{int(passed.sum())} of {len(formed)} formed books pass the API's own-style and other-style checks"
             + ("; every one is 1 on the market" if market_one else ""))
    missing_note = (f" · not formed this week: {and_list(NOT_FORMED['factor'])}" if len(NOT_FORMED) else "")
    heading, top = chart_title(title, "Exposure of each book (row) to each style (column) · outlined: the book's "
                                      "own style · market column = 1 by construction (weights sum to 1) · "
                                      f"blue = positive, red = negative, grey ≈ 0{missing_note}")
    fig.update_layout(title=heading, height=top + 70 + 52 * len(shown), margin=dict(t=top, l=120, r=40, b=70),
                      xaxis=dict(side="bottom", showgrid=False, ticks="", title="Style"),
                      yaxis=dict(autorange="reversed", showgrid=False, ticks="", title="Book"))
    fig.show()

    check_table = books[["factor", "status"] + [f"checks.{c}" for c in CHECKS]
                        + ["exposures.market", "own_exposure", "max_abs_other_style", "sum_weight"]].copy()
    for c in CHECKS:
        check_table[f"checks.{c}"] = check_table[f"checks.{c}"].map({True: "✓", False: "✗"}).fillna("–")
    display(check_table.style.format({"exposures.market": "{:.4f}", "own_exposure": "{:.4f}",
                                      "max_abs_other_style": "{:.2e}", "sum_weight": "{:.4f}"},
                                     na_rep="–").hide(axis="index"))
    display(Markdown("Check names, as this notebook reads them: "
                     + "; ".join(f"`{k}` = {v}" for k, v in CHECKS.items()) + "."))

# %% [markdown]
# **How to read this.** Follow the outlined diagonal: each book is close to 1
# on its own style. Everything else in its row is grey, close to 0, except the
# `Market` column, which is 1 for every book. That last column is the reason the
# books' raw returns move together (section 4.8). The table below the chart is
# the table twin: ✓ means the API's check passed, ✗ that it failed, and – that
# the book was not formed.
#
# **Caveats.**
#
# - The exposures describe the latest formation week only. Each week's book is
#   built again from that week's scores.
# - "About 0" is not exactly 0, and the API states its own tolerances through
#   the checks. A book can pass its checks and still carry small tilts.
# - An exposure is a model quantity, built from style scores. It says what a
#   book leans on, not what it will earn.

# %% [markdown]
# ### 4.6 Chart: what the books hold
#
# Each formed book lists its `HOLDINGS` largest positions: `ticker`, `sector`,
# `weight` (a fraction of the book) and the holding's own style scores in
# `exposures`. The list is a preview: `holdings_truncated` is true when the
# book holds more stocks than were sent. The book's full weights sum to 1
# (`sum_weight`); section 5 downloads one complete book, so you can check that
# sum yourself.
#
# The bar chart shows the `FOCUS` book. Each bar is one holding's weight, and
# its colour is that holding's score on the book's own style (blue = a positive
# score, red = a negative one). The heatmap underneath shows, for every book,
# how much of its weight its listed holdings put in each sector.

# %%
hold_rows = [{"factor": b["factor"], **h} for b in records(fp, "factor_portfolios") for h in (b.get("holdings") or [])]
holds_raw = pd.json_normalize(hold_rows) if hold_rows else pd.DataFrame()
if holds_raw.empty:
    holds = pd.DataFrame(columns=["factor", "ticker", "sector", "weight"])
    note("No holdings in this response (HOLDINGS = 0, or no book was formed).")
else:
    display(holds_raw.head())
    holds = pick(holds_raw, ["factor", "ticker", "sector", "weight"]).join(holds_raw.filter(like="exposures."))
    holds["weight"] = pd.to_numeric(holds["weight"], errors="coerce")
    no_sector = int(holds["sector"].isna().sum())
    holds["sector"] = holds["sector"].fillna("Unknown")
    before = len(holds)
    holds = holds.drop_duplicates(["factor", "ticker"], keep="last")
    print(f"{len(holds):,} holdings rows ({before - len(holds)} duplicates removed); "
          f"{no_sector} without a sector, labelled 'Unknown'; {int(holds['weight'].isna().sum())} without a weight.")
    listed = holds.groupby("factor").agg(listed=("ticker", "size"), listed_weight=("weight", "sum"),
                                         largest=("weight", "max"))
    summary = books.set_index("factor")[["n_holdings", "sum_weight", "holdings_truncated"]].join(listed)
    display(summary.reset_index().style.format({"n_holdings": "{:,.0f}", "sum_weight": "{:.4f}",
                                                "listed": "{:,.0f}", "listed_weight": "{:.1%}",
                                                "largest": "{:.2%}"}, na_rep="–").hide(axis="index"))

# %%
focus_holds = holds[holds["factor"].eq(FOCUS)].sort_values("weight", ascending=False)
if focus_holds.empty:
    note(f"The {FOCUS} book has no holdings in this response (not formed, or HOLDINGS = 0).")
else:
    focus_book = books.set_index("factor").loc[FOCUS]
    own_key = f"exposures.{FOCUS.lower()}"
    if own_key in focus_holds.columns:                     # the MARKET book has no style score of its own
        score = pd.to_numeric(focus_holds[own_key], errors="coerce")
        limit = float(np.nanmax(np.abs(score))) if score.notna().any() else 1.0
        marker = dict(color=score, colorscale=DIVERGING, cmin=-limit, cmax=limit, cmid=0,
                      colorbar=dict(title=dict(text=f"{FOCUS.capitalize()}<br>score"), thickness=14, len=0.8))
        legend_text = f"colour = the holding's {FOCUS.lower()} score (blue = positive, red = negative)"
    else:
        score, marker = pd.Series(np.nan, index=focus_holds.index), dict(color=FACTOR_COLORS[FOCUS])
        legend_text = "the MARKET book has no own-style score"
    y_labels = [f"{t} · {s}" for t, s in zip(focus_holds["ticker"], focus_holds["sector"])]
    fig = go.Figure(go.Bar(
        x=focus_holds["weight"], y=y_labels, orientation="h", marker=marker,
        customdata=np.column_stack([score.to_numpy(dtype=float)]),
        hovertemplate="%{y}<br>weight %{x:.2%}<br>own-style score %{customdata[0]:+.2f}<extra></extra>"))
    share = float(focus_holds["weight"].sum())
    top_row = focus_holds.iloc[0]
    heading, top = chart_title(
        f"The {len(focus_holds)} largest of {focus_book['n_holdings']:,.0f} {FOCUS} holdings make up "
        f"{share:.0%} of the book; the largest, {top_row['ticker']}, holds {top_row['weight']:.1%}",
        f"Weight of each listed holding in the {FOCUS} book · {legend_text} · the whole book's weights sum to "
        f"{focus_book['sum_weight']:.4f} (sum_weight)")
    fig.update_layout(title=heading, height=top + 90 + 19 * len(focus_holds), margin=dict(t=top, l=230, b=60),
                      xaxis=dict(title="Weight in the book (%)", tickformat=".1%", rangemode="tozero"),
                      yaxis=dict(autorange="reversed", ticks="", title=None), bargap=0.3)
    fig.show()
    by_sector = (focus_holds.groupby("sector")["weight"].agg(["size", "sum"])
                 .rename(columns={"size": "listed holdings", "sum": "weight"})
                 .sort_values("weight", ascending=False))
    by_sector["share of listed weight"] = by_sector["weight"] / share
    display(by_sector.reset_index().style.format({"weight": "{:.2%}", "share of listed weight": "{:.0%}"})
            .hide(axis="index"))

# %%
if holds.empty:
    note("No holdings, so there is no sector map.")
else:
    sector_weight = holds.pivot_table(index="factor", columns="sector", values="weight", aggfunc="sum", fill_value=0)
    sector_weight = sector_weight.reindex([f for f in books["factor"] if f in sector_weight.index])
    sector_weight = sector_weight[sector_weight.sum().sort_values(ascending=False).index]
    z = sector_weight.where(sector_weight > 0).to_numpy(dtype=float)     # no listed holding = blank, not 0
    fig = go.Figure(go.Heatmap(
        z=z, x=sector_weight.columns.tolist(), y=sector_weight.index.tolist(),
        text=[["" if np.isnan(v) or v < 0.005 else f"{v:.0%}" for v in row] for row in z], texttemplate="%{text}",
        textfont=dict(size=11), colorscale=[[i / 6, c] for i, c in enumerate(SEQUENTIAL)], zmin=0,
        xgap=2, ygap=2, hoverongaps=False, hovertemplate="%{y} book · %{x}: %{z:.1%} of the book<extra></extra>",
        colorbar=dict(title=dict(text="Share of<br>the book"), tickformat=".0%", thickness=14, len=0.85)))
    heavy = sector_weight.stack().idxmax()
    heading, top = chart_title(
        f"The heaviest sector block among the listed holdings: {heavy[1]} in the {heavy[0]} book "
        f"({sector_weight.loc[heavy]:.0%} of the book)",
        f"Weight of each book's {HOLDINGS} largest listed holdings, summed by sector · darker = more weight · "
        "blank = no listed holding in that sector · the rest of each book (not listed) is not shown")
    fig.update_layout(title=heading, height=top + 150 + 40 * len(sector_weight), margin=dict(t=top, l=120, b=140),
                      xaxis=dict(tickangle=-35, showgrid=False, ticks="", title=None),
                      yaxis=dict(autorange="reversed", showgrid=False, ticks="", title="Book"))
    fig.show()
    display(sector_weight.style.format("{:.1%}"))

# %% [markdown]
# **How to read this.** In the bar chart, the longest bars are the book's
# largest positions; the title says how much of the book they cover together.
# A style book built to lean on one style should mostly show blue bars: its
# largest holdings have positive scores on that style. The sector
# heatmap shows where each book's listed weight sits, so you can spot a style
# book that is, in practice, also a sector tilt. Both tables underneath are the
# table twins.
#
# **Caveats.**
#
# - The holdings are a preview of the largest positions, not the whole book.
#   Many books hold hundreds of stocks with small weights each.
# - These are the holdings formed for the latest formation week, not trades
#   that anybody executed (`labels.timing` says so).
# - A sector label is a current classification; the served caveats say when
#   it was not point-in-time.

# %% [markdown]
# ### 4.7 Weekly returns: from a dictionary to one tidy table
#
# `data.returns` is a **dictionary keyed by book**: `{"MARKET": [...],
# "SIZE": [...], ...}`. Each list holds one row per week with `week_start`,
# `formation_date`, `week_end_session`, `week_return` (a **fraction**), the
# week's `status` and its plain-English `status_label`, `in_inference`, the
# carried, invalid and exit weight shares, and the `return_basis_label`. We
# stack the lists into one long table with a `factor` column, which is the
# shape pandas likes best.

# %%
RETURNS = (data.get("returns") or {}) if AVAILABLE else {}
ret_raw = pd.DataFrame([{"factor": book, **row} for book, rows in RETURNS.items() for row in rows])
if ret_raw.empty:
    note(f"No return series in this response ({MARKET_NAMES[MARKET]} is `{data['status']}`).")
else:
    print(f"{len(ret_raw):,} rows: {len(RETURNS)} books × up to {ret_raw.groupby('factor').size().max()} weeks.")
    display(ret_raw.head())

# %% [markdown]
# **Cleaning.** Each step is printed, so nothing happens out of sight.
#
# 1. **Types.** `week_start`, `formation_date` and `week_end_session` are
#    exchange-calendar dates, parsed with an explicit format; the return and
#    the weight shares are coerced to numbers.
# 2. **De-duplication** on the natural key, (`factor`, `week_start`).
# 3. **Units.** The typical absolute weekly return should be well under 0.2 if
#    the API sends fractions. A single week beyond ±`MAX_ABS_WEEKLY` is treated
#    as a data error and counted.
# 4. **Status policy.** Only `status` = `"ok"` weeks carry a usable return.
#    A `degraded` week has a number, but the API labels it and excludes it from
#    inference, so we do the same. `unavailable`, `no_holdings` and
#    `return_not_yet_realised` weeks have no return at all. We count every
#    status per book and compare the counts with the API's own `data.counts`.
#    We never fill a missing return: a forward-filled return would invent a
#    week that nobody measured.
# 5. **Calendar gaps.** A calendar week in which the market was closed has no
#    formation. The API lists those weeks in `calendar_grid.gap_weeks` and keeps
#    them as gaps instead of squeezing the series together. We rebuild the full
#    grid of Mondays, so a gap stays a gap, and compare what we find with the
#    API's list.

# %%
RET_COLS = ["factor", "week_start", "formation_date", "week_end_session", "week_return", "status",
            "return_status", "in_inference", "in_holdout", "carried_weight_share", "invalid_weight_share",
            "exit_weight_share"]
ret = pick(ret_raw, RET_COLS)
for col in ["week_start", "formation_date", "week_end_session"]:
    ret[col] = pd.to_datetime(ret[col], format="%Y-%m-%d", errors="coerce")
for col in ["week_return", "carried_weight_share", "invalid_weight_share", "exit_weight_share"]:
    ret[col] = pd.to_numeric(ret[col], errors="coerce")
before = len(ret)
ret = ret.drop_duplicates(["factor", "week_start"], keep="last").sort_values(["factor", "week_start"])
ok = ret["status"].eq("ok")
typical = ret.loc[ok, "week_return"].abs().median()
extreme = ok & ret["week_return"].abs().gt(MAX_ABS_WEEKLY)
ret["r"] = ret["week_return"].where(ok & ~extreme)          # the clean weekly return: ok weeks only
mismatch = int((ret["in_inference"].eq(True) != ok).sum())

print(f"1. Types parsed; unparseable week_start values: {int(ret['week_start'].isna().sum())}.")
print(f"2. {before - len(ret)} duplicate (factor, week_start) rows removed.")
if ret.empty:
    print("3. No rows to check.")
elif pd.isna(typical) or typical < 0.2:
    print(f"3. Typical |weekly return| on ok weeks: {pct(typical, 2)} - consistent with fractions. "
          f"Weeks beyond ±{MAX_ABS_WEEKLY:.0%} set aside: {int(extreme.sum())}.")
else:
    raise ValueError(f"Typical |weekly return| is {typical:.2f}: the API seems to send percent, not fractions.")
print(f"4. Weeks with status 'ok': {int(ok.sum()):,} of {len(ret):,}. "
      f"Rows where in_inference disagrees with status == 'ok': {mismatch}.")
if AVAILABLE:
    print(f"   Rows inside the hold-out (in_holdout true): {int(ret['in_holdout'].eq(True).sum())}; "
          f"the response's holdout_start is {data.get('holdout_start')!r}.")

status_counts = pd.crosstab(ret["factor"], ret["status"]) if not ret.empty else pd.DataFrame()
api_counts = pd.DataFrame(data.get("counts") or {}).T if AVAILABLE else pd.DataFrame()
if not api_counts.empty:
    api_counts = api_counts.apply(pd.to_numeric, errors="coerce").fillna(0).astype(int)
    mine = status_counts.reindex(index=api_counts.index, columns=api_counts.columns, fill_value=0)
    same = bool((mine.to_numpy() == api_counts.to_numpy()).all())
    print(f"   Our status counts {'match' if same else 'DIFFER FROM'} data.counts for every book and status.")

if ret.empty:
    wide, gaps_found, api_gaps = pd.DataFrame(), pd.DatetimeIndex([]), pd.DatetimeIndex([])
else:
    wide = ret.pivot(index="week_start", columns="factor", values="r")
    order = [f for f in FACTORS if f in wide.columns] + sorted(set(wide.columns) - set(FACTORS))
    wide = wide[order]
    api_gaps = pd.DatetimeIndex(pd.to_datetime(data["calendar_grid"]["gap_weeks"], format="%Y-%m-%d"))
    if (wide.index.dayofweek == 0).all():
        grid = pd.date_range(wide.index.min(), wide.index.max(), freq="W-MON")
        gaps_found = grid.difference(wide.index)
        wide = wide.reindex(grid)
        in_window = api_gaps[(api_gaps >= grid.min()) & (api_gaps <= grid.max())]
        print(f"5. {plural(len(gaps_found), 'calendar week')} without a formation inside the window; "
              f"calendar_grid.gap_weeks lists {len(in_window)} there; same weeks: "
              f"{set(gaps_found) == set(in_window)}.")
    else:
        gaps_found = pd.DatetimeIndex([])
        print("5. Some week_start values are not Mondays, so the calendar grid is not rebuilt.")
    wide.index.name = "week_start"

if status_counts.empty:
    USE, coverage = [], pd.Series(dtype=float)
else:
    served = ret.groupby("factor").size()
    coverage = ret.groupby("factor")["r"].count() / served
    USE = [f for f in wide.columns if coverage[f] >= COVERAGE_MIN]
    table = status_counts.reindex(wide.columns).fillna(0).astype(int)
    table.insert(0, "weeks served", served.reindex(wide.columns))
    table["clean weeks (ok)"] = ret.groupby("factor")["r"].count().reindex(wide.columns)
    table["coverage"] = coverage.reindex(wide.columns)
    table["in charts"] = ["yes" if f in USE else f"no (< {COVERAGE_MIN:.0%})" for f in wide.columns]
    display(table.reset_index().style.format({"coverage": "{:.0%}"}).hide(axis="index"))
    left_out = [f for f in wide.columns if f not in USE]
    if left_out:
        print(f"Left out of the growth, drawdown, correlation and PCA charts: {and_list(left_out)} "
              f"(fewer than {COVERAGE_MIN:.0%} clean weeks). Their statistics still appear where they have "
              f"at least {MIN_WEEKS} clean weeks.")
HAVE_RETURNS = bool(USE)
NOTHING = (f"{MARKET_NAMES[MARKET]} sent no return series: `data.status` is `{data['status']}`"
           if ret.empty else "see the status table above")     # the reason the later notes give

# %% [markdown]
# **How to read this.** The table counts, for every book, how many weeks were
# served, how many had each status, and how many clean weeks remain. Coverage is
# the clean share. A book below `COVERAGE_MIN` is left out of the charts that
# compound or align weeks, because a long run of missing weeks would make its
# line meaningless; it is named, not hidden. The line above the table compares
# our counts with the API's own `data.counts`, a quick check that nothing was
# lost on the way.
#
# **Caveats.**
#
# - Dropping degraded weeks follows the API's own rule, but it is still a
#   choice: the weeks that are hard to measure are often the turbulent ones.
# - A clean week is clean by the API's degraded rule (quoted in section 4.2),
#   not perfect: a small share of a book can still be carried at its last price.

# %% [markdown]
# ### 4.8 Chart: growth of 100, raw long-only books
#
# To compare the books over time, we **compound** each book's weekly returns
# into the value of 100 invested at the start:
# value = 100 × (1 + r₁) × (1 + r₂) × … All books share **one axis** in one
# unit. A missing week leaves a break in the line and adds nothing to the
# product. MARKET is the thick ink line; the six style books keep their fixed
# colours.

# %%
if not HAVE_RETURNS:
    level = pd.DataFrame()
    note(f"No book has enough clean weeks for this chart ({NOTHING}).")
else:
    level = growth_index(wide[USE])
    final = level.ffill().iloc[-1]
    aligned = wide[USE].dropna()                            # complete-case window: every book has a clean week
    others = [f for f in USE if f != "MARKET"]
    if "MARKET" in USE and others and len(aligned) >= MIN_WEEKS:
        avg = float(aligned[others].corrwith(aligned["MARKET"]).mean())
        title = (f"All {len(USE)} books rise and fall together: their weekly returns correlate {avg:+.2f} with "
                 "the MARKET book on average" if avg >= 0.7 else
                 f"The books' weekly returns correlate {avg:+.2f} with the MARKET book on average")
    else:
        title = f"Value of 100 invested in each of {plural(len(USE), 'book')}"
    y_range = padded_range(level.to_numpy())
    PLOT_PX, BOTTOM = 340, 130

    fig = go.Figure()
    fig.add_hline(y=100, line=dict(color=AXIS, width=1), layer="below")
    for book in USE:
        fig.add_trace(go.Scatter(x=level.index, y=level[book], mode="lines", name=book,
                                 line=dict(color=FACTOR_COLORS.get(book, MUTED), width=3 if book == "MARKET" else 1.8),
                                 hovertemplate=f"{book}: %{{y:.1f}}<extra></extra>"))
    ends = pd.DataFrame({"x": [level[b].last_valid_index() for b in USE], "y": [final[b] for b in USE],
                         "text": [f"{b.capitalize()} {final[b]:.0f}" for b in USE],
                         "color": [FACTOR_COLORS.get(b, MUTED) for b in USE]})
    add_end_labels(fig, ends, y_range, PLOT_PX)
    heading, top = chart_title(title, f"Value of 100 invested at the start of each book, compounded weekly over "
                                      f"{plural(len(wide), 'week')} · gross of costs · a break = a week without "
                                      "a clean return · MARKET = thick ink line")
    fig.update_layout(title=heading, height=top + PLOT_PX + BOTTOM, margin=dict(t=top, b=BOTTOM, r=130),
                      hovermode="x unified", legend=dict(BOTTOM_LEGEND, itemclick=False, itemdoubleclick=False),
                      xaxis=date_axis(level.index), yaxis=dict(title="Value of 100 invested (index)", range=y_range))
    fig.show()
    quarterly = level.groupby(level.index.to_period("Q")).last()
    quarterly.index = quarterly.index.astype(str)
    display(quarterly.rename_axis("quarter-end level").style.format("{:.1f}", na_rep="–"))

# %% [markdown]
# **How to read this.** Each line is one book. The grey horizontal line marks
# 100 (break-even) and the label at a line's right end is its final value.
# Hover to see every book on one date. The lines climb and fall together: that
# is the market exposure of 1 that every book shares. The differences between
# the lines are much smaller than their common swings, and section 4.10
# isolates exactly those differences. The table gives the level at the end of
# each quarter.
#
# **Caveats.**
#
# - **Gross of costs**, and the return basis is the one in the quoted
#   `returns_label` (section 4.2). Weekly rebuilding has trading costs that are
#   not deducted.
# - "Value of 100" assumes the book is rebuilt every week exactly as
#   published. It is a retrospective measurement, not a record of trades.
# - The window is the `WEEKS` you requested. A different start can change
#   which book ends highest.

# %% [markdown]
# ### 4.9 Chart: drawdowns
#
# A **drawdown** is how far a book sits below its own best value so far:
# drawdown = level ÷ running peak − 1. Its lowest point is the **maximum
# drawdown**. Each book gets its own small panel, all panels share one y-axis,
# so depths compare directly.

# %%
if not HAVE_RETURNS:
    note(f"No book has enough clean weeks for drawdowns ({NOTHING}).")
else:
    drawdown = level / level.cummax() - 1
    rows, cols = grid_shape(len(USE))
    fig = make_subplots(rows=rows, cols=cols, shared_xaxes="all", shared_yaxes="all", subplot_titles=USE,
                        horizontal_spacing=0.04, vertical_spacing=0.14)
    fig.update_annotations(font=dict(size=13, color=INK))
    dd_rows = []
    for k, book in enumerate(USE):
        r, c = k // cols + 1, k % cols + 1
        s, lv = drawdown[book].dropna(), level[book].dropna()
        trough = s.idxmin()
        peak = lv.loc[:trough].idxmax()
        back = lv.loc[trough:]
        recovered = back[back >= lv.loc[peak]].first_valid_index()
        fig.add_trace(go.Scatter(x=s.index, y=s, mode="lines", name=book, showlegend=False, fill="tozeroy",
                                 fillcolor="rgba(82,81,78,0.12)", line=dict(color=INK_2, width=1.5),
                                 hovertemplate=f"{book}: %{{y:.1%}} below its peak<extra></extra>"), row=r, col=c)
        fig.add_trace(go.Scatter(x=[trough], y=[s.min()], mode="markers+text", showlegend=False, hoverinfo="skip",
                                 marker=dict(size=8, color=INK, line=dict(width=2, color=SURFACE)),
                                 text=[f"{s.min():.1%}"], textposition="bottom center", cliponaxis=False,
                                 textfont=dict(size=11, color=INK_2)), row=r, col=c)
        dd_rows.append({"book": book, "peak (week start)": f"{peak:%Y-%m-%d}", "trough": f"{trough:%Y-%m-%d}",
                        "max drawdown": s.min(), "weeks, peak to trough": int(round((trough - peak).days / 7)),
                        "back at the peak by": (f"{recovered:%Y-%m-%d}" if recovered is not None
                                                else "not within the window"),
                        "drawdown at the end": s.iloc[-1]})
    dd_table = pd.DataFrame(dd_rows)
    if "MARKET" in USE and len(USE) > 1:
        rest = dd_table[dd_table["book"].ne("MARKET")]["max drawdown"]
        mkt = float(dd_table.loc[dd_table["book"].eq("MARKET"), "max drawdown"].iloc[0])
        title = (f"MARKET's deepest fall was {mkt:.1%}; the other books' deepest falls ranged from "
                 f"{rest.min():.1%} to {rest.max():.1%}")
    else:
        deep = dd_table.loc[dd_table["max drawdown"].idxmin()]
        title = f"{deep['book']} fell furthest from a peak: {deep['max drawdown']:.1%}"
    fig.update_yaxes(tickformat=".0%", range=[float(dd_table["max drawdown"].min()) * 1.3, 0.004])
    fig.update_yaxes(title_text="Below peak (%)", col=1)
    hide_unused_panels(fig, len(USE), rows, cols)
    heading, top = chart_title(title, "Distance below each book's running peak · dot = maximum drawdown · "
                                      "shared y-axis", extra_top=22)
    fig.update_layout(title=heading, height=top + 230 * rows + 80, margin=dict(t=top, b=70), showlegend=False,
                      hovermode="x")
    fig.show()
    display(dd_table.style.format({"max drawdown": "{:.1%}", "drawdown at the end": "{:.1%}"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Each panel is one book. The shaded area is how far it
# sits below its best value so far (0% = a new high), and the dot marks the
# deepest point. Because every book carries the market once, the big falls tend
# to happen in the same weeks in every panel. The table adds when each fall
# started and ended and whether the book climbed back within the window.
#
# **Caveats.**
#
# - A maximum drawdown comes from one episode, so it is a noisy measure of risk.
# - It can only see falls inside the requested window. A longer `WEEKS` can
#   reveal a deeper one.

# %% [markdown]
# ### 4.10 Style minus MARKET: where the style shows
#
# Both a style book and the MARKET book have market exposure 1, and they differ
# by about one unit of the style. So the weekly **spread**
#
#     spread = style book's return − MARKET book's return
#
# cancels the market and keeps about one unit of the style (plus the noise of
# holding different stocks). A spread is computed only in weeks where **both**
# books have a clean return. We then compound each spread into a value of 100,
# and summarise it as an annualised mean (mean × 52) and volatility
# (standard deviation × √52), with a 95% interval for the mean. The interval
# uses HAC (Newey-West) standard errors, which allow for weeks that are not
# independent of each other.

# %%
if wide.empty or "MARKET" not in wide.columns or wide["MARKET"].count() < MIN_WEEKS:
    spreads, SPREADS, SPREAD_USE = pd.DataFrame(), [], []
    note(f"The MARKET book has fewer than {MIN_WEEKS} clean weeks, so no style-minus-MARKET spread can be "
         f"measured ({NOTHING}).")
else:
    spreads = wide.drop(columns="MARKET").sub(wide["MARKET"], axis=0)
    n_clean = spreads.count()
    SPREADS = [f for f in spreads.columns if n_clean[f] >= MIN_WEEKS]
    SPREAD_USE = [f for f in SPREADS if f in USE and "MARKET" in USE]
    too_short = [f"{f} ({n_clean[f]} weeks)" for f in spreads.columns if f not in SPREADS]
    print(f"Spreads with at least {MIN_WEEKS} clean weeks: {and_list(SPREADS)}."
          + (f" Too short for statistics: {and_list(too_short)}." if too_short else ""))
    display(spreads.dropna(how="all").head())

# %%
if not SPREAD_USE:
    note("No style book has enough clean weeks for the spread chart.")
else:
    spread_level = growth_index(spreads[SPREAD_USE])
    spread_final = spread_level.ffill().iloc[-1]
    best, worst = spread_final.idxmax(), spread_final.idxmin()
    y_range = padded_range(spread_level.to_numpy())
    PLOT_PX, BOTTOM = 320, 130
    fig = go.Figure()
    fig.add_hline(y=100, line=dict(color=AXIS, width=1), layer="below")
    for book in SPREAD_USE:
        fig.add_trace(go.Scatter(x=spread_level.index, y=spread_level[book], mode="lines",
                                 name=f"{book} − MARKET", line=dict(color=FACTOR_COLORS.get(book, MUTED), width=2),
                                 hovertemplate=f"{book} − MARKET: %{{y:.1f}}<extra></extra>"))
    ends = pd.DataFrame({"x": [spread_level[b].last_valid_index() for b in SPREAD_USE],
                         "y": [spread_final[b] for b in SPREAD_USE],
                         "text": [f"{b.capitalize()} {spread_final[b]:.0f}" for b in SPREAD_USE],
                         "color": [FACTOR_COLORS.get(b, MUTED) for b in SPREAD_USE]})
    add_end_labels(fig, ends, y_range, PLOT_PX)
    title = (f"With the market taken out: {best.capitalize()} − MARKET ended at {spread_final[best]:.0f}, "
             f"{worst.capitalize()} − MARKET at {spread_final[worst]:.0f}"
             if len(SPREAD_USE) > 1 else f"With the market taken out: {best.capitalize()} − MARKET ended at "
                                         f"{spread_final[best]:.0f}")
    heading, top = chart_title(title, "Value of 100 in each weekly style-minus-MARKET spread, compounded "
                                      f"weekly over {plural(len(spreads), 'week')} · gross of costs · "
                                      "in-sample measurement, not a forecast")
    fig.update_layout(title=heading, height=top + PLOT_PX + BOTTOM, margin=dict(t=top, b=BOTTOM, r=130),
                      hovermode="x unified", legend=dict(BOTTOM_LEGEND, itemclick=False, itemdoubleclick=False),
                      xaxis=date_axis(spread_level.index),
                      yaxis=dict(title="Value of 100 in the spread (index)", range=y_range))
    fig.show()

# %%
if not SPREADS:
    spread_stats = pd.DataFrame()
    note("No spread has enough clean weeks for statistics.")
else:
    spread_stats = pd.DataFrame({f: annual_stats(spreads[f]) for f in SPREADS}).T
    paired = {f: spreads[f].dropna().index for f in SPREADS}          # the weeks each spread actually uses
    spread_stats["book vol / year"] = [wide.loc[paired[f], f].std() * np.sqrt(WEEKS_PER_YEAR) for f in SPREADS]
    spread_stats["MARKET vol / year"] = [wide.loc[paired[f], "MARKET"].std() * np.sqrt(WEEKS_PER_YEAR)
                                         for f in SPREADS]
    spread_stats = spread_stats.rename_axis("spread").reset_index()
    spread_stats["spread"] = spread_stats["spread"] + " − MARKET"
    clear = spread_stats[(spread_stats["95% low"] > 0) | (spread_stats["95% high"] < 0)]
    title = (f"{len(clear)} of {len(spread_stats)} spreads have a 95% interval that excludes zero"
             if len(clear) else
             f"No spread's 95% interval excludes zero: with at most {int(spread_stats['weeks'].max())} clean "
             "weeks, these averages cannot be told from zero")
    colors = [MUTED if lo <= 0 <= hi else INK for lo, hi in zip(spread_stats["95% low"], spread_stats["95% high"])]
    fig = go.Figure()
    fig.add_vline(x=0, line=dict(color=AXIS, width=1), layer="below")
    fig.add_trace(go.Scatter(
        x=spread_stats["mean / year"], y=spread_stats["spread"], mode="markers", showlegend=False,
        marker=dict(size=11, color=colors, line=dict(width=2, color=SURFACE)),
        error_x=dict(type="data", symmetric=False, thickness=2, width=0, color=INK_2,
                     array=spread_stats["95% high"] - spread_stats["mean / year"],
                     arrayminus=spread_stats["mean / year"] - spread_stats["95% low"]),
        customdata=spread_stats[["95% low", "95% high", "weeks"]].to_numpy(dtype=float),
        hovertemplate="%{y}: %{x:+.1%} a year<br>95% interval %{customdata[0]:+.1%} to %{customdata[1]:+.1%}"
                      "<br>%{customdata[2]:.0f} clean weeks<extra></extra>"))
    heading, top = chart_title(title, "Annualised mean of each weekly spread (mean × 52) with a 95% interval "
                                      "from HAC standard errors · dark dot = the interval excludes zero, grey "
                                      "dot = it crosses zero · in-sample, gross of costs")
    fig.update_layout(title=heading, height=top + 90 + 46 * len(spread_stats), margin=dict(t=top, l=200, b=60),
                      xaxis=dict(title="Annualised mean of the spread (% a year)", tickformat=".0%"),
                      yaxis=dict(autorange="reversed", ticks="", title=None))
    fig.show()
    display(spread_stats.style.format({"weeks": "{:.0f}", "years": "{:.1f}", "mean / year": "{:+.1%}",
                                       "vol / year": "{:.1%}", "95% low": "{:+.1%}", "95% high": "{:+.1%}",
                                       "t (HAC)": "{:+.2f}", "book vol / year": "{:.1%}",
                                       "MARKET vol / year": "{:.1%}"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** The first chart compounds each spread. A line that
# climbs means the style book beat the MARKET book over those weeks; a line
# that falls means it trailed. The dot chart turns each spread into one
# annualised mean with a 95% interval. A whisker that crosses zero means the
# window is too short to tell that average from zero. In the table, compare
# `vol / year` of the spread with `book vol / year`: the spread swings far
# less than the book itself, because subtracting MARKET removed the market's
# swings, which are most of a long-only book's risk.
#
# **Caveats.**
#
# - **Sample size.** `weeks` and `years` are in the table. A few years of weekly
#   data give wide intervals; a mean that looks large can still be noise.
# - **Many spreads, one window.** With six spreads, one can clear zero by luck.
# - **In-sample, gross of costs, a measurement.** None of this is a forecast
#   or a claim about what the books will return. The API itself states that no
#   accuracy or performance claim is made.
# - Compounding a spread treats it as a long-short position rebuilt every
#   week: long the style book, short the MARKET book. Real short positions
#   would add costs that are not measured here.

# %% [markdown]
# ### 4.11 Chart: correlations, raw books versus spreads
#
# A **correlation** runs from −1 (always opposite) through 0 (unrelated) to +1
# (always together). We compute two matrices on complete-case windows (every
# pair uses the same weeks): the raw books on the left, the style-minus-MARKET
# spreads on the right. Both use the same diverging scale from −1 to 1, centred
# at 0, so the colours compare directly.

# %%
raw_aligned = wide[USE].dropna() if HAVE_RETURNS else pd.DataFrame()
spread_aligned = spreads[SPREAD_USE].dropna() if SPREAD_USE else pd.DataFrame()
if raw_aligned.shape[1] < 2 or len(raw_aligned) < MIN_WEEKS:
    note("Fewer than two books with enough aligned clean weeks, so there is no correlation matrix.")
else:
    raw_corr = raw_aligned.corr()
    have_spread_corr = spread_aligned.shape[1] >= 2 and len(spread_aligned) >= MIN_WEEKS
    spread_corr = spread_aligned.corr() if have_spread_corr else pd.DataFrame()
    titles = [f"Raw books · {len(raw_aligned)} weeks",
              f"Style − MARKET spreads · {len(spread_aligned)} weeks" if have_spread_corr else "Spreads: too few"]
    fig = make_subplots(rows=1, cols=2, subplot_titles=titles, horizontal_spacing=0.16)
    fig.update_annotations(font=dict(size=13, color=INK))
    fig.add_trace(corr_trace(raw_corr, showscale=True), row=1, col=1)
    if have_spread_corr:
        fig.add_trace(corr_trace(spread_corr, showscale=False), row=1, col=2)
        title = (f"Raw books correlate {mean_pair(raw_corr):+.2f} on average; after subtracting MARKET, the "
                 f"spreads correlate {mean_pair(spread_corr):+.2f}")
    else:
        title = f"Raw books correlate {mean_pair(raw_corr):+.2f} on average"
    heading, top = chart_title(title, "Correlation of weekly returns on complete-case windows · blue = move "
                                      "together, red = move opposite, grey ≈ unrelated · same scale in both "
                                      "panels", extra_top=22)
    fig.update_layout(title=heading, height=top + 120 + 46 * len(USE), margin=dict(t=top, l=110, r=40, b=110))
    fig.update_xaxes(showgrid=False, ticks="", tickangle=-35)
    fig.update_yaxes(showgrid=False, ticks="", autorange="reversed")
    fig.show()
    display(raw_corr.style.format(signed).set_caption("Raw books"))
    if have_spread_corr:
        display(spread_corr.style.format(signed).set_caption("Style − MARKET spreads"))

# %% [markdown]
# **How to read this.** On the left, almost every cell is deep blue: raw
# long-only books move together because they all carry the market. On the
# right, with the market subtracted, the colours fade towards grey and some
# turn red. These are the relationships between the styles themselves, the
# ones that matter when you think about combining them. The tables are the
# twins of the two panels.
#
# **Caveats.**
#
# - A correlation from a few years of weekly data is noisy. As a rule of thumb,
#   values within about ±2 / √(weeks) of zero cannot be told from zero.
# - Correlations change over time and tend to rise in market stress.

# %% [markdown]
# ### 4.12 Chart: the long-only spread versus its Fama-French 2×3 twin
#
# With `measurement=true` the response also carries **measurement twins** in
# `data.measurement_twins`: Fama-French-style 2×3 long-short portfolios for the
# same styles (`s3b_ff_2x3_ew` weights stocks equally inside each leg;
# `s3b_ff_2x3_rp126` by inverse 126-session volatility). They follow the
# classic academic recipe: buy one end of a sort, sell the other end short.
# Their weekly returns sit in `returns[FACTOR]`, with the same row shape as the
# books' returns. Comparing the `FOCUS` spread with its twin asks: does the
# long-only book capture the same style as the academic long-short version?

# %%
twins = (data.get("measurement_twins") or {}) if AVAILABLE else {}
if not MEASUREMENT or TWIN not in twins:
    twin_r = pd.Series(dtype=float)
    note(f"No measurement twin `{TWIN}` in this response (MEASUREMENT = {MEASUREMENT}).")
else:
    twin = twins[TWIN]
    quote(f"data.measurement_twins.{TWIN}.label", twin.get("label"))
    quote(f"data.measurement_twins.{TWIN}.returns_label", twin.get("returns_label"))
    twin_raw = pd.DataFrame((twin.get("returns") or {}).get(FOCUS) or [])
    if twin_raw.empty:
        twin_r = pd.Series(dtype=float)
        note(f"The twin has no {FOCUS} series in this response.")
    else:
        twin_rows = pick(twin_raw, ["week_start", "week_return", "status"])
        twin_rows["week_start"] = pd.to_datetime(twin_rows["week_start"], format="%Y-%m-%d", errors="coerce")
        twin_rows["week_return"] = pd.to_numeric(twin_rows["week_return"], errors="coerce")
        twin_rows = twin_rows.drop_duplicates("week_start", keep="last")
        twin_r = twin_rows.loc[twin_rows["status"].eq("ok")].set_index("week_start")["week_return"]
        print(f"Twin {FOCUS}: {len(twin_rows)} weeks served, {len(twin_r)} with status 'ok' "
              f"({twin_rows['status'].value_counts().to_dict()}).")

# %%
if FOCUS == "MARKET":
    long_only = wide["MARKET"] if "MARKET" in wide.columns else pd.Series(dtype=float)
else:
    long_only = spreads[FOCUS] if FOCUS in spreads.columns else pd.Series(dtype=float)
lo_name = "MARKET book" if FOCUS == "MARKET" else f"{FOCUS} − MARKET (long-only)"
pair = pd.concat({lo_name: long_only, f"{FOCUS} 2×3 twin": twin_r}, axis=1, sort=True).dropna()
if len(pair) < MIN_WEEKS:
    note(f"Fewer than {MIN_WEEKS} weeks in which both the {lo_name} and the twin have a clean return, "
         "so they are not compared.")
else:
    pair_level = growth_index(pair)
    pair_final = pair_level.iloc[-1]
    rho = float(pair.corr().iloc[0, 1])
    y_range = padded_range(pair_level.to_numpy())
    beta = float(pair.cov().iloc[0, 1] / pair.iloc[:, 1].var())     # long-only move per unit of the twin's move
    PLOT_PX, BOTTOM = 300, 130
    styles = {lo_name: dict(color=FACTOR_COLORS[FOCUS], width=2.4),
              f"{FOCUS} 2×3 twin": dict(color=INK_2, width=2, dash="dash")}
    fig = go.Figure()
    fig.add_hline(y=100, line=dict(color=AXIS, width=1), layer="below")
    for name in pair.columns:
        fig.add_trace(go.Scatter(x=pair_level.index, y=pair_level[name], mode="lines", name=name, line=styles[name],
                                 hovertemplate=f"{name}: %{{y:.1f}}<extra></extra>"))
    ends = pd.DataFrame({"x": [pair_level.index[-1]] * 2, "y": pair_final.to_numpy(),
                         "text": [f"{'Long-only' if i == 0 else 'Twin'} {v:.0f}" for i, v in enumerate(pair_final)],
                         "color": [FACTOR_COLORS[FOCUS], INK_2]})
    add_end_labels(fig, ends, y_range, PLOT_PX)
    heading, top = chart_title(
        f"{FOCUS}: the long-only {'book' if FOCUS == 'MARKET' else 'spread'} and its 2×3 twin correlate "
        f"{rho:+.2f} week to week",
        f"Value of 100 in each, over the {plural(len(pair), 'week')} both have a clean return · twin "
        f"{TWIN} (long-short, a yardstick for measurement, not one of the books) · gross of costs")
    fig.update_layout(title=heading, height=top + PLOT_PX + BOTTOM, margin=dict(t=top, b=BOTTOM, r=120),
                      hovermode="x unified", legend=dict(BOTTOM_LEGEND, itemclick=False, itemdoubleclick=False),
                      xaxis=date_axis(pair_level.index), yaxis=dict(title="Value of 100 (index)", range=y_range))
    fig.show()
    pair_stats = pd.DataFrame({name: annual_stats(pair[name]) for name in pair.columns}).T
    pair_stats["correlation with the other"] = rho
    print(f"Regression slope of the long-only series on the twin: {beta:.2f} (it moves about {beta:.2f} for each "
          "1.00 the twin moves in a week).")
    display(pair_stats.rename_axis("series").reset_index().style.format(
        {"weeks": "{:.0f}", "years": "{:.1f}", "mean / year": "{:+.1%}", "vol / year": "{:.1%}",
         "95% low": "{:+.1%}", "95% high": "{:+.1%}", "t (HAC)": "{:+.2f}",
         "correlation with the other": "{:+.2f}"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Both lines start at 100 on the first week they share.
# If they rise and fall in step (a high correlation), the long-only spread and
# the academic long-short portfolio capture the same style. Their levels need
# not match: the twin's exposure to the style is whatever its sort produces,
# while the long-only spread carries about one unit of it, so one line can be
# a scaled version of the other. The printed regression slope measures that
# scale: how far the long-only spread moved, on average, per unit move of the
# twin in the same week.
#
# **Caveats.**
#
# - The twin is a yardstick for measurement, not one of the books (read its
#   own label above). It needs short selling, which costs money and is not
#   always possible.
# - Both are gross of costs and measured on the same return basis (see the
#   twin's `returns_label` above).

# %% [markdown]
# ## 5. The query parameters, and what the errors look like
#
# Three more requests show the parameters you have not used yet:
#
# 1. **`factor` + `formation_date` + a complete book.** We ask for the `FOCUS`
#    book only (`factor=`), at a published formation date about a year ago
#    (`formation_date=`), with every holding (`holdings=5000`), one week of
#    returns (`weeks=1`) and no twins (`measurement=false`). With the complete
#    list we can check two things ourselves: whether the weights sum to 1, and
#    whether the weighted average of the holdings' style scores reproduces the
#    book's exposures.
# 2. **A date with no published books.** Formations happen once a week, so the
#    day after a formation date is never one. The API answers with the empty
#    state and `reason_code` = `formation_date_not_published`.
# 3. **An invalid factor.** `factor=QUALITY` is not one of the seven books. The
#    API answers HTTP 400 with the code `INVALID_FACTOR` (the JSON body's
#    `error.factors` lists the valid names), and `sf_get` raises
#    `SurgeFlowError`, which we catch.
#
# The other errors work the same way: HTTP 400 `INVALID_DATE` for a
# `formation_date` that is not a `YYYY-MM-DD` date, HTTP 400 `INVALID_MARKET`
# for a market outside `us`, `cn`, `jp`, `hk`, and HTTP 503 when the data cannot
# be read right now (`sf_get` retries, then raises; `sf_try` prints a note and
# returns `None`).

# %%
focus_ok = ret.loc[ret["factor"].eq(FOCUS) & ret["status"].eq("ok"), "formation_date"] if not ret.empty else []
pool = focus_ok if len(focus_ok) else (ret.loc[ret["status"].eq("ok"), "formation_date"] if not ret.empty else [])
formations = sorted(pd.Series(pool).dropna().unique())   # published formation dates where the FOCUS book was formed
if not formations:
    PAST_DATE = None
    note("No published formation dates in the main response, so the formation_date examples are skipped.")
else:
    PAST_DATE = pd.Timestamp(formations[max(0, len(formations) - 53)])     # about a year before the latest
    one = sf_get(f"/api/v1/markets/{MARKET}/factor-portfolios", factor=FOCUS,
                 formation_date=f"{PAST_DATE:%Y-%m-%d}", weeks=1, holdings=5000, measurement="false")
    show_freshness(one, "factor + formation_date response:")
    one_data = one["data"]
    served_books = [b["factor"] for b in records(one, "factor_portfolios")]
    print(f"Asked for factor={FOCUS}, formation_date={PAST_DATE:%Y-%m-%d}. Served: data.status "
          f"{one_data['status']!r}, formation_date {one_data.get('formation_date')!r}, books {served_books}.")
    if len(served_books) > 1 or one_data.get("formation_date") != f"{PAST_DATE:%Y-%m-%d}":
        print("The server did not apply every parameter (the offline mock used for testing ignores query "
              f"parameters). The {FOCUS} book is picked out of the response below.")
    book = next((b for b in records(one, "factor_portfolios") if b["factor"] == FOCUS), None)
    if one_data["status"] != "available" or book is None or not book.get("holdings"):
        show_state(one, f"{FOCUS} at {PAST_DATE:%Y-%m-%d}")
        note(f"No {FOCUS} holdings in this answer, so the checks are skipped.")
    else:
        full = pd.json_normalize(book["holdings"])
        full["weight"] = pd.to_numeric(full["weight"], errors="coerce")
        truncated = bool(book.get("holdings_truncated"))
        print(f"{len(full):,} holdings received of n_holdings = {book['n_holdings']:,}; "
              f"holdings_truncated = {truncated}.")
        print(f"Sum of the received weights: {full['weight'].sum():.6f} (sum_weight says {book['sum_weight']:.6f})"
              + (" - partial, because the list is truncated." if truncated else "."))
        implied = {s: float((full["weight"] * pd.to_numeric(full[f"exposures.{s}"], errors="coerce")).sum())
                   for s in STYLES if f"exposures.{s}" in full.columns}
        implied["market"] = float(full["weight"].sum())          # every stock's market loading is 1
        recon = pd.DataFrame({"book exposure (API)": pd.Series(book["exposures"]),
                              "Σ weight × holding score": pd.Series(implied)}).reindex(STYLES)
        recon["difference"] = recon["Σ weight × holding score"] - recon["book exposure (API)"]
        display(recon.style.format("{:+.4f}", na_rep="–"))
        current = set(holds.loc[holds["factor"].eq(FOCUS), "ticker"])
        then = set(full.nlargest(len(current) or HOLDINGS, "weight")["ticker"])
        if current:
            print(f"Of today's {len(current)} largest {FOCUS} holdings, {len(current & then)} were also among the "
                  f"{len(then)} largest at {PAST_DATE:%Y-%m-%d}.")
    del one                                                   # keep memory small: only the summary is needed

# %% [markdown]
# **How to read this.** The first line confirms what the server applied.
# With the complete list (`holdings_truncated` false), the weights should add
# up to 1. The table tests the usual definition of an exposure, the weighted
# average of the holdings' style scores: if the book's exposures are built that
# way, the `difference` column is close to zero for every style, and `market`
# is 1 because each stock counts once on the market. If the list is truncated,
# both checks are partial and the differences show it. The last line compares
# today's largest holdings with those of a year ago: a book is rebuilt every
# week, and its names drift.

# %%
if PAST_DATE is None:
    note("Skipped: no formation dates to build an unpublished date from.")
else:
    NOT_PUBLISHED = ret["formation_date"].max() + pd.Timedelta(days=1)   # the day after the latest formation
    miss = sf_get(f"/api/v1/markets/{MARKET}/factor-portfolios", formation_date=f"{NOT_PUBLISHED:%Y-%m-%d}",
                  weeks=1, holdings=0, measurement="false")
    show_freshness(miss, "Unpublished formation_date response:")
    status, code, message = state_of(miss)
    print(f"HTTP 200, ok = {miss['ok']} | data.status: {status!r} | data.reason_code: {code!r}")
    if status == "empty":
        display(Markdown(f"> {message}"))
    else:
        print("The server answered with books (the offline mock ignores formation_date); live, this date returns "
              "the empty state with reason_code 'formation_date_not_published'.")
    del miss

try:
    sf_get(f"/api/v1/markets/{MARKET}/factor-portfolios", factor="QUALITY", weeks=1, holdings=0,
           measurement="false")
    print("No error came back: the offline mock ignores query parameters. Live, factor=QUALITY answers "
          "HTTP 400 INVALID_FACTOR.")
except SurgeFlowError as exc:
    print(f"Caught SurgeFlowError: HTTP {exc.status}, code {exc.code}")
    print(f"Message: {exc}")

# %% [markdown]
# **How to read this.** An unpublished date is **not** an error: the answer is
# HTTP 200 with `data.status` = `"empty"`, so the code prints the message and
# carries on. An invalid factor **is** an error: a 400 with a code you can test
# for (`exc.code == "INVALID_FACTOR"`). Keep that distinction in your own code:
# show empty states, and let real errors raise, or catch them by code.

# %% [markdown]
# ## 6. Four markets: who publishes, how fresh, and one spread side by side
#
# Each market has its own publication, calendar, universe and return basis. The
# cell reuses the responses we already have (yours and Hong Kong's) and fetches
# the others with `holdings=0` and `measurement=false`, because only the return
# series are needed. It uses `sf_try`, so a market that cannot be read right
# now prints a note instead of stopping the notebook. The table shows each
# market's `data.status` and its freshness block's `state` and `weeks_behind`
# exactly as reported; the small panels compound the `FOCUS` spread (the MARKET
# book itself when `FOCUS` is MARKET).

# %%
def focus_series(payload: dict) -> pd.Series:
    """The FOCUS spread (or the MARKET book) from one market's response: clean weeks only."""
    frames = []
    for book in {"MARKET", FOCUS}:
        rows = pd.DataFrame(dig(payload, "data", "returns", book, default=[]) or [])
        if rows.empty:
            return pd.Series(dtype=float)
        rows = pick(rows, ["week_start", "week_return", "status"]).drop_duplicates("week_start", keep="last")
        rows["week_start"] = pd.to_datetime(rows["week_start"], format="%Y-%m-%d", errors="coerce")
        rows["week_return"] = pd.to_numeric(rows["week_return"], errors="coerce")
        frames.append(rows.loc[rows["status"].eq("ok")].set_index("week_start")["week_return"].rename(book))
    both = pd.concat(frames, axis=1, sort=True)
    return (both["MARKET"] if FOCUS == "MARKET" else both[FOCUS] - both["MARKET"]).dropna()


VIEWS = {}
if COMPARE_MARKETS:
    for m in MARKETS:
        payload = PAYLOADS.get(m)
        if payload is None:
            payload = sf_try(f"/api/v1/markets/{m}/factor-portfolios", weeks=WEEKS, holdings=0, measurement="false")
            if payload is not None:
                show_freshness(payload, f"{MARKET_NAMES[m]}:")
        if payload is None:
            VIEWS[m] = {"market": m, "data.status": "unreadable now"}
            continue
        status, code, message = state_of(payload)
        fresh = dig(payload, "data", "freshness", default={}) or {}
        series = focus_series(payload) if status == "available" else pd.Series(dtype=float)
        VIEWS[m] = {"market": m, "data.status": status, "reason_code": code, "message": message,
                    "publication_id": dig(payload, "data", "publication", "publication_id"),
                    "freshness.state": fresh.get("state"), "freshness.weeks_behind": fresh.get("weeks_behind"),
                    "return basis": dig(payload, "data", "return_basis", "label"),
                    "series": series} | annual_stats(series)
        if m not in (MARKET, EMPTY_DEMO):
            del payload                                       # only the summary and the series are kept
    market_table = pd.DataFrame([{k: v for k, v in view.items() if k != "series"} for view in VIEWS.values()])
    as_sent = lambda v: "–" if v is None or pd.isna(v) else f"{v:g}"      # 2.0 (a float after NaN) prints as 2
    display(styled_freshness(market_table).format({"freshness.weeks_behind": as_sent, "years": "{:.1f}",
                                                   "mean / year": "{:+.1%}",
                                                   "vol / year": "{:.1%}", "95% low": "{:+.1%}",
                                                   "95% high": "{:+.1%}", "t (HAC)": "{:+.2f}"}, na_rep="–"))
else:
    note("COMPARE_MARKETS is False, so the four-market comparison is skipped.")

# %%
if not VIEWS:
    note("Nothing to draw: the comparison was skipped.")
else:
    label = "MARKET book" if FOCUS == "MARKET" else f"{FOCUS} − MARKET"
    fig = make_subplots(rows=2, cols=2, shared_xaxes="all", shared_yaxes="all", horizontal_spacing=0.06,
                        vertical_spacing=0.16, subplot_titles=[MARKET_NAMES[m] for m in MARKETS])
    fig.update_annotations(font=dict(size=13, color=INK))
    finals = {}
    for k, m in enumerate(MARKETS):
        r, c = k // 2 + 1, k % 2 + 1
        series = VIEWS.get(m, {}).get("series", pd.Series(dtype=float))
        if len(series) >= MIN_WEEKS:
            lv = growth_index(series.to_frame(m))[m]
            finals[m] = float(lv.iloc[-1])
            fig.add_trace(go.Scatter(x=lv.index, y=lv, mode="lines", name=MARKET_NAMES[m],
                                     line=dict(color=MARKET_COLORS[m], width=2),
                                     hovertemplate=f"{MARKET_NAMES[m]}: %{{y:.1f}}<extra></extra>"), row=r, col=c)
            fig.add_hline(y=100, line=dict(color=AXIS, width=1), layer="below", row=r, col=c)
        else:
            view = VIEWS.get(m, {})
            why = view.get("message") or f"fewer than {MIN_WEEKS} clean weeks of {label}"
            xd = fig.layout[f"xaxis{k + 1 if k else ''}"].domain       # the empty panel's place on the page
            yd = fig.layout[f"yaxis{k + 1 if k else ''}"].domain
            fig.add_annotation(text="<br>".join(textwrap.wrap(f"{view.get('data.status')}: {why}", 38)),
                               x=sum(xd) / 2, y=sum(yd) / 2, xref="paper", yref="paper", showarrow=False,
                               font=dict(size=12, color=MUTED))
    if finals:
        top_m = max(finals, key=finals.get)
        title = (f"{label} across markets: {len(finals)} of 4 have a series; {MARKET_NAMES[top_m]} ended highest "
                 f"at {finals[top_m]:.0f}" if len(finals) > 1 else f"{label}: only {MARKET_NAMES[top_m]} has a series")
    else:
        title = f"No market has {MIN_WEEKS} clean weeks of {label}"
    heading, top = chart_title(title, f"Value of 100 in the weekly {label} series of each market, compounded "
                                      "weekly · each market on its own calendar and return basis (see the table) "
                                      "· shared axes · gross of costs", extra_top=22)
    fig.update_layout(title=heading, height=top + 520, margin=dict(t=top, b=70), hovermode="x unified",
                      legend=dict(BOTTOM_LEGEND, itemclick=False, itemdoubleclick=False))
    fig.update_yaxes(title_text="Value of 100", col=1)
    fig.show()

# %% [markdown]
# **How to read this.** The table is the place to start: which markets answer
# `available`, which answer `empty` (with their message), and each market's
# freshness `state` and `weeks_behind` as reported. The panels then show the
# same spread in each published market, in that market's colour, on shared axes.
# An empty market's panel carries its status and message instead of a line.
#
# **Caveats.**
#
# - Each market's returns are in its own currency and on its own return basis
#   (the `return basis` column). A spread is a difference of two returns in the
#   same currency, which removes most, but not all, of the currency's effect.
# - Markets close on different holidays, so their weeks do not line up
#   perfectly. Compare shapes and summary numbers, not individual weeks.
# - Each market's publication covers its own window and freshness; read the
#   table before comparing the lines.

# %% [markdown]
# ## 7. Extension: PCA both ways (beyond the raw API)
#
# **Principal component analysis (PCA)** looks for the few directions that
# explain most of the variation shared by many series. Here the series are the
# books' weekly returns. We run it twice, on the same weeks:
#
# 1. on the **raw** long-only returns, where we expect one component to
#    dominate: the market, which every book carries once;
# 2. on the **style-minus-MARKET spreads**, where the market is gone and the
#    variation spreads over several components.
#
# Following the kit's rules, each series is standardised first (inside a
# scikit-learn `Pipeline`, so the scaling is part of the model), and we show
# the scree (the share of variance each component explains), the cumulative
# share, and the loadings. This is descriptive: it summarises how the books
# moved together over this window, nothing more.

# %%
both_ok = raw_aligned.index.intersection(spread_aligned.index) if SPREAD_USE else pd.DatetimeIndex([])
raw_frame = raw_aligned.loc[both_ok] if len(both_ok) else raw_aligned
spread_frame = spread_aligned.loc[both_ok] if len(both_ok) else spread_aligned
if raw_frame.shape[1] < 3 or len(raw_frame) < MIN_WEEKS:
    pca_ready = False
    note("PCA needs at least 3 books with enough aligned clean weeks; this response does not have them.")
else:
    pca_ready = True
    raw_ev, raw_load, raw_scores = pca_fit(raw_frame)
    spread_ok = spread_frame.shape[1] >= 3 and len(spread_frame) >= MIN_WEEKS
    if spread_ok:
        spread_ev, spread_load, spread_scores = pca_fit(spread_frame)
    print(f"PCA on {len(raw_frame)} weeks: raw books {list(raw_frame.columns)}"
          + (f"; spreads {list(spread_frame.columns)}." if spread_ok else "; too few spreads for a second PCA."))
    if "MARKET" in raw_frame.columns:
        print(f"Correlation of the raw PC1 score with the MARKET book's return: "
              f"{np.corrcoef(raw_scores['PC1'], raw_frame['MARKET'])[0, 1]:+.2f}")
    if spread_ok and "MARKET" in wide.columns:
        print(f"Correlation of the spreads' PC1 score with the MARKET book's return: "
              f"{np.corrcoef(spread_scores['PC1'], wide.loc[spread_frame.index, 'MARKET'])[0, 1]:+.2f}")

# %%
if not pca_ready:
    note("No PCA to chart.")
else:
    panels = [("Raw long-only books", raw_ev)] + ([("Style − MARKET spreads", spread_ev)] if spread_ok else [])
    fig = make_subplots(rows=1, cols=len(panels), shared_yaxes=True, horizontal_spacing=0.08,
                        subplot_titles=[p[0] for p in panels])
    fig.update_annotations(font=dict(size=13, color=INK))
    for c, (name, ev) in enumerate(panels, start=1):
        fig.add_trace(go.Bar(x=ev.index, y=ev, name="Share of variance (each component)", marker_color=SERIES[0],
                             showlegend=c == 1, hovertemplate="%{x}: %{y:.1%} of the variance<extra></extra>"),
                      row=1, col=c)
        fig.add_trace(go.Scatter(x=ev.index, y=ev.cumsum(), mode="lines+markers", name="Cumulative share",
                                 line=dict(color=INK, width=2), marker=dict(size=8, color=INK),
                                 showlegend=c == 1, hovertemplate="Up to %{x}: %{y:.1%}<extra></extra>"),
                      row=1, col=c)
    title = (f"On raw returns PC1 explains {raw_ev.iloc[0]:.0%} of the variance; on the spreads, "
             f"{spread_ev.iloc[0]:.0%}" if spread_ok else f"On raw returns PC1 explains {raw_ev.iloc[0]:.0%}")
    heading, top = chart_title(title, "Scree: share of the standardised variance explained by each principal "
                                      "component (bars) and the running total (line) · same weeks in both "
                                      "panels", extra_top=22)
    fig.update_layout(title=heading, height=top + 400, margin=dict(t=top, b=110),
                      legend=dict(BOTTOM_LEGEND))
    fig.update_yaxes(tickformat=".0%", range=[0, 1.05])
    fig.update_yaxes(title_text="Share of variance (%)", col=1)
    fig.update_xaxes(title_text="Principal component")
    fig.show()
    scree = pd.DataFrame({"raw: share": raw_ev, "raw: cumulative": raw_ev.cumsum()})
    if spread_ok:
        scree = scree.join(pd.DataFrame({"spreads: share": spread_ev, "spreads: cumulative": spread_ev.cumsum()}),
                           how="outer")
    display(scree.style.format("{:.1%}", na_rep="–"))

# %%
if not pca_ready:
    note("No loadings to chart.")
else:
    k = 3
    sets = [("Raw books", raw_load.iloc[:, :k])] + ([("Spreads", spread_load.iloc[:, :k])] if spread_ok else [])
    fig = make_subplots(rows=1, cols=len(sets), subplot_titles=[s[0] for s in sets], horizontal_spacing=0.2)
    fig.update_annotations(font=dict(size=13, color=INK))
    for c, (name, load) in enumerate(sets, start=1):
        z = load.to_numpy(dtype=float)
        fig.add_trace(go.Heatmap(z=z, x=load.columns.tolist(), y=load.index.tolist(),
                                 text=[[signed(v) for v in row] for row in z], texttemplate="%{text}",
                                 textfont=dict(size=12), colorscale=DIVERGING, zmin=-1, zmax=1, zmid=0,
                                 xgap=2, ygap=2, showscale=c == 1,
                                 colorbar=dict(title=dict(text="Loading"), tickvals=[-1, -0.5, 0, 0.5, 1],
                                               thickness=14, len=0.85),
                                 hovertemplate=f"{name} · %{{y}} on %{{x}}: %{{z:+.2f}}<extra></extra>"),
                      row=1, col=c)
    same_sign = bool((np.sign(raw_load["PC1"]) == np.sign(raw_load["PC1"].iloc[0])).all())
    spread_mixed = spread_ok and not bool((np.sign(spread_load["PC1"]) == np.sign(spread_load["PC1"].iloc[0])).all())
    title = ("Raw PC1 loads on every book with the same sign: it is the market" if same_sign else
             "Raw PC1 does not load on every book with the same sign")
    title += "; the spreads' PC1 mixes signs" if spread_mixed else ""
    heading, top = chart_title(title, f"Loadings of the first {k} components (standardised data) · blue = "
                                      "positive, red = negative · signs are arbitrary, flipped so each "
                                      "component's loadings sum to a positive number", extra_top=22)
    fig.update_layout(title=heading, height=top + 120 + 40 * max(len(s[1]) for s in sets),
                      margin=dict(t=top, l=120, b=60))
    fig.update_yaxes(autorange="reversed", showgrid=False, ticks="")
    fig.update_xaxes(showgrid=False, ticks="", side="bottom")
    fig.show()
    display(raw_load.iloc[:, :k].style.format(signed).set_caption("Raw books: loadings"))
    if spread_ok:
        display(spread_load.iloc[:, :k].style.format(signed).set_caption("Spreads: loadings"))

# %% [markdown]
# **How to read this.** In the raw panel the first bar is tall: one component
# explains most of the variance of all the books together. Its loadings have
# the same sign and similar size on every book, and its score moves almost
# one-for-one with the MARKET book's return (printed above). That component is
# the market. In the spread panel the bars are flatter: once the market is
# subtracted, no single direction dominates, and the loadings mix signs.
# Pairs of styles that load together on a component are styles whose spreads
# moved together (compare with the right-hand correlation matrix in section
# 4.11).
#
# **Caveats.**
#
# - Descriptive and in-sample: the components summarise this window's weekly
#   co-movement. They do not forecast returns and they are not trading signals.
# - Standardising gives every series the same weight. Without it, the most
#   volatile book would dominate the first component.
# - A component's sign is arbitrary, and its loadings can change with the
#   window and with which books pass the coverage rule.

# %% [markdown]
# ## Next steps
#
# - Change `MARKET` to `"cn"` or `"jp"` and compare the quoted return-basis
#   label first, then the exposure matrix and the spreads.
# - Set `FOCUS = "VALUE"` (or another style) to see its holdings, its twin and
#   its spread in every market.
# - Check the direction of a style yourself: join the `FOCUS` book's holdings to
#   notebook 01's screen on `ticker` and compare each holding's `size` score
#   with its `market_cap_usd`, or its `value` score with its `bp`.
# - Raise `WEEKS` to 520 for about ten years of history and watch how much the
#   95% intervals of section 4.10 narrow. Keep `HOLDINGS` small when you do:
#   ask only for what you use.
# - Set `TWIN = "s3b_ff_2x3_rp126"` to compare with the volatility-weighted twin.
# - Re-run the notebook later and compare the `publication_id` and the
#   freshness block with what you see today.
# - Notebook 05 (the ML lab) reads these weekly series too, as input for more
#   machine learning.
#
# ---
#
# *Research and education only. Nothing here is investment advice or a
# recommendation to buy or sell any security. The API describes these books as
# "Model candidates, not recommendations; no accuracy or performance claim is
# made." They are retrospective measurements, gross of costs, and past returns
# do not predict future ones. The endpoint name `realtime` elsewhere in the API
# names a current-session board, not a live-tick feed, and data cadence varies
# by market: always check the freshness fields.*

# %%
print(f"API requests made in this session: {api_calls_used()}")
