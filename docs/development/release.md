# Release checklist

## Required checks

1. `ruff check`、`ruff format --check`、全`pytest`を実行する。
2. `.venv/bin/python scripts/release_smoke.py`で一時venvへwheelとruntime依存をinstallし、canonical
   CLIとjournalを実行する。
3. secret、実在email、private key、token、absolute home pathをtracked filesから検索する。
4. `ws workspace export`でbackupを作り、空のworkspaceへimportしてdoctorを実行する。
5. `TASK.md`、user manual、developer manual、`CHANGELOG.md`を更新する。
6. feature branchを`dev/work-smarter-v1`へ`--no-ff`で統合する。
7. release-quality項目がすべて完了してからだけ`dev/work-smarter-v1`を`main`へ統合する。

## Known limitations

- Facts: individual document writes and configuration writes are atomic; event append and WIP lock are
  process-safe on POSIX. Corrupt documents, unsafe archive paths, and concurrent starts have tests.
- Facts: file/Database境界はoperation journal、external deliveryはleased transactional outboxで回復する。
  Process-style crash、正常例外、lease競合、破損JSONL、backup/restoreのacceptance testがある。
- UNKNOWN: remote authentication、multi-user conflict、distributed workerはV1範囲外である。

Release evidenceは[V1 release checklist](v1-release-checklist.md)へ実行日、test数、commitを記録する。
