# Work Smarter

構造化情報を選択可能なDatabase backendへ段階移行し、narrative本文をMarkdownで扱う、
エンジニア個人向けのPersonal Engineering Workbenchです。

現在の `1.0.0` はGTD workflow、独立Knowledge、managed project、対話的Gantt、Confluence publishing、
Database authority、crash recovery、transactional outboxを実装しています。

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
- 1 entity = 1 Markdown narrative、Database-owned structured state、read-only frontmatter projection
- Database Portとadapter registry、SQLite migration、operation journal、activity event、leased outbox worker
- 1 Knowledge note = 1 Markdown、用途別template、tag、alias、source
- workspace entityへの明示的link、導出backlink、title/tag/body/alias検索
- GTD taskやInbox itemなど既存recordからKnowledgeへのidempotentなpromotion
- orphan・broken・duplicate・ambiguous linkを検査するKnowledge doctor
- Working Calendar、4 dependency type、CPM explanation、baseline付きoffline interactive Gantt
- CLI、typed loopback HTTP client、VS Code clientから利用できる型付きHTTP API

## セットアップ

Python 3.12以降が必要です。現在の対応OSはmacOS/Linuxです。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
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

## Knowledgeを再利用可能にする

Knowledgeはtask statusや期限を持たず、GTDとは独立して管理します。typeを指定して作成すると、用途別の
Markdown templateが入ります。

```bash
ws knowledge add "Release判断" \
  --type decision \
  --tag release \
  --alias ship-plan \
  --source url=https://example.com/runbook
ws knowledge show ship-plan
ws knowledge search "release" --field tag
```

Knowledge同士、またはtaskなど他のworkspace entityへstable IDでlinkできます。

```bash
ws knowledge link KN-NOTES TASK-20260723 --type supports
ws knowledge backlinks TASK-20260723
```

既存の業務記録をKnowledgeへ昇格する場合、元recordのbodyをcopyし、source IDを残します。同じsourceを
再度promoteしてもnoteは増えません。

```bash
ws knowledge promote TASK-20260723 --type reference --tag investigation
ws knowledge doctor
```

詳しい操作、link/sourceの意味、現在の検索制限は
[Knowledge guide](docs/user/knowledge.md)を参照してください。

## データ構造

```text
my-workspace/
├── inbox/                 未整理のcapture
├── tasks/                 1 task = 1 Markdown
├── gtd/projects/          GTD上のoutcome
├── someday/
├── knowledge/gtd/         GTDからreference化した文書
├── knowledge/notes/       独立Knowledge note
├── archive/inbox/         clarify前の原文とdisposition
├── templates/gtd/         user編集可能なbody template
├── templates/knowledge/   note type別bodyとMarp visual template
└── .work-smarter/
    ├── config.yml
    ├── work-smarter.db    structured state・activity・journal・outboxの正本
    ├── events.ndjson      互換audit projection
    └── workspace.lock
```

Taskの状態・関連・日付などはDatabase、意図・メモ・結果はMarkdown本文が正本です。Frontmatterはread-only
projectionであり、直接変更してもstateへ反映されません。本文の直接編集は正式対応です。詳細は
[workspace guide](docs/user/workspace.md)と[workspace format](docs/reference/workspace-format.md)にあります。

`templates/gtd/` と `templates/knowledge/` のbody template、および
`templates/knowledge/presentations/scientific.css`は自由に変更できます。次回 `init` でも既存fileは
上書きされません。

## ローカルAPI

```bash
ws server start --host 127.0.0.1 --port 8765
```

- OpenAPI: `http://127.0.0.1:8765/openapi.json`
- interactive docs: `http://127.0.0.1:8765/docs`
- health: `GET /health`
- GTD: `/api/gtd/*`
- Knowledge: `/api/knowledge/*`
- Managed Project: `/api/projects/*`
- Operation journal / outbox: `/api/system/*`

APIとCLIは同じapplication contractを呼びます。System commandは
`--server-url http://127.0.0.1:8765`でtyped HTTP clientへ切替できます。APIはlocalhostにだけbindします。

## GTD projectとproject managementは別物

GTD projectは「複数actionが必要な望ましいoutcome」です。WBS、依存関係、Gantt、QCD、risk、
review gateを持つmanaged projectではありません。後者は
`work_smarter.project_management` featureへ実装し、GTD state machineには混ぜません。

同じ方針でKnowledgeとConfluence publishingも独立境界に分離されています。将来追加するfeatureも
private domain modelを共有しません。
storageはfeatureが登録するentity codecだけを知り、GTD modelをimportしません。設計判断は
[ADR 0001](docs/architecture/0001-text-first-modular-monolith.md)と
[ADR 0002](docs/architecture/0002-feature-contract.md)、
[ADR 0003](docs/architecture/0003-hybrid-source-of-truth-and-local-application-server.md)にあります。

## 開発と検証

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/pytest
```

## 現在の非対応範囲

- Jira連携、User Story Mapping
- Web UI、file watcher
- VS Code専用UI/shortcut（integrated terminalとAPIは利用可能）
- multi-user権限管理、remote authentication/server運用、distributed outbox worker
- Windows（local file lockが現時点ではPOSIX実装）

これらは未実装であり、GTD MVPの一部として仮実装してはいません。
