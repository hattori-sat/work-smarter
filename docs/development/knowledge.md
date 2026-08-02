# Developing the Knowledge feature

## Outcome

Knowledgeのschema、graph invariant、Markdown persistenceを1つのapplication serviceへ集約し、CLI、HTTP、
将来のpublishing/search projectionが同じpublic contractを利用できるようにする。

## Module boundaries

```text
Knowledge CLI / typed FastAPI router
               │
               ▼
       KnowledgeService
        │      │       │
        │      │       └── EventStore (append-only audit)
        │      └────────── Workspace (lock + Markdown codec)
        └───────────────── Knowledge public models

other feature ── generic EntityRecord / stable ID ──► promote or link
```

- `knowledge/models.py`: strict public schema、enum、read models
- `knowledge/service.py`: lock内のcreate/update/promote invariant、query、doctor
- `knowledge/persistence.py`: `knowledge_note` codecと`knowledge/notes/` ownership
- `knowledge/templates.py`: type別body templateとuser-overridable presentation CSS
- `knowledge/presentations.py`: Knowledge revisionからのread-only Marp projection
- `knowledge/marp.py`: optional Marp CLI compiler adapter
- `knowledge/events.py`: Knowledgeが所有するstable event names
- `knowledge/errors.py`: adapterが公開できるdomain error
- `knowledge/cli.py`: root CLI stateを利用するkeyboard/script adapter
- `knowledge/api.py`: provider-neutral request modelとtyped FastAPI router
- `knowledge/__init__.py`: feature descriptorとpublic export

Domain ruleをCLI/APIへ再実装しない。adapterはinput syntaxの変換、unique prefixの解決、presentationだけを
担当する。

## Composition

`KnowledgeFeature.register()`はentity specとworkspace initializerを`FeatureRegistry`へ追加する。fresh
workspaceの既定featureは`gtd`と`knowledge`だが、`open_workspace()`はconfigに列挙されたfeatureだけを合成
する。既存のGTD-only configを暗黙upgradeしない。

Knowledge packageそのものはGTDをimportしない。このboundaryはsubprocess import testで固定する。
cross-feature操作には次の2つだけを使う。

- relation target: workspace-global stable ID
- promotion source: generic `EntityRecord`の`id`, `kind`, `title`, `body`, `path`

GTDのTask classやstatusをKnowledgeへimportしてはならない。

## Write path

create/update/promoteは次の順序で行う。

1. workspace lockを取得する。
2. 現在recordとworkspace-global ID indexを読み直す。
3. Pydantic schema、ID/alias uniqueness、link target/self/duplicate invariantを検証する。
4. frontmatterとMarkdown bodyをatomic replaceする。
5. 成功eventをappend-only event storeへ追記する。

拒否時にMarkdownとevent countを変更してはならない。現在、snapshot replaceとevent appendは同一filesystem
transactionではない。両者の間でprocessが停止した場合の一般outbox recoveryは**UNKNOWN**である。

## Schema and direct edits

`KnowledgeNote`は`extra=forbid`で、hand editのtypoを黙って捨てない。filenameは`<id>.md`、kindは
`knowledge_note`、directoryは`knowledge/notes/`で一致させる。Workspace readerが構造/schemaを検査し、
Knowledge doctorがgraph整合性を検査する。

新しいfrontmatter fieldを追加する場合は次を行う。

1. schema version据え置きでoptional compatible fieldにするか、version migrationが必要かを決める。
2. malformed、unknown-field、reload、direct-edit doctor testを先に追加する。
3. public model、service、CLI/API request/response、workspace reference、user guideを同時に更新する。
4. old document fixtureでread/migrationを検証する。

M3にはKnowledge schema migrationがない。current accepted versionは1だけである。

## Adding a note type

note typeを増やす場合は、enumだけでなく次を同じsliceで変更する。

1. `KnowledgeNoteType`
2. `DEFAULT_TEMPLATES`
3. template initializationのnon-overwrite test
4. CLI enum helpとHTTP OpenAPI schema
5. user guideのtype選択表

templateはbodyだけを定義し、frontmatter invariantを含めない。initializerはmissing fileだけを作り、userが
編集したtemplateを上書きしない。

## Search and graph projections

Searchとbacklinkは現在のMarkdown snapshotsから再計算するprojectionである。永続indexを追加する場合も
正本にしてはならず、削除して再構築できるようにする。

Search orderingやmatching semanticsを変更するとCLI/API observable behaviorが変わるため、acceptance testと
specを先に更新する。backlinkを別entityへ永続化してoutbound linkとの二重正本を作らない。

Doctorはservice writeでは通常作れないbroken/duplicate graphも、direct-edited Markdownから報告できなければ
ならない。warningとerrorの区別、および`valid`の意味を保つ。

## Presentation projections

Marp technical reportはKnowledgeの別entityではなく、現在revisionから生成するread-only projectionである。
`technical_report` note typeは発表向けsectionを持つdefault templateだが、rendererは既存noteにも利用できる。

```text
Knowledge Markdown (authority)
        │
        └── KnowledgeService.render_presentation()
                         │
                         ├── CLI stdout / .marp.md
                         └── typed FastAPI response
```

rendererはsource file、revision、event storeを変更してはならない。Marp YAMLへ入るthemeはpublic modelで
検証してから補間し、source titleはYAML frontmatterへ入れない。level-two headingだけをslide boundaryへ変換し、
それ以外の本文は保持する。

visual templateは`MarpPresentationTemplate`のclosed enumで選び、workspaceの
`templates/knowledge/presentations/<template>.css`から読む。CSSはYAML block scalarの`style`へ2-space indentで
埋め込むため、生成物は外部のtheme-set設定に依存しない。initializerはmissing CSSだけを作り、user overrideを
上書きしない。既定`scientific` CSSのdesign根拠は
[research note](../research/scientific-presentation-template.md)に記録する。

`scientific` templateのMarkdown/CSS conventionは次のとおり。

- nested unordered listはlevel 1/2/3を`■`/`●`/`▲`へ置換し、32/28/24pxへ段階化する。
- inline childが`em:only-child`のparagraphを図表captionとして中央配置する。
- tableは`max-content`幅と`max-width: 100%`を併用し、内容幅を保ちながら中央配置する。
- `section:has(table ~ table)`で複数表を検出し、そのslideのtableだけfontとcell paddingをcompact化する。
- 複数表は横幅を推測してgrid化せず、source順に縦配置する。
- `section:has(ul):has(img):has(blockquote:last-child)`で「箇条書き→図→caption→LEAD」を検出し、図高を
  260px、LEADを24pxへ固定する。SVGも同じcontractを持つ。

HTML previewは`MarpCompiler` Portを介してcompileする。Application serviceはcompilerを引数で受け、CLI/APIの
compositionが`MarpCliCompiler`を渡す。adapterは次のsecurity contractを守る。

- executableはserver/process設定で選び、HTTP requestから受け取らない。
- `subprocess.run()`へargument listを渡し、shell expansionを使わない。
- isolated temporary directoryとtimeoutを使い、出力fileの存在とnonblankを検証する。
- raw HTMLとlocal file accessを有効化するMarp CLI optionを暗黙追加しない。
- missing executable、timeout、non-zero exit、missing outputをtyped errorへ変換する。

`WORK_SMARTER_MARP_CLI`は単一のexecutable名またはpathであり、argumentを含むshell commandではない。
PDF/PPTX/image compilerはbrowser runtimeを必要とするためこのsliceでは扱わない。詳細は
[ADR 0005](../architecture/0005-marp-technical-reports-as-projections.md)を参照する。

## Promotion rules

Promotionはfeature-specific importerではない。source recordのpublic shapeだけを読み、元bodyをcopyしてentity
source referenceを付ける。同じsourceの再実行はidempotentで、既存noteを上書きしない。

将来source同期が必要になっても`promote_record`の意味を黙って双方向syncへ変えない。provider syncは別の
publishing/import contractとして、remote identity、version、conflict policyを明示する。

## Adapter contract

- ID引数はfull IDまたはworkspace-unique prefixを受け付ける。
- Knowledge note queryはexact unique aliasも利用できる。
- CLI `--json`はstdoutへJSON以外を混ぜず、promptしない。
- HTTP requestは`extra=forbid`、responseはconcrete Pydantic modelで型付けする。
- collection updateの`None`は変更なし、空listはclearである。
- missing entity、ambiguous query、domain conflictはroot adapterのstable error mappingを使う。

## TDD matrix

最低限、次のpublic behaviorをtestする。

- create → Markdown reload → created event
- all note types、template selection、user template non-overwrite
- malformed/unknown frontmatterとworkspace placement
- full ID、unique prefix、aliasの成功／not found／ambiguous
- tag/alias normalizationとglobal ID/alias collision
- explicit update、collection clear、revision、updated event
- title/tag/body/alias searchとfield restriction
- valid/self/missing/duplicate/ambiguous link、derived backlink
- generic promotion、source provenance、repeat idempotency、multiple-claim conflict
- doctor orphan/source-connected/broken/duplicate graph
- CLI JSON purityとHTTP/OpenAPI typing/error mapping
- Marp slide boundary、source revision、read-only behavior、unsafe theme、output overwrite refusal
- scientific visual template、user override non-overwrite、CSS block-scalar埋め込み、CLI/API template contract
- 3-level list marker、図表caption中央揃え、2-table compact layout、overflowなしのvisual QA
- 24/21/18pt相当のlist階層、list→figure→caption→LEAD順序、18pt相当LEADのvisual QA
- fake Marp compiler、fixed argument、HTML media type、missing/failing compiler error
- package import boundaryとfeature composition

```bash
.venv/bin/pytest -q tests/test_knowledge_service.py \
  tests/test_knowledge_cli.py tests/test_knowledge_api.py
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/pytest -q
```

## Current non-goals

Confluence conversion/sync、Marp PDF/PPTX/image compile、複数visual template、binary attachment、semantic index、
multi-user collaborationはこのpackageへ実装しない。
それらはpublic Knowledge contractを利用する別feature/projectionとする。
