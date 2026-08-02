# Workspace format 1.0

## Authority

- Registered domain entityのstructured state: configured Application Database
- Domainの操作・timer・review履歴: Database `activity_events`
- Narrative本文: entity Markdown body
- YAML frontmatterと`.work-smarter/events.ndjson`: read-only compatibility projection
- Knowledge search/backlink: 現在のMarkdownから都度再構築するprojection
- Application database: workspace configで選択したbackend artifact（初期値はSQLite）

SQLite schema v2はmigration metadata、structured entity、operation journal、append-only activity、leased
outboxを持つ。Legacy workspaceは一度だけfrontmatter/JSONLをimportし、以後のdirect frontmatter editや
手作りentity fileを再importしない。正本境界は
[ADR 0007](../architecture/0007-database-authority-journal-and-outbox.md)を参照する。

## Directory ownership

| Path | Owner | Meaning |
|---|---|---|
| `inbox/` | GTD | unclarified capture |
| `tasks/` | GTD | next/doing/waiting/scheduled/blocked/done task |
| `gtd/projects/` | GTD | 複数actionを必要とするoutcome |
| `someday/` | GTD | someday/maybe |
| `knowledge/gtd/` | GTD | clarifyでreference化した文書 |
| `knowledge/notes/` | Knowledge | independent knowledge note |
| `archive/inbox/` | GTD | raw captureとclarify disposition |
| `templates/gtd/` | GTD/user | body template |
| `templates/knowledge/` | Knowledge/user | note type別body template |
| `templates/knowledge/presentations/` | Knowledge/user | Marp visual template CSS |
| `.work-smarter/` | core | config、Database、audit projection、lock、provider state |

`knowledge/gtd/`と`knowledge/notes/`は同じ親directoryにあるが、前者はGTD、後者はKnowledgeが所有する。
Project management featureは `gtd/projects/` を再利用しない。

### Managed Project schedule fields

Managed Projectの`working_calendar`は`working_weekdays`（月曜=0〜日曜=6）、`non_working_days`、
`additional_working_days`を持つ。互換性のためfield未記載時は週7日を稼働日とする。

Work packageとmilestoneの`dependencies`は次のshapeを持つ。旧`dependency_ids`は
Finish-to-Start / lag 0として読み込み、typed entryが同じpredecessorにあればtyped entryを優先する。

```yaml
dependencies:
  - predecessor_id: WP-DESIGN
    type: finish_to_start
    lag_days: 1
progress_percent: 40
jira_status: In Progress
```

`type`は`finish_to_start`、`start_to_start`、`finish_to_finish`、`start_to_finish`のいずれか。
`progress_percent`は0〜100である。Baselineはcontent hashだけでなく、その時点のschedule item ID、
start、finishをimmutable snapshotとして保持する。Gantt HTMLはこれらから再生成できるprojectionである。

## Markdown entity

すべての管理対象entityはUTF-8 Markdownで、先頭にYAML mappingを持つ。

```markdown
---
schema_version: 3
id: TASK-20260723-102030-A1B2C3
kind: task
revision: 1
work_type: action
rigor: standard
title: 失敗するtestを1本書く
goal: parserの境界条件を実行可能な仕様にする
lifecycle: open
disposition: next
execution:
  state: idle
created_at: '2026-07-23T01:20:30Z'
updated_at: '2026-07-23T01:20:30Z'
source_inbox_id: IN-20260723-102025-D4E5F6
contexts:
- '@computer'
energy: high
original_estimate_minutes: 20
remaining_estimate_minutes: 20
actual_minutes: 0
schedule: {}
completion:
  obvious: false
  conditions:
  - id: CC-1
    text: testが意図した理由で失敗する
tags:
- parser
---

## Intent

parserの境界条件を固定する。

## Notes

## Result / Evidence
```

Rules:

- filenameは `<id>.md` と一致する。
- IDは英字で始まり、英数字、`.`, `_`, `-` の128文字以内とする。
- YAML duplicate key、unknown field、unknown kindを拒否する。
- kindは所有directoryと一致しなければならない。
- taskからGTD projectへの参照はstable `project_id`を使う。
- timezoneなしdatetimeは読み込めるが、applicationが生成する時刻はUTC awareとする。

### Knowledge note schema v1

Knowledge noteは`knowledge/notes/<id>.md`へ保存する。

```markdown
---
schema_version: 1
id: KN-8A2F1C77B410
kind: knowledge_note
note_type: decision
title: Canary release decision
tags:
- release
aliases:
- ship-plan
links:
- target_id: TASK-20260723-102030-A1B2C3
  relation: supports
  label: Execution evidence
sources:
- kind: url
  locator: https://example.com/runbook
  title: Release runbook
created_at: '2026-07-23T01:20:30Z'
updated_at: '2026-07-23T01:25:00Z'
revision: 2
---

## Context

Canaryの結果を見て段階的にreleaseする。

## Decision

最初に5%へreleaseする。
```

Knowledge固有rule:

- `note_type`は`note`, `decision`, `how_to`, `reference`, `meeting_note`, `technical_report`のいずれか。
- tagはtrim、lowercase、unique、sortされる。
- aliasはcase-insensitiveにKnowledge note間で一意である。
- linkはworkspace entityのstable IDをtargetにし、self/missing/ambiguous/duplicate target relationを拒否する。
- source kindは`entity`, `url`, `file`, `citation`, `other`のいずれか。
- `created_at`と`updated_at`はtimezone-awareで、`revision`はupdateごとに増える。
- backlinkはfrontmatterに保存せず、全noteのoutbound linkから導出する。

## Direct edits

本文とfrontmatterはVS Codeで直接編集できる。編集後は次を実行する。

```bash
ws doctor
ws knowledge doctor
```

`ws doctor`はschema、duplicate ID、filename/ID、kind/directory、GTD relation/project、dependency cycle、
work-log projection、WIP、監査logを検証する。`ws knowledge doctor`はKnowledge graphのorphan、broken、
duplicate、ambiguous linkを検証する。
状態遷移の監査を残したい変更はCLI/APIから行う。

## Templates

`ws init` は以下を存在しない場合だけ作る。

- `templates/gtd/task.md`
- `templates/gtd/project.md`
- `templates/knowledge/note.md`
- `templates/knowledge/decision.md`
- `templates/knowledge/how_to.md`
- `templates/knowledge/reference.md`
- `templates/knowledge/meeting_note.md`
- `templates/knowledge/technical_report.md`
- `templates/knowledge/presentations/scientific.css`

GTD templateでは`{{ intent }}`、`{{ outcome }}`、`{{ source_id }}` が置換される。Knowledge templateでは
現在`{{ title }}`を利用できる。body templateはfrontmatterを定義しないため、schema invariantはapplicationが
保持する。`scientific.css`はMarp presentationの`style` directiveへ埋め込まれるvisual templateで、title上端、
H1/H2/H3の階層、図表中央配置を既定とする。すべてのtemplateはuser編集可能で、再initしても既存fileを
上書きしない。

## Events

1行に1 JSON objectをappendする。最低限のenvelopeは次である。

```json
{
  "schema_version": 1,
  "id": "EVT-20260723-102040-ABC123",
  "type": "gtd.task.started",
  "occurred_at": "2026-07-23T01:20:40Z",
  "entity_id": "TASK-20260723-102030-A1B2C3",
  "payload": {}
}
```

JSONLは互換監査projectionであり、feature間deliveryを保証するmessage busではない。正本activityはDatabase、
外部deliveryは`outbox_items`である。

Knowledgeが追記するevent typeは次の3件である。

- `knowledge.note.created`
- `knowledge.note.updated`
- `knowledge.note.promoted`

## Compatibility

Task schema v1/v2はlegacy import時にv3へvalidate/migrateし、Database payloadとして保存する。既に完了済みの
v2 rigorous taskはassurance grandfather markerを保持する。Knowledgeはschema version 1だけを受け付ける。
未対応versionは自動推測せずvalidation errorにする。

Cutover後はMarkdown bodyだけが直接編集可能な正本である。FrontmatterはCLI/API writeごとにDatabase payloadから
再生成されるため、structured field変更にはdomain commandを使う。

### SQLite schema v2 contracts

- `structured_entities`: `(kind, entity_id)`、JSON payload、projection path、monotonic revision
- `operation_journal`: idempotency key、aggregate、payload、projection path、pending/completed/failed
- `activity_events`: append-only trigger付きdomain/infrastructure event
- `outbox_items`: pending/processing/completed/failed、attempt、availability、lease
- `application_markers`: one-time legacy import completion

これらのtableへ任意SQLを実行するpublic CLI/APIはない。値は全てstatic SQL statementへparameter bindingする。

## Backup representation

`ws workspace export`は選択中adapterで一貫snapshotを作り、backend名とmember pathをmanifestへ記録して
checksummed archiveへ格納する。SQLiteの`-wal`、`-shm`、`-journal`はruntime sidecarであり、backupへ
含めない。Restoreは展開前にSHA-256、pathを検査し、manifestに記録された同じadapterでsnapshotを検証する。
Database設定は次の形で、credentialを含めない。

```yaml
database:
  backend: sqlite
  location: null
```
