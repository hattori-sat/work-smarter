# Release checklist

## Required checks

1. `ruff check`、`ruff format --check`、全`pytest`を実行する。
2. clean checkout相当の一時環境でwheelをbuild・installし、`ws --help`を実行する。
3. secret、実在email、private key、token、absolute home pathをtracked filesから検索する。
4. `ws workspace export`でbackupを作り、空のworkspaceへimportしてdoctorを実行する。
5. `TASK.md`、user manual、developer manual、`CHANGELOG.md`を更新する。
6. feature branchを`dev/work-smarter-v1`へ`--no-ff`で統合する。
7. release-quality項目がすべて完了してからだけ`dev/work-smarter-v1`を`main`へ統合する。

## Known limitations

- Facts: individual document writes and configuration writes are atomic; event append and WIP lock are
  process-safe on POSIX. Corrupt documents, unsafe archive paths, and concurrent starts have tests.
- UNKNOWN: document writeとevent appendをまたぐ一般的なmulti-file crash recovery/outboxは未実装。
- Inference: 上記が解決するまで、`main`へのv1 release mergeではなくintegration PRとして扱う。
