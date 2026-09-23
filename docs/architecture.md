# Architecture

This document describes the original Stage 1 foundation. Stage 2–4 are now implemented;
the current moderation and knowledge-base workflow is documented in [stage4.md](stage4.md).

## Pipeline Boundary

Current implemented pipeline:

SourceAdapter -> RawDocument -> NormalizedDocument -> DocumentIdentity -> Versioning -> ProcessingResult -> MonitoringRun

Future pipeline:

Diff -> relevance filtering -> AI analysis -> approval -> Telegram publication -> Notion publication -> history.

The future sections below describe the historical design, not the current implementation.

## Source-Specific Logic

Source adapters own all source-specific behavior:

- HTTP/API/scraping details in future adapters.
- Source-specific item discovery.
- Source-specific document fetch.
- Source-specific HTML cleanup before core normalization.

The core system does not know CSS selectors, site routes, or source-specific page structures.

Adding `RadaAdapter`, `TaxGovAdapter`, `ZirAdapter`, `MinfinAdapter`, or `EurLexAdapter` should only require registering the adapter in `SourceRegistry`. `MonitoringService` must not receive `if source == ...` branches.

## Core Business Logic

Core business logic starts at `NormalizedDocument`.

`DocumentIdentityService` decides document identity:

1. `source + external_id`
2. `source + canonical_url`
3. conservative fallback based on source, title, type, published date, and content hash

Fallback includes content hash to avoid accidentally merging unrelated documents. This may create separate documents for unstable sources, but it is safer than false merges for legal content.

`VersioningService` owns deduplication:

- no existing document -> create `Document` and immutable `DocumentVersion #1` -> `NEW`
- same hash as current version -> update `last_seen_at` only -> `UNCHANGED`
- different hash -> create next immutable version -> `CHANGED`

## Database Integrity

Important constraints:

- `sources.code` is unique.
- `documents(source_id, identity_key)` is unique.
- `documents(source_id, external_id)` and `documents(source_id, canonical_url)` are unique when values exist.
- `document_versions(document_id, version_number)` is unique.
- `document_versions(document_id, content_hash)` is unique.
- relation edges are unique by `from_document_id`, `to_document_id`, and `relation_type`.

PostgreSQL row-level locking with `SELECT ... FOR UPDATE` protects existing document updates. Unique constraints protect concurrent creation and duplicate version insertion.

## Document Relations

`DocumentRelation` stores directed edges between documents:

- `AMENDS`
- `AMENDED_BY`
- `EXPLAINS`
- `EXPLAINED_BY`
- `IMPLEMENTS`
- `IMPLEMENTED_BY`
- `RELATED_TO`
- `SUPERSEDES`
- `SUPERSEDED_BY`

The MVP stores only the edge explicitly created. It does not automatically create inverse relations and does not infer relations semantically.

This supports future chains like:

Minfin Order #249 -> amended by Order #293 -> explained by Tax Authority letter.

## Topics

Separate `Topic` and `DocumentTopic` tables are intentionally not implemented in this step. Without AI classification, manual UI, or stable taxonomy workflow, separate tables would add operational cost too early.

Current extension point: `NormalizedDocument.metadata`. A future AI classification stage can introduce normalized topic tables when there is a clear use case for filtering, analytics, or publication rules.

## Future Relevance Filter

The future AI stage should treat material as relevant only if it:

- creates a rule;
- changes a rule;
- explains a rule;
- changes an official position;
- may lead to a rule change;
- affects a company's tax or accounting process.

Noise should be filtered out unless it contains a normative change or important official position:

- tax collection statistics;
- greetings;
- HR news;
- organizational announcements;
- meeting results.

## Future Approval And Publication

Future workflow:

AI generated content -> private Telegram approval group -> Approve/Edit/Reject.

On approval:

- short text goes to Telegram channel;
- long article goes to Notion Knowledge Base.

Notion fields like `notion_page_id`, `notion_page_url`, and `published_at` should likely belong to a future `Publication` model, not core `Document`.
