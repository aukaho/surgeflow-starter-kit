# %% [markdown]
# # 02 · AI research council: the analyst scoreboard and the paper grade book
#
# SurgeFlow runs an **AI research council** over the US momentum hotlist. Four
# analyst **seats** (factor, fundamental, technical and sentiment) score every
# hotlist name from 0 to 100 and add a one-line comment. Two more seats, macro
# and risk, look at the top names and often file a comment without a score. A
# **deterministic rule** then reads one number, the grade: above 70 opens a paper
# LONG, below 30 opens a paper SHORT, and anything from 30 to 70 is HOLD (no
# position). The seats explain the call and challenge it. Their reviews must pass
# quality gates before a position opens, but SurgeFlow states that **the seats
# never set the grade and never flip the side**. Section 5 checks the part of that
# claim the data can test.
#
# This notebook reads the two endpoints that publish the council's work: the
# **scoreboard** (what each seat thinks of each name at the latest meeting) and
# the **grade book** (the paper positions the rule opened, how they closed, and
# the latest gate decisions). Everything here is a paper research record. Nothing
# is a trade, and nothing is investment advice.
#
# **What you will learn**
#
# - The rule `> 70 LONG, < 30 SHORT, else HOLD`, and how to check it against the data.
# - How to unpack nested JSON (a score and a comment per seat) into a tidy table,
#   with an explicit policy for seats that did not report.
# - How to test a published number against its possible definitions.
# - How to measure agreement between analysts with rank correlation, and why a
#   dozen names is a small sample.
# - How to draw a side-aware position chart, so LONG and SHORT positions read the
#   same way.
# - How to summarise outcomes honestly: a Wilson interval for the hit rate, a
#   bootstrap for the mean, and a second bootstrap that respects positions opened
#   on the same day.
# - How to tell a grade's skill from the market's direction, when LONG and SHORT
#   positions have opposite market exposure.
# - How to read the six opener gates, and how to recompute them from their own
#   evidence fields.
#
# **Endpoints used**
#
# | Method | Path | What it returns |
# |---|---|---|
# | GET | `/api/v1/ai/ratings` | The council scoreboard for the US hotlist at one meeting (checkpoint): each name's composite score, every seat's score and comment, the scoreboard's own paper long/short flags, tenure and stop states |
# | GET | `/api/v1/ai/grade-book` | The deterministic paper book: positions with entry, Drop Out Zone exit and outcome; the latest opener decisions with their six gates; and the exit contract in force |
#
# **Budget:** 2 requests (the free plan allows 2,000 a day). The notebook runs in
# well under a minute.
#
# **Words used in this notebook**
#
# | Word | Meaning |
# |---|---|
# | seat | One AI analyst with one lens (for example `technical`). The API calls seats "analysts" or "agents" |
# | composite | The scoreboard's summary of a name's seat scores (0-100). It is *not* the grade |
# | grade | The book's deterministic score (`grade_score`). The rule reads this number |
# | paper position | A simulated LONG or SHORT entry, recorded for research. No order is ever placed |
# | checkpoint | One council meeting: morning, midday or close |
# | gate | A pass/fail check that must hold before a graded name opens a position |
# | Drop Out Zone | The book's only exit level: one third of the way up a session's high-low range |

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
# (`sf_get`, `sf_try`, `records`, `to_frame`, `show_freshness`, ...) and the
# chart theme. You can run it without reading it.

# %% [helpers]

# %% [markdown]
# ## 2. Parameters
#
# The council covers the **US hotlist only**, so there is no market to choose
# for the scoreboard. The other values control how much history you pull and
# how the statistics behave.

# %%
CHECKPOINT = "latest"   # scoreboard meeting: "latest" (default), "morning", "midday" or "close"
BOOK_MARKET = "us"      # the grade book follows the US hotlist; "cn", "jp" or "hk" return an empty book
BOOK_LIMIT = 200        # grade-book position rows: 1-200 (default 80). More closed rows = tighter statistics
LADDER_CLOSED = 12      # how many recent closed positions the position chart shows next to the open ones
MIN_PAIR_N = 6          # seat agreement: hide a correlation computed on fewer names than this
WINSOR_Q = 0.05         # outcome robustness: clip realised returns at the 5th and 95th percentile per side
BOOTSTRAP_SEED = 7      # fixed seed, so the bootstrap intervals come out the same every run
STALE_DAYS = 4          # warn when the latest council meeting is older than this many days

# The book's published rule ("score_rule" in every gate record). SurgeFlow fixes it;
# it is written here so the code can check the data against it. Do not tune it.
LONG_ABOVE, SHORT_BELOW = 70, 30

assert CHECKPOINT in ("latest", "morning", "midday", "close"), "CHECKPOINT: latest, morning, midday or close"
assert BOOK_MARKET in MARKETS, f"BOOK_MARKET must be one of {MARKETS}"
assert 1 <= BOOK_LIMIT <= 200, "BOOK_LIMIT must be 1-200 (the API answers 422 otherwise)"
print(f"Scoreboard checkpoint: {CHECKPOINT}. Grade book: market {BOOK_MARKET}, up to {BOOK_LIMIT} rows.")

# %% [markdown]
# A few small utilities keep the later cells short. They are plain code, so read
# them once:
#
# - `grade_side` is the rule itself, in three lines.
# - `pick` keeps exactly the documented columns. If one is missing it raises a
#   `KeyError`, because that means the API contract changed. An empty list is
#   normal, so it returns an empty table instead of crashing.
# - `wilson`, `bootstrap_mean_ci`, `cluster_bootstrap_ci` and
#   `cluster_bootstrap_spread_ci` are the interval estimates used in the outcome
#   section. They are explained there.
# - `pct`, `usd`, `p_text` and `age_text` format numbers for titles and tables.
#
# The cell also checks two library versions. Chart subtitles need plotly 5.23 or
# newer, and `DataFrame.map` needs pandas 2.1 or newer. Colab has both; an older
# local install stops here with the upgrade command instead of failing mid-way.

# %%
import re

import plotly
from IPython.display import HTML
from plotly.subplots import make_subplots
from scipy import stats
from statsmodels.stats.multitest import multipletests


def version_tuple(text: str) -> tuple:
    """'5.24.1' -> (5, 24): enough to compare major and minor versions."""
    return tuple(int(part) for part in re.findall(r"\d+", text)[:2])


assert version_tuple(plotly.__version__) >= (5, 23), "Chart subtitles need plotly 5.23+: pip install -U 'plotly>=5.24'"
assert version_tuple(pd.__version__) >= (2, 1), "DataFrame.map needs pandas 2.1+: pip install -U 'pandas>=2.1'"

SIDE_ORDER = ["LONG", "HOLD", "SHORT"]
SIDE_SIGN = {"LONG": 1, "SHORT": -1}     # +1: a rising price helps; -1: a falling price helps


def grade_side(score):
    """The deterministic rule: > 70 LONG, < 30 SHORT, otherwise HOLD. 70 and 30 themselves are HOLD."""
    if pd.isna(score):
        return None
    return "LONG" if score > LONG_ABOVE else "SHORT" if score < SHORT_BELOW else "HOLD"


def pick(raw: pd.DataFrame, columns: list) -> pd.DataFrame:
    """Keep the documented columns. Empty is normal; a missing column raises KeyError."""
    if raw.empty:
        return pd.DataFrame(columns=columns)
    return raw[columns].copy()


def wilson(hits: int, n: int, z: float = 1.96) -> tuple:
    """95% Wilson score interval for a proportion. Better than p ± 1.96·SE when n is small."""
    if n == 0:
        return (np.nan, np.nan)
    p = hits / n
    centre = (p + z**2 / (2 * n)) / (1 + z**2 / n)
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
    return (centre - half, centre + half)


def bootstrap_mean_ci(values, n_boot: int = 5000, seed: int = BOOTSTRAP_SEED) -> tuple:
    """95% percentile-bootstrap interval for a mean: resample rows with replacement, recompute, take quantiles."""
    values = pd.Series(values, dtype=float).dropna().to_numpy()
    if len(values) < 2:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    means = rng.choice(values, size=(n_boot, len(values)), replace=True).mean(axis=1)
    return tuple(np.percentile(means, [2.5, 97.5]))


def cluster_bootstrap_ci(values, clusters, n_boot: int = 5000, seed: int = BOOTSTRAP_SEED) -> tuple:
    """95% bootstrap interval for a mean when rows come in groups (here: positions graded on the same day).

    Whole groups are resampled with replacement, so rows that share a day stay together.
    """
    frame = pd.DataFrame({"v": pd.Series(values, dtype=float).to_numpy(), "c": np.asarray(clusters)}).dropna()
    groups = frame.groupby("c")["v"].agg(["sum", "count"])
    if len(groups) < 2:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    draw = rng.integers(0, len(groups), size=(n_boot, len(groups)))
    means = groups["sum"].to_numpy()[draw].sum(axis=1) / groups["count"].to_numpy()[draw].sum(axis=1)
    return tuple(np.percentile(means, [2.5, 97.5]))


def cluster_bootstrap_spread_ci(values, is_long, clusters, n_boot: int = 5000, seed: int = BOOTSTRAP_SEED) -> tuple:
    """95% bootstrap interval for mean(LONG rows) − mean(SHORT rows), resampling whole groups (grade days).

    A grade day can hold positions of both sides, so each draw keeps that day's LONG and SHORT rows together.
    """
    frame = pd.DataFrame({"v": pd.Series(values, dtype=float).to_numpy(), "is_long": np.asarray(is_long, dtype=bool),
                          "c": np.asarray(clusters)}).dropna()
    parts = pd.DataFrame({"c": frame["c"],
                          "sum_long": frame["v"].where(frame["is_long"], 0.0), "n_long": frame["is_long"].astype(int),
                          "sum_short": frame["v"].where(~frame["is_long"], 0.0),
                          "n_short": (~frame["is_long"]).astype(int)})
    groups = parts.groupby("c").sum()
    if len(groups) < 2 or groups["n_long"].sum() == 0 or groups["n_short"].sum() == 0:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    draw = rng.integers(0, len(groups), size=(n_boot, len(groups)))
    total = {col: groups[col].to_numpy(dtype=float)[draw].sum(axis=1) for col in groups.columns}
    with np.errstate(invalid="ignore", divide="ignore"):              # a draw can miss one side entirely
        spreads = total["sum_long"] / total["n_long"] - total["sum_short"] / total["n_short"]
    return tuple(np.percentile(spreads[np.isfinite(spreads)], [2.5, 97.5]))


def p_text(p: float) -> str:
    """0.0003 -> 'p < 0.001'; 0.214 -> 'p = 0.21'."""
    return "p n/a" if pd.isna(p) else "p < 0.001" if p < 0.001 else f"p = {p:.2f}"


def pct(value, digits: int = 1, signed: bool = True) -> str:
    """4.2 -> '+4.2%' (the value is already in percent)."""
    if pd.isna(value):
        return "n/a"
    return f"{value:+.{digits}f}%" if signed else f"{value:.{digits}f}%"


def usd(value) -> str:
    return "n/a" if pd.isna(value) else f"${value:,.2f}"


def age_text(stamp) -> str:
    """How long ago a UTC timestamp was, in words."""
    hours = (pd.Timestamp.now(tz="UTC") - stamp).total_seconds() / 3600
    if hours < 0:
        return "in the future (check your clock)"
    return f"{hours:,.1f} hours ago" if hours < 48 else f"{hours / 24:,.1f} days ago"


print("Rule check:", {s: grade_side(s) for s in (12.5, 29.99, 30, 50, 70, 70.01, 88)})

# %% [markdown]
# ## 3. The rule, and who is allowed to touch it
#
# The whole paper book follows one deterministic rule. "Deterministic" means the
# same input always gives the same output. No judgement, no vote:
#
# | Grade | Side | What happens |
# |---|---|---|
# | above 70 (strictly) | LONG | a paper long can open, if the gates pass |
# | 30 to 70 (both ends included) | HOLD | nothing opens |
# | below 30 (strictly) | SHORT | a paper short can open, if the gates pass |
#
# The rule check printed above shows the edges: 70 and 30 are HOLD, while 70.01
# is LONG and 29.99 is SHORT.
#
# The seats sit around the rule, not inside it:
#
# ```text
#   hotlist name ──► grade (0-100) ──► rule: > 70 LONG · < 30 SHORT · else HOLD ──► paper position
#                       ▲                                                   ▲
#                       │ never changed by a seat                           │ can be held back
#                                                                           │
#   six seats ──► score + comment ──► explain, challenge ──► gates: reviews complete, fresh, no veto
# ```
#
# A seat can explain why a name scores high, or challenge it with a low score and
# a cautious comment. If the reviews are incomplete or stale, a gate can stop a
# position from opening. But, by SurgeFlow's design, no seat can raise or lower the
# grade, and none can turn a LONG into a SHORT.
#
# The rest of the notebook checks what the data can check: that every position's
# side is the rule applied to its grade, and that the gates only hold names back.
# Whether the seats' views feed into `grade_score` itself cannot be tested from the
# published fields, because the book publishes the grade but not how it was
# computed. For that part we rely on SurgeFlow's own disclaimer, printed with the
# grade book in section 5.

# %% [markdown]
# ## 4. The scoreboard: `/api/v1/ai/ratings`
#
# **What it is for.** The scoreboard shows the council's latest meeting on the US
# hotlist. For each name it gives:
#
# - `composite_score`: the council's summary of the seat scores (0-100);
# - `per_analyst`: each seat's score and one-line comment;
# - `long` / `short`: whether the name is a leg of the **scoreboard's own paper
#   ledger** (`pick_ledger`), which has its own stop. The grade book in section 5
#   is a separate record;
# - tenure (`duration_on_list_days`, `in_top5`) and, for paper legs, the
#   direction-adjusted return since an anchor close (`return_since`).
#
# The council meets up to three times a session. `checkpoint` picks the meeting:
# `latest` (default), `morning`, `midday` or `close`. **An empty `names` list is
# normal**: before the first meeting of the day the council "hasn't met yet".
#
# We call the endpoint with `sf_try`. If the scoreboard is temporarily
# unavailable, it prints a note and the notebook carries on with an empty
# scoreboard, so the grade book in section 5 still works.

# %%
ratings_payload = sf_try("/api/v1/ai/ratings", checkpoint=CHECKPOINT)
RATINGS_AVAILABLE = ratings_payload is not None
if not RATINGS_AVAILABLE:                                      # unavailable: continue with an empty scoreboard
    ratings_payload = {"data": {"checkpoint_id": None, "checkpoint_time": None, "checkpoint_index": None,
                                "decision_session_date": None, "hotlist_size": 0, "names": [], "analysts": [],
                                "stop_reflections": [], "left_convictions": []}}
else:
    show_freshness(ratings_payload, "Scoreboard:")

meta = ratings_payload["data"]
names_raw = records(ratings_payload, "ai_ratings")
MEETING = {0: "morning", 1: "midday", 2: "close"}
checkpoint_time = pd.to_datetime(meta["checkpoint_time"], utc=True) if meta["checkpoint_time"] else pd.NaT  # UTC
if pd.notna(checkpoint_time):
    checkpoint_age_days = (pd.Timestamp.now(tz="UTC") - checkpoint_time).total_seconds() / 86400
    print(f"Checkpoint {meta['checkpoint_id']} ({MEETING.get(meta['checkpoint_index'], 'unknown')} meeting), "
          f"held {checkpoint_time:%Y-%m-%d %H:%M} UTC, {age_text(checkpoint_time)}.")
    print(f"Decision session {meta['decision_session_date']}; hotlist size {meta['hotlist_size']}; "
          f"{len(names_raw)} names on the scoreboard.")
    if checkpoint_age_days > STALE_DAYS and CHECKPOINT == "latest":
        print(f"Note: the latest meeting is {checkpoint_age_days:.0f} days old, so the council has not met since. "
              "Expect the grade book's freshness gate (G4, section 5) to hold back new grades.")
    elif checkpoint_age_days > STALE_DAYS:
        print(f"Note: this {CHECKPOINT} meeting is {checkpoint_age_days:.0f} days old. Try CHECKPOINT = 'latest'.")

if not RATINGS_AVAILABLE:
    display(Markdown("> The scoreboard cells below will skip their charts; the grade book in section 5 still works."))
elif not names_raw:
    display(Markdown("> **The team hasn't met yet.** The scoreboard is empty, which is normal before the "
                     "first meeting of a session. The scoreboard cells below will skip their charts; the "
                     "grade book in section 5 still works."))

# %% [markdown]
# **Raw preview.** `to_frame` flattens the nested JSON into dotted column names,
# such as `per_analyst.technical.score`. This is the data as it arrived. The
# comments are member-only research text: fine to read in your own notebook, but
# do not paste them into anything you publish.

# %%
ratings_raw = to_frame(ratings_payload, "ai_ratings")
print(f"{ratings_raw.shape[0]} names x {ratings_raw.shape[1]} flattened columns")
ratings_raw.head()

# %% [markdown]
# ### Cleaning the scoreboard
#
# The flattened table is wide and awkward. We build two tidy tables instead:
#
# - `board`: one row per name, with the documented fields we need;
# - `seats`: one row per (name, seat), with the seat's score and comment. This
#   "long" format makes it easy to pivot, group and chart.
#
# The steps, each done in the open:
#
# 1. **Read documented fields by name.** Accessing `n["pick_ledger"]["stop"]["state"]`
#    raises a `KeyError` if a promised field disappears. `return_since` is
#    documented as null for names that are not paper legs, so that one is allowed
#    to be empty.
# 2. **Keep tickers as text** and **de-duplicate** on the natural key: `ticker`
#    for `board`, (`ticker`, `seat`) for `seats`.
# 3. **Coerce to numbers** with `pd.to_numeric(errors="coerce")`, and parse
#    timestamps as UTC and session dates as plain dates.
# 4. **Range-check scores**: anything outside 0-100 becomes NaN, and we count it.

# %%
def flatten_name(n: dict) -> dict:
    """One scoreboard name -> one flat row of documented fields."""
    ledger, since = n["pick_ledger"], n["return_since"]          # return_since is null unless a paper leg
    return {
        "rank": n["rank"], "ticker": n["ticker"], "composite_score": n["composite_score"],
        "long": n["long"], "short": n["short"], "in_top5": n["in_top5"],
        "duration_on_list_days": n["duration_on_list_days"],
        "ledger_direction": ledger["direction"], "stop_state": ledger["stop"]["state"],
        "return_since_pct": since["return_since_pct"] if since is not None else None,
        "anchor_date": since["anchor_date"] if since is not None else None,
        "picked_at": ledger["picked_at"], "headline_comment": n["headline_comment"],
    }


BOARD_COLS = ["rank", "ticker", "composite_score", "long", "short", "in_top5", "duration_on_list_days",
              "ledger_direction", "stop_state", "return_since_pct", "anchor_date", "picked_at", "headline_comment"]
board = pick(pd.DataFrame([flatten_name(n) for n in names_raw]), BOARD_COLS)
seats = pd.DataFrame(
    [{"ticker": n["ticker"], "seat": seat, "score": review["score"], "comment": review["comment"]}
     for n in names_raw for seat, review in n["per_analyst"].items()],
    columns=["ticker", "seat", "score", "comment"])

# Step 2: tickers are labels, not numbers; one row per natural key.
board["ticker"] = board["ticker"].astype(str)
seats["ticker"] = seats["ticker"].astype(str)
n0, s0 = len(board), len(seats)
board = board.drop_duplicates(subset="ticker", keep="first").sort_values("rank").reset_index(drop=True)
seats = seats.drop_duplicates(subset=["ticker", "seat"], keep="first").reset_index(drop=True)
print(f"De-duplication: board {n0} -> {len(board)} rows, seats {s0} -> {len(seats)} rows.")

# Step 3: numbers, UTC timestamps and session dates.
for col in ["rank", "composite_score", "duration_on_list_days", "return_since_pct"]:
    board[col] = pd.to_numeric(board[col], errors="coerce")
seats["score"] = pd.to_numeric(seats["score"], errors="coerce")
board["picked_at"] = pd.to_datetime(board["picked_at"], utc=True)
board["anchor_date"] = pd.to_datetime(board["anchor_date"], format="%Y-%m-%d")
board[["long", "short", "in_top5"]] = board[["long", "short", "in_top5"]].astype(bool)

# Step 4: scores live on a 0-100 scale.
bad_seat = ~seats["score"].between(0, 100) & seats["score"].notna()
bad_comp = ~board["composite_score"].between(0, 100) & board["composite_score"].notna()
seats.loc[bad_seat, "score"] = np.nan
board.loc[bad_comp, "composite_score"] = np.nan
print(f"Range check: {int(bad_seat.sum())} seat scores and {int(bad_comp.sum())} composites were outside 0-100.")

# The seat order comes from the API's own list; any unexpected seat goes at the end.
API_SEATS = list(meta["analysts"]) if names_raw else []
SEATS = API_SEATS + sorted(set(seats["seat"]) - set(API_SEATS))
if len(SEATS) > len(API_SEATS):
    print(f"Note: seats not listed in data.analysts: {SEATS[len(API_SEATS):]}")
print(f"Seats: {', '.join(SEATS) or 'none'}.")
board.head()

# %% [markdown]
# 5. **Audit the gaps, then set a policy.** Seats do not always report, and there
#    are two different kinds of gap, so we count them separately:
#
#    - the seat's key is **absent** from `per_analyst` (macro and risk appear only
#      for the top names);
#    - the seat is **present but its score is null**: it filed a comment (often
#      "no evidence routed to this desk") without a score.
#
#    A third pattern is not a gap in the data, but may be one in substance: a seat
#    that **scored exactly 0 and filed no comment**. A review that was never filed
#    could be recorded that way. The API does not say, so we call these cells
#    **blank zeros**, count them, and flag them in the charts. (Other scores without
#    a comment are common and are not flagged; only the combination with a 0 is
#    suspicious.)
#
# Our policy is explicit: **a missing seat stays missing.** We never fill it with
# 50 ("neutral") or 0, because that would invent an opinion. Any average we
# compute ourselves uses only the seats that reported, and the agreement
# statistics use, for each pair of seats, only the names both of them scored.
# A blank zero stays 0, because that is the published score and the published
# composite averages it (step 6 checks this). Instead, the agreement and fragility
# checks below re-run without the blank zeros, so you can see how much they matter.

# %%
wide = (seats.pivot(index="ticker", columns="seat", values="score")
        .reindex(index=board["ticker"], columns=SEATS))           # names in rank order, seats in API order
present = (seats.assign(reported=1).pivot(index="ticker", columns="seat", values="reported")
           .reindex(index=board["ticker"], columns=SEATS))           # 1 where the seat key exists
comments_wide = (seats.pivot(index="ticker", columns="seat", values="comment")
                 .reindex(index=board["ticker"], columns=SEATS))
no_comment = comments_wide.map(lambda c: not isinstance(c, str) or not c.strip())
zero_no_comment = (wide == 0) & no_comment                           # a "blank zero": maybe no review filed
wide_without_blank_zeros = wide.mask(zero_no_comment)              # for the sensitivity checks only

seat_audit = pd.DataFrame({
    "names_scored": wide.notna().sum(),
    "seat_absent": present.isna().sum(),                           # key not in per_analyst at all
    "seat_present_score_null": (present.notna() & wide.isna()).sum(),
    "score_zero_no_comment": zero_no_comment.sum(),                # scored, but maybe not reviewed
}).rename_axis("seat")
seat_audit["coverage"] = seat_audit["names_scored"] / max(len(board), 1)
display(seat_audit.style.format({"coverage": "{:.0%}"}))
n_blank = int(zero_no_comment.sum().sum())
blank_by_seat = ", ".join(f"{s} {int(n)}" for s, n in zero_no_comment.sum().items() if n)
print(f"Blank zeros (score 0, no comment): {n_blank}" + (f" ({blank_by_seat}). They may be reviews that were never "
                                                         "filed; we keep them as published and flag them below."
                                                         if n_blank else "."))

board["n_seats"] = board["ticker"].map(wide.notna().sum(axis=1))
board["seat_min"] = board["ticker"].map(wide.min(axis=1))
board["seat_max"] = board["ticker"].map(wide.max(axis=1))
print("Names by number of seats that scored:", board["n_seats"].value_counts().sort_index().to_dict())

# %% [markdown]
# 6. **Check what the composite is.** Never trust a definition you can test.
#    Two readings are plausible: the mean of every seat that scored, or the mean
#    of the four core seats (factor, fundamental, technical and sentiment), which
#    score every name. For a name without a macro or risk score both readings give
#    the same number, so only names with one can tell them apart. We test both
#    and count which one reproduces the published number (a gap under 0.01 is
#    rounding). The winner is kept as `COMPOSITE_SEATS` for section 6.3.
# 7. **Apply the rule to the composite**, and compare that side with the paper
#    flags `long` / `short`. This is a lens, not the book's own rule: the book
#    applies the rule to its `grade_score`. Section 6.1 compares the two numbers.

# %%
CORE = [s for s in ("factor", "fundamental", "technical", "sentiment") if s in SEATS]
READINGS = {"mean of all scoring seats": SEATS, "mean of the four core seats": CORE}
COMPOSITE_SEATS = SEATS
if board.empty:
    print("No names to check.")
else:
    published = board.set_index("ticker")["composite_score"]
    fits = pd.DataFrame({name: (published - wide[cols].mean(axis=1)).abs() < 0.01
                         for name, cols in READINGS.items()})
    can_tell = wide.drop(columns=CORE).notna().any(axis=1)          # names with a macro or risk score
    print(f"{int(can_tell.sum())} of {len(fits)} names carry a macro or risk score and can separate the readings:")
    for name, hits in fits[can_tell].sum().items():
        print(f"  {name:<28} reproduces {int(hits)} of {int(can_tell.sum())}")
    best = fits[can_tell].sum().idxmax() if can_tell.any() else "mean of all scoring seats"
    COMPOSITE_SEATS = READINGS[best]
    neither = fits.index[~fits.any(axis=1)].tolist()
    print(f"Every published composite matches at least one reading; we use the {best}." if not neither else
          f"No reading reproduces {neither}: treat the composite as a published number, not a formula.")
    if int(can_tell.sum()) < 5:
        print(f"Only {int(can_tell.sum())} name(s) can separate the readings, so this is thin evidence. "
              "Re-run it on other checkpoints.")
    with_blank = [t for t in fits.index if zero_no_comment.loc[t, COMPOSITE_SEATS].any() and fits.loc[t, best]]
    if with_blank:                                                    # show one worked example
        t = with_blank[0]
        parts = ", ".join(f"{s} {wide.loc[t, s]:.0f}" for s in COMPOSITE_SEATS if pd.notna(wide.loc[t, s]))
        print(f"The published composite averages blank zeros like any other score: {t} {published[t]:.2f} "
              f"is the mean of {parts}. {len(with_blank)} name(s) include at least one blank zero.")

board["rule_side"] = board["composite_score"].map(grade_side)
board["flag"] = np.select([board["long"], board["short"]], ["LONG", "SHORT"], default="not flagged")
if not board.empty:                                                   # an empty board has nothing to compare
    crosstab = pd.crosstab(board["rule_side"], board["flag"]).reindex(index=SIDE_ORDER, fill_value=0)
    display(crosstab.rename_axis(index="zone of the composite", columns="paper flag"))

    contradicts = board[(board["flag"] != "not flagged") & (board["flag"] != board["rule_side"])]
    unflagged = board[board["rule_side"].isin(["LONG", "SHORT"]) & (board["flag"] == "not flagged")]
    print("No paper flag contradicts its composite zone." if contradicts.empty else
          f"{len(contradicts)} flagged name(s) sit outside their side's zone: {', '.join(contradicts['ticker'])}.")
    print(f"{len(unflagged)} name(s) sit in a LONG or SHORT zone without a flag"
          + (f": {', '.join(unflagged['ticker'])}." if len(unflagged) else "."))
    for side in ("LONG", "SHORT"):
        ranks = board.loc[board["flag"] == side, "rank"].astype(int).tolist()
        if ranks:
            print(f"Paper {side} flags sit at ranks {ranks} of {len(board)}.")

# %% [markdown]
# Read the cross-table row by row. A LONG flag should appear only in the LONG
# row and a SHORT flag only in the SHORT row, and the HOLD row should have no
# flags at all. When the first printed line says no flag contradicts its zone,
# **the side follows the zone.**
#
# Some names in a LONG or SHORT zone may carry no flag. The scoreboard does not
# publish why. The printed ranks give a clue: if the flags cluster at the very top
# or bottom of the list, the ledger takes the extremes rather than every name past
# a line. Treat that as an observation about this checkpoint, not a rule.
# The flags are also not the grade book: the book reads its own `grade_score`
# (section 6.1) and keeps its own positions (section 6.2).

# %% [markdown]
# ### Chart: where each name sits against the 30 / 70 lines
#
# Each row is one hotlist name, highest composite at the top. The big dot is the
# composite, coloured by the zone the rule puts it in. The small hollow dots are
# the individual seats' scores, and the grey bar spans the lowest to the highest
# seat. A black ring marks a paper leg in the scoreboard's ledger. A grey × marks
# a blank zero (a seat score of 0 with no comment). (This is a dot strip with one
# row per name, so every label stays readable.)

# %%
if board["composite_score"].notna().sum() == 0:
    display(Markdown("> Scoreboard unavailable right now; chart skipped." if not RATINGS_AVAILABLE else
                     "> No scoreboard names to chart. The council has not met yet."))
else:
    plot = board.dropna(subset=["composite_score"]).sort_values("composite_score")
    order = plot["ticker"].tolist()                                   # bottom -> top
    seat_pts = seats.dropna(subset=["score"])
    seat_pts = seat_pts[seat_pts["ticker"].isin(order)]
    seat_pts = seat_pts.assign(blank=[bool(zero_no_comment.at[t, s]) for t, s in zip(seat_pts["ticker"], seat_pts["seat"])])

    fig = go.Figure()
    fig.add_vrect(x0=-2, x1=SHORT_BELOW, fillcolor=SIDE_COLORS["SHORT"], opacity=0.06, line_width=0, layer="below")
    fig.add_vrect(x0=LONG_ABOVE, x1=102, fillcolor=SIDE_COLORS["LONG"], opacity=0.06, line_width=0, layer="below")
    for x, text in ((SHORT_BELOW, f"SHORT below {SHORT_BELOW}"), (LONG_ABOVE, f"LONG above {LONG_ABOVE}")):
        fig.add_vline(x=x, line=dict(color=INK_2, width=1.2, dash="dot"), annotation_text=text,
                      annotation_position="top", annotation_font=dict(size=12, color=INK_2))

    xs, ys = [], []                                                   # seat range bars (None breaks the line)
    for _, row in plot.iterrows():
        if pd.notna(row["seat_min"]):
            xs += [row["seat_min"], row["seat_max"], None]
            ys += [row["ticker"], row["ticker"], None]
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=AXIS, width=2), legendrank=6,
                             name="Range of seat scores", hoverinfo="skip"))
    filed = seat_pts[~seat_pts["blank"]]
    fig.add_trace(go.Scatter(
        x=filed["score"], y=filed["ticker"], mode="markers", name="One seat's score", legendrank=5,
        marker=dict(symbol="circle-open", size=7, color=INK_2, line=dict(width=1.2, color=INK_2)),
        customdata=filed["seat"], hovertemplate="<b>%{y}</b> · %{customdata}: %{x:.0f}<extra></extra>"))
    blank_pts = seat_pts[seat_pts["blank"]]
    if not blank_pts.empty:
        fig.add_trace(go.Scatter(
            x=blank_pts["score"], y=blank_pts["ticker"], mode="markers", legendrank=7,
            name="Seat score 0 with no comment (maybe no review)",
            marker=dict(symbol="x-thin", size=9, color=MUTED, line=dict(width=1.8, color=MUTED)),
            customdata=blank_pts["seat"],
            hovertemplate="<b>%{y}</b> · %{customdata}: 0, no comment filed (maybe no review)<extra></extra>"))
    for side in SIDE_ORDER:
        sub = plot[plot["rule_side"] == side]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["composite_score"], y=sub["ticker"], mode="markers", name=f"Composite in the {side} zone",
            legendrank=SIDE_ORDER.index(side) + 1,
            marker=dict(size=15, color=SIDE_COLORS[side], line=dict(width=1.5, color=SURFACE)),
            customdata=np.stack([sub["rank"], sub["n_seats"], sub["flag"], sub["stop_state"],
                                 sub["duration_on_list_days"]], axis=-1),
            hovertemplate=("<b>%{y}</b> · rank %{customdata[0]}"
                           "<br>Composite %{x:.1f} (%{customdata[1]} seats scored)"
                           "<br>Scoreboard paper flag: %{customdata[2]} · stop: %{customdata[3]}"
                           "<br>%{customdata[4]} days on the list<extra></extra>")))
    flagged = plot[plot["flag"] != "not flagged"]
    fig.add_trace(go.Scatter(
        x=flagged["composite_score"], y=flagged["ticker"], mode="markers", name="Paper leg in the scoreboard ledger",
        legendrank=4,
        marker=dict(symbol="circle-open", size=24, color=INK, line=dict(width=1.8, color=INK)), hoverinfo="skip"))

    n_long, n_short = int((plot["rule_side"] == "LONG").sum()), int((plot["rule_side"] == "SHORT").sum())
    n_flag_long, n_flag_short = int(plot["long"].sum()), int(plot["short"].sum())
    legs_text = " and ".join(text for n, text in ((n_flag_long, f"{n_flag_long} paper long{'s' * (n_flag_long > 1)}"),
                                                   (n_flag_short, f"{n_flag_short} paper short{'s' * (n_flag_short > 1)}"))
                             if n) or "no paper legs"
    fig.update_layout(
        title=dict(text=(f"{n_short or 'None'} of {len(plot)} names score below {SHORT_BELOW} and "
                         f"{n_long or 'none'} above {LONG_ABOVE}; the scoreboard ledger holds {legs_text}"),
                   subtitle=dict(text=(f"US hotlist, {MEETING.get(meta['checkpoint_index'], '')} meeting of "
                                       f"{meta['decision_session_date']}.<br>Big dot = published composite; hollow "
                                       "dots = seat scores; grey bar = lowest to highest seat."))),
        xaxis=dict(title="Score, 0-100 scale (low = bearish, high = bullish)", range=[-2, 102],
                   tickvals=[0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100], zeroline=False),
        yaxis=dict(title=None, categoryorder="array", categoryarray=order, showgrid=False),
        height=245 + 30 * len(plot), margin=dict(t=125, b=130),
        legend=dict(orientation="h", x=0, xanchor="left", yref="container", y=0.01, yanchor="bottom"))
    fig.show()

    twin = plot.sort_values("rank")[["rank", "ticker", "composite_score", "rule_side", "flag", "n_seats",
                                     "seat_min", "seat_max", "stop_state", "duration_on_list_days"]]
    display(twin.style.format({"composite_score": "{:.1f}", "seat_min": "{:.0f}", "seat_max": "{:.0f}",
                               "rank": "{:.0f}", "duration_on_list_days": "{:.0f}"},
                              escape="html").hide(axis="index"))

# %% [markdown]
# **How to read this.** Read across each row. The big dot tells you the zone:
# blue right of the 70 line is LONG, red left of the 30 line is SHORT, grey in
# between is HOLD. The grey bar shows how much the seats disagree on that name:
# a short bar means the seats broadly agree, and a long bar means at least one
# seat sees it very differently. A ring means the name is a leg of the
# scoreboard's paper ledger. A big dot in a coloured zone **without** a ring is a
# name the ledger did not take. The table under the chart has the same numbers.
#
# **Caveats.**
#
# - The composite summarises the seats, so one extreme seat can pull it across a
#   line. Section 6.3 measures how often that would happen.
# - Names where macro or risk scored share the chart with names where they did
#   not. The cleaning check above shows which seats the published composite
#   actually averages.
# - A blank zero (×) may be a review that was never filed rather than the most
#   bearish opinion possible. It still counts in the published composite and can
#   anchor the grey bar at 0. Section 6.3 shows which zones depend on it.
# - The zones here are drawn on the composite. The book's rule reads its own
#   `grade_score`, which can be far away (section 6.1).
# - This is one checkpoint. The hotlist changes during the session, and a name can
#   leave it (see `left_convictions` below). Check the checkpoint's age printed
#   after the call.

# %% [markdown]
# ### Chart: what each seat thinks of each name
#
# The same scores as a grid: one row per name (ranked), one column per seat. The
# colour scale is diverging and centred at 50: blue cells lean bullish, red cells
# lean bearish, and the palest cells sit near the neutral midpoint. The two kinds
# of gap from step 5 get different marks: a dash (–) is a seat that did not report
# on the name, and a "c" is a seat that filed a comment without a score. A cell
# reading 0* with a dotted outline is a blank zero: a score of 0 with no comment.

# %%
if wide.notna().sum().sum() == 0:
    display(Markdown("> No seat scores to chart."))
else:
    ranked = board.dropna(subset=["composite_score"]).sort_values("rank")
    grid = wide.reindex(index=ranked["ticker"])
    here = present.reindex(index=grid.index).notna()                  # the seat key exists for this name
    comments = comments_wide.reindex(index=grid.index)
    blank = zero_no_comment.reindex(index=grid.index)

    def cell_label(score, reported: bool, blank_zero: bool) -> str:
        if pd.isna(score):
            return "c" if reported else "–"
        return "0*" if blank_zero else f"{score:.0f}"

    def cell_hover(score, reported: bool, comment, blank_zero: bool) -> str:
        if not reported:
            return "seat did not report on this name"
        head = "no score" if pd.isna(score) else f"score {score:.0f}"
        if blank_zero:
            return f"{head}, no comment: possibly a review that was never filed"
        text = ("no comment" if not isinstance(comment, str) or not comment.strip()
                else comment if len(comment) <= 110 else comment[:110] + "…")
        return f"{head}<br>{text}"

    cell_text = [[cell_label(grid.iat[i, j], here.iat[i, j], blank.iat[i, j]) for j in range(len(SEATS))]
                 for i in range(len(grid))]
    hover_text = [[cell_hover(grid.iat[i, j], here.iat[i, j], comments.iat[i, j], blank.iat[i, j])
                   for j in range(len(SEATS))] for i in range(len(grid))]
    spread = grid.max(axis=1) - grid.min(axis=1)
    contested = spread.idxmax()
    y_labels = [f"{t} · {c:.0f}" for t, c in zip(ranked["ticker"], ranked["composite_score"])]

    fig = go.Figure(go.Heatmap(
        z=grid.to_numpy(dtype=float), x=[s.capitalize() for s in SEATS], y=y_labels,
        text=cell_text, texttemplate="%{text}", textfont=dict(size=12),
        customdata=hover_text, hoverongaps=True,                      # gaps hover too: comment-only seats
        colorscale=DIVERGING, zmin=0, zmax=100, zmid=50, xgap=2, ygap=2,
        colorbar=dict(title=dict(text="Seat score<br>(0-100)"), tickvals=[0, 30, 50, 70, 100], len=0.8,
                      thickness=14),
        hovertemplate="<b>%{y}</b> · %{x}<br>%{customdata}<extra></extra>"))
    for i, j in zip(*np.nonzero(blank.to_numpy())):                   # outline each blank zero
        fig.add_shape(type="rect", xref="x", yref="y", x0=j - 0.5, x1=j + 0.5, y0=i - 0.5, y1=i + 0.5,
                      line=dict(color=INK, width=1.5, dash="dot"))
    gap_note = "– = seat did not report; c = comment without a score"
    if blank.any().any():
        gap_note += ";<br>0* (dotted outline) = scored 0 with no comment, possibly a missing review"
    fig.update_layout(
        title=dict(text=(f"The seats disagree most on {contested}: its seat scores run from "
                         f"{grid.loc[contested].min():.0f} to {grid.loc[contested].max():.0f}"),
                   subtitle=dict(text=("Rows: hotlist names in rank order, labelled with the composite. Columns: "
                                       f"seats.<br>Colour centred at 50 (neutral); {gap_note}."))),
        xaxis=dict(title=None, side="top", showgrid=False, ticks=""),
        yaxis=dict(title=None, autorange="reversed", showgrid=False, ticks=""),
        height=200 + 30 * len(grid), margin=dict(t=165, l=110))
    fig.show()

    twin = grid.copy()
    twin.insert(0, "composite", ranked.set_index("ticker")["composite_score"])
    twin["spread"] = spread
    twin["blank_zeros"] = blank.sum(axis=1)
    display(twin.style.format({**{c: "{:.0f}" for c in twin.columns}, "composite": "{:.1f}"}, na_rep="–"))

# %% [markdown]
# **How to read this.** Scan a row to see one name through each lens. A row that
# is blue from end to end is a name every seat likes. A row with one blue cell
# among red ones is a name where one seat is pushing back: that is the
# "challenge" in action. Scan a column to see one seat's habits. A column that is
# darker than the others belongs to a seat that scores more extremely. A column of
# zeros has two possible readings: the seat is maximally bearish on those names,
# or it did not file a review and the 0 is a placeholder. When the zeros come
# without a comment (0*, dotted outline), the second reading is at least as
# likely, so treat them with care. Hover a cell to read the seat's own comment,
# including the comments that a seat filed without a score (c). The table under
# the chart adds the composite, the spread (highest seat minus lowest seat) and the
# number of blank zeros for each name.
#
# **Caveats.**
#
# - The hotlist is a momentum list, so it is not a random sample of the market.
#   Seat habits here may not carry over to an average stock.
# - Seat comments are generated research text. Treat them as a summary of the
#   inputs the seat saw, not as independent research. Offline fixture comments
#   are placeholders.

# %% [markdown]
# ### Chart: do the seats agree with each other?
#
# If two seats rank the names in a similar order, they agree. We measure that
# with **Spearman's rank correlation, ρ (rho)**. It compares the *ranks* of the
# scores, not the scores themselves, so one seat that scores everything 10
# points higher still "agrees" perfectly with another. ρ = +1 means the same
# order, 0 means no relation, and −1 means opposite orders. Tied scores (such as
# several zeros) share an average rank.
#
# Each pair is computed on the names **both** seats scored, so `n` differs by
# pair. A seat that scored fewer than `MIN_PAIR_N` names is left out of the grid,
# and so is any pair with fewer shared names than that.
#
# Two details keep the p-values honest:
#
# - **A permutation p-value.** With a dozen names and several tied scores, the
#   usual formula for Spearman's p-value is only an approximation. Instead we
#   shuffle one seat's scores across the names thousands of times and count how
#   often a ρ at least as far from 0 turns up by chance.
# - **A Holm correction.** Six pairs tested at once give six chances to look
#   "significant" by luck. Holm's method raises each p-value to allow for that;
#   a pair counts as distinguishable from zero only when its Holm-adjusted p-value
#   is below 0.05.

# %%
def rho_and_p(x: pd.Series, y: pd.Series) -> tuple:
    """Spearman's ρ and a permutation p-value (shuffle x's ranks; tied scores keep their average rank)."""
    rx, ry = stats.rankdata(x), stats.rankdata(y)
    yc = ry - ry.mean()

    def rho(r, axis=-1):                                            # Pearson correlation of the ranks = Spearman
        rc = r - r.mean(axis=axis, keepdims=True)
        return (rc * yc).sum(axis=axis) / np.sqrt((rc**2).sum(axis=axis) * (yc**2).sum())

    result = stats.permutation_test((rx,), rho, permutation_type="pairings", vectorized=True,
                                    n_resamples=9999, random_state=BOOTSTRAP_SEED)
    return float(result.statistic), float(result.pvalue)


def seat_pairs(scores: pd.DataFrame) -> pd.DataFrame:
    """ρ, permutation p and Holm-adjusted p for every pair of CORR_SEATS, on the names both seats scored."""
    out = []
    for i, a in enumerate(CORR_SEATS):
        for b in CORR_SEATS[i + 1:]:
            both = scores[[a, b]].dropna()
            ok = len(both) >= MIN_PAIR_N and both[a].nunique() > 1 and both[b].nunique() > 1
            rho, p = rho_and_p(both[a], both[b]) if ok else (np.nan, np.nan)
            out.append({"seat_a": a, "seat_b": b, "n": len(both), "rho": rho, "p_value": p})
    out = pd.DataFrame(out, columns=["seat_a", "seat_b", "n", "rho", "p_value"])
    out["p_holm"] = np.nan
    tested = out["p_value"].notna()
    if tested.any():
        out.loc[tested, "p_holm"] = multipletests(out.loc[tested, "p_value"], method="holm")[1]
    return out


CORR_SEATS = [s for s in SEATS if wide[s].notna().sum() >= MIN_PAIR_N]
dropped = [s for s in SEATS if s not in CORR_SEATS]
if dropped:
    print(f"Left out of the agreement grid (fewer than {MIN_PAIR_N} names scored): {', '.join(dropped)}.")
pairs = seat_pairs(wide)
shown = pairs.dropna(subset=["rho"])
if len(shown):
    print(f"{len(shown)} seat pairs tested. At the 5% level about {0.05 * len(shown):.1f} of them would look "
          "'significant' by luck alone, even if no two seats were related, so the verdicts use Holm-adjusted "
          "p-values.")

if shown.empty:
    display(Markdown(f"> Not enough overlapping seat scores (need {MIN_PAIR_N} names per pair) for agreement."))
else:
    def rho_needed(n: int) -> float:
        """Roughly the smallest |rho| with p < 0.05 (two-sided) for ONE test on n names (t approximation)."""
        t_crit = stats.t.ppf(0.975, n - 2)
        return t_crit / np.sqrt(n - 2 + t_crit**2)

    n_values = sorted(shown["n"].unique(), reverse=True)
    needed = ", ".join(f"{rho_needed(n):.2f} at n = {n}" for n in n_values)

    rows_, cols_ = CORR_SEATS[1:], CORR_SEATS[:-1]                    # lower triangle only, no diagonal
    lookup = {(r.seat_b, r.seat_a): r for r in pairs.itertuples()}
    z = [[lookup[(r, c)].rho if (r, c) in lookup else np.nan for c in cols_] for r in rows_]
    text = [["" if (r, c) not in lookup else
             (f"{lookup[(r, c)].rho:+.2f}  (n={lookup[(r, c)].n})" if pd.notna(lookup[(r, c)].rho)
              else f"n={lookup[(r, c)].n}: too few") for c in cols_] for r in rows_]
    nmat = [[lookup[(r, c)].n if (r, c) in lookup else 0 for c in cols_] for r in rows_]

    best_pair, worst_pair = shown.loc[shown["rho"].idxmax()], shown.loc[shown["rho"].idxmin()]
    n_sig = int((shown["p_holm"] < 0.05).sum())
    fig = go.Figure(go.Heatmap(
        z=z, x=[c.capitalize() for c in cols_], y=[r.capitalize() for r in rows_],
        text=text, texttemplate="%{text}", customdata=nmat, hoverongaps=False,
        colorscale=DIVERGING, zmin=-1, zmax=1, zmid=0, xgap=3, ygap=3,
        colorbar=dict(title=dict(text="Spearman ρ"), tickvals=[-1, -0.5, 0, 0.5, 1], len=0.8, thickness=14),
        hovertemplate="%{y} vs %{x}<br>ρ = %{z:+.2f} on %{customdata} names<extra></extra>"))
    fig.update_layout(
        title=dict(text=(f"Seats agree most on {best_pair.seat_a}–{best_pair.seat_b} (ρ = {best_pair.rho:+.2f}) "
                         f"and least on {worst_pair.seat_a}–{worst_pair.seat_b} (ρ = {worst_pair.rho:+.2f})"),
                   subtitle=dict(text=("Rank correlation across this checkpoint's hotlist names; n = names both "
                                       f"seats scored.<br>{n_sig} of {len(shown)} pairs beat chance after a Holm "
                                       f"correction (one test alone would need |ρ| above about {needed})."))),
        xaxis=dict(title=None, showgrid=False, ticks=""),
        yaxis=dict(title=None, autorange="reversed", showgrid=False, ticks=""),
        height=200 + 95 * len(rows_), margin=dict(t=125, l=110))
    fig.show()

    display(pairs.assign(distinguishable_from_zero=pairs["p_holm"] < 0.05)
            .sort_values("rho", ascending=False)
            .style.format({"rho": "{:+.2f}", "p_value": "{:.3f}", "p_holm": "{:.3f}"}, na_rep="–")
            .hide(axis="index"))

    # Sensitivity: the same pairs with the blank zeros (score 0, no comment) treated as missing.
    blank_seats = [s for s in CORR_SEATS if zero_no_comment[s].any()]
    if not blank_seats:
        print("No blank zeros among these seats, so there is no sensitivity check to run.")
    else:
        alt = seat_pairs(wide_without_blank_zeros)
        sens = pairs.merge(alt, on=["seat_a", "seat_b"], suffixes=("", "_without_blank_zeros"))
        sens = sens[sens["seat_a"].isin(blank_seats) | sens["seat_b"].isin(blank_seats)]
        print(f"Sensitivity: {int(zero_no_comment[blank_seats].sum().sum())} blank zero(s) in "
              f"{', '.join(blank_seats)}. The pairs that involve them, with and without those cells:")
        display(sens[["seat_a", "seat_b", "n", "rho", "p_holm", "n_without_blank_zeros", "rho_without_blank_zeros",
                      "p_holm_without_blank_zeros"]]
                .style.format({"rho": "{:+.2f}", "rho_without_blank_zeros": "{:+.2f}", "p_holm": "{:.3f}",
                               "p_holm_without_blank_zeros": "{:.3f}"}, na_rep="–").hide(axis="index"))

# %% [markdown]
# **How to read this.** Each cell is one pair of seats. Blue means the two seats
# rank the names in a similar order; red means they tend to disagree; pale means
# no clear relation. The small `n` is the number of names both seats scored.
# Macro and risk score very few names, so they usually drop out of the grid. The
# table lists every pair with its p-value (the chance of a correlation at least
# this strong if the two seats were truly unrelated) and its Holm-adjusted
# p-value, which allows for testing several pairs at once. When the scores carry
# blank zeros, the second table shows each affected pair again without them: if
# ρ changes a lot, the agreement rests on those placeholder-like cells.
#
# **Caveats.**
#
# - About a dozen names is a small sample. A correlation of 0.5 can easily be
#   noise, which is why the subtitle prints a rough threshold for a single test at
#   each sample size.
# - Several pairs are tested at once. The line printed above the chart says how
#   many would look "significant" by luck alone; the Holm correction allows for it.
# - Hotlist names are selected for momentum, so they are not a random sample.
#   Agreement on this list may not carry over to the wider market.
#
# **One seat against the rest.** A second view asks how each seat relates to the
# average of the *other* seats in the composite (`COMPOSITE_SEATS`, found in
# section 4). We leave the seat itself out of that average; otherwise it would
# correlate with itself (a "part-whole" effect). Seats outside the composite get
# no value, so every seat is compared with the same kind of benchmark. The lowest
# value marks the seat that breaks from the council most often: its main
# challenger. The `tilt_vs_composite` column is the seat's average score minus the
# composite, for the names it scored: positive means the seat is more bullish than
# the council.

# %%
if wide.notna().sum().sum() == 0:
    print("No seat scores to summarise.")
else:
    composite_by_name = board.set_index("ticker")["composite_score"].reindex(wide.index)
    seat_stats = []
    for s in SEATS:
        rest = wide[[c for c in COMPOSITE_SEATS if c != s]].mean(axis=1)   # mean of the OTHER composite seats
        both = pd.concat([wide[s], rest], axis=1, keys=["seat", "rest"]).dropna()
        ok = (s in COMPOSITE_SEATS and len(both) >= MIN_PAIR_N and both["seat"].nunique() > 1
              and both["rest"].nunique() > 1)
        seat_stats.append({"seat": s, "in_composite": s in COMPOSITE_SEATS, "names_scored": int(wide[s].notna().sum()),
                           "mean_score": wide[s].mean(), "sd_score": wide[s].std(),
                           "tilt_vs_composite": (wide[s] - composite_by_name).mean(),
                           "rho_with_rest": stats.spearmanr(both["seat"], both["rest"])[0] if ok else np.nan})
    seat_stats = pd.DataFrame(seat_stats).set_index("seat")
    display(seat_stats.style.format({"mean_score": "{:.1f}", "sd_score": "{:.1f}", "tilt_vs_composite": "{:+.1f}",
                                     "rho_with_rest": "{:+.2f}"}, na_rep="–"))
    if seat_stats["rho_with_rest"].notna().any():
        contrarian = seat_stats["rho_with_rest"].idxmin()
        print(f"Least aligned seat at this checkpoint: {contrarian} (rank correlation with the other composite "
              f"seats' average: {seat_stats.loc[contrarian, 'rho_with_rest']:+.2f}).")

# %% [markdown]
# ### How the seats explain and challenge each call
#
# Every name carries a short decision record in its pick ledger:
#
# - `strongest_agents`: the three seats with the **highest** scores;
# - `caution_agents`: three seats the record lists as **urging caution**. They are
#   usually low scorers, but the record picks them itself, so a seat that filed a
#   comment without a score can appear, and the list is not simply the three
#   lowest scores;
# - `stop`: the scoreboard ledger's own paper stop state (`watch_only`,
#   `working` or `stopped_out`). It watches the direction-adjusted return since
#   the anchor close against a hard stop and a warning level, printed below.
#
# For a paper LONG, the strongest seats make the case and the caution seats push
# back. For a paper SHORT it is the other way round: low scores make the case for
# the short, so the *highest* scores are the challengers. The code checks that
# each decision direction matches the paper flag. The seats' comments sit next to
# the call; they do not make it.

# %%
def seat_list(agents: list) -> str:
    """[{'agent': 'technical', 'score': 72.0, ...}, ...] -> 'technical 72 · fundamental 28'."""
    return " · ".join(f"{a['agent']} {a['score']:.0f}" if a["score"] is not None else f"{a['agent']} n/a"
                      for a in agents)


explain = pd.DataFrame([{
    "rank": n["rank"], "ticker": str(n["ticker"]), "composite": n["composite_score"],
    "decision": n["pick_ledger"]["decision"]["direction"],
    "strongest_seats": seat_list(n["pick_ledger"]["decision"]["strongest_agents"]),
    "caution_seats": seat_list(n["pick_ledger"]["decision"]["caution_agents"]),
    "stop_state": n["pick_ledger"]["stop"]["state"],
    "return_since_pct": n["return_since"]["return_since_pct"] if n["return_since"] is not None else None,
    "since": n["return_since"]["anchor_date"] if n["return_since"] is not None else None,
} for n in names_raw], columns=["rank", "ticker", "composite", "decision", "strongest_seats", "caution_seats",
                                "stop_state", "return_since_pct", "since"])
explain = explain.drop_duplicates(subset="ticker").sort_values("rank")
explain["return_since_pct"] = pd.to_numeric(explain["return_since_pct"], errors="coerce")

if explain.empty:
    print("No decision records yet.")
else:
    legs = explain[explain["decision"] != "watch only"]
    print(f"{len(legs)} of {len(explain)} names are paper legs in the scoreboard ledger; "
          f"stop states: {explain['stop_state'].value_counts().to_dict()}.")
    levels = sorted({(n["pick_ledger"]["stop"]["hard_stop_pct"], n["pick_ledger"]["stop"]["warning_pct"])
                     for n in names_raw})
    print("Ledger stop levels (hard stop %, warning %):", levels)
    as_flag = explain["decision"].map({"paper long": "LONG", "paper short": "SHORT"}).fillna("not flagged")
    matches = (as_flag.to_numpy() == explain["ticker"].map(board.set_index("ticker")["flag"]).to_numpy()).sum()
    print(f"The decision direction matches the paper flag for {int(matches)} of {len(explain)} names.")
    display(explain.style.format({"composite": "{:.1f}", "return_since_pct": "{:+.2f}%"}, na_rep="–",
                                 escape="html").hide(axis="index"))

reflections = pd.DataFrame(meta["stop_reflections"],
                           columns=["ticker", "direction", "return_since_pct", "picked_at", "message"])
left = pd.DataFrame(meta["left_convictions"])
print(f"\nStop reflections (paper legs that breached the hard stop): {len(reflections)}")
if not reflections.empty:
    display(reflections.style.format({"return_since_pct": "{:+.2f}%"}, escape="html").hide(axis="index"))
print(f"Names that recently left the hotlist (left_convictions): {len(left)}")
if not left.empty:
    display(left.style.format(escape="html").hide(axis="index"))

# %% [markdown]
# **How to read this.** Compare the two seat columns with the decision. A paper
# long whose caution seats still score 60 or more has broad support. A paper short
# whose strongest seat scores 30 has no seat arguing against it; one whose
# strongest seat scores 70 carries a strong dissent. Read `stop_state` together
# with `return_since_pct`: `working` means the leg is still open in the ledger,
# and `stopped_out` means the direction-adjusted return breached the hard stop.
# A stopped leg then appears under "stop reflections", with a prompt to revisit
# the thesis.
#
# **Caveats.**
#
# - The ledger's hard stop is a scoreboard monitor. The grade book in section 5
#   has a different exit rule (the Drop Out Zone). They are separate records.
# - `return_since_pct` is direction-adjusted: a short gains when the price falls,
#   so a positive number is good for either side. It runs from the anchor close
#   (`since`) to the latest price, which can be weeks later when the council has
#   not met. A large number on an old checkpoint is a long holding period, not a
#   quick win.

# %% [markdown]
# ## 5. The grade book: `/api/v1/ai/grade-book`
#
# **What it is for.** The grade book is the single deterministic paper book. Each
# row is one paper position that the rule opened: its side, entry, grade, the
# Drop Out Zone that closes it, and, once closed, the outcome. A second list,
# `decisions`, holds the latest grade date's actionable grades (above 70 or below
# 30) and whether each one passed the gates.
#
# Parameters: `market` (the council covers `us`; other markets return an empty
# book) and `limit` (1-200, default 80). `limit` caps the position rows only, not
# the decisions. Rows come newest first, so a bigger limit reaches further back.
#
# **The exit contract.** The response also publishes how positions close, in
# `exit_contract`. We print it right after the call, because it decides what the
# position chart may draw. Today it has one rule, the **Drop Out Zone**:
# `zone = day_low + (day_high − day_low) / 3`, a level one third of the way up a
# session's range. A position closes when an observed price falls below the
# same session's zone. Fixed stops, take-profit, profit ratchets and time exits
# are all switched off, so the book has **no** fixed stop and **no** target. The
# rows still carry a `stop_price` column; it simply mirrors the zone.

# %%
book_payload = sf_try("/api/v1/ai/grade-book", market=BOOK_MARKET, limit=BOOK_LIMIT)
BOOK_AVAILABLE = book_payload is not None
if not BOOK_AVAILABLE:                                         # unavailable: continue with an empty book
    book_payload = {"data": {"rows": [], "decisions": [], "exit_contract": None, "disclaimer": None}}
else:
    show_freshness(book_payload, "Grade book:")

book_data = book_payload["data"]
rows_raw = records(book_payload, "ai_grade_book")
decisions_raw = records(book_payload, "ai_grade_book_decisions")
contract = book_data["exit_contract"] if rows_raw else book_data.get("exit_contract")   # promised with rows
EXIT_FLAGS = {k: v for k, v in contract.items() if k.endswith("_enabled")} if contract else {}
if contract:
    print(f"Exit rule: {contract['rule']}  |  zone = {contract['formula']}  |  trigger: {contract['trigger']}")
    print(f"Other exits switched on: {[k for k, v in EXIT_FLAGS.items() if v] or 'none'}; "
          f"switched off: {[k for k, v in EXIT_FLAGS.items() if not v]}.")
    print(f"Can the entry session itself trigger the exit? {contract['entry_cutoff_can_exit']}.")
if book_data.get("disclaimer"):
    print(f"Disclaimer: {book_data['disclaimer']}")

print(f"\n{len(rows_raw)} position rows and {len(decisions_raw)} opener decisions.")
if not BOOK_AVAILABLE:
    display(Markdown("> The grade-book cells below will skip their charts. Section 4 is unaffected."))
elif not rows_raw:
    display(Markdown("> **The book is empty.** That is normal for a market the council does not cover, or "
                     "before the first position opens. The charts below will say so and skip."))

# %% [markdown]
# `show_freshness` can only see `market` here, because the book carries no
# top-level as-of field. The real freshness clues are the latest price date on
# the rows and the `built_at` stamp on the decisions. We print both after cleaning.
#
# **Raw preview.** The `gates` object stays nested in this view.

# %%
book_raw = pd.DataFrame(rows_raw)
print(f"{book_raw.shape[0]} rows x {book_raw.shape[1]} columns")
book_raw.head()

# %% [markdown]
# ### Cleaning the grade book
#
# 1. **Keep the documented columns.** `pick` raises if one is missing.
# 2. **Tickers as text; de-duplicate** on the natural key (`ticker`, `side`,
#    `grade_date`): one position per name, side and grade day.
# 3. **Numbers and dates.** Prices and returns become numbers. `grade_date`,
#    `exit_date` and the other `*_date` fields are exchange session dates (no
#    time of day), so we parse them as plain dates. `drop_out_observed_at` is a
#    timestamp, so it is parsed as UTC.
# 4. **Unpack the gate record** of each position (its entry-day gates) into flat
#    columns.

# %%
BOOK_COLS = ["ticker", "side", "status", "grade_date", "entry_date", "entry_price", "grade_score", "stop_price",
             "take_profit_price", "horizon_end_date", "ratchet_armed", "peak_price", "drop_out_zone",
             "drop_out_zone_date", "drop_out_zone_day_high", "drop_out_zone_day_low", "drop_out_observed_price",
             "drop_out_observed_at", "latest_price", "latest_price_date", "unrealized_return_pct", "exit_date",
             "exit_price", "close_reason", "realized_return_pct", "holding_days", "gates"]
NUM_COLS = ["entry_price", "grade_score", "stop_price", "take_profit_price", "peak_price", "drop_out_zone",
            "drop_out_zone_day_high", "drop_out_zone_day_low", "drop_out_observed_price", "latest_price",
            "unrealized_return_pct", "exit_price", "realized_return_pct", "holding_days"]
DATE_COLS = ["grade_date", "entry_date", "drop_out_zone_date", "latest_price_date", "exit_date", "horizon_end_date"]
GATES = {"g1_strict_grade": "G1 strict grade", "g2_six_promoted_reviews": "G2 six reviews",
         "g3_rationale_contract": "G3 rationale", "g4_review_fresh": "G4 review fresh",
         "g5_drop_out_zone_current": "G5 zone current", "g6_no_active_risk_veto": "G6 no risk veto"}

book = pick(book_raw, BOOK_COLS)                                           # step 1
book["ticker"] = book["ticker"].astype(str)                               # step 2
n0 = len(book)
book = book.drop_duplicates(subset=["ticker", "side", "grade_date"], keep="first").reset_index(drop=True)
print(f"De-duplication: {n0} -> {len(book)} rows.")

missing_before = book[NUM_COLS].isna().sum()                              # step 3
for col in NUM_COLS:
    book[col] = pd.to_numeric(book[col], errors="coerce")
print(f"Coercion: {int((book[NUM_COLS].isna().sum() - missing_before).sum())} values were not numbers.")
for col in DATE_COLS:
    book[col] = pd.to_datetime(book[col], format="%Y-%m-%d")
book["drop_out_observed_at"] = pd.to_datetime(book["drop_out_observed_at"], utc=True)

gate_cols = pd.DataFrame([{  # step 4: g6 exists only on gates written under council v3_0 (from 2026-09-04)
    **{name: g[key] for key, name in GATES.items() if key != "g6_no_active_risk_veto"},
    GATES["g6_no_active_risk_veto"]: g.get("g6_no_active_risk_veto"),
    "g3_warn_only": g["g3_warn_only"], "agents_reviewed": g["agents_reviewed"],
    "agents_expected": g["agents_expected"], "council_version": g["council_contract_version"],
    "review_checkpoint": g["review_checkpoint"]} for g in book["gates"]],
    columns=list(GATES.values()) + ["g3_warn_only", "agents_reviewed", "agents_expected", "council_version",
                                    "review_checkpoint"])
book = pd.concat([book.drop(columns="gates"), gate_cols], axis=1)
is_open, is_closed = book["status"] == "open", book["status"] == "closed"

if not book.empty:
    print(f"Positions graded {book['grade_date'].min():%Y-%m-%d} to {book['grade_date'].max():%Y-%m-%d}; "
          f"latest price date {book['latest_price_date'].max():%Y-%m-%d}.")
    print("Rows by side and status:", book.groupby(["side", "status"]).size().to_dict())
    repeats = len(book) - book["ticker"].nunique()
    print(f"{book['ticker'].nunique()} distinct tickers in {len(book)} positions"
          + (f": {repeats} positions are repeat grades of a name already in the book." if repeats else "."))
book.head()

# %% [markdown]
# 5. **Audit the gaps by status, then set a policy.** In this book, many nulls
#    are expected:
#
#    - the outcome fields (`exit_date`, `exit_price`, `close_reason`,
#      `realized_return_pct`, `holding_days`) are null **while a position is open**;
#    - `take_profit_price` and `horizon_end_date` are null **everywhere** while the
#      exit contract switches take-profit and time exits off;
#    - `G6 no risk veto` is null on rows whose gates were written before the
#      council v3_0 contract.
#
#    The audit labels each gap as expected or unexpected. We keep every NaN and
#    never fill it, and each analysis below uses only the rows it needs.

# %%
OUTCOME_COLS = ["exit_date", "exit_price", "close_reason", "realized_return_pct", "holding_days"]
DISABLED_COLS = [col for col, flag in (("take_profit_price", "take_profit_enabled"),
                                       ("horizon_end_date", "time_exit_enabled")) if not EXIT_FLAGS.get(flag)]
audit = pd.DataFrame({
    "missing_open": book[is_open].isna().sum(),
    "missing_closed": book[is_closed].isna().sum(),
})
audit = audit[(audit["missing_open"] > 0) | (audit["missing_closed"] > 0)]
audit["policy"] = np.select(
    [audit.index.isin(DISABLED_COLS), audit.index.isin(OUTCOME_COLS) & (audit["missing_closed"] == 0),
     audit.index == GATES["g6_no_active_risk_veto"]],
    ["expected: switched off in the exit contract", "expected: no outcome while open",
     "expected: older council contract"],
    default="UNEXPECTED: investigate")
display(audit if not audit.empty else Markdown("No missing values."))

# %% [markdown]
# 6. **Check the contract in the data.** The response makes several promises: the
#    side follows the rule, the zone follows its formula, the switched-off exits
#    leave no trace, returns are side-aware, and every exit happened through the
#    zone. Each line below tests one promise and counts the rows that break it.
#    This is the habit that catches silent API changes. A check here never stops
#    the notebook; it reports.
#
#    Two details the checks confirm: on a closed row `latest_price` is the close
#    of the exit day (`latest_price_date` equals `exit_date`), so
#    `unrealized_return_pct` is that close's mark, while `realized_return_pct`
#    uses the observed exit price. And because the entry session cannot trigger
#    the exit, every closed position was held at least one day.
#
#    The gate check reads the gates the same way as the decisions table below:
#    G1, G2, G4 and G5 must pass; G3 must pass unless it is warn-only; G6 must
#    pass where it was recorded (older rows have no G6 at all).

# %%
sign = book["side"].map(SIDE_SIGN)
zone_formula = book["drop_out_zone_day_low"] + (book["drop_out_zone_day_high"] - book["drop_out_zone_day_low"]) / 3
blocking = [GATES[k] for k in ("g1_strict_grade", "g2_six_promoted_reviews", "g4_review_fresh",
                               "g5_drop_out_zone_current")]
g6_ok = book[GATES["g6_no_active_risk_veto"]].map(lambda v: True if v is None or pd.isna(v) else bool(v))
g3_ok = book[GATES["g3_rationale_contract"]].astype(bool) | book["g3_warn_only"].astype(bool)   # blocks unless warn-only
gates_ok = book[blocking].astype(bool).all(axis=1) & g6_ok.astype(bool) & g3_ok


def move(level: pd.Series) -> pd.Series:
    """Side-aware move from entry, in percent (+0.0 turns -0.0 into 0.0)."""
    return sign * (level - book["entry_price"]) / book["entry_price"] * 100 + 0.0


checks = [
    ("side follows the rule (grade above 70 LONG, below 30 SHORT)",
     book["side"] == book["grade_score"].map(grade_side), True),
    ("entry_date equals grade_date", book["entry_date"] == book["grade_date"], True),
    ("zone = day_low + (day_high - day_low) / 3", np.isclose(book["drop_out_zone"], zone_formula, atol=1e-3), True),
    ("stop_price only mirrors the zone (fixed stop switched off)",
     np.isclose(book["stop_price"], book["drop_out_zone"]), not EXIT_FLAGS.get("fixed_stop_enabled", False)),
    ("take_profit_price is null (take-profit switched off)", book["take_profit_price"].isna(),
     not EXIT_FLAGS.get("take_profit_enabled", False)),
    ("horizon_end_date is null (time exit switched off)", book["horizon_end_date"].isna(),
     not EXIT_FLAGS.get("time_exit_enabled", False)),
    ("ratchet_armed is false (profit ratchet switched off)", book["ratchet_armed"] == False,  # noqa: E712
     not EXIT_FLAGS.get("profit_ratchet_enabled", False)),
    ("peak is side-aware (at or above entry for LONG, at or below for SHORT)", move(book["peak_price"]) >= -1e-9, True),
    ("unrealised return = sign x (latest - entry) / entry",
     np.isclose(move(book["latest_price"]), book["unrealized_return_pct"], atol=0.01), True),
    ("realised return = sign x (exit - entry) / entry",
     np.isclose(move(book["exit_price"]), book["realized_return_pct"], atol=0.01), is_closed),
    ("holding_days = calendar days from entry to exit",
     (book["exit_date"] - book["entry_date"]).dt.days == book["holding_days"], is_closed),
    ("closed rows are marked on the exit day (latest_price_date = exit_date)",
     book["latest_price_date"] == book["exit_date"], is_closed),
    ("no exit on the entry session (held at least one day)", book["exit_date"] > book["entry_date"],
     is_closed & ((contract or {}).get("entry_cutoff_can_exit") is False)),
    ("close_reason is drop_out_zone", book["close_reason"] == "drop_out_zone", is_closed),
    ("exit price = the observed price", np.isclose(book["exit_price"], book["drop_out_observed_price"]), is_closed),
    ("exit fired: observed price below that session's zone (zone date = exit date)",
     (book["drop_out_observed_price"] < book["drop_out_zone"]) & (book["drop_out_zone_date"] == book["exit_date"]),
     is_closed),
    ("every blocking entry gate passed (G1, G2, G4, G5; G3 unless warn-only; G6 where recorded)", gates_ok, True),
]
check_table = []
for name, ok, applies in checks:
    applies = pd.Series(applies, index=book.index)                   # a scalar True/False applies to every row
    ok = pd.Series(ok, index=book.index)[applies]
    check_table.append({"check": name, "rows_checked": int(applies.sum()), "rows_failing": int((~ok).sum()),
                        "result": "n/a (no rows)" if applies.sum() == 0 else "pass" if ok.all() else "CHECK"})
check_table = pd.DataFrame(check_table)
display(check_table.style.format(escape="html").hide(axis="index"))
g6_recorded = int(book[GATES["g6_no_active_risk_veto"]].notna().sum())
if not book.empty:
    print(f"G6 recorded on {g6_recorded} of {len(book)} rows; the gate check passes the others on G1-G5 alone."
          if g6_recorded < len(book) else f"G6 recorded on all {len(book)} rows.")

flag_open = book[is_open & (book["drop_out_observed_price"] < book["drop_out_zone"])]
if not flag_open.empty:
    shown_names = ", ".join(flag_open["ticker"].head(10)) + (", ..." if len(flag_open) > 10 else "")
    print(f"For you to check: {len(flag_open)} open row(s) show an observed price below the zone "
          f"({shown_names}). The book may not have processed that observation yet.")

# %% [markdown]
# The first line is the heart of the notebook. When it passes, **every
# position's side is exactly what the rule says for its grade**: nothing, seat or
# otherwise, overrode the rule once the grade was set. What this check cannot show
# is how `grade_score` itself was produced. No published field lets us test
# whether the seats' views feed into the grade; for that part we rely on the
# book's own disclaimer, printed after the call.
#
# The last line shows that every position passed its blocking gates on the day it
# opened (G6 only where it was recorded; the line under the table says how often).
# Gates decide *whether* a graded name opens. They do not decide its side.

# %% [markdown]
# ### Chart: positions from entry to exit
#
# This chart shows each position's key levels on one line. LONG and SHORT
# positions move in opposite directions, so raw prices would be confusing. We
# convert every level to a **side-aware move from entry**:
#
# `move % = sign × (level − entry) / entry × 100`, with sign +1 for LONG and −1 for SHORT.
#
# After this step, **right of zero is always good for the position**, whatever
# its side. Open positions are marked to the latest price and closed ones to
# their exit price. For each row:
#
# - the coloured bar runs from the entry (0) to the latest or exit mark;
# - the black triangle is the **Drop Out Zone**, the only exit level (for a closed
#   position, the zone of the exit session). It points the way the exit fires.
#   The book has one price trigger for both sides (an observed price below the
#   zone), and on the side-aware axis that trigger lands on opposite sides: ◄ on
#   a LONG row (the exit fires if the mark moves left of it) and ► on a SHORT row
#   (the exit fires if the mark moves right of it);
# - the grey diamond is the best close since entry (`peak_price`);
# - no stop or target is drawn, because the exit contract switches them off. If
#   SurgeFlow ever switches take-profit on, the chart draws it automatically.

# %%
if book.empty:
    display(Markdown("> The grade book is empty, so there are no positions to draw."))
else:
    open_pos = book[is_open].sort_values("grade_date", ascending=False)
    recent = (book[is_closed].sort_values(["exit_date", "grade_date"], ascending=False).head(LADDER_CLOSED)
              .sort_values("grade_date", ascending=False))            # most recent exits, listed by entry date
    ladder = pd.concat([open_pos.assign(panel="open"), recent.assign(panel="closed")], ignore_index=True)
    side_sign = ladder["side"].map(SIDE_SIGN)
    ladder["mark_price"] = ladder["latest_price"].where(ladder["panel"] == "open", ladder["exit_price"])
    for level in ("drop_out_zone", "mark_price", "peak_price", "take_profit_price"):
        ladder[f"{level}_move"] = side_sign * (ladder[level] - ladder["entry_price"]) / ladder["entry_price"] * 100 + 0.0
    ladder["label"] = ladder["ticker"] + " · " + ladder["grade_date"].dt.strftime("%b %d")
    if ladder["label"].duplicated().any():
        ladder["label"] = ladder["label"] + " · " + ladder["side"]
    ladder["hover"] = [
        (f"<b>{r.ticker}</b> · paper {r.side} · grade {r.grade_score:.1f}<br>"
         f"Entry {usd(r.entry_price)} on {r.grade_date:%Y-%m-%d}<br>"
         + (f"Latest {usd(r.mark_price)} ({r.latest_price_date:%Y-%m-%d}): {pct(r.mark_price_move, 2)}"
            if r.panel == "open" else
            f"Exit {usd(r.mark_price)} on {r.exit_date:%Y-%m-%d} after {r.holding_days:.0f} days: "
            f"{pct(r.mark_price_move, 2)}")
         + f"<br>Drop Out Zone {usd(r.drop_out_zone)} ({pct(r.drop_out_zone_move, 2)}), session {r.drop_out_zone_date:%Y-%m-%d}"
         + ("<br>Exit fires if the price falls below the zone: the mark crosses to the left of ◄"
            if r.side == "LONG" else
            "<br>Exit fires if the price falls below the zone: on this axis the mark crosses to the right of ►")
         + f"<br>Best close {usd(r.peak_price)} ({pct(r.peak_price_move, 2)})")
        for r in ladder.itertuples()]

    panels = [p for p in ("open", "closed") if (ladder["panel"] == p).any()]
    titles = {"open": f"Open positions ({len(open_pos)}), marked to the latest price",
              "closed": f"The {len(recent)} most recently closed positions, marked at the exit price"}
    fig = make_subplots(rows=len(panels), cols=1, shared_xaxes=True, vertical_spacing=0.12 if len(panels) > 1 else 0,
                        row_heights=[max((ladder["panel"] == p).sum(), 2) for p in panels],
                        subplot_titles=[titles[p] for p in panels])
    shown_legend = set()
    for row_i, panel in enumerate(panels, start=1):
        part = ladder[ladder["panel"] == panel]
        fig.add_trace(go.Scatter(                                     # drawn first, so it sits underneath
            x=part["peak_price_move"], y=part["label"], mode="markers", name="Best close since entry",
            legendgroup="peak", showlegend=row_i == 1, legendrank=5,
            marker=dict(symbol="diamond-open", size=10, color=INK_2, line=dict(width=1.5, color=INK_2)),
            hoverinfo="skip"), row=row_i, col=1)
        for side in ("LONG", "SHORT"):
            sub = part[part["side"] == side]
            if sub.empty:
                continue
            xs, ys = [], []
            for r in sub.itertuples():
                xs += [0, r.mark_price_move, None]
                ys += [r.label, r.label, None]
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=SIDE_COLORS[side], width=4),
                                     legendgroup=side, showlegend=False, hoverinfo="skip"), row=row_i, col=1)
            fig.add_trace(go.Scatter(
                x=sub["mark_price_move"], y=sub["label"], mode="markers", name=f"Paper {side}: entry → mark",
                legendgroup=side, showlegend=side not in shown_legend, legendrank=1 if side == "LONG" else 2,
                marker=dict(size=12, color=SIDE_COLORS[side], line=dict(width=1.5, color=SURFACE)),
                customdata=sub["hover"], hovertemplate="%{customdata}<extra></extra>"), row=row_i, col=1)
            shown_legend.add(side)
        for side, symbol, name in (("LONG", "triangle-left", "Drop Out Zone ◄ (a LONG exits left of it)"),
                                   ("SHORT", "triangle-right", "Drop Out Zone ► (a SHORT exits right of it)")):
            sub = part[part["side"] == side]                          # one trigger, opposite sides of this axis
            if sub.empty:
                continue
            fig.add_trace(go.Scatter(
                x=sub["drop_out_zone_move"], y=sub["label"], mode="markers", name=name,
                legendgroup=f"zone_{side}", showlegend=f"zone_{side}" not in shown_legend,
                legendrank=3 if side == "LONG" else 4,
                marker=dict(symbol=symbol, size=12, color=INK, line=dict(width=1, color=INK)),
                customdata=sub["hover"], hovertemplate="%{customdata}<extra></extra>"), row=row_i, col=1)
            shown_legend.add(f"zone_{side}")
        if part["take_profit_price_move"].notna().any():
            tp = part.dropna(subset=["take_profit_price_move"])
            fig.add_trace(go.Scatter(
                x=tp["take_profit_price_move"], y=tp["label"], mode="markers", name="Take-profit",
                legendgroup="tp", showlegend=row_i == 1, legendrank=6,
                marker=dict(symbol="line-ns", size=18, color=MUTED, line=dict(width=2.5, color=MUTED))),
                row=row_i, col=1)
        fig.update_yaxes(categoryorder="array", categoryarray=part["label"].tolist()[::-1], showgrid=False,
                         row=row_i, col=1)
    fig.add_vline(x=0, line=dict(color=INK, width=1.4), row="all", col=1)    # the entry price

    if len(open_pos):
        ahead = int((open_pos["unrealized_return_pct"] > 0).sum())
        headline = f"{ahead} of {len(open_pos)} open paper positions are ahead of their entry price"
    else:
        ahead = int((recent["realized_return_pct"] > 0).sum())
        headline = (f"No open paper positions (newest graded {book['grade_date'].max():%b %d}); "
                    f"{ahead} of the last {len(recent)} closed finished ahead of entry")
    fig.update_xaxes(title_text="Move from entry in the position's favour (%)", ticksuffix="%", zeroline=False,
                     row=len(panels), col=1)
    fig.update_layout(
        title=dict(text=headline, subtitle=dict(text=(
            "Side-aware: a LONG gains when the price rises, a SHORT when it falls. 0 = entry; right of 0 = good.<br>"
            "The only exit is the Drop Out Zone: a LONG exits left of its ◄, a SHORT right of its ►. "
            "No stop or target exists."))),
        height=275 + 32 * len(ladder), margin=dict(t=150, b=130, l=120),
        legend=dict(orientation="h", x=0, xanchor="left", yref="container", y=0.01, yanchor="bottom"))
    fig.show()

    display(ladder[["panel", "ticker", "side", "grade_date", "grade_score", "entry_price", "drop_out_zone",
                    "drop_out_zone_date", "peak_price", "mark_price", "drop_out_zone_move", "mark_price_move",
                    "peak_price_move"]]
            .rename(columns={"drop_out_zone_move": "zone_move", "mark_price_move": "mark_move",
                             "peak_price_move": "peak_move"})
            .style.format({"grade_date": "{:%Y-%m-%d}", "drop_out_zone_date": "{:%Y-%m-%d}",
                           "grade_score": "{:.1f}", "entry_price": "${:,.2f}", "drop_out_zone": "${:,.2f}",
                           "peak_price": "${:,.2f}", "mark_price": "${:,.2f}", "zone_move": "{:+.2f}%",
                           "mark_move": "{:+.2f}%", "peak_move": "{:+.2f}%"}, na_rep="–").hide(axis="index"))

# %% [markdown]
# **How to read this.** Start at the vertical line at 0: the entry price. A
# coloured bar going right is a position in profit (on paper); a bar going left
# is a position in a loss. Blue bars are LONG and red bars are SHORT, but thanks
# to the side-aware axis you read them the same way. The grey diamond shows the
# best close since entry, so the gap between the diamond and the dot is profit
# given back. The black triangle is the Drop Out Zone, and it points the way the
# exit fires. A closed LONG's dot sits just **left** of its ◄, because the exit
# fired when the price fell through the zone, which is adverse for a long. A closed
# SHORT's dot sits just **right** of its ►: the same fall in price is favourable
# for a short, so on this axis it moves the mark to the right. An open LONG is
# safe while its dot stays right of ◄, and an open SHORT while its dot stays left
# of ►. The table under the chart has the raw prices and the side-aware moves.
#
# **Caveats.**
#
# - The Drop Out Zone is recomputed from each session's range, so the exit level
#   moves from day to day. It is not a price fixed at entry.
# - The exit contract publishes **one trigger for both sides**: an observed price
#   below the same-session zone. For a LONG that works like a trailing stop. For a
#   SHORT a falling price is good news, so the same trigger often closes a short
#   on a down day, locking in a gain or a smaller loss. We draw the level where the
#   book puts it and quote the contract; we do not reinterpret it.
# - Paper marks use closing or snapshot prices. They ignore spreads, fees,
#   borrow costs for shorts, and slippage.

# %% [markdown]
# ### Outcomes: how did the closed positions end?
#
# A closed position's `realized_return_pct` is side-aware, so a positive number
# is a win for either side. We call a closed position a **hit** when its
# realised return is above zero (exactly zero counts as a miss).
#
# Two tools make small samples honest:
#
# - **Wilson interval for the hit rate.** If 15 of 28 positions hit, the hit rate
#   is 54%, but the true long-run rate could plausibly be anywhere from about 36%
#   to 70%. The Wilson interval gives that range. It behaves better than the
#   textbook "p ± 1.96 × standard error" when n is small or the rate is near 0% or 100%.
# - **Bootstrap interval for the mean return.** We resample the closed positions
#   with replacement 5,000 times and recompute the mean each time. The middle 95%
#   of those means is the interval. It makes no assumption about the shape of the
#   returns, which matters because a few big moves dominate.
#
# The `winsorised_mean_pct` column clips each side's returns at the 5th and 95th
# percentile first. If it differs a lot from the plain mean, a few outliers drive
# the average, and the median is the better summary.
#
# We also record each position's **raw price move**, `(exit − entry) / entry × 100`,
# which is *not* side-aware, and the share of names whose price rose
# (`share_rose`). For a LONG, a hit and a rise are the same thing; for a SHORT, a
# hit is a fall. The next two sections use the raw moves to separate what the
# grade did from what the market did.

# %%
closed = book[is_closed].dropna(subset=["realized_return_pct"]).copy()
closed["hit"] = closed["realized_return_pct"] > 0
closed["raw_move_pct"] = (closed["exit_price"] - closed["entry_price"]) / closed["entry_price"] * 100 + 0.0
closed["rose"] = closed["raw_move_pct"] > 0


def outcome_row(group: pd.DataFrame, label: str) -> dict:
    r, n, hits = group["realized_return_pct"], len(group), int(group["hit"].sum())
    lo, hi = wilson(hits, n)
    b_lo, b_hi = bootstrap_mean_ci(r)
    q_lo, q_hi = r.quantile([WINSOR_Q, 1 - WINSOR_Q]) if n else (np.nan, np.nan)
    return {"side": label, "closed": n, "hits": hits, "hit_rate": hits / n if n else np.nan,
            "hit_rate_lo95": lo, "hit_rate_hi95": hi, "mean_return_pct": r.mean(), "mean_lo95": b_lo,
            "mean_hi95": b_hi, "winsorised_mean_pct": r.clip(q_lo, q_hi).mean(), "median_return_pct": r.median(),
            "best_pct": r.max(), "worst_pct": r.min(), "median_holding_days": group["holding_days"].median(),
            "share_rose": group["rose"].mean(), "mean_price_move_pct": group["raw_move_pct"].mean()}


if closed.empty:
    display(Markdown("> No closed positions yet, so there are no outcomes to summarise."))
    outcomes = pd.DataFrame()
else:
    outcomes = pd.DataFrame([outcome_row(g, side) for side, g in closed.groupby("side")]
                            + [outcome_row(closed, "All")]).set_index("side")

    # Positions overlap in time, so they share market moves and are not independent draws.
    starts, ends = closed["entry_date"].to_numpy(), closed["exit_date"].to_numpy()
    overlaps = [int(((starts <= ends[i]) & (ends >= starts[i])).sum() - 1) for i in range(len(closed))]
    print(f"{len(closed)} closed paper positions, graded {closed['grade_date'].min():%Y-%m-%d} to "
          f"{closed['grade_date'].max():%Y-%m-%d}, on {closed['grade_date'].nunique()} grade days and "
          f"{closed['ticker'].nunique()} distinct tickers. The median position shared its holding window with "
          f"{int(np.median(overlaps))} others.")
    pct_cols = ["mean_return_pct", "mean_lo95", "mean_hi95", "winsorised_mean_pct", "median_return_pct",
                "best_pct", "worst_pct", "mean_price_move_pct"]
    display(outcomes.style.format({**{c: "{:+.2f}%" for c in pct_cols}, "hit_rate": "{:.0%}",
                                   "hit_rate_lo95": "{:.0%}", "hit_rate_hi95": "{:.0%}", "share_rose": "{:.0%}",
                                   "median_holding_days": "{:.0f}"}, na_rep="–"))

# %% [markdown]
# **Open positions: unrealised returns by side.** An open position has no
# outcome yet. Its `unrealized_return_pct` marks it to the latest price, so it
# can still change in either direction. We summarise it separately and never mix
# it with the realised returns above.

# %%
open_book = book[is_open].dropna(subset=["unrealized_return_pct"])
if open_book.empty:
    newest = f" The newest position was graded {book['grade_date'].max():%Y-%m-%d}." if not book.empty else ""
    why = " The gate table below shows why nothing newer has opened." if decisions_raw else ""
    display(Markdown(f"> **No open positions right now**, so there are no unrealised returns to summarise."
                     f"{newest}{why}"))
else:
    unrealised = (open_book.assign(ahead=open_book["unrealized_return_pct"] > 0,
                                   days_open=(open_book["latest_price_date"] - open_book["entry_date"]).dt.days)
                  .groupby("side")
                  .agg(open=("ticker", "size"), ahead=("ahead", "sum"),
                       mean_unrealised_pct=("unrealized_return_pct", "mean"),
                       median_unrealised_pct=("unrealized_return_pct", "median"),
                       median_days_open=("days_open", "median")))
    display(unrealised.style.format({"mean_unrealised_pct": "{:+.2f}%", "median_unrealised_pct": "{:+.2f}%",
                                     "median_days_open": "{:.0f}"}))
    print(f"Marked to prices as of {open_book['latest_price_date'].max():%Y-%m-%d}. Unrealised marks can still "
          "move either way: treat them as a snapshot, not a result.")

# %% [markdown]
# ### How sure can we be? Positions graded on the same day may move together
#
# The intervals above treat every position as an independent draw. That is
# optimistic: positions graded on the same day enter together, ride the same
# market days, and often exit together. A second bootstrap allows for that.
# Instead of resampling positions, it resamples whole **grade days**, keeping each
# day's positions together (a "cluster bootstrap").
#
# If positions from the same day tend to end alike, the by-day interval comes out
# wider, and the `widening` column says by how much. `hit_widening` does the same
# for the hit rate, comparing two bootstraps so that only the resampling differs.
# For a single side, a widening near ×1, or even below it, means same-day
# positions were no more alike than positions from different days. That is useful
# evidence too, not a bug. **Read the `All` row's widening with care:** each grade
# day holds both LONG and SHORT positions, and their side-aware outcomes offset
# each other when the market moves, so resampling whole days can *narrow* the
# interval. Read the widening ratio per side only. The number of grade days in the
# table, not the number of positions, is closer to the number of independent
# observations; when it is small, treat the by-day interval as a rough guide.
#
# **Is it the grade, or the market?** A LONG and a SHORT have opposite market
# exposure. In a window when most hotlist names rose, LONG positions win and SHORT
# positions lose even if the grade has no skill at all; in a falling window it is
# the other way round. So each side's own mean, and each side's verdict below, mixes
# the grade with the market's direction. Two numbers test the grade itself:
#
# - the **pooled side-aware mean** (the `All` row). Its LONG and SHORT halves carry
#   opposite market exposure, which cancels exactly when the sides are the same size;
# - the **LONG minus SHORT spread of raw price moves**: did the names graded above
#   70 rise more than the names graded below 30? With no skill, the spread is zero
#   whatever the market did. Its interval resamples grade days too.

# %%
spread, spread_lo, spread_hi = np.nan, np.nan, np.nan                # the grade test; used by the chart below
if closed.empty:
    print("No closed positions, so there is nothing to resample.")
    sure = pd.DataFrame()
else:
    sure = []
    for label, group in [*closed.groupby("side"), ("All", closed)]:
        lo_i, hi_i = bootstrap_mean_ci(group["realized_return_pct"])
        lo_c, hi_c = cluster_bootstrap_ci(group["realized_return_pct"], group["grade_date"])
        h_lo_i, h_hi_i = bootstrap_mean_ci(group["hit"].astype(float))
        h_lo, h_hi = cluster_bootstrap_ci(group["hit"].astype(float), group["grade_date"])
        sure.append({"side": label, "positions": len(group), "grade_days": group["grade_date"].nunique(),
                     "mean_return_pct": group["realized_return_pct"].mean(), "lo95_positions": lo_i,
                     "hi95_positions": hi_i, "lo95_by_day": lo_c, "hi95_by_day": hi_c,
                     "widening": (hi_c - lo_c) / (hi_i - lo_i) if hi_i > lo_i else np.nan,
                     "hit_lo95_positions": h_lo_i, "hit_hi95_positions": h_hi_i,
                     "hit_lo95_by_day": h_lo, "hit_hi95_by_day": h_hi,
                     "hit_widening": (h_hi - h_lo) / (h_hi_i - h_lo_i) if h_hi_i > h_lo_i else np.nan})
    sure = pd.DataFrame(sure).set_index("side")
    hit_cols = ["hit_lo95_positions", "hit_hi95_positions", "hit_lo95_by_day", "hit_hi95_by_day"]
    display(sure.style.format({**{c: "{:+.2f}%" for c in ["mean_return_pct", "lo95_positions", "hi95_positions",
                                                          "lo95_by_day", "hi95_by_day"]},
                               **{c: "{:.0%}" for c in hit_cols}, "widening": "×{:.2f}", "hit_widening": "×{:.2f}"},
                              na_rep="–"))
    two_sides = {"LONG", "SHORT"} <= set(closed["side"])
    for label in [s for s in ("LONG", "SHORT", "All") if s in sure.index and (s != "All" or two_sides)]:
        lo_c, hi_c = sure.loc[label, ["lo95_by_day", "hi95_by_day"]]
        verdict = ("stays above zero" if lo_c > 0 else "stays below zero" if hi_c < 0 else
                   "includes zero, so this window cannot tell a gain from a loss" if pd.notna(lo_c)
                   else "could not be computed (fewer than two grade days)")
        what = "pooled side-aware mean (both sides together)" if label == "All" else "side-aware mean"
        print(f"{label}: {what} {pct(sure.loc[label, 'mean_return_pct'], 2)} on {int(sure.loc[label, 'positions'])} "
              f"positions from {int(sure.loc[label, 'grade_days'])} grade days; the by-day interval {verdict}.")

    day_means = closed.pivot_table(index="grade_date", columns="side", values="realized_return_pct", aggfunc="mean")
    if {"LONG", "SHORT"} <= set(day_means.columns) and len(day_means.dropna()) >= 3:
        both_days = day_means.dropna()
        r_days = both_days["LONG"].corr(both_days["SHORT"])
        print(f"On the {len(both_days)} grade days with both sides, same-day LONG and SHORT side-aware means "
              f"correlate at {r_days:+.2f}"
              + ("; they tend to offset each other, which is why the All row's widening can fall below ×1."
                 if r_days < 0 else "."))

    print(f"\nMarket direction: {closed['rose'].mean():.0%} of all closed names rose over their holding window "
          f"(mean raw price move {pct(closed['raw_move_pct'].mean(), 2)}). The LONG and SHORT verdicts above each "
          "mix the grade with that market move.")
    if not two_sides:
        print("Only one side has closed positions, so the grade cannot be separated from the market's direction yet.")
    else:
        moves = closed.groupby("side")["raw_move_pct"].mean()
        spread = moves["LONG"] - moves["SHORT"]
        spread_lo, spread_hi = cluster_bootstrap_spread_ci(closed["raw_move_pct"], closed["side"] == "LONG",
                                                           closed["grade_date"])
        verdict = ("LONG names rose more than SHORT names, even allowing for same-day clustering"
                   if spread_lo > 0 else
                   "SHORT names rose more than LONG names, even allowing for same-day clustering: the grade "
                   "pointed the wrong way in this window" if spread_hi < 0 else
                   "the interval includes zero, so this window shows no clear evidence that the grade separated "
                   "rising names from falling ones" if pd.notna(spread_lo) else
                   "the interval could not be computed (fewer than two grade days)")
        print(f"Grade test: LONG names moved {pct(moves['LONG'], 2)} and SHORT names {pct(moves['SHORT'], 2)} on "
              f"average (raw price moves). Spread {pct(spread, 2)}, by-day 95% interval {pct(spread_lo, 2)} to "
              f"{pct(spread_hi, 2)}: {verdict}.")

# %% [markdown]
# ### Chart: hit rate by side, with the sample size in view
#
# The left panel shows each side's hit rate (the dot) with three 95% intervals.
# The coloured bar is the **Wilson** interval, our headline. The two thin grey bars
# below it are bootstraps: the light one resamples positions, the dark one
# resamples whole grade days. Compare the two grey bars with each other to see
# the effect of same-day clustering. The coloured bar uses a different method, so
# its gap to the dark bar mixes method with clustering.
#
# The black tick on each row is the hit rate that side would get **with no skill
# at all**: for a LONG, the share of all closed names (both sides) whose price
# rose; for a SHORT, the share whose price fell. A dot close to its tick means the
# side did about as well as the market's direction alone would give.
#
# The right panel shows every closed position's realised return as a dot, so you
# can see the sample behind the summary. The black tick is the median.
#
# To compare the sides we use **Fisher's exact test**, which asks how often a
# split at least this uneven would happen by chance if both sides had the same
# true rate. We run it twice, and only the second run tests the grade:
#
# - **on the hit rates.** The two sides have opposite market exposure, so in a
#   window when most names rose (or fell), the hit rates differ even when the grade
#   has no skill. A small p-value here is **not** evidence of skill;
# - **on the share of names that rose.** With no skill, LONG and SHORT names rise
#   equally often, whatever the market did.
#
# Fisher's test is exact, so it stays valid with small counts, but like the Wilson
# interval it assumes independent positions.

# %%
sides_present = [s for s in ("LONG", "SHORT") if s in outcomes.index] if not outcomes.empty else []
if not sides_present:
    display(Markdown("> No closed positions to chart."))
else:
    y_pos = {s: i for i, s in enumerate(reversed(sides_present))}
    no_skill = {"LONG": closed["rose"].mean(), "SHORT": (closed["raw_move_pct"] < 0).mean()}
    fisher_p, fisher_rose_p, apart = np.nan, np.nan, False
    if len(sides_present) == 2:
        table = [[outcomes.loc[s, "hits"], outcomes.loc[s, "closed"] - outcomes.loc[s, "hits"]]
                 for s in sides_present]                              # rows: sides; columns: hits, misses
        fisher_p = stats.fisher_exact(table)[1]
        rose_table = [[int(closed.loc[closed["side"] == s, "rose"].sum()),
                       int((~closed.loc[closed["side"] == s, "rose"]).sum())] for s in sides_present]
        fisher_rose_p = stats.fisher_exact(rose_table)[1]
        by_day = sure.loc[sides_present, ["hit_lo95_by_day", "hit_hi95_by_day"]]
        if by_day.notna().all().all():                                # do the by-day intervals overlap?
            (lo_a, hi_a), (lo_b, hi_b) = by_day.to_numpy()
            apart = hi_a < lo_b or hi_b < lo_a

    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, column_widths=[0.4, 0.6], horizontal_spacing=0.05,
                        subplot_titles=("Hit rate with 95% intervals", "Realised return per closed position"))
    rng = np.random.default_rng(BOOTSTRAP_SEED)                         # jitter only spreads dots vertically
    for side in sides_present:
        o, y = outcomes.loc[side], y_pos[side]
        fig.add_trace(go.Scatter(                                     # drawn first, so the dot sits on top
            x=[no_skill[side]], y=[y], mode="markers", name="Hit rate with no skill (market direction alone)",
            legendgroup="no_skill", showlegend=side == sides_present[0], legendrank=4,
            marker=dict(symbol="line-ns", size=26, color=INK, line=dict(width=2.5, color=INK)),
            hovertemplate=(f"<b>{side}</b> with no skill: {no_skill[side]:.0%}<br>(share of all closed names that "
                           f"{'rose' if side == 'LONG' else 'fell'})<extra></extra>")), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=[o["hit_rate"]], y=[y], mode="markers", name=f"{side} (n = {int(o['closed'])})", legendgroup=side,
            legendrank=1 if side == "LONG" else 2,
            marker=dict(size=15, color=SIDE_COLORS[side], line=dict(width=1.5, color=SURFACE)),
            error_x=dict(type="data", symmetric=False, array=[o["hit_rate_hi95"] - o["hit_rate"]],
                         arrayminus=[o["hit_rate"] - o["hit_rate_lo95"]], color=SIDE_COLORS[side],
                         thickness=2.5, width=8),
            hovertemplate=(f"<b>{side}</b><br>{int(o['hits'])} hits of {int(o['closed'])} closed<br>"
                           f"Hit rate {o['hit_rate']:.0%} (Wilson 95%: {o['hit_rate_lo95']:.0%} to "
                           f"{o['hit_rate_hi95']:.0%})<extra></extra>")), row=1, col=1)
        for offset, lo_col, hi_col, colour, label, group, rank in (
                (0.17, "hit_lo95_positions", "hit_hi95_positions", AXIS, "positions resampled", "by_pos", 5),
                (0.3, "hit_lo95_by_day", "hit_hi95_by_day", MUTED, "grade days resampled", "by_day", 6)):
            b_lo, b_hi = sure.loc[side, [lo_col, hi_col]]
            if pd.isna(b_lo):
                continue
            fig.add_trace(go.Scatter(
                x=[b_lo, b_hi], y=[y - offset, y - offset], mode="lines+markers", name=f"95% bootstrap, {label}",
                legendgroup=group, showlegend=side == sides_present[0], legendrank=rank,
                line=dict(color=colour, width=1.8), marker=dict(symbol="line-ns", size=9, color=colour,
                                                                line=dict(width=1.8, color=colour)),
                hovertemplate=(f"<b>{side}</b>, {label}<br>95%: {b_lo:.0%} to {b_hi:.0%}<extra></extra>")),
                row=1, col=1)
        pts = closed[closed["side"] == side]
        fig.add_trace(go.Scatter(
            x=pts["realized_return_pct"], y=y + rng.uniform(-0.22, 0.22, len(pts)), mode="markers",
            legendgroup=side, showlegend=False,
            marker=dict(size=8, color=SIDE_COLORS[side], opacity=0.65, line=dict(width=1, color=SURFACE)),
            customdata=np.stack([pts["ticker"], pts["grade_date"].dt.strftime("%Y-%m-%d"),
                                 pts["holding_days"].map("{:.0f}".format)], axis=-1),
            hovertemplate=("<b>%{customdata[0]}</b> · " + side + " graded %{customdata[1]}<br>"
                           "Realised %{x:+.2f}% after %{customdata[2]} days<extra></extra>")), row=1, col=2)
        fig.add_trace(go.Scatter(
            x=[o["median_return_pct"]], y=[y], mode="markers", name="Median", legendgroup="median",
            showlegend=side == sides_present[0], legendrank=3,
            marker=dict(symbol="line-ns", size=34, color=INK, line=dict(width=3, color=INK)),
            hovertemplate=f"{side} median: {o['median_return_pct']:+.2f}%<extra></extra>"), row=1, col=2)
    fig.add_vline(x=0, line=dict(color=AXIS, width=1.5), row=1, col=2)
    fig.update_xaxes(title_text="Hit rate (share closed in the position's favour)", tickformat=".0%",
                     range=[0, 1], row=1, col=1)
    fig.update_xaxes(title_text="Realised return, side-aware (%)", ticksuffix="%", zeroline=False, row=1, col=2)
    fig.update_yaxes(tickvals=list(y_pos.values()),
                     ticktext=[f"{s}<br>n = {int(outcomes.loc[s, 'closed'])}" for s in y_pos],
                     range=[-0.6, len(y_pos) - 0.4], row=1, col=1)
    fig.update_yaxes(showgrid=False, zeroline=False, ticks="")

    if len(sides_present) == 2:                                       # headline: the grade test, not the hit gap
        rose = outcomes.loc[sides_present, "share_rose"]
        shares = f"LONG {rose['LONG']:.0%}, SHORT {rose['SHORT']:.0%}"
        if spread_lo > 0:
            headline = (f"Names graded LONG rose more than names graded SHORT ({pct(spread, 1)} on average), "
                        "even allowing for same-day clustering")
        elif spread_hi < 0:
            headline = (f"Names graded SHORT rose more than names graded LONG ({pct(-spread, 1)} on average): "
                        "the grade pointed the wrong way in this window")
        elif rose.min() > 0.5:
            headline = f"Most names on both sides rose ({shares}): the hit-rate gap reflects a rising market, not the grade"
        elif rose.max() < 0.5:
            headline = f"Most names on both sides fell ({shares}): the hit-rate gap reflects a falling market, not the grade"
        else:
            headline = f"Share of names that rose: {shares}; no clear sign that the grade separated them"
    else:
        s0 = sides_present[0]
        headline = (f"Only {s0} positions have closed so far ({outcomes.loc[s0, 'hit_rate']:.0%} hit); with one "
                    "side, the grade cannot be separated from the market")
    fig.update_layout(
        title=dict(text=headline, subtitle=dict(text=(
            f"{len(closed)} closed paper positions from {closed['grade_date'].nunique()} grade days. Coloured bars: "
            "Wilson; grey bars: bootstrap of positions (light) and grade days (dark).<br>Black tick on the left: "
            "the hit rate with no skill (share of all names that rose for LONG, fell for SHORT). Dots jittered."))),
        height=500, margin=dict(t=150, b=140),
        legend=dict(orientation="h", x=0, xanchor="left", yref="container", y=0.01, yanchor="bottom"))
    fig.show()

    twin = outcomes[["closed", "hits", "hit_rate", "hit_rate_lo95", "hit_rate_hi95", "share_rose",
                     "median_return_pct"]].join(
        sure[["grade_days", "hit_lo95_positions", "hit_hi95_positions", "hit_lo95_by_day", "hit_hi95_by_day",
              "hit_widening"]])
    twin.insert(5, "no_skill_hit_rate", pd.Series(no_skill).reindex(twin.index))
    rate_cols = ["hit_rate", "hit_rate_lo95", "hit_rate_hi95", "no_skill_hit_rate", "share_rose",
                 "hit_lo95_positions", "hit_hi95_positions", "hit_lo95_by_day", "hit_hi95_by_day"]
    display(twin.style.format({**{c: "{:.0%}" for c in rate_cols}, "median_return_pct": "{:+.2f}%",
                               "hit_widening": "×{:.2f}"}, na_rep="–"))

    if len(sides_present) == 2:
        hi_side = outcomes.loc[sides_present, "hit_rate"].idxmax()
        lo_side = [s for s in sides_present if s != hi_side][0]
        gap = (f"Hit rates: {hi_side} {outcomes.loc[hi_side, 'hit_rate']:.0%} vs {lo_side} "
               f"{outcomes.loc[lo_side, 'hit_rate']:.0%}; ")
        if fisher_p < 0.05 and apart:
            gap += (f"Fisher {p_text(fisher_p)} and the by-day intervals do not overlap, so the gap is unlikely to "
                    "be chance alone.")
        elif fisher_p < 0.05:
            gap += (f"Fisher {p_text(fisher_p)}, but allowing for same-day clustering the sides' intervals overlap, "
                    "so the data cannot separate them with confidence.")
        else:
            gap += f"the gap could easily be chance (Fisher {p_text(fisher_p)})."
        print(gap + " But this compares sides with opposite market exposure, so it is not a test of the grade.")
        print(f"Share of names that rose: LONG {outcomes.loc['LONG', 'share_rose']:.0%} vs SHORT "
              f"{outcomes.loc['SHORT', 'share_rose']:.0%} (Fisher {p_text(fisher_rose_p)}). This is the version "
              "that tests the grade: with no skill, the two shares are equal.")

    per_position = (closed[["side", "ticker", "grade_date", "exit_date", "holding_days", "realized_return_pct",
                            "raw_move_pct", "hit"]].sort_values(["side", "realized_return_pct"]))
    per_position_html = (per_position.style
                         .format({"grade_date": "{:%Y-%m-%d}", "exit_date": "{:%Y-%m-%d}", "holding_days": "{:.0f}",
                                  "realized_return_pct": "{:+.2f}%", "raw_move_pct": "{:+.2f}%"}, escape="html")
                         .hide(axis="index").to_html())
    display(HTML(f"<details><summary>Show all {len(per_position)} closed positions (the dots in the right panel)"
                 f"</summary>{per_position_html}</details>"))

# %% [markdown]
# **How to read this.** On the left, each dot is a side's hit rate and the bars
# around it are the ranges of plausible true rates. If the two sides' bars
# overlap a lot, the data cannot tell the sides apart. Then compare each dot with
# its black tick, the hit rate that the market's direction alone would give: a dot
# near its tick means the grade added little beyond the market's direction.
# On the right, each dot is one closed position. Look at the spread, not just the
# median: a handful of large wins or losses can move a mean far from the typical
# position. The table under the chart repeats the left panel's numbers, and the
# collapsed table under it lists every position behind the right panel.
#
# **Caveats, with the sample size in mind.**
#
# - The positions come from a limited number of grade days (printed in the
#   subtitle and the table). That number, not the number of positions, is closer
#   to the number of independent observations. Compare the two grey bars before
#   you trust any interval.
# - The same ticker can appear several times (graded again on a later day), and
#   positions from *different* grade days often exit on the same day. The by-day
#   bootstrap does not cover that second link, so even the dark grey bars are, if
#   anything, too narrow.
# - A Fisher p-value above 0.05 means "we cannot tell", not "the sides are the
#   same". A small p-value still assumes independent positions, and a small
#   p-value on the hit rates is no evidence of skill at all, because the two sides
#   have opposite market exposure.
# - The book shows at most `limit` recent rows (up to 200). Older positions are
#   not included, and the window you see may not represent other periods or
#   market conditions.
# - This is a record of paper research. Past paper outcomes do not predict future
#   ones, and none of this is a recommendation to trade.

# %% [markdown]
# ### The decisions gate table
#
# `decisions` lists the latest grade date's actionable grades: every name graded
# above 70 or below 30. For each one the book records six gates and whether the
# name qualifies to open a position:
#
# | Gate | Passes when | Blocks an opening? |
# |---|---|---|
# | G1 strict grade | the grade is strictly above 70 (LONG) or strictly below 30 (SHORT) | yes |
# | G2 six reviews | all six seats filed a promoted review (`agents_reviewed` = `agents_expected`) | yes |
# | G3 rationale | the six rationales meet the content contract (the expected personas and evidence) | no: warn-only when `g3_warn_only` is true |
# | G4 review fresh | the council's `review_date` is on or after the `freshness_floor` | yes |
# | G5 zone current | the grade day has its own Drop Out Zone and the observed price is not below it | yes |
# | G6 no risk veto | no active risk veto (recorded from council v3_0, 2026-09-04) | yes |
#
# Notice what the gates check. G2, G3, G4 and G6 are about the seats' reviews:
# are they complete, well-formed, fresh, and free of a risk veto? They can stop
# a position from opening. None of them changes `grade_score` or `side`.
#
# The `review` and `zone_check` columns show the evidence behind G4 and G5, so
# you can see *why* a gate failed, not just that it did.

# %%
def gate_mark(value) -> str:
    if value is None or (not isinstance(value, bool) and pd.isna(value)):
        return "– n/a"
    return "✓ pass" if value else "✗ fail"


def zone_check(g: dict, grade_date: str) -> str:
    """Spell out the G5 evidence: is there a zone for the grade day, and is the observed price above it?"""
    zone, observed, zone_date = g["drop_out_zone"], g["drop_out_observed_price"], g["drop_out_zone_date"]
    if zone is None or observed is None:
        return "no zone or no observed price"
    if zone_date != grade_date:
        return f"latest zone is from {zone_date}, not the grade day"
    return f"observed {observed:,.2f} {'below' if observed < zone else 'at or above'} zone {zone:,.2f}"


dec = pd.DataFrame([{
    "ticker": str(d["ticker"]), "side": d["side"], "grade_date": d["grade_date"], "grade_score": d["grade_score"],
    **{name: d["gates"].get(key) if key == "g6_no_active_risk_veto" else d["gates"][key]
       for key, name in GATES.items()},                               # g6 only exists from council v3_0
    "g3_warn_only": d["gates"]["g3_warn_only"],
    "reviews": f"{d['gates']['agents_reviewed']}/{d['gates']['agents_expected']}",
    "review": f"{d['gates']['review_date']} (floor {d['gates']['freshness_floor']})",
    "review_date": d["gates"]["review_date"], "review_checkpoint": d["gates"]["review_checkpoint"],
    "zone_check": zone_check(d["gates"], d["grade_date"]), "qualifies": d["qualifies"],
    "reject_reasons": "; ".join(d["reject_reasons"]) or "none", "built_at": d["built_at"],
} for d in decisions_raw], columns=["ticker", "side", "grade_date", "grade_score", *GATES.values(), "g3_warn_only",
                                   "reviews", "review", "review_date", "review_checkpoint", "zone_check",
                                   "qualifies", "reject_reasons", "built_at"])
dec = dec.drop_duplicates(subset=["ticker", "grade_date"], keep="first")
dec["grade_score"] = pd.to_numeric(dec["grade_score"], errors="coerce")
dec["built_at"] = pd.to_datetime(dec["built_at"], utc=True)

if not BOOK_AVAILABLE:
    display(Markdown("> Grade book unavailable right now; gate table skipped."))
elif dec.empty:
    display(Markdown("> No opener decisions for the latest grade date. No name graded above 70 or below 30, "
                     "or the book has not been built yet today."))
else:
    built = dec["built_at"].max()
    grade_day = pd.Timestamp(dec["grade_date"].max())
    print(f"Decisions built {built:%Y-%m-%d %H:%M} UTC ({age_text(built)}), grade date {grade_day:%Y-%m-%d}.")
    review_day = pd.to_datetime(dec["review_date"], format="%Y-%m-%d").max()   # null when never reviewed
    print(f"The newest council review behind them is from {review_day:%Y-%m-%d}, "
          f"{(grade_day - review_day).days} days before the grade date." if pd.notna(review_day) else
          "No council review is recorded behind these decisions.")
    rule_ok = (dec["side"] == dec["grade_score"].map(grade_side)).all()
    print(f"Side follows the rule for every decision, qualifying or not: {rule_ok}.")

    # Our reading of the gates: every blocking gate must pass; G3 blocks only when it is not warn-only.
    g6 = dec[GATES["g6_no_active_risk_veto"]].map(lambda v: True if v is None or pd.isna(v) else bool(v))
    predicted = (dec[[GATES[k] for k in ("g1_strict_grade", "g2_six_promoted_reviews", "g4_review_fresh",
                                          "g5_drop_out_zone_current")]].astype(bool).all(axis=1)
                 & g6.astype(bool) & (dec[GATES["g3_rationale_contract"]].astype(bool) | dec["g3_warn_only"]))
    n_ok = int(dec["qualifies"].sum())
    print(f"Our gate reading reproduces `qualifies` for {int((predicted == dec['qualifies']).sum())} of {len(dec)} "
          f"decisions. {n_ok} of {len(dec)} qualif{'ies' if n_ok == 1 else 'y'} to open.")
    failing = {name: int(dec[name].eq(False).sum()) for name in [*blocking, GATES["g6_no_active_risk_veto"]]}
    print("Decisions failing each blocking gate:", failing)
    opened = set(book.loc[is_open, "ticker"])
    qualifying = set(dec.loc[dec["qualifies"], "ticker"])
    missing = sorted(qualifying - opened)
    print("No decision qualified, so no new position opens from this grade date." if not qualifying
          else "Every qualifying decision appears as an open position." if not missing
          else f"Qualifying but not (yet) open in the book: {missing}.")
    if not book.empty and book["grade_date"].max() < grade_day:
        print(f"No position has opened since {book['grade_date'].max():%Y-%m-%d}, the newest grade date in the book.")

    view = dec[["ticker", "side", "grade_score", *GATES.values(), "reviews", "review", "zone_check", "qualifies",
                "reject_reasons"]].copy()
    for col in GATES.values():
        view[col] = view[col].map(gate_mark)
    view["qualifies"] = view["qualifies"].map({True: "✓ opens", False: "✗ held back"})

    def gate_style(v) -> str:
        if isinstance(v, str) and v.startswith("✗"):                  # the glyph carries "fail"; no side colour
            return f"color: {INK}; font-weight: 700"
        return f"color: {MUTED}" if isinstance(v, str) and v.startswith("–") else ""

    styled = (view.style
              .map(gate_style, subset=[*GATES.values(), "qualifies"])
              .map(lambda v: f"color: {SIDE_COLORS[v]}; font-weight: 600", subset=["side"])
              .format({"grade_score": "{:.1f}"}, escape="html")
              .set_properties(subset=["reject_reasons", "zone_check"], **{"white-space": "normal", "max-width": "320px"})
              .hide(axis="index"))
    display(styled)

# %% [markdown]
# **How to read this.** Read each row left to right. The side and grade come first;
# the check printed above confirms that the side matches the rule. Then come the
# six gates. A bold ✗ in a blocking gate is enough to hold a name back, and
# `reject_reasons` says why in words. A ✗ in G3 alone does not block while G3 is
# warn-only. The `review` column compares the council's review date with the
# freshness floor (G4); when the council has not met for weeks, every grade fails
# here. The `zone_check` column explains G5: either the grade day has no zone of
# its own yet, or the price was below it. A name that is held back today is not
# lost for good: once the reviews are completed and refreshed, a later grade date
# can open it.
#
# **Caveats.**
#
# - The decisions cover one grade date only. They are not capped by `limit`.
# - "Qualifies" means "opens a paper position". It is not a buy or sell signal.
# - Gate names and rules are versioned (`council_contract_version` in the gate
#   record). Gates written under an older contract have no G6.
#
# **Recompute the gates yourself.** Each gate record stores the evidence next to
# the verdict: review counts, dates, the zone and the observed price. If our
# reading of the table above is right, we can rebuild G1, G2, G4 and G5 from that
# evidence alone, for the positions' entry-day gates and for the latest decisions.
# Any disagreement would mean our reading is wrong, or the rules changed.

# %%
GATE_RULES = {
    "g1_strict_grade": ("G1", "rule side of grade_score equals the gate's side, and it is not HOLD",
                        lambda g, score, day: grade_side(score) == g["side"] and g["side"] in SIDE_SIGN),
    "g2_six_promoted_reviews": ("G2", "agents_reviewed >= agents_expected",
                                lambda g, score, day: g["agents_reviewed"] >= g["agents_expected"]),
    "g4_review_fresh": ("G4", "review_date >= freshness_floor (ISO dates compare as text)",
                        lambda g, score, day: (g["review_date"] is not None and g["freshness_floor"] is not None
                                               and g["review_date"] >= g["freshness_floor"])),
    "g5_drop_out_zone_current": ("G5", "zone dated on the grade day, and observed price >= zone",
                                 lambda g, score, day: (g["drop_out_zone"] is not None
                                                        and g["drop_out_observed_price"] is not None
                                                        and g["drop_out_zone_date"] == day
                                                        and g["drop_out_observed_price"] >= g["drop_out_zone"])),
}
gate_sources = {"positions (entry-day gates)": [(r["gates"], r["grade_score"], r["grade_date"]) for r in rows_raw],
                "latest decisions": [(d["gates"], d["grade_score"], d["grade_date"]) for d in decisions_raw]}
recheck = []
for key, (short, rule, derive) in GATE_RULES.items():
    row = {"gate": short, "our rule": rule}
    for label, items in gate_sources.items():
        agree = sum(bool(derive(g, score, day)) == bool(g[key]) for g, score, day in items)
        row[label] = f"{agree} of {len(items)} agree" if items else "no rows"
    recheck.append(row)
display(pd.DataFrame(recheck).style.format(escape="html").hide(axis="index"))

# %% [markdown]
# When every cell reads "N of N agree", the published gates are exactly the
# simple rules in the second column: no hidden judgement sits inside them. G3 and
# G6 are left out because their evidence (the rationale text and the risk desk's
# veto) is not fully published.

# %% [markdown]
# ## 6. Extension: joining the scoreboard and the book
#
# *This section goes beyond the raw API.* The two endpoints describe the same
# council from two sides, and they share the `ticker` key. Joining them tests
# whether the story holds together.
#
# ### 6.1 Same name, two numbers: composite and grade
#
# The scoreboard shows a `composite_score`; the book's rule reads `grade_score`.
# For the latest decisions we can put the two side by side. Keep two things apart:
#
# - **What the data confirm.** The book's side is the rule applied to
#   `grade_score`, never to the composite, so where the two numbers fall in
#   different zones, the side follows the grade. That is true by construction:
#   section 5 already checked it for every position and decision.
# - **What the data cannot show.** Whether the seats influence `grade_score`
#   itself cannot be tested from these fields, because the book publishes the
#   grade but not how it was computed. For that part we rely on SurgeFlow's
#   published disclaimer (printed with the grade book). A large gap between the
#   two numbers is not evidence either way, especially when they come from
#   different days: the gap then mixes the passage of time with the difference
#   in method.
#
# So the cell first prints how many days separate the scoreboard's session from
# the decisions' `grade_date`.

# %%
if dec.empty or board.empty:
    print("Need both the latest decisions and a scoreboard to compare.")
else:
    both = dec[["ticker", "side", "grade_score", "qualifies"]].merge(
        board[["ticker", "composite_score", "rule_side", "flag"]], on="ticker", how="left")
    both["gap"] = both["composite_score"] - both["grade_score"]
    on_board = both.dropna(subset=["composite_score"])
    session_day = pd.to_datetime(meta["decision_session_date"], format="%Y-%m-%d")
    graded_day = pd.to_datetime(dec["grade_date"], format="%Y-%m-%d").max()
    day_gap = (graded_day - session_day).days
    print(f"Scoreboard session {session_day:%Y-%m-%d}; decisions graded {graded_day:%Y-%m-%d}: "
          f"{day_gap} day(s) apart.")
    reviews = sorted({c for c in dec["review_checkpoint"] if isinstance(c, str) and c})   # skip nulls
    same_meeting = meta["checkpoint_id"] in reviews
    meeting_text = "the same meeting the scoreboard shows" if same_meeting else "a different meeting"
    print(f"The decisions rest on council review {', '.join(reviews)}: {meeting_text}." if reviews else
          "The decisions record no council review.")
    if on_board.empty:
        print("None of the decision names is on the scoreboard.")
    else:
        print(f"{len(on_board)} of {len(both)} decision names are on the scoreboard. The composite and the grade "
              f"agree on the side for {int((on_board['side'] == on_board['rule_side']).sum())} of them; "
              f"largest gap {on_board['gap'].abs().max():.1f} points.")
        if abs(day_gap) > STALE_DAYS:
            print(f"The two numbers are {abs(day_gap)} days apart (more than STALE_DAYS = {STALE_DAYS}), so the gap "
                  "mixes time with method. We draw no conclusion from its size.")
        disagree = on_board[on_board["side"] != on_board["rule_side"]]
        if len(disagree):
            print(f"Where the zones differ ({', '.join(disagree['ticker'])}), the book's side follows the grade. "
                  "That is the rule at work (checked in section 5), not a test of whether the seats influence "
                  "the grade.")
    display(both.rename(columns={"side": "side_from_grade", "rule_side": "side_from_composite",
                                 "flag": "scoreboard_flag"})
            .style.format({"grade_score": "{:.2f}", "composite_score": "{:.2f}", "gap": "{:+.2f}"}, na_rep="–")
            .hide(axis="index"))

# %% [markdown]
# ### 6.2 Two paper records: the scoreboard ledger and the grade book
#
# It is tempting to assume that the scoreboard's paper flags *are* the grade
# book's positions. They are not the same record:
#
# | | Scoreboard ledger (`ai/ratings`) | Grade book (`ai/grade-book`) |
# |---|---|---|
# | What sets the side | the scoreboard's own pick (`long` / `short`) | the grade rule, > 70 / < 30 |
# | Score it uses | `composite_score` | `grade_score` |
# | Exit | hard stop on the return since the anchor close | the Drop Out Zone only |
# | Gates | none published | six gates, checked before an opening |
#
# The reconciliation table below lines the two up, name by name, together with
# the latest decisions.

# %%
ledger_legs = board[board["flag"] != "not flagged"].set_index("ticker")
open_side = book[is_open].drop_duplicates("ticker").set_index("ticker")["side"]
dec_by_name = dec.set_index("ticker") if not dec.empty else pd.DataFrame(columns=["side", "grade_score", "qualifies"])
names = sorted(set(ledger_legs.index) | set(open_side.index) | set(dec_by_name.index))
if not names:
    print("No scoreboard paper legs, open positions or decisions to reconcile.")
else:
    recon = pd.DataFrame({"ticker": names})
    recon["scoreboard_ledger"] = recon["ticker"].map(
        lambda t: f"{ledger_legs.loc[t, 'flag']} ({ledger_legs.loc[t, 'stop_state']})" if t in ledger_legs.index else "–")
    recon["open_in_grade_book"] = recon["ticker"].map(lambda t: open_side.get(t, "–"))
    recon["latest_decision"] = recon["ticker"].map(
        lambda t: (f"{dec_by_name.loc[t, 'side']} at {dec_by_name.loc[t, 'grade_score']:.0f}, "
                   f"{'opens' if dec_by_name.loc[t, 'qualifies'] else 'held back'}") if t in dec_by_name.index else "–")
    working = set(ledger_legs.index[ledger_legs["stop_state"] != "stopped_out"])
    print(f"Scoreboard ledger: {len(ledger_legs)} paper legs ({len(working)} still working). "
          f"Grade book: {len(open_side)} open positions. In both: {sorted(working & set(open_side.index)) or 'none'}.")
    display(recon.style.format(escape="html").hide(axis="index"))

# %% [markdown]
# **How to read this.** Each row is a name that appears in at least one of the
# three lists. A dash means the name is absent from that list. When a name is a
# working leg in the scoreboard ledger but not open in the grade book, the two
# records simply disagree about it: for example, the ledger took a short while
# the book's gates held the grade back, or the book never graded it past a line.
# Neither record is "wrong"; they answer different questions. Quote the grade
# book when you mean the deterministic rule.

# %% [markdown]
# ### 6.3 How fragile is each scoreboard composite?
#
# Section 4 found which seats the published composite averages
# (`COMPOSITE_SEATS`). Now ask a "what if" question: **if one of those seats had
# not reported, would the composite land in a different zone?** For each name we
# drop each seat in turn, recompute the mean of the others, and apply the rule. A
# name whose zone flips when a single seat is removed rests on that one seat's
# score. If that score is a blank zero (0 with no comment), the name may rest on a
# review that was never filed rather than on an opinion. The published composite
# averages blank zeros like any other score, so the table keeps them; the line
# under the table re-runs the check with them set to missing and lists what changes.
#
# This is about the scoreboard's composite only. The book's grade is a separate
# number, and nothing here changes it. We use no machine learning in this notebook
# on purpose: a hotlist's worth of names and the book's closed positions are far
# too few to fit a model honestly. Descriptive checks like this one are the right
# tool.

# %%
def fragility_table(scores: pd.DataFrame) -> pd.DataFrame:
    """Leave-one-seat-out check on the composite seats, one row per name with at least 3 scoring seats."""
    out = []
    for ticker, row in scores.reindex(columns=COMPOSITE_SEATS).iterrows():
        scored = row.dropna()
        if len(scored) < 3:
            continue
        loo = (scored.sum() - scored) / (len(scored) - 1)             # mean without each seat in turn
        full = scored.mean()                                          # reproduces the published composite
        zone = grade_side(full)
        flips = loo[loo.map(grade_side) != zone]
        margin = min(abs(full - LONG_ABOVE), abs(full - SHORT_BELOW))
        out.append({"ticker": ticker, "seat_mean": full, "zone": zone, "seats": len(scored),
                    "points_to_nearest_line": margin, "loo_min": loo.min(), "loo_max": loo.max(),
                    "seats_that_flip_it": ", ".join(f"{s} ({grade_side(v)})" for s, v in flips.items()) or "none"})
    return pd.DataFrame(out, columns=["ticker", "seat_mean", "zone", "seats", "points_to_nearest_line",
                                      "loo_min", "loo_max", "seats_that_flip_it"])


fragility = fragility_table(wide)
if fragility.empty:
    print("Not enough seat scores for a leave-one-seat-out check.")
else:
    print(f"Composite reading used: mean of {', '.join(COMPOSITE_SEATS)}.")
    fragile = fragility[fragility["seats_that_flip_it"] != "none"]
    print(f"{len(fragile)} of {len(fragility)} names would change zone if one seat were left out"
          + (f": {', '.join(fragile['ticker'])}." if len(fragile) else "."))
    display(fragility.sort_values("points_to_nearest_line")
            .style.format({"seat_mean": "{:.1f}", "points_to_nearest_line": "{:.1f}", "loo_min": "{:.1f}",
                           "loo_max": "{:.1f}"})
            .map(lambda v: "font-weight: 600" if v != "none" else f"color: {MUTED}", subset=["seats_that_flip_it"])
            .hide(axis="index"))

    # Sensitivity: the same check with the blank zeros (score 0, no comment) set to missing.
    n_blank_comp = int(zero_no_comment.reindex(columns=COMPOSITE_SEATS).sum().sum())
    if n_blank_comp == 0:
        print("No blank zeros among the composite seats, so the zones do not depend on them.")
    else:
        alt = fragility_table(wide_without_blank_zeros)
        compare = fragility[["ticker", "zone", "seat_mean"]].merge(
            alt[["ticker", "zone", "seat_mean"]], on="ticker", how="left", suffixes=("", "_alt"))
        unchecked = compare[compare["zone_alt"].isna()]                # fewer than 3 seats left without them
        changed = compare[compare["zone_alt"].notna() & (compare["zone"] != compare["zone_alt"])]
        moves = [f"{r.ticker} {r.zone} -> {r.zone_alt} (mean {r.seat_mean:.1f} -> {r.seat_mean_alt:.1f})"
                 for r in changed.itertuples()]
        print(f"Sensitivity: with the {n_blank_comp} blank zero(s) set to missing, {len(changed)} of "
              f"{len(compare) - len(unchecked)} names change zone" + (": " + "; ".join(moves) + "." if moves else "."))
        if len(unchecked):
            print(f"Without them, {', '.join(unchecked['ticker'])} keep(s) fewer than 3 scoring seats and cannot be "
                  "checked: the zone rests on placeholder-like scores.")

# %% [markdown]
# **How to read this.** The table is sorted by distance to the nearest line (30 or
# 70), closest first. `seat_mean` is the composite rebuilt from its seats, and
# `loo_min` and `loo_max` show the range of averages you get by leaving out one
# seat at a time ("loo" = leave one out). When that range crosses a line, the last
# column names the seat whose absence would move the name into another zone, and
# which zone. Names near a line with a wide range are the council's close calls.
# Names far from both lines are robust to any single seat. The sensitivity line
# under the table lists the names whose zone depends on a blank zero: for those,
# check whether the seat really reviewed the name before you read the zone as the
# council's view.

# %% [markdown]
# ## Next steps
#
# - Run the scoreboard again with `CHECKPOINT = "morning"`, `"midday"` and
#   `"close"` to see how the council's view moves during a session.
# - Keep `BOOK_LIMIT = 200` and save the closed positions every week. The
#   by-day intervals narrow only as new grade days accumulate.
# - Ask whether more extreme grades did better: plot each closed position's
#   grade against its raw price move (so the market's direction cannot pass for
#   skill), and resample grade days for the interval.
# - Join the scoreboard to the hotlist and screen boards from notebook 01 on
#   `ticker`, and look at what the high-scoring names have in common.
# - Read the seats' comments for the names that section 6.3 flags as fragile, and
#   decide for yourself which seat has the stronger case.
#
# ---
#
# *Research and education only. The AI ratings and the grade book are paper
# research records: no orders are placed and nothing here is investment advice.
# The `realtime` endpoint elsewhere in this kit names a current-session board, not
# a live-tick feed, and update cadence varies by market. Check each checkpoint's
# time and the book's `built_at` before you rely on any number.*

# %%
print(f"API requests made in this session: {api_calls_used()}")
