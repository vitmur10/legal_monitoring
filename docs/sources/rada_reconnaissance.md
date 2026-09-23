# Rada Source Reconnaissance

Research target: official "Законодавство України" website of the Verkhovna Rada of Ukraine.

Primary test document:

- title: Податковий кодекс України
- legal number: 2755-VI
- stable system number / URL identifier: 2755-17
- canonical URL: https://zakon.rada.gov.ua/laws/show/2755-17
- short redirect URL: https://zakon.rada.gov.ua/go/2755-17

Reference acceptance case:

- Tax Code revision date: 15.04.2026
- basis document: Закон No. 4835-IX
- basis system number: 4835-20

No production `RadaAdapter` was implemented during this research.

## 1. Investigated Endpoints

### Official open-data API / endpoints

Official open-data readme:

- `https://data.rada.gov.ua/ogd/zak/laws/readme.txt`

The readme explicitly documents:

- `http://data.rada.gov.ua/laws/show/{nreg}`
- `http://data.rada.gov.ua/laws/show/{nreg}/ed{YYYYMMDD}`
- `http://data.rada.gov.ua/laws/main/r`
- `http://data.rada.gov.ua/laws/card/{nreg}.json`

Important access rule: API requests require `User-Agent: OpenData` or an `OpenData` cookie. In testing, exact `User-Agent: OpenData` worked; variants like `OpenData/1.0` or suffixes returned 403.

Working structured examples:

- `https://data.rada.gov.ua/laws/card/2755-17.json`
- `https://data.rada.gov.ua/laws/card/2755-17/ed20260415.json`
- `https://data.rada.gov.ua/laws/card/2755-17/ed20261101.json`
- `https://data.rada.gov.ua/laws/card/4835-20.json`
- `https://data.rada.gov.ua/laws/main/r.json`
- `https://data.rada.gov.ua/laws/main/r.xml`
- `https://data.rada.gov.ua/laws/main/r.txt`

Working text examples:

- `https://data.rada.gov.ua/laws/show/2755-17`
- `https://data.rada.gov.ua/laws/show/2755-17/ed20260415`
- `https://data.rada.gov.ua/laws/show/4835-20`

### Public website endpoints

Document:

- `https://zakon.rada.gov.ua/laws/show/2755-17`
- `https://zakon.rada.gov.ua/laws/show/2755-17/ed20260415`
- `https://zakon.rada.gov.ua/laws/show/2755-17/ed20260415/print`

Document card:

- `https://zakon.rada.gov.ua/laws/card/2755-17`
- `https://zakon.rada.gov.ua/laws/card/2755-17/ed20260415`

Document text frame:

- `https://zakon.rada.gov.ua/laws/show/2755-17/ed20260415.frame`

The `.frame` endpoint returned 403 without browser-like context, but worked with browser User-Agent, `Referer`, and `X-Requested-With: XMLHttpRequest`.

New/updated discovery:

- `https://zakon.rada.gov.ua/laws/main/n`
- `https://zakon.rada.gov.ua/laws/main/n.xml`
- `https://zakon.rada.gov.ua/laws/main/n.txt`
- `https://zakon.rada.gov.ua/laws/main/nYYYYMM`
- `https://zakon.rada.gov.ua/laws/main/nYYYYMM.xml`
- `https://zakon.rada.gov.ua/laws/main/nYYYYMM.txt`
- `https://data.rada.gov.ua/laws/main/r.json`

Download/export controls:

- `https://zakon.rada.gov.ua/laws/file/2755-17`
- `https://zakon.rada.gov.ua/laws/file/2755-17/archive`
- `https://zakon.rada.gov.ua/laws/file/2755-17/pdf`
- `https://zakon.rada.gov.ua/laws/file/2755-17/doc`

The website download form posts a `nospam` value derived from cookie `sid`. For MVP automation, prefer API/HTML text endpoints instead of relying on this POST flow.

### Open data bulk datasets

Open-data catalog:

- `https://data.rada.gov.ua/open/data/en-mt/laws`

Dataset pages:

- `https://data.rada.gov.ua/open/data/en-mt/docs`
- `https://data.rada.gov.ua/open/data/en-mt/dict`
- `https://data.rada.gov.ua/open/data/en-mt/proj`

Relevant files discovered:

- `https://data.rada.gov.ua/ogd/zak/laws/data/csv/doc.txt`
- `https://data.rada.gov.ua/ogd/zak/laws/data/csv/doc-dates.txt`
- `https://data.rada.gov.ua/ogd/zak/laws/data/csv/doc-update.txt`
- `https://data.rada.gov.ua/ogd/zak/laws/data/csv/ist.txt`
- `https://data.rada.gov.ua/ogd/zak/laws/data/csv/links.csv`
- `https://data.rada.gov.ua/ogd/zak/laws/data/csv/public.txt`
- `https://data.rada.gov.ua/ogd/zak/laws/data/csv/vidnosh.txt`
- `https://data.rada.gov.ua/ogd/zak/laws/data/csv/podia.txt`
- `https://data.rada.gov.ua/ogd/zak/laws/data/csv/stan.txt`
- `https://data.rada.gov.ua/ogd/zak/laws/data/csv/typ.txt`
- `https://data.rada.gov.ua/ogd/zak/laws/data/csv/org.txt`

Structure files:

- `https://data.rada.gov.ua/ogd/zak/stru/doc-stru.csv`
- `https://data.rada.gov.ua/ogd/zak/stru/ist-stru.csv`
- `https://data.rada.gov.ua/ogd/zak/stru/vidnosh-stru.csv`

The bulk CSV data is useful for later sync jobs, but the first RadaAdapter should start with JSON card + updated/new endpoints to avoid implementing a large bulk importer too early.

## 2. Document Identity Strategy

Concepts should stay separate:

- `external_id`: VRU system number, e.g. `2755-17`.
- `document_number`: legal number displayed to users, e.g. `2755-VI`.
- `dokid`: internal numeric database id from open-data API, e.g. `338198`.
- `canonical_url`: `https://zakon.rada.gov.ua/laws/show/2755-17`.
- `go_url`: `https://zakon.rada.gov.ua/go/2755-17`.

For our core `Document.external_id`, use `nreg` / system number (`2755-17`), not the human legal number (`2755-VI`).

Reasons:

- The official open-data schemas call `nreg` the system document number.
- API and URL patterns are based on `nreg`.
- Legal numbers can repeat across issuers/types or contain roman convocations, while `nreg` is the website/API key.

Store legal number in metadata, e.g. `document_number = 2755-VI`.

## 3. Metadata Availability

Best source: `https://data.rada.gov.ua/laws/card/{nreg}.json` with `User-Agent: OpenData`.

Observed fields for Tax Code `2755-17`:

- `dokid`: `338198`
- `nreg`: `2755-17`
- `nazva`: `Податковий кодекс України`
- `status`: `5`
- `organs`: `1:20101202:2755-VI`
- `types`: `21|1|124`
- `datred`: `20260531`
- `cured`: `0`
- `comped`: `238`
- `edcnt`: `241`
- `pidstava`: `4894-20`
- `poddat`: `20260531`
- `podid`: `0`
- `eds`: list of revisions
- `hist`: parsed event list
- `history`: compact history string
- `links`: compact relation-position/count string

Useful dictionaries:

- status dictionary: `stan.txt`; status `5` means `Чинний`.
- type dictionary: `typ.txt`; for `2755-17`, `21|1|124` means `Кодекс України`, `Закон`, `Кодекс`.
- issuer dictionary: `org.txt`; org `1` means `Верховна Рада України`.
- event dictionary: `podia.txt`; `0` means `Редакція`, `1` means `Набрання чинності`, `4` means `Прийняття`.
- relation dictionary: `vidnosh.txt`.

Field stability:

- `nreg`, `dokid`, `nazva`, `status`, `organs`, `types`, `datred`, `eds`, `hist` are stable structured API fields.
- adoption date and document number are embedded in `organs` as `org_id:YYYYMMDD:number`.
- effective date can be determined from `hist` event `podid=1` for many documents. It is not a single top-level field in the observed payload.
- publication date is available in `publics` for documents where publication records exist, and from `public.txt` bulk data.
- not every document has all metadata; adapters must not invent unavailable values.

## 4. Best Way To Get Document Text

Recommended order:

1. `https://data.rada.gov.ua/laws/show/{nreg}` for current text.
2. `https://data.rada.gov.ua/laws/show/{nreg}/ed{YYYYMMDD}` for specific revision when it returns full text.
3. `https://zakon.rada.gov.ua/laws/show/{nreg}/ed{YYYYMMDD}/print` for full server-rendered print HTML.
4. `.frame` endpoint only as fallback with browser-like headers and referer.

For large documents like the Tax Code:

- normal page for a specific historical edition may contain a placeholder section with `data-load="/laws/show/2755-17/ed20260415.frame"`;
- `print` returns a full HTML document with the legal text in `div id=article`;
- `.frame` returns a full text fragment but may require `Referer` and XHR headers.

Avoid PDF for the MVP if HTML text is available. PDF is worse for deterministic normalization, hashing, version comparison, and future legal diff.

Text extraction recommendation:

- parse `div#article` from `data.rada.gov.ua/laws/show/...` or `/print`;
- remove UI controls, scripts, styles, images, panels;
- preserve paragraph order, headings, article anchors, tables where possible;
- keep source-specific HTML cleanup inside `RadaAdapter.normalize`;
- then pass cleaned text to core deterministic normalization.

## 5. Revision History Mechanism

Best source: JSON card API.

For Tax Code:

- `https://data.rada.gov.ua/laws/card/2755-17.json`
- `edcnt = 241`
- `eds` contains revisions with:
  - `datred`: revision date as `YYYYMMDD`
  - `pidstava`: comma-separated basis `nreg` values
  - `podid`: event type
  - `format`
  - `pages`
  - `size`

Observed 2026 revisions:

- `20260101`, basis `4536-20,4698-20`
- `20260415`, basis `4835-20`
- `20260531`, basis `4894-20`
- `20261101`, basis `3173-20,4115-20,4536-20`

Specific revision URL pattern is stable:

- `https://zakon.rada.gov.ua/laws/show/2755-17/ed20260415`
- `https://data.rada.gov.ua/laws/show/2755-17/ed20260415`

Card API for specific revision also works:

- `https://data.rada.gov.ua/laws/card/2755-17/ed20260415.json`

Observed for `ed20260415`:

- `datred = 20260415`
- `pidstava = 4835-20`
- `cured = 239`

## 6. Current Vs Future Revision Logic

Do not treat max revision date as current.

Use card JSON top-level fields:

- current revision date: top-level `datred` from `card/{nreg}.json`
- current basis: top-level `pidstava`
- current URL: `/laws/show/{nreg}`

Then classify `eds`:

- `ed.datred < current_datred` -> previous revision
- `ed.datred == current_datred` -> current revision
- `ed.datred > current_datred` -> future revision

For Tax Code on 28.08.2026:

- current revision: `31.05.2026`, basis `4894-20`
- future revision: `01.11.2026`, basis `3173-20,4115-20,4536-20`

HTML card confirms this:

- current row has anchor `Current`, class `current-col`, and link text `поточна редакція`;
- future row has anchor `Future`, class `group`, and link text `остання редакція`.

Future revisions must be stored or emitted separately as future-effective source facts, not as current legal text.

## 7. Change Basis Mechanism

Revision basis is explicit and deterministic.

For the Tax Code revision `15.04.2026`:

- card JSON `eds` item has `datred = 20260415`
- `pidstava = 4835-20`
- basis document card `https://data.rada.gov.ua/laws/card/4835-20.json`
- basis legal number from `organs`: `1:20260407:4835-IX`
- basis title: `Про внесення змін до пункту 16-1 підрозділу 10 розділу XX "Перехідні положення" Податкового кодексу України щодо справляння військового збору`
- basis history: `20260407:4` and `20260415:1`

This supports deterministic relation:

- `Law 4835-IX AMENDS Tax Code 2755-VI`
- equivalently in our relation orientation: `4835-20 AMENDS 2755-17`

No AI should infer this relation because VRU provides it explicitly as `pidstava`.

## 8. New-Document Discovery

Recommended sources:

1. `https://data.rada.gov.ua/laws/main/r.json` for updated documents.
2. `https://zakon.rada.gov.ua/laws/main/n.xml` or monthly `nYYYYMM.xml` for new arrivals.
3. `n.txt` / `r.txt` as lightweight id-only fallback.

Observed `r.json` structure:

- `block`: update block number
- `cnt`: item count
- `from`: offset
- `list[]` with `dokid`, `nreg`, `nazva`, `organs`, `orgdat`, `orgnum`, `poddat`, `pridat`, `status`, `typ`, `types`

`r.json` is the best incremental candidate because it exposes an update `block`. Store the last processed block and/or last seen `nreg`/timestamp in source metadata in a future adapter-specific cursor.

`n.xml` gives new arrivals for the last 30 days:

- RSS `item/title`
- `description`
- `link`
- `pubDate`
- `guid` as `nreg`

Monthly archives exist:

- `/laws/main/nYYYYMM`
- `/laws/main/nYYYYMM.xml`
- `/laws/main/nYYYYMM.txt`

Daily archives exist under month pages:

- `/laws/main/nYYYYMMDD`

This avoids scanning the entire VRU base each run.

## 9. Explicit Document Relations

VRU exposes relation taxonomy through `vidnosh.txt`.

Useful deterministic mappings:

- `1 Змінює документ / Змінюється документом` -> `AMENDS` / `AMENDED_BY`
- `2 Спричинив прийняття / Прийнятий на виконання` -> `IMPLEMENTS` or a future `CAUSES_ADOPTION`
- `5 Роз'яснює / Роз'яснюється` -> `EXPLAINS` / `EXPLAINED_BY`
- `6 Відсилає до / Має відсилання з` -> `REFERENCES` / referenced by; current enum can map this to `RELATED_TO` unless schema is extended later
- `10 Затверджує / Затверджується` -> future `APPROVES`
- `11 Пов'язаний з / Пов'язаний з` -> `RELATED_TO`
- `16 Тлумачить / Тлумачиться` -> `EXPLAINS` / `EXPLAINED_BY` or future `INTERPRETS`
- `22 Визнає нечинним / Втрачає чинність` -> `SUPERSEDES` or future `INVALIDATES`
- `25 Припиняє дію / Припиняється дія` -> future `SUSPENDS_OR_TERMINATES`

Relation list endpoints support JSON:

- `https://data.rada.gov.ua/laws/main/l338198p1.json`
- `https://data.rada.gov.ua/laws/main/l338198z1.json`
- `https://data.rada.gov.ua/laws/main/l338198.json`
- `https://data.rada.gov.ua/laws/main/lb338198e0.json`

Here `338198` is `dokid` for Tax Code, and `p1` / `z1` represent direct/reverse relation type 1.

For the first adapter, deterministic relations should be limited to:

- basis-derived `AMENDS`
- explicit relation list type `1`
- explicit explanation/interpretation types `5` and `16`
- generic `RELATED_TO` for type `11`

Do not implement semantic relation inference in the adapter.

## 10. HTTP / Access Limitations

Observed:

- ordinary GET works for public HTML pages with a browser-like User-Agent;
- open-data API requires exact `User-Agent: OpenData` or `OpenData` cookie;
- incorrect API User-Agent can return 403;
- direct old `cgi-bin/laws/main.cgi?...` endpoint returned 403 and should not be used;
- direct `.frame` endpoint may return 403 without `Referer` / XHR context;
- no Cloudflare page or CAPTCHA was observed;
- no CSRF is needed for GET endpoints;
- download POST uses `nospam` and cookie `sid`, so avoid it for MVP automation;
- encoding is `utf-8` for API JSON/HTML/RSS and `windows-1251` for some open-data documentation/CSV structure files;
- `Last-Modified` header is present on some text endpoints;
- be conservative with request rate; use conditional requests if ETag/Last-Modified is available.

Do not bypass anti-DDoS/CAPTCHA if it appears. Back off and log the limitation.

## 11. Tax Code No. 2755-VI Example

Card API:

- `https://data.rada.gov.ua/laws/card/2755-17.json`

Observed fields:

- `dokid = 338198`
- `nreg = 2755-17`
- `nazva = Податковий кодекс України`
- `status = 5` (`Чинний`)
- `organs = 1:20101202:2755-VI`
- `types = 21|1|124`
- `datred = 20260531`
- `edcnt = 241`
- `pidstava = 4894-20`

Canonical document text:

- current: `https://data.rada.gov.ua/laws/show/2755-17`
- current print fallback: `https://zakon.rada.gov.ua/laws/show/2755-17/print`

Specific revision:

- `https://data.rada.gov.ua/laws/card/2755-17/ed20260415.json`
- `https://data.rada.gov.ua/laws/show/2755-17/ed20260415`
- print fallback: `https://zakon.rada.gov.ua/laws/show/2755-17/ed20260415/print`

## 12. Revision 15.04.2026 / Law 4835-IX

Required source data is available.

Old version:

- previous Tax Code revision before 15.04.2026 is `ed20260101`
- basis: `4536-20,4698-20`

New version:

- Tax Code revision `ed20260415`
- basis: `4835-20`

Basis document:

- API card: `https://data.rada.gov.ua/laws/card/4835-20.json`
- text: `https://data.rada.gov.ua/laws/show/4835-20`
- title: `Про внесення змін до пункту 16-1 підрозділу 10 розділу XX "Перехідні положення" Податкового кодексу України щодо справляння військового збору`
- legal number: `4835-IX`
- adoption date: `07.04.2026`
- effective date: `15.04.2026`, from history event `podid=1`

Future system has enough source data for:

- old Tax Code text;
- new Tax Code text;
- basis law text;
- deterministic `AMENDS` relation;
- effective date.

No legal diff was implemented.

## 13. Recommended Future RadaAdapter Architecture

Keep the adapter simple and deterministic:

1. `fetch_items`
   - primary: call `https://data.rada.gov.ua/laws/main/r.json` with `User-Agent: OpenData`;
   - fallback: `n.xml` / monthly `nYYYYMM.xml` for new arrivals;
   - emit `RawDocument` stubs with `external_id = nreg`, `canonical_url`, title, status/type/org/date metadata.

2. `fetch_document`
   - call `https://data.rada.gov.ua/laws/card/{nreg}.json`;
   - determine current revision from top-level `datred`;
   - collect revisions from `eds`;
   - fetch text from `https://data.rada.gov.ua/laws/show/{nreg}` for current or `/edYYYYMMDD` for selected revision;
   - fallback to `/print` when normal endpoint returns only loader/placeholder.

3. `normalize`
   - parse `div#article`;
   - remove scripts/styles/panels/images;
   - preserve headings, paragraphs, tables, and anchor ids;
   - pass cleaned text to core normalization;
   - put source metadata into `NormalizedDocument.metadata`.

4. Relations
   - create deterministic relation candidates from revision `pidstava`;
   - map `pidstava` to `basis_nreg`;
   - later service can create `basis_document AMENDS target_document`;
   - fetch relation-list JSON only when needed, not on every run for every document.

5. Current/future handling
   - never use max `eds.datred` as current;
   - current is top-level `datred`;
   - future revisions are `eds.datred > current_datred`.

6. Cursor
   - store adapter cursor in source-specific metadata in future, e.g. last processed `block` from `r.json`;
   - fallback cursor can use RSS `pubDate` + `guid`.

No DB schema change is required before implementing the first RadaAdapter. Existing `Document.metadata`, `DocumentVersion.metadata`, and `DocumentRelation` are enough for the first deterministic adapter.
