# Work Smarter product vision

## Outcome

Work Smarter is a text-first personal execution system for an engineer who wants
the benefits of rigorous GTD without performing clerical maintenance.

The first product is GTD. Project management, User Story Mapping, TBP,
Confluence publishing, and other capabilities are separate features that share
the same workspace contracts without sharing state machines.

## Product principles

1. Markdown is the source of truth; databases and views are projections.
2. Capture must be faster than deciding where an item belongs.
3. The system moves and transforms files; the user does not copy or sort them.
4. One current task is the default. More work in progress requires an explicit
   override.
5. A project is an outcome that needs more than one action, and every active
   project needs a visible next step.
6. Calendar dates are reserved for real date-specific commitments. A desired
   completion date is not silently treated as a calendar commitment.
7. Metrics are for reflection and system improvement, not self-punishment.
8. Every entity has a stable ID and every state transition is auditable.
9. Extension features depend on public contracts, never on GTD internals.

## Target user

The initial user is a single software/systems engineer working primarily in VS
Code. They prefer keyboard-driven flows and inspectable text, but will not
maintain folders, duplicate metadata, or manually move captured material.

## Non-goals for the first release

- General project-management scheduling, Gantt, QCD, or EVM
- User Story Mapping
- TBP or issue-driven problem solving
- Confluence synchronization
- Multi-user collaboration and permissions
- AI prioritization or automatic decision-making
- A standalone web frontend or mobile application

