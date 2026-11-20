from typing import Any, Dict, Optional


class SurgeFlowError(Exception):
    pass


class SurgeFlowConnectionError(SurgeFlowError):
    pass


class SurgeFlowTimeoutError(SurgeFlowConnectionError):
    pass


class SurgeFlowResponseError(SurgeFlowError):
    pass


class SurgeFlowApiError(SurgeFlowError):
    def __init__(
        self,
        status_code: int,
        message: str,
        payload: Optional[Dict[str, Any]] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload
        self.retry_after = retry_after


class NotAvailableYet(SurgeFlowError):
    pass
