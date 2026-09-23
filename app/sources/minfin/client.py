from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse, urlunparse

import httpx

logger = logging.getLogger(__name__)


class MinfinSourceError(RuntimeError):
    pass


class MinfinHTTPError(MinfinSourceError):
    access_classification = "HTTP_ERROR"

    def __init__(self, status_code: int, url: str, message: str | None = None) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(message or f"Minfin HTTP error {status_code} for {url}")


class MinfinAccessBlockedError(MinfinHTTPError):
    access_classification = "ACCESS_BLOCKED"


class MinfinNotFoundError(MinfinHTTPError):
    access_classification = "NOT_FOUND"


class MinfinTransientHTTPError(MinfinHTTPError):
    access_classification = "TRANSIENT_FAILURE"


class MinfinClient:
    def __init__(
        self,
        timeout: float = 20.0,
        retries: int = 2,
        min_delay: float = 0.6,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.min_delay = min_delay
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "MinfinClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_text(self, url: str) -> str:
        response = await self._request("GET", normalize_url(url))
        return response.text

    async def _request(self, method: str, url: str) -> httpx.Response:
        await self._ensure_client()
        assert self._client is not None
        last_error: Exception | None = None

        for attempt in range(self.retries + 1):
            if self.min_delay:
                await asyncio.sleep(self.min_delay)
            try:
                response = await self._client.request(method, normalize_url(url))
                self._validate_response(response, str(response.url))
                return response
            except (MinfinAccessBlockedError, MinfinNotFoundError):
                raise
            except MinfinTransientHTTPError as exc:
                last_error = exc
                logger.warning(
                    "minfin_transient_status url=%s attempt=%s status=%s",
                    url,
                    attempt + 1,
                    exc.status_code,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                logger.warning("minfin_transient_error url=%s attempt=%s error=%s", url, attempt + 1, exc)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("minfin_http_error url=%s attempt=%s error=%s", url, attempt + 1, exc)

            if attempt < self.retries:
                await asyncio.sleep(0.8 * (attempt + 1))

        if isinstance(last_error, MinfinHTTPError):
            raise last_error
        raise RuntimeError(f"Minfin request failed for {url}: {last_error}") from last_error

    async def _ensure_client(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers=self._headers(),
            )
            self._owns_client = True

    def _validate_response(self, response: httpx.Response, url: str) -> None:
        if response.status_code == 403:
            raise MinfinAccessBlockedError(403, url, "Minfin access blocked")
        if response.status_code == 404:
            raise MinfinNotFoundError(404, url, "Minfin document or section not found")
        if response.status_code == 429 or 500 <= response.status_code < 600:
            raise MinfinTransientHTTPError(response.status_code, url)
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


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc or "mof.gov.ua"
    if netloc.lower() == "www.mof.gov.ua":
        netloc = "mof.gov.ua"
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path, "", parsed.query, parsed.fragment))
