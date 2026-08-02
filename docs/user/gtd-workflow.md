# Personal-engineer GTD workflow

Work SmarterのGTDは、Markdownを手で移動・複製せずに、思考を捕まえ、意味を決め、いま実行する
1件へ集中するためのworkflowです。1 taskは1 Markdownのまま、状態遷移と履歴をserviceが更新します。

## Outcome

毎日の成功条件は「Inboxもtask一覧も完全に空にすること」ではありません。

- 気になったことを数秒で外へ出せる。
- Inboxを1件ずつ、次に判断できる形へ変換できる。
- いま実行可能なactionだけから1件を選べる。
- 他者待ち、障害、日付制約を忘れずに再提示できる。
- 週次reviewを中断・再開し、全領域を意識的に確認した証跡を残せる。

## The lazy daily loop

### 1. Capture without classifying

判断しないで、その場で投入します。

```bash
ws capture "release判断で確認したいこと"
printf '%s\n' 'CIが遅い理由を調べる' | ws capture
```

すでに物理的な次の行動が明確なら、Inboxへ残して後でファイルを移動する必要はありません。
`add`は内部でcaptureとclarifyを原子的に行い、Inbox由来のprovenanceをtaskへ残します。

```bash
ws add "失敗したjobのlogを10分確認する" --context @computer --estimate 10
```

### 2. Clarify one item

```bash
ws inbox
ws clarify
```

IDを省略すると最古のInbox itemを処理します。対話では次のどれかを1件だけ選びます。

| Decision | 使う場面 | 作られるもの |
|---|---|---|
| `next` | 1回の着手で進む | next action |
| `project` | 2個以上のactionが必要 | GTD projectと最初のaction |
| `waiting` | 他者・外部条件が次の進行を握る | waiting task |
| `scheduled` | その日時に実行する意味がある | calendar task |
| `someday` | まだcommitしない | Someday/Maybe item |
| `reference` | 行動を要求しない | reference item |
| `done` | 2分程度でその場で処理した | completed task |
| `trash` | 保存する価値がない | archive recordだけ |

`done`を選ぶと、通常完了と区別できる`two_minute_rule`付きaudit eventが残ります。時間を厳密に
計測して2分を証明する機能ではなく、「整理せずに今処理した」という判断の記録です。

非対話・JSON modeではdecisionと必須fieldを明示します。

```bash
ws --json clarify IN-20260723 --decision next --context @computer
ws --json clarify IN-20260723 --decision project \
  --outcome "release可否を説明できる" \
  --first-action "未解決riskを3件書き出す"
```

### 3. See today, then engage one task

```bash
ws today
ws focus --context @computer --minutes 30 --energy medium
ws start TASK-20260723
ws stop
ws done TASK-20260723
```

`today`は、実行中の1件、Inbox件数、期限超過、今日が期限、follow-up、escalation、今日の
calendar、blocker、現在利用可能なactionを一画面に集めます。検証用には日付を固定できます。

```bash
ws --json today --day 2026-07-23
```

日付境界は`.work-smarter/config.yml`のIANA timezoneを使います。既定は既存workspaceとの互換性を
優先して`UTC`です。日本時間で運用する場合は次のように設定します。

```yaml
timezone: Asia/Tokyo
```

デフォルトWIPは1件です。別taskの開始は拒否され、割込みを受け入れるときだけ明示的に切り替えます。

```bash
ws start TASK-OTHER --switch
```

## A task is several facets, not one fragile status

表示用の`status`は、次の事実から導出されます。

- lifecycle: `open | completed | cancelled`
- disposition: `next | waiting | calendar`
- execution: `idle | doing`
- unresolved blockers: 0件以上

表示優先順位は`done/cancelled`、`doing`、`blocked`、`waiting`、`scheduled`、`next`です。たとえば
委任中のtaskへ環境blockerが加わると表示は`blocked`になりますが、waiting情報は消えません。
最後のblockerを解決すると`waiting`が再び見えます。

taskのgoal、制約、前提、Definition of Doneについては
[Task tickets](task-tickets.md)を参照してください。

## Waiting-for without memory work

### Delegate

「相手の名前」だけでなく、依頼内容、期待日、次のfollow-up、escalation条件を一度に記録します。

```bash
ws task delegate TASK-20260723 "Security reviewer" \
  --request "threat modelを承認する" \
  --expected 2026-07-25 \
  --follow-up 2026-07-24 \
  --escalation 2026-07-26 \
  --escalate-to "Security lead"
```

委任するとactionは`waiting`になります。実行中ならtimerを停止し、calendar指定があれば解除します。
due dateとblockerは独立facetなので保持されます。すでにwaiting中のtaskを二重委任することはできません。

### Follow up, record a response, and escalate

```bash
ws task follow-up TASK-20260723 \
  --note "review channelで再通知した" --next 2026-07-25

ws task respond TASK-20260723 \
  --note "追加traceが必要との回答" --still-waiting --next 2026-07-28

ws task escalate TASK-20260723 \
  --note "release critical pathに入った" --to "Security lead"

ws task respond TASK-20260723 \
  --note "承認済み。decision recordを受領" --resolved
```

未解決responseはwaitingを維持し、次のfollow-upを設定します。解決responseはtaskを`next`へ戻し、
委任、follow-up、response、escalationのinteraction一式を`waiting_history`へ移します。再委任は新しい
waiting cycleになり、過去cycleを上書きしません。

`task respond`はflagを省略すると安全側の`--still-waiting`です。`--resolved`と`--next`の同時指定は
矛盾として拒否されます。

escalation実行時に次のescalation日を与えなければ、消化済みのdeadlineは解除されます。同じ期限が
毎日通知され続けないためです。

## Blockers are independent

1 taskへ複数のblockerを追加でき、それぞれIDで解決します。

```bash
ws block TASK-20260723 --reason "staging credentialがない"
ws block TASK-20260723 --reason "再現環境が停止中"
ws task unblock TASK-20260723 BLK-1 --note "credentialを再発行した"
ws task unblock TASK-20260723 BLK-2 --note "環境を再起動した"
```

`ws ready TASK-...`はwaiting、blocked、scheduledを手動で利用可能側へ戻すescape hatchです。blocked
では全blockerを「Made ready manually」として解決するため、原因ごとの解決内容が分かる場合は
`task unblock`を使います。

## Three date meanings

同じ「日付」でも意味を混ぜません。

| Field | 意味 | Focus / startへの効果 | 例 |
|---|---|---|---|
| `scheduled_for` | その日時に行うcalendar commitment | 未来なら開始不可。到達後は実行候補 | 会議、release window |
| `not_before` | それ以前は見せないtickler/defer | 到達前はFocusから除外。statusは`next`のまま | 来週再検討 |
| `due_on` | 期限 | 可否は変えず、Dashboardと並び順へ反映 | 提出期限 |

```bash
ws task schedule TASK-20260723 2026-07-25T10:00:00+09:00
ws task defer TASK-20260723 2026-07-24T09:00:00+09:00
ws task due TASK-20260723 2026-07-26
ws task due TASK-20260723 --clear
```

「いつかやりたい」をcalendarへ押し込まず、commitしていなければSomeday/Maybe、開始を遅らせる
だけならdefer、真のdeadlineだけをdueにします。

## Completion and reopening

通常はDefinition of Doneを満たしてから完了します。waitingや未解決blockerがあるtaskは完了できません。

```bash
ws task check TASK-20260723 CC-1 --evidence knowledge/decisions/release.md
ws done TASK-20260723
```

完了後に証拠が覆った場合は、完了情報を消さず、理由付きで再開します。

```bash
ws task reopen TASK-20260723 --reason "production evidenceが結論と矛盾した"
```

完了時刻、resolution、DoDの状態、結果、証拠、実績工数は`completion_history`へsnapshotされ、新しい
open cycleではDoD checkと結果をやり直します。理由なしのreopenと、次回分をすでに生成するrecurring
occurrenceのreopenは拒否されます。

## A resumable weekly review

週次reviewは一括で「済」にするcommandではなく、workspaceへ保存されるsessionです。

```bash
ws review start
ws review resume
ws review check REVIEW-20260723 inbox_zero
ws review check REVIEW-20260723 calendar_reviewed
ws review check REVIEW-20260723 waiting_reviewed
ws review check REVIEW-20260723 projects_reviewed
ws review check REVIEW-20260723 someday_reviewed
ws review complete REVIEW-20260723
```

各checkは「queueが空」ではなく「残件を意識的に確認し、必要な判断をした」という意味です。残件が
あってもreviewは完了できますが、5 stepすべてのcheckが必要です。途中で終了しても`resume`は同じ
sessionを返します。完了後の`start`は新しいsessionを作ります。

review reportはInbox、waiting、blocked、stale action、次のactionがないGTD project、calendar、
Someday/Maybeをまとめます。

## Metrics are feedback, not a score

```bash
ws metrics
ws --json metrics
```

主な意味は次の通りです。

| Metric | 定義 |
|---|---|
| `focus_minutes_total` | timer/manual work logの実効合計 |
| `average_lead_time_hours` | task作成から完了までの平均経過時間 |
| `average_cycle_time_hours` | 最初のstart eventからcomplete eventまでの平均経過時間 |
| `waiting_minutes_total` | 委任からwaiting解決まで。未解決分は集計時刻まで |
| `blocked_minutes_total` | blocker発生から解決まで。同一taskの重複blocker時間は1回だけ |
| `wip_current` | 現在doingのtask数 |
| `waiting_current` / `blocked_current` | 現在該当facetを持つtask数 |
| current age metrics | 現在のwaiting/blockerの平均・最古age |
| `average_estimate_ratio` | 完了taskの実効actual / original estimate |

work logを誤記した場合、元logを上書きせず、理由付きcorrectionを追記して実効時間を再計算します。

```bash
ws task correct-work TASK-20260723 WL-1 20 \
  --reason "10分は昼休みで、active workではなかった"
```

通常のhuman outputは主要値だけを表示します。waiting/blocker ageやsample数を含む全fieldを見る場合は
`ws --json metrics`を使います。

数字は評価点ではなく、見積りの癖、外部待ち、blocker、WIPの滞留を発見する材料として使います。

## Canonical GTD commands and editor integration

既存の`ws capture`、`ws focus`、`ws done`は日常操作用aliasとして残ります。script、Vim、長期的な
command contractではdomain/resource/operation順のcanonical formを使います。

```bash
ws gtd capture "APIの失敗条件を調べる"
ws gtd action create "再現testを書く" --context @computer --estimate 20
ws gtd action list --output picker
ws gtd action open TASK-20260803
ws gtd project create "再現可能なdebugging" --outcome "全failureをlocal再現できる"
ws gtd project list
```

`open`はworkspace内のunique ID prefixを解決し、`$EDITOR`へpathを固定引数として渡します。
`--output picker`は`status / ID / title / context / estimate`の安定した1行形式で、fzf等へpipeできます。

GTD projectは複数actionを必要とするoutcomeです。WBSやscheduleを持つManaged Projectとは別機能であり、
private modelを共有しません。

## Facts, inferences, and UNKNOWNs

### Facts

- Markdown/YAML snapshotとappend-only audit eventが正本である。
- task IDはfull IDだけでなく、workspace内で一意なprefixをCLI/API pathで解決できる。
- `--json` modeは対話promptを行わず、machine-readable outputだけをstdoutへ返す。
- waiting、blocker、calendarは同時に存在し得るfacetとして保存される。

### Inferences

- 個人業務では、priorityを細かく採点するより、実行可否とcommitmentを先に分ける方が日々の判断を
  減らせる。Work SmarterのFocus排序はこの前提に基づく。
- `today`はすべてを処理するqueueではなく、見落とし防止のnavigationとして使うのがよい。

### UNKNOWNs

- 営業日calendar、taskごとのtimezone、複雑なRRULEは未対応である。workspace全体のtimezoneは設定できる。
- notification daemon、mail/Slackからの自動capture、VS Code keybindingの最終UXは未確定である。
- GTD projectと将来のmanaged projectを自動変換するpolicyは未確定であり、現時点では別機能である。

永続形式と直接編集時の注意は[Workspace guide](workspace.md)、taskの厳格度は
[Task tickets](task-tickets.md)を参照してください。
