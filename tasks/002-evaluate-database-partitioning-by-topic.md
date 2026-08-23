---
task_id: "002"
title: Evaluate database partitioning by major subject or topic
task_status: backlog
task_priority: medium
task_created: 2026-08-23
task_due:
task_completed:
tags:
  - enhancement
  - architecture
---

## Description

Evaluate whether the Thoughts SQLite store should be partitioned or sharded by major subject area, topic, or corpus boundary.

This is an architecture enhancement, not an implementation decision. The goal is to understand whether partitioning would improve maintainability, privacy boundaries, backup/restore, sync ergonomics, or performance without weakening SQLite as the canonical source of truth.

## Acceptance Criteria

- [ ] Candidate partition boundaries are documented, such as project, life area, source, or topic.
- [ ] Benefits and costs are compared against a single canonical database.
- [ ] Query, search, export, backup, and sync behavior are evaluated for both designs.
- [ ] Cross-topic references and global search requirements are explicitly addressed.
- [ ] A recommendation is recorded before any schema or storage migration is implemented.

## Notes

- Treat this as design research until there is a written decision.
- Avoid creating multiple writable canonical stores without a clear ownership and merge policy.
