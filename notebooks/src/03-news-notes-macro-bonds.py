# %% [markdown]
# # 04 · News, notes, macro and bonds: headlines, research notes, the release calendar and the bond board
#
# Four SurgeFlow endpoints describe the *context* around stock prices. The
# **news** endpoint returns scored headlines with their tickers and a sentiment
# score. The **daily notes** are SurgeFlow's member research notes: one global
# note and one note per market, each split into sections. The **macro
# calendar** lists the economic releases due in the coming days, with the
# previous value, the economists' forecast and an importance tag. The **bond
# ETF** board tracks ten US credit and rates funds.
#
# You read each endpoint, clean it in the open and chart it honestly. Along the
# way you learn the basics of working with text: cleaning a headline, splitting
# it into words, counting them, and turning Markdown into plain words.
#
# **Live status.** When this notebook was last checked against the live API,
# the news feed was temporarily unavailable: it answered HTTP 200 with an error
# inside the body. The notebook reads news with `sf_try`, so a missing feed
# prints a short note and every other section still runs. The text-cleaning
# steps also run on the sample articles that the daily notes embed (section 4).
#
# **What you will learn**
#
# - How to handle an endpoint that is temporarily down (`sf_try`) and a result
#   that is empty, without crashing the notebook.
# - How to clean text: decode HTML entities, lowercase, strip URLs and
#   punctuation, drop stopwords and split into tokens. This includes Chinese and
#   Japanese text, which has no spaces between words.
# - How to render Markdown that an API sends, and how to count its words fairly
#   (link targets and table rules are not words).
# - How to parse lists that arrive as JSON text, timestamps that arrive in two
#   formats, and dates that arrive with or without a time.
# - How to use the query parameters `ticker`, `sentiment`, `market`,
#   `as_of_date` and `days`, and how to check what really came back.
# - What a macro **surprise** and an **expected change** are, and why you must
#   scale them before you compare two indicators.
# - How to read a bond ETF board: assets, fees, returns, yields and credit spreads.
# - Simple, honest statistics: confidence intervals for a mean and a share, rank
#   correlation, a sign test and a regression with robust (HC3) standard errors.
#
# **Endpoints used**
#
# | Method | Path | What it returns |
# |---|---|---|
# | GET | `/api/v1/markets/{market}/news` | The latest scored news articles with sentiment, tickers and keywords. Query: `ticker`, `sentiment`, `limit` (at most 50). Can be temporarily unavailable |
# | GET | `/api/v1/notes/daily` | The daily research notes (member content): a global note plus one note per market, split into sections. Query: `market` (default `all`), `as_of_date` |
# | GET | `/api/v1/macro/calendar` | One market's release calendar: upcoming releases with the previous value, the consensus forecast and an importance tag (actual and surprise fill in after a release). Query: `market`, `days` (at most 60, default 14) |
# | GET | `/api/v1/bond/etfs` | The bond ETF board: assets, expense ratio, NAV, last close, 1-day, 1-year and year-to-date returns, yields and credit spreads for ten US credit and rates funds |
#
# Extension 7.2 also reads `/api/v1/markets/{market}/sector`, which notebook 01
# teaches. Markets: `us`, `cn`, `jp`, `hk`. The notebook makes about 14
# requests (8 when the news feed is down); the free plan allows 2,000 a day and
# 180 a minute. It runs in about a minute.
#
# **Words used in this notebook**
#
# | Word | Meaning |
# |---|---|
# | token | One unit of text after splitting, usually a word |
# | stopword | A very common word ("the", "of", "and") that carries little meaning, so we drop it before counting |
# | bigram | Two neighbouring characters (or words) taken together as one token |
# | sentiment score | A model's reading of an article's tone, from −1 (negative) to +1 (positive) |
# | consensus | The typical forecast that economists publish before a data release |
# | previous | The value of the last release of the same indicator |
# | surprise | The actual number minus the consensus. Positive means "above forecast", which is not always good news |
# | expected change | The consensus minus the previous value: the move economists expect before the release |
# | AUM | Assets under management: the money invested in a fund |
# | NAV | Net asset value: what the bonds inside one fund share are worth |
# | expense ratio | The yearly fee a fund charges, as a percentage of the money you invest |
# | YTD | Year to date: since 1 January |
# | SEC yield | A standard 30-day yield that US bond funds report, after fees |
# | credit spread | The extra yield a bond pays over a US Treasury of similar maturity, in basis points (bp; 100 bp = 1 percentage point) |

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
# (`sf_get`, `sf_try`, `to_frame`, `dig`, `show_freshness`, ...) and the chart
# theme. You can run it without reading it.

# %% [helpers]

# %% [markdown]
# ## 2. Parameters
#
# Change `MARKET` and run the notebook again to read another market's news and
# market note. The notes and the macro calendar always cover all four markets,
# and the bond board is US only.

# %%
MARKET = "us"                    # news market and detail note: one of "us", "cn", "jp", "hk"
NEWS_LIMIT = 50                  # articles per news call: 1-50 (default 20). v1 has no offset, so you see the newest 50
NEWS_TICKER = None               # filter demo, native format: "NVDA" (us), "600519" (cn), "7203" (jp), "00700" (hk); None = most-mentioned
NEWS_SENTIMENT = "negative"      # filter demo: "positive", "negative" or "neutral"
NOTES_MARKET = "all"             # daily notes: "all" (global note + 4 market notes) or one of "us", "cn", "jp", "hk"
NOTES_DATE = None                # "YYYY-MM-DD" for an earlier day's notes; None = the latest
RENDER_ALL_NOTES = False         # 4.2 renders the global and MARKET notes only; True renders all five (member content)
MACRO_DAYS = 14                  # macro calendar window: 1-60 days ahead (default 14)
MACRO_MIN_IMPORTANCE = "medium"  # heatmap and events table: "high", "medium" or "low" (= every release)
TOP_N = 15                       # ranked charts show at most this many bars
COMPARE_MARKETS = True           # extension 7.1 reads the other three markets' news (3 requests, only if the feed is up)
JOIN_PRICES = True               # extension 7.2 reads the sector snapshot (1 request, about 1 MB for us, only if the feed is up)

# Facts the API does not send with these endpoints.
MARKET_TZ = {"us": "America/New_York", "cn": "Asia/Shanghai", "jp": "Asia/Tokyo", "hk": "Asia/Hong_Kong"}
SESSION_HOURS = {"us": ("09:30", "16:00"), "cn": ("09:30", "15:00"), "jp": ("09:00", "15:30"), "hk": ("09:30", "16:00")}

# Sentiment labels reuse the theme's diverging blue (positive) and red (negative), with grey for neutral.
SENTIMENT_COLORS = {"positive": DIVERGING[3][1], "neutral": MUTED, "negative": DIVERGING[1][1]}
SENTIMENT_ORDER = ["positive", "neutral", "negative"]
# Importance is ordered (low < medium < high), so it gets light-to-dark steps of the one sequential hue.
IMPORTANCE_ORDER = ["high", "medium", "low"]
IMPORTANCE_COLORS = {"low": SEQUENTIAL[1], "medium": SEQUENTIAL[3], "high": SEQUENTIAL[6]}
LEGEND_BELOW = dict(orientation="h", x=0, y=0.01, yref="container", yanchor="bottom")   # legend pinned to the figure's bottom edge

assert MARKET in MARKETS, f"MARKET must be one of {MARKETS}"
assert 1 <= NEWS_LIMIT <= 50, "NEWS_LIMIT must be between 1 and 50 (the API answers HTTP 422 otherwise)"
assert NEWS_SENTIMENT in SENTIMENT_ORDER, f"NEWS_SENTIMENT must be one of {SENTIMENT_ORDER}"
assert NOTES_MARKET in ("all", *MARKETS), "NOTES_MARKET must be 'all' or a market code"
assert 1 <= MACRO_DAYS <= 60, "MACRO_DAYS must be between 1 and 60"
assert MACRO_MIN_IMPORTANCE in IMPORTANCE_ORDER, f"MACRO_MIN_IMPORTANCE must be one of {IMPORTANCE_ORDER}"
MIN_IMPORTANCE_RANK = IMPORTANCE_ORDER.index(MACRO_MIN_IMPORTANCE)
TODAY = pd.Timestamp.now(tz="UTC")
print(f"News market: {MARKET_NAMES[MARKET]} ({MARKET}); exchange clock {MARKET_TZ[MARKET]}; "
      f"now {TODAY:%Y-%m-%d %H:%M} UTC.")

# %% [markdown]
# A few small utilities keep the later cells short. They are plain code, so read
# them once:
#
# - `pick` keeps exactly the documented columns. If one is missing it raises a
#   `KeyError`: that means the API contract changed, and you want to know. An
#   empty list is normal, so it returns an empty table instead of crashing.
# - `json_list` turns a list that arrived as JSON text (`'["AAPL", "MSFT"]'`)
#   into a real Python list.
# - `fmt_unit` writes a macro number with its unit (`4.4%`, `75K`, `−81.9B`,
#   `557.8 pts`). A signed change in a percentage reads in percentage points (`+0.1 pp`).
# - `markdown_text` and `word_count` turn Markdown into plain words and count
#   them; `quote_markdown` prepares an API's Markdown for display.
# - `money`, `shorten` and `wrap` make readable labels.
# - `chart_title` builds a chart's title (the takeaway) and a smaller grey
#   subtitle, wrapped to fit a notebook cell (`even_wrap` keeps the lines of
#   similar length), and returns the top margin they need. Plotly never wraps
#   a title by itself, so a long one runs off the right edge and hides its last
#   numbers. The subtitle is plain `<br>` plus a styled `<span>`, which works
#   on every Plotly 5 (Plotly's own `title.subtitle` needs version 5.23 or
#   later).
# - `mean_ci`, `wilson` and `spearman_ci` compute the confidence intervals used
#   in the statistics tables. A 95% confidence interval comes from a method
#   that, over many repeated samples, captures the true value 95% of the time.
#   A wide interval means "we do not know much yet".

# %%
import html
import json
import re
import textwrap
from collections import Counter

import statsmodels.api as sm
from plotly.subplots import make_subplots
from scipy import stats


def pick(raw: pd.DataFrame, columns: list) -> pd.DataFrame:
    """Keep the documented columns. Empty is normal; a missing column raises KeyError."""
    if raw.empty:
        return pd.DataFrame(columns=columns)
    return raw[columns].copy()


def json_list(value) -> list:
    """'["AAPL", "MSFT"]' -> ['AAPL', 'MSFT']. Some list fields arrive as JSON text, not as lists."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if value is None or value == "" or (isinstance(value, float) and np.isnan(value)):
        return []
    parsed = json.loads(value)                      # malformed JSON raises: a contract problem worth seeing
    if not isinstance(parsed, list):
        raise ValueError(f"Expected a JSON list, got {value!r}")
    return [str(v) for v in parsed]


UNIT_SUFFIX = {"%": "%", "K": "K", "M": "M", "B": "B", "T": "T", "Points": " pts"}


def fmt_unit(value, unit, signed: bool = False) -> str:
    """4.4 + '%' -> '4.4%'; 75 + 'K' -> '75K'. A signed % change reads in percentage points: '+0.1 pp'."""
    if pd.isna(value):
        return "–"
    text = format(float(value), "+,.6g" if signed else ",.6g").replace("-", "−")
    if unit is None or pd.isna(unit):
        return text                                   # no unit: an index level (PMI, sentiment survey)
    if signed and unit == "%":
        return f"{text} pp"
    return f"{text}{UNIT_SUFFIX.get(unit, ' ' + str(unit))}"


URL_RE = re.compile(r"https?://\S+|www\.\S+")
MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")        # [text](target)


def markdown_text(md) -> str:
    """Markdown -> plain text: keep each link's text, drop link targets and bare URLs."""
    return URL_RE.sub(" ", MD_LINK.sub(r"\1", str(md)))


def word_count(md) -> int:
    """Runs of letters or digits; '16.17%' and '$2.0B' count as one word. Markdown symbols are ignored."""
    return len(re.findall(r"\w+(?:[.,'’]\w+)*", markdown_text(md)))


def quote_markdown(md) -> str:
    """Demote headings three levels (so a note's '#' title cannot outrank this notebook's headings) and quote every line."""
    demoted = re.sub(r"^(#{1,3}) ", lambda m: "#" * (len(m.group(1)) + 3) + " ", str(md), flags=re.M)
    return "\n".join("> " + line for line in demoted.splitlines())


def money(value, digits: int = 2) -> str:
    """29304856609 -> '$29.30B'."""
    if pd.isna(value):
        return "n/a"
    sign, value = ("−" if value < 0 else ""), abs(float(value))
    for size, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= size:
            return f"{sign}${value / size:,.{digits}f}{unit}"
    return f"{sign}${value:,.0f}"


def shorten(text, width: int = 60) -> str:
    """Cut a long text to `width` characters, with an ellipsis."""
    text = str(text)
    return text if len(text) <= width else text[: width - 1] + "…"


def wrap(text, width: int = 28) -> str:
    """Break a long label over several lines (Plotly uses <br> for a new line)."""
    return "<br>".join(textwrap.wrap(str(text), width)) or str(text)


TITLE_CHARS, SUBTITLE_CHARS = 80, 110   # about 700 px each: fits a notebook cell (850 px or more)


def even_wrap(text: str, width: int) -> list:
    """Wrap into as few lines as `width` allows, then even out their lengths (no one-word last line)."""
    lines = textwrap.wrap(str(text), width, break_on_hyphens=False)
    if len(lines) < 2:
        return lines
    for w in range(int(np.ceil(len(str(text)) / len(lines))), width):   # narrowest width with the same line count
        even = textwrap.wrap(str(text), w, break_on_hyphens=False)
        if len(even) == len(lines):
            return even
    return lines


def chart_title(takeaway: str, subtitle: str = "") -> tuple:
    """(title dict, top margin in px): the takeaway wrapped at 80 characters, a grey 13 px subtitle at 110."""
    head = even_wrap(takeaway, TITLE_CHARS) or [str(takeaway)]
    sub = even_wrap(subtitle, SUBTITLE_CHARS)
    text = "<br>".join(head)
    if sub:
        text += f"<br><span style='font-size:13px;color:{INK_2}'>" + "<br>".join(sub) + "</span>"
    top = 40 + 22 * (len(head) + len(sub))     # each line is 22 px (1.3 × the 17 px title font), plus padding
    return dict(text=text, y=1, yanchor="top", pad=dict(t=16, l=8)), top


def mean_ci(values, level: float = 0.95):
    """Mean with a t-based confidence interval. Returns (n, mean, low, high)."""
    v = pd.Series(values, dtype=float).dropna()
    n = len(v)
    if n < 2:
        return n, (float(v.mean()) if n else np.nan), np.nan, np.nan
    half = stats.t.ppf(0.5 + level / 2, n - 1) * v.std(ddof=1) / np.sqrt(n)
    return n, float(v.mean()), float(v.mean() - half), float(v.mean() + half)


def wilson(k: int, n: int, level: float = 0.95):
    """Wilson score interval for a share k/n. Better than p ± 2·se when n is small or p is near 0 or 1."""
    if n == 0:
        return np.nan, np.nan
    z, p = stats.norm.ppf(0.5 + level / 2), k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def spearman_ci(x: pd.Series, y: pd.Series, level: float = 0.95, min_n: int = 8):
    """Spearman's rho with a Fisher-z confidence interval (Bonett & Wright, 2000). Returns (n, rho, low, high)."""
    ok = x.notna() & y.notna()
    n = int(ok.sum())
    if n < min_n or x[ok].nunique() < 2 or y[ok].nunique() < 2:
        return n, np.nan, np.nan, np.nan
    rho = float(stats.spearmanr(x[ok], y[ok]).statistic)
    z, se = np.arctanh(np.clip(rho, -0.9999, 0.9999)), np.sqrt((1 + rho ** 2 / 2) / (n - 3))
    q = stats.norm.ppf(0.5 + level / 2)
    return n, rho, float(np.tanh(z - q * se)), float(np.tanh(z + q * se))

# %% [markdown]
# ## 3. News: scored headlines
#
# **What it is for.** The news endpoint returns the latest articles for one
# market. Each article comes with its headline, publisher, the tickers it
# mentions, a few keyword tags and a **sentiment score** from −1 (negative) to
# +1 (positive). Use it to see what the market is talking about and in what
# tone.
#
# Three query parameters shape the answer:
#
# - `limit`: how many articles, 1 to 50 (default 20). There is no `offset`, so
#   you can only ever see the newest 50 articles that match.
# - `ticker`: only articles that mention this ticker, in the market's own
#   format (`NVDA`, `600519`, `7203`, `00700`).
# - `sentiment`: only `positive`, `negative` or `neutral` articles.
#
# Sources differ by market. The US feed is English media. China is Chinese
# media. Japan and Hong Kong mix official company **disclosures** (filings) with
# local media.
#
# **When the feed is down.** The feed can be temporarily unavailable. It then
# answers HTTP 200 with `{"ok": true, "data": {"ok": false, "error": {...}}}`:
# the request worked, but the news service behind it did not. `sf_get` turns
# that inner error into a `SurgeFlowError`; `sf_try` catches it, prints a
# short note and returns `None`. Every news cell below checks for articles and
# prints a sentence instead of a chart when there are none. Sections 4 to 6 do
# not depend on the news.

# %%
news_payload = sf_try(f"/api/v1/markets/{MARKET}/news", limit=NEWS_LIMIT)
news_ok = news_payload is not None


def sent(value, fmt: str = "{}") -> str:
    """Format an optional field, or say plainly that the API did not send it."""
    return "not sent" if value is None else fmt.format(value)


if news_ok:
    show_freshness(news_payload, "News:")
    news_meta = news_payload["data"]
    coverage, method = news_meta.get("coverage") or {}, news_meta.get("methodology") or {}
    display(pd.DataFrame({"value": [
        sent(news_meta.get("count")), sent(news_meta.get("total_matching"), "{:,}"), sent(news_meta.get("offset")),
        sent(coverage.get("total_articles"), "{:,}"), sent(coverage.get("scored_pct"), "{}%"),
        ", ".join(coverage.get("languages") or []) or "not sent", sent(coverage.get("latest_date")),
        sent(coverage.get("sentiment_latest_date")), sent(method.get("source")), sent(method.get("sentiment_source")),
        sent(method.get("content_license")),
    ]}, index=pd.Index(["articles returned (count)", "articles matching (total_matching)", "offset", "corpus size",
                        "share of corpus scored", "languages", "latest article date", "latest scored date",
                        "source", "sentiment model", "licence"], name="field")))
else:
    news_meta, coverage, method = {}, {}, {}
    display(Markdown(f"> **No news this run.** The {MARKET_NAMES[MARKET]} feed is unavailable, so the news charts below "
                     "print a short note instead. Run the notebook again later: the cells need no change when "
                     "articles come back. Section 4 shows real articles from the daily notes in the meantime."))

# %% [markdown]
# **What is known about the shape.** No working response from this endpoint
# has been seen yet. The article fields are *inferred* from the sample articles
# that the daily notes embed (section 4.3), which carry the keys the news
# endpoint is documented to send. Check them when articles come back. So the
# cleaning step below insists only on the fields this notebook actually uses;
# a change there still raises, as a contract change should. The descriptive
# extras (`description`, `article_url`, `provider`, ...) are read with
# `reindex` and simply come back empty if one is renamed. The envelope fields
# above (`total_matching`, `coverage`, `methodology`) are read with `.get` and
# show "not sent" if one is missing. The documented shape has no `as_of` or
# `data_quality` fields; if a working response does carry them,
# `show_freshness` prints them. Until then the coverage dates are your
# freshness check.
#
# **Raw preview.** This is the data exactly as it arrived, before any cleaning.
# Look at `tickers` and `keywords`: they look like lists, but they are text.

# %%
news_raw = to_frame(news_payload, "news") if news_ok else pd.DataFrame()
print(f"{news_raw.shape[0]} rows x {news_raw.shape[1]} columns")
if news_raw.empty:
    display(Markdown("> No articles to preview. A feed that is down, a quiet feed or a narrow filter can do that."))
else:
    print("type of the first 'tickers' value:", type(news_raw["tickers"].iloc[0]).__name__)
news_raw.head()

# %% [markdown]
# ### 3.1 Cleaning the articles
#
# We put the cleaning in one visible function, because the filter demos,
# section 4 and extension 7.1 reuse it. Each step is plain pandas:
#
# 1. **Keep the columns.** `pick` raises if a field the notebook uses
#    (`NEWS_REQUIRED`) is missing. The extras (`NEWS_OPTIONAL`) are read with
#    `reindex`, and the audit counts any that did not arrive.
# 2. **De-duplicate on `article_id`.** It is the natural key: one row per article.
# 3. **Parse timestamps as UTC.** Most rows look like `2026-10-06T16:32:39Z`. Rows
#    from the FMP provider look like `2026-10-06 11:55:02`, with no time zone.
#    `format="mixed"` reads both. The field reference says to treat the bare
#    ones as UTC, and we count them so you know how many there are.
# 4. **Coerce numbers** with `pd.to_numeric(errors="coerce")`. Anything that is
#    not a number becomes `NaN` (pandas' marker for a missing value).
# 5. **Decode HTML entities.** Live headlines can contain `&#39;` for an
#    apostrophe and `&amp;` for "&". `html.unescape` turns them back into
#    characters.
# 6. **Parse the JSON lists.** `tickers` and `keywords` are JSON text, so
#    `json_list` turns them into lists. Japan and Hong Kong put a marker in
#    `keywords` (`ticker_matched` or `no_ticker_match`). It says whether a ticker
#    was found, not what the article is about, so we remove it.
# 7. **Set a NaN policy.** An article counts as *scored* only if
#    `sentiment_available` is true and the score lies between −1 and 1.
#    Unscored articles stay in the table (they still mention tickers), but every
#    sentiment statistic leaves them out, and the audit counts them.
#
# One pandas detail: we test booleans with `.eq(True)`, not with
# `lambda v: v is True`. In recent pandas a boolean column hands `numpy.bool`
# values to `.map`, and `numpy.bool(True) is True` is `False`.

# %%
# Inferred article shape (see above). The notebook uses the required fields; the optional ones are only previewed.
NEWS_REQUIRED = ["article_id", "published_utc", "title", "publisher_name", "tickers", "ticker_count", "keywords",
                 "sentiment_score", "sentiment_label", "sentiment_available", "language"]
NEWS_OPTIONAL = ["description", "article_url", "provider", "source_family", "article_type", "content_available"]
NEWS_COLS = NEWS_REQUIRED + NEWS_OPTIONAL
NEWS_DERIVED = ["published", "ticker_list", "keyword_list", "scored"]
KEYWORD_MARKERS = {"ticker_matched", "no_ticker_match"}   # jp/hk markers, not topics


def clean_news(raw: pd.DataFrame, label: str, report: bool = True) -> pd.DataFrame:
    """Documented columns -> one row per article -> UTC times, numbers, decoded text, parsed lists."""
    if raw.empty:                                                                 # empty is normal
        if report:
            display(Markdown(f"> Nothing to clean for {label}: no articles came back."))
        return pd.DataFrame(columns=NEWS_COLS + NEWS_DERIVED)
    df = pd.concat([pick(raw, NEWS_REQUIRED), raw.reindex(columns=NEWS_OPTIONAL)], axis=1)   # step 1
    not_sent = [c for c in NEWS_OPTIONAL if c not in raw.columns]
    n_raw = len(df)
    df["article_id"] = df["article_id"].astype(str)
    df = df.drop_duplicates(subset="article_id", keep="first").copy()             # step 2
    stamps = df["published_utc"].astype(str)
    no_zone = ~stamps.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True)
    df["published"] = pd.to_datetime(df["published_utc"], utc=True, format="mixed", errors="coerce")   # step 3
    df["sentiment_score"] = pd.to_numeric(df["sentiment_score"], errors="coerce")                   # step 4
    df["ticker_count"] = pd.to_numeric(df["ticker_count"], errors="coerce")
    raw_titles = df["title"].fillna("").astype(str)
    df["title"] = raw_titles.map(html.unescape)                                                     # step 5
    n_decoded = int((raw_titles != df["title"]).sum())          # count now: sorting below changes the row order
    df["sentiment_label"] = df["sentiment_label"].astype(str).str.lower()
    df["ticker_list"] = df["tickers"].map(json_list)                                                # step 6
    df["keyword_list"] = df["keywords"].map(json_list).map(lambda ks: [k for k in ks if k not in KEYWORD_MARKERS])
    df["scored"] = df["sentiment_available"].eq(True) & df["sentiment_score"].between(-1, 1)        # step 7
    df = df.sort_values("published").reset_index(drop=True)
    if report:
        n_foreign = sum(":" in t for ts in df["ticker_list"] for t in ts)
        audit = pd.DataFrame({"result": [
            ", ".join(not_sent) or "none",
            f"{n_raw} -> {len(df)} ({n_raw - len(df)} duplicates removed)",
            int(no_zone.sum()), int(df["published"].isna().sum()),
            n_decoded,
            int(df["sentiment_score"].isna().sum()), int((~df["scored"]).sum()),
            int((df["ticker_count"] != df["ticker_list"].map(len)).sum()), n_foreign,
        ]}, index=pd.Index([
            "optional fields not sent (left empty)",
            "rows -> after de-duplication on article_id",
            "timestamps without a time zone (read as UTC)", "timestamps that failed to parse (NaN)",
            "titles with HTML entities decoded", "sentiment scores missing or not numbers (NaN)",
            "articles not scored (left out of sentiment statistics)",
            "rows where ticker_count differs from the parsed list", "foreign-listed symbols (contain ':')",
        ], name=f"cleaning audit: {label}"))
        display(audit)
    return df


news = clean_news(news_raw, f"{MARKET} news")

# %% [markdown]
# **Labels versus scores.** Each article also has a `sentiment_label`. The model
# assigns it; it is **not** a fixed cut-off on the score. The table shows the
# score range inside each label. Where two ranges overlap (for example −0.1
# appears under both "negative" and "neutral"), the label is carrying extra
# information. So use the label as given, and do not rebuild it from the score.

# %%
if news.empty or not news["scored"].any():
    display(Markdown("> No scored articles, so there is no label table."))
else:
    label_table = (news[news["scored"]].groupby("sentiment_label")["sentiment_score"]
                   .agg(articles="size", lowest="min", highest="max", mean="mean")
                   .reindex(SENTIMENT_ORDER))
    display(label_table.style.format({"lowest": "{:+.1f}", "highest": "{:+.1f}", "mean": "{:+.2f}", "articles": "{:.0f}"},
                                     na_rep="–"))

# %% [markdown]
# ### 3.2 Cleaning the text: from headline to tokens
#
# Computers cannot count "topics", but they can count words. To count words
# fairly, every headline goes through the same steps:
#
# 1. **Decode and lowercase**, so "Stocks" and "stocks" are the same word.
# 2. **Strip URLs**, which are links, not words.
# 3. **Strip punctuation and digits.** `[^\w\s]` matches any character that is
#    neither a letter/digit nor a space, in any script, so Chinese "，" and
#    Japanese "：" go too. Numbers such as "2.9%" mean little on their own.
# 4. **Tokenise**: split the text into tokens. English separates words with
#    spaces. **Chinese and Japanese do not.** A proper word splitter needs a
#    dictionary (`jieba` for Chinese, `fugashi` for Japanese). A simple,
#    dictionary-free choice is **character bigrams**: overlapping pairs of
#    characters, so "资金观望" becomes "资金", "金观" and "观望". Some pairs are
#    real words and some are not, but real words repeat across headlines and
#    rise to the top. For Japanese we drop pairs that contain hiragana: hiragana
#    mostly writes grammar (particles such as の and に, verb endings), while
#    names and topics are written in kanji and katakana.
# 5. **Drop stopwords and one-letter tokens.** The list is written out below so
#    you can see and edit it. It includes company suffixes (inc, corp, ltd),
#    which are part of names, not news. Note that it also drops "up", "down" and
#    "not". That is fine for counting topics, but you would keep them for a
#    sentiment model.

# %%
CJK = "぀-ヿ㐀-䶿一-鿿豈-﫿"   # Japanese kana + Chinese/Japanese characters
RUN_RE = re.compile(f"[{CJK}]+|[^{CJK}\\s]+")                    # a run of CJK characters, or a run of anything else
HIRAGANA = re.compile("[぀-ゟ]")                   # Japanese hiragana
STOPWORDS = set("""
a about above after again against all also am an and any are as at be because been before being below between
both but by can could did do does doing down during each few for from further had has have having he her here
hers him his how i if in into is it its itself just me more most my no nor not now of off on once only or other
our out over own same she should so some such than that the their them then there these they this those through
to too under until up very was we were what when where which while who whom why will with would you your
inc corp corporation co ltd plc llc lp group holdings company companies sa ag nv se
""".split())


def clean_text(text) -> str:
    """Decode, lowercase, strip URLs, punctuation (any script) and digits, squeeze spaces."""
    text = html.unescape(str(text)).lower()
    text = URL_RE.sub(" ", text)
    text = re.sub(r"[^\w\s]|_", " ", text)
    text = re.sub(r"\d+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenise(text) -> list:
    """Words for spaced scripts; overlapping character pairs (bigrams) for Chinese and Japanese."""
    tokens = []
    for run in RUN_RE.findall(clean_text(text)):
        if re.match(f"[{CJK}]", run):
            pairs = [run[i:i + 2] for i in range(len(run) - 1)] or [run]
            tokens += [p for p in pairs if not HIRAGANA.search(p)]
        elif len(run) > 1 and run not in STOPWORDS:
            tokens.append(run)
    return tokens


news["clean_title"] = news["title"].map(clean_text)
news["tokens"] = news["title"].map(tokenise)
if news.empty:
    display(Markdown("> No headlines to clean. The same two functions run on the notes' sample articles in section 4."))
else:
    example = news.sort_values("published", ascending=False).head(5)
    display(pd.DataFrame({"headline": example["title"].map(lambda t: shorten(t, 70)),
                          "cleaned": example["clean_title"].map(lambda t: shorten(t, 70)),
                          "tokens": example["tokens"].map(lambda ts: " · ".join(ts[:10]))}).style.hide(axis="index"))
print(f"{len(STOPWORDS)} stopwords; {sum(map(len, news['tokens'])):,} tokens from {len(news)} headlines.")

# %% [markdown]
# ### Chart: sentiment over time
#
# Each dot is one article, placed at its publication time and its sentiment
# score. Colour shows the model's label. The black line is a **rolling mean**:
# the average score of the nearest few articles, which shows the drift of the
# tone without the noise of single articles. The grey bands mark the exchange's
# regular trading hours on weekdays, on the exchange's own clock.

# %%
scored = news[news["scored"]].copy() if not news.empty else news
if scored.empty:
    display(Markdown("> No scored articles came back, so there is no tone to chart."))
else:
    tz = MARKET_TZ[MARKET]
    scored["local"] = scored["published"].dt.tz_convert(tz).dt.tz_localize(None)   # plot on the exchange clock
    window = int(np.clip(len(scored) // 4, 3, 10))
    scored["rolling_mean"] = scored["sentiment_score"].rolling(window, center=True, min_periods=max(2, window // 2)).mean()
    n, mean, lo, hi = mean_ci(scored["sentiment_score"])
    mix = scored["sentiment_label"].value_counts().reindex(SENTIMENT_ORDER, fill_value=0)
    trend = stats.spearmanr(scored["published"].rank(), scored["sentiment_score"]) if n >= 8 else None
    first, last = scored["local"].min(), scored["local"].max()
    span_hours = (last - first).total_seconds() / 3600
    pad = pd.Timedelta(hours=max(span_hours * 0.03, 0.05))

    fig = go.Figure()
    open_, close_ = SESSION_HOURS[MARKET]
    for day in pd.date_range(first.normalize(), last.normalize(), freq="D"):
        start, end = day + pd.Timedelta(f"{open_}:00"), day + pd.Timedelta(f"{close_}:00")
        start, end = max(start, first - pad), min(end, last + pad)
        if day.weekday() < 5 and start < end:
            fig.add_vrect(x0=start, x1=end, fillcolor=GRID, opacity=0.5, layer="below", line_width=0)
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name="Regular session (weekdays)",
                             marker=dict(symbol="square", size=12, color=GRID)))
    for label in ["negative", "neutral", "positive"]:
        part = scored[scored["sentiment_label"] == label]
        if part.empty:
            continue
        fig.add_trace(go.Scatter(
            x=part["local"], y=part["sentiment_score"], mode="markers", name=f"{label.title()} ({len(part)})",
            marker=dict(size=10, color=SENTIMENT_COLORS[label], opacity=0.85, line=dict(width=1, color=SURFACE)),
            customdata=np.column_stack([part["title"].map(lambda t: wrap(shorten(t, 110), 55)), part["publisher_name"],
                                        part["ticker_list"].map(lambda ts: ", ".join(ts[:6]) or "none")]),
            hovertemplate=("<b>%{customdata[0]}</b><br>%{x|%a %d %b %H:%M} local · %{customdata[1]}"
                           "<br>Score %{y:+.1f} · tickers: %{customdata[2]}<extra></extra>")))
    fig.add_trace(go.Scatter(x=scored["local"], y=scored["rolling_mean"], mode="lines", name=f"Rolling mean ({window} articles)",
                             line=dict(color=INK, width=2.5), hovertemplate="Rolling mean %{y:+.2f}<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=AXIS, width=1))
    MIN_FOR_CI = 5                                   # below this, a t-interval is wider than the −1..+1 scale itself
    tone = ("too thin to call" if n < MIN_FOR_CI else "negative" if hi < 0 else "positive" if lo > 0
            else "neutral on balance")
    ci_text = f"95% CI {lo:+.2f} to {hi:+.2f}" if n >= MIN_FOR_CI else "too few articles for an interval"
    span_text = f"{span_hours:.1f} hours" if span_hours < 48 else f"{span_hours / 24:.1f} days"
    fig.update_xaxes(type="date", title_text=f"Published (exchange local time, {tz})", range=[first - pad, last + pad])
    fig.update_yaxes(title_text="Sentiment score (−1 to +1)", range=[-1.08, 1.08], dtick=0.5, tickformat="+.1f",
                     zeroline=False)
    title_spec, title_px = chart_title(
        f"{MARKET_NAMES[MARKET]} news tone is {tone}: mean score {mean:+.2f} across {n} articles",
        f"{ci_text} · {mix['positive']} positive, {mix['neutral']} neutral, {mix['negative']} negative · "
        f"the newest {n} articles span {span_text}")
    fig.update_layout(title=title_spec, height=title_px + 135 + 280, margin=dict(t=title_px, b=135), legend=LEGEND_BELOW)
    fig.show()

    trend_text = (f"Spearman ρ between time and score = {trend.statistic:+.2f} (p = {trend.pvalue:.2f})"
                  if trend is not None else "too few articles to test a trend")
    display(pd.DataFrame({"value": [n, f"{mean:+.3f}", ci_text, f"{scored['sentiment_score'].median():+.2f}",
                                    f"{(mix['positive'] - mix['negative']) / n:+.2f}", trend_text]},
                         index=pd.Index(["scored articles", "mean score", "95% CI of the mean", "median score",
                                         "net tone: (positive − negative) / all", "time trend"], name="statistic")))
    display(scored[["local", "sentiment_label", "sentiment_score", "rolling_mean", "publisher_name", "title"]]
            .iloc[::-1].style.format({"local": "{:%a %d %b %H:%M}", "sentiment_score": "{:+.1f}",
                                               "rolling_mean": "{:+.2f}", "title": lambda t: shorten(t, 70)},
                                              na_rep="–").hide(axis="index"))

# %% [markdown]
# **How to read this.** Dots above the grey zero line are positive articles;
# dots below are negative. The black line is the local average tone: if it
# sits above zero for a stretch, the news flow leaned positive then. The title
# gives the overall mean and its 95% confidence interval. If the interval
# includes 0, the tone is "neutral on balance": we cannot tell it apart from
# zero. The first table gives the numbers, including a **time trend**: Spearman's
# ρ (rho) between publication order and score. A ρ near 0 means the tone did
# not drift. The second table lists every plotted article, newest first.
#
# **Caveats.**
#
# - Only the newest `NEWS_LIMIT` articles are visible (there is no offset). On
#   a busy US day, 50 articles can cover less than an hour, so this is a
#   snapshot of the latest flow, not a day's tone.
# - Scores move in steps of 0.1, and one story is often written up several
#   times. Repeats are not independent, so the real uncertainty is wider than
#   the interval shows.
# - Session bands use regular weekday hours. They ignore lunch breaks and
#   exchange holidays (China's Golden Week, for example).

# %% [markdown]
# ### Chart: which tickers the news talks about
#
# One article can mention several tickers. We **explode** the ticker lists, so
# each (article, ticker) pair becomes one row, then count articles per ticker
# and average their scores. Symbols with an exchange prefix (such as
# `TSX:SHOP`, a Toronto listing, or `X:USDCUSD`, a crypto pair) are not stocks of
# this market, so we set them aside and count them.

# %%
BY_TICKER_COLS = ["ticker", "articles", "scored_articles", "mean_sentiment", "lowest", "highest", "latest_headline"]
if news.empty:
    by_ticker = pd.DataFrame(columns=BY_TICKER_COLS)
    display(Markdown("> No articles, so no tickers to count."))
else:
    mentions = (news[["article_id", "ticker_list", "sentiment_score", "scored", "title"]]
                .explode("ticker_list").rename(columns={"ticker_list": "ticker"}).dropna(subset=["ticker"]))
    mentions["ticker"] = mentions["ticker"].astype(str).str.strip()
    foreign = mentions["ticker"].str.contains(":", regex=False)
    print(f"{len(mentions)} (article, ticker) pairs; {int(foreign.sum())} use a foreign or non-stock symbol and are set aside.")
    mentions = mentions[~foreign].drop_duplicates(subset=["article_id", "ticker"])
    mentions["score_if_scored"] = mentions["sentiment_score"].where(mentions["scored"])
    by_ticker = (mentions.groupby("ticker")
                 .agg(articles=("article_id", "nunique"), scored_articles=("score_if_scored", "count"),
                      mean_sentiment=("score_if_scored", "mean"), lowest=("score_if_scored", "min"),
                      highest=("score_if_scored", "max"), latest_headline=("title", "last"))
                 .reset_index().sort_values(["articles", "ticker"], ascending=[False, True]).reset_index(drop=True))

if news.empty:
    pass
elif by_ticker.empty:
    display(Markdown("> No article in this batch mentions a ticker of this market."))
else:
    top = by_ticker.head(TOP_N).iloc[::-1]          # reversed so the most-mentioned ticker sits on top
    R = max(0.1, float(np.ceil(top["mean_sentiment"].abs().max() * 10) / 10)) if top["mean_sentiment"].notna().any() else 1
    lead = by_ticker.iloc[0]
    has_score = top["mean_sentiment"].notna()
    fig = go.Figure()
    if has_score.any():                               # scored tickers: diverging colour = mean sentiment
        part = top[has_score]
        fig.add_trace(go.Bar(
            x=part["articles"], y=part["ticker"], orientation="h", name="Scored (colour = mean sentiment)",
            marker=dict(color=part["mean_sentiment"], colorscale=DIVERGING, cmin=-R, cmax=R, cmid=0,
                        line=dict(width=1, color=AXIS),
                        colorbar=dict(title=dict(text="Mean<br>sentiment"), tickformat="+.1f", thickness=14, len=0.8)),
            text=[f"{m:+.2f}" for m in part["mean_sentiment"]], textposition="outside",
            textfont=dict(size=11, color=INK_2), cliponaxis=False,
            customdata=np.column_stack([part["scored_articles"], part["lowest"], part["highest"],
                                        part["latest_headline"].map(lambda t: wrap(shorten(t, 100), 50))]),
            hovertemplate=("<b>%{y}</b>: %{x} article(s), %{customdata[0]} scored<br>Mean sentiment %{text}"
                           " (range %{customdata[1]:+.1f} to %{customdata[2]:+.1f})<br>Latest: %{customdata[3]}<extra></extra>")))
    if (~has_score).any():                            # unscored tickers: hatched, so they never pass for a mean of 0
        part = top[~has_score]
        fig.add_trace(go.Bar(
            x=part["articles"], y=part["ticker"], orientation="h", name="Unscored (no sentiment)",
            marker=dict(color=SURFACE, line=dict(width=1.5, color=MUTED), pattern=dict(shape="/", fgcolor=MUTED, size=6)),
            text=["unscored"] * len(part), textposition="outside", textfont=dict(size=11, color=MUTED), cliponaxis=False,
            customdata=part["latest_headline"].map(lambda t: wrap(shorten(t, 100), 50)),
            hovertemplate="<b>%{y}</b>: %{x} article(s), none scored<br>Latest: %{customdata}<extra></extra>"))
    fig.update_xaxes(title_text="Articles that mention the ticker", dtick=1 if top["articles"].max() <= 10 else None,
                     range=[0, top["articles"].max() * 1.18])
    fig.update_yaxes(title_text=None, type="category", categoryorder="array", categoryarray=list(top["ticker"]))
    mean_text = f"mean sentiment {lead['mean_sentiment']:+.2f}" if pd.notna(lead["mean_sentiment"]) else "unscored"
    n_tied = int((by_ticker["articles"] == lead["articles"]).sum())
    headline = (f"{lead['ticker']} is the most-mentioned ticker: {lead['articles']} of {len(news)} articles, {mean_text}"
                if n_tied == 1 else
                f"No ticker dominates: {n_tied} tickers tie at {lead['articles']} article(s) each")
    n_unscored = int((~has_score).sum())
    title_spec, title_px = chart_title(
        headline, f"Top {len(top)} of {len(by_ticker)} tickers · bar length = article count · colour and label = mean "
                  "sentiment of those articles (blue positive, red negative)"
                  + (f" · hatched = {n_unscored} with no scored article" if n_unscored else ""))
    bottom = 110 if n_unscored else 50
    fig.update_layout(title=title_spec, height=title_px + bottom + max(220, 26 * len(top) + 50), barmode="overlay",
                      showlegend=bool(n_unscored), margin=dict(t=title_px, r=90, b=bottom), legend=LEGEND_BELOW)
    fig.show()
    display(by_ticker.head(TOP_N).style.format({"mean_sentiment": "{:+.2f}", "lowest": "{:+.1f}", "highest": "{:+.1f}",
                                                "latest_headline": lambda t: shorten(t, 60)}, na_rep="–")
            .hide(axis="index"))

# %% [markdown]
# **How to read this.** Longer bars mean more articles mention the ticker. The
# colour (and the number at the end of each bar) is the average sentiment of
# those articles: blue leans positive, red leans negative, pale grey is close to
# zero. The colour range is symmetric around zero, so equal shades mean equal
# distance from neutral. A hatched, uncoloured bar is a ticker whose articles
# have no score at all; it is not the same as a mean of 0. The table lists the
# same numbers plus the lowest and highest score.
#
# **Caveats.**
#
# - Ties are ordered alphabetically. Many tickers have only one article, and a
#   mean of one article is just that article's score, so do not rank tickers
#   by colour.
# - The score belongs to the **article**, not to each ticker in it. An article
#   about Apple that also names Microsoft gives Microsoft Apple's score. (In
#   Japan and Hong Kong the model scores "the financial implication for the
#   tagged company", which is closer to per-ticker.)
# - Tickers are text. Keep `"00700"` with its zeros, and never cast tickers to
#   integers.

# %% [markdown]
# ### Chart: the words in the headlines
#
# Now we count tokens. Two choices make the count fair:
#
# - **De-duplicate headlines first.** The same headline often appears several
#   times (syndication, or a story updated during the day). We keep one copy
#   of each cleaned headline, so one story cannot dominate the count.
# - **Count articles, not occurrences.** A token counts once per headline. This
#   is called **document frequency**: "in how many headlines does this word
#   appear?"
#
# We use headlines, not descriptions. Every article has one, and descriptions
# often repeat the headline or carry publisher boilerplate. Next to the words,
# the right panel counts the provider's own `keywords` tags (with generic tags
# such as "news" removed). Many tags are vendor categories ("analyst ratings")
# rather than words from the text.

# %%
GENERIC_TAGS = {"news", "general"}          # vendor tags that nearly every article carries


def doc_frequency(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    """Headlines containing each token (once per headline), with the mean score of those headlines."""
    long = frame[["article_id", "sentiment_score", "scored", column]].copy()
    long[column] = long[column].map(lambda items: sorted(set(items)))
    long = long.explode(column).dropna(subset=[column]).rename(columns={column: "token"})
    if long.empty:
        return pd.DataFrame(columns=["token", "headlines", "share", "mean_sentiment"])
    out = (long.assign(score=long["sentiment_score"].where(long["scored"]))
           .groupby("token").agg(headlines=("article_id", "nunique"), mean_sentiment=("score", "mean")).reset_index())
    out["share"] = out["headlines"] / max(len(frame), 1)
    return out.sort_values(["headlines", "token"], ascending=[False, True]).reset_index(drop=True)[
        ["token", "headlines", "share", "mean_sentiment"]]


if news.empty:
    display(Markdown("> No headlines, so no words to count."))
else:
    unique_heads = news[news["clean_title"] != ""].drop_duplicates(subset="clean_title", keep="last")
    print(f"{len(news)} headlines -> {len(unique_heads)} after removing {len(news) - len(unique_heads)} repeated headlines.")
    words = doc_frequency(unique_heads, "tokens")
    tags = doc_frequency(unique_heads.assign(tag_list=unique_heads["keyword_list"].map(
        lambda ks: [k.lower() for k in ks if k.lower() not in GENERIC_TAGS])), "tag_list")
    panels = [("Words in headlines (our tokeniser)", words)] + ([("Provider keyword tags", tags)] if not tags.empty else [])
    if tags.empty:
        print("This market's articles carry no keyword tags (China sends '[]'; Japan and Hong Kong send only markers).")

    if words.empty:
        display(Markdown("> No tokens to count."))
    else:
        fig = make_subplots(rows=1, cols=len(panels), horizontal_spacing=0.2,
                            subplot_titles=[f"{name}" for name, _ in panels])
        for col, (name, table) in enumerate(panels, start=1):
            part = table.head(TOP_N).iloc[::-1]
            fig.add_trace(go.Bar(
                x=part["headlines"], y=part["token"], orientation="h", name=name, showlegend=False,
                marker=dict(color=MARKET_COLORS[MARKET], opacity=1.0 if col == 1 else 0.6),
                customdata=np.column_stack([part["share"], part["mean_sentiment"]]),
                hovertemplate=("<b>%{y}</b>: in %{x} headlines (%{customdata[0]:.0%})"
                               "<br>Mean sentiment of those headlines %{customdata[1]:+.2f}<extra></extra>")),
                row=1, col=col)
            fig.update_yaxes(type="category", tickfont=dict(size=12), row=1, col=col)
            fig.update_xaxes(title_text="Headlines containing it", row=1, col=col)
        lead = words.iloc[0]
        leaders = words.loc[words["headlines"] == lead["headlines"], "token"].tolist()
        named = ", ".join(f"“{t}”" for t in leaders[:3]) + (f" and {len(leaders) - 3} more" if len(leaders) > 3 else "")
        verb = "is the most common headline word" if len(leaders) == 1 else "tie as the most common headline words"
        title_spec, title_px = chart_title(
            f"{named} {verb}: in {lead['headlines']} of {len(unique_heads)} distinct headlines ({lead['share']:.0%})",
            f"{MARKET_NAMES[MARKET]} · top {min(TOP_N, len(words))} tokens by document frequency · stopwords, digits "
            "and repeated headlines removed")
        top_px = title_px + 24                      # room for the panel titles
        fig.update_layout(title=title_spec, height=top_px + 50 + max(250, 24 * min(TOP_N, len(words)) + 50),
                          margin=dict(t=top_px, b=50))
        fig.show()
        for name, table in panels:                   # table twins: one per panel
            display(table.head(TOP_N).rename(columns={"token": name}).style
                    .format({"share": "{:.0%}", "mean_sentiment": "{:+.2f}"}, na_rep="–").hide(axis="index"))

# %% [markdown]
# **How to read this.** Each bar counts the distinct headlines that contain the
# token. A long bar is a recurring theme in the latest news flow. Hover to see
# the share of headlines and their average tone: a frequent word with a red
# tone (for example "lowers", in a run of price-target cuts) tells you more than
# the count alone. The tables list the top tokens and, when the articles carry
# them, the top provider tags, with the same numbers.
#
# **Caveats.**
#
# - Word counts describe *what is written*, not *what matters*. Headline styles
#   repeat ("shares rise", "price target"), so stock phrases rank high.
# - For Chinese and Japanese, bigrams are an approximation: some pairs cross a
#   word boundary and some names are split. A longer word shows up as a family
#   of overlapping pairs with the same count: 売買代金 ("trading value") becomes
#   売買, 買代 and 代金. Use a real word splitter for serious work.
# - Fixture headlines (offline mode) are synthetic templates, so their word
#   counts are repetitive by design.

# %% [markdown]
# ### 3.3 Query parameters: filter by ticker and by sentiment
#
# The documentation says both filters run **on the server**, over the whole
# corpus. That has not been seen in a working live response yet, so treat it
# as the documented behaviour, not a checked fact. If it holds, it matters
# because of the 50-article cap: asking for `ticker=AVGO` reaches the newest 50
# articles *about AVGO*, even if they are days old and would never appear in
# the general feed. `total_matching` (when sent) tells you how many articles
# match in the whole corpus. The two filters can be combined in one call
# (`ticker=..., sentiment=...`).
#
# Good practice: **check that a filter was applied**, then apply it locally as
# well. The check protects you from typos (an unknown ticker can return
# nothing) and from tools that ignore parameters. The offline mock used to test
# this notebook ignores every filter, for example. Both calls use `sf_try`
# and are skipped when the feed is down.

# %%
focus = NEWS_TICKER or (by_ticker["ticker"].iloc[0] if not by_ticker.empty else None)
ticker_news = pd.DataFrame(columns=NEWS_COLS + NEWS_DERIVED)
if not news_ok:
    display(Markdown("> Skipped: the news feed is unavailable, so there is nothing to filter."))
elif focus is None:
    display(Markdown("> No ticker to filter on: the latest articles mention none. Set `NEWS_TICKER` and re-run."))
else:
    ticker_payload = sf_try(f"/api/v1/markets/{MARKET}/news", ticker=focus, limit=NEWS_LIMIT)
    if ticker_payload is not None:
        show_freshness(ticker_payload, f"News with ticker={focus}:")
        ticker_news = clean_news(to_frame(ticker_payload, "news"), f"ticker={focus}", report=False)
        tagged = ticker_news["ticker_list"].map(lambda ts: focus in ts).astype(bool)
        if ticker_news.empty:
            verdict = f"No article mentions {focus}. Check the ticker format for this market."
        elif tagged.all():
            verdict = f"Filter applied by the server: all {len(ticker_news)} articles tag {focus}."
        else:
            verdict = (f"{int((~tagged).sum())} of {len(ticker_news)} articles do not tag {focus}, so the filter was not "
                       "applied here (the offline mock ignores filters). We keep only the tagged ones.")
        ticker_news = ticker_news[tagged]
        matching = dig(ticker_payload, "data", "total_matching")
        display(Markdown(f"> {verdict} Matching articles in the whole corpus: **{sent(matching, '{:,}')}**."))
        if not ticker_news.empty:
            n, mean, lo, hi = mean_ci(ticker_news.loc[ticker_news["scored"], "sentiment_score"])
            first, last = ticker_news["published"].min(), ticker_news["published"].max()
            ci_text = f"95% CI {lo:+.2f} to {hi:+.2f}" if n >= 5 else f"only {n} scored, too few for an interval"
            print(f"{len(ticker_news)} articles about {focus} from {first:%Y-%m-%d %H:%M} to {last:%Y-%m-%d %H:%M} UTC; "
                  f"mean sentiment {mean:+.2f} ({ci_text}).")
            display(ticker_news.sort_values("published", ascending=False)
                    [["published", "sentiment_label", "sentiment_score", "publisher_name", "title"]].head(10)
                    .style.format({"published": "{:%Y-%m-%d %H:%M}", "sentiment_score": "{:+.1f}",
                                   "title": lambda t: shorten(t, 80)}).hide(axis="index"))

# %% [markdown]
# Now the `sentiment` filter. We ask for the newest `NEWS_SENTIMENT` articles
# and check their labels in the same way.

# %%
if not news_ok:
    display(Markdown("> Skipped: the news feed is unavailable."))
else:
    mood_payload = sf_try(f"/api/v1/markets/{MARKET}/news", sentiment=NEWS_SENTIMENT, limit=NEWS_LIMIT)
    mood_news = (clean_news(to_frame(mood_payload, "news"), f"sentiment={NEWS_SENTIMENT}", report=False)
                 if mood_payload is not None else pd.DataFrame())
    if mood_payload is not None:
        show_freshness(mood_payload, f"News with sentiment={NEWS_SENTIMENT}:")
    if mood_news.empty:
        display(Markdown(f"> No {NEWS_SENTIMENT} articles came back right now."))
    else:
        match = mood_news["sentiment_label"] == NEWS_SENTIMENT
        if match.all():
            verdict = f"Filter applied by the server: all {len(mood_news)} articles are labelled {NEWS_SENTIMENT}."
        else:
            verdict = (f"{int((~match).sum())} of {len(mood_news)} articles carry another label, so the filter was not "
                       "applied here (the offline mock ignores filters). We keep only the matching ones.")
        mood_news = mood_news[match]
        matching = dig(mood_payload, "data", "total_matching")
        display(Markdown(f"> {verdict} Matching articles in the whole corpus: **{sent(matching, '{:,}')}**."))
        if not mood_news.empty:
            span = mood_news["published"].max() - mood_news["published"].min()
            print(f"The newest {len(mood_news)} {NEWS_SENTIMENT} articles span {span.total_seconds() / 3600:.1f} hours; "
                  f"scores from {mood_news['sentiment_score'].min():+.1f} to {mood_news['sentiment_score'].max():+.1f}.")
            display(mood_news.sort_values("sentiment_score", ascending=NEWS_SENTIMENT != "positive")
                    [["published", "sentiment_score", "ticker_list", "publisher_name", "title"]].head(10)
                    .style.format({"published": "{:%Y-%m-%d %H:%M}", "sentiment_score": "{:+.1f}",
                                   "ticker_list": lambda ts: ", ".join(ts[:5]) or "–", "title": lambda t: shorten(t, 80)})
                    .hide(axis="index"))

# %% [markdown]
# **How to read this.** The first table holds the newest articles about one
# ticker; the second holds the strongest-scored articles with one label. The
# line above each table says whether the server applied the filter and how many
# articles match in the whole corpus.
#
# **Caveats for the news section.**
#
# - Sentiment models differ by market (see `sentiment_source`), so a +0.3 in
#   Tokyo and a +0.3 in New York are not the same measurement.
# - Article links point to the publisher (`article_url` can be empty); the API
#   ships the title and a short description, not the full text.
# - Offline, the fixture headlines and links (`example.com`) are synthetic.

# %% [markdown]
# ## 4. Daily notes: SurgeFlow's member research notes
#
# **What it is for.** Each day SurgeFlow writes **Daily Notes**: a short global
# note (FX, bonds, a key event, news and the four markets' leaders) and one
# note per market. A market note has eight or nine sections, each named by its
# `tab` and `label`: price momentum, turnover surge, market structure, whales,
# fundamental valuation, macro risk, the ML market map, the AI Analyst Team
# (US only) and news & sentiment. Every section has a `headline`; depending on
# the tab it adds `lines` (extra sentences), `top_rows` (the stocks behind a
# candidate headline), `articles` (news samples) or `scores`. Each note also
# carries `copy_markdown`, a ready-to-paste Markdown version with tables.
#
# **The AI Analyst Team section reports on SurgeFlow's AI research committee,
# which is paused.** Its two endpoints (`/api/v1/ai/ratings` and
# `/api/v1/ai/grade-book`) are retired (HTTP 410) and this kit no longer calls
# them. Do not read that section as current research.
#
# **Member content.** On surgeflows.capital the Daily Notes sit behind the
# member sign-in. Through the API you need a key with the `notes` scope (free
# keys include it today). Read them in your own notebook, but do not republish
# them or paste them into anything you publish. Once this section has run, the
# notebook's outputs contain member content: clear all outputs (in Colab,
# Edit > Clear all outputs) before you share, commit or screenshot it. To
# keep that content small, section 4.2 renders only the global note and the
# `MARKET` note unless you set `RENDER_ALL_NOTES = True`.
#
# Parameters: `market` (`all` by default, which returns the global note plus
# the four market notes; one market returns one note) and `as_of_date`
# (`YYYY-MM-DD`, an earlier day). The call uses `sf_try`: if the notes cannot be
# read, the section prints a note and the notebook carries on.

# %%
notes_payload = sf_try("/api/v1/notes/daily", market=NOTES_MARKET, as_of_date=NOTES_DATE)
notes_ok = notes_payload is not None
RATING_SCALE = (1, 5)
if notes_ok:
    show_freshness(notes_payload, "Daily notes:")
    notes_meta = notes_payload["data"]
    contract = notes_meta["agent_rating_contract"]
    RATING_SCALE = (dig(contract, "scale", "min", default=1), dig(contract, "scale", "max", default=5))
    print(f"methodology_version: {notes_meta['methodology_version']} · agent ratings: {contract['status']} "
          f"(scale {RATING_SCALE[0]} to {RATING_SCALE[1]}; top-down = {', '.join(contract.get('top_down') or [])}; "
          f"bottom-up = {', '.join(contract.get('bottom_up') or [])})")
    display(Markdown(f"*{notes_meta['disclosure']}*"))
else:
    notes_meta = {}
    display(Markdown("> If the message above says HTTP 401 or 403, your key lacks the `notes` scope (notebook 00, "
                     "section 5, lists your scopes). Otherwise the notes are briefly unavailable. Section 4 prints "
                     "short notes instead of tables; sections 5 and 6 do not need it."))

# %% [markdown]
# **Raw preview.** One row per note. `sections` is still a list of
# dictionaries inside each row; the cleaning step unpacks it.

# %%
notes_raw = to_frame(notes_payload, "notes") if notes_ok else pd.DataFrame()
if notes_raw.empty and notes_ok:
    display(Markdown("> The notes list is empty. Notes are written after the close; try again later or set `NOTES_DATE`."))
notes_raw.head()

# %% [markdown]
# ### 4.1 Cleaning the notes
#
# 1. **Keep the documented columns** and lowercase `market` (`all` marks the
#    global note).
# 2. **De-duplicate on `market`**, the natural key of a note within one day.
# 3. **Parse `generated_at` as UTC** and the dates as dates.
# 4. **Unpack the sections** into a tidy table: one row per (note, section).
#    `tab`, `label`, `ok` and `headline` are in every section, so we demand
#    them. The other keys depend on the tab (`lines`, `top_rows`, `articles`,
#    `as_of_date`, `error`, ...), so we read them with `.get` and an empty
#    default.
# 5. **Count words fairly.** `copy_markdown` is full of links such as
#    `[NVDA](https://...)` and table rules such as `| ---: |`. `markdown_text`
#    keeps a link's text ("NVDA") and drops its target, so a URL does not count
#    as five words. A "word" is then a run of letters or digits: "16.17%" counts
#    as one, and so does a run of Chinese characters.
#
# A section has its **own** `as_of_date`. A note written this morning about
# yesterday's session is one weekday old, which is normal. Macro risk is a
# monthly series, and a market on holiday (China in early October) shows its
# last session, so some sections are older. `age_days` counts calendar days and
# `age_weekdays` counts weekdays (`np.busday_count`); the audit lists the
# sections more than one weekday older than their note.

# %%
NOTE_COLS = ["scope", "market", "title", "as_of_date", "generated_at", "website_url", "copy_markdown", "sections",
             "source_status.section_count", "source_status.ok_sections"]   # to_frame flattens nested dicts into dotted columns
SECTION_COLS = ["market", "tab", "label", "ok", "headline", "lines", "section_as_of", "error", "top_rows", "articles",
                "note_as_of"]
NOTE_ORDER = ["all", *MARKETS]
NOTE_NAMES = {"all": "Global", **MARKET_NAMES}

notes = pick(notes_raw, NOTE_COLS)
notes["market"] = notes["market"].astype(str).str.lower()
n_before = len(notes)
notes = notes.drop_duplicates(subset="market", keep="first").copy()
notes["generated_at"] = pd.to_datetime(notes["generated_at"], utc=True, errors="coerce")
notes["as_of_date"] = pd.to_datetime(notes["as_of_date"], errors="coerce")
notes["order"] = notes["market"].map({m: i for i, m in enumerate(NOTE_ORDER)})
notes = notes.sort_values("order").reset_index(drop=True)
notes["words"] = notes["copy_markdown"].map(word_count).astype(int)

section_rows = []
for note in notes.itertuples():
    for s in note.sections:
        section_rows.append({"market": note.market, "tab": s["tab"], "label": s["label"], "ok": bool(s["ok"]),
                             "headline": s["headline"], "lines": list(s.get("lines") or []),
                             "section_as_of": s.get("as_of_date"), "error": s.get("error"),
                             "top_rows": s.get("top_rows") or [], "articles": s.get("articles") or [],
                             "note_as_of": note.as_of_date})
sections = pd.DataFrame(section_rows, columns=SECTION_COLS)
sections = sections.drop_duplicates(subset=["market", "tab"], keep="first").reset_index(drop=True)
sections["section_as_of"] = pd.to_datetime(sections["section_as_of"], errors="coerce")
sections["note_as_of"] = pd.to_datetime(sections["note_as_of"], errors="coerce")
sections["age_days"] = (sections["note_as_of"] - sections["section_as_of"]).dt.days
sections["age_weekdays"] = [np.busday_count(str(a.date()), str(b.date())) if pd.notna(a) and pd.notna(b) else np.nan
                            for a, b in zip(sections["section_as_of"], sections["note_as_of"])]
sections["words"] = [word_count(h) + sum(word_count(x) for x in lines)
                     for h, lines in zip(sections["headline"], sections["lines"])]
print(f"{n_before} notes -> {len(notes)} after de-duplication; {len(sections)} sections; "
      f"{int((~sections['ok'].astype(bool)).sum())} not available; {int(sections['section_as_of'].isna().sum())} "
      "without their own date (they share the note's date).")
if sections.empty:
    display(Markdown("> No sections to audit."))
else:
    aged = sections[sections["age_weekdays"].gt(1) | ~sections["ok"].astype(bool)]
    print(f"{len(aged)} of {len(sections)} sections are more than one weekday older than their note, or not available:")
    if aged.empty:
        display(Markdown("> None: every dated section covers the last session before its note."))
    else:
        display(aged[["market", "label", "ok", "section_as_of", "age_days", "age_weekdays", "error", "headline"]]
                .style.format({"section_as_of": lambda d: f"{d:%Y-%m-%d}" if pd.notna(d) else "–", "age_days": "{:.0f}",
                               "age_weekdays": "{:.0f}", "headline": lambda t: shorten(t, 70)}, na_rep="–")
                .hide(axis="index"))

# %% [markdown]
# An `ok: false` section would appear in the same table, with an `error` code
# instead of a headline you can rely on.
#
# ### 4.2 The notes, rendered as Markdown
#
# `copy_markdown` is plain Markdown, so `display(Markdown(...))` renders it as
# formatted text, tables included. Two small text operations make it fit this
# notebook:
#
# - `quote_markdown` **demotes the headings** by three levels. The note's title
#   starts with `#`, the largest heading, which would otherwise outrank this
#   notebook's own section titles.
# - It then **quotes every line** (`> `), so you can tell the API's text from
#   this notebook's prose.
#
# The caption under each note gives its word count and a link to the same note
# on the website. By default only the global note and the `MARKET` note are
# rendered (`RENDER_ALL_NOTES`); every note's sections still feed the tables
# and charts below.

# %%
to_render = notes if RENDER_ALL_NOTES else notes[notes["market"].isin(["all", MARKET])]
if notes.empty:
    display(Markdown("> No notes to render."))
elif to_render.empty:
    display(Markdown(f"> Neither the global note nor the {MARKET} note is in this response (`NOTES_MARKET` = "
                     f"{NOTES_MARKET!r}). Set `RENDER_ALL_NOTES = True` to render the notes that did come back."))
for note in to_render.itertuples():
    ok = sections.loc[sections["market"] == note.market, "ok"].astype(bool)
    has_ai = (sections.loc[sections["market"] == note.market, "tab"] == "ai_agents").any()
    display(Markdown(quote_markdown(note.copy_markdown)))
    display(Markdown(f"*{NOTE_NAMES.get(note.market, note.market)} note · **{note.words} words** (tables included) · "
                     f"{int(ok.sum())} of {len(ok)} sections available · generated {note.generated_at:%Y-%m-%d %H:%M} UTC · "
                     f"[open on the website]({note.website_url})*"
                     + (" · *its AI Analyst Team section reports on the AI research committee, which is paused*"
                        if has_ai else "")))
if not notes.empty:
    hidden = len(notes) - len(to_render)
    display(Markdown((f"> {hidden} other note(s) not rendered (`RENDER_ALL_NOTES = False`). " if hidden else "> ")
                     + "**This notebook's outputs now contain member content.** Clear all outputs (in Colab, "
                       "Edit > Clear all outputs) before you share, commit or screenshot it."))

# %% [markdown]
# `copy_markdown` is the polished text. The `sections` hold the same content
# as data, plus things the text leaves out: each section's own date, extra
# `lines`, and the `top_rows` behind each candidate table with an **agent
# rating**. Here is the `MARKET` note as a tidy table, one row per section.

# %%
own = sections[sections["market"] == MARKET]
if own.empty:
    display(Markdown(f"> There is no {MARKET} note in this response (`NOTES_MARKET` = {NOTES_MARKET!r})."))
else:
    display(own.assign(lines_n=own["lines"].map(len), top_rows_n=own["top_rows"].map(len),
                       articles_n=own["articles"].map(len))
            [["label", "tab", "ok", "section_as_of", "age_days", "words", "lines_n", "top_rows_n", "articles_n", "headline"]]
            .rename(columns={"lines_n": "lines", "top_rows_n": "top rows", "articles_n": "articles"})
            .style.format({"section_as_of": lambda d: f"{d:%Y-%m-%d}" if pd.notna(d) else "–", "age_days": "{:.0f}",
                           "headline": lambda t: shorten(t, 80)}, na_rep="–").hide(axis="index"))

# %% [markdown]
# **The candidate rows.** The price momentum, turnover surge and fundamental
# valuation sections list up to five candidates each in `top_rows`. Their
# returns are **fractions** (0.05 = +5%). Each candidate also carries an
# `agent_rating`: six evidence lenses scored from 1 to 5, averaged into a
# top-down score (macro, sentiment, factor), a bottom-up score (technical,
# fundamental, risk) and an overall score. A rating is `partial` when a lens
# is missing. Empty `top_rows` is normal: no stock passed that tab's filter.
#
# **A unit check you can do for free.** The note prints the same candidates
# in its Markdown tables (1D, 5D and YTD columns). We parse those tables back
# into data (`note_table_rows`) and ask, for every row, whether the printed YTD
# equals `ytd_return` × 100 (a fraction) or `ytd_return` itself (already a
# percent). When one field is printed both ways, its unit is in doubt, and the
# column `ytd_as_printed` says so. The red rows are the ones to distrust: for
# them the table shows both readings (`+420% or +4.2%?`) next to the stored
# number (`ytd_return_raw`), instead of picking one. We also print where the
# two readings split by size, which hints at the cause.

# %%
CANDIDATE_TABS = ["ma_breakthrough", "turnover", "fundamental"]
TOP_COLS = ["ticker", "name", "sector", "change_pct", "return_5d", "ytd_return"]
RATING_COLS = ["agent_rating.overall", "agent_rating.top_down", "agent_rating.bottom_up", "agent_rating.state"]
candidates = [pd.json_normalize(s.top_rows).assign(market=s.market, tab=s.label)
              for s in sections.itertuples() if s.tab in CANDIDATE_TABS and s.top_rows]
top_rows = pd.concat(candidates, ignore_index=True) if candidates else pd.DataFrame(columns=["market", "tab", *TOP_COLS])
rating_cols = [c for c in RATING_COLS if c in top_rows.columns]   # absent when the rating contract is 'unavailable'
top_rows = pick(top_rows, ["market", "tab", *TOP_COLS, *rating_cols])
top_rows["ticker"] = top_rows["ticker"].astype(str)
for col in ["change_pct", "return_5d", "ytd_return", *[c for c in rating_cols if c != "agent_rating.state"]]:
    top_rows[col] = pd.to_numeric(top_rows[col], errors="coerce")
top_rows = top_rows.drop_duplicates(subset=["market", "tab", "ticker"]).reset_index(drop=True)


def note_table_rows(md) -> dict:
    """Markdown tables in a note -> {ticker: {column header: cell text}}, keyed by the first link in each row."""
    rows, header = {}, None
    for line in str(md).splitlines():
        if not line.startswith("|"):
            header = None                                          # a table ended
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = cells                                         # first row of a table = column headers
        elif not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):   # skip the | --- | rule under the headers
            link = MD_LINK.search(line)
            if link and len(cells) == len(header):
                rows.setdefault(link.group(1), {}).update(zip(header, cells))
    return rows


printed = {m: note_table_rows(md) for m, md in zip(notes["market"], notes["copy_markdown"])}


def ytd_as_printed(row) -> str:
    """How the note's own table prints this row's ytd_return: as a fraction (x100) or as an already-percent number."""
    text = printed.get(row["market"], {}).get(row["ticker"], {}).get("YTD")
    if text is None or pd.isna(row["ytd_return"]):
        return "not in the note's table"
    shown = float(text.replace("%", "").replace("+", "").replace("−", "-").replace(",", ""))
    if abs(shown - 100 * row["ytd_return"]) <= 0.05 + 1e-9:
        return "fraction"
    if abs(shown - row["ytd_return"]) <= 0.05 + 1e-9:
        return "percent?"
    return "differs"


top_rows["ytd_as_printed"] = top_rows.apply(ytd_as_printed, axis=1) if not top_rows.empty else pd.Series(dtype=str)
DOUBTFUL = {"percent?", "differs"}


def ytd_text(value, reading) -> str:
    """The year-to-date return as text; both readings when the note prints the field the other way."""
    if pd.isna(value):
        return "–"
    if reading in DOUBTFUL:
        return f"{100 * value:+,.0f}% or {value:+.1f}%?"
    return f"{100 * value:+,.0f}%"


top_rows["ytd"] = [ytd_text(v, r) for v, r in zip(top_rows["ytd_return"], top_rows["ytd_as_printed"])]
readings = top_rows["ytd_as_printed"].value_counts()
mine = top_rows[top_rows["market"] == MARKET]
if mine.empty:
    display(Markdown(f"> No candidate rows for {MARKET_NAMES[MARKET]} in these notes."))
else:
    print(f"{len(top_rows)} candidate rows across {top_rows['market'].nunique()} market notes; "
          f"{len(mine)} for {MARKET_NAMES[MARKET]}. Ratings run from {RATING_SCALE[0]} to {RATING_SCALE[1]}.")
    print("How each note's own table prints ytd_return: "
          + ", ".join(f"{k} {v}" for k, v in readings.items()) + ".")
    display(mine.drop(columns="market").rename(columns=lambda c: c.replace("agent_rating.", "rating_"))
            .rename(columns={"ytd_return": "ytd_return_raw"}).style.format(
        {"change_pct": "{:+.1%}", "return_5d": "{:+.1%}", "ytd_return_raw": "{:+.4g}", "rating_overall": "{:.2f}",
         "rating_top_down": "{:.2f}", "rating_bottom_up": "{:.2f}"}, na_rep="–")
        .apply(lambda col: [f"color: {DIVERGING[1][1]}; font-weight: 600" if v in DOUBTFUL else "" for v in col],
               subset=["ytd_as_printed", "ytd"]).hide(axis="index"))
if readings.get("percent?", 0):
    as_fraction = top_rows.loc[top_rows["ytd_as_printed"].eq("fraction"), "ytd_return"].abs()
    as_is = top_rows.loc[top_rows["ytd_as_printed"].eq("percent?"), "ytd_return"].abs()
    clean_split = not as_fraction.empty and as_fraction.max() < as_is.min()
    split_text = (f"The two readings split cleanly by size: every |ytd_return| up to {as_fraction.max():.2f} is printed "
                  f"× 100, and every one from {as_is.min():.2f} up is printed as it is. That points to a display "
                  "threshold in the note's Markdown (a rule such as \"a number this large must already be a percent\"), "
                  "rather than a field stored in mixed units. It is still a guess, not a documented fact."
                  if clean_split else
                  "The two readings do not split cleanly by size, so the field itself may be stored in mixed units.")
    print(f"Magnitude check: largest |ytd_return| printed as a fraction = "
          f"{as_fraction.max() if not as_fraction.empty else float('nan'):.2f}; smallest printed as it is = {as_is.min():.2f}.")
    display(Markdown(
        f"> **Unit check: `ytd_return` is ambiguous for {readings['percent?']} of {len(top_rows)} rows.** The same number "
        "is stored twice in each note: in `top_rows` and in the `copy_markdown` table. For most rows the table prints "
        "`ytd_return` × 100 (a stored 1.25 shows as +125%), so the field is a fraction. For the rows marked "
        "`percent?` it prints the stored value as it is (a stored 4.2 shows as +4.2%). One field cannot be both, so for "
        f"those rows the API alone cannot tell you whether the year-to-date return is +4.2% or +420%. {split_text} "
        "The table above shows both readings for those rows. Do not average `ytd_return` across rows until the unit "
        "is settled."))

# %% [markdown]
# ### 4.3 The articles inside the notes
#
# Each market note's news section embeds its three newest `articles`, with the
# keys that the news endpoint is documented to send (the endpoint itself has
# not been seen working yet, so these samples are where its article shape was
# inferred from). That gives us real text to practise on, in English, Chinese
# and Japanese, even when the news feed is down. We run the same `clean_news` and `tokenise` functions from section 3
# on them. Nothing new is fetched.

# %%
note_frames = []
for s in sections[(sections["tab"] == "news") & sections["market"].isin(MARKETS)].itertuples():
    if s.articles:
        note_frames.append(clean_news(pd.DataFrame(s.articles), f"{s.market} note articles", report=False)
                           .assign(market=s.market))
note_articles = pd.concat(note_frames, ignore_index=True) if note_frames else pd.DataFrame()
if note_articles.empty:
    display(Markdown("> The notes embed no articles today."))
else:
    note_articles["tokens"] = note_articles["title"].map(tokenise)
    print(f"{len(note_articles)} articles from {note_articles['market'].nunique()} market notes; languages: "
          f"{', '.join(sorted(note_articles['language'].astype(str).unique()))}; "
          f"{int(note_articles['scored'].sum())} scored.")
    display(note_articles[["market", "published", "language", "publisher_name", "sentiment_label", "sentiment_score",
                           "title", "tokens"]]
            .style.format({"published": "{:%Y-%m-%d %H:%M}", "sentiment_score": "{:+.1f}",
                           "title": lambda t: shorten(t, 60), "tokens": lambda ts: " · ".join(ts[:8]) or "–"},
                          na_rep="–").hide(axis="index"))

# %%
note_scored = note_articles[note_articles["scored"]].copy() if not note_articles.empty else note_articles
if note_scored.empty:
    display(Markdown("> No scored sample articles to chart."))
else:
    order = [m for m in MARKETS if (note_scored["market"] == m).any()]
    jitter = np.random.default_rng(4).uniform(-0.17, 0.17, len(note_scored))   # fixed seed: the same picture every run
    note_scored["y"] = note_scored["market"].map({m: i for i, m in enumerate(order)}) + jitter
    mix = note_scored["sentiment_label"].value_counts().reindex(SENTIMENT_ORDER, fill_value=0)
    fig = go.Figure()
    for label in SENTIMENT_ORDER:
        part = note_scored[note_scored["sentiment_label"] == label]
        if part.empty:
            continue
        fig.add_trace(go.Scatter(
            x=part["sentiment_score"], y=part["y"], mode="markers", name=f"{label.title()} ({len(part)})",
            marker=dict(size=13, color=SENTIMENT_COLORS[label], line=dict(width=2, color=SURFACE)),
            customdata=np.column_stack([part["market"].map(MARKET_NAMES), part["title"].map(lambda t: wrap(shorten(t, 90), 45)),
                                        part["publisher_name"]]),
            hovertemplate="<b>%{customdata[0]}</b> · %{customdata[2]}<br>%{customdata[1]}<br>Score %{x:+.1f}<extra></extra>"))
    fig.add_vline(x=0, line=dict(color=AXIS, width=1))
    fig.update_xaxes(range=[-1.05, 1.05], dtick=0.25, tickformat="+.2f", title_text="Sentiment score (−1 to +1)")
    fig.update_yaxes(tickvals=list(range(len(order))), ticktext=[MARKET_NAMES[m] for m in order],
                     range=[-0.6, len(order) - 0.4], showgrid=False, zeroline=False, ticks="")
    title_spec, title_px = chart_title(
        f"The notes' {len(note_scored)} sample articles: {mix['positive']} positive, {mix['neutral']} neutral, "
        f"{mix['negative']} negative",
        "The three newest articles in each market note · equal scores are spread vertically · far too few articles "
        "to compare the markets' mood")
    fig.update_layout(title=title_spec, height=title_px + 110 + max(150, 60 + 60 * len(order)),
                      margin=dict(t=title_px, b=110), legend=LEGEND_BELOW)
    fig.show()

# %% [markdown]
# **How to read this.** Each dot is one article, placed at its sentiment score
# and coloured by the model's label. The small vertical spread inside a row
# only keeps equal scores from hiding each other. The table above lists the
# same articles with their cleaned tokens: English words for the US, character
# bigrams for China, Japan and Hong Kong.
#
# **Caveats.** Three articles per market is a sample of the format, not a
# measure of mood: use section 3 (and extension 7.1) for that when the feed is
# up. The notes picked the *newest* articles, so they say nothing about the
# day's tone.
#
# ### Chart: how long each section is, note by note
#
# A heatmap with one column per note and one row per section. The number in
# each cell is the section's word count (headline plus extra lines; the
# candidate tables in `copy_markdown` are not counted here), and each column
# header adds up the cells below it. An empty cell means that note has no such
# section (the global note has its own five); "n/a" means the section exists
# but is not available today.

# %%
if sections.empty:
    display(Markdown("> No sections to chart."))
else:
    rank = sections["market"].map({m: i for i, m in enumerate(NOTE_ORDER)}).fillna(len(NOTE_ORDER))
    tab_order = list(dict.fromkeys(sections.assign(rank=rank).sort_values("rank", kind="stable")["tab"]))
    tab_label = sections.drop_duplicates("tab", keep="last").set_index("tab")["label"]   # market notes' label wins
    note_cols = [m for m in NOTE_ORDER if m in set(sections["market"])]
    grid = sections.pivot(index="tab", columns="market", values="words").reindex(index=tab_order, columns=note_cols)
    okgrid = sections.pivot(index="tab", columns="market", values="ok").reindex(index=tab_order, columns=note_cols)
    z = grid.where(okgrid.eq(True))                              # unavailable sections get no colour
    text = np.where(okgrid.eq(False), "n/a", np.where(z.notna(), z.fillna(0).astype(int).astype(str), ""))
    totals = sections.groupby("market")["words"].sum()              # the header adds up the cells below it
    fig = go.Figure(go.Heatmap(
        z=z.to_numpy(dtype=float), x=[f"{NOTE_NAMES.get(m, m)}<br>{int(totals.get(m, 0))} words" for m in note_cols],
        y=[tab_label[t] for t in tab_order], text=text, texttemplate="%{text}", textfont=dict(size=11),
        colorscale=[[i / 6, c] for i, c in enumerate(SEQUENTIAL)], zmin=0, xgap=3, ygap=3, hoverongaps=False,
        colorbar=dict(title=dict(text="Words"), thickness=14, len=0.8),
        hovertemplate="%{x}<br>Section: %{y}<br>%{z:.0f} words<extra></extra>"))
    for i, j in zip(*np.where(okgrid.eq(False).to_numpy())):      # outline the sections that are not available
        fig.add_shape(type="rect", x0=j - 0.47, x1=j + 0.47, y0=i - 0.45, y1=i + 0.45,
                      line=dict(color=AXIS, width=1), fillcolor="rgba(0,0,0,0)")
    fig.update_yaxes(autorange="reversed", ticks="", showgrid=False, title_text=None)
    fig.update_xaxes(side="top", ticks="", showgrid=False, title_text=None)
    longest = notes.loc[notes["words"].idxmax()]
    wordiest = sections.loc[sections["words"].idxmax()]
    n_na = int((~sections["ok"].astype(bool)).sum())
    headline = (f"The {NOTE_NAMES.get(longest['market'], longest['market'])} note is the longest at {longest['words']} "
                f"words (tables included); the wordiest section is {NOTE_NAMES.get(wordiest['market'], wordiest['market'])} "
                f"{tab_label[wordiest['tab']]} ({wordiest['words']} words)")
    title_spec, title_px = chart_title(
        headline, f"Daily notes as of {notes['as_of_date'].max():%Y-%m-%d} · cell = words in the section's headline "
                  "and lines · header = sum of its column (whole-note counts, tables included, are in the table "
                  f"below) · {n_na} section(s) not available today")
    top_px = title_px + 45                          # room for the two-line column headers on top
    fig.update_layout(title=title_spec, height=top_px + 30 + 34 * len(tab_order) + 20, margin=dict(t=top_px, l=170, b=30))
    fig.show()
    display(grid.rename(index=tab_label, columns=NOTE_NAMES).rename_axis(index="section", columns="note")
            .style.format("{:.0f}", na_rep="–"))
    # The global note's source_status counts only its context sections, not the closing "markets" summary.
    counted = sections[~((sections["market"] == "all") & (sections["tab"] == "markets"))]
    summary = notes[["market", "as_of_date", "generated_at", "words", "source_status.section_count",
                     "source_status.ok_sections"]].assign(
        sections=notes["market"].map(sections.groupby("market").size()),
        compared=notes["market"].map(counted.groupby("market").size()),
        available=notes["market"].map(counted.groupby("market")["ok"].sum()),
        section_words=notes["market"].map(sections.groupby("market")["words"].sum()))
    summary["counts agree"] = ((summary["compared"] == summary["source_status.section_count"])
                               & (summary["available"] == summary["source_status.ok_sections"]))
    display(summary.rename(columns={"words": "copy_markdown words", "source_status.section_count": "API section_count",
                                    "source_status.ok_sections": "API ok_sections", "compared": "sections compared",
                                    "available": "compared and available"})
            .style.format({"as_of_date": "{:%Y-%m-%d}", "generated_at": "{:%Y-%m-%d %H:%M}"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Read down a column to see how one note spends its
# words; darker cells are longer sections. Read across a row to compare the
# same section across markets. A grey-outlined "n/a" cell is a section the note
# could not fill today. The table under the chart is the per-note summary: the
# word count of the whole `copy_markdown` (tables included) next to the words
# in the section headlines and lines. `counts agree` compares the sections we
# unpacked with the note's own `source_status` counts. For the **global** note,
# `source_status` counts only its context sections (macro and FX, bond, the
# key event and news), not the closing "Markets" summary: every response seen
# so far has five sections and a `section_count` of four. So the comparison
# leaves that one section out (`sections compared`). A "False" after that is
# worth a look: some section is listed but not counted (or the reverse), so
# find out which before you rely on either number.
#
# **Caveats.**
#
# - Word count measures length, not information. A short macro headline can
#   matter more than a long list of tickers.
# - Chinese and Japanese names count as one "word" per unbroken run of
#   characters, so word counts are only comparable within a language.
# - The note's `as_of_date` is the writing date; each section carries its own
#   data date (see the age table above).
# - Notes are research documentation, written by a pipeline. They are not
#   investment advice.

# %% [markdown]
# **The `as_of_date` and single-market parameters.** One more call asks for a
# single market's note on an earlier weekday. As with the news filters, we
# check what came back instead of trusting it. Nothing below depends on this
# call, so it uses `sf_try`: any failure (an unknown date, a server error)
# prints a note and the notebook carries on.

# %%
if not notes_ok or notes.empty:
    display(Markdown("> Skipped: no notes were readable above."))
else:
    earlier = (notes["as_of_date"].max() - pd.offsets.BDay(1)).strftime("%Y-%m-%d")
    one = sf_try("/api/v1/notes/daily", market=MARKET, as_of_date=earlier)
    if one is None:
        display(Markdown(f"> No notes for {earlier}. Older notes may not be kept, the date may not have been a session, "
                         "or the service is briefly unavailable (see the message above)."))
    else:
        show_freshness(one, f"Daily notes, market={MARKET}, as_of_date={earlier}:")
        got, got_notes = dig(one, "data", "as_of_date"), records(one, "notes")
        markets_back = sorted({str(n.get("market")) for n in got_notes})
        verdict = ("as asked" if str(got) == earlier else
                   "**not** the date we asked for (the offline mock ignores `as_of_date`; live, check before you compare days)")
        display(Markdown(f"> Asked for `{earlier}`: got as_of_date `{got}`, {verdict}. "
                         f"{len(got_notes)} note(s) for market(s) {', '.join(markets_back) or 'none'}."))

# %% [markdown]
# ## 5. Macro calendar: what is due, what is expected, and (later) the surprise
#
# **What it is for.** Economic data releases (jobs, inflation, growth, surveys)
# move markets, mostly when they **surprise**. Before each release, economists
# publish forecasts; the typical forecast is the **consensus**. The calendar
# lists one market's releases for the next `days` days, each with the
# **previous** value, the consensus (when one exists) and an **importance** tag
# (`low`, `medium`, `high`). Once a release is out, `actual` is filled in and
# `surprise = actual − consensus`.
#
# What the live API sends today: the window looks **forward only**. Every event
# is flagged `is_upcoming`, `status` is `scheduled` (has a consensus) or
# `missing_consensus`, and `actual` and `surprise` are empty. So this section is
# built to work either way. It measures surprises when actual numbers exist,
# and otherwise reads the **expected change** (consensus − previous): what
# economists expect to move.
#
# Parameters: `market` (`us`, `cn`, `jp`, `hk`; default `us`) and `days` (1–60,
# default 14), the window length. We ask for all four markets (4 requests,
# with `sf_try`), and check that each answer is labelled with the market we
# asked for.
#
# The freshness fields live one level deeper than usual, in `data.data`, so
# `show_freshness` finds only the market. We print the container fields
# ourselves: `last_checked_utc` says when the calendar was refreshed, `stale`
# flags an old one and `available` says whether the provider answered.

# %%
MACRO_BOX = ["market", "days", "source", "available", "last_checked_utc", "stale"]
macro_payloads, macro_meta = {}, []
for m in MARKETS:
    payload = sf_try("/api/v1/macro/calendar", market=m, days=MACRO_DAYS)
    if payload is None:
        continue
    show_freshness(payload, f"{MARKET_NAMES[m]} calendar:")
    box = payload["data"]["data"]
    meta = {"asked_for": m, **{k: box[k] for k in MACRO_BOX}, "events": len(records(payload, "macro_calendar"))}
    if meta["market"] == m:
        macro_payloads[m], meta["used"] = payload, "yes"
    else:
        meta["used"] = f"no: labelled {meta['market']!r}"
    macro_meta.append(meta)

if not macro_meta:
    display(Markdown("> No calendar could be read. Sections 5.1 to 5.5 print short notes instead of charts."))
else:
    macro_meta = pd.DataFrame(macro_meta).set_index("asked_for")
    macro_meta["last_checked_utc"] = pd.to_datetime(macro_meta["last_checked_utc"], utc=True, errors="coerce")
    macro_meta["hours_since_check"] = (TODAY - macro_meta["last_checked_utc"]).dt.total_seconds() / 3600
    display(macro_meta.style.format({"last_checked_utc": "{:%Y-%m-%d %H:%M} UTC", "hours_since_check": "{:,.1f}"}))
    for m, row in macro_meta.iterrows():
        if row["market"] != m:
            print(f"{MARKET_NAMES[m]}: the answer is labelled {row['market']!r}, so we skip it rather than count the same "
                  "events twice. (An offline snapshot can hold one market's calendar only.)")
        elif not row["available"]:
            print(f"{MARKET_NAMES[m]}: the provider did not answer; the calendar is not available right now.")
        elif row["stale"]:
            print(f"{MARKET_NAMES[m]}: the calendar is marked stale; treat 'upcoming' flags with care.")

# %% [markdown]
# **Raw preview** (the `MARKET` calendar, or the first one we could read).

# %%
macro_raw = {m: to_frame(p, "macro_calendar") for m, p in macro_payloads.items()}
print({m: len(df) for m, df in macro_raw.items()} or "no calendars")
macro_raw.get(MARKET, next(iter(macro_raw.values()), pd.DataFrame())).head()

# %% [markdown]
# ### 5.1 Cleaning the calendar
#
# 1. **Keep the documented columns** and stack the markets.
# 2. **De-duplicate on `event_id`**, the stable id of a release.
# 3. **Parse the times.** `release_time_utc` is the exact moment, in UTC.
#    `local_time` is the wall clock in the market's time zone (`market_tz`): it
#    reads `YYYY-MM-DD HH:MM`, or just `YYYY-MM-DD` when `time_tbd` is true (no
#    confirmed time; such an event sits at 00:00 UTC). `format="mixed"` reads
#    both; we count the date-only ones. One trap: for a time-TBD event the
#    API's local date is the local date of that 00:00 UTC instant, and west of
#    UTC that is **the day before** (a Monday holiday shows up on Sunday in
#    New York). For those rows we take the date from `release_time_utc`
#    instead, and count how many moved.
# 4. **Coerce `previous`, `consensus`, `actual` and `surprise` to numbers.**
#    Empty values become `NaN`.
# 5. **Sanity-check the units.** `unit` is metadata, and metadata can be wrong.
#    A price *index* level (around 300 for US consumer prices) is sometimes
#    tagged `%`. A percent rate above 100 is implausible here, so we relabel
#    those events as "no unit" (an index level) and count them.
# 6. **Split the reference period off the name.** "Non Farm Payrolls (Sep)"
#    becomes the indicator "Non Farm Payrolls" and the period "Sep". Weekly
#    releases (jobless claims) then share one row in the heatmap.
# 7. **Compute the two differences.** `surprise` = actual − consensus (we also
#    recompute it and compare with the API's value); `expected change` =
#    consensus − previous.
# 8. **NaN policy, by status.** A `missing_consensus` event has no forecast,
#    so it can have neither an expected change nor a surprise. An event without
#    an actual number has no surprise. We count each case and leave the `NaN`
#    in place.

# %%
MACRO_COLS = ["event_id", "market", "country", "indicator_name", "category", "release_time_utc", "local_time",
              "market_tz", "importance", "previous", "consensus", "actual", "surprise", "unit", "status", "source",
              "time_tbd", "is_upcoming"]
MACRO_NUM = ["previous", "consensus", "actual", "surprise"]

frames = [pick(df, MACRO_COLS) for df in macro_raw.values() if not df.empty]
macro = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=MACRO_COLS)
n_before = len(macro)
macro["event_id"] = macro["event_id"].astype(str)
macro = macro.drop_duplicates(subset="event_id", keep="first").copy()
macro["market"] = macro["market"].astype(str).str.lower()
macro["release_utc"] = pd.to_datetime(macro["release_time_utc"], utc=True, errors="coerce")
date_only = macro["local_time"].astype(str).str.fullmatch(r"\d{4}-\d{2}-\d{2}")
macro["local"] = pd.to_datetime(macro["local_time"], format="mixed", errors="coerce")
tbd = macro["time_tbd"].eq(True) & macro["release_utc"].notna()
utc_day = macro["release_utc"].dt.tz_convert(None).dt.normalize()     # the date the event is filed under, in UTC
moved_day = tbd & (macro["local"].dt.normalize() != utc_day)
macro.loc[tbd, "local"] = utc_day[tbd]
for col in MACRO_NUM:
    macro[col] = pd.to_numeric(macro[col], errors="coerce")
macro["unit"] = macro["unit"].astype(object).where(macro["unit"].notna(), None)
suspect_unit = macro["unit"].eq("%") & macro[["previous", "consensus", "actual"]].abs().max(axis=1).gt(100)
relabelled_ids = set(macro.loc[suspect_unit, "event_id"])
macro.loc[suspect_unit, "unit"] = None
parts = macro["indicator_name"].astype(str).str.extract(r"^(?P<indicator>.*?)(?:\s*\((?P<period>[^()]*)\))?\s*$")
macro["indicator"], macro["period"] = parts["indicator"].str.strip(), parts["period"]
macro["importance_rank"] = macro["importance"].map({k: i for i, k in enumerate(IMPORTANCE_ORDER)}).fillna(len(IMPORTANCE_ORDER))
macro["surprise_calc"] = macro["actual"] - macro["consensus"]
macro["expected_change"] = macro["consensus"] - macro["previous"]
gap = (macro["surprise_calc"] - macro["surprise"]).abs()
passed = macro["is_upcoming"].eq(True) & (macro["release_utc"] < TODAY)
macro = macro.sort_values(["release_utc", "market", "indicator"]).reset_index(drop=True)

print(f"{n_before} events -> {len(macro)} after de-duplication on event_id; "
      f"{int(macro['release_utc'].isna().sum())} release times and {int(macro['local'].isna().sum())} local times "
      f"failed to parse; {int(date_only.sum())} local times are a date only (time to be decided), of which "
      f"{int(moved_day.sum())} moved to the date of release_time_utc (the API's local date was a day early).")
relabelled = sorted(set(macro.loc[macro["event_id"].isin(relabelled_ids), "indicator_name"]))
print(f"{len(relabelled_ids)} event(s) tagged '%' with a value above 100 relabelled as index levels"
      + (f": {', '.join(relabelled)}." if relabelled else "."))
print(f"{int(macro['actual'].notna().sum())} events have an actual number; {int(macro['is_upcoming'].eq(True).sum())} are "
      f"flagged upcoming, of which {int(passed.sum())} have passed since the calendar was last checked.")
if gap.notna().any():
    print(f"Surprise check: largest |(actual − consensus) − surprise| = {gap.max():.4f} over {int(gap.notna().sum())} "
          f"events; {int((gap > 0.011).sum())} disagree by more than rounding.")
else:
    print("Surprise check: no event has both an actual and an API surprise yet, so there is nothing to compare.")
if macro.empty:
    display(Markdown("> No events to audit."))
else:
    nan_policy = (macro.assign(**{f"has_{c}": macro[c].notna() for c in MACRO_NUM})
                  .groupby("status")[[f"has_{c}" for c in MACRO_NUM]].agg(["sum", "size"]))
    display(pd.DataFrame({c: nan_policy[(c, "sum")].astype(int).astype(str) + " of " + nan_policy[(c, "size")].astype(str)
                          for c in [f"has_{c}" for c in MACRO_NUM]}).rename_axis("status"))

# %% [markdown]
# ### 5.2 Scaling a difference so that indicators can be compared
#
# A difference of +28 means one thing for payrolls (28 thousand jobs) and
# another for a survey index (28 points would be enormous). Units differ, so raw
# differences cannot share one colour scale.
#
# Professional surprise indices divide each surprise by that indicator's
# historical surprise volatility. We do not have that history here, so we use
# two simpler, transparent scales, one for each kind of series:
#
# - **Percent rates** are already on a common scale: the **percentage point**
#   (pp). These are releases whose unit is `%`: growth rates such as "Retail
#   Sales MoM" or "Inflation Rate YoY", and rates such as a mortgage or
#   unemployment rate. A release named `MoM`, `QoQ`, `YoY` or `Growth` that
#   arrives without a unit counts as a rate too. We compare their moves in pp.
#   Dividing a rate by its own level would mislead: Retail Sales MoM going from
#   1.2% to 0.1% is an ordinary −1.1 pp slowdown, but as a percentage of 1.2 it
#   reads −92%, only because the base is small.
# - **Levels** (jobless claims in thousands, housing starts in millions, index
#   levels such as a sentiment survey or the CPI) are compared as a
#   **percentage of the reference value**:
#   - surprise mode (actual numbers exist): `100 × (actual − consensus) / max(|consensus|, 0.1)`;
#   - expected-change mode (no actual numbers yet): `100 × (consensus − previous) / max(|previous|, 0.1)`.
#
#   The `max(…, 0.1)` stops a reference near zero from producing a huge ratio.
#
# A pp and a percentage of a level are different measures, so the two groups
# are never ranked against each other: every ranking, median and colour scale
# below works within one group. Every chart also shows the raw difference in
# its own unit.
#
# **Where the % scale breaks.** For a level, a percentage means nothing when
# the series **crosses zero** (a budget deficit turning into a surplus), when
# the base is **near zero** (the move is larger than the level itself), or
# when the series is itself a **balance or a change** (trade balance, "Stocks
# Change"). Such a release can show +200% for an ordinary swing. We flag these
# levels as `off_scale`, keep their raw difference, and leave them out of every
# ranking, colour cap and median. The name test is a simple pattern
# (`Balance`, `Change`, `Current Account`, `Net`). The sign and size tests add
# the balances that cross or come close to zero, but a change series with
# another name and a large base still gets through, so read the indicator
# names in the tables. Percent rates are never off scale: a move in pp means the
# same thing whatever the sign or size of the rate.
#
# The next cell picks the mode from the data, so the charts below need no
# change on the day actual numbers start to arrive. It switches to surprises
# only once at least `MIN_RELEASED` events have an actual number; with fewer,
# the charts keep the expected changes and the few surprises get a table of
# their own.

# %%
released = macro[macro["actual"].notna() & macro["consensus"].notna()].copy()
released["change"] = released["surprise"].fillna(released["surprise_calc"])
released["reference"] = released["consensus"]
expected = macro[macro["actual"].isna() & macro["consensus"].notna() & macro["previous"].notna()].copy()
expected["change"], expected["reference"] = expected["expected_change"], expected["previous"]

MIN_RELEASED = 5                       # surprises take over the charts only when at least this many exist
MODE = "surprise" if len(released) >= MIN_RELEASED else "expected"
MODE_TEXT = {
    "surprise": dict(name="surprise", formula="actual − consensus", ref="consensus", x="consensus", y="actual",
                     above="above consensus", below="below consensus"),
    "expected": dict(name="expected change", formula="consensus − previous", ref="previous", x="previous",
                     y="consensus", above="expected to rise", below="expected to fall"),
}[MODE]
RATE_NAMES = re.compile(r"\b(?:MoM|QoQ|YoY|Growth)\b", re.I)                    # growth rates by name
SCALE_NAMES = re.compile(r"\b(?:Balance|Change|Current Account|Net)\b", re.I)   # balances and changes by name


def add_scale(frame: pd.DataFrame, ref_name: str) -> pd.DataFrame:
    """Put each difference on a comparable scale: pp for percent rates, % of |reference| for levels.

    `scaled` holds the number every ranking and colour uses; it is NaN for levels the % scale cannot describe.
    """
    frame = frame.copy()
    ref, target = frame["reference"], frame["reference"] + frame["change"]
    names = frame["indicator"].astype(str)
    frame["rate"] = frame["unit"].eq("%") | (frame["unit"].isna() & names.str.contains(RATE_NAMES))
    frame["rel_pct"] = 100 * frame["change"] / ref.abs().clip(lower=0.1)
    frame["change_text"] = [fmt_unit(c, u, signed=True) for c, u in zip(frame["change"], frame["unit"])]
    frame["date"] = frame["local"].dt.normalize()
    reasons = pd.DataFrame({
        "sign flip": np.sign(ref) != np.sign(target),
        "near-zero base": ref.abs() < frame["change"].abs(),
        "balance or change series": names.str.contains(SCALE_NAMES),
    }, index=frame.index)
    frame["off_scale"] = ~frame["rate"] & reasons.any(axis=1)      # a move in pp is fine whatever the base
    frame["scaled"] = frame["change"].where(frame["rate"], frame["rel_pct"]).where(~frame["off_scale"])
    frame["scale_note"] = ["percent rate: in pp" if rate else
                           ", ".join(k for k, hit in r.items() if hit) or f"level: % of |{ref_name}|"
                           for rate, r in zip(frame["rate"], reasons.to_dict("records"))]
    frame["scaled_text"] = [fmt_unit(c, "%", signed=True) if rate else "off the % scale" if off
                            else f"{rel:+.1f}% of |{ref_name}|".replace("-", "−")
                            for c, rel, rate, off in zip(frame["change"], frame["rel_pct"], frame["rate"], frame["off_scale"])]
    return frame


released, expected = add_scale(released, "consensus"), add_scale(expected, "previous")
view = released if MODE == "surprise" else expected
REL_COL = f"% of |{MODE_TEXT['ref']}|"
PP_COL = f"{MODE_TEXT['name']} (pp)"

print(f"{len(released)} events have an actual number and a consensus; {len(expected)} upcoming events have a "
      f"consensus and a previous value. Mode: **{MODE_TEXT['name']}** ({MODE_TEXT['formula']}).")
if MODE == "surprise" and not expected.empty:
    print(f"{len(expected)} upcoming releases with an expected change are not in the surprise charts; table 5.6 lists them.")
if view.empty:
    display(Markdown("> No event has the numbers either mode needs. Raise `MACRO_DAYS` and re-run."))
else:
    rates, levels = view[view["rate"]], view[~view["rate"]]
    n_off = int(view["off_scale"].sum())
    print(f"{len(rates)} of {len(view)} releases are percent rates (compared in pp) and {len(levels)} are levels "
          f"(compared as {REL_COL}). {n_off} of the levels are off the % scale (sign flip, near-zero base, or a balance "
          "or change series): they keep their raw difference but are left out of the rankings, colour caps and medians.")
    shown_cols = ["market", "indicator_name", "importance", "unit", MODE_TEXT["x"], MODE_TEXT["y"]]
    if not rates.empty:
        display(Markdown("**Largest moves among percent rates**, in percentage points:"))
        display(rates[shown_cols + ["change"]].sort_values("change", key=lambda s: s.abs(), ascending=False).head(10)
                .rename(columns={"change": PP_COL})
                .style.format({MODE_TEXT["x"]: "{:,.6g}", MODE_TEXT["y"]: "{:,.6g}", PP_COL: "{:+.2f} pp"}, na_rep="–")
                .hide(axis="index"))
    on_scale = levels[~levels["off_scale"]]
    if not on_scale.empty:
        display(Markdown(f"**Largest moves among levels**, as a percentage of |{MODE_TEXT['ref']}|:"))
        display(on_scale[shown_cols + ["change_text", "rel_pct"]]
                .sort_values("rel_pct", key=lambda s: s.abs(), ascending=False).head(10)
                .rename(columns={"change_text": MODE_TEXT["name"], "rel_pct": REL_COL})
                .style.format({MODE_TEXT["x"]: "{:,.6g}", MODE_TEXT["y"]: "{:,.6g}", REL_COL: "{:+.1f}%"},
                              na_rep="–").hide(axis="index"))
    if n_off:
        display(Markdown("**Levels off the % scale** (raw difference only):"))
        display(view[view["off_scale"]][shown_cols + ["change_text", "rel_pct", "scale_note"]]
                .rename(columns={"change_text": MODE_TEXT["name"], "rel_pct": f"{REL_COL} (not meaningful)",
                                 "scale_note": "why off scale"})
                .style.format({MODE_TEXT["x"]: "{:,.6g}", MODE_TEXT["y"]: "{:,.6g}",
                               f"{REL_COL} (not meaningful)": "{:+.1f}%"}, na_rep="–").hide(axis="index"))
if MODE == "expected" and not released.empty:
    display(Markdown(f"> **{len(released)} release(s) already have an actual number**: fewer than `MIN_RELEASED` = "
                     f"{MIN_RELEASED}, too few for the surprise charts, so they are listed here and the charts below keep "
                     "the expected changes."))
    display(released[["market", "indicator_name", "importance", "consensus", "actual", "change_text", "scaled_text",
                      "scale_note"]]
            .rename(columns={"change_text": "surprise", "scaled_text": "on its scale"})
            .style.format({"consensus": "{:,.6g}", "actual": "{:,.6g}"}, na_rep="–").hide(axis="index"))

# %% [markdown]
# ### 5.3 Chart: the surprise heatmap
#
# One panel per market. Rows are indicators, columns are release dates (on the
# market's own calendar). Colour is the difference on its own scale (see 5.2),
# on a **diverging** scale: blue means above the reference, red below, pale
# grey close to it. Percent rates (rows marked `· pp`) are coloured by their
# move in percentage points; levels by their move as a percentage of the
# reference. The two groups get **separate colour bars**, each symmetric
# around zero and capped at the 75th percentile of that group's |moves|, so a
# few large values cannot wash out the rest. Off-scale levels (sign flips,
# near-zero bases, balances and changes) get no colour and a dotted outline,
# and they take no part in the caps or the headline. The text in each cell is
# the raw difference in its own unit. The headline names the largest move
# within each group. Rows are limited to `MACRO_MIN_IMPORTANCE` and above.
#
# When actual numbers exist, the cells are **surprises**. When none exist yet
# (the usual live case today), the heatmap says so and shows the **expected
# change** instead, so you can see which upcoming releases economists expect to
# move, and in which direction.

# %%
def colour_cap(values: pd.Series, step: float, floor: float) -> float:
    """The 75th percentile of |values|, rounded up to a multiple of `step`, and at least `floor`."""
    values = values.dropna().abs()
    return float(max(floor, np.ceil(values.quantile(0.75) / step - 1e-9) * step)) if not values.empty else floor


def describe(b: pd.Series, with_market: bool) -> str:
    """One release for a headline, with its move on its own scale (pp or % of the reference)."""
    name = f"{MARKET_NAMES[b['market']]} {b['indicator_name']}" if with_market else b["indicator_name"]
    if MODE == "surprise":
        return (f"{name} at {fmt_unit(b['actual'], b['unit'])} vs {fmt_unit(b['consensus'], b['unit'])} expected "
                f"({b['scaled_text']})")
    return f"{name}, {fmt_unit(b['previous'], b['unit'])} → {fmt_unit(b['consensus'], b['unit'])} ({b['scaled_text']})"


heat = view[view["importance_rank"] <= MIN_IMPORTANCE_RANK].copy() if not view.empty else view
if MODE == "expected":
    have = (f"None of the {len(macro)} events in this window has an actual number" if released.empty else
            f"Only {len(released)} of the {len(macro)} events in this window have an actual number (5.2 lists them)")
    display(Markdown(f"> **No surprises to colour yet.** {have}, so there is no surprise map to draw. The heatmap below "
                     "shows the **expected change** (consensus − previous) instead. It turns into the surprise heatmap "
                     f"automatically once the API sends at least {MIN_RELEASED} actual numbers."))
if heat.empty:
    display(Markdown(f"> No event with importance '{MACRO_MIN_IMPORTANCE}' or higher has both numbers. Set "
                     "`MACRO_MIN_IMPORTANCE = \"low\"` or raise `MACRO_DAYS`."))
else:
    CATEGORY_ORDER = ["inflation", "labor", "growth", "survey", "housing", "trade", "credit", "rates", "other"]
    heat["cat_rank"] = heat["category"].map({c: i for i, c in enumerate(CATEGORY_ORDER)}).fillna(len(CATEGORY_ORDER))
    dates = sorted(heat["date"].dropna().unique())
    date_labels = [pd.Timestamp(d).strftime("%a %d %b") for d in dates]
    shown = [m for m in MARKETS if (heat["market"] == m).any()]
    R_LEVEL = colour_cap(heat.loc[~heat["rate"], "scaled"], step=1, floor=1)        # % of |reference|
    R_RATE = colour_cap(heat.loc[heat["rate"], "scaled"], step=0.25, floor=0.25)    # percentage points
    heat["level_on"] = heat["scaled"].where(~heat["rate"]).clip(-R_LEVEL, R_LEVEL)  # off-scale levels stay NaN
    heat["rate_on"] = heat["scaled"].where(heat["rate"]).clip(-R_RATE, R_RATE)
    heat["off"] = heat["off_scale"].astype(float)
    # Each group gets its own colour axis (and colour bar); a group with no coloured cell gets none.
    AXES = {"level": ("coloraxis", "level_on", R_LEVEL, "%", f"Levels: {MODE_TEXT['name']},<br>% of |{MODE_TEXT['ref']}|"),
            "rate": ("coloraxis2", "rate_on", R_RATE, " pp", f"Percent rates (· pp):<br>{MODE_TEXT['name']} in pp")}
    groups = [g for g in AXES if heat[AXES[g][1]].notna().any()]
    heights = [max(2, heat.loc[heat["market"] == m, "indicator"].nunique()) for m in shown]
    fig = make_subplots(rows=len(shown), cols=1, shared_xaxes=True, vertical_spacing=0.06 if len(shown) > 1 else 0.02,
                        row_heights=[h / sum(heights) for h in heights],
                        subplot_titles=[f"<b>{MARKET_NAMES[m]}</b>" for m in shown])
    for row, m in enumerate(shown, start=1):
        part = heat[heat["market"] == m].sort_values(["cat_rank", "indicator", "date"])
        order = list(dict.fromkeys(part["indicator"]))
        is_rate = part.groupby("indicator")["rate"].first().reindex(order)

        def cell(col):
            return part.pivot_table(index="indicator", columns="date", values=col, aggfunc="first").reindex(
                index=order, columns=dates)

        part = part.assign(hover=[
            f"<b>{n}</b> · {c} · {imp} importance<br>Released {t:%a %d %b %H:%M} local<br>"
            f"{MODE_TEXT['y'].title()} {fmt_unit(y, u)} vs {MODE_TEXT['x']} {fmt_unit(x, u)}<br>"
            + (f"{MODE_TEXT['name'].capitalize()} {s}; off the % scale ({note})" if off else
               f"{MODE_TEXT['name'].capitalize()} {s} (percent rate, compared in pp)" if rate else
               f"{MODE_TEXT['name'].capitalize()} {s} = {sc}")
            for n, c, imp, t, y, x, u, s, sc, rate, off, note in zip(
                part["indicator_name"], part["category"], part["importance"], part["local"], part[MODE_TEXT["y"]],
                part[MODE_TEXT["x"]], part["unit"], part["change_text"], part["scaled_text"], part["rate"],
                part["off_scale"], part["scale_note"])])
        txt, hv = cell("change_text").fillna(""), cell("hover").fillna("")
        off = cell("off").fillna(0).to_numpy(dtype=float) > 0
        labels = [f"{shorten(i, 30)} · pp" if r else shorten(i, 34) for i, r in zip(order, is_rate)]
        for g in groups:
            axis, col, _, _, _ = AXES[g]
            z = cell(col).to_numpy(dtype=float)
            if np.isnan(z).all():
                continue
            fig.add_trace(go.Heatmap(
                z=z, x=date_labels, y=labels, text=np.where(np.isnan(z), "", txt.to_numpy()), texttemplate="%{text}",
                textfont=dict(size=10), customdata=hv.to_numpy(), hovertemplate="%{customdata}<extra></extra>",
                hoverongaps=False, coloraxis=axis, xgap=2, ygap=2), row=row, col=1)
        if off.any():                                   # off-scale releases: no colour, raw text, dotted outline
            fig.add_trace(go.Heatmap(
                z=np.where(off, 1.0, np.nan), x=date_labels, y=labels, text=np.where(off, txt.to_numpy(), ""),
                texttemplate="%{text}", textfont=dict(size=10, color=INK_2), customdata=hv.to_numpy(),
                hovertemplate="%{customdata}<extra></extra>", hoverongaps=False, showscale=False,
                colorscale=[[0, SURFACE], [1, SURFACE]], xgap=2, ygap=2), row=row, col=1)
            for i, j in zip(*np.where(off)):
                fig.add_shape(type="rect", x0=j - 0.46, x1=j + 0.46, y0=i - 0.42, y1=i + 0.42,
                              line=dict(color=INK_2, width=1, dash="dot"), fillcolor="rgba(0,0,0,0)", row=row, col=1)
        fig.update_yaxes(autorange="reversed", ticks="", tickfont=dict(size=11), row=row, col=1)
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=date_labels, ticks="", tickangle=-45, showgrid=False)
    fig.update_yaxes(showgrid=False)
    for ann in fig.layout.annotations:
        ann.update(x=0, xanchor="left", font=dict(size=13, color=INK))
    plot_h = 30 * sum(heights) + 40 * len(shown) + 50
    bar_len = min(0.45 if len(groups) > 1 else 0.6, 260 / plot_h)
    for k, g in enumerate(groups):                      # stacked colour bars on the right, levels first
        axis, _, cap, suffix, bar_title = AXES[g]
        fig.update_layout({axis: dict(colorscale=DIVERGING, cmin=-cap, cmax=cap, colorbar=dict(
            title=dict(text=bar_title, side="right", font=dict(size=12)), ticksuffix=suffix, thickness=14,
            len=bar_len, y=1 - k * (bar_len + 0.1), yanchor="top"))})

    n_up = int((heat["change"] > 0).sum())
    n_off = int(heat["off_scale"].sum())
    n_rate, n_level = int(heat["rate"].sum()), int((~heat["rate"] & ~heat["off_scale"]).sum())
    leaders = [f"{describe(grp.loc[grp['scaled'].abs().idxmax()], len(shown) > 1)} among {label}"   # rank within a group
               for label, grp in (("percent rates", heat[heat["rate"]]), ("levels", heat[~heat["rate"] & ~heat["off_scale"]]))
               if grp["scaled"].notna().any()]
    noun = "surprise" if MODE == "surprise" else "expected move"
    if not leaders:
        headline = f"Every {MODE_TEXT['name']} here is off the % scale, so there is no fair 'biggest' to name"
    else:
        headline = f"Largest {noun}{'s' if len(leaders) > 1 else ''}: " + "; ".join(leaders)
    caps = [f"±{R_RATE:g} pp for the {n_rate} percent-rate cells" if "rate" in groups else "",
            f"±{R_LEVEL:g}% for the {n_level} on-scale level cells" if "level" in groups else ""]
    print(f"{n_off} of {len(heat)} cells are off the % scale (uncoloured, dotted outline) and left out of the headline "
          f"and the colour caps. Caps (the 75th percentile of each group's |moves|, rounded up): "
          f"{'; '.join(c for c in caps if c) or 'none'}.")
    title_spec, title_px = chart_title(
        headline, f"{n_up} of {len(heat)} {MACRO_MIN_IMPORTANCE}-or-higher importance releases {MODE_TEXT['above']} · "
                  f"colour: pp for percent rates (rows marked · pp), % of |{MODE_TEXT['ref']}| for levels, each with "
                  f"its own colour bar · text = raw {MODE_TEXT['name']}"
                  + (f" · dotted = {n_off} off the % scale" if n_off else ""))
    top_px = title_px + 24                              # room for the first panel title
    fig.update_layout(title=title_spec, height=top_px + 90 + plot_h, margin=dict(t=top_px, l=230, b=90))
    fig.show()
    display(heat[["market", "date", "indicator_name", "category", "importance", MODE_TEXT["x"], MODE_TEXT["y"],
                  "change_text", "scaled_text", "scale_note"]].sort_values(["market", "date", "importance"])
            .rename(columns={"change_text": MODE_TEXT["name"], "scaled_text": "on its scale", "scale_note": "scale"})
            .style.format({"date": "{:%Y-%m-%d}", MODE_TEXT["x"]: "{:,.6g}", MODE_TEXT["y"]: "{:,.6g}"}, na_rep="–")
            .hide(axis="index"))

# %% [markdown]
# **How to read this.** Find a market panel, then read across: each coloured
# cell is one release. Deep blue means a big move up against the reference,
# deep red a big move down, and pale cells were close to it. "Big" is judged
# within the row's group: a row marked `· pp` is a percent rate and follows the
# pp colour bar; every other row is a level and follows the % colour bar. So
# compare shades within a group, not across groups. An uncoloured cell with a
# dotted outline is off the % scale: read its raw text, not a colour. A row
# with several cells (weekly jobless claims) shows the same indicator over
# time. Hover for the full numbers; the table under the chart has every cell
# as numbers, on its own scale, with the reason for each off-scale cell.
#
# **Caveats.**
#
# - "Above" is not always good news. More jobless claims than expected is a
#   **weak** reading, even though it is blue here. Colour shows direction, not
#   good or bad.
# - Both scales are rough comparison tools (see 5.2). Even in pp, a volatile
#   rate (a year-on-year change in home sales) moves more than a steady one (core
#   inflation) without being more surprising. For a serious study, collect
#   months of releases and divide each surprise by that indicator's own
#   surprise volatility.
# - Releases without a consensus (very common: check the NaN table) have
#   neither a surprise nor an expected change, so they are not in the heatmap.
# - The same number can appear under two names (a price index can be listed as
#   both "Inflation Rate" and "CPI"). The heatmap shows both rows; section 5.4
#   collapses such duplicates before it counts anything.

# %% [markdown]
# ### 5.4 Chart: how big each expected change (or surprise) is
#
# Each dot is one release. Across is its reference level: the previous value
# (or, in surprise mode, the consensus). Up is the **difference in the
# release's own unit**: consensus − previous, the expected change (or actual −
# consensus, the surprise). On the dashed zero line nothing is expected to
# change (or the forecast was exactly right). Dots above it are releases that
# economists expect to **rise** (or that beat the forecast); dots below are
# expected to **fall** (or fell short).
#
# Why the difference and not the two levels? One panel can hold a 0.3% monthly
# rate next to a 76% capacity-utilisation rate. On a chart of level against
# level, a move of 0.3 points would be a few pixels off the diagonal, and every
# dot would seem to sit on the line. Plotting the difference makes the moves
# themselves the thing you see.
#
# Units still differ, so there is **one panel per unit**, each with its own
# scale, symmetric around zero so that ups and downs compare fairly. Markets
# keep their usual colours, and each also has its own marker shape, so you can
# tell them apart without colour. Every release with both numbers is plotted,
# whatever its importance.
#
# Before counting, we **collapse duplicates**: the same market, release time,
# unit and numbers listed under two names (a price index published as both
# "CPI" and "Inflation Rate", for example). Counting both would overstate how
# many independent releases there are.

# %%
UNIT_TITLES = {"%": "Percent (%)", "index": "Index level or no unit", "K": "Thousands (K)", "M": "Millions (M)",
               "B": "Billions (B)", "T": "Trillions (T)"}
UNIT_AXIS = {"%": ("%", "pp"), "index": ("level", "points"), "K": ("thousands", "thousands"),
             "M": ("millions", "millions"), "B": ("billions", "billions"), "T": ("trillions", "trillions")}
MARKET_SYMBOLS = dict(zip(MARKETS, ["circle", "square", "diamond", "triangle-up"]))


def median_moves(part: pd.DataFrame) -> tuple:
    """Median |move| within each group: pp for percent rates, % of |reference| for on-scale levels."""
    return (part.loc[part["rate"], "scaled"].abs().median(),
            part.loc[~part["rate"] & ~part["off_scale"], "scaled"].abs().median())


if view.empty:
    display(Markdown("> No release has both numbers in this window, so there is no difference to plot."))
else:
    view["unit_group"] = view["unit"].replace({"Points": None}).fillna("index")
    xcol, ycol = MODE_TEXT["x"], MODE_TEXT["y"]
    key = ["market", "release_utc", "unit_group", xcol, ycol]          # one release, whatever its name
    pts = view.sort_values(["importance_rank", "indicator_name"]).drop_duplicates(subset=key, keep="first")
    collapsed = view.loc[~view.index.isin(pts.index), "indicator_name"]
    print(f"{len(view)} rows -> {len(pts)} releases after collapsing {len(collapsed)} duplicate row(s) "
          "(same market, release time, unit and numbers under another name)"
          + (f": {', '.join(collapsed)}." if len(collapsed) else "."))
    units = [u for u in UNIT_TITLES if (pts["unit_group"] == u).any()] + sorted(set(pts["unit_group"]) - set(UNIT_TITLES))
    cols = min(3, len(units))
    rows = int(np.ceil(len(units) / cols))
    fig = make_subplots(rows=rows, cols=cols, horizontal_spacing=0.11, vertical_spacing=0.24 if rows > 1 else 0.1,
                        subplot_titles=[f"{UNIT_TITLES.get(u, u)} · {int((pts['unit_group'] == u).sum())} releases"
                                        for u in units])
    for i, unit in enumerate(units):
        r, c = i // cols + 1, i % cols + 1
        part = pts[pts["unit_group"] == unit]
        level_name, change_name = UNIT_AXIS.get(unit, (unit, unit))
        span = float(part["change"].abs().max()) or 1.0                     # symmetric y range around zero
        xs = part[xcol].astype(float)
        x_pad = max((xs.max() - xs.min()) * 0.1, abs(xs.max()) * 0.05, 0.5)
        x_rng = [xs.min() - x_pad, xs.max() + x_pad]
        fig.add_trace(go.Scatter(x=x_rng, y=[0, 0], mode="lines", line=dict(color=MUTED, width=1.5, dash="dash"),
                                 name="Forecast exactly right (0)" if MODE == "surprise" else "No change expected (0)",
                                 showlegend=(i == 0), hoverinfo="skip"), row=r, col=c)
        for m in MARKETS:
            pm = part[part["market"] == m]
            if pm.empty:
                continue
            rel_text = [f"off the % scale: {note}" if off else "a percent rate, compared in pp" if rate else sc
                        for sc, rate, off, note in zip(pm["scaled_text"], pm["rate"], pm["off_scale"], pm["scale_note"])]
            fig.add_trace(go.Scatter(
                x=pm[xcol], y=pm["change"], mode="markers", name=MARKET_NAMES[m], legendgroup=m,
                showlegend=not any(t.name == MARKET_NAMES[m] for t in fig.data),
                marker=dict(size=11, color=MARKET_COLORS[m], symbol=MARKET_SYMBOLS[m], line=dict(width=1, color=SURFACE)),
                customdata=np.column_stack([
                    pm["indicator_name"], pm["change_text"], rel_text, pm["importance"],
                    [fmt_unit(v, u) for v, u in zip(pm[xcol], pm["unit"])],
                    [fmt_unit(v, u) for v, u in zip(pm[ycol], pm["unit"])]]),
                hovertemplate=(f"<b>%{{customdata[0]}}</b> ({MARKET_NAMES[m]}, %{{customdata[3]}} importance)"
                               f"<br>{xcol.title()} %{{customdata[4]}} → {ycol} %{{customdata[5]}}"
                               f"<br>{MODE_TEXT['name'].capitalize()} %{{customdata[1]}} (%{{customdata[2]}})"
                               "<extra></extra>")),
                row=r, col=c)
        far = part.loc[part["change"].abs().idxmax()]                         # the largest move in the panel's unit
        right = (far[xcol] - x_rng[0]) / (x_rng[1] - x_rng[0]) > 0.55        # label towards the panel's centre
        fig.add_annotation(x=far[xcol], y=far["change"], text=shorten(far["indicator"], 24), showarrow=True,
                           arrowhead=0, arrowcolor=MUTED, ax=-30 if right else 30, ay=30 if far["change"] > 0 else -30,
                           xanchor="right" if right else "left", font=dict(size=10, color=INK_2), row=r, col=c)
        fig.update_xaxes(range=x_rng, title_text=f"{xcol.title()} ({level_name})", row=r, col=c)
        fig.update_yaxes(range=[-1.25 * span, 1.25 * span], zeroline=False,
                         title_text=f"{MODE_TEXT['name'].capitalize()} ({change_name})", row=r, col=c)
    for j in range(len(units), rows * cols):                              # hide the grid cells with no unit
        fig.update_xaxes(visible=False, row=j // cols + 1, col=j % cols + 1)
        fig.update_yaxes(visible=False, row=j // cols + 1, col=j % cols + 1)
    ups, downs = int((pts["change"] > 0).sum()), int((pts["change"] < 0).sum())
    med_pp, med_level = median_moves(pts)
    medians = " and ".join(text for text, value in [(f"{med_pp:.2f} pp for percent rates", med_pp),
                                                     (f"{med_level:.1f}% of |{MODE_TEXT['ref']}| for levels", med_level)]
                           if pd.notna(value)) or "not defined (every release is an off-scale level)"
    if MODE == "surprise":
        headline = (f"{ups} of {len(pts)} releases came in above the consensus and {downs} below; "
                    f"median miss {medians}")
    else:
        headline = (f"Economists expect {ups} of {len(pts)} releases to rise and {downs} to fall; "
                    f"median expected move {medians}")
    title_spec, title_px = chart_title(
        headline, f"{ups} {MODE_TEXT['above']}, {downs} {MODE_TEXT['below']}, {len(pts) - ups - downs} unchanged · "
                  f"{len(collapsed)} duplicate row(s) collapsed · one panel per unit, each on its own scale · medians "
                  "within each group, off-scale levels left out · the largest "
                  f"{MODE_TEXT['name']} in each panel is labelled")
    top_px = title_px + 24                              # room for the panel titles
    fig.update_layout(title=title_spec, height=top_px + 110 + 330 * rows, margin=dict(t=top_px, b=110),
                      legend=LEGEND_BELOW)
    fig.show()

    rows_ = []
    for name, part in [("all markets", pts), *[(m, pts[pts["market"] == m]) for m in MARKETS if (pts["market"] == m).any()]]:
        k, n_ = int((part["change"] > 0).sum()), int((part["change"] != 0).sum())
        low, high = wilson(k, n_)
        rows_.append({"group": name, "releases": len(part), "up": k, "down": n_ - k, "unchanged": len(part) - n_,
                      "share_up": k / n_ if n_ else np.nan, "ci_low": low, "ci_high": high,
                      "sign_test_p": stats.binomtest(k, n_, 0.5).pvalue if n_ else np.nan,
                      **dict(zip(["median_pp_rates", "median_pct_levels"], median_moves(part)))})
    display(pd.DataFrame(rows_).set_index("group").rename(columns={
        "up": MODE_TEXT["above"], "down": MODE_TEXT["below"], "median_pp_rates": "median |move|, rates (pp)",
        "median_pct_levels": f"median |move|, levels ({REL_COL})"})
        .style.format({"share_up": "{:.0%}", "ci_low": "{:.0%}", "ci_high": "{:.0%}", "sign_test_p": "{:.2f}",
                       "median |move|, rates (pp)": "{:.2f}", f"median |move|, levels ({REL_COL})": "{:.1f}%"},
                      na_rep="–"))
    display(pts.sort_values(["unit_group", "market", "change"])
            [["unit_group", "market", "indicator_name", "importance", xcol, ycol, "change_text", "scaled_text",
              "scale_note"]]
            .rename(columns={"change_text": MODE_TEXT["name"], "scaled_text": "on its scale", "scale_note": "scale"})
            .style.format({xcol: "{:,.6g}", ycol: "{:,.6g}"}, na_rep="–")
            .hide(axis="index"))

# %% [markdown]
# **How to read this.** Find a unit's panel. The height of a dot above or below
# the dashed zero line is the size of the move, in that panel's unit
# (percentage points, thousands, ...). Its position across only says where the
# indicator sits; it is not a move. Hover for the full numbers, including the
# move on its comparison scale from 5.2 (pp for a percent rate, % of the
# reference for a level, or why a level is off that scale). The headline gives
# one median per group, because a median of pp and percentages mixed together
# would mean nothing.
#
# The first table under the chart asks a simple question: are moves up more
# common than moves down? `share_up` counts the ups among the releases that were
# not unchanged, with a 95% **Wilson** interval. The **sign test** p-value asks
# how surprising that split would be if up and down were equally likely (a coin
# flip). A large p (above about 0.05) means the split is consistent with chance.
# Both count releases after the duplicates were collapsed. The second table
# lists every dot.
#
# **Caveats.**
#
# - Two weeks of releases is a small sample, and releases are still not
#   independent after the duplicates go (the monthly and yearly inflation rates
#   come from the same report, and weekly series repeat), so the sign test is
#   on the optimistic side.
# - Consensus values come from one provider (`source`); other polls differ.
# - In expected-change mode, "expected to rise" describes a forecast, not a
#   result. Re-run after the releases to see the surprises.

# %% [markdown]
# ### 5.5 Chart: when the releases land
#
# This one works on every event, with or without a consensus: how many
# releases fall on each day of the window, stacked by importance. The darkest
# blue (high importance) sits at the base of each bar, so the days that matter
# most are easy to compare. Each market gets its own panel and its own local
# calendar, and all panels share one y scale, so a tall bar means a busy day
# in any market. Time-TBD events sit on the date of `release_time_utc` (see
# cleaning step 3).

# %%
cal = macro.dropna(subset=["local"]).assign(day=lambda d: d["local"].dt.normalize())
if cal.empty:
    display(Markdown("> No dated events to place on a calendar."))
else:
    counts = (cal.groupby(["market", "day", "importance"]).size().unstack("importance", fill_value=0)
              .reindex(columns=IMPORTANCE_ORDER, fill_value=0))
    days = pd.date_range(cal["day"].min(), cal["day"].max(), freq="D")
    day_labels = [f"{d:%a %d %b}" for d in days]
    shown = [m for m in MARKETS if m in counts.index.get_level_values("market")]
    fig = make_subplots(rows=len(shown), cols=1, shared_xaxes=True, vertical_spacing=0.08,
                        subplot_titles=[f"<b>{MARKET_NAMES[m]}</b>" for m in shown])
    for row, m in enumerate(shown, start=1):
        part = counts.loc[m].reindex(days, fill_value=0)
        for imp in IMPORTANCE_ORDER:                         # high first, so it sits on the baseline
            fig.add_trace(go.Bar(
                x=day_labels, y=part[imp], name=f"{imp.title()} importance", legendgroup=imp, showlegend=(row == 1),
                marker=dict(color=IMPORTANCE_COLORS[imp], line=dict(width=1, color=SURFACE)),
                hovertemplate=f"{MARKET_NAMES[m]} · %{{x}}: %{{y}} {imp}-importance release(s)<extra></extra>"),
                row=row, col=1)
        fig.update_yaxes(title_text="Releases" if row == (len(shown) + 1) // 2 else None, row=row, col=1)
    for ann in fig.layout.annotations:
        ann.update(x=0, xanchor="left", font=dict(size=13, color=INK))
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=day_labels, tickangle=-45, ticks="")
    fig.update_yaxes(matches="y")                     # one y scale for every panel, so bar heights compare across markets
    totals = counts.sum(axis=1)
    (high_m, high_d), (busy_m, busy_d) = counts["high"].idxmax(), totals.idxmax()
    where = lambda m: f" ({MARKET_NAMES[m]})" if len(shown) > 1 else ""       # name the market only when there are several
    n_high = int(counts["high"].sum())
    if n_high == 0:
        headline = f"No high-importance release in the window; {busy_d:%a %d %b}{where(busy_m)} is the busiest day ({int(totals.max())})"
    elif (high_m, high_d) == (busy_m, busy_d):
        headline = (f"{busy_d:%a %d %b}{where(busy_m)} is the day to watch: the most releases ({int(totals.max())}) and the "
                    f"most high-importance ones ({int(counts['high'].max())})")
    else:
        headline = (f"{high_d:%a %d %b}{where(high_m)} carries the most high-importance releases "
                    f"({int(counts['high'].max())}); {busy_d:%a %d %b}{where(busy_m)} is the busiest overall ({int(totals.max())})")
    title_spec, title_px = chart_title(
        headline, f"Releases per day on each market's own calendar · window of {MACRO_DAYS} days · {len(cal)} releases "
                  f"in all, {n_high} high importance · the same y scale in every panel · days without a bar have no "
                  "release (weekends, holidays)")
    top_px = title_px + 24                              # room for the panel titles
    fig.update_layout(barmode="stack", title=title_spec, height=top_px + 150 + 230 * len(shown),   # 230 px per panel
                      margin=dict(t=top_px, b=150), legend=dict(LEGEND_BELOW, traceorder="normal"))
    fig.show()
    display(counts.assign(total=totals).reset_index().query("total > 0")
            .style.format({"day": "{:%a %Y-%m-%d}"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Taller bars are busier days; the dark base of each bar
# counts the high-importance releases, the ones that usually move markets.
# Weekends and holidays show as gaps. The table lists the same counts.
#
# **Caveats.** Importance is the provider's tag, not a measure of market
# impact. A "low" release can still move a stock that depends on it.
#
# ### 5.6 The upcoming events table
#
# The releases still to come, **most important first**, then soonest first,
# across all markets we could read. Rows below `MACRO_MIN_IMPORTANCE` are
# counted but hidden. `due` counts from now. `is_upcoming` was set when the
# calendar was last checked, so a release that has passed since then shows
# "passed: re-fetch". "time TBD" marks an event without a confirmed time.

# %%
upcoming = macro[macro["is_upcoming"].eq(True)].copy()
if upcoming.empty:
    display(Markdown("> No upcoming releases in this window. Raise `MACRO_DAYS` to look further ahead."))
else:
    hours = (upcoming["release_utc"] - TODAY).dt.total_seconds() / 3600
    upcoming["due"] = [("passed: re-fetch" if h < 0 else f"in {int(h // 24)} d {int(h % 24):02d} h" if h >= 24
                        else f"in {h:.1f} h") if pd.notna(h) else "–" for h in hours]
    upcoming["local release"] = [("–" if pd.isna(t) else f"{t:%a %d %b}, time TBD" if tbd is True else f"{t:%a %d %b %H:%M}")
                                 + f" ({str(tz).split('/')[-1].replace('_', ' ')})"
                                 for t, tbd, tz in zip(upcoming["local"], upcoming["time_tbd"].eq(True),
                                                       upcoming["market_tz"])]
    table = pd.DataFrame({
        "market": upcoming["market"], "importance": upcoming["importance"], "local release": upcoming["local release"],
        "due": upcoming["due"], "indicator": upcoming["indicator_name"], "category": upcoming["category"],
        "previous": [fmt_unit(v, u) for v, u in zip(upcoming["previous"], upcoming["unit"])],
        "consensus": [fmt_unit(v, u) for v, u in zip(upcoming["consensus"], upcoming["unit"])],
        "expected change": [fmt_unit(v, u, signed=True) for v, u in zip(upcoming["expected_change"], upcoming["unit"])],
        "status": upcoming["status"], "_rank": upcoming["importance_rank"], "_time": upcoming["release_utc"]})
    shown_rows = table[table["_rank"] <= MIN_IMPORTANCE_RANK].sort_values(["_rank", "_time"]).drop(columns=["_rank", "_time"])
    by_importance = table["importance"].value_counts().reindex(IMPORTANCE_ORDER, fill_value=0)
    print(f"{len(table)} upcoming releases across {table['market'].nunique()} market(s) in a {MACRO_DAYS}-day window: "
          + ", ".join(f"{by_importance[k]} {k}" for k in IMPORTANCE_ORDER)
          + f". Showing {len(shown_rows)} with importance '{MACRO_MIN_IMPORTANCE}' or higher "
            f"({len(table) - len(shown_rows)} hidden; set MACRO_MIN_IMPORTANCE = 'low' to list them all).")
    display(shown_rows.style.apply(
        lambda row: ["font-weight: 600" if row["importance"] == "high" else f"color: {INK_2}"] * len(row), axis=1)
        .hide(axis="index"))

# %% [markdown]
# **How to read this.** High-importance releases come first and are in bold:
# those are the ones that usually move markets. Compare `consensus` with
# `previous` (the `expected change` column) to see what economists expect.
# `missing_consensus` means no forecast is published yet; there will be no
# surprise to measure until there is one.
#
# **Caveats for the macro section.**
#
# - Release times can move. Re-fetch close to the date.
# - `local release` is the market's own clock; `release_time_utc` is the exact
#   moment if you need to line it up with prices in another zone.
# - Some rows are speeches, auctions or holidays. They carry no numbers at all;
#   the importance tag tells you whether to watch them.

# %% [markdown]
# ## 6. Bond ETFs: the credit and rates board
#
# **What it is for.** Bond ETFs are exchange-traded funds that hold baskets of
# bonds. They give a quick read on the US bond market: investment-grade
# corporate bonds (safer companies), high-yield bonds (riskier companies, higher
# interest), and the broad market (Treasuries, mortgages and corporates
# together). The board lists ten such funds with their size (AUM), fee (expense
# ratio), returns and yields. There are no parameters.
#
# Units matter here. **Every `*_pct` field and `expense_ratio` is in percent**
# (0.14 means 0.14%), `aum` is in US dollars, and `credit_spread_bps` is in basis
# points. There are no freshness fields at any level, so we print each fund's
# `latest_bar_date` (the last daily price) and `treasury_curve_date` (the
# Treasury curve used for the spread) ourselves.
#
# **The two dates can differ.** `treasury_curve_date` can be older than
# `latest_bar_date` because the data provider publishes Treasury curve values
# later than it publishes prices. When that happens, the spreads use the most
# recent curve the provider has published while the price bars are newer. The
# cell below prints both dates and the gap between them, so you can see which
# curve the spreads use.
#
# One definition is missing. The API does not say whether `return_1y_pct` and
# `return_ytd_pct` include **distributions** (the interest a bond fund pays
# out). A *total* return includes them; a *price* return does not. For bond
# funds that yield 4% to 7% a year the two differ by several points, so this
# notebook calls them "returns as reported". One thing holds either way: a
# negative reported return means the **price** fell, because distributions can
# only add to a return.
#
# The board's response wraps an upstream service, like the news (`data.ok`,
# then `data.data.etfs`), so it too can answer HTTP 200 with an error inside.
# The call uses `sf_try`: if the board cannot be read, the bond cells print
# short notes and the rest of the notebook carries on.

# %%
bond_payload = sf_try("/api/v1/bond/etfs")
bonds_ok = bond_payload is not None
if bonds_ok:
    show_freshness(bond_payload, "Bond ETFs:")
bonds_raw = to_frame(bond_payload, "bond_etfs") if bonds_ok else pd.DataFrame()
if not bonds_ok:
    display(Markdown("> **No bond board this run.** The bond cells below print short notes instead of charts, and "
                     "extension 7.3 skips its bond check. Run the notebook again later: the cells need no change."))
elif bonds_raw.empty:
    display(Markdown("> The bond board is empty right now. Try again later."))
else:
    print(f"Latest price bars: {bonds_raw['latest_bar_date'].min()} to {bonds_raw['latest_bar_date'].max()}; "
          f"Treasury curve date: {', '.join(sorted(set(bonds_raw['treasury_curve_date'].astype(str))))}.")
    curve_lag = (pd.to_datetime(bonds_raw["latest_bar_date"], errors="coerce")
                 - pd.to_datetime(bonds_raw["treasury_curve_date"], errors="coerce")).dt.days
    lagged = curve_lag[curve_lag > 0]
    if not lagged.empty:
        span = f"{int(lagged.min())}" if lagged.min() == lagged.max() else f"{int(lagged.min())} to {int(lagged.max())}"
        print(f"For {len(lagged)} of {int(curve_lag.notna().sum())} funds the Treasury curve date is {span} calendar "
              "day(s) before the latest price bar. The data provider publishes Treasury curve values later than "
              "prices, so those spreads use the most recent curve it has published (treasury_curve_date).")
    elif curve_lag.eq(0).all():
        print("Every fund's Treasury curve date matches its latest price bar.")

# %% [markdown]
# **Raw preview.**

# %%
bonds_raw.head()

# %% [markdown]
# ### Cleaning the bond board
#
# 1. **Keep the documented columns.** We leave out `avg_volume`, which is always
#    empty, and keep the provenance fields (`*_source`) for the audit.
# 2. **De-duplicate on `ticker`.**
# 3. **Coerce numbers and parse dates.**
# 4. **Check an identity.** The API defines
#    `credit_spread_bps = (sec_yield_30d_pct − matched_treasury_yield_pct) × 100`.
#    We recompute it; a gap above about 0.1 bp would mean a contract change
#    (the API rounds the spread to one decimal).
# 5. **Add derived columns:** `price_vs_last_nav_pct` (the last close against
#    the last NAV the provider sent), the yearly fee per $10,000 invested, and
#    the fund's age. Careful with the first one. The board does not send the
#    NAV's date, and the NAV comes from a quote provider that usually lags the
#    price by a day. So `last_close / nav − 1` compares today's price with
#    yesterday's NAV, and it mostly measures the last day's price move, not a
#    premium or discount to the bonds inside. The cell prints how closely it
#    tracks `pct_change_1d`. `lag_adjusted_vs_nav_pct` is a rough,
#    clearly labelled correction that assumes the NAV is exactly one day older
#    than the close and moved with it: `last_close / (nav × (1 + pct_change_1d / 100)) − 1`.
# 6. **NaN policy.** We count gaps and keep them; each chart drops only the
#    funds it cannot place, and says so.

# %%
BOND_ID = ["ticker", "name", "short_label", "etf_company", "asset_class", "category", "fund_category", "market_region"]
BOND_NUM = ["aum", "expense_ratio", "nav", "last_close", "pct_change_1d", "return_1y_pct", "return_ytd_pct", "volume",
            "sec_yield_30d_pct", "ytm_proxy_pct", "matched_treasury_yield_pct", "avg_maturity_years", "credit_spread_bps"]
BOND_DATES = ["latest_bar_date", "inception_date", "treasury_curve_date"]
BOND_META = ["aum_source", "expense_ratio_source", "nav_source", "metadata_completeness"]

bonds = pick(bonds_raw, BOND_ID + BOND_NUM + BOND_DATES + BOND_META)
bonds["ticker"] = bonds["ticker"].astype(str)
n_before = len(bonds)
bonds = bonds.drop_duplicates(subset="ticker", keep="first").reset_index(drop=True)
missing_before = bonds[BOND_NUM].isna().sum()
for col in BOND_NUM:
    bonds[col] = pd.to_numeric(bonds[col], errors="coerce")
for col in BOND_DATES:
    bonds[col] = pd.to_datetime(bonds[col], errors="coerce")
spread_gap = ((bonds["sec_yield_30d_pct"] - bonds["matched_treasury_yield_pct"]) * 100 - bonds["credit_spread_bps"]).abs()
bonds["price_vs_last_nav_pct"] = 100 * (bonds["last_close"] / bonds["nav"] - 1)          # NAV date not sent; it lags
bonds["lag_adjusted_vs_nav_pct"] = 100 * (bonds["last_close"] / (bonds["nav"] * (1 + bonds["pct_change_1d"] / 100)) - 1)
bonds["fee_per_10k_usd"] = bonds["expense_ratio"] / 100 * 10_000
bonds["age_years"] = (TODAY.tz_localize(None) - bonds["inception_date"]).dt.days / 365.25

print(f"{n_before} funds -> {len(bonds)} after de-duplication; "
      f"{int((bonds[BOND_NUM].isna().sum() - missing_before).sum())} values became NaN when coerced.")
if spread_gap.notna().any():
    print(f"Credit-spread identity: largest gap {spread_gap.max():.2f} bp "
          f"({'rounding only' if spread_gap.max() <= 0.1 else 'larger than rounding: check the contract'}).")
else:
    print("Credit-spread identity: no funds to check (no fund has all three numbers).")
nav_pair = bonds[["price_vs_last_nav_pct", "pct_change_1d"]].dropna()
if len(nav_pair) >= 3 and nav_pair.nunique().min() > 1:
    r_nav = float(np.corrcoef(nav_pair["price_vs_last_nav_pct"], nav_pair["pct_change_1d"])[0, 1])
    print(f"Price vs last NAV: {nav_pair['price_vs_last_nav_pct'].min():+.2f}% to {nav_pair['price_vs_last_nav_pct'].max():+.2f}% "
          f"across {len(nav_pair)} funds; correlation with the last day's price change = {r_nav:+.2f}"
          + (" - it mostly tracks the day's move, so the NAV is probably from an earlier day." if r_nav > 0.7 else "."))
gaps = bonds[BOND_NUM].isna().sum()
if bonds.empty:
    display(Markdown("> No funds, so there is nothing to audit."))
elif (gaps > 0).any():
    display(pd.DataFrame({"missing": gaps[gaps > 0]}).rename_axis("column"))
else:
    display(Markdown("> No numeric gaps: every fund has every number."))
if not bonds.empty:
    display(bonds[["ticker", *BOND_META]].set_index("ticker").T)

# %% [markdown]
# ### Chart: size versus 1-year return
#
# Each bubble is one fund. Across is its size (AUM) on a **log axis**, because
# the biggest fund is many times the smallest. Up and down is the 1-year
# return. Bubble **area** shows the average maturity of the fund's bonds:
# longer maturities make a bond fund more sensitive to interest rates (the key
# on the right shows two reference sizes). Colour shows the fund category, with
# at most three colours, as the theme asks. The category colours are slots that
# no market uses, so they never read as "US" or "China". Extension 7.4 puts
# maturity itself on the x axis.

# %%
CATEGORY_SLOTS = ["US Investment Grade", "US High Yield", "US Broad Market"]
CATEGORY_COLORS = dict(zip(CATEGORY_SLOTS, SERIES[4:7]))      # slots no market uses: pink, green, purple
bonds["category_group"] = bonds["category"].where(bonds["category"].isin(CATEGORY_SLOTS), "Other")
CATEGORY_COLORS["Other"] = MUTED

plot = bonds.dropna(subset=["aum", "return_1y_pct", "avg_maturity_years"])
plot = plot[plot["aum"] > 0]
print(f"Plotting {len(plot)} of {len(bonds)} funds ({len(bonds) - len(plot)} dropped for a missing size, return or maturity).")
if plot.empty:
    display(Markdown("> No fund has all three numbers, so there is nothing to plot."))
else:
    n_size, rho_size, lo_size, hi_size = spearman_ci(np.log10(plot["aum"]), plot["return_1y_pct"], min_n=5)
    n_mat, rho_mat, lo_mat, hi_mat = spearman_ci(plot["avg_maturity_years"], plot["return_1y_pct"], min_n=5)
    sizeref = 2.0 * plot["avg_maturity_years"].max() / 54 ** 2      # the longest maturity gets a ~54 px bubble
    fig = go.Figure()
    for group in [g for g in [*CATEGORY_SLOTS, "Other"] if (plot["category_group"] == g).any()]:
        part = plot[plot["category_group"] == group]
        fig.add_trace(go.Scatter(
            x=part["aum"], y=part["return_1y_pct"], mode="markers", name=group,
            marker=dict(size=part["avg_maturity_years"], sizemode="area", sizeref=sizeref, sizemin=6,
                        color=CATEGORY_COLORS[group], opacity=0.8, line=dict(width=1.5, color=SURFACE)),
            customdata=np.column_stack([part["ticker"], part["name"], part["aum"].map(money), part["avg_maturity_years"],
                                        part["return_ytd_pct"], part["expense_ratio"], part["sec_yield_30d_pct"]]),
            hovertemplate=("<b>%{customdata[0]}</b> · %{customdata[1]}<br>AUM %{customdata[2]} · 1-year return "
                           "%{y:+.2f}% (as reported)<br>YTD %{customdata[4]:+.2f}% · average maturity %{customdata[3]:.1f} years"
                           "<br>Expense ratio %{customdata[5]:.2f}% · 30-day SEC yield %{customdata[6]:.2f}%<extra></extra>")))
    to_label = pd.concat([plot.nlargest(1, "aum"), plot.nlargest(1, "return_1y_pct"), plot.nsmallest(1, "return_1y_pct"),
                          plot.nlargest(1, "avg_maturity_years")]).drop_duplicates(subset="ticker")
    for _, row in to_label.iterrows():
        radius = np.sqrt(max(row["avg_maturity_years"], 0) / (2 * sizeref))            # rendered bubble radius in px
        fig.add_annotation(x=np.log10(row["aum"]), y=row["return_1y_pct"], text=f"{row['ticker']} · {row['avg_maturity_years']:.0f}y",
                           showarrow=True, arrowhead=0, arrowcolor=MUTED, ax=40, ay=-34, standoff=max(radius, 3) + 2,
                           font=dict(size=11, color=INK_2))
    fig.add_hline(y=0, line=dict(color=AXIS, width=1))
    lo_x, hi_x = np.log10(plot["aum"].min()), np.log10(plot["aum"].max())
    ticks = [s * 10.0 ** e for e in range(int(np.floor(lo_x)), int(np.ceil(hi_x)) + 1) for s in (1, 2, 5)
             if lo_x - 0.2 <= np.log10(s * 10.0 ** e) <= hi_x + 0.2]
    fig.update_xaxes(type="log", title_text="Assets under management (USD, log scale)", tickvals=ticks,
                     ticktext=[money(t, 0) for t in ticks])
    fig.update_yaxes(title_text="1-year return as reported (%)", ticksuffix="%", zeroline=False)
    # Size key: two reference bubbles drawn in the right margin, in pixels, with the same area rule as the data.
    candidates = [y for y in (1, 2, 5, 10, 20, 30) if y <= plot["avg_maturity_years"].max()]
    key_years = [candidates[-3], candidates[-1]] if len(candidates) >= 3 else candidates[-2:]
    for k, years in enumerate(key_years):
        radius, y_key = np.sqrt(years / (2 * sizeref)), 0.82 - 0.3 * k
        fig.add_shape(type="circle", xref="paper", yref="paper", xsizemode="pixel", ysizemode="pixel", xanchor=1,
                      yanchor=y_key, x0=60 - radius, x1=60 + radius, y0=-radius, y1=radius,
                      line=dict(color=MUTED, width=1), fillcolor="rgba(137,135,129,0.25)")
        fig.add_annotation(x=1, xref="paper", y=y_key, yref="paper", xanchor="left", xshift=92, showarrow=False,
                           text=f"{years} years", font=dict(size=11, color=INK_2))
    if key_years:
        fig.add_annotation(x=1, xref="paper", y=1.0, yref="paper", xanchor="left", xshift=24, yanchor="bottom",
                           showarrow=False, text="Bubble area =<br>average maturity", align="left",
                           font=dict(size=11, color=INK_2))
    worst = plot.loc[plot["return_1y_pct"].idxmin()]
    size_ci = f"[{lo_size:+.2f}, {hi_size:+.2f}]"
    maturity_clear = pd.notna(rho_mat) and abs(rho_mat) >= 0.5 and (pd.isna(rho_size) or abs(rho_mat) > abs(rho_size))
    if pd.isna(rho_size):
        headline = (f"{worst['ticker']} has the weakest reported 1-year return ({worst['return_1y_pct']:+.1f}%); too few "
                    "funds to relate size and return")
    elif lo_size <= 0 <= hi_size:                     # the size interval includes 0: say so, then add maturity if it is clear
        headline = f"Fund size says little about 1-year return (ρ = {rho_size:+.2f} {size_ci})"
        if maturity_clear:
            headline += f"; the big long-maturity bubbles sit {'lowest' if rho_mat < 0 else 'highest'}"
    else:                                             # size is related too: state both correlations, rank neither
        headline = (f"Over 1 year, bigger funds did {'better' if rho_size > 0 else 'worse'}: ρ(log AUM, return) = "
                    f"{rho_size:+.2f} {size_ci}; ρ(maturity, return) = {rho_mat:+.2f}")
    title_spec, title_px = chart_title(
        headline, f"{int((plot['return_1y_pct'] < 0).sum())} of {len(plot)} fund prices are down over 1 year (reported "
                  "return below 0) · bubble area = average maturity · "
                  f"Spearman ρ(log AUM, return) = {rho_size:+.2f} {size_ci}, "
                  f"ρ(maturity, return) = {rho_mat:+.2f} [{lo_mat:+.2f}, {hi_mat:+.2f}], n = {n_mat}")
    fig.update_layout(title=title_spec, height=title_px + 110 + 330, margin=dict(t=title_px, b=110, r=160),
                      legend=dict(LEGEND_BELOW, itemsizing="constant"))
    fig.show()
    display(plot[["ticker", "category", "aum", "return_1y_pct", "return_ytd_pct", "avg_maturity_years", "sec_yield_30d_pct",
                  "credit_spread_bps"]].sort_values("return_1y_pct").style.format(
        {"aum": money, "return_1y_pct": "{:+.2f}%", "return_ytd_pct": "{:+.2f}%", "avg_maturity_years": "{:.1f} y",
         "sec_yield_30d_pct": "{:.2f}%", "credit_spread_bps": "{:+.0f} bp"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Further right is a bigger fund; each gridline step on a
# log axis is a multiple, not a fixed amount. Higher is a better reported 1-year
# return (see the note on distributions above).
# Watch the big bubbles: they are long-maturity funds. When interest rates rise,
# existing bonds lose value, and long bonds lose the most. So if the big bubbles
# sit low, the year was driven by rates. If the high-yield funds (green) sit
# apart from the investment-grade ones (pink), credit risk mattered too.
# Spearman's ρ summarises each relationship from −1 to +1; with ten funds the
# intervals in brackets are wide. The title leads with what the axes show
# (size against return) and mentions maturity only when its link is clear and
# stronger than the size link.
#
# **Caveats.**
#
# - Ten funds is a tiny sample. The ρ values describe these funds, not bonds in
#   general, and they are not a forecast.
# - Maturity and category overlap: high-yield funds are also short-maturity
#   funds, so the chart cannot separate the two effects (see extension 7.4).
# - AUM tells you how popular a fund is, not how good it is.

# %% [markdown]
# ### Chart: year-to-date returns
#
# The same funds ranked by their return since 1 January, with the same category
# colours as the bubble chart.

# %%
ytd = bonds.dropna(subset=["return_ytd_pct"]).sort_values("return_ytd_pct")
if ytd.empty:
    display(Markdown("> No YTD returns to chart."))
else:
    fig = go.Figure()
    for group in [g for g in [*CATEGORY_SLOTS, "Other"] if (ytd["category_group"] == g).any()]:
        part = ytd[ytd["category_group"] == group]
        fig.add_trace(go.Bar(
            x=part["return_ytd_pct"], y=part["ticker"], orientation="h", name=group,
            marker=dict(color=CATEGORY_COLORS[group]), text=part["return_ytd_pct"].map(lambda v: f"{v:+.1f}%"),
            textposition="outside", textfont=dict(size=11, color=INK_2), cliponaxis=False,
            customdata=np.column_stack([part["name"], part["return_1y_pct"], part["pct_change_1d"]]),
            hovertemplate=("<b>%{y}</b> · %{customdata[0]}<br>YTD %{x:+.2f}% · 1 year %{customdata[1]:+.2f}%"
                           " · last day %{customdata[2]:+.2f}%<extra></extra>")))
    span = ytd["return_ytd_pct"].abs().max()
    fig.update_xaxes(title_text="Return since 1 January, as reported (%)", ticksuffix="%",
                     range=[min(0, ytd["return_ytd_pct"].min()) - span * 0.25, max(0, ytd["return_ytd_pct"].max()) + span * 0.25])
    fig.update_yaxes(type="category", categoryorder="array", categoryarray=list(ytd["ticker"]), title_text=None)
    worst, best = ytd.iloc[0], ytd.iloc[-1]
    n_down = int((ytd["return_ytd_pct"] < 0).sum())
    title_spec, title_px = chart_title(
        f"{n_down} of {len(ytd)} bond ETF prices are down this year; {worst['ticker']} is the weakest at "
        f"{worst['return_ytd_pct']:+.1f}% as reported",
        f"Best: {best['ticker']} ({best['return_ytd_pct']:+.1f}%) · prices as of {ytd['latest_bar_date'].max():%Y-%m-%d} · "
        "the API does not say whether these returns include distributions; a negative one means the price fell "
        "either way")
    fig.update_layout(title=title_spec, height=title_px + 110 + max(180, 34 * len(ytd)), margin=dict(t=title_px, b=110),
                      barmode="overlay", legend=LEGEND_BELOW)
    fig.add_vline(x=0, line=dict(color=AXIS, width=1))
    fig.show()
    display(ytd[["ticker", "short_label", "category", "return_ytd_pct", "return_1y_pct", "pct_change_1d", "latest_bar_date"]]
            .iloc[::-1].style.format({"return_ytd_pct": "{:+.2f}%", "return_1y_pct": "{:+.2f}%", "pct_change_1d": "{:+.2f}%",
                                      "latest_bar_date": "{:%Y-%m-%d}"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Bars to the left of the line have a negative reported
# return: the fund's price fell this year. Bars to the right have a positive
# one. Long bars in one colour point to a whole segment moving together.
# Compare this ranking with the bubble chart: a fund that ranks low on both
# horizons has had a consistently hard year.
#
# **Caveats.**
#
# - Year-to-date windows have different lengths depending on the date you run
#   this, so compare YTD numbers only within one run.
# - The API does not say whether these returns include distributions. For bond
#   funds yielding 4% to 7% a year that changes a return by several points, so
#   a fund whose price fell may still have paid its holders more in interest
#   than it lost in price. Extension 7.4 shows one way to look for a hint in
#   the data.
#
# ### The expense ratio table
#
# Fees compound. The **expense ratio** is charged every year on the whole
# balance, so it is the one number you can be sure of before you invest. We
# turn it into dollars: the yearly fee on $10,000. The 30-day SEC yield is
# already after fees, so we do not subtract the fee again.

# %%
fees = bonds.sort_values(["expense_ratio", "ticker"])[
    ["ticker", "short_label", "etf_company", "category", "expense_ratio", "fee_per_10k_usd", "aum", "sec_yield_30d_pct",
     "credit_spread_bps", "pct_change_1d", "price_vs_last_nav_pct", "lag_adjusted_vs_nav_pct", "age_years"]]
if fees.dropna(subset=["expense_ratio"]).empty:
    display(Markdown("> No funds with an expense ratio to list."))
else:
    priced = fees.dropna(subset=["expense_ratio"])
    cheap, dear = priced.iloc[0], priced.iloc[-1]
    display(Markdown(f"> Cheapest: **{cheap['ticker']}** at {cheap['expense_ratio']:.2f}% (${cheap['fee_per_10k_usd']:,.0f} a "
                     f"year on $10,000). Most expensive: **{dear['ticker']}** at {dear['expense_ratio']:.2f}% "
                     f"(${dear['fee_per_10k_usd']:,.0f}). Over ten years that gap is about "
                     f"${(dear['fee_per_10k_usd'] - cheap['fee_per_10k_usd']) * 10:,.0f} on $10,000, before compounding."))
    display(fees.style.format({"expense_ratio": "{:.2f}%", "fee_per_10k_usd": "${:,.0f}", "aum": money,
                               "sec_yield_30d_pct": "{:.2f}%", "credit_spread_bps": "{:+.0f} bp", "pct_change_1d": "{:+.2f}%",
                               "price_vs_last_nav_pct": "{:+.2f}%", "lag_adjusted_vs_nav_pct": "{:+.2f}%",
                               "age_years": "{:.0f} y"}, na_rep="–")
            .bar(subset=["expense_ratio"], color=SEQUENTIAL[2], vmin=0).hide(axis="index"))

# %% [markdown]
# **How to read this.** Funds are sorted from cheapest to most expensive; the
# blue bar shows the fee. The other columns put the fee in context: a higher
# yield or spread usually comes with more credit risk. Read
# `price_vs_last_nav_pct` next to `pct_change_1d`: when the two move together
# (as the cleaning cell's correlation shows), the gap is mostly the last day's
# price move against an older NAV, not a premium or discount to the bonds
# inside. The board does not send the NAV's date, so it cannot settle that.
# `lag_adjusted_vs_nav_pct` is only an approximation under a one-day-lag
# assumption; do not read small values of either column as a real premium.
#
# **Caveats for the bond section.**
#
# - `credit_spread_bps` can be negative (for AGG and several investment-grade
#   funds). The SEC yield and the matched Treasury yield are measured in
#   different ways and on different dates (`treasury_curve_date`, which can be
#   a few days older than `latest_bar_date` because the provider publishes
#   Treasury curve values later than prices), and AGG holds Treasuries itself.
#   Read the spread as a rough gauge, not a precise price of credit risk.
# - The board covers ten US funds only: it describes the US credit and rates
#   complex, not every bond market.
# - Fund metadata (AUM, fees, NAV) comes from a quote provider (`*_source`) and
#   can lag the price by a day or more.

# %% [markdown]
# ## 7. Extensions (beyond the raw API)
#
# *These sections go beyond a single endpoint call.* They combine endpoints and
# add statistics. Everything here is descriptive: it explains differences
# between articles, markets or funds today. Nothing here forecasts prices or
# recommends a trade. Extensions 7.1 and 7.2 need the news feed; when it is
# down they say so and make no requests.
#
# ### 7.1 News tone across the four markets
#
# We read the news for the other three markets (3 requests, with `sf_try`),
# clean it with the same `clean_news` function, and compare the mix of labels.
# The mix is a **part-to-whole** question, so the chart is a stacked 100% bar
# per market.

# %%
news_by_market = {MARKET: news} if news_ok else {}
news_models = {MARKET: method.get("sentiment_source") or "not sent"}       # which sentiment model each market uses
if not news_ok:
    print("Skipped: the news feed is unavailable, so the other markets are not requested either.")
elif not COMPARE_MARKETS:
    print("COMPARE_MARKETS is False: skipped.")
else:
    for m in MARKETS:
        if m == MARKET:
            continue
        payload = sf_try(f"/api/v1/markets/{m}/news", limit=NEWS_LIMIT)
        if payload is None:
            continue
        show_freshness(payload, f"{MARKET_NAMES[m]} news:")
        frame = clean_news(to_frame(payload, "news"), f"{m} news", report=False)
        frame["tokens"] = frame["title"].map(tokenise)
        news_models[m] = dig(payload, "data", "methodology", "sentiment_source", default="not sent")
        news_by_market[m] = frame

tone_rows = []
for m in [m for m in MARKETS if m in news_by_market]:
    frame = news_by_market[m]
    s = frame[frame["scored"]] if not frame.empty else frame
    n, mean, lo, hi = mean_ci(s["sentiment_score"])
    mix = s["sentiment_label"].value_counts().reindex(SENTIMENT_ORDER, fill_value=0)
    span = (s["published"].max() - s["published"].min()).total_seconds() / 3600 if n else np.nan
    top_tokens = Counter(t for toks in frame.drop_duplicates("title")["tokens"] for t in set(toks)).most_common(5)
    pos_low, pos_high = wilson(int(mix["positive"]), n)
    tone_rows.append({"market": m, "articles": len(frame), "scored": n, "hours_covered": span,
                      **{f"share_{k}": mix[k] / n if n else np.nan for k in SENTIMENT_ORDER},
                      "positive_ci_low": pos_low, "positive_ci_high": pos_high,
                      "mean_score": mean, "ci_low": lo, "ci_high": hi,
                      "top_tokens": " · ".join(t for t, _ in top_tokens),
                      "sentiment_model": news_models.get(m, "not sent")})
tone = pd.DataFrame(tone_rows, columns=["market", "articles", "scored", "hours_covered", "share_positive",
                                        "positive_ci_low", "positive_ci_high", "share_neutral", "share_negative",
                                        "mean_score", "ci_low", "ci_high", "top_tokens", "sentiment_model"]).set_index("market")
if tone.empty:
    display(Markdown("> No market's news could be read, so there is nothing to compare."))
else:
    display(tone.style.format({"hours_covered": "{:.1f}", "share_positive": "{:.0%}", "positive_ci_low": "{:.0%}",
                               "positive_ci_high": "{:.0%}", "share_neutral": "{:.0%}", "share_negative": "{:.0%}",
                               "mean_score": "{:+.2f}", "ci_low": "{:+.2f}", "ci_high": "{:+.2f}"}, na_rep="–"))

# %%
if tone.empty or tone["scored"].sum() == 0:
    display(Markdown("> No scored articles in any market, so there is no mix to chart."))
else:
    tone_plot = tone[tone["scored"] > 0]
    names = [MARKET_NAMES[m] for m in tone_plot.index][::-1]
    fig = go.Figure()
    for label in SENTIMENT_ORDER:
        shares = tone_plot[f"share_{label}"][::-1]
        cis = [wilson(int(round(v * n)), int(n)) for v, n in zip(shares.fillna(0), tone_plot["scored"][::-1])]
        fig.add_trace(go.Bar(
            x=shares, y=names, orientation="h", name=label.title(), marker=dict(color=SENTIMENT_COLORS[label]),
            text=[f"{v:.0%}" if v >= 0.06 else "" for v in shares.fillna(0)], textposition="inside", insidetextanchor="middle",
            textfont=dict(color="white" if label != "neutral" else INK, size=12),
            customdata=np.array([[lo_, hi_, n] for (lo_, hi_), n in zip(cis, tone_plot["scored"][::-1])], dtype=float),
            hovertemplate=(f"%{{y}}: %{{x:.0%}} {label} (95% Wilson CI %{{customdata[0]:.0%}} to %{{customdata[1]:.0%}},"
                           " n = %{customdata[2]:.0f})<extra></extra>")))
    for name, (_, row) in zip(names, tone_plot[::-1].iterrows()):
        ci = f" [{row['ci_low']:+.2f}, {row['ci_high']:+.2f}]" if row["scored"] >= 5 else " (too few for a CI)"
        fig.add_annotation(x=1.01, xref="paper", y=name, yref="y", showarrow=False, xanchor="left",
                           text=f"mean {row['mean_score']:+.2f}{ci}", font=dict(size=11, color=INK_2))
    n_plotted = len(tone_plot)
    n_clear = int(((tone_plot["ci_low"] > 0) | (tone_plot["ci_high"] < 0)).sum())   # mean tone distinguishable from 0
    if n_plotted == 1:
        only = tone_plot.iloc[0]
        title = (f"Label mix of the newest {int(only['scored'])} scored {MARKET_NAMES[tone_plot.index[0]]} articles: "
                 f"{only['share_positive']:.0%} positive, {only['share_neutral']:.0%} neutral, "
                 f"{only['share_negative']:.0%} negative")
        ranking = ""
    else:
        title = "Label mix of each market's newest scored articles (different models, so do not rank the markets)"
        best = tone_plot["share_positive"].idxmax()
        others = tone_plot.drop(index=best)
        clears = bool(tone_plot.loc[best, "positive_ci_low"] > others["positive_ci_high"].max())
        ranking = (f" · {MARKET_NAMES[best]} has the largest positive share, and its 95% interval clears every other "
                   "market's, but the models differ" if clears else
                   " · the positive shares' 95% intervals overlap, so no market stands out")
    title_spec, title_px = chart_title(
        title, f"{n_clear} of {n_plotted} market(s) have a mean tone whose 95% CI excludes 0{ranking} · right: mean "
               "score with 95% CI · each market uses its own sentiment model and source mix")
    fig.update_layout(barmode="stack", title=title_spec, height=title_px + 110 + max(160, 55 * n_plotted),
                      margin=dict(t=title_px, r=200, b=110), legend=dict(LEGEND_BELOW, traceorder="normal"))
    fig.update_xaxes(range=[0, 1], tickformat=".0%", title_text="Share of scored articles (%)")
    fig.update_yaxes(ticks="")
    fig.show()

# %% [markdown]
# **How to read this.** Each bar splits one market's latest articles into
# positive (blue), neutral (grey) and negative (red); the three parts add up to
# 100%. On the right, the mean score and its 95% interval. Hover over a bar
# part for its 95% **Wilson** interval: with about 40 to 50 articles a share of
# 40% could easily be anywhere from about 25% to 55%. The table above lists the
# numbers (with the Wilson interval of the positive share), how many hours each
# batch covers, the five most frequent headline tokens (character bigrams for
# China, Japan and Hong Kong) and the sentiment model each market uses.
#
# The title is descriptive on purpose. It does not name a "most positive"
# market. The subtitle says so only if one market's positive-share interval
# clears all the others, and even then it repeats the warning below.
#
# **Caveats.** Each market uses a **different sentiment model and source mix**
# (English media in the US, Chinese media in China, filings plus media in Japan
# and Hong Kong). The batches also cover different time spans. So compare each
# market with its own history, not with the others.
#
# ### 7.2 Does news tone line up with the day's price move?
#
# Notebook 01 teaches the **sector** endpoint: every stock's one-day change. We
# fetch it for `MARKET` (1 request) and join it on `ticker` with the mean
# sentiment of each ticker's articles. The question is descriptive: across
# tickers, are stocks with more positive news also the ones that rose?
#
# Two cleaning steps come first:
#
# - **Same day only.** The news batch is simply the newest `NEWS_LIMIT`
#   articles, whatever their date, while the prices describe one session
#   (`as_of_date`). An article from the next morning reacts to the move; one
#   from two days earlier may already be in the price. So we keep only articles
#   whose publication date, on the exchange's clock, is the session date, and
#   count the ones we drop.
# - **Winsorise the price change.** One-day changes have heavy tails (a stock
#   can jump 50% on news), and news covers big movers most. We clip the change
#   at the whole market's 1st and 99th percentile, so one or two extreme moves
#   cannot drive the line. Clipped points are drawn as triangles at the clip
#   level; hover and the table keep the raw value.
#
# We report **Spearman's ρ** (rank correlation, robust to outliers, on the raw
# change) with a 95% interval, and an OLS slope on the winsorised change with
# **HC3** robust standard errors (they stay valid when the noise is uneven
# across stocks) and t-based intervals, which suit a small sample.

# %%
joined = pd.DataFrame()
if not news_ok or not JOIN_PRICES or by_ticker.empty:
    display(Markdown("> Skipped (the news feed is unavailable, JOIN_PRICES is False, or no ticker was mentioned)."))
else:
    sector_payload = sf_try(f"/api/v1/markets/{MARKET}/sector")
    if sector_payload is not None:
        show_freshness(sector_payload, "Sector snapshot:")
        session = str(dig(sector_payload, "data", "as_of_date"))
        prices = pick(to_frame(sector_payload, "sector"), ["ticker", "name", "sector", "change_pct", "sector_mean_1d"])
        prices["ticker"] = prices["ticker"].astype(str)
        prices = prices.drop_duplicates(subset="ticker")
        for col in ["change_pct", "sector_mean_1d"]:
            prices[col] = pd.to_numeric(prices[col], errors="coerce")
        # Same day only: the article's date on the exchange clock must be the price session's date.
        local_day = news["published"].dt.tz_convert(MARKET_TZ[MARKET]).dt.strftime("%Y-%m-%d")
        same_day_ids = set(news.loc[local_day == session, "article_id"])
        print(f"{len(news)} articles in the batch; {len(same_day_ids)} were published on the price session's date "
              f"({session}, {MARKET_TZ[MARKET]} clock) and are kept; {len(news) - len(same_day_ids)} from other days are left "
              "out (earlier ones may already be in the price, later ones react to it).")
        day_mentions = mentions[mentions["article_id"].isin(same_day_ids)]
        day_ticker = (day_mentions.groupby("ticker")
                      .agg(articles=("article_id", "nunique"), mean_sentiment=("score_if_scored", "mean")).reset_index())
        joined = day_ticker.merge(prices, on="ticker", how="inner", validate="one_to_one").dropna(
            subset=["mean_sentiment", "change_pct"])
        joined["change_pct_100"] = joined["change_pct"] * 100            # fraction -> percent for the chart
        # Winsorise at the whole market's 1st / 99th percentile (thousands of stocks: a stable yardstick).
        clip_lo, clip_hi = (prices["change_pct"].quantile([0.01, 0.99]) * 100).tolist()
        joined["change_w"] = joined["change_pct_100"].clip(clip_lo, clip_hi)
        joined["clipped"] = np.sign(joined["change_pct_100"] - joined["change_w"]).astype(int)   # +1 above, −1 below
        print(f"{len(day_ticker)} tickers mentioned that day; {len(joined)} found on the sector snapshot with a price "
              f"change and a score. Winsorised at the market's 1st / 99th percentile ({clip_lo:+.1f}% / {clip_hi:+.1f}%, "
              f"from {int(prices['change_pct'].notna().sum()):,} stocks): {int((joined['clipped'] != 0).sum())} of "
              f"{len(joined)} joined tickers clipped.")

# %%
if len(joined) < 8:
    display(Markdown("> Fewer than 8 tickers joined, too few for a correlation. When the feed is up, raise `NEWS_LIMIT` "
                     "or try another market."))
else:
    n, rho, lo, hi = spearman_ci(joined["mean_sentiment"], joined["change_pct_100"])
    ols = sm.OLS(joined["change_w"], sm.add_constant(joined["mean_sentiment"])).fit(cov_type="HC3", use_t=True)
    slope, se = ols.params["mean_sentiment"], ols.bse["mean_sentiment"]
    ci_lo, ci_hi = ols.conf_int().loc["mean_sentiment"]
    grid_x = np.linspace(joined["mean_sentiment"].min(), joined["mean_sentiment"].max(), 50)
    pred = ols.get_prediction(sm.add_constant(pd.Series(grid_x, name="mean_sentiment"))).summary_frame(alpha=0.05)
    color = MARKET_COLORS[MARKET]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=np.r_[grid_x, grid_x[::-1]], y=np.r_[pred["mean_ci_upper"], pred["mean_ci_lower"][::-1]],
                             fill="toself", fillcolor="rgba(137,135,129,0.18)", line=dict(width=0), name="95% band of the line",
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=grid_x, y=pred["mean"], mode="lines", line=dict(color=INK, width=2), name="OLS line",
                             hoverinfo="skip"))
    for is_clipped, part in joined.groupby(joined["clipped"] != 0):
        fig.add_trace(go.Scatter(
            x=part["mean_sentiment"], y=part["change_w"], mode="markers",
            name="Clipped at the 1st / 99th percentile (raw in hover)" if is_clipped else "Ticker (size = article count)",
            marker=dict(size=7 + 3 * np.sqrt(part["articles"].astype(float)), color=color, opacity=0.8,
                        symbol=np.where(part["clipped"] > 0, "triangle-up", "triangle-down") if is_clipped else "circle",
                        line=dict(width=1, color=SURFACE)),
            customdata=np.column_stack([part["ticker"], part["name"], part["articles"], part["change_pct_100"]]),
            hovertemplate=("<b>%{customdata[0]}</b> · %{customdata[1]}<br>Mean sentiment %{x:+.2f} over %{customdata[2]} "
                           "article(s)<br>One-day change %{customdata[3]:+.2f}%"
                           + (" (drawn at the clip level)" if is_clipped else "") + "<extra></extra>")))
    for _, row in joined.reindex(joined["change_pct_100"].abs().sort_values(ascending=False).index).head(3).iterrows():
        fig.add_annotation(x=row["mean_sentiment"], y=row["change_w"], text=row["ticker"], showarrow=True, arrowhead=0,
                           arrowcolor=MUTED, ax=24, ay=-20, font=dict(size=11, color=INK_2))
    fig.add_hline(y=0, line=dict(color=AXIS, width=1))
    fig.add_vline(x=0, line=dict(color=AXIS, width=1))
    fig.update_xaxes(title_text="Mean sentiment of the ticker's same-day articles (−1 to +1)", tickformat="+.1f")
    fig.update_yaxes(title_text="One-day price change (%, winsorised)", ticksuffix="%", zeroline=False)
    strength = "lines up with" if lo > 0 else "runs against" if hi < 0 else "is only loosely related to"
    n_clipped = int((joined["clipped"] != 0).sum())
    title_spec, title_px = chart_title(
        f"Across tickers, same-day news tone {strength} the day's price change: Spearman ρ = {rho:+.2f} "
        f"[{lo:+.2f}, {hi:+.2f}]",
        f"{n} tickers · OLS slope {slope:+.2f} pp per +1 sentiment (HC3 s.e. {se:.2f}; 95% CI {ci_lo:+.2f} to "
        f"{ci_hi:+.2f}, t-based) · price session {session} · {n_clipped} clipped · dot size = article count")
    fig.update_layout(title=title_spec, height=title_px + 110 + 320, margin=dict(t=title_px, b=110), legend=LEGEND_BELOW)
    fig.show()
    display(joined[["ticker", "name", "sector", "articles", "mean_sentiment", "change_pct", "clipped", "sector_mean_1d"]]
            .assign(clipped=joined["clipped"].map({1: "at 99th pct", -1: "at 1st pct", 0: ""}))
            .sort_values("mean_sentiment").style.format({"mean_sentiment": "{:+.2f}", "change_pct": "{:+.2%}",
                                                         "sector_mean_1d": "{:+.2%}"}).hide(axis="index"))

# %% [markdown]
# **How to read this.** Each dot is a ticker: the tone of its articles from the
# price session's day across, its one-day price change up. If tone and price
# line up, the dots rise from left to right, and the black OLS line with its
# grey band slopes up. Triangles are clipped moves, drawn at the clip level
# (the table keeps the raw change). The title states Spearman's ρ with its
# interval; if the interval excludes 0, the link is clear for today's sample.
# The slope says how many percentage points of price change go with one unit
# more sentiment. The two measures can disagree near the edge (one interval
# just excludes 0, the other just includes it). When they do, call the link
# weak.
#
# **Caveats.**
#
# - This is a same-day, cross-sectional association. Even on the same day,
#   news often *reacts* to prices ("shares fall 3%..."), so the arrow can point
#   either way. It is not a trading signal and it does not forecast returns.
# - Keeping same-day articles only can leave few tickers on a quiet day, or
#   when the newest batch was published after the session. The printed counts
#   tell you how much was dropped.
# - Note the units: `change_pct` from the sector endpoint is a fraction
#   (0.0142 = 1.42%); we multiplied it by 100 for the chart.
#
# ### 7.3 Do the notes agree with the raw endpoints?
#
# The notes quote numbers from other endpoints. We pull those numbers out of
# the text with **regular expressions** (patterns that match text) and compare
# them with what we fetched. No new requests. Three checks:
#
# 1. the global note's **bond** line (ticker, price date, one-day change and
#    credit spread) against the bond board;
# 2. each market note's **macro risk** "Upcoming:" lines (indicator, local time,
#    consensus, importance) against the macro calendar;
# 3. the `MARKET` note's sample **articles** against the news endpoint.
#
# A number printed with one decimal agrees if it matches the endpoint after
# rounding to one decimal. If the wording changes, a pattern stops matching and
# the check says "could not parse" rather than crashing.

# %%
BOND_LINE = re.compile(r"(?P<ticker>[A-Z]{2,5}) latest bar (?P<date>\d{4}-\d{2}-\d{2}); 1D (?P<chg>[+-]?\d+(?:\.\d+)?)%, "
                       r"credit spread (?P<spread>[+-]?\d+(?:\.\d+)?) bp")
UPCOMING_LINE = re.compile(r"Upcoming: (?P<name>.+?) — (?P<when>\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?) local"   # "—" is an em dash
                           r"(?:, consensus (?P<consensus>[+-]?\d[\d,]*(?:\.\d+)?)(?P<unit>[%KMBT]?))?"
                           r"(?: \[(?P<importance>[a-z]+)\])?\.?$")


def agrees_printed(text: str, value) -> bool:
    """Does a number printed in a note match an endpoint value, up to the note's rounding?"""
    if value is None or pd.isna(value):
        return False
    text = text.replace(",", "")
    decimals = len(text.split(".")[1]) if "." in text else 0
    return abs(float(text) - float(value)) <= 0.5 * 10 ** -decimals + 1e-9


def note_section(market: str, tab: str):
    """One available note section as a row (Series), or None."""
    hit = sections[(sections["market"] == market) & (sections["tab"] == tab) & sections["ok"].astype(bool)]
    return None if hit.empty else hit.iloc[0]


checks = []
if not notes_ok or sections.empty:
    display(Markdown("> Skipped: there are no notes to compare."))
else:
    sec = note_section("all", "bond")                                            # 1. bond line vs the bond board
    found = BOND_LINE.search(sec["headline"]) if sec is not None else None
    if sec is None:
        missing = ("no global note in this response" if not (sections["market"] == "all").any()
                   else "the global note's bond section is not available")
        checks.append({"check": "global note: bond line", "note says": f"{missing} (NOTES_MARKET = {NOTES_MARKET!r})",
                       "endpoint says": "–", "agree": None})
    elif found is None:
        checks.append({"check": "global note: bond line", "note says": "could not parse", "endpoint says": "–", "agree": None})
    elif bonds.empty:                                                            # board unavailable or empty: no check
        checks.append({"check": f"global note: {found['ticker']}", "note says": found.group(0),
                       "endpoint says": "bond board not read (unavailable or empty)", "agree": None})
    elif not (bonds["ticker"] == found["ticker"]).any():
        checks.append({"check": f"global note: {found['ticker']}", "note says": found.group(0),
                       "endpoint says": "ticker not on the bond board", "agree": False})
    else:
        b = bonds.set_index("ticker").loc[found["ticker"]]
        bar_date = f"{b['latest_bar_date']:%Y-%m-%d}" if pd.notna(b["latest_bar_date"]) else "–"
        checks.append({"check": f"global note: {found['ticker']} price date, 1-day change, credit spread",
                       "note says": f"{found['date']}, {found['chg']}%, {found['spread']} bp",
                       "endpoint says": f"{bar_date}, {b['pct_change_1d']:+.3f}%, {b['credit_spread_bps']:+.1f} bp",
                       "agree": found["date"] == bar_date and agrees_printed(found["chg"], b["pct_change_1d"])
                       and agrees_printed(found["spread"], b["credit_spread_bps"])})

    for m in MARKETS:                                                            # 2. upcoming events vs the calendar
        sec = note_section(m, "macro")
        for line in (sec["lines"] if sec is not None else []):
            hit = UPCOMING_LINE.search(line)
            if hit is None:
                continue                                                         # another kind of line
            said = [f"consensus {hit['consensus']}{hit['unit']}" if hit["consensus"] else "no consensus",
                    f"[{hit['importance']}]" if hit["importance"] else "no tag"]
            row = {"check": f"{m} note: {hit['name']} at {hit['when']}", "note says": ", ".join(said)}
            if m not in macro_payloads:
                checks.append({**row, "endpoint says": f"{m} calendar not read", "agree": None})
                continue
            ev = macro[(macro["market"] == m) & (macro["indicator_name"] == hit["name"])
                       & macro["local_time"].astype(str).str.startswith(hit["when"])]
            if ev.empty:
                checks.append({**row, "endpoint says": f"not in the {MACRO_DAYS}-day calendar", "agree": False})
                continue
            e = ev.iloc[0]
            agree = ((hit["importance"] is None or hit["importance"] == e["importance"])
                     and (hit["consensus"] is None or agrees_printed(hit["consensus"], e["consensus"])))
            checks.append({**row, "endpoint says": f"consensus {fmt_unit(e['consensus'], e['unit'])}, [{e['importance']}]",
                           "agree": bool(agree)})

    sec = note_section(MARKET, "news")                                           # 3. sample articles vs the feed
    ids = [a["article_id"] for a in (sec["articles"] if sec is not None else [])]
    row = {"check": f"{MARKET} note: sample articles in the news feed", "note says": f"{len(ids)} article id(s)"}
    if not ids:
        checks.append({**row, "endpoint says": "–", "agree": None})
    elif not news_ok:
        checks.append({**row, "endpoint says": "news feed unavailable", "agree": None})
    else:
        k = sum(i in set(news["article_id"]) for i in ids)
        checks.append({**row, "endpoint says": f"{k} of {len(ids)} among the newest {len(news)} articles",
                       "agree": k == len(ids)})

    check_table = pd.DataFrame(checks, columns=["check", "note says", "endpoint says", "agree"])
    made = check_table["agree"].notna()
    print(f"{int(check_table['agree'].eq(True).sum())} of {int(made.sum())} checks agree; "
          f"{int((~made).sum())} could not be made (missing data or unparsed text).")
    display(check_table.assign(agree=check_table["agree"].map({True: "yes", False: "no"}).fillna("n/a"))
            .style.apply(lambda col: [f"color: {DIVERGING[1][1]}; font-weight: 600" if v == "no" else "" for v in col],
                         subset=["agree"]).hide(axis="index"))

# %% [markdown]
# **How to read this.** Each row compares one statement in the notes with the
# same fact straight from an endpoint. "yes" means they match, "no" (in red)
# means they differ, and "n/a" means the check could not be made (an endpoint
# was down, a calendar was not read, the global note was not requested, or the
# text did not parse). A mismatch is
# not automatically an error: the note was written at `generated_at`, and the
# endpoints may have moved since (a newer news batch, a new price bar, an
# updated forecast or importance tag). Check the dates before you conclude
# anything.
#
# ### 7.4 Bond funds: how much does maturity explain?
#
# The bubble chart suggested that longer-maturity funds lost more. We put a
# number on it with an ordinary least squares (OLS) regression:
# `1-year return = a + b × average maturity`. We report **HC3** standard
# errors, which do not assume equal noise for every fund, and with only ten
# funds we base the intervals and p-values on the t distribution (n − 2 = 8
# degrees of freedom) rather than the normal one, which would make them too
# narrow in so small a sample (`use_t=True`).

# %%
reg = bonds.dropna(subset=["return_1y_pct", "avg_maturity_years"])
if len(reg) < 5:
    display(Markdown("> Fewer than 5 funds with both numbers: too few for a regression."))
else:
    fit = sm.OLS(reg["return_1y_pct"], sm.add_constant(reg["avg_maturity_years"])).fit(cov_type="HC3", use_t=True)
    b, se = fit.params["avg_maturity_years"], fit.bse["avg_maturity_years"]
    ci_lo, ci_hi = fit.conf_int().loc["avg_maturity_years"]
    display(pd.DataFrame({
        "estimate": [fit.params["const"], b], "HC3 s.e.": [fit.bse["const"], se],
        "95% CI low": fit.conf_int()[0].to_numpy(), "95% CI high": fit.conf_int()[1].to_numpy(),
        "p-value": fit.pvalues.to_numpy()}, index=["intercept (% return at 0 years)", "slope (pp per extra year)"])
        .style.format("{:+.3f}").format("{:.3f}", subset=["HC3 s.e.", "p-value"]))
    print(f"n = {int(fit.nobs)} funds, R² = {fit.rsquared:.2f}: maturity accounts for {fit.rsquared:.0%} of the "
          f"differences in 1-year return between these funds.")
    # A clue to the return definition: a fund with zero maturity is close to cash, so its 1-year TOTAL return
    # should be near a cash yield (positive, several percent), not well below zero.
    cash_like = reg["matched_treasury_yield_pct"].min()
    print(f"Intercept (fitted return at zero maturity): {fit.params['const']:+.2f}%; the lowest matched Treasury yield on "
          f"the board is {cash_like:.2f}%."
          + (" A total return near zero maturity would sit near a cash yield, so a clearly negative intercept hints that "
             "the reported returns leave distributions out. The API does not say; treat it as a hint, not a fact."
             if fit.params["const"] < 0 and pd.notna(cash_like) and cash_like > 0 else ""))

    xs = np.linspace(reg["avg_maturity_years"].min(), reg["avg_maturity_years"].max(), 50)
    band = fit.get_prediction(sm.add_constant(pd.Series(xs, name="avg_maturity_years"))).summary_frame(alpha=0.05)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=np.r_[xs, xs[::-1]], y=np.r_[band["mean_ci_upper"], band["mean_ci_lower"][::-1]],
                             fill="toself", fillcolor="rgba(137,135,129,0.18)", line=dict(width=0),
                             name="95% band of the line", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=xs, y=band["mean"], mode="lines", line=dict(color=INK, width=2), name="OLS line", hoverinfo="skip"))
    for group in [g for g in [*CATEGORY_SLOTS, "Other"] if (reg["category_group"] == g).any()]:
        part = reg[reg["category_group"] == group]
        fig.add_trace(go.Scatter(
            x=part["avg_maturity_years"], y=part["return_1y_pct"], mode="markers", name=group, customdata=part[["ticker"]],
            marker=dict(size=12, color=CATEGORY_COLORS[group], line=dict(width=1, color=SURFACE)),
            hovertemplate=("<b>%{customdata[0]}</b><br>Average maturity %{x:.1f} years<br>1-year return %{y:+.2f}% "
                           "(as reported)<extra></extra>")))
    reg = reg.assign(residual=fit.resid)                     # distance above (+) or below (−) the line, in pp
    to_label = pd.concat([reg.nlargest(1, "return_1y_pct"), reg.nsmallest(1, "return_1y_pct"),
                          reg.loc[[reg["residual"].abs().idxmax()]]]).drop_duplicates(subset="ticker")
    for _, row in to_label.iterrows():
        above = row["residual"] >= 0
        fig.add_annotation(x=row["avg_maturity_years"], y=row["return_1y_pct"], showarrow=True, arrowhead=0, arrowcolor=MUTED,
                           text=f"{row['ticker']} ({row['residual']:+.1f} pp vs line)", ax=30, ay=-30 if above else 30,
                           xanchor="left", standoff=7, font=dict(size=11, color=INK_2))
    fig.add_hline(y=0, line=dict(color=AXIS, width=1))
    fig.update_xaxes(title_text="Average maturity of the fund's bonds (years)")
    fig.update_yaxes(title_text="1-year return as reported (%)", ticksuffix="%", zeroline=False)
    title_spec, title_px = chart_title(
        f"Each extra year of maturity went with {b:+.2f} pp of reported 1-year return (95% CI {ci_lo:+.2f} to {ci_hi:+.2f})",
        f"OLS with HC3 standard errors and t-based intervals ({int(fit.df_resid)} df) · n = {int(fit.nobs)} funds · "
        f"R² = {fit.rsquared:.2f} · descriptive, not a forecast")
    fig.update_layout(title=title_spec, height=title_px + 110 + 320, margin=dict(t=title_px, b=110), legend=LEGEND_BELOW)
    fig.show()
    display(reg[["ticker", "category", "avg_maturity_years", "return_1y_pct", "residual"]].sort_values("avg_maturity_years")
            .style.format({"avg_maturity_years": "{:.1f} y", "return_1y_pct": "{:+.2f}%", "residual": "{:+.2f} pp"})
            .hide(axis="index"))

# %% [markdown]
# **How to read this.** Each dot is a fund. The labels mark the best and worst
# 1-year returns and the fund furthest from the line (its **residual**: how
# much better or worse it did than its maturity alone suggests). The black line
# is the best straight-line fit, and the grey band is its 95% confidence band:
# lines inside the band fit the data about as well. The slope says how many
# percentage points of 1-year return changed, on average, with one more year of
# average maturity. A negative slope is what rising interest rates do to long
# bonds. The table lists every fund with its residual.
#
# **Caveats.**
#
# - Ten funds and one predictor: treat the slope as a description of this
#   board over this year, not a law.
# - Maturity is a stand-in for **duration** (the true measure of rate
#   sensitivity), which the board does not send.
# - High-yield funds are short-maturity *and* carry credit risk, so part of the
#   slope may be a credit effect. Fixing that needs more funds than ten.
# - The returns are as reported, and the API does not say whether they include
#   distributions (see section 6). The **intercept** gives a rough clue: it is
#   the fitted return of a fund with zero maturity, which is close to cash. A
#   1-year *total* return for cash would sit near a cash yield (several
#   percent), so an intercept well below zero suggests price-only returns. The
#   cell prints the intercept next to the lowest matched Treasury yield. A
#   straight line through ten funds is a weak instrument, so this is a hint,
#   not a fact.

# %% [markdown]
# ## Next steps
#
# - Re-run when the news feed is back: sections 3, 7.1 and 7.2 fill in with no
#   code change.
# - Change `MARKET` to `"jp"` or `"hk"` and run again: the news mixes company
#   filings with media, and the word chart switches to character bigrams.
# - Set `NEWS_TICKER` to a stock you follow and compare its tone with the
#   market's.
# - Save the macro calendar every day. After a release, the same event comes
#   back with an actual number, and once `MIN_RELEASED` events have one,
#   section 5 switches from expected changes to surprises. After a few months you can divide each surprise by that
#   indicator's own surprise volatility, the way professional surprise indices do.
# - Join the notes' `top_rows` tickers with the screen (notebook 01) or the ML
#   clusters (notebook 02) on `ticker`.
# - Track the bond board daily and chart the credit spreads of HYG and LQD over
#   time.
#
# ---
#
# *Research and education only. Nothing here is investment advice or a
# recommendation to buy or sell any security. Sentiment scores are model
# outputs, the Daily Notes are research documentation, and the macro and bond
# numbers come from third-party providers. Elsewhere in the API, the endpoint
# name `realtime` describes a current-session board, not a live-tick feed. Data
# cadence varies by market and source: always check the freshness fields.*

# %%
print(f"API requests made in this session: {api_calls_used()}")
