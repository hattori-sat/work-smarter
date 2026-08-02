# ADR 0007: Database authority, operation journal, and transactional outbox

- Status: Accepted
- Date: 2026-08-03
- Completes: ADR 0003 domain ownership migration

## Outcome

Registered GTD、Knowledge、Managed Project entityのstructured stateとactivity historyをDatabase正本へ
切り替える。Markdownはnarrative本文とread-only structured projection、JSONLは互換audit projectionとする。
file/Database境界はdurable operation journal、外部delivery境界はleased transactional outboxで回復する。

## Facts

- Schema v1にはappend-only `activity_events`と未接続の`outbox_items`があった。
- Entity stateはMarkdown frontmatter、domain activityはJSONLが正本だった。
- MarkdownとDatabaseを単一ACID transactionへ参加させることはできない。
- V1 serverはloopback-only、single-user、POSIX workspace lockを前提にする。

## Considered paths

### Domainごとの専用SQL schemaへ一括置換する

Query最適化はしやすいが、3 domainのmigration、direct-edit contract、backup、provider adapterを同時に変更し、
rollback面積が大きい。

### DatabaseをMarkdownのderived cacheにする

互換性は高いが、structured stateのauthorityとserver-only mutationを満たさない。

### Registered kind共通のstructured record Portでownershipを切り替える

Provider-neutral payloadをpublic Pydantic schemaで検証し、kind単位でimportできる。専用indexが必要になったdomainは
forward-only migrationでmaterialized tableを追加できる。

## Decision

3番目を採用する。

1. SQLite schema v2は`structured_entities`、`operation_journal`、`application_markers`、outbox leaseを持つ。
2. Workspace初回openでlegacy frontmatterとJSONLをidempotentにimportし、marker完了後は再importしない。
3. 以後、frontmatterはread-only projectionであり、直接変更してもstructured stateへ昇格しない。
4. Markdown本文だけをnarrative正本として直接編集できる。
5. Writeはjournal intent、atomic Markdown projection、Database entity/event/journal commitの順に行う。
6. 通常例外はoperationを`failed`にし、stateへ採用しない。process終了で残った`pending`だけを次回open時に
   projection一致を検証してcompleteする。
7. Activity eventはDatabase正本とし、JSONL append失敗はstate transitionを取り消さない。
8. Outbox workerは短いDatabase transactionでleaseし、provider call中はtransactionを保持しない。
   `operation_id`をprovider idempotency keyとし、失敗はretry可能な状態へ戻す。
9. Structured-state capabilityを持たないexternal backendはlegacy modeを維持し、capabilityを要求するsystem APIでは
   明示errorを返す。
10. Canonical infrastructure CLIは`ws system <resource> <operation>`とし、`--server-url`ではtyped loopback
    HTTP clientを使う。

## Recovery invariants

- `pending + matching projection`: entity write/deleteをcompleteする。
- `pending + missing/mismatched projection`: failedへ固定し、勝手にstateへ採用しない。
- `failed`: reopenで再実行しない。
- completed outbox: 同じlease completionを再送してもcompletedのまま。
- expired processing lease: 5分後に別workerがclaimできる。
- backup: Markdown、journal、structured entities、activity、outboxを同じSQLite online snapshotへ含める。

## Inferences

- Common record PortはV1のmigration riskを下げる。domain queryの実測後に専用read modelを足せる。
- JSONLを残すことで既存toolingとdiff可能性を維持しつつ、破損projectionがapplication stateを壊さなくなる。

## Hypotheses

- 5分leaseとbounded batchはsingle-user local integrationに十分である。
- 1,000件までのstartup journal scanとlegacy one-time importはV1 workspace規模で許容できる。

## Unknowns

- Multi-user optimistic concurrency、remote authentication、distributed leaseはV1範囲外でUNKNOWN。
- Domain別secondary indexの閾値はdogfooding前のためUNKNOWN。
