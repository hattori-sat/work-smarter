# Work Smarter v1 — implementation tracker

最終更新: 2026-08-03

## Outcome

個人のengineering業務を、Markdownを正本としてcapture・実行・振り返り・knowledge化・
project計画・Confluence公開まで一貫して扱えるlocal-first systemを完成させる。

## Success criteria

- ファイルを手動移動しなくてもGTDを運用できる。
- task ticketにgoal、制約、前提、完了条件、依存、証拠、時間履歴が残る。
- waiting-forは委任先、依頼日時、follow-up、期限、応答、escalationを失わない。
- knowledgeはtag、link、backlink、全文検索で再利用できる。
- managed projectはGTD projectと分離され、WBS、依存、milestone、Gantt、QCD、riskを持つ。
- Confluence Cloudはfrontmatterでmappingし、dry-run、push、pull、競合検出ができる。
- CLI、HTTP API、VS Codeから同じapplication serviceを利用する。
- すべての主要state transitionをTDDで固定し、user/developer docsを分離する。

## Facts / Inferences / Hypotheses

### Facts

- `main` はGitHub上のinitial commitを基点とする。
- integration branchは `dev/work-smarter-v1`、実装sliceは `feat/*` とする。
- GTD foundationとrigorous Task schema v3は実装済みで、82 testsが通過している。
- 現行domainのsource of truthはMarkdown frontmatterとappend-only JSONL eventである。
- Target Architectureでは構造化情報をSQLite、narrative本文をMarkdownの正本とし、FastAPIを
  local application serverにする。
- `feat/release-quality`は`origin/dev/work-smarter-v1`へmerge済みである。

### Inferences

- Jiraのwork item、workflow validator、links、time trackingは参考になる。
- single-user GTDではassignee/reporter/permission schemeより、実行可能性と認知負荷の低さを優先する。
- project scheduleやConfluence viewはMarkdownから生成するprojectionにするとtext-firstを維持できる。

### Hypotheses to validate by dogfooding

- daily viewは「現在の1件 + follow-up期限 + 次の候補5件」で十分に意思決定できる。
- task作成時の必須項目はtitleだけにし、goal/constraints/DoDはclarifyまたは着手前validatorで補う方が速い。
- waiting-forの自動escalation候補表示が、週次reviewだけより取りこぼしを減らす。

## Branch map

```text
main
└── dev/work-smarter-v1
    ├── feat/foundation
    ├── feat/gtd-ticket-model
    ├── feat/gtd-workflow
    ├── feat/knowledge
    ├── feat/project-management
    ├── feat/confluence-sync
    ├── feat/vscode-integration
    └── feat/release-quality
```

各`feat/*`はtest・docs・implementationを含むself-contained commit群にし、green確認後に
`dev/work-smarter-v1`へ`--no-ff` mergeする。全acceptance通過後だけ`main`へmergeする。

## Progress

### M0 Foundation — `feat/foundation`

- [x] Python package、CLI、FastAPI、Markdown/JSONL persistence
- [x] capture / clarify / focus / WIP=1 / review / doctor / metrics
- [x] generic feature codec registryとPOSIX workspace lock
- [x] path traversal、duplicate ID、kind/directory mismatch検査
- [x] user-overridable GTD templates
- [x] 43 tests、85% coverage、wheel smoke test
- [x] repository instructionsとdocs routing
- [x] foundation commit
- [x] `dev/work-smarter-v1`へのmerge

### M1 GTD ticket model — `feat/gtd-ticket-model`

- Current branch: `feat/gtd-ticket-model`
- Status: COMPLETE

- [x] work type: action / decision / investigation / communication / routine
- [x] goal / why / desired outcome
- [x] constraints / assumptions / risks
- [x] definition of done / acceptance criteria / evidence
- [x] priorityを直接順位ではなくurgency・impact・commitmentで表現
- [x] parent / depends-on / blocks / relates-to links
- [x] estimate / remaining / actual work log
- [x] recurring ruleとnext occurrence
- [x] schema migration 1/2→3
- [x] ticket create/show/edit/link CLI/API

### M2 GTD workflow — `feat/gtd-workflow`

- Current branch: `feat/gtd-workflow`
- Status: COMPLETE

- [x] clarify decision treeとtwo-minute handling
- [x] explicit transition validator
- [x] delegate→waiting-for transition
- [x] delegatee / requested-at / expected-by / follow-up-on / escalation-after
- [x] response log、chase、resolve、reopen
- [x] blocked reason + blocker link + unblock
- [x] calendar / not-before / due semantics
- [x] daily dashboard、tickler、再開可能なweekly review checklist state
- [x] cycle time、lead time、WIP、estimate error、waiting/blocked age metrics
- [x] recurring task generation
- [x] append-only work-log correction
- [x] workspace timezoneを使った日付境界
- [x] CLI / typed HTTP API
- [x] 107 tests、85% coverage

### M3 Knowledge — `feat/knowledge`

- Current branch: `feat/knowledge`
- Status: COMPLETE

- [x] independent knowledge entity/repository/service
- [x] note / decision / how-to / reference / meeting-note templates
- [x] tags、aliases、outbound links、backlinks
- [x] title/tag/body/alias search
- [x] generic workspace recordからknowledgeへのidempotent promotion
- [x] orphan/broken/duplicate/ambiguous-link doctor
- [x] CLI / typed HTTP API / OpenAPI contract
- [x] 20 Knowledge testsを含む全180 tests green

### M4 Project management — `feat/project-management`

- [x] managed project / phase / work package / milestone models
- [x] WBS and dependency DAG validation
- [x] text schedule format and critical-path calculation
- [x] terminal table、Mermaid Gantt、HTML table projection
- [x] QCD baseline/current/forecast
- [x] risk/opportunity/issue/decision registers
- [x] completion criteria、constraints、assumptions、stakeholder fields
- [x] NASA/JERGを参考にしたdocument template catalog
- [x] GTD actionへのstable-ID link（state machineは共有しない）
- [x] CLI/API

### M5 Confluence publishing — `feat/confluence-sync`

- [x] provider-neutral publishable document contract
- [x] Confluence frontmatter (`space_key`, `page_id`, `parent_id`, `title`)
- [x] Cloud REST client、tokenはenvironment/keyringのみ
- [x] Markdown↔Confluence storage-format conversion boundary
- [x] dry-run、push、pull
- [x] content hash/versionによるconflict detection
- [x] project Gantt/QCD table projection
- [x] fake server contract tests、credentialsなしacceptance

### M6 VS Code and integration — `feat/vscode-integration`

- [x] command/task snippets for capture/add/status/focus/review
- [x] workspace recommendations and keybinding examples
- [x] typed OpenAPI schema/client contract
- [x] cross-feature dashboard
- [x] checksummed export/import/backup and schema migration commands

### M7 Release quality — `feat/release-quality`

- [x] cross-feature user journey acceptance tests
- [ ] corrupt/crash/concurrency/recovery tests（single-file atomicityとconcurrencyはcovered。
  multi-file crash recoveryはUNKNOWN）
- [ ] package install and clean-room smoke test
- [ ] user manual完成
- [ ] developer architecture/API/contribution manual完成
- [ ] changelog and v1 release checklist
- [ ] `dev/work-smarter-v1` → `main` merge

### M8 Target architecture foundation — `feat/architecture-foundation`

- Current branch: `feat/architecture-foundation`
- Status: COMPLETE

- [x] Target ArchitectureをADR 0003として記録
- [x] SQLite database pathとforward-only migration基盤
- [x] append-only activity event schemaとoutbox schema
- [x] workspace初期化とFastAPI lifecycleへのmigration統合
- [x] typed health responseでdatabase schema状態を公開
- [x] canonical `ws server start` commandとloopback-only制約

Follow-up slices:

- [x] SQLite snapshotを含む整合backup/restore (`feat/sqlite-backup`)
- [ ] domain単位のDatabase source-of-truth移行
- [ ] CLI domain/resource/operation treeとHTTP client化
- [ ] operation journalとoutbox worker

移行中の正本境界、比較案、未確認事項は
`docs/architecture/0003-hybrid-source-of-truth-and-local-application-server.md`を参照する。

### M9 SQLite backup and SQL safety — `feat/sqlite-backup`

- Current branch: `feat/sqlite-backup`
- Status: COMPLETE

- [x] SQLite backup APIによるonline snapshot
- [x] WAL transactionを含むbackup/restore acceptance
- [x] `-wal`、`-shm`、`-journal`のarchive除外
- [x] restore展開前のSQLite integrity/schema検証
- [x] parameter bindingでSQL injection payloadをdataとして保存
- [x] dynamic SQL interpolationを拒否するarchitecture test
- [x] provider-neutral Database Portとbackend registry
- [x] workspace設定によるbackend/location選択
- [x] backend metadata付きbackup/restore contract
- [x] fake non-SQLite adapterによる初期化・FastAPI・backup/restore acceptance
- [x] SQLite driver importのadapter内隔離
- [x] user/developer documentation

### M10 Marp technical reports — `feat/marp-technical-reports`

- Current branch: `feat/marp-technical-reports`
- Status: COMPLETE

- [x] `technical_report` Knowledge template
- [x] Knowledge revisionからのread-only Marp projection
- [x] source ID/revision付きのtyped presentation contract
- [x] canonical `ws knowledge presentation render` CLIとsafe overwrite
- [x] typed FastAPI/OpenAPI endpoint
- [x] YAML injectionを防ぐtheme validation
- [x] browser-ready HTML compileとpreview endpoint
- [x] 科学技術報告向け`scientific` visual template
- [x] title上端、H1/H2/H3階層、図表中央配置のHTML visual QA
- [x] workspaceで編集可能かつ再initで上書きしないpresentation CSS
- [x] CLI/APIのtyped template selection
- [x] source Markdownと監査eventを変更しないacceptance test
- [x] optional Marp CLI adapterによるbrowser-ready HTML preview
- [x] fixed subprocess argument、timeout、missing/failure typed error
- [x] `--format html` CLIと`text/html` FastAPI route
- [x] ADR 0005、user/developer/spec/reference documentation

## Definition of Done for every slice

1. 失敗するacceptance/unit testを先に置く。
2. 最小実装でgreenにする。
3. public I/O、関数境界、error semanticsをuser視点でreviewする。
4. `ruff check`、`ruff format --check`、全`pytest`を通す。
5. user-visible変更は`docs/user/`、設計変更は`docs/development/`またはADRへ残す。
6. TASK.mdを更新する。
7. Conventional Commit形式でcommitする。

## Research inputs

- Jira work item creation and child items:
  https://support.atlassian.com/jira-software-cloud/docs/create-a-work-item-and-a-subtask/
- Jira workflow transitions and validators:
  https://support.atlassian.com/jira-cloud-administration/docs/edit-an-issue-workflow/
- Jira work item links:
  https://support.atlassian.com/jira-software-cloud/docs/link-issues/
- Jira time tracking:
  https://support.atlassian.com/jira-software-cloud/docs/log-time-on-an-issue/
- Jira field configuration:
  https://support.atlassian.com/jira-cloud-administration/docs/edit-or-delete-a-custom-field/

採用・不採用の判断は `docs/research/jira-work-items-for-personal-gtd.md` に残す。
