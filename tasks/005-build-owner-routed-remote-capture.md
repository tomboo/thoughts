---
task_id: "005"
title: Build owner-routed remote capture
task_status: done
task_priority: high
task_created: 2026-08-23
task_due:
task_completed: 2026-08-23
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

- [x] The database owner machine is documented.
- [x] MacBook can submit a new thought through the owner-routed path.
- [x] iPhone can submit a new thought through a documented route.
- [x] Remote capture does not write to a non-owner canonical SQLite database.
- [x] Offline, retry, and duplicate-submission behavior is documented.
- [x] The capture path has a narrow command or API surface.
- [x] Tests or manual verification steps prove owner-side SQLite receives the thought.

## Notes

- This overlaps with task `003`; keep `003` as architecture/channel design and use this task for the MVP implementation.
- Implementation plan: `docs/plans/2026-08-23-task-005-owner-routed-remote-capture.md`.
- Decision: `docs/adr/0002-owner-routed-create-only-remote-capture.md`.
- Operator runbook: `docs/ops/remote-capture.md`.
- Surface: `thoughts receive` on the owner, `thoughts remote capture|flush|status` on clients.
- Idempotency comes from a client-generated `request_id` recorded in `capture_requests` (migration 3).
- Tailscale can provide private connectivity, but it is not a write-safety boundary.
