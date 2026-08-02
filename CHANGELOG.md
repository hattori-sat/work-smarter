# Changelog

All notable changes to Work Smarter are documented here.

## Unreleased

## 1.0.0 - 2026-08-03

### Added

- Rigorous GTD task tickets, one-piece-flow workflow, daily dashboard, and resumable weekly review.
- Independent Knowledge notes with templates, links, backlinks, search, promotion, and doctor.
- Managed projects with WBS, dependencies, schedule and critical path, QCD, registers, and projections.
- Provider-neutral publishing and Confluence Cloud dry-run/push/pull with conflict detection.
- VS Code tasks, typed OpenAPI contracts, a cross-feature overview, and checksummed workspace archives.
- SQLite migrations, append-only activity events, outbox schema, and consistent online snapshots.
- A selectable database port and adapter registry with backend-aware backup manifests.
- A canonical `ws gtd` command tree with standalone GTD outcome creation, typed project API,
  ID-prefix selection, and editor integration.
- Working-calendar scheduling with all four precedence types, lead/lag, explainable CPM fields,
  immutable baselines, and an offline interactive HTML Gantt.
- Database-owned structured entity/activity state with one-time legacy import and read-only
  Markdown/JSONL compatibility projections.
- Durable operation-journal recovery, leased transactional outbox delivery, typed system API,
  loopback HTTP client, and canonical `ws system` commands.

### Security

- Provider credentials remain in environment variables or keyring and are excluded from workspace files.
- Workspace restore verifies member paths, a manifest, and SHA-256 checksums before extraction.
- SQL statements are static literals with bound values, enforced by an architecture test.
- SQLite restore rejects sidecar-based archives and verifies database integrity before extraction.
- Workspace backup rejects database symlinks that escape the workspace boundary.
