import json

import pytest

from surgeflow import NotAvailableYet, SurgeFlow, SurgeFlowApiError

KEY = "sf_live_REPLACE_WITH_YOUR_KEY"
BASE = "https://stock-api-c4qdowjxva-uc.a.run.app"


class FakeResponse:
    def __init__(self, body='{"synthetic":true,"ok":true}', status_code=200, headers=None):
        self.body = body
        self.status_code = status_code
        self.headers = headers or {}

    @property
    def text(self):
        return self.body

    def json(self):
        return json.loads(self.body)


class FakeSession:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response


def member_call(client, method):
    calls = {
        "macro_model": lambda: client.member_macro_model_votes(KEY),
        "macro_index": lambda: client.member_macro_index_votes(KEY, horizon=1),
        "cycle": lambda: client.member_macro_cycle_composites(KEY),
        "recession": lambda: client.member_macro_recession_probability(KEY, version="v1"),
        "hmm": lambda: client.member_fund_hmm_regime(KEY),
        "scores": lambda: client.member_sentiment_scores(
            "us", KEY, ticker="SYNTH", limit=10, min_dimensions=2,
            direction="desc", basis="news_led"
        ),
        "whale": lambda: client.member_sentiment_whale_picks("us", KEY, limit=5),
        "weekly": lambda: client.member_weekly_pure_books(KEY),
        "historical": lambda: client.member_historical_pure_books(KEY),
        "three_model": lambda: client.member_three_model_portfolios(
            KEY, factor="value", formation_date="2026-11-16", weeks=4,
            holdings=10, measurement=False
        ),
        "picks": lambda: client.member_fundamental_picks(KEY),
        "peers": lambda: client.member_fundamental_peers(KEY, "SYNTH", group="sector"),
        "watchlists": lambda: client.member_watchlists(KEY),
        "screens": lambda: client.member_screens(KEY),
        "alerts": lambda: client.member_alerts(KEY),
        "portfolio": lambda: client.member_fund_portfolio_summary(KEY),
        "hotlist": lambda: client.member_hotlist("us", KEY, limit=100),
        "realtime": lambda: client.member_realtime("us", KEY, limit=25),
        "insights": lambda: client.member_daily_insights(KEY),
    }
    return calls[method]()


@pytest.mark.parametrize(
    "method,path,params",
    [
        ("macro_model", "/api/macro/model-votes", {"market": "us"}),
        ("macro_index", "/api/macro/index-votes", {"market": "us", "horizon": 1}),
        ("cycle", "/api/macro/cycle-composites", {"version": "v2"}),
        ("recession", "/api/macro/recession-probability", {"version": "v1"}),
        ("hmm", "/api/fund/hmm-regime", {}),
        ("scores", "/api/us/stock-scores", {
            "ticker": "SYNTH", "limit": 10, "min_dimensions": 2,
            "direction": "desc", "basis": "news_led"
        }),
        ("whale", "/api/us/sentiment-whale-picks", {"limit": 5}),
        ("weekly", "/api/us/weekly-pure-books", {}),
        ("historical", "/api/us/historical-pure-books", {}),
        ("three_model", "/api/us/three-model/portfolios", {
            "factor": "VALUE", "formation_date": "2026-11-16", "weeks": 4,
            "holdings": 10, "measurement": False
        }),
        ("picks", "/api/us/fundamental-picks", {}),
        ("peers", "/api/us/fundamental-peers", {"ticker": "SYNTH", "group": "sector"}),
        ("watchlists", "/api/watchlists", {}),
        ("screens", "/api/screens", {}),
        ("alerts", "/api/alerts", {}),
        ("portfolio", "/api/fund/portfolio-summary", {}),
        ("hotlist", "/api/v1/markets/us/hotlist", {"limit": 100}),
        ("realtime", "/api/v1/markets/us/realtime", {"limit": 25}),
        ("insights", "/api/us/daily-insights", {}),
    ],
)
def test_member_method_url_header_and_params(method, path, params):
    session = FakeSession()
    client = SurgeFlow(base_url=BASE, session=session)

    assert member_call(client, method)["synthetic"] is True

    call = session.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == BASE + path
    assert call["params"] == params
    assert call["headers"]["Authorization"] == f"Bearer {KEY}"
    assert "apiKey" not in call["params"] and "api_key" not in call["params"]
    assert KEY not in call["url"]


@pytest.mark.parametrize("method", ["member_technical_cohorts", "member_layoffs"])
def test_unavailable_offerings_raise_clear_typed_error(method):
    session = FakeSession()
    client = SurgeFlow(session=session)

    with pytest.raises(NotAvailableYet, match="not available with a member key yet"):
        getattr(client, method)(KEY)
    assert session.calls == []


def test_fixture_mode_reads_local_file_without_session(monkeypatch):
    session = FakeSession()
    client = SurgeFlow(session=session)
    monkeypatch.setenv("SURGEFLOW_FIXTURES", "1")

    payload = client.member_me(KEY)

    assert payload["synthetic"] is True
    assert payload["plan"] == "free"
    assert session.calls == []


def test_retry_after_is_typed_on_429():
    response = FakeResponse(
        '{"error":{"message":"Slow down"}}', status_code=429,
        headers={"Retry-After": "42"}
    )
    client = SurgeFlow(session=FakeSession(response))

    with pytest.raises(SurgeFlowApiError) as caught:
        client.member_me(KEY)

    assert caught.value.status_code == 429
    assert caught.value.retry_after == 42
    assert str(caught.value) == "Slow down"


@pytest.mark.parametrize("market", ["us", "cn", "jp", "hk"])
def test_all_four_market_paths_preserve_market_and_header(market):
    session = FakeSession()
    client = SurgeFlow(base_url=BASE, session=session)

    client.member_sentiment_scores(market, KEY)
    client.member_sentiment_whale_picks(market, KEY)
    client.member_three_model_portfolios(KEY, market=market)
    client.member_hotlist(market, KEY)
    client.member_realtime(market, KEY)

    assert [call["url"] for call in session.calls] == [
        f"{BASE}/api/{market}/stock-scores",
        f"{BASE}/api/{market}/sentiment-whale-picks",
        f"{BASE}/api/{market}/three-model/portfolios",
        f"{BASE}/api/v1/markets/{market}/hotlist",
        f"{BASE}/api/v1/markets/{market}/realtime",
    ]
    for call in session.calls:
        assert call["headers"]["Authorization"] == f"Bearer {KEY}"
        assert KEY not in call["url"]


@pytest.mark.parametrize("market", ["cn", "jp", "hk"])
def test_macro_vote_methods_reject_non_us_market_before_request(market):
    session = FakeSession()
    client = SurgeFlow(base_url=BASE, session=session)

    with pytest.raises(ValueError):
        client.member_macro_model_votes(KEY, market=market)
    with pytest.raises(ValueError):
        client.member_macro_index_votes(KEY, market=market)
    assert session.calls == []


def test_user_agent_matches_package_version():
    import surgeflow

    session = FakeSession()
    SurgeFlow(base_url=BASE, session=session).member_watchlists(KEY)
    assert session.calls[0]["headers"]["User-Agent"] == f"surgeflow-python/{surgeflow.__version__}"
