import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class RadaHTTPError(RuntimeError):
    def __init__(self, status_code: int, url: str, message: str | None = None) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(message or f"Rada HTTP error {status_code} for {url}")


class RadaNotFoundError(RadaHTTPError):
    pass


class RadaAccessDeniedError(RadaHTTPError):
    pass


class RadaClient:
    def __init__(
        self,
        base_url: str = "https://data.rada.gov.ua",
        public_base_url: str = "https://zakon.rada.gov.ua",
        timeout: float = 20.0,
        retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.public_base_url = public_base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "RadaClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_card(self, nreg: str, revision_date: str | None = None) -> dict[str, Any]:
        suffix = f"/ed{revision_date}" if revision_date else ""
        return await self.get_json(f"/laws/card/{nreg}{suffix}.json")

    async def get_updated_documents(self) -> dict[str, Any]:
        return await self.get_json("/laws/main/r.json")

    async def get_document_html(self, nreg: str, revision_date: str | None = None) -> str:
        suffix = f"/ed{revision_date}" if revision_date else ""
        return await self.get_text(f"/laws/show/{nreg}{suffix}")

    async def get_print_html(self, nreg: str, revision_date: str | None = None) -> str:
        suffix = f"/ed{revision_date}" if revision_date else ""
        url = f"{self.public_base_url}/laws/show/{nreg}{suffix}/print"
        return await self._request_text("GET", url, self._browser_headers())

    async def get_json(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"User-Agent": "OpenData", "Accept": "application/json"}
        response = await self._request("GET", url, headers)
        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning("rada_invalid_json url=%s", url)
            raise ValueError(f"Invalid JSON from Rada endpoint {url}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected JSON payload from Rada endpoint {url}")
        return payload

    async def get_text(self, path: str) -> str:
        url = f"{self.base_url}{path}"
        response = await self._request("GET", url, {"User-Agent": "OpenData", "Accept": "text/html,*/*"})
        return response.text

    async def _request_text(self, method: str, url: str, headers: dict[str, str]) -> str:
        response = await self._request(method, url, headers)
        return response.text

    async def _request(self, method: str, url: str, headers: dict[str, str]) -> httpx.Response:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
            self._owns_client = True

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = await self._client.request(method, url, headers=headers)
                self._validate_response(response, url)
                return response
            except RadaHTTPError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                logger.warning("rada_transient_error url=%s attempt=%s error=%s", url, attempt + 1, exc)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("rada_http_error url=%s attempt=%s error=%s", url, attempt + 1, exc)

            if attempt < self.retries:
                await asyncio.sleep(0.3 * (attempt + 1))

        raise RuntimeError(f"Rada request failed for {url}: {last_error}") from last_error

    def _validate_response(self, response: httpx.Response, url: str) -> None:
        if response.status_code == 403:
            logger.warning("rada_access_denied url=%s user_agent=OpenData", url)
            raise RadaAccessDeniedError(403, url, "Rada access denied; verify exact User-Agent: OpenData")
        if response.status_code == 404:
            raise RadaNotFoundError(404, url, "Rada document or revision not found")
        if response.status_code == 429 or 500 <= response.status_code < 600:
            raise RadaHTTPError(response.status_code, url)
        response.raise_for_status()

    def _browser_headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
        }
