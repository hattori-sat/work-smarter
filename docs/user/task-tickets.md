# Task tickets

Work Smarterのtaskは単なるTODO行ではなく、個人業務の判断・実行・証拠を一つのMarkdownへ
まとめたticketです。ファイルのコピーや移動は不要です。

## Three rigor levels

- `quick`: titleだけで作れます。完了が自明な短い行動向けです。
- `standard`: goalと1件以上の完了条件が必須です。
- `assured`: standardに加え、各条件のevidenceとconstraints/assumptions reviewが必須です。

```bash
ws add "設計reviewを依頼する"
ws task define TASK-... \
  --type communication \
  --rigor standard \
  --goal "明示的なreview判断を得る" \
  --why "未解決interfaceのまま実装しないため" \
  --constraint "機密情報を除く" \
  --assumption "reviewerが文書へアクセスできる" \
  --criterion "判断とaction itemが記録された"
ws task show TASK-...
```

完了条件はIDでcheckします。assured taskでは証拠を指定し、最後に前提・制約を確認します。

```bash
ws task check TASK-... CC-1 --evidence knowledge/decisions/review.md
ws task assure TASK-...
ws done TASK-...
```

例外完了は黙って条件を消さず、`ws done TASK-... --waiver "理由"`で理由を残します。

## Priority without a magic score

priority番号は保存しません。次の3軸を独立に残します。

- urgency: `low | normal | high | critical`
- impact: `low | medium | high`
- commitment: `none | intended | committed`

```bash
ws task define TASK-... --urgency high --impact high --commitment committed
```

Focusは、実行可能性、urgency、commitment、impact、期限、作成日時を決定的に評価します。

## Structure and dependencies

parentは作業分解、dependencyは実行順序です。この二つは混ぜません。

```bash
ws task parent CHILD-TASK PARENT-TASK
ws task link PREDECESSOR SUCCESSOR --type blocks
ws task link SUCCESSOR PREDECESSOR --type depends_on
```

dependency未完了のtaskはFocusにも出ず、startもできません。循環、自己参照、存在しない参照は
操作時または`ws doctor`で検出します。

## Estimates and actual work

```bash
ws task define TASK-... --estimate 60
ws task log TASK-... 15 --note "traceの第一段階を確認"
ws task estimate TASK-... 30 --reason "追加環境の確認が必要"
```

- original: 最初の見積り。通常操作では変更しません。
- remaining: 現時点の予測。変更理由をauditへ残します。
- actual: timerとmanual work logの合計です。

`ws start` / `ws stop`もwork logを追記します。過去ログを上書きせず、振り返り指標を再計算できます。

## Recurring work

```bash
ws task repeat TASK-... --frequency weekly --interval 2 --anchor 2026-07-23
```

反復taskを完了すると、完了履歴を保持したまま新しいIDで次回分を作ります。将来分は
`occurrence_on`までFocusへ出ません。
