import httpx
import pytest

from app.sources.minfin.client import (
    MinfinAccessBlockedError,
    MinfinClient,
    MinfinHTTPError,
    MinfinNotFoundError,
    normalize_url,
)


def test_minfin_normalizes_www_host() -> None:
    assert normalize_url("https://www.mof.gov.ua/uk/crs-578") == "https://mof.gov.ua/uk/crs-578"


async def test_minfin_client_raises_access_blocked_on_403() -> None:
    client = MinfinClient(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(403, request=request))
        ),
        retries=0,
        min_delay=0,
    )

    with pytest.raises(MinfinAccessBlockedError) as exc:
        await client.get_text("https://mof.gov.ua/uk/crs-578")
    assert exc.value.access_classification == "ACCESS_BLOCKED"


async def test_minfin_client_raises_not_found_on_404() -> None:
    client = MinfinClient(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(404, request=request))
        ),
        retries=0,
        min_delay=0,
    )

    with pytest.raises(MinfinNotFoundError):
        await client.get_text("https://mof.gov.ua/uk/missing")


async def test_minfin_client_raises_transient_error_on_429() -> None:
    client = MinfinClient(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(429, request=request))
        ),
        retries=0,
        min_delay=0,
    )

    with pytest.raises(MinfinHTTPError):
        await client.get_text("https://mof.gov.ua/uk/crs-578")
