# Thoughts

A self-organizing personal knowledge system built on [Obsidian](https://obsidian.md) with a [SQLite](https://www.sqlite.org) intelligence layer.

## The idea

You dump raw thoughts — ideas, tasks, facts, reminders, anything worth keeping — into a single inbox. A processing pipeline uses an LLM to classify each thought, extract structured metadata (due dates, priorities, tags), and file it with appropriate frontmatter properties. Over time, embeddings stored in SQLite enable semantic search and the emergence of higher-level synthesized objects: concepts, entities, and digests.

The system is designed to **evolve**. Raw thoughts accumulate. The system processes them into structure. Synthesized objects emerge that connect and contextualize the corpus. A lifecycle model handles correction, supersession, and pruning so the knowledge base stays healthy as it grows.

## How it works

1. **Capture** — Drop a thought into `Inbox/` as a markdown file
2. **Process** — Run `thoughts process` to have the LLM classify, tag, and extract metadata
3. **Search** — Use `thoughts search` for semantic similarity search across all thoughts
4. **Synthesize** *(future)* — Run `thoughts synthesize` to detect emerging themes and generate concept pages
5. **Digest** *(future)* — Run `thoughts digest` to generate daily/weekly/monthly summaries

## Architecture

- **Obsidian vault** is the source of truth — markdown files with YAML frontmatter, human-readable, git-versionable
- **SQLite + sqlite-vec** is the intelligence layer — structured queries, embedding storage, vector similarity search
- **Flat structure** — all raw thoughts live in `Inbox/`; categorization is done via frontmatter properties, not physical folders
- **No file moving** — processing updates frontmatter in place; Obsidian Bases provides virtual groupings

## Status

**Design phase.** The full architecture is documented in [DESIGN.md](./DESIGN.md). Implementation is deferred.

### MVP (Phase 1)

- [ ] `thoughts init` — vault setup + SQLite schema
- [ ] `thoughts process` — inbox scan → LLM classify → frontmatter update → embed
- [ ] `thoughts search` — vector similarity search
- [ ] `thoughts status` — vault and DB overview
- [ ] `thoughts reprocess` — re-run classification on a single thought
- [ ] `thoughts reindex` — full vault rescan + rebuild

### Future

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
