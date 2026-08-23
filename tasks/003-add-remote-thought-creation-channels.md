---
task_id: "003"
title: Add remote thought creation channels from MacBook and iPhone
task_status: backlog
task_priority: medium
task_created: 2026-08-23
task_due:
task_completed:
tags:
  - enhancement
  - infrastructure
  - capture
---

## Description

Add remote channels that allow at least thought creation from other devices, starting with MacBook and iPhone.

The goal is low-friction capture without creating competing writable SQLite owners. Remote channels may use Tailscale for private connectivity and Hermes for an approved execution path, but the design must preserve a clear database owner and reviewed write boundary.

## Acceptance Criteria

- [ ] Supported source devices are documented, including MacBook and iPhone.
- [ ] The canonical database owner for remote writes is documented.
- [ ] A Tailscale connectivity path is defined without treating VPN access as a sandbox.
- [ ] A Hermes-mediated capture path is defined with approvals or other write controls.
- [ ] Thought creation works from MacBook without local canonical database writes.
- [ ] Thought creation works from iPhone through a documented capture route.
- [ ] Duplicate, offline, and retry behavior is documented before broader capture features are added.

## Notes

- Start with create-only capture; defer remote edit, sync, and search workflows.
- Prefer a narrow command/API that appends one canonical thought through the owner machine.
- Do not expose unrestricted database or filesystem writes over the remote channel.
