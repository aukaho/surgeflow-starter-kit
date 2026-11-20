import json
import socket
from pathlib import Path

import pytest
import requests

from surgeflow import (
    SurgeFlow,
    SurgeFlowApiError,
    SurgeFlowConnectionError,
    SurgeFlowResponseError,
    SurgeFlowTimeoutError,
)

FIXTURES = Path(__file__).parent / "fixtures"
KEY = "sf_live_REPLACE_WITH_YOUR_KEY"


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Network access is disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket.socket, "connect_ex", fail)


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    @property
    def text(self):
        return self.body

    def json(self):
        return json.loads(self.body)


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def fixture_text(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_momentum_hotlist_uses_recorded_fixture_and_user_agent():
    body = fixture_text("momentum-hotlist-us.json")
    session = FakeSession(FakeResponse(body))
    client = SurgeFlow(session=session)

    result = client.momentum_hotlist("us")

    assert result == json.loads(body)
    call = session.calls[0]
    assert call["method"] == "GET"
    assert call["url"].endswith("/api/public/snapshots/momentum-hotlist.json")
    assert call["params"] == {"market": "us"}
    assert call["timeout"] == 30
    assert call["headers"] == {
        "Accept": "application/json",
        "User-Agent": "surgeflow-python/0.1.0",
    }


def test_csv_snapshot_returns_recorded_text():
    body = fixture_text("momentum-hotlist-us.csv")
    session = FakeSession(FakeResponse(body))
    client = SurgeFlow(session=session)

    result = client.momentum_hotlist("us", response_format="csv")

    assert result == body
    assert session.calls[0]["url"].endswith("/momentum-hotlist.csv")
    assert session.calls[0]["headers"]["Accept"] == "text/csv"


@pytest.mark.parametrize(
    "method,args,path,params",
    [
        ("macro_indicators", (), "/api/public/snapshots/macro-indicators.json", {}),
        ("news_sentiment", (30,), "/api/public/snapshots/news-sentiment.json", {"days": 30}),
        ("factor_overview", ("jp",), "/api/public/snapshots/factor-overview.json", {"market": "jp"}),
        ("data_freshness", (), "/api/public/snapshots/data-freshness.json", {}),
    ],
)
def test_public_snapshot_methods(method, args, path, params):
    body = fixture_text("data-freshness.json")
    session = FakeSession(FakeResponse(body))
    client = SurgeFlow(session=session)

    result = getattr(client, method)(*args)

    assert result["ok"] is True
    assert session.calls[0]["url"].endswith(path)
    assert session.calls[0]["params"] == params


def test_member_me_sends_bearer_key():
    session = FakeSession(FakeResponse('{"ok":true,"data":{}}'))
    client = SurgeFlow(session=session)

    assert client.member_me(KEY)["ok"] is True
    call = session.calls[0]
    assert call["url"].endswith("/api/v1/me")
    assert call["headers"]["Authorization"] == f"Bearer {KEY}"


def test_member_hotlist_validates_market_and_sends_key():
    session = FakeSession(FakeResponse(fixture_text("momentum-hotlist-us.json")))
    client = SurgeFlow(session=session)

    result = client.member_hotlist("hk", KEY)

    assert result["data"]["rows"]
    call = session.calls[0]
    assert call["url"].endswith("/api/v1/markets/hk/hotlist")
    assert call["headers"]["Authorization"] == f"Bearer {KEY}"


@pytest.mark.parametrize("market", ["xx", "US", "", None])
def test_invalid_market_fails_before_a_request(market):
    session = FakeSession()
    client = SurgeFlow(session=session)

    with pytest.raises(ValueError):
        client.momentum_hotlist(market)
    assert session.calls == []


@pytest.mark.parametrize("days", [0, 366, True, 1.5])
def test_invalid_days_fail_before_a_request(days):
    session = FakeSession()
    client = SurgeFlow(session=session)

    with pytest.raises(ValueError):
        client.news_sentiment(days)
    assert session.calls == []


def test_unknown_snapshot_and_format_fail_before_a_request():
    session = FakeSession()
    client = SurgeFlow(session=session)

    with pytest.raises(ValueError):
        client.public_snapshot("unknown")
    with pytest.raises(ValueError):
        client.data_freshness(response_format="xml")
    assert session.calls == []


def test_http_error_has_typed_status_and_payload():
    session = FakeSession(FakeResponse('{"error":"Invalid key"}', 401))
    client = SurgeFlow(session=session)

    with pytest.raises(SurgeFlowApiError) as caught:
        client.member_me(KEY)

    assert caught.value.status_code == 401
    assert caught.value.payload == {"error": "Invalid key"}
    assert str(caught.value) == "Invalid key"


def test_timeout_has_a_typed_error():
    session = FakeSession(requests.Timeout("slow"))
    client = SurgeFlow(session=session)

    with pytest.raises(SurgeFlowTimeoutError):
        client.data_freshness()


def test_connection_failure_has_a_typed_error():
    session = FakeSession(requests.ConnectionError("offline"))
    client = SurgeFlow(session=session)

    with pytest.raises(SurgeFlowConnectionError):
        client.data_freshness()


def test_invalid_json_has_a_typed_error():
    session = FakeSession(FakeResponse("not-json"))
    client = SurgeFlow(session=session)

    with pytest.raises(SurgeFlowResponseError):
        client.data_freshness()


def test_ok_false_has_a_typed_error():
    session = FakeSession(FakeResponse('{"ok":false}'))
    client = SurgeFlow(session=session)

    with pytest.raises(SurgeFlowResponseError):
        client.data_freshness()
