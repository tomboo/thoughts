# Thoughts

A self-organizing personal knowledge system with a [SQLite](https://www.sqlite.org) canonical store and [Obsidian](https://obsidian.md) as the human-readable interface.

## The idea

You dump raw thoughts — ideas, tasks, facts, reminders, anything worth keeping — into the system. SQLite keeps the canonical structured record. Markdown files are exported for Obsidian so the corpus remains browsable, linkable, and reviewable by a human. A processing pipeline can use an LLM to classify each thought, extract structured metadata (due dates, priorities, tags), and propose higher-level structure. Over time, embeddings stored in SQLite enable semantic search and the emergence of synthesized objects: concepts, entities, and digests.

The system is designed to **evolve**. Raw thoughts accumulate. The system processes them into structure. Synthesized objects emerge that connect and contextualize the corpus. A lifecycle model handles correction, supersession, and pruning so the knowledge base stays healthy as it grows.

## How it works

1. **Capture** — Create a canonical SQLite record with a stable ID
2. **Export** — Generate Obsidian-readable Markdown projections
3. **Sync** — Validate manual Markdown edits before importing them
4. **Process** — Run `thoughts process` to classify, tag, and extract metadata
5. **Search** — Use `thoughts search` for semantic similarity search across all thoughts
6. **Synthesize** *(future)* — Run `thoughts synthesize` to detect emerging themes and generate concept pages
7. **Digest** *(future)* — Run `thoughts digest` to generate daily/weekly/monthly summaries

## Architecture

- **SQLite** is the source of truth — structured schema, constraints, stable IDs, migrations, processing state
- **Markdown files** are Obsidian projections — human-readable, git-versionable, and safe to regenerate
- **Obsidian Bases** is the human-facing structured view layer
- **LLM writes are gated** — model output should be validated before it can update canonical state

## Status

**Design phase.** Architecture lives under [docs/design/](./docs/design/). Implementation plans live under [docs/plans/](./docs/plans/). Reviews live under [docs/reviews/](./docs/reviews/). ADRs live under [docs/adr/](./docs/adr/). Project tasks live under [tasks/](./tasks/) and can be viewed through [bases/tasks.base](./bases/tasks.base).

### Proposed Foundation

- [ ] `thoughts init` — vault setup + SQLite schema
- [ ] `thoughts capture` — create canonical records with stable IDs
- [ ] `thoughts export-md` — export Obsidian-readable Markdown
- [ ] `thoughts sync --check` — validate Markdown edits before import
- [ ] `thoughts status` — vault and DB overview
- [ ] `thoughts doctor` — detect schema, projection, and sync problems

### Future

- [ ] LLM processing: classify, tag, extract metadata
- [ ] Search: vector similarity search
- [ ] Synthesis: concepts, entities, digests
- [ ] Lifecycle management: pruning, supersession, duplicate detection
- [ ] Integration: calendar sync, mobile capture, web UI

## Tech stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.11+ |
| Package manager | `uv` |
| Vector search | `sqlite-vec` |
| Embeddings | `sentence-transformers` (local) or OpenAI API |
| LLM | OpenAI API |
| Vault | Obsidian |
| CLI | `typer` |

## License

MIT
