# DPS Ukraine Source Reconnaissance

Date: 2026-08-28

Scope: technical reconnaissance for official materials on `tax.gov.ua`. No production adapter, DB schema, migrations, Docker, PostgreSQL, AI, legal diff, Telegram, Notion, ZIR, or Minfin work was performed.

## 1. Investigated Endpoints

Primary official endpoints checked:

- `https://tax.gov.ua/media-tsentr/novini/`
- `https://tax.gov.ua/media-tsentr/novini/1025759.html`
- `https://tax.gov.ua/media-tsentr/novini/print-1025759.html`
- `https://tax.gov.ua/zakonodavstvo/podatki-ta-zbori/zagalnoderjavni-podatki/podatok-na-pributok-pidpri/formi-zvitnosti/80085.html`
- `https://tax.gov.ua/zakonodavstvo/podatki-ta-zbori/zagalnoderjavni-podatki/podatok-na-pributok-pidpri/formi-zvitnosti/print-80085.html`
- `https://www.tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/`
- `https://www.tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/80205.html`
- `https://www.tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/print-80205.html`
- `https://www.tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/80206.html`
- `https://www.tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/print-80206.html`
- `https://tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/listi-dps/`
- `https://tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/listi-dps/80200.html`
- `https://tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/listi-dps/print-80200.html`
- `https://tax.gov.ua/zakonodavstvo/podatki-ta-zbori/zagalnoderjavni-podatki/podatok-na-pributok-pidpri/listi/2026-rik/`
- `https://tax.gov.ua/search/?query=...`
- `https://tax.gov.ua/rss`, `https://tax.gov.ua/rss.xml`, `https://tax.gov.ua/media-tsentr/novini/rss`
- `https://tax.gov.ua/sitemap.xml`
- `https://tax.gov.ua/robots.txt`

Observed behavior:

- Browser-like `GET` works with a normal `User-Agent`.
- PowerShell default `Invoke-WebRequest` got `403 Forbidden`.
- `HEAD` is not reliable as a reconnaissance signal; use `GET`.
- Responses are `text/html; charset=UTF-8` and commonly gzip-compressed.
- `Last-Modified` and `ETag` were not present on checked pages.
- `Cache-Control` was generally `max-age=0, no-cache, no-store`.
- `robots.txt` returned `404` with a rendered site page, not a robots policy file.
- `sitemap.xml` returned `404`.
- RSS candidates returned `404` or `500`; RSS link exists in markup but is not a reliable feed in tested paths.

## 2. Discovery Strategy

The most stable discovered mechanism is official category list pages plus their built-in "load more" POST behavior.

List pages contain stable item links such as:

- `/media-tsentr/novini/1044966.html`
- `/zakonodavstvo/podatkove-zakonodavstvo/nakazi/80206.html`
- `/zakonodavstvo/podatkove-zakonodavstvo/listi-dps/80200.html`

Pagination / incremental loading:

- The page includes a `news__loadmore` control.
- `camon.js` shows that the list posts to the current URL with:
  - `more=1`
  - `page=<next page>`
  - optional `date_from`
  - optional `date_to`
- The response is JSON text with a `feed` field containing an HTML fragment.
- A test POST to `https://tax.gov.ua/media-tsentr/novini/` with `more=1&page=2` returned status `200` and a JSON object containing `feed`.

Recommended discovery approach:

1. Maintain a configured allowlist of important official sections.
2. Fetch page 1 HTML for each section.
3. Use POST `more=1&page=N` for a small bounded number of pages or until no `feed`.
4. Extract IDs and canonical URLs from item links.
5. Re-fetch known IDs periodically to detect content changes by hash.

Recommended initial sections:

- News: `https://tax.gov.ua/media-tsentr/novini/`
- Orders: `https://www.tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/`
- DPS letters: `https://tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/listi-dps/`
- Profit tax forms: `https://tax.gov.ua/zakonodavstvo/podatki-ta-zbori/zagalnoderjavni-podatki/podatok-na-pributok-pidpri/formi-zvitnosti/`
- Profit tax letters by year: `https://tax.gov.ua/zakonodavstvo/podatki-ta-zbori/zagalnoderjavni-podatki/podatok-na-pributok-pidpri/listi/2026-rik/`

Search should be fallback only. It works for exact document numbers, but results are broad and not incremental.

## 3. Identity Strategy

The numeric ID in URLs is the best primary identity:

- `print-80085.html` / `80085.html`
- `print-80205.html` / `80205.html`
- `print-1025759.html` / `1025759.html`

Findings:

- The same numeric ID appears in print and normal page URLs.
- Acceptance pages use the same ID in content asset paths, for example `/data/normativ/000/005/80085/...`.
- The ID appears stable across canonical and print counterparts.
- The same material may appear under different section paths in search results, e.g. `80206.html` can appear under general orders and profit-tax normative acts. That means the ID is safer than the full path as the primary identity.

Recommendation:

- `external_id`: `dps:<numeric_id>`, for example `dps:80205`.
- `canonical_url`: non-print page URL discovered from list/search/canonical footer, normalized to one preferred host/path if possible.
- `source_url`: the exact URL fetched, usually print URL for content and normal URL for attachments.

Do not use title as primary identity.

## 4. Canonical vs Print URL

Print URL pattern:

- Replace final `<id>.html` with `print-<id>.html` in the same section directory.

Observed:

- Print pages are much smaller and cleaner.
- Print pages contain title, author/issuer line, publication timestamp, section, body, optional additional materials text, and a footer with canonical non-print URL.
- Print pages do not always preserve attachment `href` URLs. For `80205` and `80085`, print pages list additional materials as text only; normal pages contain actual `/data/normativ/...docx` links.
- Normal pages contain navigation, menus, scripts, related UI, social/footer elements, and attachment links.

Recommendation:

- Use print page as primary content fetch.
- Use normal page as metadata/attachment supplement.
- Store both `canonical_url` and `source_url`.

## 5. Metadata Availability

Fields and source quality:

- `title`: structured enough in print page heading/title area; also visible in list item labels.
- `published_at`: print and normal pages contain Ukrainian text like `опубліковано 13 липня 2026 о 14:30`; structured text parsing required.
- `updated_at`: not observed as a distinct stable field.
- `category`: print page has `Розділ: Новини`, `Розділ: Накази`, `Розділ: Форми звітності`, `Розділ: Листи`.
- `document_type`: deterministic from section/path/category for broad type; details may require title/body parsing.
- `source_section`: deterministic from URL path and breadcrumb/list section.
- `author/issuer`: often visible before publication date, e.g. `Департамент методології` or `Пресслужба Державної податкової служби України`; optional.
- `document number`: requires regex parsing from title/body, e.g. `№ 186`, `№ 249`, `№ 293`, DPS letter number.
- `linked order/law number`: body text parsing or explicit link/attachment label parsing.
- `effective date`: only when explicitly stated in body, e.g. CRS page says from 1 July 2026; orders may state effective from official publication without publication source date.
- `attachments`: normal page structured links under `.materials-additional`; print page may only contain labels/sizes.
- `related links`: body links are available, e.g. CRS page links to a CRS notice page and a PDF.

## 6. Content Extraction

Best content endpoint:

- Print page is the cleanest primary source for article text.

Observed containers:

- Print pages wrap content in a `.print` layout and include a central material body.
- Normal pages contain a richer page container with navigation and a `materials-additional` block.

Cleanup should:

- remove `script`, `style`, navigation, footer, header, social sharing, outlinks, load-more controls, search forms, and sidebars;
- keep title, publication date, section, paragraphs, lists, tables, inline links, and additional-material labels;
- optionally merge attachment URLs from normal page into metadata.

No structured JSON article endpoint was found.

## 7. Updated vs New Detection

The site does not provide reliable HTTP validators in checked responses:

- no `Last-Modified`;
- no `ETag`;
- no observed explicit page revision/update timestamp.

Core versioning is still compatible:

- new numeric ID -> `NEW`;
- same numeric ID + same normalized content hash -> `UNCHANGED`;
- same numeric ID + changed normalized content hash -> `CHANGED`.

Recommendation:

- Use stable numeric `external_id`.
- Periodically re-fetch known IDs from monitored sections.
- Hash normalized print content plus a deterministic representation of attachments if attachment changes should count as document changes.
- Do not rely on HTTP cache validators.

## 8. Attachment Handling

Attachment types observed or supported by markup patterns:

- PDF: CRS page has `https://tax.gov.ua/data/files/687542.pdf`.
- DOCX: form/order pages have `/data/normativ/.../*.docx`.
- XLSX: site-wide footer/list markup includes `/data/files/529461.xlsx`; not acceptance-specific.
- ZIP/XML are plausible by extension handling but not observed in acceptance pages.

Acceptance case attachments:

- `80085` normal page has seven DOCX links for declaration and appendices:
  - `/data/normativ/000/005/80085/OSNOVNA_FORMA.docx`
  - `/data/normativ/000/005/80085/dodatok_AV.docx`
  - `/data/normativ/000/005/80085/Dodatok_VP.docx`
  - `/data/normativ/000/005/80085/dodatok_ZP.docx`
  - `/data/normativ/000/005/80085/dodatok_K_K.docx`
  - `/data/normativ/000/005/80085/Dodatok_MPZ_Z.docx`
  - `/data/normativ/000/005/80085/Dodatok_PP.docx`
- `80205` normal page has two DOCX links:
  - `/data/normativ/000/005/80205/Zm_ni.docx`
  - `/data/normativ/000/005/80205/Dodatok.docx`
- `1025759` print and normal pages have a PDF link:
  - `/data/files/687542.pdf`

Recommendation:

- Store attachments in `DocumentVersion.version_metadata["attachments"]` initially.
- Each attachment metadata item should contain URL, label, extension/type, size text if available, and source container.
- A dedicated Attachment model may be useful later if attachment diffing, downloads, hashes, or lifecycle tracking become Stage 1 requirements. It is not required for initial monitoring.

## 9. Relation Opportunities

Deterministic candidates:

- DPS page references Minfin order when title/body explicitly contains `Наказ Міністерства фінансів України від <date> № <number>`.
- DPS letter explains or provides guidance for an order when body explicitly says it is sent for administration/application and references that order.
- Attachment links can be related to their parent DPS page deterministically.
- Search/list links can discover separate pages for related documents, but search result proximity alone should not create relations.

Acceptance facts:

- `80206` title/body explicitly states Order №293 amends Order №249.
- `80200` body explicitly references Order №249 and Order №293 and explains administration/application of profit tax declaration changes.

Recommended relation handling:

- Add source-specific `relation_candidates` metadata only for explicit text/link evidence.
- Use `AMENDS` only for direct wording like Order №293 amends Order №249.
- Use `EXPLAINS` or `RELATED_TO` for DPS letters only when wording is explicit enough; otherwise leave to AI/relation enrichment.
- Do not infer tax relevance semantically in the adapter.

## 10. Rate / Access Limitations

Observed:

- Browser-like `GET` works.
- Default PowerShell user agent got `403`.
- No CAPTCHA was observed on tested pages.
- No Cloudflare challenge page was observed.
- Dynamic anti-bot/performance script URLs are present.
- gzip works.
- `Cache-Control: no-cache/no-store` is common.
- `HEAD` is less reliable than `GET`.

Recommendation:

- Use a stable, transparent browser-like `User-Agent`.
- Low request rate.
- Bounded pagination.
- Cache fetched IDs and content hashes.
- Retry only transient network/5xx errors.
- Avoid full-site crawl and browser automation.

## 11. Acceptance Case №186

URL:

- `https://tax.gov.ua/zakonodavstvo/podatki-ta-zbori/zagalnoderjavni-podatki/podatok-na-pributok-pidpri/formi-zvitnosti/print-80085.html`

Available facts:

- Page ID: `80085`.
- Canonical URL in print footer: `https://tax.gov.ua/zakonodavstvo/podatki-ta-zbori/zagalnoderjavni-podatki/podatok-na-pributok-pidpri/formi-zvitnosti/80085.html`.
- Title: Minfin Order dated `06.04.2026` № `186`, about changes to the corporate profit tax declaration form.
- Published: `22 квітня 2026 о 16:30`.
- Section: `Форми звітності`.
- Issuer/author line: `Департамент методології`.
- Body exists in print page.
- Attachments are present on normal page, not as hrefs on print page: declaration form and appendices in DOCX.

Sufficiency:

- Source data is sufficient for future AI/legal analysis: title, official body, publication timestamp, affected declaration/form, and attachments are available.

## 12. Acceptance Case №249 / №293 / DPS Letter

Primary URL:

- `https://www.tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/print-80205.html`

Related official pages found:

- Order №293: `https://www.tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/80206.html`
- Order №293 print: `https://www.tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/print-80206.html`
- DPS letter: `https://tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/listi-dps/80200.html`
- DPS letter print: `https://tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/listi-dps/print-80200.html`

Facts for `80205`:

- Page ID: `80205`.
- Title: Minfin Order dated `11.05.2026` № `249`.
- Published: `13 липня 2026 о 14:30`.
- Section: `Накази`.
- Body includes the order text.
- Normal page has two DOCX attachments.

Facts for `80206`:

- Page ID: `80206`.
- Title/body explicitly: Minfin Order dated `02.06.2026` № `293` amends Minfin Order dated `11 травня 2026 року` № `249`.
- Published on checked print page: `13 липня 2026 о 14:48`.
- Section: `Накази`.
- Relation `80206 AMENDS 80205` is deterministic from title/body wording.

Facts for `80200`:

- Page ID: `80200`.
- Title: DPS letter dated `08.07.2026` № `15504/7/99-00-21-02-01-07`.
- Published: `09 липня 2026 о 10:50`.
- Section: `Листи`.
- Body explicitly references Order №249 and Order №293.
- Body states the letter is for proper administration of corporate profit tax and tax control.

Recommendation:

- Deterministic relation:
  - Order №293 `AMENDS` Order №249.
- Deterministic or high-confidence source-specific candidate:
  - DPS letter `EXPLAINS` / `RELATED_TO` Order №249 and Order №293, because the letter explicitly references them and is about administration/application. Final relation type can be conservative as `RELATED_TO` unless wording rules for `EXPLAINS` are defined.
- Do not build broader graph relations from search-result co-occurrence.

## 13. Acceptance Case CRS 2.0

URL:

- `https://tax.gov.ua/media-tsentr/novini/print-1025759.html`

Available facts:

- Page ID: `1025759`.
- Canonical URL in print footer: `https://tax.gov.ua/media-tsentr/novini/1025759.html`.
- Title: CRS 2.0 new reporting rules for financial accounts.
- Published: `30 червня 2026 о 12:10`.
- Section: `Новини`.
- Author line: `Пресслужба Державної податкової служби України`.
- Body explicitly mentions Minfin Order № `316`.
- Body contains date `15.06.2026` for Order №316.
- Body explicitly says new requirements start from `1 липня 2026`.
- Body/print page includes PDF link `https://tax.gov.ua/data/files/687542.pdf`.
- Body links to `https://tax.gov.ua/baneryi/crs/povidomlennya/1025757.html`.

International taxation/reporting category:

- The page path is news, not an explicit international taxation category.
- CRS content and links are explicit in body and related URL, but category-level classification would require title/body keyword rules or later AI enrichment.

## 14. Recommended DpsAdapter Architecture

Do not implement yet. Recommended future structure:

```text
app/sources/dps/
    __init__.py
    client.py
    parser.py
    schemas.py
    adapter.py
```

Responsibilities:

- `client.py`
  - HTTP GET/POST with browser-like headers.
  - Retry transient failures.
  - `fetch_list_page(section_url)`.
  - `fetch_more(section_url, page, date_from=None, date_to=None)`.
  - `fetch_print_page(canonical_url or id/path)`.
  - `fetch_normal_page(canonical_url)`.

- `parser.py`
  - Parse list items from initial HTML and JSON `feed`.
  - Extract numeric page ID from URL.
  - Derive print URL and canonical URL.
  - Parse print page title, published_at, section, author, main body text.
  - Parse normal page attachments from `.materials-additional`.
  - Extract deterministic document references by strict regex plus explicit wording patterns.

- `schemas.py`
  - `DpsDocumentStub`.
  - `DpsPageMetadata`.
  - `DpsAttachment`.
  - `DpsRelationCandidate`.
  - `DpsDocumentType`.

- `adapter.py`
  - `fetch_items`: bounded discovery from configured sections.
  - `fetch_document`: print content + normal page attachment enrichment.
  - `normalize`: use existing legal text normalization and attach source metadata.

## 15. Core Compatibility

Current core structures are sufficient for initial Stage 1:

- `Document`: stable identity via `external_id=dps:<id>`.
- `DocumentVersion`: stores normalized content, raw content, hash, and source metadata.
- `DocumentRelation`: can store deterministic relation candidates resolved by external IDs when both documents exist.
- `MonitoringRun`: supports NEW / UNCHANGED / CHANGED / FAILED.

Potential future needs:

- Attachment model if attachment downloads, binary hashes, file updates, or attachment-level relations become required.
- Source section configuration table if section allowlist should be managed at runtime rather than code/config.
- More explicit relation metadata conventions across sources.

No DB schema change is recommended before implementing the first DpsAdapter version.

## 16. Risks

- RSS and sitemap are not reliable; discovery depends on HTML list structure and POST `more=1`.
- `robots.txt` did not return a usable policy file.
- Default/non-browser user agents may receive 403.
- Print pages can omit attachment href URLs.
- Normal pages are large and noisy.
- `updated_at` is not exposed reliably.
- Numeric IDs appear globally stable in tested pages but should be monitored for duplicates across mirrored section paths.
- Exact document type classification is deterministic at broad section level only; relevance/tax-topic classification should not be hardcoded too aggressively.

## 17. Open Questions

- Are numeric IDs globally unique across all tax.gov.ua content types, or only practically unique in current CMS behavior?
- Does the POST `more=1` endpoint accept stable date formats for all section types?
- Are older yearly archives consistently available for all tax categories?
- Do some sections expose hidden APIs not present in loaded JS?
- Should attachment content changes count as parent document changes in Stage 1?
- Which relation type should be used for DPS letters that explicitly discuss implementation: `EXPLAINS` or conservative `RELATED_TO`?
