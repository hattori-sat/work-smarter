# GTD workflow and reflection specification

- Status: Implemented on `feat/gtd-workflow`
- Date: 2026-07-23
- Scope: personal-engineer GTD only
- Related schema: [GTD Task Ticket schema v3](gtd-ticket-v3.md)

## Outcome

Capture時の摩擦を最小に保ちながら、taskの目的、実行可否、外部待ち、blocker、時間制約、完了、
振り返りを、1件のMarkdown snapshotとappend-only eventで再現可能にする。

managed project、knowledge、publishing、User Story Mapping、TBPはこのaggregateへ取り込まず、stable IDと
public contractで連携する別featureとする。

## Success criteria

1. known actionはcopy/moveなしでcaptureからtaskへ変換できる。
2. lifecycle、waiting、calendar、execution、blockerを組合せ可能な独立facetとして保持できる。
3. waitingの依頼、follow-up、response、escalation、解決をcycle単位で失わずに残せる。
4. `scheduled_for`、`not_before`、`due_on`が異なる実行意味を持つ。
5. Daily Dashboardが今日判断すべきqueueを決定的に投影できる。
6. Weekly Reviewを中断・再開でき、全stepを意識的に確認しない限り完了できない。
7. reopenが旧完了snapshotと理由を保持する。
8. effort、cycle、waiting、blocker、WIPをsnapshotとeventから再計算できる。
9. service、CLI、HTTPが同じdomain invariantを使い、writeはworkspace lock内で行われる。

## Facts

- Markdown/YAML snapshotと`.work-smarter/events.ndjson`のaudit eventがauthoritativeである。
- `Task` schema v3は`extra=forbid`であり、未知fieldを受け入れない。
- CLI/APIはadapterであり、状態遷移ruleは`GtdService`が所有する。
- GTD projectは「複数actionを要するoutcome」であり、managed projectとは別entityである。
- current implementationはsingle-userを前提とし、assignee permissionやmulti-user conflict resolutionを
  持たない。

## Considered paths and hypotheses

### Path A: one status enum

`waiting`、`blocked`、`scheduled`を単一fieldへ入れる方法は表示が単純である。一方、委任中に環境も
止まった場合、`waiting_blocked`のような直積statusが増え、一方の文脈を上書きしやすい。

### Path B: orthogonal facets

`lifecycle`、`disposition`、`execution`、blocker listを保存し、statusを表示用に導出する。queryは少し
複雑になるが、各事実と履歴を独立して扱える。

Decision: Path B。仮説は「個人業務の忘却は、複合状態を単一labelで潰すことから起きやすい」である。

### Weekly Review alternatives

- stateless report: queueをその場で表示し、1 commandで完了記録を残す。
- durable session: stepごとのchecked timestampを保存し、途中から再開する。

Decision: durable session。queueが空であることと、利用者がqueueを確認したことは別の事実だからである。

## Aggregate state

### Persistent facets

| Facet | Values | Rule |
|---|---|---|
| `lifecycle` | `open`, `completed`, `cancelled` | closed taskはdoing、active waiting、unresolved blockerを持てない |
| `disposition` | `next`, `waiting`, `calendar` | waitingはactive detail、calendarは`scheduled_for`必須 |
| `execution.state` | `idle`, `doing` | doingは`started_at`必須。既定WIPは1 |
| `blockers[]` | 0件以上 | unresolved itemごとにID、理由、開始、解決、解決noteを持つ |

### Effective status

statusは次の先勝ち規則で導出する。

1. completed → `done`
2. cancelled → `cancelled`
3. execution doing → `doing`
4. unresolved blockerあり → `blocked`
5. waiting disposition → `waiting`
6. calendar disposition → `scheduled`
7. otherwise → `next`

この規則により、waiting taskへblockerが重なると表示は`blocked`だが、waiting detailとfollow-upは保持
される。最後のblocker解決後に`waiting`が再び表面化する。

## Capture and clarify

Captureはtext、source、tagだけを要求し、分類を要求しない。known action用`add_next_action`は同一lock内で
captureとNEXTへのclarifyを行い、source Inboxをarchiveして`source_inbox_id`を保持する。

| Decision | Postcondition | Required input |
|---|---|---|
| `next` | open / next / idle task | title |
| `project` | active GTD project + first next action | outcome, first_action |
| `waiting` | open / waiting task | waiting_for |
| `scheduled` | open / calendar task | scheduled_for |
| `someday` | SomedayItem | title |
| `reference` | Reference | title |
| `done` | completed task | title |
| `trash` | archived Inbox only | none |

`done`は`gtd.inbox.clarified`へ`handling=two_minute`、`gtd.task.completed`へ
`two_minute_rule=true`を記録する。「2分以内だった」という計測値ではなく、clarify中に実行した判断を
表す。

## Transition contract

| Operation | Preconditions | Postcondition | Required event(s) |
|---|---|---|---|
| start | open、dependency完了、waiting/blockerなし、calendarなら時刻到達、WIP許容 | execution=doing | `gtd.task.started` |
| stop | doing | execution=idle、timer work log追加 | `work.logged`, `task.stopped` |
| complete | open、waiting/blockerなし、rigor gate充足またはwaiver | lifecycle=completed | `task.completed` |
| delegate | open、active waitingなし | disposition=waiting、new waiting cycle | `task.delegated` |
| follow-up | open waiting | interaction追加、follow-up更新 | `task.waiting.followed_up` |
| response unresolved | open waiting、next date任意 | waiting継続、interaction追加 | `task.response.recorded` |
| response resolved | open waiting、next dateなし | detailをhistoryへ移動、disposition=next | `response.recorded`, `waiting.resolved` |
| escalate | open waiting、escalation targetあり | interaction追加、次期限を更新/解除 | `task.escalated` |
| block | open | unresolved blockerを追加。doingなら先にstop | `task.blocked` |
| resolve blocker | matching unresolved blocker、noteあり | 指定blockerだけ解決 | `task.unblocked` |
| schedule | open、not waiting | disposition=calendar、scheduled_for設定 | `task.scheduled` |
| defer | open、not waiting | not_before設定。dispositionは変更しない | `task.deferred` |
| set/clear due | open | due_on設定/解除。可否は変更しない | `task.due.set` |
| ready | effective status waiting/blocked/scheduled | 対象facetを手動解決 | facet event(s), `task.ready` |
| reopen | completed non-recurring occurrence、reasonあり | old completionをhistoryへ、open/next | `task.reopened` |

`ready`は粗いescape hatchである。blockedなら全unresolved blockerを解決し、waiting detailは保持する。
waitingならcycleを「Made ready manually」でhistoryへ移す。scheduledなら`scheduled_for`を解除する。

## Waiting cycle

### Shape

```yaml
waiting:
  id: WAIT-...
  target_kind: person
  target: Security reviewer
  request: threat modelを承認する
  delegated_at: 2026-07-23T01:00:00Z
  expected_on: 2026-07-25
  follow_up_on: 2026-07-24
  escalation_on: 2026-07-26
  escalation_to: Security lead
  interactions:
    - id: INT-1
      kind: delegated
      occurred_at: 2026-07-23T01:00:00Z
      note: threat modelを承認する
```

interaction kindは`delegated | follow_up | response | escalated`である。cycle IDはtask内で一意、interaction
IDはcycle内で一意でなければならない。active waitingは`resolved_at`を持たず、history itemは必ず
`resolved_at`と`resolution_note`を持つ。

resolved responseと`next_follow_up_on`の同時指定は矛盾として拒否する。unresolved responseはnext dateを
持てる。escalationでnext dateを指定しなければ消化済み`escalation_on`をclearする。

## Blocker semantics

blockerはwaitingとは別facetであり、taskへ複数存在できる。`BLK-n`ごとに解決するため、1件の解除で
別blockerを失わない。Metricsでは各episodeをaudit eventで追跡するが、同一task上でblocker期間が重なる
時間はwall-clock unionとして1回だけ数える。

dependency relationによるpredecessorもstartを止めるが、`TaskBlocker`とは別contractである。前者はtask
graph、後者はそのtask内の障害記録である。

## Temporal semantics

| Field | Domain meaning | State effect | Availability effect |
|---|---|---|---|
| `scheduled_for` | calendar commitment | disposition=calendar | futureならstart/Focus不可、到達後は可 |
| `not_before` | tickler / defer boundary | dispositionを変更しない | futureならFocus不可 |
| `due_on` | promised deadline | 変更しない | start可否は変えずDashboard/orderingへ反映 |

delegateは`scheduled_for`をclearするが、`not_before`と`due_on`を保持する。schedule/deferはactive waiting中に
拒否される。dueはwaiting中でも設定できる。

## Daily Dashboard projection

`DailyDashboard(day)`はopen taskだけを対象に、次を返す。

- `current_task`: doing task、なければnull
- `inbox_count`
- `overdue`: due_on < day
- `due_today`: due_on == day
- `follow_ups_due`: active waitingかつfollow_up未設定またはday以前
- `escalations_due`: active waitingかつ未消化escalationがday以前
- `scheduled_today`: calendar taskのscheduled dateがday
- `blocked`: effective statusがblocked
- `available_actions`: 指定日の終端時刻を基準にしたFocus結果

`day`を省略したときの日付境界と`scheduled_today`のdatetime変換には、workspace configのIANA
`timezone`を使う。既存workspaceとの互換性のため既定値は`UTC`である。

同じtaskがfollow-upとescalationの双方へ出てもよい。これは重複ではなく、2つの判断が必要という意味で
ある。

## Durable Weekly Review

`WeeklyReviewSession`は`gtd/reviews/`へMarkdownとして保存される。未完了sessionはworkspaceに最大1件。
`start`は未完了sessionがあれば同じものを返し、なければ作成する。

必須stepは次の5件である。

1. `inbox_zero`
2. `calendar_reviewed`
3. `waiting_reviewed`
4. `projects_reviewed`
5. `someday_reviewed`

stepのcheck/undoはsession revisionを進め、`checked_at`を設定/解除する。全step checkedでなければcompleteを
拒否する。complete時はactive GTD projectの`last_reviewed_at`を更新し、attention item数をeventへ記録
する。attention queueが0件であることはcomplete条件ではない。

## Reopen contract

reopenは現在の完了を削除しない。次を`completion_history[]`へsnapshotする。

- completed_atとresolution
- 完了時のDefinition of Doneとassurance情報
- result summaryとevidence links
- actual minutes
- reopened_atと必須reason

active taskはopen/next/idleへ戻り、completion conditionのcheck/evidence、result、current evidence linksを
clearする。work log自体はaudit historyとして保持する。recurrenceは完了時に別IDの次回occurrenceを作る
ため、完了済みrecurring occurrenceのreopenは拒否する。

## Metrics definitions

Metricsは純粋なprojectionであり、`as_of`を指定するとその時刻より後のeventを無視し、open intervalを
その時刻で打ち切る。

| Field | Projection |
|---|---|
| `completed_total` | 現在snapshotがdoneで、as_of以前に完了したtask数 |
| `completed_last_7_days` | 上記のうちas_ofから7日以内 |
| `focus_minutes_total` | 対象taskのwork logged event。correctionを順番に反映 |
| `average_lead_time_hours` | current done taskのcreated_at→completed_at平均 |
| `average_estimate_ratio` | current done taskのeffective focus minutes / original estimate平均 |
| `average_cycle_time_hours` | paired first start→complete eventの平均wall-clock |
| `cycle_time_sample_count` | 上記pair件数 |
| `waiting_minutes_total` | delegated→waiting resolvedのepisode合計。openはas_ofまで |
| `blocked_minutes_total` | blocked→unblocked。task内overlapはunion、task間は合計 |
| `wip_current` | effective status doingのsnapshot数 |
| `waiting_current` | active waiting detailを持つsnapshot数 |
| `blocked_current` | effective status blockedのsnapshot数 |
| current waiting age | active waitingのdelegated_atからas_ofまでの平均/最大 |
| current blocked age | taskごとの最古unresolved blockerからas_ofまでの平均/最大 |

Cycle timeはactive effortではない。stop中、waiting中、blocked中の経過も含むflow timeであり、active workは
`focus_minutes_total`を使う。

work log correctionは元logを変更せず、`work_log_corrections[]`と`gtd.task.work.corrected`を追記する。
同じlogへの複数correctionはprevious→correctedのchainが一致しなければschema validationで拒否する。

## Legacy limitations

- Task v1/v2 snapshotはread時にv3へlazy migrationするが、audit event自体の一括migrationは行わない。
- waiting/blocker IDがない旧eventは、同一taskの最古open episodeへFIFOでpairする。explicit IDが一致しない
  close eventは別episodeを誤って閉じない。
- naive legacy datetimeはUTCとして解釈する。
- cycle sampleはstart/complete event pairがあるtaskだけを含む。snapshotだけの旧完了taskはlead timeには
  入るがcycle timeには入らない。
- reopened taskはcurrent snapshotがopenなので`completed_total`へは数えない。旧完了は
  `completion_history`に残るが、この集計はhistorical completion countではない。
- task Markdownを手動削除すると、そのIDのeventはcurrent task metricsから除外される。削除をarchiveへ
  置き換えるpolicyは未実装である。

## HTTP and CLI public contract

CLI commandは[User GTD workflow](../user/gtd-workflow.md)を参照する。HTTPはすべて`/api/gtd` prefixを持つ。

| Intent | HTTP route |
|---|---|
| delegate | `POST /tasks/{id}/delegate` |
| follow up | `POST /tasks/{id}/follow-up` |
| record response | `POST /tasks/{id}/response` |
| escalate | `POST /tasks/{id}/escalate` |
| resolve blocker | `POST /tasks/{id}/blockers/{blocker_id}/resolve` |
| schedule / defer / due | `PUT /tasks/{id}/schedule|defer|due` |
| reopen | `POST /tasks/{id}/reopen` |
| correct work log | `POST /tasks/{id}/work-logs/{work_log_id}/correct` |
| today | `GET /dashboard/today?day=YYYY-MM-DD` |
| review start | `POST /review/weekly/start` |
| review step | `PUT /review/weekly/{review_id}/steps/{step}` |
| review complete | `POST /review/weekly/{review_id}/complete` |

All IDs accept a full value or workspace-unique prefix. Domain refusal maps to HTTP 409; missing entity maps to 404;
malformed request/schema maps to FastAPI validation response.

## Verification plan

Public acceptance tests must cover success, refusal, emitted event, and reload for each transition. Minimum scenarios:

1. waiting interaction sequence survives reload and moves as one resolved history cycle。
2. overlapping waiting + two blockers reveals waiting only after both blocker resolutions。
3. calendar, defer, due each affect Focus/Dashboard differently。
4. review start is resumable and unchecked complete is refused。
5. reopen retains old completion and rejects blank reason/recurring occurrence。
6. deterministic `as_of` projection calculates cycle, waiting, blocker, correction, current age。
7. CLI JSON and typed API expose the same Task/Dashboard/Review shapes。

## Inferences and UNKNOWNs

### Inferences

- Daily Dashboardでfollow-upとescalationを別listにする方が、単一の「overdue」bucketより次の判断を明確に
  する。
- Weekly Reviewのcheckはqueue zeroではなくconscious reviewを表す方が、長期waitingやSomedayを不正に
  削除せずに済む。

### UNKNOWNs

- repeated escalationをどのcadenceで自動生成するか。現状は利用者が次回日を明示する。
- business calendar、holiday、複数timezoneを跨ぐdue/follow-up policy。workspace timezone自体は設定可能だが、
  taskごとのtimezoneは持たない。
- historical completionをreopen cycle単位で集計するreportの公開時期。
- notification/automationがeventを読むか、専用outbox contractを持つか。
- work logを削除相当の0分へcorrectした際のUI表現。
