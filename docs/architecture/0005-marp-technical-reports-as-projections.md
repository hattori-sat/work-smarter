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

## Facts

- Knowledge本文の正本は`knowledge/notes/<id>.md`である。
- MarpはYAML frontmatterとMarkdownの`---`区切りを使うため、通常のKnowledge本文へ設定を混ぜると
  domain metadataとpresentation metadataが同じfrontmatterを共有する。
- 同じ技術報告でも、本文の再利用、Confluence公開、slide発表では必要な見せ方が異なる。
- HTML、PDF、PPTX生成には外部のMarp compilerまたは対応editorが必要である。

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
9. Marp compiler、Node.js、browser automationをcore dependencyへ追加しない。

## Verification plan

- technical-report templateを作成し、unique prefixからprojectionできること。
- level-two headingがslideになり、source ID/revisionが出力へ残ること。
- unsafe themeを拒否し、sourceとevent countが変わらないこと。
- CLIのJSON purity、file overwrite refusal、FastAPI/OpenAPIのresponse typingを確認すること。
- 全Knowledge testsと全repository testsを実行すること。

## Consequences

- `.marp.md`は配布可能なartifactだが正本ではなく、いつでも再生成できる。
- `technical_report` noteは本文を直接編集し、presentationを再renderする。
- theme CSSやimage assetの可搬性は利用側Marp環境の責任になる。
- PDF/PPTX/HTMLへのcompile失敗をWork Smarterが監査eventとして扱うことは現時点ではない。

## Unknowns

- custom theme assetをworkspace所有にするかはUNKNOWN。
- diagram、image、code blockが1 slideを超える場合の自動分割policyはUNKNOWN。
- speaker notes、multiple audience variant、PDF/PPTX build pipelineをcoreへ持つ必要性はUNKNOWN。
- Marp出力をConfluenceへpublishするか、Knowledge本文をpublishするかのUI選択方式はUNKNOWN。
