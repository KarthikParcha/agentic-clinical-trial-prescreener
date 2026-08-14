import asyncio
from collections.abc import Awaitable, Callable

import httpx
import pytest

from clinical_trial_prescreener.config import ClinicalTrialsSettings
from clinical_trial_prescreener.infrastructure.clinicaltrials.client import (
    ClinicalTrialsClient,
)
from clinical_trial_prescreener.infrastructure.clinicaltrials.exceptions import (
    ClinicalTrialsClientError,
)


def run(coroutine: Awaitable[object]) -> object:
    return asyncio.run(coroutine)


async def with_client(
    handler: Callable[[httpx.Request], httpx.Response],
    operation: Callable[[ClinicalTrialsClient], Awaitable[object]],
) -> object:
    client = ClinicalTrialsClient(transport=httpx.MockTransport(handler))
    try:
        return await operation(client)
    finally:
        await client.aclose()


def test_successful_response_sends_condition_and_page_size_parameters() -> None:
    received_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal received_request
        received_request = request
        return httpx.Response(200, json={"studies": [{"id": "study-1"}]})

    async def operation(client: ClinicalTrialsClient) -> object:
        return await client.search_studies(
            "Type 2 Diabetes", page_size=25, query_term="AREA[StudyType]INTERVENTIONAL"
        )

    result = run(with_client(handler, operation))

    assert result == {"studies": [{"id": "study-1"}]}
    assert received_request is not None
    assert received_request.url.path == "/api/v2/studies"
    assert received_request.url.params["query.cond"] == "Type 2 Diabetes"
    assert received_request.url.params["pageSize"] == "25"
    assert received_request.url.params["query.term"] == "AREA[StudyType]INTERVENTIONAL"
    assert "pageToken" not in received_request.url.params


def test_page_token_parameter_is_sent_when_supplied() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["pageToken"] == "next-page-token"
        return httpx.Response(200, json={"studies": []})

    async def operation(client: ClinicalTrialsClient) -> object:
        return await client.search_studies("Type 2 Diabetes", page_token="next-page-token")

    assert run(with_client(handler, operation)) == {"studies": []}


def test_empty_studies_response_succeeds() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"studies": []})

    async def operation(client: ClinicalTrialsClient) -> object:
        return await client.search_studies("Type 2 Diabetes")

    assert run(with_client(handler, operation)) == {"studies": []}


@pytest.mark.parametrize("condition", ["", "   "])
def test_blank_condition_is_rejected(condition: str) -> None:
    client = ClinicalTrialsClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    try:
        with pytest.raises(ValueError, match="condition must not be blank"):
            run(client.search_studies(condition))
    finally:
        run(client.aclose())


@pytest.mark.parametrize("page_size", [0, -1, 1001])
def test_invalid_page_size_is_rejected(page_size: int) -> None:
    client = ClinicalTrialsClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    try:
        with pytest.raises(ValueError, match="page_size must be between 1 and 1000"):
            run(client.search_studies("Type 2 Diabetes", page_size=page_size))
    finally:
        run(client.aclose())


def test_http_error_is_converted_to_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    async def operation(client: ClinicalTrialsClient) -> object:
        with pytest.raises(ClinicalTrialsClientError, match="HTTP 503"):
            await client.search_studies("Type 2 Diabetes")
        return None

    run(with_client(handler, operation))


def test_transport_error_is_converted_to_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    async def operation(client: ClinicalTrialsClient) -> object:
        with pytest.raises(ClinicalTrialsClientError, match="request failed"):
            await client.search_studies("Type 2 Diabetes")
        return None

    run(with_client(handler, operation))


def test_invalid_json_is_converted_to_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json", request=request)

    async def operation(client: ClinicalTrialsClient) -> object:
        with pytest.raises(ClinicalTrialsClientError, match="invalid JSON"):
            await client.search_studies("Type 2 Diabetes")
        return None

    run(with_client(handler, operation))


def test_base_url_and_timeout_are_configurable() -> None:
    settings = ClinicalTrialsSettings(
        base_url="https://example.test/api",
        timeout_seconds=2.5,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://example.test/api/studies")
        return httpx.Response(200, json={"studies": []})

    async def operation(client: ClinicalTrialsClient) -> object:
        return await client.search_studies("Type 2 Diabetes")

    async def configured_operation() -> object:
        client = ClinicalTrialsClient(
            settings=settings,
            transport=httpx.MockTransport(handler),
        )
        try:
            return await operation(client)
        finally:
            await client.aclose()

    assert run(configured_operation()) == {"studies": []}
