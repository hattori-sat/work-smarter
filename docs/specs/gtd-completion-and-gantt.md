# GTD completion and interactive Gantt contract

- Status: Implemented on `feat/gtd-gantt-completion`
- Date: 2026-08-03
- Input: Work Smarter 4+1 Architecture Draft 0.1

## Outcome

Finish the missing GTD interaction surface and provide an explainable, offline managed-project Gantt while
preserving current workspace authority and public feature boundaries.

## GTD contract

- `GtdService.create_project()` creates a multi-action outcome without fabricating Inbox provenance.
- GTD project create/complete events are append-only and reload to the same state.
- `ws gtd <resource> <operation>` is canonical; historical root commands remain ergonomic aliases.
- `ws gtd action list --output picker` is stable text for Vim/fzf pipelines.
- `action open` and `project open` resolve unique ID prefixes and pass one workspace-contained path to
  `$EDITOR` as a fixed argument vector.
- HTTP exposes typed create/list/show project operations under `/api/gtd/projects`.

## Schedule contract

- Dependency types: Finish-to-Start, Start-to-Start, Finish-to-Finish, Start-to-Finish.
- `lag_days > 0` is lag; `lag_days < 0` is lead.
- Working calendars contain weekdays, non-working exceptions, and additional working exceptions.
- Output contains earliest/latest start and finish, total/free float, critical path, project finish,
  progress, owner, Jira display state, delay, and constraint violation.
- Calculation failure does not write a partial aggregate.
- `explain_schedule()` returns the date-driving reasons rather than an opaque date.

## Gantt contract

The HTML is self-contained and escapes all user-authored text. It contains WBS/phase, work items,
milestones, dependency lines, critical state, progress, latest baseline/current plan, delay, float, owner,
Jira state, text filter, zoom, and today marker. CLI and HTTP use the same renderer port.

## Explicit unknowns

- Project Scenario persistence/acceptance is UNKNOWN and remains a later slice.
- Jira synchronization is not implemented by this projection; `jira_status` is display metadata only.
- The architecture Draft's structured-data Database authority is not active in this slice.
