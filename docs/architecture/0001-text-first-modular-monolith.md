# ADR 0001: Text-first modular monolith

- Status: Superseded by ADR 0003
- Date: 2026-07-23

## Context

Work Smarter needs a fast GTD workflow now and separately evolving project
management, User Story Mapping, and publishing features later. The primary
interface is VS Code, but the domain must remain usable from a CLI, an HTTP API,
and automation.

## Considered approaches

### VS Code extension owns the domain

This gives a quick UI but couples persistence and workflow rules to TypeScript
and makes headless use and future features duplicate logic.

### Database is the source of truth

This makes queries convenient but makes ordinary Git, direct inspection, and
long-term portability secondary export concerns.

### Python core with Markdown source and derived indexes

This keeps every durable item readable, lets the CLI and API share one domain,
and permits a thin VS Code client. Query indexes can be rebuilt.

## Decision

Use a modular Python application with these boundaries:

- `work_smarter.gtd`: GTD entities, state machine, invariants, and use cases
- `work_smarter.storage`: feature-neutral Markdown frontmatter, registry-based
  codecs, locking, and append-only events
- `work_smarter.composition`: enabled feature selection and codec composition
- `work_smarter.project_management`: a separate, initially empty feature
- `work_smarter.features`: the public extension registry
- `work_smarter.cli`: keyboard/script interface
- `work_smarter.api`: local HTTP interface

Markdown and YAML frontmatter are authoritative. JSON Lines events are
authoritative history. Any SQLite index is a disposable projection.

This source-of-truth decision was superseded on 2026-08-02. See
[ADR 0003](0003-hybrid-source-of-truth-and-local-application-server.md).

## Consequences

- Direct file edits remain possible and must be validated rather than hidden.
- File writes must be atomic and use safe YAML loading.
- Commands, APIs, and future UI must call application services instead of
  reproducing state transitions.
- Extension features communicate with stable IDs and public events, not private
  GTD objects.
