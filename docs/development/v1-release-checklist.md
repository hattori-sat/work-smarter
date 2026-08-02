# V1 release checklist

- Release: `1.0.0`
- Date: 2026-08-03
- Branch flow: `feat/v1-completion` → `dev/work-smarter-v1` → `main`
- Status: COMPLETE

## Product acceptance

- [x] GTD capture/clarify/engage/reviewとstandalone GTD project
- [x] rigorous task ticket、waiting/blocking/schedule/recurrence/audit
- [x] Knowledge note/search/link/backlink/promotion/Marp presentation
- [x] Managed Project、WBS、QCD、risk、Working Calendar、4 dependency types、CPM
- [x] baseline/current/progress/dependencyを持つoffline interactive Gantt
- [x] Confluence dry-run/push/pull conflict boundary
- [x] checksummed workspace backup/restoreとSQLite online snapshot
- [x] Database structured-state authorityとone-time legacy import
- [x] operation journal crash recoveryとtransactional outbox worker
- [x] canonical domain/resource/operation CLI、typed API、loopback HTTP client

## Quality evidence

- [x] `ruff check src tests scripts`
- [x] `ruff format --check src tests scripts`
- [x] full `pytest` — 234 passed
- [x] clean-room wheel/runtime dependency install and CLI smoke
- [x] requirements install and `pip check`
- [x] secret/private-path scan（test fixtureの`engineer@example.com`だけを確認）
- [x] backup→restore→doctor release smoke
- [x] clean worktree after Conventional Commit

## Documentation

- [x] User manual index and system recovery runbook
- [x] Developer architecture, Database, API, testing, contribution manuals
- [x] Workspace format 1.0 reference
- [x] ADR 0007 authority/journal/outbox decision
- [x] `CHANGELOG.md` 1.0.0 release entry
- [x] `TASK.md` all V1 items complete

## Delivery

- [x] Feature commit created
- [x] Feature merged into dev with `--no-ff`
- [x] Dev merged into main with `--no-ff`
- [x] Main worktree and full-suite result verified

## Known boundaries

- Fact: V1 supports local single-user macOS/Linux and loopback FastAPI.
- UNKNOWN: remote authentication、multi-user permission/conflict、distributed worker。
- UNKNOWN: Web UI、Jira、User Story Mapping、Project Scenario persistence。
