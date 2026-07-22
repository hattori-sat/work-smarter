# GTD MVP requirements

## Core workflow

### Capture

- A user can capture plain text with one command.
- Capture never asks for a project, context, priority, or date.
- Captured material becomes one Markdown file in `inbox/`.
- Standard input and future adapters may call the same application service.
- A known next action can use one atomic quick-add operation without leaving an
  inbox item behind.

### Clarify

- The oldest inbox item is selected when no ID is supplied.
- Exactly one outcome is chosen: next action, project, waiting, scheduled,
  someday/maybe, reference, done now, or trash.
- The application creates the destination file and archives the raw capture.
- A project outcome requires its first next action in the same flow.

### Organize

- Next actions may carry contexts, energy, and an estimated duration.
- Waiting items require a person or external condition.
- Scheduled actions require a real date or time.
- Due dates remain distinct from scheduled dates and start constraints.

### Engage

- Focus candidates can be filtered by context, available minutes, and energy.
- Starting work is refused while another task is active unless the user
  explicitly switches.
- Starting, stopping, switching, and completing work are recorded as events.
- Waiting, blocked, and scheduled tasks can return to Next Actions without
  direct metadata editing.

### Reflect

- Daily status exposes the current task and immediate commitments.
- Weekly review exposes unprocessed inbox items, waiting follow-ups, stale or
  blocked actions, someday/maybe items, and active projects without a next
  action.
- A workspace doctor reports invalid Markdown metadata and broken relations.
- A daily status summarizes every task state, active projects, inbox size, and
  projects that need a next action.

## Required invariants

- Entity IDs are unique across the workspace.
- At most one task is `doing` by default.
- An active GTD project has at least one unfinished next, doing, waiting,
  scheduled, or blocked action.
- A waiting task has `waiting_for`.
- A scheduled task has `scheduled_for`.
- A blocked task has `blocked_reason`.
- A completed task has `completed_at`.
- Derived state can be rebuilt from Markdown and the append-only event log.

## Acceptance scenario

1. Initialize an empty workspace.
2. Capture five unrelated thoughts without classifying them.
3. Clarify them as a task, project plus first action, reference, someday item,
   and discarded item.
4. Filter next actions for a context and 30 minutes of availability.
5. Start one task and verify that starting another is refused.
6. Stop and complete the task, preserving elapsed time.
7. Run a weekly review and see the now-actionless project as needing attention.
8. Run workspace validation with no unreadable or duplicate entities.
