# Tasks

A minimal, portable task system: one Markdown file per task, plain YAML frontmatter, and one Obsidian Base as the UI.

This mirrors the lightweight pattern used in `youtube-watch`: no plugin, no CLI requirement, and no database dependency for project-management metadata.

## Layout

```text
tasks/
  README.md
  _template.md
  001-some-task.md
bases/
  tasks.base
```

## Filenames

Use `NNN-kebab-slug.md`.

The number is the task's stable identity, mirrored in `task_id`. Numbers are never reused, including for cancelled or deleted tasks.

## Frontmatter

```yaml
---
task_id: "001"
title: Short imperative statement of the task
task_status: todo
task_priority: medium
task_created: 2026-08-23
task_due:
task_completed:
tags: []
---
```

| Field | Required | Notes |
|---|---|---|
| `task_id` | yes | Quoted string matching the filename prefix. |
| `title` | yes | Action-oriented task title. |
| `task_status` | yes | `backlog`, `todo`, `doing`, `done`, or `cancelled`. |
| `task_priority` | yes | `high`, `medium`, or `low`. |
| `task_created` | yes | `YYYY-MM-DD`, set once. |
| `task_due` | no | Real deadlines only. |
| `task_completed` | no | Set only for `done` or `cancelled`. |
| `tags` | no | Obsidian tag property. |

## Workflow

1. Copy [_template.md](./_template.md) to the next `NNN-slug.md`.
2. Fill in the frontmatter.
3. Track active work in [../bases/tasks.base](../bases/tasks.base).
4. Move work by editing `task_status`.
5. Set `task_completed` when moving to `done` or `cancelled`.

Keep the system intentionally small. Relationships and context belong in the task body as wikilinks and notes.
