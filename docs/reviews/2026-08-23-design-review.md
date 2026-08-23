---
title: Thoughts Design Review
date: 2026-08-23
tags:
  - review
  - design
  - thoughts
status: published
reviewed:
  - "[[DESIGN]]"
  - "[[README]]"
---

# Thoughts Design Review

## Verdict

The design has a strong core: Markdown/YAML as the durable source of truth, SQLite as a rebuildable intelligence layer, manual processing, and Obsidian as the human-facing interface. That is the right direction for a personal system that must remain useful even when the tool breaks.

The current MVP is still too ambitious and underspecified. It tries to ship six CLI commands, LLM classification, frontmatter mutation, body mutation, embeddings, vector search, lifecycle schema, correction semantics, and rebuild behavior all at once. The highest-risk part is not the LLM itself; it is allowing an uncertain classifier to mutate canonical notes before the system has stable identity, idempotency, review, and recovery rules.

My pushback: do not build Phase 1 exactly as written. Split it into a narrower foundation phase that proves capture, identity, indexing, and reversible metadata application before adding semantic search or synthesis.

## High-Priority Findings

### P0: Source-of-truth boundaries are asserted but not operationally true

The design says Markdown files are canonical and SQLite can be rebuilt from the vault at any time (`DESIGN.md:58-64`, `DESIGN.md:71`). But the schema stores fields that are not fully reconstructible from current Markdown:

- `raw_content` is described as original pre-processing content (`DESIGN.md:170`).
- `processing_log` records historical actions (`DESIGN.md:180-186`).
- `review_queue`, `duplicates`, and `supersessions` are stateful workflows (`DESIGN.md:201-229`).
- `thoughts reindex` is described as destructive to SQLite (`DESIGN.md:318-324`).

Those claims collide. If SQLite is disposable, then historical processing logs, original raw content, unresolved duplicate decisions, review status, and supersession decisions must either live in Markdown or be explicitly treated as disposable cache. The current design does neither.

Recommendation: define three state classes before implementation:

| Class | Examples | Owner |
|---|---|---|
| Canonical durable note state | `id`, `type`, `status`, `created`, `processed`, `due`, `priority`, tags, supersession links, correction notes | Markdown/YAML |
| Rebuildable derived index | parsed content, tag rows, embeddings, vector tables, inferred entities | SQLite |
| Operational audit/cache | processing logs, model calls, confidence scores, review suggestions | Either Markdown sidecar files or disposable SQLite, but document the loss semantics |

If the answer is "processing logs are disposable," say that clearly. If the answer is "processing logs are part of the personal record," store them in Markdown-visible files under a tool-owned folder.

### P0: Stable identity is missing

The schema uses `id INTEGER PRIMARY KEY AUTOINCREMENT` and `path TEXT UNIQUE NOT NULL` (`DESIGN.md:153-156`). That is not enough for a vault where humans and Obsidian can rename files. Reindexing can assign new integer IDs. Paths can change. Wikilinks can be rewritten. Duplicate/supersession relationships can become ambiguous.

This is the most important technical omission in the design.

Recommendation: every thought should get a durable machine ID in frontmatter at capture time, for example:

```yaml
id: th_01K3...
```

Use a ULID or UUID. SQLite should use that ID as the primary key. Paths should be mutable attributes, not identity. This also makes reindex, dedupe, supersession, sync conflict recovery, and exports tractable.

### P0: Direct LLM mutation of canonical notes needs a write fence

The design says `thoughts process` updates frontmatter and adds LLM-suggested wikilinks to the content body (`DESIGN.md:297-301`). It also says the LLM does all classification with no rules-first fallback (`DESIGN.md:90-97`).

That is risky for a note system where the vault is canonical. A model can misclassify a task, invent a due date, overtag, add noisy links, or rewrite structure in ways that are annoying to unwind. The design acknowledges correction (`DESIGN.md:335-343`) but does not prevent damage or make changes reviewable.

Recommendation: Phase 1 should not let the LLM modify the note body. Limit writes to a constrained frontmatter patch generated from a strict schema, then validate it before writing. Record enough metadata to support audit and reversal:

```yaml
processed: 2026-08-23T18:00:00
processor:
  model: gpt-...
  version: 1
  confidence: 0.82
  reviewed: false
```

For low-confidence or high-impact changes, write `status: flagged` and enqueue review rather than committing aggressive metadata. Suggested wikilinks should be proposals until a later reviewed feature exists.

### P1: The MVP is not actually minimal

Phase 1 includes initialization, processing, search, status, reprocess, reindex, SQLite schema, sqlite-vec, embeddings, LLM processing, and lifecycle schema (`DESIGN.md:573-580`). That is too much surface area for the first version.

The riskiest parts depend on each other:

- Search quality depends on embeddings and identity.
- Reindex depends on stable source-of-truth semantics.
- Reprocess depends on idempotent frontmatter writes.
- Lifecycle schema depends on stable identity and correction semantics.
- LLM processing depends on prompt/version tracking and validation.

Recommendation: split the current MVP:

| Phase | Ship | Explicitly exclude |
|---|---|---|
| Phase 0: Durable capture and index | `init`, `capture`, `index`, `status`; stable IDs; parse/validate YAML; SQLite rebuilt from Markdown | LLM, embeddings, vector search, body mutation |
| Phase 1: Reviewed classification | `process --dry-run`, `process --apply`; strict JSON schema; confidence; frontmatter-only writes; review queue | suggested body links, synthesis, pruning |
| Phase 2: Search | embeddings; `search`; backfill/re-embed; model/version metadata | clustering, auto concept pages |
| Phase 3: Synthesis | concepts/entities/digests as generated notes with provenance | auto-pruning and destructive lifecycle actions |

This shape lets the foundation fail in boring ways before model-driven behavior touches canonical notes.

### P1: "Current vault context" is dangerously vague

The classifier input includes "current vault context" and existing tags (`DESIGN.md:294-296`). That can become expensive, slow, privacy-sensitive, and nondeterministic. It also risks leaking unrelated private notes into every classification call if OpenAI API is used.

Recommendation: define a bounded context contract:

- Allowlist which folders are visible to classification.
- Include only a compact tag/type vocabulary and nearest-neighbor snippets when embeddings exist.
- Never send entire vault state by default.
- Log which context bundle was used for each run.
- Add a local-only mode where classification is disabled or uses local models.

For a personal vault, privacy is a product requirement, not an implementation detail.

### P1: The design mixes Obsidian Bases with Dataview

The design says "Obsidian Bases (or Dataview)" for virtual groupings (`DESIGN.md:77`). That weakens the interface commitment. Dataview is powerful, but for this project the user-facing structured layer should be Obsidian Bases.

Recommendation: remove Dataview from the primary design. Build generated `.base` files as first-class outputs when views are needed. Treat Dataview, if supported at all, as an optional export later.

### P1: Reindex semantics are underspecified

`thoughts reindex` says it walks the vault, rebuilds SQLite, and recomputes all embeddings (`DESIGN.md:318-324`). That is expensive and may mutate enough derived state to surprise the user. It also does not say how deleted files, moved files, renamed files, changed frontmatter, or corrupted YAML are handled.

Recommendation: specify reindex modes:

- `reindex --check`: parse and report drift without writing.
- `reindex --index-only`: rebuild SQLite rows from Markdown without changing notes.
- `reindex --embeddings`: recompute missing or stale embeddings only.
- `reindex --force-embeddings`: expensive full recompute.

Add explicit behavior for missing IDs, duplicate IDs, moved paths, invalid frontmatter, and files outside managed folders.

### P1: Task handling is too weak for the promise being made

The system classifies tasks and extracts due dates and priorities (`DESIGN.md:31-33`, `DESIGN.md:133-140`), but it does not define how task checkboxes relate to `status`, how completed tasks are detected, or whether Obsidian Tasks-style syntax is supported.

Recommendation: decide whether tasks are notes, checkboxes, or both. If they are notes, use frontmatter `status`. If they are checkbox lines inside notes, define line-level identity and sync rules. Avoid pretending both are solved.

### P2: Lifecycle schema should not ship before lifecycle behavior

The design includes lifecycle tables in the MVP while deferring features (`DESIGN.md:201-229`, `DESIGN.md:580`). Schema-first lifecycle work adds migration burden without proving user value. Worse, if stable identity changes later, these tables will be the first things to break.

Recommendation: keep lifecycle fields that are user-visible and durable in Markdown, but defer `review_queue`, `duplicates`, and `supersessions` tables until the corresponding commands exist. Alternatively, mark those tables as experimental cache and allow dropping them without migration guarantees.

### P2: Generated synthesized objects need provenance and overwrite policy

Concepts, entities, and digests are described as auto-generated living pages (`DESIGN.md:392-557`). The design does not yet say how user edits are protected. A generated concept page that gets re-synthesized can overwrite human improvements unless there is a hard boundary.

Recommendation: generated notes need one of these policies:

- Tool-owned files only: user edits are discouraged and may be overwritten.
- Section-owned files: the tool rewrites only fenced generated sections.
- Proposal files: new syntheses are written as review candidates.

For Obsidian, the section-owned model is usually the best compromise:

```markdown
## Generated summary

<!-- thoughts:begin generated-summary -->
...
<!-- thoughts:end generated-summary -->
```

### P2: Embedding model choice is not a detail

The schema hardcodes a sample `float[384]` vector dimension (`DESIGN.md:194-198`) while the tech stack allows `sentence-transformers` or OpenAI embeddings (`DESIGN.md:566`). Those dimensions and distance assumptions differ. A model switch can invalidate the vector table.

Recommendation: make embedding collections model-specific. Store provider, model, dimension, normalization, content hash, and generated timestamp. Consider separate vector tables per dimension/model or a rebuild path that drops incompatible embeddings.

### P2: The tag model needs stricter normalization

Tags appear as both JSON text in `thoughts.tags` and normalized rows in `tags` (`DESIGN.md:165`, `DESIGN.md:188-192`). The design does not define casing, spaces, nested tags, aliases, or whether tags include `#`.

Recommendation: pick one canonical storage shape in Markdown and one derived index shape in SQLite. Normalize tags on write, preserve user display only if needed, and reject ambiguous values.

## Adversarial Scenarios

These are the tests I would use to break the design before trusting it:

1. A user renames a processed note in Obsidian, then runs `reindex`.
2. Two notes accidentally receive the same frontmatter ID.
3. The LLM extracts "tomorrow" as a due date across a midnight run.
4. A note says "do not buy milk" and the classifier creates a shopping task.
5. A capture has invalid YAML because the raw text starts with `---`.
6. A file is changed on mobile while `thoughts process` is running.
7. The embedding model changes dimension after a dependency upgrade.
8. The user manually edits a generated concept page, then runs `synthesize`.
9. A completed task is marked with a checkbox but frontmatter still says `active`.
10. Reindex drops `processing_log`; the user expected an audit trail.

If the implementation has clear answers for these, the design is much stronger.

## Recommended Revised Architecture

Keep the conceptual architecture, but tighten ownership:

```text
Obsidian Markdown/YAML
  durable identity, user-visible state, task state, supersession links

SQLite
  disposable/rebuildable parsed index, search index, embeddings, derived relations

Tool audit
  either disposable cache with documented loss semantics
  or Markdown-visible logs if the history matters

LLM
  proposal generator first, canonical mutator only after schema validation and confidence gates
```

## Concrete Design Changes To Make Now

1. Add durable frontmatter `id` to every thought at capture/init time.
2. Replace SQLite integer identity with the durable thought ID.
3. Remove Dataview from the primary design and commit to Obsidian Bases.
4. Remove body mutation from `thoughts process` Phase 1.
5. Add `process --dry-run` before `process --apply`.
6. Add strict JSON schema validation for LLM output.
7. Define confidence thresholds and review behavior.
8. Split the MVP into foundation, reviewed classification, search, and synthesis phases.
9. Define reindex behavior for moved, deleted, malformed, duplicate-ID, and manually edited notes.
10. Decide whether processing logs are canonical records or disposable cache.
11. Add model/version/content-hash metadata for embeddings.
12. Define generated-note overwrite policy before building concepts/entities/digests.

## What I Would Build First

Build the boring foundation:

```text
thoughts init
thoughts capture "text"
thoughts index --check
thoughts index --force
thoughts status
```

Acceptance criteria:

- New captures get stable IDs.
- Markdown frontmatter round-trips without formatting corruption.
- SQLite can be deleted and rebuilt with no loss of canonical state.
- Duplicate IDs and invalid YAML are detected.
- Manual Obsidian edits are reflected after indexing.
- No LLM call is required for the system to be useful.

Only after that would I add `process --dry-run` with LLM classification.

## Addendum: Canonical SQLite, Markdown Projection

After reconsidering the user's concern that consistency is difficult to maintain when Markdown is canonical, I would change the recommended ownership model for this project:

> Use SQLite as the canonical store and treat Obsidian Markdown as a readable, editable projection.

This keeps the best reason to build on Obsidian: human readability, browsing, links, portability, and low-friction review. But it moves consistency enforcement into the layer that can actually enforce consistency: a relational database with constraints, migrations, typed columns, foreign keys, uniqueness checks, and transactional writes.

### Revised recommendation

| Layer | Responsibility |
|---|---|
| SQLite | Canonical records, stable IDs, schema constraints, task state, links, tags, entity references, processing logs, embeddings metadata, sync state |
| Markdown files | Human-readable Obsidian projection of database records |
| Obsidian edits | Allowed input channel, but validated and imported through `thoughts sync` |
| Bases | Human-facing structured views over projected Markdown properties |
| LLM | Proposal/classification engine, never an unchecked canonical writer |

This is a better fit if the project is expected to maintain strict consistency over time. Markdown remains useful, but it is no longer asked to be both a pleasant note format and a reliable database.

### Why SQLite over Postgres

I would still start with SQLite, not Postgres.

Postgres is the right choice if this becomes a shared service with multiple concurrent users, a web app, remote access, background workers, role-based permissions, or always-on integrations. Those are not current requirements. For a local-first personal system, Postgres adds server lifecycle, authentication, backup, restore, network, and hosting concerns before the product has proved its shape.

SQLite gives enough rigor for this stage:

- `CHECK` constraints for enums such as `type`, `status`, and `priority`.
- `FOREIGN KEY` constraints for links, supersessions, entities, and generated objects.
- Unique stable IDs.
- Transactions for multi-record updates.
- Migrations.
- FTS for text search.
- `sqlite-vec` or adjacent tables for embeddings.
- A single local file that is easy to back up and inspect.

The practical recommendation is:

```text
Canonical truth: .thoughts/thoughts.sqlite
Human projection: Inbox/*.md, Concepts/*.md, Entities/*.md, Digests/*.md
Sync command: thoughts sync
Export command: thoughts export-md
Repair command: thoughts doctor
```

### How Markdown edits should work

Obsidian edits should not be ignored, but they should not be blindly trusted either.

Each projected Markdown file should carry stable identity and sync metadata:

```yaml
---
id: th_01K3...
type: task
status: active
due: 2026-08-25
tags:
  - shopping
schema_version: 1
last_exported_hash: ...
---
```

On `thoughts sync`, the tool should:

1. Parse changed Markdown files.
2. Match records by stable `id`, not path or title.
3. Validate frontmatter against the SQLite schema.
4. Import valid user edits into SQLite.
5. Quarantine invalid edits into a review report instead of partially applying them.
6. Re-export normalized Markdown from SQLite.

This creates a controlled two-way workflow: humans can edit in Obsidian, but the database remains the final arbiter of valid state.

### Generated content boundary

If SQLite is canonical, generated Markdown needs an explicit overwrite policy. The safest version is section ownership:

```markdown
## Notes

Human-authored content lives here.

## Generated summary

<!-- thoughts:begin generated-summary -->
Tool-authored content lives here and may be rewritten.
<!-- thoughts:end generated-summary -->
```

The tool may rewrite fenced generated sections. It should not rewrite unfenced human-authored sections except through an explicit command.

### Updated first build

Under the SQLite-canonical architecture, the first useful milestone becomes:

```text
thoughts init
thoughts capture "text"
thoughts export-md
thoughts sync --check
thoughts status
thoughts doctor
```

Acceptance criteria:

- SQLite schema is the authoritative contract.
- Captures create database records with stable IDs.
- Markdown files are generated from database rows.
- Manual Markdown edits can be detected, validated, and imported.
- Invalid Markdown edits are reported without corrupting canonical state.
- Deleting Markdown does not delete canonical data unless an explicit delete/import policy says so.
- The database can regenerate the Obsidian projection.

This design is less "pure local files as truth" but more honest about the consistency problem. For this project, that tradeoff is probably worth it.

## Final Assessment

The design is promising, but it is currently a compelling product sketch more than an implementation-ready design. The main fix is not adding more schema for its own sake. It is clarifying ownership, identity, idempotency, and review boundaries.

If Markdown remains canonical, the system needs much stricter validation and repair semantics than the current design describes. If consistency matters more than file purity, the stronger architecture is SQLite canonical with Markdown as an Obsidian projection.

If those boundaries are corrected, this can become a durable local-first Obsidian intelligence layer. If they are not, the project is likely to become a pile of clever automation around fragile note mutations.
