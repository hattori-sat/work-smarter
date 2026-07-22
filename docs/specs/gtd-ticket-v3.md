# GTD Task Ticket schema v3

- Status: Implemented
- Date: 2026-07-23
- Branch: `feat/gtd-ticket-model`

## Outcome

一つの個人業務actionを、実行可能性だけでなく目的、制約、前提、完了条件、依存、結果証拠まで
追跡できるticketにする。ただしcaptureの速さを失わない。

## Facts

- Jiraはwork item、workflow transition、validator、directional link、worklog、historyを分離している。
- 現行Task schemaは`status`一つへwaiting、scheduled、blocked、doingを押し込んでいる。
- waitingとfollow-up期限、calendarとblockerは同時に成立し得る。
- single-user GTDではassignee/reporter/permission schemeは不要である。

## Considered models

### A. 単一statusを拡張する

現行互換性は高いが、`waiting_due`、`scheduled_blocked`のような組合せstatusが増える。

### B. Faceted ticket

`lifecycle`、`disposition`、`execution`、`availability`を分離し、UI用statusを導出する。
移行は必要だが、複合状態とmetricが一貫する。

## Decision

Bを採用する。永続化する主軸は次である。

- `lifecycle`: `open | completed | cancelled`
- `disposition`: `next | waiting | calendar`
- `execution.state`: `idle | doing`
- unresolved blocker: 0件以上
- `effective status`: 上記から導出し、旧CLI/APIの`status`として返す

status導出優先順位:

1. completed / cancelled
2. doing
3. blocked
4. waiting
5. scheduled
6. next

## Rigor profiles

| Profile | Creation/clarify | Completion gate |
|---|---|---|
| `quick` | titleだけでよい | 完了が自明。criteriaは任意checklist |
| `standard` | goalと1件以上のcondition | 全condition達成、または理由付きwaiver |
| `assured` | standard + constraints/assumptions review | conditionごとのevidence、または理由付きwaiver |

Inbox captureにはrigorを要求しない。known actionのquick-addは`quick`、重要業務はclarify/editで
`standard`または`assured`へ上げる。

## Persistent shape

```yaml
schema_version: 3
id: TASK-20260723-ABC123
kind: task
revision: 1
work_type: investigation
rigor: standard
title: API失敗条件を確定する
goal: retry設計の判断材料を得る
why: production障害を再発させないため
desired_outcome: 失敗modeと対策がreview可能

lifecycle: open
disposition: next
execution:
  state: idle
  started_at: null

project_id: PRJ-...
parent_id: null
relations:
  - type: blocks
    target_id: TASK-...

contexts: ['@computer']
energy: high
original_estimate_minutes: 45
remaining_estimate_minutes: 45
actual_minutes: 0
urgency: high
impact: high
commitment: committed
work_logs: []

schedule:
  not_before: null
  scheduled_for: null
  due_on: 2026-07-25

waiting: null
blockers: []

constraints:
  - 本番credentialをlogへ出さない
assumptions:
  - id: ASM-1
    statement: stagingで同じfailureを再現できる
    status: open
risks: []

completion:
  obvious: false
  conditions:
    - id: CC-1
      text: failure mode一覧をreviewした
      met_at: null
      evidence: null
  waiver_reason: null
  assurance_reviewed_at: null
  assurance_review_hash: null
  assurance_grandfathered: false

recurrence:
  frequency: weekly
  interval: 2
  anchor_on: 2026-07-23
recurrence_series_id: TASK-20260723-ABC123
occurrence_on: 2026-07-23

resolution: null
result_summary: null
evidence_links: []
```

本文templateは次を表示する。

- Why / Goal / Desired outcome
- Constraints
- Assumptions
- Definition of Done
- Notes
- Result / Evidence

query/report対象はfrontmatter、長文の思考過程は本文へ置く。重複項目はapplicationがtemplate生成時に
snapshotとして埋めるが、frontmatterを正とする。

## Relations

- `parent_id`: 作業分解だけに使う。
- `blocks`: source完了までtargetを開始できない方向付きlink。
- `depends_on`: sourceがtargetの完了を必要とする、`blocks`の逆向き表現。
- `relates_to`: 実行制約を持たない関連。
- `duplicates`: sourceはtargetと重複。
- `implements`: sourceがtargetの要求・決定等を実装する。

dependency graphは表現方法にかかわらずcycleを拒否する。project ownershipは`project_id`一件、その他projectとの関係は
relationで表す。

## Priority, effort, and recurrence

- opaqueなpriority scoreは保存しない。`urgency`、`impact`、`commitment`を別々に判断する。
- original estimateは最初の予測として不変にする。
- remaining estimateの変更には理由を要求し、work log追加時は実績分を自動減算できる。
- timer/manual work logをtaskとaudit eventの双方へ追記し、`actual_minutes`を投影する。
- recurrenceは`daily | weekly | monthly`とintervalを持つ。完了したtaskを再openせず、新IDの
  次回occurrenceを生成する。

## Schema migration

Task v1/v2はread時にmemory上でv3へ変換し、次回writeでv3として保存する。

- `status` → lifecycle/disposition/execution/blocker
- `estimate_minutes` → original/remaining estimate
- `not_before/scheduled_for/due_on` → schedule
- `waiting_for/follow_up_on` → waiting
- `completion_criteria` → completion conditions
- existing v1 taskはbehavior互換のため`quick`
- v2で既に完了していたrigorous taskは、当時存在しなかったassurance review markerを
  `assurance_grandfathered`として明示し、読めなくなることを防ぐ

原文backupを暗黙作成せず、migration commandを追加するまでは個別write時のlazy migrationとする。

## Invariants

- doingはstarted_at必須。
- waiting dispositionはwaiting detail必須。
- calendar dispositionはscheduled_for必須。
- unresolved task blockerまたは`blocks` predecessorがあれば開始不可。
- standard/assuredはgoalとcondition必須。
- assured完了は全conditionのevidenceとconstraints/assumptions review記録が必須。review hashが
  現在の内容と一致しなければstaleとして拒否する。
- completedはcompleted_atとresolution必須。
- parent/blocks cycleは禁止。
- original estimateは通常操作で上書きせず、変更はaudit eventに理由を残す。

## TDD acceptance

1. v1/v2 Markdownを読むとv3 Taskになり、write後はv3 frontmatterになる。
2. quick Taskはtitleだけで作成・完了できる。
3. standard Taskはgoalまたはcondition不足を拒否する。
4. assured Taskはevidence不足の完了を拒否する。
5. condition達成を記録すると完了できる。
6. task detailのCLI JSONとAPI responseが同じschemaを返す。
7. title/goal/constraints/assumptions/conditionsをpublic service経由で更新できる。
8. blocks relationは開始を止め、predecessor完了後に解除される。
9. blocks/parent cycleを作るlinkを拒否する。
10. Markdown body templateにrigor sectionsが生成される。
11. parentとdependency cycle、missing referenceをservice/doctorが拒否する。
12. manual/timer work logがmetricsへ一度だけ反映される。
13. recurrence完了時は履歴を残したまま別IDの次回taskが生成される。

## Unknowns

- `goal`と`desired_outcome`をdogfooding後も別fieldとして維持する価値。
- relationをTask内へ複製するか、独立edge entityへ移す時期。
- より複雑な営業日・RRULE互換recurrenceを導入する時期。
