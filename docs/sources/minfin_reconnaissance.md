# Minfin Source Reconnaissance

Date: 2026-08-29

Scope: technical reconnaissance for official materials on `mof.gov.ua`. No production `MinfinAdapter`, DB schema, migrations, Docker, PostgreSQL, AI, legal diff, Telegram, Notion, Playwright, Selenium, proxy, CAPTCHA bypass, or broad crawl was performed.

## 1. Investigated Endpoints

Primary official endpoints checked:

- `https://mof.gov.ua/`
- `https://mof.gov.ua/uk/`
- `https://mof.gov.ua/uk/tax-policy`
- `https://mof.gov.ua/uk/set-of-summarizing-tax-consultations`
- `https://mof.gov.ua/uk/crs-578`
- `https://mof.gov.ua/uk/news`
- `https://www.mof.gov.ua/uk/news/ukraina_vprovadzhuie_crs_20_minfin_onoviv_pravila_avtomatichnogo_obminu_informatsiieiu_pro_finansovi_rakhunki-5797`
- `https://mof.gov.ua/uk/accounting`
- `https://mof.gov.ua/uk/buhgalterskij-oblik-ta-auditorska-dijalnist`
- `https://mof.gov.ua/uk/buhgalterskij-oblik-v-pidpriemnickij-sferi`
- `https://mof.gov.ua/uk/nacionalni-polozhennja1`
- `https://mof.gov.ua/uk/nacionalni-polozhennja`
- `https://mof.gov.ua/uk/zagalni-rozjasnennja-fin-zvitnosti`
- `https://mof.gov.ua/uk/zagalni-roz_jasnennja`
- `https://mof.gov.ua/uk/sustainability_reporting-806`
- `https://mof.gov.ua/uk/regulatory_and_legal_documents-807`
- `https://mof.gov.ua/uk/international-tax-relations`
- `https://mof.gov.ua/uk/clarification-641`
- `https://mof.gov.ua/uk/crs_reporting-741`
- `https://mof.gov.ua/uk/transfer_pricing_regulatory_documents-839`
- `https://mof.gov.ua/uk/proekti-normativno-pravovih-aktiv`
- `https://mof.gov.ua/uk/Draft_regulatory_legal_acts_in_2026`
- `https://mof.gov.ua/uk/postanovi`
- `https://mof.gov.ua/uk/orders_of_the_Ministry_of_Finance_of_Ukraine_in_2026.`
- `https://mof.gov.ua/uk/orders_of_the_ministry_of_finance_of_ukraine_in_2025-823`
- `https://mof.gov.ua/uk/search?query=316`
- `https://mof.gov.ua/uk/search?query=CRS`
- `https://mof.gov.ua/uk/search?query=податкова+консультація`
- `https://mof.gov.ua/uk/search?query=бухгалтерський+облік`
- `https://mof.gov.ua/robots.txt`
- `https://mof.gov.ua/sitemap.xml`
- `https://mof.gov.ua/rss`
- `https://mof.gov.ua/rss.xml`

Representative attachment endpoints checked through page links:

- `https://mof.gov.ua/storage/files/Наказ_316.pdf`
- `https://mof.gov.ua/storage/files/Зміни_наказ_316.pdf`
- `https://mof.gov.ua/storage/files/Наказ_УПК_оборонні закупівлі.pdf`
- `https://mof.gov.ua/storage/files/УПК оборонні закупівлі.pdf`
- `https://mof.gov.ua/storage/files/Наказ №249.pdf`
- `https://mof.gov.ua/storage/files/Зміни_до наказу №249.pdf`

Observed behavior:

- Public pages are server-rendered HTML and are readable without browser automation from a normal browser/indexed fetch path.
- Local low-rate `curl.exe` from this environment returned Akamai `403 Access Denied` for pages, `robots.txt`, `sitemap.xml`, and RSS candidates, even with a browser-like `User-Agent`.
- The `403` response includes `Cache-Control: max-age=0, no-cache, no-store`, no useful `ETag`, no useful `Last-Modified`, and Akamai `Server-Timing`.
- The public site banner says the site is in test operation mode.
- The pages use Ukrainian path prefixes, usually `/uk/...`.
- The same content may be indexed under both `mof.gov.ua` and `www.mof.gov.ua`; canonicalization should normalize host to one configured base host.

## 2. Discovery Strategy

Best currently identified discovery sources:

1. Stable official HTML pages and year tables.
2. News list page with query filters and "load more" UI.
3. Official search as fallback.
4. Browser automation only as a last resort, not required for MVP design.

No official structured JSON API, sitemap, or RSS feed was confirmed during this reconnaissance.

Recommended MVP discovery:

- Maintain an allowlist of important Minfin section URLs.
- Fetch each section page and parse either:
  - static page body;
  - table rows with document links and attachment links;
  - news list item links.
- For yearly order/project pages, parse the table as the primary list source and schedule the current year more frequently.
- For static policy pages such as `tax-policy`, `crs-578`, `accounting`, and standards pages, re-fetch the page itself and detect changes by hash.
- For news, use `https://mof.gov.ua/uk/news` plus filters:
  - `date-from=YYYY-MM-DD`
  - `date-to=YYYY-MM-DD`
  - `type=<numeric category>`
- Treat search as fallback for targeted checks by order number, CRS, or phrase. Search is useful but not a stable incremental feed.

Discovery priority for MVP:

1. `https://mof.gov.ua/uk/orders_of_the_Ministry_of_Finance_of_Ukraine_in_2026.`
2. `https://mof.gov.ua/uk/set-of-summarizing-tax-consultations`
3. `https://mof.gov.ua/uk/crs-578`
4. `https://mof.gov.ua/uk/clarification-641`
5. `https://mof.gov.ua/uk/accounting`
6. `https://mof.gov.ua/uk/nacionalni-polozhennja1`
7. `https://mof.gov.ua/uk/nacionalni-polozhennja`
8. `https://mof.gov.ua/uk/zagalni-rozjasnennja-fin-zvitnosti`
9. `https://mof.gov.ua/uk/zagalni-roz_jasnennja`
10. `https://mof.gov.ua/uk/Draft_regulatory_legal_acts_in_2026`
11. `https://mof.gov.ua/uk/news?date-from=<recent>&date-to=&type=`

## 3. Identity Strategy

Observed identity patterns:

- News pages have a stable numeric suffix in the URL, for example:
  - `.../uk/news/ukraina_vprovadzhuie_crs_20_minfin_onoviv_pravila_avtomatichnogo_obminu_informatsiieiu_pro_finansovi_rakhunki-5797`
  - Recommended `external_id`: `news:5797`
- Some static/section pages have a numeric suffix, for example:
  - `crs-578`
  - `clarification-641`
  - `crs_reporting-741`
  - `sustainability_reporting-806`
  - `regulatory_and_legal_documents-807`
  - `orders_of_the_ministry_of_finance_of_ukraine_in_2025-823`
  - Recommended `external_id`: `page:<numeric_suffix>` when suffix exists.
- Some official pages have no visible numeric suffix, for example:
  - `tax-policy`
  - `set-of-summarizing-tax-consultations`
  - `accounting`
  - `orders_of_the_Ministry_of_Finance_of_Ukraine_in_2026.`
  - Recommended `external_id`: `path:<normalized_uk_path>`.
- Many order and consultation table rows link directly to files, not separate HTML pages. For these row-level documents, use deterministic legal identity:
  - `order:<YYYY-MM-DD>:<number>`
  - example: `order:2026-06-15:316`
  - for general tax consultations: `general_tax_consultation:<order_date>:<order_number>`.

Recommended fields:

- `external_id`:
  - page/news: numeric suffix when present;
  - static page without suffix: normalized path;
  - row-level order/consultation: extracted kind, order date, order number.
- `canonical_url`:
  - normalized absolute URL for HTML pages;
  - for row-level orders with no HTML page, use the source table page plus a stable fragment-like synthetic suffix in metadata, not as real URL.
- `source_url`:
  - exact list/page URL where the item was discovered.

Do not use title as identity when a numeric suffix, path, or order date/number exists. Slugs may change when titles change; the trailing numeric suffix is safer for news and many section pages. For pages without suffix, path is the only observed stable identifier.

## 4. Material Types

Recommended broad classification:

- `NEWS`: `/uk/news/...` and `/uk/news` list items.
- `TAX_POLICY`: `/uk/tax-policy` and direct child pages under the tax policy menu.
- `GENERAL_TAX_CONSULTATION`: rows in `/uk/set-of-summarizing-tax-consultations` whose title contains "Узагальнюючої податкової консультації" or "Узагальнюючих податкових консультацій".
- `ORDER`: rows in `/uk/orders_of_the_Ministry_of_Finance_of_Ukraine_in_<year>` and related "Постанови та Накази" pages.
- `ACCOUNTING`: accounting pages and rows under `/uk/accounting`, `/uk/nacionalni-polozhennja1`, `/uk/nacionalni-polozhennja`, `/uk/zagalni-роз...` accounting sections.
- `FINANCIAL_REPORTING`: IFRS, financial reporting explanations, sustainability reporting, and reporting-specific pages.
- `CRS`: `/uk/crs-578`, `/uk/crs_reporting-741`, `/uk/clarification-641`, and CRS child pages.
- `OTHER`: anything outside the allowlist or not safely classified from path/section.

Keep classification path/section-based. Avoid semantic taxonomy.

## 5. Metadata Availability

Observed metadata by field:

- `title`: structured enough from page heading or list/table link text. Required for all examples.
- `published_at`: available for news pages and list items as a visible date. For table rows, first column is publication/list date, not always order date.
- `updated_at`: not observed as a visible field on checked pages. Treat as unavailable unless raw HTML later exposes it.
- `category`: available from section path or news `type` filter, but not consistently shown as a structured field.
- `section`: stable from URL path/menu hierarchy.
- `issuer/author`: usually implicit "Міністерство фінансів України"; not consistently a page field.
- `document number`: deterministic in order titles when pattern exists.
- `order number`: deterministic with regex over explicit text, for example `від 15.06.2026 № 316` or `від 15 червня 2026 року № 316`.
- `order date`: deterministic with the same regex; support numeric and Ukrainian month forms.
- `effective date`: occasionally present in page text. CRS page explicitly says changes enter into effect from `1 липня 2026 року`. PDF order text may say "набирає чинності з дня його офіційного опублікування".
- `attachments`: available as links in tables or "Додаткові матеріали та посилання"; labels are visible. File size was not visible in checked pages.
- `related links`: available as inline links in content and attachment sections.
- `tags`: not observed.

Stability:

- Page/title/date/link text: medium to high.
- Order number/date extracted from explicit titles: high.
- Effective date: optional, high when explicitly present.
- Updated date/tags/author/file size: low or unavailable.

## 6. Content Extraction

Best extraction strategy:

- Prefer raw HTML parsing once access is confirmed in the deployment environment.
- Extract from the main page body after the global navigation/sidebar and before newsletter/footer blocks.
- Preserve:
  - heading/title;
  - paragraphs;
  - lists;
  - tables;
  - inline links with labels and absolute hrefs;
  - attachment link labels and URLs.
- Remove:
  - header;
  - footer;
  - global menu;
  - search form;
  - breadcrumbs unless needed for section metadata;
  - newsletter/subscription forms;
  - related cards/news controls;
  - social buttons;
  - scripts/styles;
  - cookie/UI noise.

Selector recommendation:

- Final CSS selectors need validation against raw HTML in a non-blocked HTTP environment.
- Do not parse by rendered line number.
- Candidate approach:
  - locate `h1`;
  - find its nearest content wrapper;
  - remove descendants matching nav/search/newsletter/footer/sidebar/social/script/style;
  - keep `p`, `h2`-`h6`, `ul`, `ol`, `table`, and `a`.
- For year/order/consultation pages, parse actual HTML tables if present; if the CMS emits table-like markup rather than semantic `table`, fall back to ordered link/date grouping inside the content wrapper.

## 7. Updated vs New

No reliable visible `updated_at`, revision marker, `ETag`, or `Last-Modified` was confirmed.

Recommended behavior with existing core:

- New `external_id` -> `NEW`.
- Same `external_id` and same semantic hash -> `UNCHANGED`.
- Same `external_id` and changed normalized content -> `CHANGED`.

For pages with numeric suffix or stable path, identity is stable enough for update detection. For row-level order/consultation entries, identity by order date and number is stable enough if extracted from explicit text.

Do not interpret temporary 403/5xx/network failures as deletion.

## 8. Attachments

Observed attachment types:

- PDF: confirmed in orders and consultations.
- XLS/XLSX: likely in reporting/form pages, especially tax/reporting forms, but not confirmed in low-rate samples.
- DOC/DOCX: likely in draft regulatory pages, but not confirmed in low-rate samples.
- ZIP/XML: possible in CRS/reporting technical materials, but not confirmed in low-rate samples.

Attachment metadata available:

- URL: yes, usually under `/storage/files/...`.
- Label: yes, visible link text such as `Додаток`, `Додаток. Зміни`, `Форма звіту`.
- Type: infer from extension or response content type.
- Size: not visible on checked pages.
- Relation to page: inferred from table row or section block.

Recommendation: store attachment metadata inside `DocumentVersion.version_metadata`, for example:

```json
{
  "attachments": [
    {
      "label": "Додаток. Зміни",
      "url": "https://mof.gov.ua/storage/files/...",
      "content_type": "application/pdf",
      "extension": "pdf",
      "source_context": "orders_2026 row order:2026-06-15:316"
    }
  ]
}
```

Do not create an `Attachment` DB model for MVP.

## 9. Tax Policy

`https://mof.gov.ua/uk/tax-policy` is a static policy/landing page, not a list of dated child materials.

Observed content:

- Describes state tax policy.
- Links to the Ministry regulation, the public finance management strategy, the Tax Code, and the social contribution law.
- No page-level publication date was visible.
- No pagination was visible.

Discovery:

- Monitor the page itself by path identity: `path:/uk/tax-policy`.
- Discover child sections through the menu allowlist, especially:
  - `/uk/set-of-summarizing-tax-consultations`
  - `/uk/clarification-641` for CRS explanations
  - `/uk/news?date-from=<recent>&date-to=&type=` for recent news fallback.

Incremental discovery of new tax-policy-specific materials is not available from this landing page alone.

## 10. General Tax Consultations

`https://mof.gov.ua/uk/set-of-summarizing-tax-consultations` is a static page containing explanatory text and a full table of consultations.

Observed:

- It is not a paginated list.
- Each consultation row usually links directly to one or more PDF files, not a separate HTML consultation page.
- Rows include:
  - list/publication date;
  - order title;
  - explicit order date and number;
  - attachments.
- The page also references the expert council and procedural documents.

Examples:

- `12.06.2026`: `Наказ Міністерства фінансів України від 12.06.2026 № 314 ... Узагальнюючої податкової консультації ...`
- `04.03.2026`: orders `№ 133` and `№ 132`.
- `09.08.2024`: order `№ 397`.

Deterministic relation opportunity:

- Consultation rows explicitly mention Tax Code provisions in the title, for example `пункт 197.23 статті 197` and `підпунктами 4 та 5 пункту 32 підрозділу 2 розділу ХХ`.
- A relation such as `EXPLAINS` can be created only when exact Tax Code provision text is present in the title/body or attachment text and the target rule can be resolved deterministically by the Rada source. Do not infer from topic alone.

## 11. CRS Case

Acceptance case checked:

- Primary page: `https://mof.gov.ua/uk/crs-578`
- Related news page: `https://www.mof.gov.ua/uk/news/ukraina_vprovadzhuie_crs_20_minfin_onoviv_pravila_avtomatichnogo_obminu_informatsiieiu_pro_finansovi_rakhunki-5797`
- Orders page row: `https://mof.gov.ua/uk/orders_of_the_Ministry_of_Finance_of_Ukraine_in_2026.`
- Attachments:
  - `https://mof.gov.ua/storage/files/Наказ_316.pdf`
  - `https://mof.gov.ua/storage/files/Зміни_наказ_316.pdf`

Facts available from official pages:

- Title/section identity: `CRS: автоматичний обмін інформацією про фінансові рахунки`, external ID `page:578`.
- Page content references `Порядок застосування CRS`, approved by Minfin order `26 травня 2023 року № 282`.
- Page explicitly says changes were approved by order `15 червня 2026 року № 316`, with changes by order `25 червня 2026 року № 338`.
- Page explicitly says these changes enter into effect from `1 липня 2026 року`.
- Orders 2026 page has a row dated `26.06.2026` for `Наказ Міністерства фінансів України від 15.06.2026 № 316 ...` and an attachment `Додаток. Зміни`.
- Related news page dated `30 Червня 2026` says the updated procedure will apply from `1 липня 2026 року`.
- Cross-source links include Rada for the base CRS procedure and other official/international materials.

PDF notes:

- `Наказ_316.pdf` text visible through PDF extraction contains an unsigned template line `від ______________ Київ № __________`, but body text identifies the subject and says the order enters into force from official publication. Prefer page/table title for date and number in metadata.
- `Зміни_наказ_316.pdf` explicitly states approval by `Наказ Міністерства фінансів України 15 червня 2026 року № 316`.

## 12. Accounting/Financial Reporting

Relevant official sections:

- `https://mof.gov.ua/uk/buhgalterskij-oblik-ta-auditorska-dijalnist`
- `https://mof.gov.ua/uk/accounting`
- `https://mof.gov.ua/uk/buhgalterskij-oblik-v-pidpriemnickij-sferi`
- `https://mof.gov.ua/uk/nacionalni-polozhennja1`
- `https://mof.gov.ua/uk/nacionalni-polozhennja`
- `https://mof.gov.ua/uk/zagalni-rozjasnennja-fin-zvitnosti`
- `https://mof.gov.ua/uk/zagalni-roz_jasnennja`
- `https://mof.gov.ua/uk/sustainability_reporting-806`
- `https://mof.gov.ua/uk/regulatory_and_legal_documents-807`
- `https://mof.gov.ua/uk/Draft_regulatory_legal_acts_in_2026`
- `https://mof.gov.ua/uk/orders_of_the_Ministry_of_Finance_of_Ukraine_in_2026.`

Observed structures:

- `accounting` is a static list of core normative acts with links to Rada.
- `nacionalni-polozhennja1` lists national accounting standards for the business sector with Rada links.
- `nacionalni-polozhennja` lists public-sector accounting standards with Rada links.
- `zagalni-rozjasnennja-fin-zvitnosti` lists dated downloadable financial reporting explanations.
- `zagalni-roz_jasnennja` lists dated downloadable accounting explanations.
- `orders_of_the_Ministry_of_Finance_of_Ukraine_in_2026.` includes accounting and reporting orders with attachments.
- `Draft_regulatory_legal_acts_in_2026` includes draft accounting/reporting acts and attachments.

Real examples:

- `Національне положення (стандарт) бухгалтерського обліку 1 "Загальні вимоги до фінансової звітності"`, linked from `nacionalni-polozhennja1` to Rada.
- `Наказ Міністерства фінансів України від 01 червня 2026 року № 292 "Про затвердження Змін до Національного положення (стандарту) бухгалтерського обліку в державному секторі 132 "Виплати працівникам"` with attachment `Додаток. Зміни`.
- `Наказ Міністерства фінансів України від 19 травня 2026 року № 262 "Про затвердження Змін до деяких нормативно-правових актів з бухгалтерського обліку в державному секторі"` with attachment `Додаток. Зміни`.
- `Проєкт наказу Міністерства фінансів України "Про затвердження Змін до деяких нормативно-правових актів Міністерства фінансів України з бухгалтерського обліку"` dated `12.06.2026`, with publication notice, draft changes, and report links.

## 13. Search

Official search endpoint:

- `GET https://mof.gov.ua/uk/search?query=<term>`

Observed search UI:

- Keyword input.
- Button `Знайти`.
- Button `Знайти в документах`.
- Results grouped by site area, for example `Про Міністерство`, `Діяльність`, `Законодавство`, `Для громадськості`, `Пресцентр`.
- Results include counts and "Завантажити ще" controls.

Search checks:

- `316`: official search and external search find CRS page, related CRS news, and the 2026 orders page.
- `CRS`: finds CRS static pages, CRS reporting, and CRS explanations.
- `податкова консультація`: finds the full consultations page.
- `бухгалтерський облік`: finds accounting sections and order/project pages.

Search is a fallback because:

- It is relevance-based, not a stable chronological feed.
- It mixes page sections and news.
- Pagination/load-more mechanics were not verified at raw HTTP level due local `403`.

## 14. Relations

Deterministic relation candidates:

- Minfin page `REFERENCES` Minfin order:
  - extract exact pattern `наказом Мінфіну від 15 червня 2026 року № 316`.
- Minfin order `AMENDS` or `CHANGES` another Minfin order:
  - only when explicit title says `Про внесення змін до наказу ... від ... № ...`.
- Minfin consultation `EXPLAINS` Tax Code provision:
  - only when exact article/paragraph/subparagraph references are present.
- Minfin page `REFERENCES` Rada document:
  - direct links to `zakon.rada.gov.ua` or `zakon2.rada.gov.ua`.
- Minfin page `REFERENCES` DPS:
  - explicit `tax.gov.ua` links or emails/mentions; a resolver can be added later.

Recommended DTO:

```python
MinfinDocumentReference(
    kind: str,
    number: str | None,
    date: date | None,
    url: str | None,
    text: str,
)
```

Regex targets:

- `наказ(?:ом)? (?:Міністерства фінансів України|Мінфіну) від (?P<date>...) № ?(?P<number>[0-9]+)`
- `постанов(?:ою|а) Кабінету Міністрів України від (?P<date>...) № ?(?P<number>[0-9]+)`
- Rada URL plus visible title.

Do not perform semantic NLP for relations.

## 15. Cross-Source References

Observed cross-source opportunities:

- Rada:
  - Tax Code links from tax policy page.
  - Ministry regulation and public finance strategy links.
  - Accounting standards and procedures from accounting pages.
  - CRS base procedure and MCAA CRS links.
- DPS:
  - CRS page mentions reporting submission to the State Tax Service and gives `crs.info@tax.gov.ua`.
  - News and CRS pages contain practical references to DPS.
- EU/OECD:
  - CRS page references OECD and DAC 8.
  - Sustainability reporting page links to EUR-Lex Directive `(ЄС) 2022/2464`.
  - News page references EU4PFM.

No cross-source resolver should be implemented in MVP reconnaissance. Store explicit references in metadata or create relations only when target documents are already resolvable.

## 16. HTTP/Access

Low-rate HTTP findings:

- Local `curl.exe -I -L https://mof.gov.ua/uk/tax-policy` returned `403 Forbidden`.
- Same behavior for:
  - `/uk/set-of-summarizing-tax-consultations`
  - `/uk/crs-578`
  - `/robots.txt`
  - `/sitemap.xml`
  - `/rss`
- Browser-like `User-Agent` did not change local `403`.
- Response looked like Akamai/EdgeSuite access denial.
- No CAPTCHA was encountered in the accessible rendered/indexed path.
- No cookies, CSRF, or session requirements were confirmed for normal page reads.
- Encoding is UTF-8 on indexed HTML pages.
- Attachment PDFs are publicly reachable through official links in the browser/indexed path.

Risk: access must be re-tested from the deployment network. Do not build anti-bot bypass. If official site blocks simple HTTP clients, consider:

- polite browser-like headers;
- low request rate;
- conditional fallback to search-index discovery;
- manual allowlisting of key pages;
- direct attachment links discovered from official pages.

## 17. Real Examples

1. CRS static page
   - URL: `https://mof.gov.ua/uk/crs-578`
   - Stable ID: `page:578`
   - Title: `CRS: автоматичний обмін інформацією про фінансові рахунки`
   - Date: no visible page publication date
   - Type: `CRS`
   - Body: available as HTML page content
   - Attachments/links: CRS standards, MCAA CRS, base procedure, order 316 changes, information letter, order 468, order 516, order 674, presentations/videos/OECD
   - References: Minfin orders `282`, `316`, `338`; Rada; OECD/EU; DPS

2. CRS news item
   - URL: `https://www.mof.gov.ua/uk/news/ukraina_vprovadzhuie_crs_20_minfin_onoviv_pravila_avtomatichnogo_obminu_informatsiieiu_pro_finansovi_rakhunki-5797`
   - Stable ID: `news:5797`
   - Title: `Україна впроваджує CRS 2.0: Мінфін оновив правила автоматичного обміну інформацією про фінансові рахунки`
   - Date: `30 Червня 2026`
   - Type: `NEWS` plus CRS-related metadata
   - Body: available
   - Attachments: no direct file attachment observed in page body; inline links exist
   - References: order `15 червня 2026 року № 316`, CRS page, EU4PFM, DPS contact email

3. Tax policy page
   - URL: `https://mof.gov.ua/uk/tax-policy`
   - Stable ID: `path:/uk/tax-policy`
   - Title: `Податкова політика`
   - Date: no visible publication date
   - Type: `TAX_POLICY`
   - Body: available
   - Attachments: none observed
   - References: Ministry regulation, strategy, Tax Code, social contribution law

4. General tax consultation row
   - Source URL: `https://mof.gov.ua/uk/set-of-summarizing-tax-consultations`
   - Stable ID: `general_tax_consultation:2026-06-12:314`
   - Title: `Наказ Міністерства фінансів України від 12.06.2026 № 314 ... Узагальнюючої податкової консультації ...`
   - Date: row date `12.06.2026`; order date `12.06.2026`
   - Type: `GENERAL_TAX_CONSULTATION`
   - Body: table row plus PDF attachments
   - Attachments: order PDF and consultation PDF
   - References: Tax Code provisions explicitly named in title and attachment

5. Accounting page
   - URL: `https://mof.gov.ua/uk/accounting`
   - Stable ID: `path:/uk/accounting`
   - Title: `Бухгалтерський облік`
   - Date: no visible publication date
   - Type: `ACCOUNTING`
   - Body: available
   - Attachments: none observed; external Rada links
   - References: accounting law, financial reporting procedure, Minfin orders `88` and `879`

6. Financial reporting explanations page
   - URL: `https://mof.gov.ua/uk/zagalni-rozjasnennja-fin-zvitnosti`
   - Stable ID: `path:/uk/zagalni-rozjasnennja-fin-zvitnosti`
   - Title: `Загальні роз'яснення`
   - Date: item dates visible, for example `03 Березня 2021`
   - Type: `FINANCIAL_REPORTING`
   - Body: list of dated downloadable materials
   - Attachments: downloadable linked documents
   - References: financial reporting and IFRS topics

7. Order with tax reporting form attachments
   - Source URL: `https://mof.gov.ua/uk/orders_of_the_Ministry_of_Finance_of_Ukraine_in_2026.`
   - Stable ID: `order:2026-05-11:249`
   - Title: `Наказ Міністерства фінансів України від 11 травня 2026 року № 249 "Про затвердження Змін до форми Податкової декларації з податку на прибуток підприємств"...`
   - Date: row date `08.06.2026`; order date `11.05.2026`
   - Type: `ORDER`
   - Body: table row plus PDF attachments
   - Attachments: `Наказ №249.pdf`, `Зміни_до наказу №249.pdf`, and labels `Додаток. Зміни`, `Додаток ЄП`
   - References: changes to tax declaration form

8. Accounting order with attachment
   - Source URL: `https://mof.gov.ua/uk/orders_of_the_Ministry_of_Finance_of_Ukraine_in_2026.`
   - Stable ID: `order:2026-06-01:292`
   - Title: `Наказ Міністерства фінансів України від 01 червня 2026 року № 292 "Про затвердження Змін до Національного положення (стандарту) бухгалтерського обліку в державному секторі 132 "Виплати працівникам""`
   - Date: row date `17.06.2026`; order date `01.06.2026`
   - Type: `ACCOUNTING` plus `ORDER`
   - Body: table row plus attachment
   - Attachments: `Додаток. Зміни`
   - References: NPSAS 132

## 18. Hashing Recommendation

Semantic hash input:

- normalized title;
- normalized main content text;
- normalized tables/list rows;
- meaningful dates:
  - visible publication/list date;
  - extracted order date;
  - extracted effective date when explicit;
- attachment metadata:
  - label;
  - normalized URL;
  - extension/content type;
  - row context.

Exclude:

- header/menu/footer;
- search and subscription UI;
- "Завантажити ще";
- related/news cards outside the main article/list;
- social buttons;
- scripts/styles;
- cookie banners/UI noise;
- volatile generated timestamps/session data;
- external crawler line numbers.

Do not change the core SHA256 implementation.

## 19. Core Compatibility

Existing core models are sufficient for MVP:

- `Document`
  - stores source identity, title, type, publication/effective date.
- `DocumentVersion`
  - stores raw content, normalized content, hash, and `version_metadata`.
  - sufficient for attachment metadata without schema changes.
- `DocumentRelation`
  - sufficient for explicit document references when both sides exist in the corpus.
- `MonitoringRun`
  - sufficient for run status and counts.

Potential future needs only:

- first-class attachment model if later attachment-level diffing/search/download state becomes important;
- stronger relation target model for unresolved external references;
- separate "source page" vs "legal document row" entity if Minfin order tables become a large primary corpus.

No schema change is recommended before Minfin MVP.

## 20. Recommended MinfinAdapter

Recommended package shape:

```text
app/sources/minfin/
    __init__.py
    client.py
    parser.py
    schemas.py
    adapter.py
```

Responsibilities:

- `client.py`
  - HTTP GET/POST wrapper;
  - retry/backoff;
  - base URL normalization;
  - low-rate behavior;
  - content-type handling;
  - explicit handling of `403` as access failure, not deletion.
- `parser.py`
  - page body extraction;
  - news list parsing;
  - year/order table parsing;
  - consultation table parsing;
  - attachment extraction;
  - explicit reference extraction by regex;
  - Ukrainian date parsing.
- `schemas.py`
  - `MinfinDocumentStub`
  - `MinfinAttachment`
  - `MinfinReference`
  - `MinfinDocumentType`
- `adapter.py`
  - converts stubs and full parsed pages to `RawDocument`;
  - converts raw documents to `NormalizedDocument`;
  - populates metadata with attachments, source URL, section, extracted references, row date, order date/number, and access diagnostics.

Suggested metadata keys:

- `source_url`
- `section`
- `path`
- `row_date`
- `order_number`
- `order_date`
- `effective_date_text`
- `attachments`
- `references`
- `access`

No production adapter was implemented in this reconnaissance step.

## 21. Risk Assessment

Overall complexity: `MEDIUM`.

Breakdown:

- Access: `HIGH`
  - local simple HTTP gets are blocked by Akamai `403`; deployment-network testing is mandatory.
- Identity: `LOW` to `MEDIUM`
  - numeric suffixes and order date/number are strong; static path-only pages are acceptable but less ideal.
- Discovery: `MEDIUM`
  - no confirmed structured API/RSS/sitemap; official HTML tables are usable.
- Content extraction: `MEDIUM`
  - pages include large navigation/footer; raw selectors need validation.
- Updated detection: `MEDIUM`
  - no visible `updated_at`; hash-based detection is required.
- Attachments: `LOW` to `MEDIUM`
  - links and labels are visible; size and attachment revision metadata are not.
- Anti-bot: `HIGH`
  - do not bypass; keep rate low and document failures.

## 22. Open Questions

- Does the production/deployment network receive `403` from `mof.gov.ua`, or is blocking specific to this local/sandbox environment?
- What are the exact raw HTML CSS selectors for the main content wrapper, table rows, and load-more controls?
- Does the news "Завантажити ще" endpoint use a POST/AJAX endpoint, query paging, or both?
- Does "Знайти в документах" use a separate search parameter or endpoint from `GET /uk/search?query=`?
- Are `robots.txt`, `sitemap.xml`, `rss`, and `rss.xml` truly missing/unavailable, or blocked only for direct HTTP clients?
- Are file sizes available in raw HTML attributes or only through HTTP headers?
- Should row-level orders from yearly pages be represented as primary documents in MVP, or should the page be primary and orders kept in metadata until a stronger Minfin order source is found?
