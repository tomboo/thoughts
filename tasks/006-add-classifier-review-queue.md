---
task_id: "006"
title: Add classifier proposal review queue
task_status: backlog
task_priority: high
task_created: 2026-08-23
task_due:
task_completed:
tags:
  - enhancement
  - mvp
  - review
  - llm
---

## Description

Add a first-class review queue for classifier proposals so model output can be approved, rejected, or edited before it updates canonical state.

The current classifier path validates output and sends low-confidence proposals to `sync_issues`. That is useful as a safety gate, but the MVP needs a clearer user workflow for reviewing model suggestions.

## Acceptance Criteria

- [ ] Review item storage is designed for classifier proposals.
- [ ] Proposal payloads preserve the exact model output and validation result.
- [ ] Approving a proposal applies only allowed canonical fields.
- [ ] Rejecting a proposal records the decision without mutating the thought.
- [ ] Editing a proposal before approval is either supported or explicitly deferred.
- [ ] CLI commands or Markdown projections expose pending review items.
- [ ] Tests cover approve, reject, invalid output, and low-confidence proposal behavior.

## Notes

- Do not allow high-impact semantic guesses to become silent canonical writes.
- Keep the review queue narrow before adding synthesis or pruning workflows.
