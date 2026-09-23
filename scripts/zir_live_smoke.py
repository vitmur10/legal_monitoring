import asyncio

from app.sources.base import RawDocument
from app.sources.zir.adapter import ZirAdapter
from app.sources.zir.parser import parse_answer_fragment, parse_search_response
from app.sources.zir.schemas import ZirStatus


async def main() -> None:
    adapter = ZirAdapter(
        category_ids=["1"],
        statuses=[ZirStatus.CURRENT],
        max_load_more_batches=0,
        discovery_limit=3,
    )
    client = adapter.client

    await client.initialize_session()

    search_xml = await client.search_consultations(cat_id="1", status="1")
    search = parse_search_response(search_xml, default_status=ZirStatus.CURRENT)
    print(f"search_count={search.count} parsed_items={len(search.items)}")
    for item in search.items[:3]:
        print(f"item external_id={item.external_id} status={item.status} category={item.category}")

    stubs_by_id = {item.id: item for item in search.items}
    raw_inputs = [
        RawDocument(
            source_code="zir",
            external_id=stubs_by_id["38043"].external_id,
            canonical_url=stubs_by_id["38043"].canonical_url,
            title=stubs_by_id["38043"].question,
            metadata={
                "src": stubs_by_id["38043"].src,
                "zir_id": stubs_by_id["38043"].id,
                "category": stubs_by_id["38043"].category,
                "status": stubs_by_id["38043"].status.value,
                "status_text": stubs_by_id["38043"].status_text,
            },
        )
    ]
    raw_inputs.append(
        RawDocument(
            source_code="zir",
            external_id="ques:33804",
            canonical_url="https://zir.tax.gov.ua/main/bz/view/?src=ques&id=33804",
            metadata={"src": "ques", "zir_id": "33804", "status": ZirStatus.NON_CURRENT.value},
        )
    )

    for raw_input in raw_inputs:
        zir_id = str(raw_input.metadata["zir_id"])
        raw = await adapter.fetch_document(raw_input)
        normalized = await adapter.normalize(raw)
        answer = await client.get_answer_content(zir_id)
        parsed_answer = parse_answer_fragment(answer)
        print(
            "consultation "
            f"external_id={normalized.external_id} "
            f"status={normalized.metadata.get('status')} "
            f"category={normalized.metadata.get('category')} "
            f"refs={len(normalized.metadata.get('normative_references') or [])} "
            f"answer_non_empty={bool(parsed_answer.raw_text)}"
        )

    if hasattr(client, "__aexit__"):
        await client.__aexit__(None, None, None)


if __name__ == "__main__":
    asyncio.run(main())
