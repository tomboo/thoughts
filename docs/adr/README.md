# Architecture Decision Records

ADRs record durable architecture decisions, especially decisions that constrain implementation or reverse an earlier assumption.

## Layout

```text
docs/adr/
  README.md
  _template.md
  adr.schema.json
  0001-sqlite-canonical-markdown-projection.md
  0002-owner-routed-create-only-remote-capture.md
```

## Filenames

Use `NNNN-kebab-slug.md`.

Numbers are stable and never reused. If a decision is superseded, leave the old ADR in place and set `status: superseded`.

## Frontmatter

```yaml
---
adr_id: "0001"
title: Short decision title
status: accepted
date: 2026-08-23
deciders:
  - Tom
tags:
  - adr
---
```

The frontmatter shape is described in [adr.schema.json](./adr.schema.json). The schema covers metadata; the body still follows the template.

## Status Values

- `proposed` — written for review, not yet binding.
- `accepted` — current decision.
- `superseded` — replaced by a newer ADR.
- `deprecated` — no longer recommended but not directly replaced.
- `rejected` — considered and deliberately not chosen.

## Body

Each ADR should include:

- Context
- Decision
- Consequences
- Alternatives considered
- Links
