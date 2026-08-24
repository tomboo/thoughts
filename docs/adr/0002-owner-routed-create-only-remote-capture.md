---
adr_id: "0002"
title: Route remote capture through the owner as create-only requests over SSH
status: accepted
date: 2026-08-23
deciders:
  - Tom
supersedes: []
superseded_by:
tags:
  - adr
---

# ADR 0002: Route Remote Capture Through the Owner as Create-Only Requests Over SSH

## Context

[[0001-sqlite-canonical-markdown-projection]] makes SQLite canonical, and task
`001` gave that database a single owner machine. That leaves the obvious gap:
the MacBook and iPhone still need to add thoughts, and SQLite does not tolerate
several machines writing the same file.

The tempting shortcuts all fail in the same way. A synced copy of the database
across devices is multi-writer SQLite wearing a disguise. A local fallback
database "just until the owner is back" silently forks the corpus. Exposing the
database file over the network makes every client a writer with full schema
access.

Connectivity is not the hard part — Tailscale already solves reaching the owner
from anywhere. The hard part is keeping one writer while letting several devices
originate thoughts, and being honest about what happens when the network drops
mid-request.

## Decision

Non-owner devices never write canonical SQLite. They send one JSON capture
request to the owner, which validates it and performs exactly one create.

- **Transport is SSH.** `ssh owner thoughts receive` starts a short-lived
  process on the owner. There is no daemon, no listening port, and no second
  credential system.
- **The surface is one verb.** `thoughts receive` creates. It cannot edit,
  delete, change status, or read. Remote edit and search stay out of scope.
- **Requests are idempotent.** A client-generated `request_id` is recorded in
  `capture_requests` in the same transaction as the thought. Replaying a
  request returns the original thought id instead of creating a second thought.
- **Provenance is owner-assigned.** The owner sets `source` to
  `remote:<origin>` from the validated origin label. A client cannot claim to
  be a local `cli` write.
- **Unknown fields are rejected.** A newer client fails loudly against an older
  owner rather than silently dropping data.
- **Offline queues, it does not fork.** An unreachable owner makes the client
  spool the request to local disk. It never creates a local database.

Tailscale supplies the route when the client is off-LAN. It changes the
address, not the trust model.

## Consequences

- Capture works from any device that can hold an SSH key, with no service to
  operate and nothing exposed to the network.
- Retry after a lost response is safe, which is the property that makes capture
  from a phone on a flaky connection trustworthy.
- The owner must be reachable for a capture to land immediately; otherwise the
  thought waits in the spool until `thoughts remote flush`. This is the intended
  trade — a delayed thought is recoverable, a forked database is not.
- The capture path is only as narrow as the SSH authorization behind it. A
  general-purpose shell key can do far more than capture. Constraining the key
  to a forced command (`command="thoughts receive"` in `authorized_keys`) is the
  natural follow-up and is not yet done.
- Two devices editing the same thought is still unsolved, because remote edit is
  deliberately not built. Whatever solves it will need a conflict story that
  create-only capture does not.

## Alternatives Considered

- **HTTP receiver on the owner.** More conventional and easier to call from iOS
  Shortcuts without a shell app, but it means a daemon, a bind address, a
  token, and a web dependency in a project whose only runtime dependency is
  `pyyaml` — all to move one JSON object over a channel SSH already provides.
- **Git as the transport**: each device commits a capture file, the owner
  imports on pull. Works offline by construction, but makes Git the write path
  for canonical data, which task `001` explicitly ruled out, and turns every
  capture into a merge.
- **Shared/synced SQLite over Tailscale or iCloud.** Simplest to describe and
  the most dangerous: it is multi-writer SQLite with extra steps, and it
  corrupts quietly.
- **Owner-side inbox folder watched for dropped files.** No protocol to write,
  but no validation boundary, no idempotency, and it depends on broad writable
  filesystem sharing.

## Links

- [[0001-sqlite-canonical-markdown-projection]]
- [[2026-08-23-task-005-owner-routed-remote-capture]]
- [[2026-08-23-database-owner-handoff]]
- [[remote-capture]]
