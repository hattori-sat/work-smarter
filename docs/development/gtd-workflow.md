# Developing the GTD workflow

## Outcome

GTDの状態遷移を1か所で保ち、CLI、HTTP、将来のVS Code clientが同じ不変条件、Markdown形式、
監査eventを共有できるようにする。

## Module boundaries

```text
CLI / FastAPI
     │ typed input/output
     ▼
GtdService ───────► pure metrics projector
     │
     ├── Task / WeeklyReviewSession models
     ├── Workspace Markdown snapshots
     └── EventStore append-only audit events
```

- `gtd/models.py`: durable schema、facet invariant、read model
- `gtd/service.py`: lock内のuse caseとtransition validator
- `gtd/events.py`: GTDが所有するevent name
- `gtd/metrics.py`: snapshot/eventを入力にする副作用なしのprojection
- `gtd/persistence.py`: entity kindとdirectoryの登録
- `cli.py` / `api.py`: adapter。domain ruleを再実装しない

managed project、knowledge、ConfluenceはGTD modelへfieldを追加せず、別featureからstable IDで参照する。

## Adding a transition

1. 利用者のGiven/When/Thenをservice acceptance testへ先に追加する。
2. modelだけで検出できる矛盾はPydantic invariantへ置く。
3. 現在snapshotをworkspace lock内で再読込する。
4. preconditionを検証してからMarkdownを書き、成功した事実をeventへ追記する。
5. CLI/APIを同じservice methodへ接続する。
6. 成功、拒否、複合facet、再読込、event payloadを確認する。
7. user guideと[workflow specification](../specs/gtd-workflow.md)を更新する。

拒否されたtransitionはrevision、Markdown、event件数を変えてはならない。`ValidationError`はadapterへ
漏らさず、service境界で`InvalidTransitionError`へ変換する。

## Facet rules

表示用`Task.status`を遷移条件の唯一の根拠にしない。たとえばwaitingとblockerは同時成立し、effective
statusは`blocked`になる。waiting操作は`disposition`とactive `waiting`、blocker操作は未解決itemを
直接検証する。

closed taskにはdoing、active waiting、未解決blockerを残さない。Waiting cycleはactive fieldから解決済み
historyへ移し、再委譲で上書きしない。

## Snapshot and event consistency

Markdown snapshotは現在状態、eventは履歴とmetrics intervalの根拠である。現在のlocal filesystem実装では
snapshot置換とevent appendは単一filesystem transactionではない。再実行可能なrecurrence生成では欠落
eventをbackfillする。その他のwrite/event間でprocessが停止した場合の一般outbox recoveryは
**UNKNOWN**であり、release hardeningでdoctorの照合範囲を拡張する。

event payloadには、将来のsnapshotだけから復元できないstable episode IDと、その時点の予定値を含める。
Waitingとblockerは別intervalとして投影し、blockerが重なる期間はtask単位のunionを取る。

## Time and dates

- timestampはtimezone-awareで保存する。
- naive legacy timestampはUTCとして扱う。
- `due_on`などdate-only fieldとDaily Dashboard境界にはworkspaceのIANA `timezone`を使う。
- `metrics(as_of=...)`はテストと再現可能な分析のため、未来eventを除外する。

## Verification

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/pytest -q
.venv/bin/pytest --cov=work_smarter --cov-report=term-missing -q
```

最低限のtest matrixは次を含む。

- valid/invalid transitionとno-write-on-refusal
- waiting + multiple blockersなどの複合facet
- CLI JSONとHTTP responseのschema parity
- Markdown再読込後の履歴
- fixed `today` / `as_of` / timezone boundary
- legacy event、重複event、重複blocker interval
- weekly reviewの中断、再開、全step gate

