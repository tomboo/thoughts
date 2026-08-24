---
task_id: "001"
title: Transfer ownership of database to iMac
task_status: done
task_priority: medium
task_created: 2026-08-23
task_due:
task_completed: 2026-08-23
tags:
  - infrastructure
---

## Description

Move operational ownership of the Thoughts SQLite database to the iMac so live database writes have a single machine owner.

## Acceptance Criteria

- [x] Current database location and active writer are documented.
- [x] iMac has the canonical project checkout and initialized `.thoughts/thoughts.sqlite`.
- [x] Non-owner machines are documented as read-only or sync-only for database writes.
- [x] Backup/export path is verified after the ownership transfer.
- [x] A handoff note records the final owner, date, and rollback path.

## Notes

- Keep SQLite as the source of truth.
- Do not create competing writable database copies during the transfer.
- Implementation plan: `docs/plans/2026-08-24-task-001-database-owner-transfer.md`.
- Handoff note: `docs/ops/2026-08-23-database-owner-handoff.md`.
- Owner is now `Toms-iMac.local`; the MacBook runtime is archived at `.thoughts.noncanonical-20260823/`.
