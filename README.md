# Legal Monitoring MVP

AI-ready foundation for monitoring changes in Ukrainian tax, accounting, and related legislation.

Current MVP implements source abstraction, normalized documents, document identity, deduplication, immutable version history, deterministic explicit document relations, monitoring run history, a simple scheduler foundation, internal FastAPI endpoints, the Stage 2 diff + AI analysis pipeline, and the Stage 3 Telegram approval/publication workflow.

It intentionally does not implement Playwright/Selenium, embeddings/RAG, semantic inferred linking, Notion API, frontend/admin UI, or production deployment.

## Architecture

Core flow:

`SourceAdapter -> RawDocument -> NormalizedDocument -> DocumentIdentity -> Versioning -> ProcessingResult -> MonitoringRun`

The source adapter boundary owns source-specific fetch/cleanup. Core services work only with `NormalizedDocument`, so future adapters like `RadaAdapter`, `TaxGovAdapter`, `ZirAdapter`, `MinfinAdapter`, and `EurLexAdapter` can be registered without changing `MonitoringService`.

Stage 2 flow:

`DocumentVersion change -> deterministic diff -> AI relevance filter -> AI full analysis -> version metadata audit`

Stage 3 flow:

`Generated content -> moderation group -> approve/revise/reject -> Telegram channel`

See [docs/architecture.md](docs/architecture.md).

## Project Structure

```text
app/
  api/routes/
  core/
  db/
  models/
  repositories/
  schemas/
  services/
  sources/
  monitoring/
  utils/
alembic/
docs/
scripts/
tests/
```

## Prerequisites

- Python 3.12+
- Docker for local PostgreSQL

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[test]
Copy-Item .env.example .env
```

Start PostgreSQL:

```powershell
docker compose up -d postgres
```

Run migrations:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

The Compose PostgreSQL service is exposed on host port `55432` to avoid conflicts with a locally installed PostgreSQL on `5432`.

Seed local sources:

```powershell
.\.venv\Scripts\python.exe scripts\seed_sources.py
```

Run API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Swagger is available at `/docs`.

## API Endpoints

- `GET /health`
- `GET /sources`
- `GET /sources/{id}`
- `POST /sources/{id}/run`
- `GET /monitoring/runs`
- `GET /documents`
- `GET /documents/{id}`
- `GET /documents/{id}/versions`
- `GET /documents/{id}/relations`
- `POST /documents/{id}/relations`

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Tests cover:

- `NEW`, `UNCHANGED`, `CHANGED`
- no duplicate document for the same external ID
- deterministic normalization and hashing
- deterministic diff blocks
- AI provider-independent relevance filtering
- full analysis schema validation
- Stage 2 pipeline metadata persistence
- `FILTERED_OUT`, `AI_FAILED`, and token-limit handling
- adapter item error does not stop the run
- monitoring counters
- relation creation and chain fetching
- concurrent duplicate/version scenario
- disabled source is not scheduled

PostgreSQL-specific tests are skipped unless `TEST_DATABASE_URL` is set.

## Mock Demo

Without real scraping:

```powershell
$env:DATABASE_URL='sqlite+aiosqlite:///./mock_demo.sqlite'
.\.venv\Scripts\python.exe scripts\mock_demo.py
```

Expected sequence:

```text
RUN #1: NEW
RUN #2: UNCHANGED
RUN #3: CHANGED
```

The same script also creates a manual chain:

`Order 293 AMENDS Order 249`, then `Tax Authority explanation EXPLAINS Order 293`.

## Stage 2 Diff + AI Analysis

Stage 2 is enabled automatically when `AI_API_KEY` is configured. The API key is read only from environment/settings and must not be committed or logged.

Relevant settings:

```text
AI_API_KEY=
AI_ENABLED=true
AI_MODEL_RELEVANCE=gpt-4o-mini
AI_MODEL_ANALYSIS=gpt-4o
AI_BASE_URL=https://api.openai.com/v1
AI_TIMEOUT_SECONDS=60
AI_MAX_RETRIES=2
AI_RELEVANCE_MAX_INPUT_CHARS=24000
AI_ANALYSIS_MAX_INPUT_CHARS=36000
AI_RELEVANCE_MAX_OUTPUT_TOKENS=800
AI_ANALYSIS_MAX_OUTPUT_TOKENS=2200
AI_MAX_TOTAL_TOKENS_PER_DOCUMENT=
```

For `NEW` versions, Stage 2 sends the normalized text to the relevance filter, then to full analysis if relevant.

For `CHANGED` versions, Stage 2 first builds a deterministic block diff and sends the structured before/after changes to analysis.

For `UNCHANGED` and `FAILED`, Stage 2 is skipped.

Stage 2 result is stored in `DocumentVersion.version_metadata["stage2"]` with:

- `status`: `ANALYZED`, `FILTERED_OUT`, `AI_FAILED`, `NO_MEANINGFUL_CHANGE`, or `TOKEN_LIMIT_EXCEEDED`
- `analyzed_at`
- prompt versions
- deterministic diff
- relevance decision
- full analysis, when applicable
- usage metadata
- error metadata, when applicable

Run the provider-independent acceptance demo:

```powershell
.\.venv\Scripts\python.exe scripts\stage2_acceptance_demo.py
```

Run a live AI smoke only when external API use and token cost are acceptable:

```powershell
.\.venv\Scripts\python.exe scripts\ai_live_smoke.py
```

## Scheduler

Set `SCHEDULER_ENABLED=true` to start APScheduler with the FastAPI app. It schedules only enabled DB sources that have a registered adapter. Manual runs remain available through `POST /sources/{id}/run`.

## Stage 3 Telegram Approval

Create a test bot, add it to a closed moderation group and as an administrator of the test publication channel. Configure `.env`:

```text
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=your_test_bot_token
TELEGRAM_MODERATION_CHAT_ID=-100...
TELEGRAM_PUBLICATION_CHANNEL_ID=@your_test_channel
TELEGRAM_ALLOWED_USER_IDS=123456789
TELEGRAM_WEBHOOK_SECRET=optional_random_secret
```

`TELEGRAM_ALLOWED_USER_IDS` accepts comma-separated numeric Telegram user IDs. Users outside this list cannot approve, revise, or reject content.

For local testing without a public webhook, run the API and the polling worker in separate terminals:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
.\.venv\Scripts\python.exe scripts\telegram_bot.py
```

When only `TELEGRAM_ENABLED=true` and `TELEGRAM_BOT_TOKEN` are configured, the
polling worker starts in discovery mode. Add the bot to the test group and send `/chatid`
to receive that group's numeric ID. Send `/myid` to receive your own Telegram user ID.
After filling the remaining settings, restart the worker to enable the full workflow.

Relevant analyzed documents are sent to the moderation group automatically. A specific existing version can be sent from Swagger with `POST /review/items/{version_id}/dispatch`.

The moderation card has `Погодити`, `Виправити`, `Відхилити`, and `Повна стаття` buttons. Approval publishes the short post followed by the full article to the configured channel. Revision waits for the reviewer's next text message, regenerates both content formats with AI, stores a new content version, and sends it for review again. Publication failures remain retryable per message, and repeated approval does not create duplicate channel posts.

For deployment with a public HTTPS endpoint, point the Telegram webhook to `POST /review/telegram/webhook` and pass `TELEGRAM_WEBHOOK_SECRET` as Telegram's secret token.

## Adding A SourceAdapter

Implement `SourceAdapter` from `app/sources/base.py`:

- `source_code`
- `fetch_items`
- optional `fetch_document`
- `normalize`

Then register it in `SourceRegistry`. Do not add source-specific branching to `MonitoringService`.

## Not Implemented Yet

- Playwright, Selenium, proxies
- embeddings, vector DB, RAG
- semantic inferred document linking
- Notion API or pages
- frontend/admin panel
- production deployment
