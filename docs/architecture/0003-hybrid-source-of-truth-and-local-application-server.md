# ADR 0003: Hybrid source of truth and local application server

- Status: Accepted
- Date: 2026-08-02
- Supersedes: ADR 0001 source-of-truth and client-write decisions

## Outcome

Work Smarterを、FastAPI local application serverを介して構造化データを更新し、SQLiteと
Markdownが情報種別ごとに正本を分担するlocal-first modular monolithへ段階移行する。

## Facts

- 現行実装はMarkdown/YAMLをentityの正本、JSONLを監査履歴の正本としている。
- GTD、Knowledge、Managed Project、Confluence、CLI、FastAPIには既存の利用可能な機能がある。
- Target Architectureはstatus、relation、estimate、time、history、external mappingをDatabase、
  narrative本文をMarkdownの正本と定義する。
- 単一利用者、local macOS/Linux、`127.0.0.1`上のserverが初期deployment条件である。
- TBP専用featureは実装対象外である。

## Considered paths

### 既存機能を一度にDatabaseへ置換する

Target構造へ最短で到達する一方、GTD、Knowledge、Managed Project、backup、CLIを同時に変更し、
移行失敗時に既存workspaceを読めなくするriskが大きい。

### Databaseをderived indexとして追加する

互換性は高いが、構造化fieldとeventのtransactional consistency、server-only writerという目的を
満たさず、ADR 0001の制約を固定してしまう。

### Migration基盤を先に置き、domain単位で正本を切り替える

一時的にlegacy persistenceとtarget persistenceが共存するが、各vertical sliceでschema migration、
API、CLI、backup、rollbackを検証できる。

## Decision

3番目の段階移行を採用する。

1. Local Application ServerはFastAPIを使用し、初期値ではloopback interfaceだけへbindする。
2. SQLite databaseは`.work-smarter/work-smarter.db`へ置き、forward-only migrationで管理する。
3. Databaseは構造化state、relation、time entry、activity event、outbox、provider mappingの正本とする。
4. Markdownは意図、背景、作業メモ、結果等のnarrative documentの正本とする。
5. 同一fieldをDatabaseとMarkdownの双方から編集可能にしない。Markdownへ構造化fieldを表示する場合は
   read-only projectionとして明示する。
6. CLI、Vim、Webは最終的にFastAPI上の同じapplication use caseを呼ぶ。移行中のlegacy direct CLIは、
   対象domainの切替が完了するまで互換interfaceとして残す。
7. Domain moduleはFastAPI、`sqlite3`、provider SDKをimportしない。Database transactionは
   application/infrastructure境界で扱う。
8. Activity eventはDatabase内でappend-onlyとし、外部連携は同じtransactionでoutboxへ登録する。
9. Domainの正本切替は、migration、API、canonical CLI、doctor、backup/restore、persistence reloadの
   acceptance testが揃ったsliceだけで行う。
10. CLIのcanonical treeは`ws <domain> <resource> <operation>`とし、頻用操作だけroot aliasを許す。

## Current transition state

- SQLite schema v1はmigration metadata、append-only `activity_events`、`outbox_items`を提供する。
- Workspace初期化とFastAPI lifecycleがschemaを最新化する。
- 既存GTD、Knowledge、Managed Projectのentity stateはまだMarkdown、historyはJSONLが正本である。
- DB tablesへlegacy eventを二重書込みしない。各domainの切替sliceで一度だけownershipを移す。

## Consequences

- 既存workspaceを読みながらdomain単位で移行できる。
- 移行期間中は正本の所在をdomainごとに文書化する必要がある。
- DatabaseとMarkdownを含む整合backupが必要になる。raw SQLite fileのcopy方式はserver稼働中には
  不十分であり、SQLite backup APIを用いるsliceが必要である。
- Remote bindはauthenticationと明示configurationのADRが決まるまで拒否する。
- CLI全操作のHTTP client化、operation journal、domain schema、outbox workerは未実装である。

## Unknowns

- GTD、Knowledge、Managed Projectの最適な移行順はUNKNOWN。
- Web frontend、file watcher、search index、Gantt rendererはUNKNOWN。
- Database migration失敗時の自動restore policyはUNKNOWN。
