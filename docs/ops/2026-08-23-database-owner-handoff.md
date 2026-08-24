---
title: Database Owner Handoff — iMac
date: 2026-08-23
status: active
tags:
  - ops
  - infrastructure
  - ownership
related:
  - "[[2026-08-24-task-001-database-owner-transfer]]"
  - "[[001-transfer-ownership-of-database-to-imac]]"
---

# Database Owner Handoff — iMac

## Current Owner

| Field | Value |
|---|---|
| Canonical owner | `Toms-iMac.local` |
| Checkout path | `/Users/tom/Projects/hermes-projects/thoughts` |
| Database path | `.thoughts/thoughts.sqlite` |
| Transfer date | 2026-08-23 |
| Commit at transfer | `758bfbe` |
| Previous owner | `Toms-MacBook-Air.local` (now non-canonical) |

## Pre-Transfer State (MacBook)

| Metric | Value |
|---|---|
| thoughts | 8 |
| projections | 8 |
| unresolved sync issues | 0 |
| latest migration | 2 |
| doctor | 0 errors, 0 warnings |

Post-transfer iMac `thoughts status` matched these counts exactly.

## Canonical Write Commands (iMac Only)

- `thoughts capture`
- `thoughts sync --apply`
- `thoughts process --apply`
- future remote capture receiver commands

The iMac is the only machine permitted to run these. Because `uv` is not on the
non-interactive `PATH` there, remote invocations use:

```bash
ssh toms-imac.local "export PATH=/opt/homebrew/bin:\$PATH; \
  uv run --directory /Users/tom/Projects/hermes-projects/thoughts thoughts <command>"
```

## Non-Owner Machines

- **MacBook Air** — does not run canonical write commands. Its former runtime is
  archived at `.thoughts.noncanonical-20260823/` so any accidental local write
  fails visibly with `database is not initialized`. It consumes thoughts by
  pulling Markdown projections from Git.
- **iPhone** — no capture path yet. Deferred to tasks `003` and `005`.

Non-owner machines must not create a competing writable `.thoughts/thoughts.sqlite`.

## Backups

- Transfer backup: `backups/thoughts-20260823-205652.sqlite` (present on both
  machines; `PRAGMA integrity_check` = `ok` on each).
- `backups/` is untracked — `*.sqlite` is covered by `.gitignore`.

## Rollback Path

Rollback is allowed only until remote capture channels (tasks `003`/`005`) are enabled.

1. Stop all iMac writes.
2. Preserve the iMac runtime:

   ```bash
   sqlite3 .thoughts/thoughts.sqlite \
     ".backup 'backups/thoughts-imac-rollback-$(date +%Y%m%d-%H%M%S).sqlite'"
   ```

3. On the MacBook, restore the archived runtime:

   ```bash
   mv .thoughts.noncanonical-20260823 .thoughts
   ```

4. Re-run `uv run thoughts status` and `uv run thoughts doctor` on the restored owner.
5. Record why ownership reverted and replay any iMac-only thoughts by hand.

Do not delete `.thoughts.noncanonical-20260823/` until the rollback window closes.
