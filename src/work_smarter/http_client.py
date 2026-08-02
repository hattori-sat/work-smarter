"""Typed loopback HTTP client used by canonical CLI adapters."""

from __future__ import annotations

from typing import TypeVar
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ValidationError

from work_smarter.api import (
    HealthResponse,
    OperationRecoveryResponse,
    OperationResponse,
    OutboxEnqueueRequest,
    OutboxResponse,
)
from work_smarter.errors import WorkSmarterError
from work_smarter.shared.outbox import OutboxRunReport


class RemoteApiError(WorkSmarterError):
    """Stable client error returned by the local application server."""


ModelT = TypeVar("ModelT", bound=BaseModel)


def validate_loopback_server(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise RemoteApiError("Server URL must use http on a loopback host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RemoteApiError("Server URL must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise RemoteApiError("Server URL must not contain an application path")
    return value.strip().rstrip("/")


class WorkSmarterHttpClient:
    """Small typed client; domain CLI commands never parse ad-hoc response dictionaries."""

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = validate_loopback_server(base_url)
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=10,
            trust_env=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WorkSmarterHttpClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: object) -> object:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise RemoteApiError(f"Local server request failed: {exc}") from exc
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except (ValueError, AttributeError):
                detail = response.text
            raise RemoteApiError(f"Local server returned {response.status_code}: {detail}")
        try:
            return response.json()
        except ValueError as exc:
            raise RemoteApiError("Local server returned invalid JSON") from exc

    @staticmethod
    def _decode(model: type[ModelT], payload: object) -> ModelT:
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise RemoteApiError(f"Local server response violated {model.__name__}") from exc

    def _decode_list(self, model: type[ModelT], payload: object) -> list[ModelT]:
        if not isinstance(payload, list):
            raise RemoteApiError("Local server response must be a JSON list")
        return [self._decode(model, item) for item in payload]

    def health(self) -> HealthResponse:
        return self._decode(HealthResponse, self._request("GET", "/health"))

    def list_operations(self, *, limit: int = 100) -> list[OperationResponse]:
        payload = self._request("GET", "/api/system/operations", params={"limit": limit})
        return self._decode_list(OperationResponse, payload)

    def get_operation(self, operation_id: str) -> OperationResponse:
        payload = self._request("GET", f"/api/system/operations/{operation_id}")
        return self._decode(OperationResponse, payload)

    def recover_operations(self) -> OperationRecoveryResponse:
        payload = self._request("POST", "/api/system/operations/recover")
        return self._decode(OperationRecoveryResponse, payload)

    def list_outbox(self, *, limit: int = 100) -> list[OutboxResponse]:
        payload = self._request("GET", "/api/system/outbox", params={"limit": limit})
        return self._decode_list(OutboxResponse, payload)

    def enqueue_outbox(self, request: OutboxEnqueueRequest) -> OutboxResponse:
        payload = self._request(
            "POST",
            "/api/system/outbox",
            json=request.model_dump(mode="json", exclude_none=True),
        )
        return self._decode(OutboxResponse, payload)

    def run_outbox(self, *, limit: int = 25) -> OutboxRunReport:
        payload = self._request("POST", "/api/system/outbox/run", json={"limit": limit})
        return self._decode(OutboxRunReport, payload)


__all__ = ["RemoteApiError", "WorkSmarterHttpClient", "validate_loopback_server"]
