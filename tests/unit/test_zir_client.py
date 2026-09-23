import httpx
import pytest

from app.sources.zir.client import ZirAccessDeniedError, ZirClient, ZirMalformedResponseError


async def test_zir_client_initializes_session_then_posts_with_xhr_headers() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, text="<html>search</html>", headers={"Set-Cookie": "PHPSESSID=abc"}, request=request)
        assert request.headers["X-Requested-With"] == "XMLHttpRequest"
        assert request.headers["Referer"].endswith("/main/bz/search/?src=ques&srch=bz")
        assert "application/x-www-form-urlencoded" in request.headers["Content-Type"]
        return httpx.Response(
            200,
            text='<?xml version="1.0" encoding="UTF-8"?><body><count>0</count><content></content></body>',
            request=request,
        )

    client = ZirClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    await client.search_consultations(cat_id="1")

    assert [call.method for call in calls] == ["GET", "POST"]


async def test_zir_client_rejects_malformed_200_error_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text="<html>search</html>", request=request)
        return httpx.Response(
            200,
            text="<!DOCTYPE html><html><head><title>Помилка</title></head><body>bad</body></html>",
            request=request,
        )

    client = ZirClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), retries=0)

    with pytest.raises(ZirMalformedResponseError):
        await client.search_consultations(cat_id="1")


async def test_zir_client_raises_access_denied_on_403() -> None:
    client = ZirClient(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(403, request=request))
        ),
        retries=0,
    )

    with pytest.raises(ZirAccessDeniedError):
        await client.initialize_session()
