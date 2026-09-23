# ZIR Source Reconnaissance

Date: 2026-08-28

Scope: technical reconnaissance for the official ZIR knowledge base at `zir.tax.gov.ua`. No production `ZirAdapter`, DB schema, migrations, Docker, PostgreSQL, AI, legal diff, Telegram, Notion, Minfin, Playwright, or Selenium work was performed.

The internal Codex compact failure `/backend-api/codex/responses/compact 404 Not Found` was treated as unrelated to this project and unrelated to `zir.tax.gov.ua`.

## 1. Filesystem State

Checked before continuing:

- `docs/sources/zir_reconnaissance.md` did not exist.
- Existing source reconnaissance files were:
  - `docs/sources/dps_reconnaissance.md`
  - `docs/sources/rada_reconnaissance.md`
- Existing local ZIR mentions were only broad future-adapter references in `README.md`.
- The current workspace is not visible as a Git repository from `E:\Проекти\legal_monitoring`; `git status --short` returned `fatal: not a git repository`.

This document was created from the current filesystem/state and from low-rate HTTP reconnaissance.

## 2. Primary Public Pages

Primary pages checked:

- `https://zir.tax.gov.ua/`
- `https://zir.tax.gov.ua/main/bz/search/?src=ques&srch=bz`
- `https://zir.tax.gov.ua/main/bz/view/?src=ques&id=38043`
- `https://zir.tax.gov.ua/main/bz/view/?src=ques&id=33804`
- `https://zir.tax.gov.ua/js/main/bz.js?v=19112021`

Observed:

- Main/search/view pages return browser HTML with `200`.
- Search page sets `PHPSESSID`.
- Root page also sets Akamai/Bot Manager cookies on `.tax.gov.ua`, for example `bm_s` and `bm_so`.
- The JS URL uses `v=19112021`, but the fetched file header says `// 20260531`.
- Page markup loads jQuery 3.7.1 and `bz.js`.

## 3. Core Endpoint Model

The public AJAX endpoint is:

- `POST https://zir.tax.gov.ua/bz/view`

The operation is selected by form field `t`.

Observed public operations from `bz.js`:

- `t=checkSess`
- `t=getResultList`
- `t=getCategoryPath`
- `t=addToResultList`
- `t=getAnswerContent`
- `t=getComments`

Administrative/edit operations also exist in JS under `/bz/edit`, but they are outside public adapter scope:

- `POST /bz/edit`, `t=getBzAddForm`
- `POST /bz/edit`, `t=addNewBZ`
- `POST /bz/edit`, `t=delBz`

## 4. HTTP Requirements

Important behavior:

- A plain `POST /bz/view` without browser/XHR-like context can return a rendered HTML error page with HTTP `200`, not an XML payload.
- Working requests used:
  - prior `GET https://zir.tax.gov.ua/main/bz/search/?src=ques&srch=bz` to establish `PHPSESSID`
  - `Referer: https://zir.tax.gov.ua/main/bz/search/?src=ques&srch=bz`
  - `X-Requested-With: XMLHttpRequest`
  - browser-like `User-Agent`
  - `Content-Type: application/x-www-form-urlencoded; charset=UTF-8`
- The endpoint commonly returns `Content-Type: text/html; charset=utf-8` even when the body is XML-like.
- Do not trust HTTP status alone; inspect body prefix and parseability.

Example error signal from a bad POST:

- status: `200`
- body begins with a full HTML error page, including `\module\defaults\erroor.phtml`

## 5. Search Endpoint

Working search request:

```http
POST /bz/view
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
X-Requested-With: XMLHttpRequest

t=getResultList&
wordsVal=&
srcVal=ques&
themeVal=all&
checkedValue=&
catVal=1&
hrenVal=all&
contVal=cont-no&
statusVal=1&
statusFOP=all&
dateS=&
dateE=
```

Meaning of observed fields:

- `srcVal`: `ques`, `ci`, `glo`
  - `ques`: questions and answers
  - `ci`: documents
  - `glo`: glossary
- `themeVal`: `all`, `1`, `3`, `4`
  - `1`: Оподаткування
  - `3`: Єдиний внесок
  - `4`: Електронні довірчі послуги
- `catVal`: category id; `0` means no selected category.
- `hrenVal`: search area:
  - `ques`: questions
  - `answ`: answers
  - `description`: keywords
  - `all`: everywhere
- `contVal`: `cont-no` or `cont-yes`, controls whether answer content is embedded in search results.
- `statusVal`: `1`, `2`, `all`
  - `1`: Чинні
  - `2`: Не чинні
  - `all`: all statuses
- `statusFOP`: `all`, `u`, `f`, `s`
  - `u`: legal entities
  - `f`: individuals/FOP
  - `s`: self-employed
- `dateS`, `dateE`: dates sent as `YYYY-MM-DD` by current JS.
- `checkedValue`: optional checkbox value; empty when not selected.

Observed response:

- XML-like body:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<body>
  <count>1088</count>
  <content>escaped HTML result rows</content>
</body>
```

For `catVal=1`, `statusVal=1`, `srcVal=ques`, the observed count was `1088`.

Result rows contain:

- stable result id, currently either `row-id="..."` or legacy attributes like `quesid="..."`
- category label in a `div id="cat"`
- title link to `/main/bz/view/?src=ques&id=<id>`
- answer preview in title/content HTML
- status indicator such as `class="actual"` with either current or expired wording

Observed current consultation example:

- ID: `38043`
- URL: `https://zir.tax.gov.ua/main/bz/view/?src=ques&id=38043`
- question: `Які платники ЄП можуть бути платниками ПДВ?`
- category: `101.01 платники податку`
- status search used: `statusVal=1`

## 6. Question / Answer Retrieval

XHR answer request:

```http
POST /bz/view
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
X-Requested-With: XMLHttpRequest

t=getAnswerContent&id=38043&srchWords=&type=ques
```

Observed response:

- status: `200`
- content type: `text/html; charset=utf-8`
- body is an HTML fragment, not JSON.
- It begins with answer text sections such as `Коротка:` and `Повна:`.
- For `type=ques`, the JS expects an optional trailer split by `<br />[` with rating/status counters:
  - total marks
  - mark 1 count
  - mark 2 count
  - mark 3 count
  - internal status flag

Direct canonical view also works:

- `GET /main/bz/view/?src=ques&id=38043`

Observed direct view response:

- full HTML page
- contains the question and answer in `#bz_hide_window_content`
- contains hidden PDF export fields:
  - `expQues`
  - `expAnsw`
- form action: `/main/bz/exporttopdf/`

Recommendation:

- Prefer direct `GET /main/bz/view/?src=ques&id=<id>` for stable canonical URL and complete HTML fallback.
- Use `POST /bz/view` with `t=getAnswerContent` when replicating the UI behavior or when only the answer fragment is needed.
- Normalize both paths through the same parser.

## 7. Stable Consultation ID

Stable ID candidate:

- numeric `id` from `/main/bz/view/?src=ques&id=<id>`
- result row attribute `row-id`, `quesid`, `ciid`, or equivalent typed id

Examples:

- current: `38043`
- non-current: `33804`

Suggested adapter key:

- source: `zir`
- external_id: `<src>:<id>`, for example `ques:38043`
- canonical_url: `https://zir.tax.gov.ua/main/bz/view/?src=ques&id=38043`

The `src` component should be included because JS supports multiple source types (`ques`, `ci`, `glo`).

## 8. Category Structure

Top-level categories are embedded in the search page and can also be requested through:

```http
POST /bz/view

t=getCategoryPath&catId=1
```

Observed response:

- HTML fragment of one or more `<select id="srch_cat">` controls.
- First select includes top-level categories.
- Subsequent select includes child categories for the selected id.

Example top-level category IDs:

- `1`: `101. Податок на додану вартість`
- `62`: `102. Податок на прибуток підприємств`
- `102`: `103. Податок на доходи фізичних осіб`
- `181`: `107. Єдиний податок для фізичних осіб - підприємців (спрощена система оподаткування)`
- `214`: `109. Порядок застосування РРО та/або ПРРО`
- `582`: `201. Єдиний внесок на загальнообов’язкове державне соціальне страхування`
- `601`: `301. Електронні довірчі послуги`

Example children for `catId=1`:

- `4709`: `101.01 платники податку`
- `4710`: `101.02 реєстрація осіб платниками податку`
- `4711`: `101.03 анулювання реєстрації платників податків`
- `4712`: `101.04 об’єкт оподаткування`
- `4713`: `101.05 визначення місця постачання товарів та послуг`

Recommendation:

- Build a category crawler from `getCategoryPath`.
- Parse option text into `code` and `title` when it starts with a numeric code.
- Preserve raw `cat_id`, label, and parent chain because IDs are server-specific.

## 9. Pagination / Incremental Loading

Pagination is not exposed as a clear `page=N` parameter in `bz.js`.

UI function:

```http
POST /bz/view

t=addToResultList&srchWords=<current search box value>
```

Observed behavior:

- Must follow an initial `t=getResultList` in the same session.
- Server appears to keep result-list state in PHP session.
- Response is XML-like and contains additional escaped HTML rows in `<content>`.
- There is no explicit count in the observed `addToResultList` response.
- Observed additional rows after an initial `catVal=1`, `statusVal=1` search included ID `35130`.

Adapter implication:

- Incremental crawling through `addToResultList` is session-stateful and less robust than page-numbered APIs.
- For a future adapter, use short-lived sessions and bounded page loading.
- Persist discovered IDs and re-fetch by canonical URL for verification.
- Avoid large unbounded category-wide scans during normal polling.

## 10. Existing Consultation Update Detection

No explicit "updated since" endpoint was found in `bz.js`.

Recommended strategy:

1. Discover IDs by category/status/date/search filters.
2. Fetch each known canonical view URL.
3. Extract normalized fields:
   - question
   - short answer
   - full answer
   - category code/title
   - status text
   - effective/end-date text when present
   - normative references
   - comment text
4. Compute content hash from normalized semantic fields, not raw HTML.
5. Store first_seen_at, last_seen_at, last_checked_at, content_hash, status.
6. Detect:
   - content changed: same `src:id`, different hash
   - archived/non-current: status changed or answer/title contains `Діяло до`, `Діяла до`, `Втратила чинність`
   - disappeared/error: repeated fetch failures, not one-off HTTP/body errors

## 11. Revision / History

No public revision/history endpoint was identified in `bz.js` or tested public pages.

The site exposes current and non-current consultations as separate queryable states via `statusVal`, but no per-ID revision list was observed.

Recommendation:

- Treat ZIR as snapshot-only.
- Maintain local history from repeated canonical fetches.
- Link archived/current relationships heuristically only when titles/questions and categories strongly match; do not assume the site provides a durable predecessor/successor relation.

## 12. Archive / Status

Status filter:

- `statusVal=1`: current
- `statusVal=2`: non-current
- `statusVal=all`: all

Confirmed non-current example:

- ID: `33804`
- URL: `https://zir.tax.gov.ua/main/bz/view/?src=ques&id=33804`
- search response status visual: `Втратила чинність`
- question prefix: `Діяло до 23.05.2020`
- answer prefix: `Діяла до 23.05.2020`
- comment says the Q&A was moved to non-current due to Law of Ukraine No. 466-IX dated 2020-01-16.

For `catVal=1`, `statusVal=2`, `srcVal=ques`, observed count was `1422`.

## 13. Normative References

Normative references are embedded in answer text, not separately structured in the observed public responses.

Examples found in tested records:

- Tax Code of Ukraine No. 2755-VI dated 2010-12-02.
- Specific Tax Code articles and paragraphs, for example `п. 180.1 ст. 180`, `п. 181.1 ст. 181`, `п. 293.3 ст. 293`.
- Law of Ukraine No. 466-IX dated 2020-01-16 in an archived consultation comment.

Recommendation:

- Extract normative references with a post-parser over normalized answer/comment text.
- Keep raw text snippets around references for reviewer context.
- Do not rely on dedicated structured fields unless later reconnaissance finds them.

## 14. Anti-Bot / Rate Limits

Observed low-rate behavior:

- Browser-like GETs and XHR-style POSTs worked.
- Root response set Akamai/Bot Manager cookies (`bm_s`, `bm_so`) on `.tax.gov.ua`.
- Search page set `PHPSESSID`.
- Failed/malformed AJAX-like calls can return HTML error with status `200`.

No CAPTCHA or hard block was encountered during this low-rate run.

Adapter caution:

- Use low concurrency.
- Reuse a session for a short crawl batch.
- Send realistic headers.
- Add body validation and retry classification.
- Do not treat `200` as success until the expected XML/HTML fragment shape is confirmed.

## 15. Recommendation For Future ZirAdapter

Suggested approach:

1. Start with `GET /main/bz/search/?src=ques&srch=bz` to initialize cookies and parse filter metadata.
2. Crawl category tree via `t=getCategoryPath`.
3. Discover IDs with bounded `t=getResultList` searches by category/status/date.
4. Use `statusVal=1` for current monitoring and periodic `statusVal=2` sampling for archive detection.
5. Use same-session `t=addToResultList` only for bounded pagination after a search.
6. Fetch canonical detail pages by `GET /main/bz/view/?src=<src>&id=<id>`.
7. Parse and normalize:
   - `external_id`
   - `canonical_url`
   - `src`
   - category path/code/title
   - question/title
   - short answer
   - full answer
   - status text
   - effective end date if present
   - comments
   - normative references
8. Detect updates by normalized content hash per `src:id`.
9. Maintain local revision history because no official history endpoint was found.

Complexity estimate: `MEDIUM`.

Reasons:

- The public surface is accessible and mostly stable.
- The endpoint model is simple.
- Pagination is session-stateful.
- Responses are XML-like with escaped HTML fragments and inconsistent content types.
- Archive/update semantics require text/status normalization rather than a clean structured API.

## 16. Open Questions

- Whether `src=ci` document records have a different stable ID shape and whether `/main/bz/export/?id=<id>` is the best retrieval path for documents.
- Whether `src=glo` glossary records use `getAnswerContent` with a different `type`.
- Whether date filters are based on publication, last update, or consultation creation date.
- Whether there is an undiscovered internal endpoint for full revision history.
- Whether `addToResultList` has an implicit server-side page size that changes by category or source type.
