# ADR 0006: Explainable scheduling and an offline Gantt projection

- Status: Accepted
- Date: 2026-08-03

## Outcome

Managed Project schedules are calculated by a domain service from Markdown/YAML-authoritative project
metadata. Gantt is a disposable projection produced through `GanttRenderer`; it is never a source of truth.

## Facts

- The repository contract makes Markdown/YAML and append-only events authoritative.
- The previous scheduler supported only Finish-to-Start dependencies over calendar days.
- The architecture Draft 0.1 requires four dependency types, lead/lag, working calendars, float,
  critical path, baseline/current comparison, progress, dependency lines, filter, zoom, and a today marker.
- The Draft leaves the Gantt library and full web frontend technology UNKNOWN.

## Considered paths

1. Add a browser Gantt dependency. This reduces renderer code but introduces an offline asset/version and
   supply-chain lifecycle.
2. Generate a self-contained HTML/CSS/SVG/JavaScript projection. This keeps export deterministic and works
   without a CDN, at the cost of owning a focused renderer.

Decision: path 2 for v1. `HtmlGanttRenderer` implements the port and can be replaced without importing a
renderer into the domain model.

## Scheduling model

Dates are normalized to integer working-day ticks. Every relation becomes one precedence inequality:

```text
successor_start >= predecessor_start + weight

FS: predecessor_duration + lag
SS: lag
FF: predecessor_duration - successor_duration + lag
SF: -successor_duration + lag
```

A forward pass derives earliest dates. A reverse pass derives latest dates; their differences yield total
and free float. Negative lag is a lead. Cycles and missing predecessors are rejected before persistence.

The default calendar remains seven days for compatibility with existing projects. A project opts into a
business week and holiday exceptions explicitly.

## Consequences and unknowns

- Baselines now retain an immutable schedule snapshot alongside the existing content hash.
- Explanations identify the driving predecessor, relation, lead/lag, explicit constraint, and skipped
  non-working dates.
- Scenario persistence and a full application web frontend remain UNKNOWN and are not implied by this ADR.
- Database source-of-truth migration remains a separate architecture slice because it conflicts with the
  currently published workspace contract.
