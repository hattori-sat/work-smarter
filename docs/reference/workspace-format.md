# Workspace format 0.1

## Authority

- 現行domain entityの現在状態: Markdown + YAML frontmatter
- 現行domainの操作・timer・review履歴: `.work-smarter/events.ndjson`
- Knowledge search/backlink: 現在のMarkdownから都度再構築するprojection
- Application database: `.work-smarter/work-smarter.db`

SQLiteはmigration metadata、append-only activity event、outbox schemaを持つ。GTD、Knowledge、
Managed Projectの正本は各domain migrationが完了するまでMarkdown/JSONLであり、曖昧な二重書込みはしない。
Targetの正本境界は[ADR 0003](../architecture/0003-hybrid-source-of-truth-and-local-application-server.md)
を参照する。

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
| `.work-smarter/` | core | config、監査event、SQLite database、lock、provider state |

`knowledge/gtd/`と`knowledge/notes/`は同じ親directoryにあるが、前者はGTD、後者はKnowledgeが所有する。
Project management featureは `gtd/projects/` を再利用しない。

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

- `note_type`は`note`, `decision`, `how_to`, `reference`, `meeting_note`のいずれか。
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

GTD templateでは`{{ intent }}`、`{{ outcome }}`、`{{ source_id }}` が置換される。Knowledge templateでは
現在`{{ title }}`を利用できる。templateはfrontmatterではなく本文だけを定義するため、schema invariantは
applicationが保持する。

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

0.1では監査履歴であり、feature間deliveryを保証するmessage busではない。

Knowledgeが追記するevent typeは次の3件である。

- `knowledge.note.created`
- `knowledge.note.updated`
- `knowledge.note.promoted`

## Compatibility

Task schema v1/v2はread時にv3へlazy migrationし、次回writeでv3として保存する。既に完了済みの
v2 rigorous taskは新しいassurance gateで読めなくならないよう、frontmatterにgrandfather markerを
明示する。Knowledgeはschema version 1だけを受け付け、migrationはまだない。その他entityと未対応versionは
自動推測せずvalidation errorにする。

## Backup representation

`ws workspace export`はSQLite backup APIで`.work-smarter/work-smarter.db`の一貫snapshotを作り、
checksummed archiveへ格納する。SQLiteの`-wal`、`-shm`、`-journal`はruntime sidecarであり、backupへ
含めない。Restoreは展開前にSHA-256、path、SQLite integrity、migration metadataを検査する。
