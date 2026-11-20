from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Optional, Union

import requests

from ._errors import (
    SurgeFlowApiError,
    SurgeFlowConnectionError,
    SurgeFlowResponseError,
    SurgeFlowTimeoutError,
)
from ._fixtures import fixture_enabled, read_fixture
from ._member import MemberMethods

JsonObject = Dict[str, Any]
SnapshotResult = Union[JsonObject, str]
Params = Dict[str, Union[str, int, bool]]


class SurgeFlow(MemberMethods):
    MARKETS = ("us", "cn", "jp", "hk")
    SNAPSHOTS = (
        "momentum-hotlist",
        "macro-indicators",
        "news-sentiment",
        "factor-overview",
        "data-freshness",
    )

    def __init__(
        self,
        base_url: str = "https://surgeflows.capital",
        timeout: float = 30.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = session or requests.Session()

    def catalog(self) -> JsonObject:
        result = self._request("/api/v1/catalog")
        if isinstance(result, str):
            raise SurgeFlowResponseError("Expected a JSON response")
        return result

    def public_snapshot(
        self,
        snapshot_id: str,
        *,
        market: Optional[str] = None,
        days: Optional[int] = None,
        response_format: str = "json",
    ) -> SnapshotResult:
        if snapshot_id not in self.SNAPSHOTS:
            raise ValueError(f"Unknown snapshot: {snapshot_id}")
        params: Params = {}
        if market is not None:
            self._validate_market(market)
            params["market"] = market
        if days is not None:
            self._validate_days(days)
            params["days"] = days
        return self._request(
            f"/api/public/snapshots/{snapshot_id}.{response_format}",
            params=params,
            response_format=response_format,
        )

    def momentum_hotlist(
        self, market: str, response_format: str = "json"
    ) -> SnapshotResult:
        self._validate_market(market)
        return self.public_snapshot(
            "momentum-hotlist", market=market, response_format=response_format
        )

    def macro_indicators(self, response_format: str = "json") -> SnapshotResult:
        return self.public_snapshot(
            "macro-indicators", response_format=response_format
        )

    def news_sentiment(
        self, days: int = 30, response_format: str = "json"
    ) -> SnapshotResult:
        self._validate_days(days)
        return self.public_snapshot(
            "news-sentiment", days=days, response_format=response_format
        )

    def factor_overview(
        self, market: str, response_format: str = "json"
    ) -> SnapshotResult:
        self._validate_market(market)
        return self.public_snapshot(
            "factor-overview", market=market, response_format=response_format
        )

    def data_freshness(self, response_format: str = "json") -> SnapshotResult:
        return self.public_snapshot(
            "data-freshness", response_format=response_format
        )

    def member_me(self, api_key: str) -> JsonObject:
        return self._member_get("/api/v1/me", api_key)

    def member_hotlist(
        self, market: str, api_key: str, limit: Optional[int] = None
    ) -> JsonObject:
        self._validate_market(market)
        params: Params = {}
        if limit is not None:
            self._validate_range("limit", limit, 1, 1000)
            params["limit"] = limit
        return self._member_get(
            f"/api/v1/markets/{market}/hotlist", api_key, params
        )

    def _request(
        self,
        path: str,
        *,
        api_key: Optional[str] = None,
        params: Optional[Params] = None,
        response_format: str = "json",
    ) -> SnapshotResult:
        if response_format not in ("json", "csv"):
            raise ValueError("response_format must be json or csv")
        request_params = {
            key: value for key, value in (params or {}).items() if value is not None
        }
        headers = {
            "Accept": "application/json" if response_format == "json" else "text/csv",
            "User-Agent": "surgeflow-python/0.1.0",
        }
        if api_key is not None:
            if not isinstance(api_key, str) or not api_key.strip():
                raise ValueError("api_key must be a non-empty string")
            headers["Authorization"] = f"Bearer {api_key}"
        if fixture_enabled():
            return read_fixture(path, request_params, response_format)
        try:
            response = self._session.request(
                "GET",
                f"{self.base_url}{path}",
                headers=headers,
                params=request_params,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise SurgeFlowTimeoutError("The SurgeFlow request timed out") from exc
        except requests.RequestException as exc:
            raise SurgeFlowConnectionError("The SurgeFlow request failed") from exc

        if not 200 <= response.status_code < 300:
            error_payload: Optional[JsonObject] = None
            try:
                candidate = response.json()
                if isinstance(candidate, dict):
                    error_payload = candidate
            except ValueError:
                pass
            message = f"SurgeFlow returned HTTP {response.status_code}"
            if error_payload:
                detail = error_payload.get("error") or error_payload.get("message")
                if isinstance(detail, dict):
                    detail = detail.get("message") or detail.get("code")
                if isinstance(detail, str):
                    message = detail
            response_headers = getattr(response, "headers", {})
            retry_after = self._retry_after(response_headers.get("Retry-After"))
            raise SurgeFlowApiError(
                response.status_code, message, error_payload, retry_after
            )

        if response_format == "csv":
            return response.text
        try:
            payload = response.json()
        except ValueError as exc:
            raise SurgeFlowResponseError("SurgeFlow returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise SurgeFlowResponseError("SurgeFlow returned a non-object JSON response")
        if payload.get("ok") is False:
            raise SurgeFlowResponseError("The SurgeFlow response contains ok=false")
        return payload

    @staticmethod
    def _retry_after(value: Optional[str]) -> Optional[float]:
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                target = parsedate_to_datetime(value)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                return max(
                    0.0, (target - datetime.now(timezone.utc)).total_seconds()
                )
            except (TypeError, ValueError):
                return None

    def _validate_market(self, market: str) -> None:
        if market not in self.MARKETS:
            raise ValueError("market must be us, cn, jp, or hk")

    @staticmethod
    def _validate_days(days: int) -> None:
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
            raise ValueError("days must be an integer from 1 through 365")
