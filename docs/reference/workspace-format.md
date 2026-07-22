# Workspace format 0.1

## Authority

- entityの現在状態: Markdown + YAML frontmatter
- 操作・timer・reviewの履歴: `.work-smarter/events.ndjson`
- 将来追加するSQLite/検索index/view: 破棄して再構築できるprojection

## Directory ownership

| Path | Owner | Meaning |
|---|---|---|
| `inbox/` | GTD | unclarified capture |
| `tasks/` | GTD | next/doing/waiting/scheduled/blocked/done task |
| `gtd/projects/` | GTD | 複数actionを必要とするoutcome |
| `someday/` | GTD | someday/maybe |
| `knowledge/gtd/` | GTD | clarifyでreference化した文書 |
| `knowledge/`のその他 | user/future knowledge feature | GTD doctorの管理外 |
| `archive/inbox/` | GTD | raw captureとclarify disposition |
| `templates/gtd/` | GTD/user | body template |
| `.work-smarter/` | core | config、監査event、lock、将来のprovider state |

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

## Direct edits

本文とfrontmatterはVS Codeで直接編集できる。編集後は次を実行する。

```bash
ws doctor
```

doctorはschema、duplicate ID、filename/ID、kind/directory、missing relation/project、dependency cycle、
work-log projection、WIP、監査logを検証する。
状態遷移の監査を残したい変更はCLI/APIから行う。

## Templates

`ws init` は以下を存在しない場合だけ作る。

- `templates/gtd/task.md`
- `templates/gtd/project.md`

`{{ intent }}`、`{{ outcome }}`、`{{ source_id }}` が置換される。templateはfrontmatterではなく本文だけを
定義するため、schema invariantはapplicationが保持する。

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

## Compatibility

Task schema v1/v2はread時にv3へlazy migrationし、次回writeでv3として保存する。既に完了済みの
v2 rigorous taskは新しいassurance gateで読めなくならないよう、frontmatterにgrandfather markerを
明示する。その他entityと未対応versionは自動推測せずvalidation errorにする。
