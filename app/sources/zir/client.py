from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.core.http import system_ssl_context
from app.sources.zir.parser import BASE_URL, validate_ajax_xml

logger = logging.getLogger(__name__)


class ZirSourceError(RuntimeError):
    pass


class ZirHTTPError(ZirSourceError):
    def __init__(self, status_code: int, url: str, message: str | None = None) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(message or f"ZIR HTTP error {status_code} for {url}")


class ZirNotFoundError(ZirHTTPError):
    pass


class ZirAccessDeniedError(ZirHTTPError):
    pass


class ZirMalformedResponseError(ZirSourceError):
    pass


class ZirClient:
    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = 20.0,
        retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self._client = client
        self._owns_client = client is None
        self._initialized = False

    async def __aenter__(self) -> "ZirClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
            self._initialized = False

    async def initialize_session(self) -> str:
        response = await self._request("GET", self.search_url, headers=self._browser_headers())
        self._initialized = True
        return response.text

    async def search_consultations(
        self,
        *,
        cat_id: str,
        status: str = "1",
        theme: str = "all",
        date_s: str = "",
        date_e: str = "",
    ) -> str:
        await self._ensure_initialized()
        return await self._post_view(
            {
                "t": "getResultList",
                "wordsVal": "",
                "srcVal": "ques",
                "themeVal": theme,
                "checkedValue": "",
                "catVal": cat_id,
                "hrenVal": "all",
                "contVal": "cont-no",
                "statusVal": status,
                "statusFOP": "all",
                "dateS": date_s,
                "dateE": date_e,
            },
            required_tags=("count", "content"),
        )

    async def load_more(self, srch_words: str = "") -> str:
        await self._ensure_initialized()
        return await self._post_view(
            {"t": "addToResultList", "srchWords": srch_words},
            required_tags=("content",),
        )

    async def get_category_path(self, cat_id: str) -> str:
        await self._ensure_initialized()
        return await self._post_view(
            {"t": "getCategoryPath", "catId": cat_id},
            validate_xml=False,
        )

    async def get_consultation_page(self, zir_id: str, src: str = "ques") -> str:
        response = await self._request(
            "GET",
            f"{self.base_url}/main/bz/view/?src={src}&id={zir_id}",
            headers=self._browser_headers(),
        )
        if _looks_like_error_page(response.text):
            raise ZirMalformedResponseError(f"ZIR returned error page for consultation {src}:{zir_id}")
        return response.text

    async def get_answer_content(self, zir_id: str, src: str = "ques", srch_words: str = "") -> str:
        await self._ensure_initialized()
        return await self._post_view(
            {"t": "getAnswerContent", "id": zir_id, "srchWords": srch_words, "type": src},
            validate_xml=False,
        )

    async def _post_view(
        self,
        data: dict[str, Any],
        *,
        required_tags: tuple[str, ...] = (),
        validate_xml: bool = True,
    ) -> str:
        response = await self._request(
            "POST",
            f"{self.base_url}/bz/view",
            data={key: str(value) for key, value in data.items()},
            headers=self._xhr_headers(),
        )
        text = response.text
        try:
            if validate_xml:
                validate_ajax_xml(text, required_tags)
            elif _looks_like_error_page(text):
                raise ValueError("ZIR returned full HTML error page")
        except ValueError as exc:
            raise ZirMalformedResponseError(str(exc)) from exc
        return text

    async def _request(
        self,
        method: str,
        url: str,
        *,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        await self._ensure_client()
        assert self._client is not None

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = await self._client.request(method, url, data=data, headers=headers)
                self._validate_response(response, str(response.url))
                return response
            except (ZirAccessDeniedError, ZirNotFoundError):
                raise
            except ZirHTTPError as exc:
                last_error = exc
                logger.warning("zir_transient_status url=%s attempt=%s status=%s", url, attempt + 1, exc.status_code)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                logger.warning("zir_transient_error url=%s attempt=%s error=%s", url, attempt + 1, exc)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("zir_http_error url=%s attempt=%s error=%s", url, attempt + 1, exc)
            if attempt < self.retries:
                await asyncio.sleep(0.5 * (attempt + 1))
        if isinstance(last_error, ZirHTTPError):
            raise last_error
        raise RuntimeError(f"ZIR request failed for {url}: {last_error}") from last_error

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize_session()

    async def _ensure_client(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers=self._browser_headers(),
                verify=system_ssl_context(),
            )
            self._owns_client = True

    @property
    def search_url(self) -> str:
        return f"{self.base_url}/main/bz/search/?src=ques&srch=bz"

    def _validate_response(self, response: httpx.Response, url: str) -> None:
        if response.status_code == 403:
            raise ZirAccessDeniedError(403, url, "ZIR access denied")
        if response.status_code == 404:
            raise ZirNotFoundError(404, url, "ZIR endpoint or consultation not found")
        if response.status_code == 429 or 500 <= response.status_code < 600:
            raise ZirHTTPError(response.status_code, url)
        response.raise_for_status()

    def _browser_headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36 legal-monitoring/0.1"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
        }

    def _xhr_headers(self) -> dict[str, str]:
        return {
            **self._browser_headers(),
            "Referer": self.search_url,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/xml, text/xml, text/html, */*; q=0.01",
        }


def _looks_like_error_page(text: str) -> bool:
    leading = text.lstrip()[:200].lower()
    return (
        leading.startswith("<!doctype html")
        and ("<title>помилка</title>" in text.lower() or "module\\defaults\\erroor.phtml" in text)
    )
