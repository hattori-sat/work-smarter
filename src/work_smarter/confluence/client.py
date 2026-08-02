"""Small injectable client for the documented Confluence Cloud REST v2 surface."""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
)

from work_smarter.confluence.errors import (
    ConfluenceAuthenticationError,
    ConfluenceConflictError,
    ConfluenceCredentialError,
    ConfluenceNotFoundError,
    ConfluenceRateLimitError,
    ConfluenceTransportError,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfluenceConfig(StrictModel):
    base_url: str
    email: str
    api_token: SecretStr
    timeout_seconds: float = Field(default=15.0, gt=0, le=120)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        cleaned = value.strip().rstrip("/")
        if cleaned.endswith("/wiki"):
            cleaned = cleaned[: -len("/wiki")]
        parsed = urlparse(cleaned)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ConfluenceCredentialError("Confluence base URL must use HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfluenceCredentialError("Confluence base URL cannot contain credentials/query")
        if parsed.path not in {"", "/"}:
            raise ConfluenceCredentialError("Confluence base URL must be the Cloud site root")
        return cleaned.rstrip("/")

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or "@" not in cleaned:
            raise ConfluenceCredentialError("Confluence account email is missing or invalid")
        return cleaned

    @field_validator("api_token")
    @classmethod
    def validate_token(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ConfluenceCredentialError("Confluence API token is missing")
        return value

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> ConfluenceConfig:
        values = os.environ if environment is None else environment
        names = {
            "base_url": "WORK_SMARTER_CONFLUENCE_BASE_URL",
            "email": "WORK_SMARTER_CONFLUENCE_EMAIL",
            "api_token": "WORK_SMARTER_CONFLUENCE_API_TOKEN",
        }
        missing = [env_name for env_name in names.values() if not values.get(env_name, "").strip()]
        if missing:
            raise ConfluenceCredentialError(
                "Confluence credentials are missing: " + ", ".join(missing)
            )
        return cls(**{field: values[env_name] for field, env_name in names.items()})


class HttpRequest(StrictModel):
    method: str
    url: str
    headers: dict[str, str]
    json_body: dict[str, Any] | None = None
    timeout_seconds: float


class HttpResponse(StrictModel):
    status_code: int
    body: bytes
    headers: dict[str, str]


class HttpTransport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse: ...


class UrllibTransport:
    """Production transport with no dependency beyond the standard library."""

    def send(self, request: HttpRequest) -> HttpResponse:
        data = (
            json.dumps(request.json_body, ensure_ascii=False).encode("utf-8")
            if request.json_body is not None
            else None
        )
        raw_request = Request(
            request.url,
            data=data,
            headers=request.headers,
            method=request.method,
        )
        try:
            with urlopen(raw_request, timeout=request.timeout_seconds) as response:  # noqa: S310
                return HttpResponse(
                    status_code=response.status,
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except HTTPError as exc:
            return HttpResponse(
                status_code=exc.code,
                body=exc.read(),
                headers=dict(exc.headers.items()) if exc.headers else {},
            )
        except URLError as exc:
            raise OSError(str(exc.reason)) from exc


class ConfluenceSpace(StrictModel):
    id: str
    key: str
    name: str | None = None


class ConfluencePage(StrictModel):
    id: str
    title: str
    space_id: str
    parent_id: str | None = None
    version: int = Field(ge=1)
    storage: str


def _numeric_id(value: str, *, name: str) -> str:
    cleaned = value.strip()
    if not cleaned.isdecimal():
        raise ValueError(f"Confluence {name} must be numeric")
    return cleaned


class ConfluenceClient:
    def __init__(
        self,
        config: ConfluenceConfig,
        *,
        transport: HttpTransport | None = None,
    ):
        self.config = config
        self.transport = transport or UrllibTransport()

    @property
    def _authorization(self) -> str:
        credential = f"{self.config.email}:{self.config.api_token.get_secret_value()}".encode()
        return "Basic " + base64.b64encode(credential).decode("ascii")

    def _url(self, path: str, query: Mapping[str, str] | None = None) -> str:
        suffix = f"?{urlencode(query)}" if query else ""
        return f"{self.config.base_url}/wiki/api/v2/{path.lstrip('/')}{suffix}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        expected: set[int] = frozenset({200}),
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "Authorization": self._authorization,
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = HttpRequest(
            method=method,
            url=self._url(path, query),
            headers=headers,
            json_body=payload,
            timeout_seconds=self.config.timeout_seconds,
        )
        try:
            response = self.transport.send(request)
        except Exception as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise ConfluenceTransportError(f"Confluence request failed: {exc}") from exc

        if response.status_code not in expected:
            self._raise_remote_error(response)
        try:
            decoded = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfluenceTransportError("Confluence returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise ConfluenceTransportError("Confluence returned a non-object JSON response")
        return decoded

    @staticmethod
    def _raise_remote_error(response: HttpResponse) -> None:
        message = f"Confluence returned HTTP {response.status_code}"
        try:
            decoded = json.loads(response.body.decode("utf-8"))
            if isinstance(decoded, dict) and isinstance(decoded.get("message"), str):
                message += f": {decoded['message']}"
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        if response.status_code in {401, 403}:
            raise ConfluenceAuthenticationError(message)
        if response.status_code == 404:
            raise ConfluenceNotFoundError(message)
        if response.status_code in {409, 412}:
            raise ConfluenceConflictError(message)
        if response.status_code == 429:
            raw_retry = next(
                (value for key, value in response.headers.items() if key.lower() == "retry-after"),
                None,
            )
            retry = int(raw_retry) if raw_retry and raw_retry.isdecimal() else None
            raise ConfluenceRateLimitError(message, retry_after_seconds=retry)
        raise ConfluenceTransportError(message)

    @staticmethod
    def _page(payload: Mapping[str, Any]) -> ConfluencePage:
        try:
            body = payload.get("body") or {}
            storage = body.get("storage") or {}
            version = payload.get("version") or {}
            return ConfluencePage(
                id=str(payload["id"]),
                title=str(payload["title"]),
                space_id=str(payload["spaceId"]),
                parent_id=str(payload["parentId"]) if payload.get("parentId") else None,
                version=int(version["number"]),
                storage=str(storage.get("value", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfluenceTransportError("Confluence returned an invalid page payload") from exc

    def resolve_space(self, space_key: str) -> ConfluenceSpace:
        key = space_key.strip()
        if not key:
            raise ValueError("Confluence space key cannot be blank")
        payload = self._request(
            "GET",
            "spaces",
            query={"keys": key, "limit": "2"},
        )
        results = payload.get("results")
        if not isinstance(results, list):
            raise ConfluenceTransportError("Confluence returned an invalid space payload")
        matches = [
            item for item in results if str(item.get("key", "")).casefold() == key.casefold()
        ]
        if not matches:
            raise ConfluenceNotFoundError(f"Confluence space {key!r} does not exist")
        if len(matches) > 1:
            raise ConfluenceConflictError(f"Confluence space key {key!r} is not unique")
        item = matches[0]
        try:
            return ConfluenceSpace(
                id=str(item["id"]),
                key=str(item["key"]),
                name=str(item["name"]) if item.get("name") else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfluenceTransportError("Confluence returned an invalid space payload") from exc

    def get_page(self, page_id: str) -> ConfluencePage:
        page = _numeric_id(page_id, name="page ID")
        payload = self._request(
            "GET",
            f"pages/{page}",
            query={"body-format": "storage"},
        )
        return self._page(payload)

    def create_page(
        self,
        *,
        space_id: str,
        title: str,
        storage: str,
        parent_id: str | None = None,
    ) -> ConfluencePage:
        payload: dict[str, Any] = {
            "spaceId": _numeric_id(space_id, name="space ID"),
            "status": "current",
            "title": title.strip(),
            "body": {"representation": "storage", "value": storage},
        }
        if not payload["title"]:
            raise ValueError("Confluence page title cannot be blank")
        if parent_id is not None:
            payload["parentId"] = _numeric_id(parent_id, name="parent ID")
        result = self._request("POST", "pages", payload=payload, expected={200, 201})
        return self._page(result)

    def update_page(
        self,
        *,
        page_id: str,
        title: str,
        storage: str,
        current_version: int,
        parent_id: str | None = None,
        message: str = "Published by Work Smarter",
    ) -> ConfluencePage:
        page = _numeric_id(page_id, name="page ID")
        if current_version < 1:
            raise ValueError("Confluence current version must be positive")
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Confluence page title cannot be blank")
        payload: dict[str, Any] = {
            "id": page,
            "status": "current",
            "title": clean_title,
            "body": {"representation": "storage", "value": storage},
            "version": {"number": current_version + 1, "message": message.strip()},
        }
        if parent_id is not None:
            payload["parentId"] = _numeric_id(parent_id, name="parent ID")
        result = self._request("PUT", f"pages/{page}", payload=payload)
        return self._page(result)


__all__ = [
    "ConfluenceClient",
    "ConfluenceConfig",
    "ConfluencePage",
    "ConfluenceSpace",
    "HttpRequest",
    "HttpResponse",
    "HttpTransport",
    "UrllibTransport",
]
