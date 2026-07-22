# Work Smarter

Markdownを正本にし、事務作業をシステムへ押しつける、エンジニア個人向けのGTDツールです。

現在の `0.1.0` はGTD MVPです。プロジェクトマネジメント、User Story Mapping、TBP、
Confluence同期は、GTDとは別featureとして後から追加できる境界だけを用意しています。

## いまできること

- 引数、標準入力、HTTP APIから即座にInboxへcapture
- Inboxの最古項目をID指定なしでclarify
- next action、GTD project + 最初のaction、waiting、scheduled、someday、reference、
  done now、trashの8分類
- systemによるMarkdown生成・移動・Inbox原文のarchive
- 既知のnext actionを `add` 一発で作成
- context、所要時間、energyによるfocus候補の絞り込み
- WIPを常に1件へ制限し、明示的なswitchだけを許可
- waiting / blocked / scheduledからreadyへの復帰
- 日次status、週次review、workspace doctor、実績metrics
- 1 task = 1 Markdown、YAML frontmatter、append-only JSONL監査ログ
- CLIと、VS Code clientから利用できる型付きHTTP API

## セットアップ

Python 3.12以降が必要です。現在の対応OSはmacOS/Linuxです。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install '.[dev]'
source .venv/bin/activate
```

個人データを置くworkspaceを初期化します。code repositoryと同じ場所でも、別のprivate
repositoryでも構いません。

```bash
ws --workspace /absolute/path/to/my-workspace init
export WORK_SMARTER_WORKSPACE=/absolute/path/to/my-workspace
```

以後は `--workspace` を省略できます。既存ファイルや変更済みtemplateを `init` が上書きすることは
ありません。

## 怠惰に回す日常フロー

思いついた時点では分類しません。

```bash
ws capture "APIの失敗条件を調べる"
printf '%s\n' "選択中のTODO" | ws capture --source vscode-selection
```

すでに物理的なnext actionだと分かっているものは一発です。

```bash
ws add "失敗するtestを1本書く" --context @computer --estimate 20 --energy high
```

整理するときは最古のInboxを開きます。IDもファイル移動も不要です。

```bash
ws clarify
```

対話中の1キーは `n` next、`p` project、`w` waiting、`c` calendar、`s` someday、
`r` reference、`t` trash、`d` done nowです。scriptから使う場合は明示します。

```bash
ws clarify --decision next --context @computer --estimate 30
ws clarify --decision project \
  --outcome "障害解析を再現可能にする" \
  --first-action "再現条件を箇条書きにする"
```

着手時は全体像から一件を選びます。

```bash
ws status
ws focus --context @computer --minutes 30 --energy low
ws start TASK-20260723
ws done TASK-20260723
```

別taskがdoingなら `start` は拒否されます。意図的な切替だけ `--switch` を付けます。

```bash
ws start TASK-OTHER --switch
ws ready TASK-WAITING
```

GTD projectの最後のactionを完了すると、次のaction追加かproject完了をstatus/reviewが要求します。

```bash
ws add "運用結果を確認する" --project PRJ-20260723
ws project-done PRJ-20260723
```

週に一度、頭の外に出したものを信頼できる状態へ戻します。

```bash
ws review
ws review --complete
ws doctor
ws metrics
```

すべてのIDは一意なprefixまで短縮できます。自動化では全commandに `--json` を付けられます。

## データ構造

```text
my-workspace/
├── inbox/                 未整理のcapture
├── tasks/                 1 task = 1 Markdown
├── gtd/projects/          GTD上のoutcome
├── someday/
├── knowledge/gtd/         GTDからreference化した文書
├── knowledge/             自由なknowledge文書を置ける領域
├── archive/inbox/         clarify前の原文とdisposition
├── templates/gtd/         user編集可能なbody template
└── .work-smarter/
    ├── config.yml
    ├── events.ndjson      timer・遷移・reviewの監査履歴
    └── workspace.lock
```

taskの状態・関連・日付などはfrontmatter、意図・メモ・結果は本文です。直接編集も正式な使い方ですが、
編集後は `ws doctor` でschema、ID、配置、関連、WIPを検証してください。詳細は
[workspace format](docs/reference/workspace-format.md)にあります。

`templates/gtd/task.md` と `templates/gtd/project.md` は自由に変更できます。次回 `init` でも
上書きされません。

## ローカルAPI

```bash
ws serve --host 127.0.0.1 --port 8765
```

- OpenAPI: `http://127.0.0.1:8765/openapi.json`
- interactive docs: `http://127.0.0.1:8765/docs`
- health: `GET /health`
- GTD: `/api/gtd/*`

APIとCLIは同じapplication serviceを呼ぶため、VS Code extensionが独自に状態遷移を再実装する必要は
ありません。APIは初期状態でlocalhostにだけbindします。

## GTD projectとproject managementは別物

GTD projectは「複数actionが必要な望ましいoutcome」です。WBS、依存関係、Gantt、QCD、risk、
review gateを持つmanaged projectではありません。後者は
`work_smarter.project_management` featureへ実装し、GTD state machineには混ぜません。

同じ方針でUser Story Mapping、issue-driven TBP、Confluence publishingも独立featureにします。
storageはfeatureが登録するentity codecだけを知り、GTD modelをimportしません。設計判断は
[ADR 0001](docs/architecture/0001-text-first-modular-monolith.md)と
[ADR 0002](docs/architecture/0002-feature-contract.md)にあります。

## 開発と検証

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/pytest
```

## 現在の非対応範囲

- managed project、Gantt、QCD/EVM、system engineering document set
- User Story Mapping、TBP
- Confluence Cloud push/pull
- VS Code専用UI/shortcut（integrated terminalとAPIは利用可能）
- multi-user権限管理、remote server運用
- Windows（local file lockが現時点ではPOSIX実装）

これらは未実装であり、GTD MVPの一部として仮実装してはいません。
