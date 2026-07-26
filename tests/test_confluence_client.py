from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from work_smarter.confluence.client import (
    ConfluenceClient,
    ConfluenceConfig,
    HttpRequest,
    HttpResponse,
)
from work_smarter.confluence.errors import (
    ConfluenceAuthenticationError,
    ConfluenceConflictError,
    ConfluenceCredentialError,
    ConfluenceNotFoundError,
    ConfluenceRateLimitError,
    ConfluenceTransportError,
)


class FakeTransport:
    def __init__(self, *responses: HttpResponse | Exception):
        self.responses = list(responses)
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def response(
    status: int,
    payload: object,
    headers: Mapping[str, str] | None = None,
) -> HttpResponse:
    return HttpResponse(
        status_code=status,
        body=json.dumps(payload).encode(),
        headers=dict(headers or {}),
    )


def config() -> ConfluenceConfig:
    return ConfluenceConfig(
        base_url="https://example.atlassian.net/",
        email="engineer@example.com",
        api_token="never-print-this-token",
    )


def test_config_loads_namespaced_environment_and_never_reveals_token() -> None:
    loaded = ConfluenceConfig.from_environment(
        {
            "WORK_SMARTER_CONFLUENCE_BASE_URL": "https://example.atlassian.net/wiki",
            "WORK_SMARTER_CONFLUENCE_EMAIL": "engineer@example.com",
            "WORK_SMARTER_CONFLUENCE_API_TOKEN": "super-secret-token",
        }
    )

    assert loaded.base_url == "https://example.atlassian.net"
    assert loaded.email == "engineer@example.com"
    assert "super-secret-token" not in repr(loaded)
    assert "super-secret-token" not in str(loaded)

    with pytest.raises(ConfluenceCredentialError, match="missing"):
        ConfluenceConfig.from_environment({})
    with pytest.raises(ConfluenceCredentialError, match="HTTPS"):
        ConfluenceConfig(
            base_url="http://example.atlassian.net",
            email="engineer@example.com",
            api_token="secret",
        )


def test_client_resolves_space_reads_page_and_sends_basic_auth() -> None:
    transport = FakeTransport(
        response(
            200,
            {"results": [{"id": "42", "key": "ENG", "name": "Engineering"}]},
        ),
        response(
            200,
            {
                "id": "123",
                "title": "Runbook",
                "spaceId": "42",
                "parentId": "100",
                "version": {"number": 7},
                "body": {"storage": {"value": "<p>Body</p>"}},
            },
        ),
    )
    client = ConfluenceClient(config(), transport=transport)

    space = client.resolve_space("ENG")
    page = client.get_page("123")

    assert (space.id, space.key) == ("42", "ENG")
    assert (page.id, page.version, page.storage) == ("123", 7, "<p>Body</p>")
    assert transport.requests[0].url.endswith("/wiki/api/v2/spaces?keys=ENG&limit=2")
    assert transport.requests[1].url.endswith("/wiki/api/v2/pages/123?body-format=storage")
    authorization = transport.requests[0].headers["Authorization"]
    assert authorization.startswith("Basic ")
    assert "never-print-this-token" not in authorization
    assert transport.requests[0].headers["Accept"] == "application/json"


def test_client_creates_and_updates_storage_pages_with_explicit_next_version() -> None:
    transport = FakeTransport(
        response(
            201,
            {
                "id": "123",
                "title": "Plan",
                "spaceId": "42",
                "parentId": "100",
                "version": {"number": 1},
                "body": {"storage": {"value": "<h1>Plan</h1>"}},
            },
        ),
        response(
            200,
            {
                "id": "123",
                "title": "Plan v2",
                "spaceId": "42",
                "parentId": "100",
                "version": {"number": 8},
                "body": {"storage": {"value": "<h1>Plan v2</h1>"}},
            },
        ),
    )
    client = ConfluenceClient(config(), transport=transport)

    created = client.create_page(
        space_id="42",
        title="Plan",
        storage="<h1>Plan</h1>",
        parent_id="100",
    )
    updated = client.update_page(
        page_id=created.id,
        title="Plan v2",
        storage="<h1>Plan v2</h1>",
        current_version=7,
        parent_id="100",
    )

    create_request, update_request = transport.requests
    assert (create_request.method, create_request.url.rsplit("/", 1)[-1]) == ("POST", "pages")
    assert create_request.json_body == {
        "spaceId": "42",
        "status": "current",
        "title": "Plan",
        "parentId": "100",
        "body": {"representation": "storage", "value": "<h1>Plan</h1>"},
    }
    assert update_request.method == "PUT"
    assert update_request.json_body == {
        "id": "123",
        "status": "current",
        "title": "Plan v2",
        "parentId": "100",
        "body": {"representation": "storage", "value": "<h1>Plan v2</h1>"},
        "version": {"number": 8, "message": "Published by Work Smarter"},
    }
    assert updated.version == 8


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, ConfluenceAuthenticationError),
        (403, ConfluenceAuthenticationError),
        (404, ConfluenceNotFoundError),
        (409, ConfluenceConflictError),
        (412, ConfluenceConflictError),
        (429, ConfluenceRateLimitError),
    ],
)
def test_client_maps_remote_errors_without_leaking_credentials(
    status: int,
    error_type: type[Exception],
) -> None:
    transport = FakeTransport(
        response(status, {"message": "remote refused request"}, {"Retry-After": "17"})
    )
    client = ConfluenceClient(config(), transport=transport)

    with pytest.raises(error_type) as caught:
        client.get_page("123")

    assert "never-print-this-token" not in str(caught.value)
    if isinstance(caught.value, ConfluenceRateLimitError):
        assert caught.value.retry_after_seconds == 17


def test_client_rejects_invalid_ids_malformed_json_and_transport_failure() -> None:
    client = ConfluenceClient(config(), transport=FakeTransport())
    with pytest.raises(ValueError, match="numeric"):
        client.get_page("../outside")

    malformed = ConfluenceClient(
        config(),
        transport=FakeTransport(HttpResponse(status_code=200, body=b"not json", headers={})),
    )
    with pytest.raises(ConfluenceTransportError, match="invalid JSON"):
        malformed.get_page("123")

    failed = ConfluenceClient(config(), transport=FakeTransport(OSError("network down")))
    with pytest.raises(ConfluenceTransportError, match="network down"):
        failed.get_page("123")
