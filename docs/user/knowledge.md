# Knowledge guide

Work SmarterのKnowledgeは、あとで再利用したい情報を1件1 Markdownとして保存し、tag、alias、明示的な
link、backlink、検索で取り出す機能です。GTDのtaskやprojectとは別のfeatureなので、Knowledge noteに
実行statusや期限はありません。

## Enable the feature

新しく`ws init`したworkspaceでは、GTDとKnowledgeが既定で有効です。

以前のversionで作ったworkspaceが`.work-smarter/config.yml`に`gtd`だけを指定している場合は、
`knowledge`を追加してから再度`init`します。既存文書や変更済みtemplateは上書きされません。

```yaml
features:
- gtd
- knowledge
```

```bash
ws init
```

## Choose a note type

| Type | Use it for | Default body sections |
|---|---|---|
| `note` | 一般的な知見や説明 | Summary, Details, Related |
| `decision` | 判断とその根拠 | Context, Decision, Consequences, Alternatives |
| `how_to` | 再現可能な手順 | Goal, Prerequisites, Procedure, Verification |
| `reference` | 外部資料や調査結果 | Summary, Extracts, Sources |
| `meeting_note` | 会議記録 | Attendees, Agenda, Notes, Decisions, Actions |
| `technical_report` | 技術報告と発表 | Executive Summary, Objective, Method, Results, Evidence, Limitations and Unknowns, Conclusion, Next Actions, Sources |

typeを省略すると`note`です。本文を省略すると`templates/knowledge/<type>.md`が使われます。

## Create and retrieve notes

```bash
ws knowledge add "リリース判断" \
  --type decision \
  --tag release \
  --alias ship-plan \
  --source url=https://example.com/runbook
```

本文をcommand lineで渡す場合は`--body`、既存Markdownを使う場合は`--body-file`を指定します。

```bash
ws knowledge add "再試行policy" --type how_to --body-file notes/retry.md
```

表示、一覧、検索では、ファイルを探す必要はありません。

```bash
ws knowledge show KN-12AB
ws knowledge show ship-plan
ws knowledge list --type decision --tag release
ws knowledge search "canary"
ws knowledge search "verification" --field body
```

IDはworkspace内で一意になる長さのprefixまで短縮できます。`show`と`update`はKnowledge内で一意な
aliasも受け付けます。検索対象は`title`、`tag`、`body`、`alias`で、`--field`を繰り返して限定できます。
現在の検索は大文字小文字を無視した部分一致です。

## Update metadata and body

`update`に渡したcollection fieldは追加ではなく置換です。たとえば次のcommandはtag全体を
`delivery`と`reviewed`へ置き換えます。

```bash
ws knowledge update ship-plan \
  --title "Canary release decision" \
  --tag delivery \
  --tag reviewed \
  --alias canary-plan
```

空にする場合は明示的なclear optionを使います。

```bash
ws knowledge update canary-plan --clear-tags --clear-aliases
ws knowledge update canary-plan --clear-links --clear-sources
```

更新ごとに`revision`が増え、`knowledge.note.updated` eventが監査logへ追記されます。

## Connect knowledge

Knowledge linkは、相手のtitleやpathではなくstable IDを保存します。相手はKnowledge noteに限らず、
GTD taskなどworkspaceに登録されたentityでも構いません。

```bash
ws knowledge link KN-SOURCE KN-TARGET \
  --type supports \
  --label "実装時の検証結果"
ws knowledge backlinks KN-TARGET
```

利用できるrelationは次の5種類です。

- `related_to`
- `supports`
- `contradicts`
- `supersedes`
- `derived_from`

作成・更新と同時にlinkする場合、`--link TARGET`は`related_to`、
`--link derived_from=TARGET`は指定relationになります。backlinkは別fieldへ複製されず、現在のoutbound
linksから都度求められます。

sourceは「このnoteを作る根拠」を表し、linkとは別です。`entity`、`url`、`file`、`citation`、`other`を
指定できます。

```bash
ws knowledge add "調査結果" \
  --source url=https://example.com/paper \
  --source file=docs/experiment.md
```

## Promote existing work

GTD taskやInbox itemなど、公開fieldとして`id`、`kind`、`title`を持つworkspace recordをKnowledgeへ
昇格できます。

```bash
ws knowledge promote TASK-12AB --type reference --tag investigation
```

promotionは次を行います。

1. 元recordのtitleとMarkdown bodyを新しいKnowledge noteへcopyする。
2. 元recordのstable IDを`entity` sourceとして残す。
3. `knowledge.note.promoted` eventを追記する。

同じsourceを再度promoteしても別noteを増やさず、最初のpromotionを返します。これは継続同期では
ありません。promotion後に元recordを編集してもKnowledge noteは自動更新されません。

## Keep the graph healthy

Markdown/frontmatterの直接編集も正式な使い方です。編集後はKnowledge固有の検査を実行します。

```bash
ws knowledge doctor
```

doctorは次を報告します。

- `orphan`: valid link/backlinkもsourceもないnote。warningであり、終了codeは成功。
- `duplicate_link`: 同じrelationとtargetの重複。warning。
- `broken_link`: targetが存在しないlink。error。
- `ambiguous_link`: workspace内でtarget IDが重複しているlink。error。

errorがある場合、`ws knowledge doctor`は終了code 1です。一般workspace/GTDの検査には別途
`ws doctor`も実行してください。

## Automation and HTTP

すべてのKnowledge commandはroot optionの`--json`に対応します。

```bash
ws --json knowledge search "release" --field tag
```

local APIを使う場合は`ws serve`を起動し、`/api/knowledge/*`を利用します。request/response schemaは
`/openapi.json`で確認できます。

## Create a Marp technical report

発表用の技術報告は`technical_report` templateから作成します。本文の`##`見出しが1枚のslideになります。

```bash
ws knowledge add "Database adapter移行報告" --type technical_report
ws knowledge presentation render KN-12AB --output adapter-rollout.marp.md
```

既存のKnowledge noteも同じcommandで投影できます。既定の`scientific` templateは、titleを上端、図表を中央、
H1/H2/H3を大・中・小の順に配置します。`--theme`、`--template scientific`、`--no-paginate`を指定でき、
既存出力を置換する場合だけ`--force`が必要です。

```bash
ws knowledge presentation render ship-plan \
  --template scientific \
  --theme gaia \
  --no-paginate \
  --output release-report.marp.md
```

生成された`.marp.md`にはsource IDとrevisionが入り、元のKnowledge fileや監査eventは変更されません。
Work SmarterはMarp CLIを同梱・暗黙downloadしません。HTML previewを使う場合はMarp CLIをinstallし、
`marp`をPATHへ置きます。別の場所にある場合は単一のexecutable pathを設定します。

```bash
npm install -g @marp-team/marp-cli
# または: brew install marp-cli

export WORK_SMARTER_MARP_CLI=/path/to/marp
```

HTML fileへrenderするとbrowserで実際のtheme、pagination、slide navigationを確認できます。

```bash
ws knowledge presentation render KN-12AB \
  --format html \
  --output adapter-rollout.html
```

色、font、余白、図表サイズを変える場合はworkspace内の次のfileを編集します。

```text
templates/knowledge/presentations/scientific.css
```

このCSSは生成する`.marp.md`へ埋め込まれるため、別途Marp themeを登録する必要はありません。`ws init`を
再実行しても編集済みCSSは上書きされません。図は通常のMarkdown imageで置き、captionは`<small>`または
`<figcaption>`を使うと中央配置のcaption styleが適用されます。

`--json`と`--format html`を組み合わせるとsource metadataとHTMLをJSONで返します。Marp CLIがない場合は
installまたは`WORK_SMARTER_MARP_CLI`設定を案内するerrorになります。command argumentを環境変数へ含めることは
できません。

APIからは次のread-only routeを使用します。最初はJSONのMarp projection、2番目はbrowserで直接開けるHTMLです。

```text
GET /api/knowledge/notes/{id}/presentations/marp?template=scientific&theme=default&paginate=true
GET /api/knowledge/notes/{id}/presentations/marp/html?template=scientific&theme=default&paginate=true
```

## Current limits

- 検索index、ranking、stemming、fuzzy searchはなく、現在のnoteを逐次検索する。
- 添付ファイルのcopy、version管理、content extractionは行わない。
- promotion後の双方向同期は行わない。
- Confluence push/pullとprovider mappingはKnowledgeではなく、後続のpublishing featureで扱う。
- MarpからPDF/PPTX/imageへのcompileは行わない。
- visual templateは現在`scientific`だけで、speaker notesやaudience別variantはない。
- graph visualization、automatic link suggestion、semantic/embedding searchは未実装。
