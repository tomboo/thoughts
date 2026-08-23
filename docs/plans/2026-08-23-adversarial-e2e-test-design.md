---
title: Adversarial End-to-End Test Design
created: 2026-08-23
status: draft
related:
  - "[[2026-08-23-design-review]]"
  - "[[2026-08-23-implementation-and-test-plan]]"
---

# Adversarial End-to-End Test Design

This plan translates the adversarial scenarios from the design review into end-to-end tests for the current SQLite-canonical design.

The current implementation has:

- SQLite as canonical state.
- Markdown as a projection.
- `init`, `capture`, `export-md`, `sync`, `doctor`, `process`, and `search`.
- Reviewed classifier output with confidence gates.
- FTS and embedding metadata.

It does not yet have:

- `reindex`.
- `synthesize`.
- generated concept pages.
- durable `processing_log`.
- task checkbox parsing.
- real external LLM calls.

## Applicability Matrix

| Scenario | Applies now? | Current answer | E2E test status |
|---|---:|---|---|
| 1. User renames a processed note in Obsidian, then runs `reindex`. | Partial | There is no `reindex`; `sync` and `doctor` can still reason by frontmatter ID inside managed folders. | Design now for rename-through-sync; defer reindex rebuild test. |
| 2. Two notes accidentally receive the same frontmatter ID. | Yes | `sync --check`, `sync --apply`, and `doctor` reject duplicates. | Add command-level E2E coverage. |
| 3. LLM extracts "tomorrow" as a due date across a midnight run. | Partial | Classifier schema accepts only ISO dates; relative dates are rejected if passed through as `"tomorrow"`. No real LLM prompt/date normalization exists. | Add E2E rejection test now; defer prompt/timezone test. |
| 4. Note says "do not buy milk" and classifier creates a shopping task. | Yes | High-confidence classifier output can update type/status/due/priority/tags, so semantic mistakes must be caught by confidence/review policy or future approval UI. | Add E2E showing low confidence is quarantined; add future approval-review test. |
| 5. Capture has invalid YAML because raw text starts with `---`. | Yes | Capture writes SQLite body first; export serializes body below generated frontmatter. | Add capture/export/sync round-trip E2E. |
| 6. File is changed on mobile while `thoughts process` is running. | Yes | `process` updates SQLite only and does not write Markdown projections, so it should not overwrite mobile Markdown edits. | Add E2E proving external Markdown edit survives process. |
| 7. Embedding model changes dimension after dependency upgrade. | Yes | Embedding metadata is provider/model/dimension-specific; same provider/model with different dimension is rejected. | Already has integration coverage; add CLI/E2E once embedding command exists. |
| 8. User manually edits a generated concept page, then runs `synthesize`. | No | No synthesize or generated concept pages exist. | Defer until synthesize milestone. |
| 9. Completed task is marked with checkbox but frontmatter still says `active`. | Partial | No checkbox parser exists; canonical status comes from frontmatter/SQLite. | Add future task-body parser test before checkbox sync support. |
| 10. Reindex drops `processing_log`; user expected audit trail. | No | No `reindex` or durable `processing_log` exists. | Defer until processing log semantics are decided. |

## Current E2E Test Suite Additions

These tests should live in a command-level file such as `tests/test_adversarial_e2e.py`. They should use `tmp_path` with a real SQLite file and call `thoughts.cli.run` so they exercise the public command surface.

### E2E-001: Renamed Projection Still Syncs By ID

Purpose: prove path changes inside managed projection folders do not break identity.

Steps:

1. Run `init`.
2. Run `capture "Original body" --title "Original title"`.
3. Run `export-md`.
4. Rename the generated `Inbox/<id>-original-title.md` file to `Inbox/renamed-by-user.md`.
5. Edit frontmatter `title` to `"Renamed title"` and body to `"Renamed body\n"`.
6. Run `sync --check`.
7. Run `sync --apply`.
8. Open SQLite and load the thought by the original ID.

Expected:

- `sync --check` reports one update and no errors.
- `sync --apply` applies one update.
- SQLite row with the original ID has the edited title and body.
- No second thought row is created.

Important gap:

- This does not test `reindex`; when `reindex` exists, add a variant that rebuilds derived state from the renamed file without changing the stable ID.

### E2E-002: Duplicate Frontmatter IDs Block All Apply

Purpose: prove duplicate Markdown IDs cannot partially update canonical state.

Steps:

1. Run `init`.
2. Capture and export two thoughts.
3. Copy the first thought's `id` into the second projection's frontmatter.
4. Also edit the first projection body to a tempting valid update.
5. Run `sync --apply`.
6. Inspect SQLite and `sync_issues`.

Expected:

- Command exits non-zero.
- Duplicate ID errors are written to `sync_issues`.
- Neither thought's canonical title/body/status/tags are changed.

### E2E-003: Relative LLM Due Date Is Rejected

Purpose: prevent model output from smuggling time-sensitive natural language into canonical date fields.

Steps:

1. Run `init`.
2. Capture one thought.
3. Create a mock classifier output file for that ID with `"due": "tomorrow"`.
4. Run `process --apply --mock-output <file>`.
5. Inspect SQLite and `sync_issues`.

Expected:

- Command exits non-zero.
- SQLite `due_on` remains `NULL`.
- A `classification_invalid_output` error is written.
- Error message mentions malformed due date.

Future variant:

- Once a real model prompt exists, freeze current date/time near midnight and require the model adapter to return a normalized `YYYY-MM-DD` before validation.

### E2E-004: Low-Confidence Negation Classification Goes To Review

Purpose: prove a semantically risky classifier proposal does not become an unchecked writer when confidence is below the threshold.

Steps:

1. Run `init`.
2. Capture `do not buy milk`.
3. Create mock classifier output proposing `type: "task"`, a shopping tag, and confidence below threshold.
4. Run `process --apply --mock-output <file>`.
5. Inspect SQLite and `sync_issues`.

Expected:

- Command exits zero because this is a reviewable warning, not invalid output.
- SQLite type/status/due/priority/tags remain unchanged.
- A `classification_low_confidence` warning is written.

Future variant:

- Add an explicit approval workflow test before allowing high-impact semantic changes from real model output.

### E2E-005: YAML-Looking Capture Body Round-Trips

Purpose: prove raw body content that starts with YAML delimiters cannot corrupt generated frontmatter.

Steps:

1. Run `init`.
2. Run `capture` with body beginning:

   ```text
   ---
   not: frontmatter
   ---
   actual body
   ```

3. Run `export-md`.
4. Run `sync --check`.
5. Parse the exported Markdown and inspect SQLite.

Expected:

- Exported file has exactly one generated frontmatter block before the body.
- The body still contains the literal raw `---` lines.
- `sync --check` reports no errors.
- SQLite body is unchanged.

### E2E-006: Mobile Markdown Edit Survives Processing

Purpose: prove `process` does not overwrite an externally edited projection while proposing canonical metadata.

Steps:

1. Run `init`.
2. Capture and export one thought.
3. Edit the Markdown projection body to simulate a mobile change, but do not run `sync`.
4. Run `process --apply --mock-output <file>` with high-confidence metadata output.
5. Read the Markdown file from disk.
6. Inspect SQLite.
7. Run `doctor`.

Expected:

- Markdown file still contains the mobile edit.
- SQLite metadata fields are updated by process.
- SQLite body remains the pre-sync canonical body.
- `doctor` reports hash drift or equivalent warning, not silent overwrite.

### E2E-007: Search And Embedding Work Do Not Mutate Canonical Fields

Purpose: prove derived search indexes do not compromise canonical state.

Steps:

1. Run `init`.
2. Capture multiple thoughts with tags.
3. Run `search <query>`.
4. Refresh embeddings through an injected deterministic embedder.
5. Re-read all thoughts.

Expected:

- Search returns expected IDs.
- Embedding metadata rows are created.
- Canonical thought rows and tag rows are unchanged.

## Deferred E2E Tests

### Reindex Rebuild Preserves IDs And Audit Expectations

Add when `reindex` exists.

Required scenarios:

- Renamed projection file with same ID is accepted.
- Missing ID is rejected or quarantined.
- Duplicate IDs block rebuild.
- Invalid frontmatter blocks rebuild or quarantines the file.
- Existing processing/audit semantics are either preserved or explicitly documented as rebuildable/disposable.

### Synthesize Does Not Overwrite Human Concept Edits

Add when `synthesize` and generated concept pages exist.

Required scenarios:

- User edits a generated concept page body.
- `synthesize` proposes updates.
- Human edits are preserved or a conflict/review artifact is produced.
- No generated page is overwritten silently.

### Checkbox Task State Reconciliation

Add before body checkbox parsing is implemented.

Required scenarios:

- Body checkbox says complete while frontmatter/SQLite status is `active`.
- System reports a conflict instead of guessing.
- Any automatic reconciliation has a documented precedence rule.

## Recommended Priority

1. Add E2E-002, E2E-003, E2E-005, and E2E-006 first. These cover the highest-risk current write paths.
2. Add E2E-001 once the expected behavior for renamed projection metadata is confirmed.
3. Add E2E-007 as a guardrail around search and embedding growth.
4. Add deferred tests before implementing `reindex`, `synthesize`, or checkbox parsing.
