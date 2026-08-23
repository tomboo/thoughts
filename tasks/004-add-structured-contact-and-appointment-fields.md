---
task_id: "004"
title: Add structured contact and appointment fields
task_status: backlog
task_priority: high
task_created: 2026-08-23
task_due:
task_completed:
tags:
  - enhancement
  - mvp
  - schema
---

## Description

Add a narrow structured metadata model for contact and appointment thoughts while preserving the raw thought body as canonical context.

The immediate use case is capturing a contact such as a physician, their organization/specialty, appointment date/time, notes, and a simple rating without leaving all of that information trapped in free text.

## Acceptance Criteria

- [ ] The MVP fields for contacts are defined, including name, organization, and role or specialty.
- [ ] The MVP fields for appointments are defined, including date, optional time, notes, and linked contact.
- [ ] Rating support is either included as a controlled field or explicitly deferred.
- [ ] Raw thought body remains preserved and searchable.
- [ ] Migration and rollback behavior are documented before schema changes are applied.
- [ ] Tests cover capture, storage, export, sync, and search for a contact appointment example.

## Notes

- Start narrow; do not build a full CRM.
- Prefer structured fields beside the raw thought rather than replacing the original body.
