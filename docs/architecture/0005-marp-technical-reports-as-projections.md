# ADR 0005: Render Marp technical reports as Knowledge projections

- Status: Accepted
- Date: 2026-08-02
- Extends: ADR 0003

## Outcome

KnowledgeのMarkdown正本を変更せず、技術報告をMarp互換Markdownへ再現可能に投影する。編集可能な
Knowledge本文と、発表用のslide区切り・theme・paginationを別の責務として扱う。

## Success criteria

1. `technical_report` templateが結論、成果、根拠、risk、次の行動、出典を先に整理できる。
2. full ID、unique prefix、aliasから同じMarp MarkdownをCLIとFastAPIで生成できる。
3. 生成結果はsource IDとrevisionを持ち、どの正本から作られたか追跡できる。
4. renderはKnowledge Markdown、revision、監査eventを変更しない。
5. Marp固有runtimeをcore dependencyにせず、`.marp.md`を任意のMarp環境で利用できる。
6. optional Marp CLI adapterが同じprojectionをbrowser-ready HTMLへcompileできる。
7. 科学技術報告向けの既定visual templateを持ち、title、見出し階層、図表の配置をHTMLで確認できる。

## Facts

- Knowledge本文の正本は`knowledge/notes/<id>.md`である。
- MarpはYAML frontmatterとMarkdownの`---`区切りを使うため、通常のKnowledge本文へ設定を混ぜると
  domain metadataとpresentation metadataが同じfrontmatterを共有する。
- 同じ技術報告でも、本文の再利用、Confluence公開、slide発表では必要な見せ方が異なる。
- HTML、PDF、PPTX生成には外部のMarp compilerまたは対応editorが必要である。
- Marpはdocument frontmatterの`style` directiveで、そのpresentationだけにCSSを適用できる。

## Considered paths

### Knowledge正本をMarp documentとして保存する

そのままpreviewできる一方、`marp`、`theme`、`paginate`がKnowledge schemaへ入り、slide区切りが
Confluence等の別projectionにも漏れる。presentation設定変更もKnowledge revision変更になる。

### Presentationを独立したauthoritative entityとして保存する

slide単位の独立編集は可能だが、Knowledge本文との二重正本になり、同期・競合・source更新policyが必要になる。

### Knowledge revisionからread-only projectionを生成する

presentation固有設定を出力へ閉じ込められる。slideごとの大幅な編集はsourceへ戻す必要があるが、同じrevision
から決定論的に再生成できる。

## Decision

3番目を採用する。

1. `KnowledgePresentationMode.TECHNICAL_REPORT`をpresentationのpublic contractとする。
2. `KnowledgeNoteType.TECHNICAL_REPORT`はpresentation向けの既定本文templateを提供する。ただしrendererは
   既存の全Knowledge noteへ使用できる。
3. level-two heading (`##`) ごとにslideを開始し、source本文のMarkdownはそれ以外変更しない。
4. 出力frontmatterは`marp: true`、validated theme、paginateだけを生成する。
5. theme名は英数字で始まる英数字・`.`・`_`・`-`の64文字以内に限定し、YAMLへの改行注入を拒否する。
6. 出力は`source_id`、`source_revision`、mode、theme、paginate、media type、推奨extension、Markdownを持つ
   `MarpPresentation`として返す。
7. CLI contractは`ws knowledge presentation render <id>`とし、stdoutまたは明示した`--output`へ出力する。
   既存fileは`--force`なしで上書きしない。`--json`は型付きprojectionだけをstdoutへ返す。
8. HTTP contractは`GET /api/knowledge/notes/{id}/presentations/marp`とする。renderは副作用を持たない。
9. HTML compileは`MarpCompiler` Portを介し、built-in adapterはMarp CLI executableだけを固定引数で起動する。
10. executableは`WORK_SMARTER_MARP_CLI`または既定の`marp`からserver起動側が選ぶ。HTTP requestから
    command、argument、config fileを指定させない。
11. adapterはshellを使わず、isolated temporary directory、30秒timeout、固定`--output`引数で実行する。
    raw HTMLを許可する`--html`とlocal file accessを許可する`--allow-local-files`は渡さない。
12. CLIは`--format html`でHTMLをstdout/file/JSONへ返す。FastAPIの`.../marp/html` routeは
    `text/html`を返し、browserから直接確認できる。
13. Marp CLI、Node.js、browser automationをcore dependencyへ追加せず、toolを暗黙downloadしない。
14. 既定のvisual templateは`scientific`とし、workspaceの
    `templates/knowledge/presentations/scientific.css`から読む。`ws init`はmissing fileだけを作り、利用者の
    編集を上書きしない。
15. rendererはtemplate CSSをYAML block scalarの`style`へ埋め込み、自己完結した`.marp.md`を生成する。
    外部theme登録やcompiler固有のconfig fileを要求しない。
16. `scientific` templateはtitleを上端に置き、H1/H2/H3を44/36/28pxで段階化し、図と表を中央配置する。
    本文は24px、表は20pxとし、白地、濃い文字、青1色のaccent、余白を基本にする。
17. CLIの`--template`とHTTPの`template` queryはclosed enumとし、現時点の値は`scientific`だけとする。

## Verification plan

- technical-report templateを作成し、unique prefixからprojectionできること。
- level-two headingがslideになり、source ID/revisionが出力へ残ること。
- unsafe themeを拒否し、sourceとevent countが変わらないこと。
- CLIのJSON purity、file overwrite refusal、FastAPI/OpenAPIのresponse typingを確認すること。
- fake executableで固定argument、shell non-expansion、missing/failure/timeout boundaryを確認すること。
- HTML previewが`text/html`で返り、sourceとeventを変更しないこと。
- visual templateの初期化、user overrideのnon-overwrite、Marp frontmatterへの埋め込みを確認すること。
- HTMLを実renderし、titleが上端、H1/H2/H3が44/36/28px、図表のcenter deltaが0pxであることを確認すること。
- 全Knowledge testsと全repository testsを実行すること。

## Consequences

- `.marp.md`は配布可能なartifactだが正本ではなく、いつでも再生成できる。
- `technical_report` noteは本文を直接編集し、presentationを再renderする。
- visual template CSSはworkspaceで管理され、生成するMarp Markdownへinline化される。image assetの可搬性は
  利用側Marp環境の責任になる。
- HTML compileにはMarp CLIのinstallが必要で、未導入時はtyped unavailable errorになる。
- HTML compile失敗をWork Smarterが監査eventとして扱うことは現時点ではない。
- PDF/PPTX/imageはbrowser runtimeを必要とするため、このsliceでは扱わない。

## Unknowns

- 複数のvisual templateを追加したときの互換性・versioning policyはUNKNOWN。
- diagram、image、code blockが1 slideを超える場合の自動分割policyはUNKNOWN。
- speaker notes、multiple audience variant、PDF/PPTX build pipelineをcoreへ持つ必要性はUNKNOWN。
- Marp出力をConfluenceへpublishするか、Knowledge本文をpublishするかのUI選択方式はUNKNOWN。
