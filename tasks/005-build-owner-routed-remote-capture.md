---
task_id: "005"
title: Build owner-routed remote capture
task_status: backlog
task_priority: high
task_created: 2026-08-23
task_due:
task_completed:
tags:
  - enhancement
  - mvp
  - infrastructure
  - capture
---

## Description

Build a create-only remote capture path so MacBook and iPhone can add thoughts through the canonical owner machine without creating competing writable SQLite databases.

This task implements the practical MVP slice of remote channels: reliable thought creation first, with edit, delete, sync, and search left for later.

## Acceptance Criteria

- [ ] The database owner machine is documented.
- [ ] MacBook can submit a new thought through the owner-routed path.
- [ ] iPhone can submit a new thought through a documented route.
- [ ] Remote capture does not write to a non-owner canonical SQLite database.
- [ ] Offline, retry, and duplicate-submission behavior is documented.
- [ ] The capture path has a narrow command or API surface.
- [ ] Tests or manual verification steps prove owner-side SQLite receives the thought.

## Notes

- This overlaps with task `003`; keep `003` as architecture/channel design and use this task for the MVP implementation.
- Tailscale can provide private connectivity, but it is not a write-safety boundary.
