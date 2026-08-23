---
title: Thoughts Implementation and Test Plan
date: 2026-08-23
status: draft
tags:
  - plan
  - implementation
  - testing
related:
  - "[[0001-sqlite-canonical-markdown-projection]]"
  - "[[2026-08-23-design-review]]"
---

# Thoughts Implementation and Test Plan

## Goal

Build the first useful version of Thoughts as a local-first Python CLI where SQLite is canonical and Markdown files are Obsidian-readable projections.

The first implementation should prove durable capture, schema enforcement, projection export, sync validation, and repair diagnostics before adding LLM processing, embeddings, synthesis, or lifecycle automation.

## Non-Goals for the First Milestone

- No LLM classification.
- No embeddings or vector search.
- No automatic concept/entity/digest generation.
- No calendar or mobile integration.
- No Postgres backend.
- No background watcher.
- No destructive sync from Markdown deletion to SQLite.

These are deliberately deferred until the core data boundary is boring and reliable.

## Architecture Commitments

1. SQLite is the canonical data store.
2. Markdown is a projection that can be regenerated.
3. Obsidian edits are allowed but must pass validation before import.
4. Stable IDs, not paths or titles, identify records.
5. All writes to canonical state happen through transactions.
6. Tool-owned generated Markdown sections are fenced.
7. Invalid user edits produce reviewable diagnostics, not partial imports.

## Proposed Repository Shape

```text
.
|-- README.md
|-- pyproject.toml
|-- src/
|   `-- thoughts/
|       |-- __init__.py
|       |-- cli.py
|       |-- db.py
|       |-- ids.py
|       |-- markdown.py
|       |-- migrations.py
|       |-- models.py
|       |-- paths.py
|       |-- sync.py
|       `-- doctor.py
|-- tests/
|   |-- fixtures/
|   |-- test_cli.py
|   |-- test_db.py
|   |-- test_markdown_export.py
|   |-- test_sync.py
|   `-- test_doctor.py
|-- docs/
|   |-- adr/
|   |-- design/
|   |-- plans/
|   `-- reviews/
|-- tasks/
`-- bases/
```

Keep implementation code under `src/thoughts/`. Keep generated runtime data under `.thoughts/`, which is already ignored.

## Canonical Data Model

### Tables for Milestone 1

```sql
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE thoughts (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('inbox', 'task', 'note', 'idea')),
    status TEXT NOT NULL CHECK (status IN ('active', 'done', 'archived', 'superseded', 'flagged')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    due_on TEXT,
    priority TEXT CHECK (priority IN ('low', 'medium', 'high') OR priority IS NULL),
    source TEXT NOT NULL DEFAULT 'cli',
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE thought_tags (
    thought_id TEXT NOT NULL REFERENCES thoughts(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (thought_id, tag)
);

CREATE TABLE markdown_projections (
    thought_id TEXT PRIMARY KEY REFERENCES thoughts(id) ON DELETE CASCADE,
    path TEXT NOT NULL UNIQUE,
    last_exported_at TEXT NOT NULL,
    last_exported_hash TEXT NOT NULL,
    last_seen_hash TEXT
);

CREATE TABLE sync_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thought_id TEXT REFERENCES thoughts(id),
    path TEXT,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    message TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    resolved_at TEXT
);
```

### Deferred Tables

- Embeddings.
- Entity mentions.
- Generated concepts/entities/digests.
- Processing logs for LLM calls.
- Supersession and duplicate detection tables.

Do not add these until the command that needs them exists.

## Markdown Projection Contract

Each exported note should contain a stable frontmatter envelope and a human-editable body.

```yaml
---
id: th_01K3...
title: Buy groceries
type: task
status: active
due: 2026-08-25
priority: medium
tags:
  - shopping
schema_version: 1
last_exported_hash: ...
---
```

Generated sections must be fenced:

```markdown
<!-- thoughts:begin generated-summary -->
Generated text.
<!-- thoughts:end generated-summary -->
```

Milestone 1 should not generate body summaries yet, but the exporter should preserve fenced-section boundaries once they exist.

## Command Plan

### `thoughts init`

Creates `.thoughts/thoughts.sqlite`, applies migrations, and creates projection folders.

Acceptance criteria:

- Idempotent on an initialized repo.
- Fails clearly if the database path is not writable.
- Enables SQLite foreign keys.
- Records applied migrations.

### `thoughts capture "text"`

Creates one canonical thought record.

Acceptance criteria:

- Generates a stable ID.
- Writes a single SQLite transaction.
- Defaults to `type = inbox` and `status = active`.
- Supports optional `--title`, `--tag`, `--type`, `--due`, and `--priority`.
- Does not require Obsidian or Markdown export to succeed.

### `thoughts export-md`

Exports canonical records to Markdown projections.

Acceptance criteria:

- Creates deterministic paths from ID plus slug.
- Writes frontmatter in stable order.
- Preserves human-authored body content already stored in SQLite.
- Updates `markdown_projections`.
- Does not overwrite an externally modified Markdown file without detecting drift.

### `thoughts sync --check`

Reads projected Markdown files and reports importable changes or validation failures.

Acceptance criteria:

- Matches records by `id`.
- Detects missing IDs, duplicate IDs, invalid enum values, malformed dates, and changed hashes.
- Reports what would change without mutating SQLite.
- Does not treat deleted Markdown as database deletion.

### `thoughts sync --apply`

Imports valid Markdown edits into SQLite.

Implementation choice: apply mode uses one all-or-nothing transaction per run for canonical thought updates. If any projected file has a validation error, no canonical thought rows are updated; blocking issues are recorded in `sync_issues` for review.

Acceptance criteria:

- Imports only validated fields.
- Writes invalid files to `sync_issues`.
- Uses one transaction per file or one all-or-nothing transaction per run; choose and document the behavior before implementation.
- Re-exports normalized Markdown after successful import.

### `thoughts status`

Reports database and projection health.

Acceptance criteria:

- Shows total thought count.
- Shows counts by type and status.
- Shows projection count.
- Shows unresolved sync issue count.
- Shows latest migration version.

### `thoughts doctor`

Runs consistency checks.

Acceptance criteria:

- Detects missing projection rows.
- Detects projection files missing on disk.
- Detects duplicate Markdown IDs.
- Detects orphaned projection rows.
- Detects invalid frontmatter.
- Returns non-zero for errors.

## Milestones

### Milestone 0: Project Skeleton

Deliverables:

- `pyproject.toml`.
- `src/thoughts/` package.
- `thoughts` CLI entrypoint.
- Ruff, mypy, pytest configuration.
- Initial test fixtures.

Tests:

- CLI help renders.
- Package imports.
- Formatting/lint/type gates run.

Exit criteria:

- `python -m pytest` passes.
- `python -m ruff check .` passes.
- `python -m mypy src` passes.
- `git diff --check` passes.

### Milestone 1: Canonical Store

Deliverables:

- Migration runner.
- Initial SQLite schema.
- Stable ID generation.
- `init`.
- `capture`.
- `status`.

Tests:

- Fresh database initializes.
- Repeated init is idempotent.
- Foreign keys are enabled.
- Invalid enum values are rejected.
- Capture creates a valid record and tags.
- Capture rollback leaves no partial tag rows.

Exit criteria:

- A user can create and inspect canonical records without Markdown.

### Milestone 2: Markdown Export

Deliverables:

- Markdown serializer.
- Stable frontmatter ordering.
- Slug/path generation.
- `export-md`.
- Projection hash tracking.

Tests:

- Exported Markdown parses as YAML.
- Export is deterministic.
- Title changes produce predictable paths or documented path stability.
- Existing externally modified file is not overwritten silently.
- Tags round-trip in normalized form.

Exit criteria:

- SQLite can generate an Obsidian-browsable projection.

### Milestone 3: Sync Validation

Deliverables:

- Markdown parser.
- Field validator.
- `sync --check`.
- `sync --apply`.
- `sync_issues` writing.

Tests:

- Valid title/body/status/tag edits import.
- Invalid status is rejected.
- Duplicate IDs are rejected.
- Missing ID is rejected.
- Malformed YAML is rejected.
- Markdown deletion is reported but does not delete database rows.
- Apply mode is transactional.

Exit criteria:

- Obsidian edits can be safely imported or quarantined.

### Milestone 4: Doctor and Repair

Deliverables:

- `doctor`.
- Structured diagnostics.
- Suggested repair messages.

Tests:

- Missing projection detected.
- Orphaned projection row detected.
- Duplicate Markdown ID detected.
- Hash drift detected.
- Command exit codes distinguish clean, warning, and error states.

Exit criteria:

- A user can tell whether the repo, database, and Markdown projection agree.

### Milestone 5: Reviewed LLM Classification

Deliverables:

- LLM abstraction.
- Strict JSON schema for classifier output.
- `process --dry-run`.
- `process --apply`.
- Confidence and review behavior.

Tests:

- Mock model outputs are validated.
- Invalid JSON is rejected.
- Unknown enum values are rejected.
- Low confidence creates a review issue instead of updating canonical state.
- Dry-run does not mutate SQLite.
- Apply mutates only approved canonical fields.

Exit criteria:

- Model output can propose useful metadata without becoming an unchecked writer.

### Milestone 6: Search

Deliverables:

- Full-text search using SQLite FTS.
- Embedding metadata tables.
- Optional vector index.
- `search`.

Tests:

- FTS search returns expected records.
- Embedding rows include provider, model, dimension, content hash, and timestamp.
- Model dimension mismatch is detected before querying.
- Re-embedding only updates stale records unless forced.

Exit criteria:

- Search works without compromising canonical data integrity.

## Test Strategy

### Unit Tests

Focus on pure behavior:

- ID generation.
- Slug generation.
- Date parsing.
- Tag normalization.
- Frontmatter serialization.
- Frontmatter validation.
- Migration ordering.
- Hash calculation.

### Integration Tests

Use temporary directories and real SQLite files:

- `init -> capture -> export-md -> sync --check`.
- Manual Markdown edit -> `sync --apply` -> normalized export.
- Invalid Markdown edit -> `sync --check` reports issue -> database unchanged.
- Deleted Markdown file -> `doctor` reports projection drift -> database unchanged.

### CLI Tests

Exercise the installed command surface:

- Help output.
- JSON output if added.
- Exit codes.
- Error messages for invalid options.
- Commands run from vault root and from subdirectories.

### Golden File Tests

Use fixture snapshots for exported Markdown.

Golden files should cover:

- Inbox thought.
- Task with due date and priority.
- Note with multiple tags.
- Body with YAML-looking text.
- Body with fenced generated section.

### Property and Fuzz Tests

Add after the parser stabilizes:

- Random tag lists normalize without invalid YAML.
- Random titles produce safe paths.
- Markdown export/import round-trips for allowed fields.
- Body text containing `---`, colons, brackets, and HTML comments survives export/import.

### Adversarial Regression Tests

Create explicit tests for the design-review failure cases:

1. Renamed Markdown path still maps by ID.
2. Duplicate Markdown IDs are rejected.
3. Invalid YAML does not mutate SQLite.
4. External edits are not overwritten silently.
5. Deleted Markdown does not delete canonical rows.
6. Date strings are timezone/date-normalized predictably.
7. Invalid enum values cannot enter canonical state.
8. Generated fenced sections do not erase human sections.

## Validation Gate

Use this gate before commits:

```bash
python -m pytest
python -m ruff check .
python -m mypy src
git diff --check
```

For documentation-only commits before implementation exists:

```bash
git diff --check
python3 -m json.tool docs/adr/adr.schema.json >/dev/null
```

## Implementation Order

1. Create the Python package skeleton and test harness.
2. Implement migrations and schema.
3. Implement IDs and canonical capture.
4. Implement status.
5. Implement Markdown export.
6. Implement sync check.
7. Implement sync apply.
8. Implement doctor.
9. Add LLM processing only after sync and doctor are reliable.
10. Add search only after canonical body updates and projection hashes are stable.

## Key Open Decisions

1. Should `sync --apply` use one transaction for the whole run or one transaction per file?
2. Should Markdown path slugs update when titles change, or should paths stay stable after first export?
3. Which fields are user-editable from Markdown in Milestone 1?
4. Should capture require a title or derive one from the first line/body?
5. What backup policy protects `.thoughts/thoughts.sqlite` now that it is canonical?

Resolve these with ADRs if they materially constrain implementation.
