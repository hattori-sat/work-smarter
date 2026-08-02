# Changelog

All notable changes to Work Smarter are documented here.

## Unreleased

### Added

- Rigorous GTD task tickets, one-piece-flow workflow, daily dashboard, and resumable weekly review.
- Independent Knowledge notes with templates, links, backlinks, search, promotion, and doctor.
- Managed projects with WBS, dependencies, schedule and critical path, QCD, registers, and projections.
- Provider-neutral publishing and Confluence Cloud dry-run/push/pull with conflict detection.
- VS Code tasks, typed OpenAPI contracts, a cross-feature overview, and checksummed workspace archives.
- SQLite migrations, append-only activity events, outbox schema, and consistent online snapshots.

### Security

- Provider credentials remain in environment variables or keyring and are excluded from workspace files.
- Workspace restore verifies member paths, a manifest, and SHA-256 checksums before extraction.
- SQL statements are static literals with bound values, enforced by an architecture test.
- SQLite restore rejects sidecar-based archives and verifies database integrity before extraction.
- Workspace backup rejects database symlinks that escape the workspace boundary.
