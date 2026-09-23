import httpx
import pytest

from app.sources.dps.client import DpsAccessDeniedError, DpsClient, DpsHTTPError, DpsNotFoundError


async def test_dps_client_raises_access_denied_on_403() -> None:
    client = DpsClient(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(403, request=request))
        )
    )

    with pytest.raises(DpsAccessDeniedError):
        await client.get_text("https://tax.gov.ua/x")


async def test_dps_client_raises_not_found_on_404() -> None:
    client = DpsClient(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(404, request=request))
        )
    )

    with pytest.raises(DpsNotFoundError):
        await client.get_text("https://tax.gov.ua/x")


async def test_dps_client_raises_http_error_on_429() -> None:
    client = DpsClient(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(429, request=request))
        ),
        retries=0,
    )

    with pytest.raises(DpsHTTPError):
        await client.get_text("https://tax.gov.ua/x")
