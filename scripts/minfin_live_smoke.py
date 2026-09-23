from __future__ import annotations

import asyncio

from app.sources.minfin.client import MinfinAccessBlockedError, MinfinClient, MinfinHTTPError
from app.sources.minfin.parser import parse_consultation_table, parse_order_table, parse_page


TARGETS = [
    ("static", "https://mof.gov.ua/uk/crs-578"),
    ("orders", "https://mof.gov.ua/uk/orders_of_the_Ministry_of_Finance_of_Ukraine_in_2026."),
    ("consultations", "https://mof.gov.ua/uk/set-of-summarizing-tax-consultations"),
]


async def main() -> None:
    async with MinfinClient(retries=1, min_delay=1.0) as client:
        for kind, url in TARGETS:
            try:
                html = await client.get_text(url)
                if kind == "orders":
                    count = len(parse_order_table(html, url))
                elif kind == "consultations":
                    count = len(parse_consultation_table(html, url))
                else:
                    count = 1 if parse_page(html, url) else 0
                print(f"{url} OK items={count}")
            except MinfinAccessBlockedError as exc:
                print(f"{url} ACCESS_BLOCKED status={exc.status_code}")
            except MinfinHTTPError as exc:
                print(f"{url} {exc.access_classification} status={exc.status_code}")
            except Exception as exc:
                print(f"{url} ERROR {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
