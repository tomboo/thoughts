---
title: Task 001 Database Owner Transfer Plan
date: 2026-08-24
status: draft
tags:
  - plan
  - infrastructure
  - ownership
related:
  - "[[001-transfer-ownership-of-database-to-imac]]"
  - "[[003-add-remote-thought-creation-channels]]"
  - "[[005-build-owner-routed-remote-capture]]"
---

# Task 001 Database Owner Transfer Plan

## Goal

Move operational ownership of the Thoughts SQLite database to the iMac before designing or implementing remote capture channels.

The end state is one canonical writer: the iMac owns `.thoughts/thoughts.sqlite`, while MacBook and iPhone paths submit create-only requests through the owner path later in tasks `003` and `005`.

## Non-Goals

- Do not implement remote capture in this task.
- Do not add email, iPhone, Hermes, or Tailscale write paths yet.
- Do not expose direct SQLite access over the network.
- Do not make Git the canonical database transport.
- Do not support multi-writer SQLite.

## Preconditions

- The current checkout is clean except for intentional planning/task-note edits.
- The current MacBook `.thoughts/thoughts.sqlite` can be opened by `thoughts status` and `thoughts doctor`.
- The iMac is reachable by the chosen operator channel, such as physical access, SSH over the local network, or SSH over Tailscale.
- The iMac has a project checkout at an agreed path, preferably `/Users/tom/Projects/hermes-projects/thoughts`.
- The transfer is scheduled during a quiet period when no other `thoughts capture`, `sync`, or `process` commands are running.

## Source Of Truth Decision

After this task, the iMac is the only machine allowed to run canonical write commands:

- `thoughts capture`
- `thoughts sync --apply`
- `thoughts process --apply`
- future remote capture receiver commands

Non-owner machines may run read-only commands against local projections or a copied database only when clearly labeled non-canonical. They must not create a competing writable `.thoughts/thoughts.sqlite`.

## Implementation Steps

### 1. Freeze And Inspect Current Owner

1. Stop any active Thoughts commands or agents that may write SQLite.
2. On the current machine, run:

   ```bash
   git status --short --branch
   uv run thoughts status
   uv run thoughts doctor
   ```

3. Record:
   - hostname
   - checkout path
   - database path
   - thought count
   - projection count
   - latest migration
   - current commit

### 2. Create A Transfer Backup

1. Export Markdown projections from the current owner:

   ```bash
   uv run thoughts export-md
   uv run thoughts doctor
   ```

2. Create a timestamped local backup of the SQLite runtime:

   ```bash
   mkdir -p backups
   sqlite3 .thoughts/thoughts.sqlite ".backup 'backups/thoughts-YYYYMMDD-HHMMSS.sqlite'"
   ```

3. Verify the backup opens:

   ```bash
   sqlite3 backups/thoughts-YYYYMMDD-HHMMSS.sqlite "PRAGMA integrity_check;"
   ```

4. Commit and push any intentional Markdown projection or task documentation changes before moving the canonical owner.

### 3. Prepare The iMac Checkout

1. On the iMac, clone or fast-forward the repository:

   ```bash
   git clone https://github.com/tomboo/thoughts.git /Users/tom/Projects/hermes-projects/thoughts
   cd /Users/tom/Projects/hermes-projects/thoughts
   git pull --ff-only
   ```

2. Install dependencies if needed:

   ```bash
   uv sync
   ```

3. Confirm the iMac checkout can run the CLI:

   ```bash
   uv run thoughts --version
   ```

### 4. Install Canonical Runtime On The iMac

Preferred path: initialize from the repo and import or copy the current runtime only once.

1. If `.thoughts/` does not exist on the iMac:

   ```bash
   uv run thoughts init
   ```

2. Copy the backed-up SQLite file to the iMac runtime path using a controlled one-time transfer:

   ```bash
   cp /path/to/transferred/thoughts-YYYYMMDD-HHMMSS.sqlite .thoughts/thoughts.sqlite
   ```

3. Run owner-side checks on the iMac:

   ```bash
   uv run thoughts status
   uv run thoughts doctor
   ```

4. Compare iMac status against the pre-transfer recorded counts.

### 5. Mark Non-Owner Machines Read-Only

1. On the MacBook, rename or archive the old local runtime so accidental writes fail visibly:

   ```bash
   mv .thoughts .thoughts.noncanonical-YYYYMMDD
   ```

2. Do not delete the old runtime until the iMac owner has passed verification and the rollback window has closed.
3. Add or update handoff documentation stating:
   - iMac owns the canonical database.
   - MacBook does not run canonical write commands locally.
   - iPhone capture is deferred until tasks `003` and `005`.

### 6. Verify Owner-Only Writes

1. On the iMac, create a small transfer verification thought:

   ```bash
   uv run thoughts capture "Transfer verification: iMac owns the canonical Thoughts database." --title "iMac database owner verification" --type note --tag infrastructure --tag verification
   uv run thoughts export-md
   uv run thoughts doctor
   ```

2. Commit and push the resulting Markdown projection from the iMac.
3. On the MacBook, pull the repo and confirm the projection appears without running a local SQLite write.

## Rollback Plan

Rollback is allowed only before remote capture channels are enabled.

1. Stop iMac writes.
2. Preserve the iMac runtime:

   ```bash
   sqlite3 .thoughts/thoughts.sqlite ".backup 'backups/thoughts-imac-rollback-YYYYMMDD-HHMMSS.sqlite'"
   ```

3. Restore the archived MacBook runtime:

   ```bash
   mv .thoughts.noncanonical-YYYYMMDD .thoughts
   ```

4. Re-run `uv run thoughts status` and `uv run thoughts doctor` on the restored owner.
5. Document why ownership reverted and whether any iMac-only thoughts need manual replay.

## Acceptance Mapping

| Task 001 criterion | Plan step |
|---|---|
| Current database location and active writer are documented. | Step 1 |
| iMac has the canonical project checkout and initialized `.thoughts/thoughts.sqlite`. | Steps 3 and 4 |
| Non-owner machines are documented as read-only or sync-only for database writes. | Step 5 |
| Backup/export path is verified after the ownership transfer. | Steps 2, 4, and 6 |
| A handoff note records the final owner, date, and rollback path. | Steps 5 and 6 |

## Follow-On Sequence

Only after task `001` is complete:

1. Use task `003` to design MacBook and iPhone creation channels against the iMac owner boundary.
2. Use task `005` to implement the narrow owner-routed capture MVP.
3. Keep Tailscale as private connectivity, not a write authorization or sandbox boundary.
