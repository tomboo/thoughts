---
adr_id: "0001"
title: Use SQLite as canonical store and Markdown as Obsidian projection
status: accepted
date: 2026-08-23
deciders:
  - Tom
supersedes: []
superseded_by:
tags:
  - adr
---

# ADR 0001: Use SQLite as Canonical Store and Markdown as Obsidian Projection

## Context

The original design made Markdown files the source of truth and SQLite a rebuildable intelligence layer. That keeps the system highly portable and human-readable, but it also puts consistency pressure on YAML frontmatter, human edits, and file-level conventions.

The user has previously found consistency difficult to maintain when Markdown is canonical. This project needs a stronger schema boundary while preserving Obsidian as the human-facing interface.

## Decision

SQLite is the canonical data store. Markdown files are generated and synchronized projections for Obsidian.

Canonical state includes stable IDs, types, statuses, task state, dates, tags, links, entity references, processing logs, embeddings metadata, and sync state. Markdown files remain readable and editable, but imports from Markdown must be validated before they update canonical SQLite state.

## Consequences

- The system can enforce schema constraints, uniqueness, foreign keys, and transactional writes.
- Obsidian remains useful for reading, linking, and light manual editing.
- `thoughts sync` becomes a real import/validation boundary, not a blind file scan.
- The database must be backed up because it is no longer disposable cache.
- Markdown export must define generated-section boundaries to avoid overwriting human-authored content.

## Alternatives Considered

- **Markdown canonical, SQLite disposable**: simpler and more portable, but weaker for consistency and harder to validate over time.
- **Postgres canonical**: stronger for multi-user/server use, but premature for a local-first personal project because it adds service lifecycle, access control, backup, and hosting complexity.

## Links

- [[DESIGN]]
- [[2026-08-23-design-review]]
