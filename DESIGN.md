# Thoughts — Self-Organizing Note System

> A personal "second brain" that starts as a dumping ground for raw thoughts and evolves into structured knowledge over time. Built on top of Obsidian with a SQLite intelligence layer.

## Concept

You dump thoughts — ideas, tasks, facts, shopping list items, things to remember — into an inbox folder. A processing pipeline (triggered manually) uses an LLM to classify each thought, extract structured data, and file it with appropriate frontmatter properties. Over time, embeddings stored in SQLite enable semantic search, theme discovery, and synthesis of higher-level objects like concepts, entities, and digests.

The system is designed to evolve: raw thoughts accumulate, the system processes them into structure, and over time synthesized objects emerge that connect and contextualize the corpus. A lifecycle model handles correction, supersession, and pruning so the knowledge base stays healthy as it grows.

## Architecture

```
┌──────────────────────────────────────────────┐
│              Obsidian Vault                    │
│         (source of truth: .md files)            │
│                                                  │
│  Inbox/     →  all raw thoughts, flat            │
│  Concepts/  →  auto-generated concept pages      │
│  Entities/  →  auto-generated entity hubs        │
│  Digests/   →  daily/weekly/monthly summaries   │
│  .thoughts/  →  SQLite DB (hidden from Obsidian)  │
└──────────────┬───────────────────────────────────┘
               │  manual trigger: `thoughts process`
               ▼
┌──────────────────────────────────────────────┐
│         Processing Pipeline (Python)            │
│                                                  │
│  1. Scan Inbox/ for unprocessed thoughts        │
│  2. LLM classifies each thought                 │
│     → task | note | idea                         │
│  3. LLM extracts metadata                       │
│     → due dates, priority, tags, summaries      │
│  4. Update .md frontmatter in place (no move)   │
│  5. Compute embedding, store in SQLite           │
│  6. Log processing action                        │
└──────────────┬───────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│         SQLite Intelligence Layer               │
│                                                  │
│  thoughts        (id, path, content, type, ...)  │
│  embeddings      (thought_id, vector BLOB)        │
│  tags            (thought_id, tag)                │
│  processing_log  (thought_id, action, ts)        │
│  review_queue    (thought_id, reason, ...)       │
│  supersessions   (old_id, new_id, ...)            │
│  duplicates      (thought_id, duplicate_of, ...)  │
│                                                  │
│  + future: concepts, entities, digests tables   │
│  + sqlite-vec → semantic similarity search       │
└──────────────────────────────────────────────┘
```

## Design Decisions

### Markdown files are the source of truth

- Obsidian renders them natively (graph view, backlinks, plugins, mobile sync)
- Human-readable, git-versionable, portable
- You can always browse and edit without the tool
- SQLite can be fully rebuilt from the vault at any time

### SQLite is the intelligence layer

- Fast structured queries (filter by type, date range, tags)
- `sqlite-vec` extension for vector similarity search on embeddings
- Stores processing state (what's been processed, what hasn't)
- Embeddings as BLOBs — first-class, not crammed into YAML
- Derived from vault; vault is canonical

### Flat structure — properties over physical folders

- All raw thoughts live in `Inbox/` — no file moving during processing
- Categorization is done entirely through frontmatter properties (`type`, `status`, `tags`, `due`, `priority`)
- Obsidian Bases (or Dataview) provides virtual groupings: a "Tasks" view is `WHERE type = 'task'`, an "Ideas" view is `WHERE type = 'idea'`
- Reclassification is free — just update the property, no file move
- Fewer sync conflicts (no rename operations on iCloud/Dropbox)
- SQLite doesn't care about folders; `type`, `status`, `tags`, `due` are the primary query dimensions

**Why this over folders:**
- Simpler pipeline (no file-moving logic, no path syncing)
- Reclassification is a property update, not a rename
- Obsidian Bases does the visual organization natively
- One folder for all raw thoughts keeps things uncluttered

**System-generated synthesized objects** (concepts, entities, digests) do get their own folders, since the system creates them in the right place rather than moving user files. See [Synthesized Objects](#synthesized-objects-future).

### LLM does the heavy lifting

- Classification: task vs. note vs. idea
- Extraction: due dates, priorities, tags, context
- Summarization: generate a summary line for each thought
- The LLM sees the thought content + current vault state, outputs structured decisions
- LLM does everything — no rules-first fallback for MVP

### Manual trigger

- `thoughts process` — you run it when you want to triage
- No background watchers, no real-time processing
- Simple, predictable, easy to debug
- Future: optional scheduled mode

## Folder Structure

```
vault/
├── Inbox/          # All raw thoughts, flat, properties for categorization
├── Concepts/       # (future) Auto-generated concept/theme pages
├── Entities/        # (future) Auto-generated entity hub pages
├── Digests/        # (future) Daily/weekly/monthly digests
└── .thoughts/       # SQLite DB + processing state (hidden from Obsidian)
```

Only `Inbox/` is created in the MVP. `Concepts/`, `Entities/`, and `Digests/` are created when their features are built.

## Frontmatter Schema

### Unprocessed (raw inbox item)

```yaml
---
type: inbox
created: 2026-08-23T14:30:00
---
```

### Processed

```yaml
---
type: task                  # task | note | idea
status: active               # active | done | archived | superseded | flagged
created: 2026-08-23T14:30:00
processed: 2026-08-23T18:00:00
tags: [shopping, groceries]
due: 2026-08-25             # tasks only, if a date was detected
priority: medium            # low | medium | high (tasks only)
summary: "Buy groceries: milk, eggs, bread"
corrected:                  # (optional) timestamp of last correction
correction_note:            # (optional) what was corrected
superseded_by:              # (optional) wikilink to superseding thought
last_activity: 2026-08-23T18:00:00
---
```

## SQLite Schema

### Core tables (MVP)

```sql
CREATE TABLE thoughts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT UNIQUE NOT NULL,       -- vault-relative path
    filename        TEXT NOT NULL,
    type            TEXT NOT NULL,              -- task | note | idea | inbox
    status          TEXT DEFAULT 'active',      -- active | done | archived | superseded | flagged
    content         TEXT NOT NULL,              -- markdown body (sans frontmatter)
    summary         TEXT,                       -- LLM-generated one-liner
    created         TEXT NOT NULL,              -- ISO timestamp
    processed       TEXT,                       -- ISO timestamp, NULL if unprocessed
    due             TEXT,                       -- ISO date or NULL (tasks only)
    priority        TEXT,                       -- low | medium | high | NULL
    tags            TEXT,                        -- JSON array as string
    corrected       TEXT,                       -- timestamp of last manual correction
    correction_note TEXT,                        -- what was corrected
    superseded_by   INTEGER REFERENCES thoughts(id), -- thought that supersedes this one
    last_activity   TEXT,                       -- last time this thought was referenced/modified
    raw_content     TEXT NOT NULL               -- original unmodified content (pre-processing)
);

CREATE TABLE embeddings (
    thought_id      INTEGER PRIMARY KEY REFERENCES thoughts(id),
    embedding       BLOB NOT NULL,              -- float32 vector via sqlite-vec
    model           TEXT NOT NULL,              -- which embedding model produced it
    created         TEXT NOT NULL
);

CREATE TABLE processing_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    thought_id      INTEGER REFERENCES thoughts(id),
    action          TEXT NOT NULL,              -- classified | embedded | corrected | reprocessed | flagged
    timestamp       TEXT NOT NULL,
    details         TEXT                         -- JSON with extra info
);

CREATE TABLE tags (
    thought_id      INTEGER REFERENCES thoughts(id),
    tag             TEXT NOT NULL,
    PRIMARY KEY (thought_id, tag)
);

-- sqlite-vec virtual table for vector search
CREATE VIRTUAL TABLE vec_embeddings USING vec0(
    thought_id INTEGER PRIMARY KEY,
    embedding  float[384]                    -- dimension depends on model
);
```

### Lifecycle tables (MVP — schema only, features deferred)

```sql
CREATE TABLE supersessions (
    old_thought_id   INTEGER REFERENCES thoughts(id),
    new_thought_id   INTEGER REFERENCES thoughts(id),
    created          TEXT NOT NULL,
    note             TEXT,
    PRIMARY KEY (old_thought_id, new_thought_id)
);

CREATE TABLE duplicates (
    thought_id      INTEGER REFERENCES thoughts(id),
    duplicate_of    INTEGER REFERENCES thoughts(id),
    similarity      REAL NOT NULL,
    detected        TEXT NOT NULL,
    resolved        TEXT,                       -- NULL = unresolved, timestamp = user confirmed
    PRIMARY KEY (thought_id, duplicate_of)
);

CREATE TABLE review_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    thought_id      INTEGER REFERENCES thoughts(id),
    reason          TEXT NOT NULL,             -- stale | duplicate | supersession_candidate | low_activity | llm_uncertain
    priority        TEXT,                      -- low | medium | high
    detected        TEXT NOT NULL,
    resolved        TEXT                        -- NULL = pending, timestamp = resolved
);
```

### Synthesized object tables (future — not in MVP)

```sql
CREATE TABLE concepts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    path             TEXT UNIQUE NOT NULL,
    name             TEXT NOT NULL,
    summary          TEXT,
    thought_count    INTEGER NOT NULL,
    cluster_centroid BLOB,              -- for comparing new thoughts against existing clusters
    created          TEXT NOT NULL,
    last_updated     TEXT NOT NULL
);

CREATE TABLE concept_members (
    concept_id       INTEGER REFERENCES concepts(id),
    thought_id       INTEGER REFERENCES thoughts(id),
    similarity       REAL,               -- how close this thought is to the cluster centroid
    PRIMARY KEY (concept_id, thought_id)
);

CREATE TABLE entities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,       -- person | project | place | topic | thing
    aliases         TEXT,                -- JSON array
    mention_count   INTEGER NOT NULL DEFAULT 0,
    created         TEXT NOT NULL
);

CREATE TABLE entity_mentions (
    entity_id       INTEGER REFERENCES entities(id),
    thought_id      INTEGER REFERENCES thoughts(id),
    context         TEXT,                -- the sentence where the entity was mentioned
    PRIMARY KEY (entity_id, thought_id)
);

CREATE TABLE digests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT UNIQUE NOT NULL,
    kind            TEXT NOT NULL,       -- daily | weekly | monthly
    date_start      TEXT NOT NULL,
    date_end         TEXT NOT NULL,
    thought_count   INTEGER NOT NULL,
    summary         TEXT,
    created         TEXT NOT NULL
);
```

## Processing Pipeline

### `thoughts init`

1. Create vault folder structure (`Inbox/`)
2. Initialize SQLite database with schema
3. Load `sqlite-vec` extension
4. Create `.thoughts/` directory for DB + config

### `thoughts process`

1. **Scan**: Find all `.md` files in `Inbox/` that have `type: inbox` in frontmatter
2. **Index**: Read each file, extract raw content
3. **Classify (LLM)**: For each thought, send to LLM with a classification prompt:
   - Input: thought content + current vault context (existing types/tags)
   - Output: `{ type, due, priority, tags, summary, suggested_links }`
4. **Write back**:
   - Update the `.md` file's frontmatter with classified type, tags, summary, etc.
   - File stays in `Inbox/` — no move
   - Add any LLM-suggested wikilinks to the content body
5. **Embed**: Compute embedding vector for the thought, store in SQLite
6. **Log**: Record the processing action in `processing_log`

### `thoughts search <query>`

1. Embed the query text
2. Run vector similarity search against `vec_embeddings`
3. Return top-N results with path, summary, type, and similarity score
4. Optionally filter by type/status/tags/dates

### `thoughts status`

1. Show inbox count (unprocessed thoughts)
2. Show last processed timestamp
3. Show DB stats (total thoughts by type, by status)
4. Show review queue count (if any)

### `thoughts reindex`

1. Walk entire vault (all `.md` files)
2. Rebuild SQLite `thoughts` table from file contents + frontmatter
3. Recompute all embeddings
4. Full sync — destructive to SQLite, vault is untouched
5. Useful after manual edits or as a recovery tool

### `thoughts reprocess <path>`

1. Re-run classification on a single thought
2. Update frontmatter + embedding
3. Log the reprocessing action
4. Use case: after manually correcting a misclassification

## Lifecycle and Correction

### Correction (MVP-adjacent)

The LLM will sometimes misclassify a thought or extract the wrong metadata. Correction is handled gracefully:

- **Manual correction**: edit frontmatter properties directly in Obsidian. The `corrected` and `correction_note` fields record what changed and when.
- **`thoughts reprocess <path>`**: re-run classification on a single thought after you've edited it.
- **SQLite picks up changes**: on next scan/reindex, the DB reflects the corrected frontmatter.

No special machinery needed — the flat/properties approach makes correction a simple property update.

### Supersession (schema-ready, feature deferred)

Over time, your thinking evolves. A thought from March about how to manage your time might be superseded by a realization in August that the approach doesn't work. The old thought isn't *wrong* — it's *superseded*:

- Set `status: superseded` and `superseded_by: "[[newer-thought]]"` in frontmatter
- The superseding thought references back with `supersedes: ["[[older-thought]]"]`
- The SQLite layer down-weights or excludes superseded thoughts from synthesis while keeping them in search results and history
- The `supersessions` table records the relationship

### Pruning and Review (schema-ready, feature deferred)

Different object types age differently. Pruning means lifecycle state transitions, not deletion:

| Object | Obsolescence pattern | Pruning rule |
|--------|----------------------|--------------|
| Completed tasks | Done, no longer relevant after N days | Auto-archive after 30 days |
| Abandoned ideas | No activity, no linked thoughts | Flag for review after 90 days of inactivity |
| Stale concepts | Thought count declining, no new members | Flag when no new members in 60 days |
| One-off entities | Mentioned once, never again | Flag after 90 days with mention_count = 1 |
| Duplicate thoughts | Same content captured twice | Detect via embedding similarity > 0.95 |

A future `thoughts prune` or `thoughts review` command would:
1. Apply automatic rules (archive completed tasks older than threshold)
2. Surface items that *might* be obsolete for your approval
3. Never delete without explicit approval — pruning is reversible until `thoughts purge`

```
                    ┌──────────┐
    capture ──────→ │  active   │ ←── corrected (metadata fixed)
                    └────┬─────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
         ┌────────┐ ┌────────┐ ┌──────────────┐
         │  done  │ │ flagged │ │  superseded   │
         │(tasks) │ │(review) │ │ (by newer     │
         └───┬────┘ └───┬────┘ │  thought)     │
             │          │      └──────────────┘
             ▼          ▼
         archived ←── user approves
             │
             ▼
         purged (optional, explicit, irreversible)
```

The `review_queue` table is in the schema from day one so items can be flagged as they're detected, even before the full pruning feature is built.

## Synthesized Objects (Future)

These are higher-level objects that *emerge from* the collection of raw thoughts. They're not captured — they're generated. This is the "evolution" part of the concept, and the part that no existing tool fully nails.

### Concepts / Themes

Recurring topics that emerge across many thoughts. You mention "productivity" in 15 different thoughts over 3 months — that's a concept.

**Generation:**
- `thoughts synthesize` clusters embeddings (k-means or similar)
- Clusters with enough members (3+ thoughts) become concept candidates
- LLM reviews the cluster and generates: a name, a summary, and connections
- Concept pages are **living documents** — re-synthesized on each run, picking up new related thoughts

**Example:**
```yaml
---
type: concept
created: 2026-08-23T18:00:00
last_updated: 2026-09-15T09:00:00
thought_count: 14
summary: "A recurring thread around food planning, grocery efficiency, and local sourcing"
tags: [food, planning, lifestyle]
---
# Food & Sourcing

Across 14 thoughts over 3 weeks, you've been thinking about:
- Grocery efficiency and list management
- Meal planning as a way to reduce waste
- Local sourcing (farmers market, CSA)

## Related thoughts
- [[20260823-1430-buy-groceries]]
- [[20260825-0915-meal-planning]]
- [[20260901-1200-farmers-market]]
...
```

### Entities

People, projects, places, and things that show up across your thoughts. "Mom" appears in 8 thoughts. "Project Aurora" appears in 23. Each gets an entity hub page.

**Generation:**
- LLM extracts named entities during processing
- Entities accumulate in the `entities` table
- When an entity crosses a threshold (2+ mentions), it gets a page
- Entity pages are auto-maintained — updated as new thoughts mention them

**Example:**
```yaml
---
type: entity
entity_kind: person
created: 2026-08-20T10:00:00
mention_count: 8
aliases: [Mom, mom, my mother]
tags: [family]
---
# Mom

Mentioned in 8 thoughts:
- [[20260820-1000-call-mom]] — "Call Mom about Thanksgiving plans"
- [[20260822-1530-mom-birthday]] — "Mom's birthday is Oct 3, need a gift"
...
```

### Daily Digests

A synthesized narrative summary of everything that went through the system on a given day.

**Generation:**
- `thoughts digest` (defaults to today) or `thoughts digest --date 2026-08-23`
- Pulls all thoughts with `created` date = target date
- LLM generates a readable summary: what you were thinking about, what themes emerged, what tasks came up

**Example:**
```yaml
---
type: digest
digest_kind: daily
date: 2026-08-23
thought_count: 12
tasks_created: 3
ideas_created: 2
themes: [productivity, food-planning, reading]
---
# August 23, 2026

A busy thinking day — 12 thoughts captured. Three tasks came up (groceries, calling Mom, renewing a library book), and you had two ideas worth developing: one about a reading habit tracker and one about weekend meal prep.

## Tasks
- [ ] Buy groceries (milk, eggs, bread) — due tomorrow
- [ ] Call Mom about Thanksgiving — no due date
- [ ] Return library book — due Aug 28

## Ideas
- [[20260823-1645-reading-tracker]] — Reading habit tracker concept
- [[20260823-1715-weekend-meal-prep]] — Weekend meal prep system
```

### Reports (weekly/monthly)

Higher-level synthesis across days, surfacing trends.

**Generation:**
- `thoughts digest --weekly` or `thoughts digest --monthly`
- Pulls all thoughts + digests in the date range
- LLM synthesizes: what changed, what's new, what's recurring, what's fading

**Example:**
```yaml
---
type: digest
digest_kind: weekly
date_range: [2026-08-17, 2026-08-23]
thought_count: 47
tasks_completed: 12
tasks_created: 18
top_themes: [productivity, food-planning, reading, fitness]
emerging: [meditation]
fading: [podcast-ideas]
---
# Week of August 17-23

## What happened
47 thoughts this week, slightly up from last. Productivity and food planning remain your dominant themes. A new thread around meditation started mid-week.

## Emerging
- **Meditation** — 4 thoughts starting Tuesday, seems new

## Fading
- **Podcast ideas** — only 1 mention this week, down from 6 last week

## Tasks
- 18 created, 12 completed (67% completion rate)
- 3 overdue: ...
```

### How synthesized objects fit together

```
Raw thoughts (type: task|note|idea)
        │
        │  thoughts synthesize (future)
        │  embedding clustering + LLM
        ▼
   Concepts (type: concept)
   ── wikilinks back to member thoughts
   ── living documents, re-synthesized on each run

        │
        │  entity extraction (future, during process)
        │
        ▼
   Entities (type: entity)
   ── auto-maintained hub pages
   ── updated as new thoughts mention them

        │
        │  thoughts digest --daily|--weekly|--monthly (future)
        │
        ▼
   Digests (type: digest)
   ── temporal snapshots
   ── narrative summaries
```

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.11+ | Already available, rich ecosystem |
| Package manager | `uv` | Fast, installed, handles venv |
| Vector search | `sqlite-vec` | Lightweight SQLite extension, no separate DB |
| Embeddings | `sentence-transformers` (local) or OpenAI API | Start local for privacy; OpenAI as fallback |
| LLM | OpenAI API (or local model) | Classification + extraction |
| Vault | Obsidian | Source of truth, human-facing layer |
| CLI | `click` or `typer` | Clean command-line interface |
| Markdown parsing | `python-frontmatter` | Parse/update YAML frontmatter |
| File watching | (not needed — manual trigger) | Keep it simple for MVP |

## MVP Scope (Phase 1)

1. **Vault setup**: `thoughts init` creates `Inbox/` folder + SQLite schema
2. **CLI**: `thoughts init`, `thoughts process`, `thoughts search`, `thoughts status`, `thoughts reprocess`, `thoughts reindex`
3. **SQLite layer**: Core schema, sqlite-vec integration, embedding storage
4. **Processing pipeline**: Inbox scan → LLM classify → frontmatter update (in place) → embed → log
5. **Search**: Vector similarity search from CLI
6. **Lifecycle schema**: `status`, `superseded_by`, `corrected`, `review_queue` tables exist but features are minimal (manual correction only)

## Future Extensions

### Phase 2 — Synthesis
- `thoughts synthesize` — concept/theme detection via embedding clustering
- Entity extraction and entity hub pages
- `thoughts digest` — daily/weekly/monthly narrative digests

### Phase 3 — Lifecycle Management
- `thoughts prune` / `thoughts review` — automated pruning rules, review queue
- Duplicate detection via embedding similarity
- Supersession linking and visualization
- Auto-archival of completed tasks

### Phase 4 — Integration
- Calendar integration (export task due dates to Apple Calendar / Google Calendar)
- Daily digest auto-generation on schedule
- Mobile capture (quick-capture from phone into `Inbox/`)
- Web UI for browsing/searching beyond Obsidian + CLI
- Richer classification types (shopping list, recipe, contact, reference, etc.)
- Connection discovery: "You've thought about X 12 times across 3 months — here's a synthesis"
