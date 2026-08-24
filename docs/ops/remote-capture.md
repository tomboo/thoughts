---
title: Remote Capture Runbook
date: 2026-08-23
status: active
tags:
  - ops
  - capture
  - infrastructure
related:
  - "[[2026-08-23-database-owner-handoff]]"
  - "[[0002-owner-routed-create-only-remote-capture]]"
  - "[[2026-08-23-task-005-owner-routed-remote-capture]]"
---

# Remote Capture Runbook

How to add a thought from a device that does not own the database.

The owner is the iMac (see [the owner handoff note](./2026-08-23-database-owner-handoff.md)).
Every other device sends the owner one create-only request and waits for a
confirmed thought id. No other device writes canonical SQLite, ever.

## The Shape Of It

```text
MacBook / iPhone                       iMac (owner)
  thoughts remote capture "..."
        │  one JSON request
        └── ssh ────────────────►  thoughts receive
                                        │
                                        ├── capture_requests: seen this
                                        │   request_id before?
                                        │      yes → return the same
                                        │            thought id, write nothing
                                        │      no  → create thought + record
                                        │            request, one transaction
        ◄──── one JSON response ────────┘
              {"status": "created", "thought_id": "th_..."}

  owner unreachable?
        └── request queued in ~/.local/state/thoughts/spool
            drained later by `thoughts remote flush`
```

## Owner Setup (iMac, Once)

```bash
uv run thoughts init      # idempotent; applies migration 3 (capture_requests)
uv run thoughts status    # confirm latest_migration: 3
```

The owner needs nothing running. `thoughts receive` is started by the incoming
SSH session and exits when the request is done.

## MacBook Setup

`~/.config/thoughts/remote.json`:

```json
{
  "owner_command": [
    "ssh", "toms-imac.local",
    "export PATH=/opt/homebrew/bin:$PATH; uv run --directory /Users/tom/Projects/hermes-projects/thoughts thoughts receive --export"
  ],
  "origin": "macbook",
  "timeout_seconds": 20
}
```

`--export` refreshes the Markdown projection on the owner so the new thought is
ready to commit. Drop it if you would rather batch exports.

Environment variables override the file, which is handy for testing:
`THOUGHTS_OWNER_COMMAND`, `THOUGHTS_ORIGIN`, `THOUGHTS_SPOOL_DIR`,
`THOUGHTS_REMOTE_CONFIG`.

Then:

```bash
uv run thoughts remote capture "Buy sourdough starter" --type task --tag errands
# created: req_2f1c...: th_9ab4...

uv run thoughts remote status
uv run thoughts remote flush
```

`origin` must match `^[a-z0-9][a-z0-9-]{0,31}$`. The owner turns it into the
thought's `source` as `remote:macbook` — a client cannot choose its own
`source`, so a remote write can never masquerade as a local one.

## iPhone Route

The iPhone has no Python, so it sends the same JSON over the same SSH channel
from a shell app. Two working options:

**Blink Shell (recommended).** Blink holds an SSH key and can be driven by
Shortcuts.

1. Add the iPhone's public key to `~/.ssh/authorized_keys` on the iMac.
2. Install Tailscale on the phone so `toms-imac` resolves off the home network.
3. Build a Shortcut:
   - *Ask for Input* → text, prompt "Thought".
   - *Text* action holding the request JSON, with the input substituted into
     `body` and a fresh UUID in `request_id`:

     ```json
     {"protocol_version":1,"request_id":"req_UUID","origin":"iphone",
      "thought":{"body":"INPUT","type":"inbox"}}
     ```

     Use the Shortcuts *UUID* action for `request_id` — that is what makes a
     retry safe.
   - *Run Script Over SSH* (or Blink's Shortcut action) piping that text to:

     ```bash
     export PATH=/opt/homebrew/bin:$PATH
     uv run --directory /Users/tom/Projects/hermes-projects/thoughts thoughts receive --export
     ```

   - *Show Result* so you see `created` and the thought id.
4. Add the Shortcut to the home screen or to a Back Tap.

**a-Shell** works the same way with its built-in `ssh` and `pbpaste`, if you
prefer capturing from the clipboard rather than a prompt.

The phone has no spool. If the Shortcut fails, it failed loudly and nothing was
written — run it again. Because the same Shortcut generates a new `request_id`
per run, a re-run after a *visible* failure creates one thought; a re-run after
an *ambiguous* failure (spinner, then nothing) could create a second. Keep the
`request_id` from the failed run if you want to be certain, or reconcile later
with `thoughts search`.

## Offline, Retry, And Duplicate Behavior

**Duplicates.** Every request carries a client-generated `request_id`. The owner
records it in `capture_requests` in the same transaction as the thought, and
looks it up before creating anything. Replaying a request id returns
`status: "duplicate"` with the original thought id and writes nothing.

**Retries.** Reuse the same `request_id` when retrying the same thought. Then a
retry is always safe: either the first attempt never landed and this one
creates the thought, or it did land and this one reports `duplicate`. The
MacBook client does this automatically — a spooled request keeps its id.

**Offline.** If the owner cannot be reached, `thoughts remote capture` writes
the request to `~/.local/state/thoughts/spool` and reports `spooled`. It does
not create a local database. Nothing is lost and nothing is forked.

**Flushing.** `thoughts remote flush` drains the spool oldest-first and stops at
the first transport failure, so a still-offline owner does not produce a wall of
errors. A file is deleted only after the owner confirms `created` or
`duplicate`. A request the owner *rejects* — a bad type, a malformed date —
moves to `spool/rejected/` instead of retrying forever; fix or discard those by
hand.

**Ordering.** The spool flushes in the order requests were made, but a thought's
`created_at` is stamped when the owner receives it, not when you typed it. The
request's `submitted_at` is kept in `capture_requests` if you need the original
moment.

## Verifying

On the owner:

```bash
uv run thoughts status          # remote_capture_requests should have moved
uv run thoughts doctor
uv run thoughts search "the text you captured"
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `remote capture is not configured` | No `owner_command` or `origin` | Write `~/.config/thoughts/remote.json`, or set `THOUGHTS_OWNER_COMMAND` and `THOUGHTS_ORIGIN` |
| `could not run owner command` | Bad path in `owner_command`, SSH key rejected | Run the `ssh ...` part by hand and read its error |
| `owner command returned no response` | `uv`/`thoughts` not on the owner's non-interactive `PATH` | Keep the `export PATH=/opt/homebrew/bin:$PATH` prefix in `owner_command` |
| `owner command returned an unusable response` | Something on the owner printed to stdout before the JSON | Make sure the remote command emits nothing but the response |
| `unsupported protocol_version` | Client newer than the owner | `git pull` on the owner and re-run `thoughts init` |
| `unknown request field(s)` | Client newer than the owner | Same as above |
| `rejected` with an invalid-type error | Bad `--type`/`--priority`/`--due` | Fix the spooled file in `spool/rejected/` and move it back, or discard it |
| Thought created but no Markdown file | Owner ran without `--export` | Run `thoughts export-md` on the owner |

## Known Gaps

- The SSH key used for capture is a general shell key. Narrowing it with
  `command="…thoughts receive"` in `authorized_keys` is the obvious hardening
  step and is not done yet.
- The iMac cannot push to GitHub (see the owner handoff note), so remotely
  captured thoughts land in owner SQLite but their projections do not reach
  other machines until that is fixed.
- The iPhone route has no spool, so it needs the owner reachable at capture time.
