from typing import Any, Dict, Optional, Union

from ._errors import NotAvailableYet, SurgeFlowResponseError

JsonObject = Dict[str, Any]
Params = Dict[str, Union[str, int, bool]]


class MemberMethods:
    @staticmethod
    def _validate_us_only(market: str) -> None:
        # The macro vote routes declare market pattern ^us$.
        if market != "us":
            raise ValueError("market must be us for the macro vote routes")

    def _member_get(
        self, path: str, api_key: str, params: Optional[Params] = None
    ) -> JsonObject:
        result = self._request(path, api_key=api_key, params=params)
        if isinstance(result, str):
            raise SurgeFlowResponseError("Expected a JSON response")
        return result

    def member_macro_model_votes(
        self, api_key: str, market: str = "us"
    ) -> JsonObject:
        self._validate_us_only(market)
        return self._member_get(
            "/api/macro/model-votes", api_key, {"market": market}
        )

    def member_macro_index_votes(
        self, api_key: str, market: str = "us", horizon: int = 21
    ) -> JsonObject:
        self._validate_us_only(market)
        if horizon not in (1, 21):
            raise ValueError("horizon must be 1 or 21")
        return self._member_get(
            "/api/macro/index-votes",
            api_key,
            {"market": market, "horizon": horizon},
        )

    def member_macro_cycle_composites(
        self, api_key: str, version: str = "v2"
    ) -> JsonObject:
        self._validate_version(version)
        return self._member_get(
            "/api/macro/cycle-composites", api_key, {"version": version}
        )

    def member_macro_recession_probability(
        self, api_key: str, version: str = "v2"
    ) -> JsonObject:
        self._validate_version(version)
        return self._member_get(
            "/api/macro/recession-probability", api_key, {"version": version}
        )

    def member_fund_hmm_regime(self, api_key: str) -> JsonObject:
        return self._member_get("/api/fund/hmm-regime", api_key)

    def member_sentiment_scores(
        self,
        market: str,
        api_key: str,
        *,
        ticker: Optional[str] = None,
        limit: int = 50,
        min_dimensions: int = 2,
        direction: str = "desc",
        basis: str = "news_led",
    ) -> JsonObject:
        self._validate_market(market)
        self._validate_range("limit", limit, 1, 200)
        self._validate_range("min_dimensions", min_dimensions, 0, 4)
        if direction not in ("asc", "desc"):
            raise ValueError("direction must be asc or desc")
        if basis not in ("legacy", "news_led"):
            raise ValueError("basis must be legacy or news_led")
        params: Params = {
            "limit": limit,
            "min_dimensions": min_dimensions,
            "direction": direction,
            "basis": basis,
        }
        if ticker is not None:
            if not ticker.strip():
                raise ValueError("ticker must be non-empty")
            params["ticker"] = ticker.strip()
        return self._member_get(f"/api/{market}/stock-scores", api_key, params)

    def member_sentiment_whale_picks(
        self, market: str, api_key: str, limit: int = 5
    ) -> JsonObject:
        self._validate_market(market)
        self._validate_range("limit", limit, 1, 50)
        return self._member_get(
            f"/api/{market}/sentiment-whale-picks", api_key, {"limit": limit}
        )

    def member_technical_cohorts(self, api_key: str) -> JsonObject:
        raise NotAvailableYet(
            "Technical cohorts are not available with a member key yet. "
            "The live route uses a website cookie; use only the public factor context."
        )

    def member_weekly_pure_books(self, api_key: str) -> JsonObject:
        return self._member_get("/api/us/weekly-pure-books", api_key)

    def member_historical_pure_books(self, api_key: str) -> JsonObject:
        return self._member_get("/api/us/historical-pure-books", api_key)

    def member_three_model_portfolios(
        self,
        api_key: str,
        market: str = "us",
        *,
        factor: Optional[str] = None,
        formation_date: Optional[str] = None,
        weeks: int = 52,
        holdings: int = 25,
        measurement: bool = True,
    ) -> JsonObject:
        self._validate_market(market)
        self._validate_range("weeks", weeks, 1, 1000)
        self._validate_range("holdings", holdings, 0, 5000)
        if not isinstance(measurement, bool):
            raise ValueError("measurement must be boolean")
        params: Params = {
            "weeks": weeks,
            "holdings": holdings,
            "measurement": measurement,
        }
        if factor is not None:
            if not factor.strip() or len(factor) > 20:
                raise ValueError("factor must contain 1 through 20 characters")
            params["factor"] = factor.strip().upper()
        if formation_date is not None:
            if len(formation_date) != 10:
                raise ValueError("formation_date must use YYYY-MM-DD")
            params["formation_date"] = formation_date
        return self._member_get(
            f"/api/{market}/three-model/portfolios", api_key, params
        )

    def member_fundamental_picks(
        self, api_key: str, industry: Optional[str] = None
    ) -> JsonObject:
        params: Params = {}
        if industry is not None:
            if not industry.strip() or len(industry) > 200:
                raise ValueError("industry must contain 1 through 200 characters")
            params["industry"] = industry.strip()
        return self._member_get("/api/us/fundamental-picks", api_key, params)

    def member_fundamental_peers(
        self, api_key: str, ticker: str, group: str = "industry"
    ) -> JsonObject:
        if not isinstance(ticker, str) or not 1 <= len(ticker.strip()) <= 20:
            raise ValueError("ticker must contain 1 through 20 characters")
        if group not in ("industry", "sector"):
            raise ValueError("group must be industry or sector")
        return self._member_get(
            "/api/us/fundamental-peers",
            api_key,
            {"ticker": ticker.strip(), "group": group},
        )

    def member_watchlists(self, api_key: str) -> JsonObject:
        return self._member_get("/api/watchlists", api_key)

    def member_screens(self, api_key: str) -> JsonObject:
        return self._member_get("/api/screens", api_key)

    def member_alerts(self, api_key: str) -> JsonObject:
        return self._member_get("/api/alerts", api_key)

    def member_portfolio(self, api_key: str) -> JsonObject:
        return self._member_get("/api/portfolio", api_key)

    def member_realtime(
        self, market: str, api_key: str, limit: int = 50
    ) -> JsonObject:
        self._validate_market(market)
        self._validate_range("limit", limit, 1, 100)
        return self._member_get(
            f"/api/v1/markets/{market}/realtime", api_key, {"limit": limit}
        )

    def member_daily_insights(self, api_key: str) -> JsonObject:
        return self._member_get("/api/us/daily-insights", api_key)

    def member_layoffs(self, api_key: str) -> JsonObject:
        raise NotAvailableYet(
            "Layoffs are not available with a member key yet. "
            "No stock-api route exists, so this notebook shows no layoffs data."
        )

    @staticmethod
    def _validate_version(version: str) -> None:
        if version not in ("v1", "v2"):
            raise ValueError("version must be v1 or v2")

    @staticmethod
    def _validate_range(name: str, value: int, minimum: int, maximum: int) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not minimum <= value <= maximum
        ):
            raise ValueError(
                f"{name} must be an integer from {minimum} through {maximum}"
            )
