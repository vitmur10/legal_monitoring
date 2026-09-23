import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DpsHTTPError(RuntimeError):
    def __init__(self, status_code: int, url: str, message: str | None = None) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(message or f"DPS HTTP error {status_code} for {url}")


class DpsNotFoundError(DpsHTTPError):
    pass


class DpsAccessDeniedError(DpsHTTPError):
    pass


class DpsTransientHTTPError(DpsHTTPError):
    pass


class DpsClient:
    def __init__(
        self,
        timeout: float = 20.0,
        retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "DpsClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers=self._headers(),
            )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_text(self, url: str) -> str:
        response = await self._request("GET", url)
        return response.text

    async def post_more(
        self,
        section_url: str,
        page: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        data = {"more": "1", "page": str(page)}
        if date_from is not None:
            data["date_from"] = date_from
        if date_to is not None:
            data["date_to"] = date_to
        response = await self._request(
            "POST",
            section_url,
            data=data,
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json,*/*"},
        )
        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning("dps_invalid_json url=%s", section_url)
            raise ValueError(f"Invalid JSON from DPS endpoint {section_url}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected JSON payload from DPS endpoint {section_url}")
        return payload

    async def _request(
        self,
        method: str,
        url: str,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers=self._headers(),
            )
            self._owns_client = True

        request_headers = dict(headers or {})
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = await self._client.request(
                    method,
                    url,
                    data=data,
                    headers=request_headers,
                )
                self._validate_response(response, str(response.url))
                return response
            except (DpsAccessDeniedError, DpsNotFoundError):
                raise
            except DpsTransientHTTPError as exc:
                last_error = exc
                logger.warning(
                    "dps_transient_status url=%s attempt=%s status=%s",
                    url,
                    attempt + 1,
                    exc.status_code,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                logger.warning("dps_transient_error url=%s attempt=%s error=%s", url, attempt + 1, exc)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("dps_http_error url=%s attempt=%s error=%s", url, attempt + 1, exc)

            if attempt < self.retries:
                await asyncio.sleep(0.4 * (attempt + 1))

        if isinstance(last_error, DpsHTTPError):
            raise last_error
        raise RuntimeError(f"DPS request failed for {url}: {last_error}") from last_error

    def _validate_response(self, response: httpx.Response, url: str) -> None:
        if response.status_code == 403:
            logger.warning("dps_access_denied url=%s", url)
            raise DpsAccessDeniedError(403, url, "DPS access denied")
        if response.status_code == 404:
            raise DpsNotFoundError(404, url, "DPS document or section not found")
        if response.status_code == 429 or 500 <= response.status_code < 600:
            raise DpsTransientHTTPError(response.status_code, url)
        response.raise_for_status()

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36 legal-monitoring/0.1"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
        }
