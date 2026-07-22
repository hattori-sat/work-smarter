# Work Smarter v1 — implementation tracker

最終更新: 2026-07-23

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
- GTD MVPの基礎実装と43 testsは `feat/foundation` へ導入中である。
- source of truthはMarkdown frontmatterとappend-only audit eventである。

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
- [ ] `dev/work-smarter-v1`へのmerge

### M1 GTD ticket model — `feat/gtd-ticket-model`

- [ ] work type: action / decision / investigation / communication / routine
- [ ] goal / why / desired outcome
- [ ] constraints / assumptions / risks
- [ ] definition of done / acceptance criteria / evidence
- [ ] priorityを直接順位ではなくurgency・impact・commitmentで表現
- [ ] parent / depends-on / blocks / relates-to links
- [ ] estimate / remaining / actual work log
- [ ] recurring ruleとnext occurrence
- [ ] schema migration 1→2
- [ ] ticket create/show/edit/link CLI/API

### M2 GTD workflow — `feat/gtd-workflow`

- [ ] clarify decision treeとtwo-minute handling
- [ ] explicit transition validator
- [ ] delegate→waiting-for transition
- [ ] delegatee / requested-at / expected-by / follow-up-on / escalation-after
- [ ] response log、chase、resolve、reopen
- [ ] blocked reason + blocker link + unblock
- [ ] calendar / not-before / due semantics
- [ ] daily dashboard、tickler、weekly review checklist state
- [ ] cycle time、lead time、WIP、estimate error、waiting age metrics
- [ ] recurring task generation

### M3 Knowledge — `feat/knowledge`

- [ ] independent knowledge entity/repository/service
- [ ] note / decision / how-to / reference / meeting-note templates
- [ ] tags、aliases、outbound links、backlinks
- [ ] title/tag/body search
- [ ] captureからknowledgeへのpromotion
- [ ] orphan/broken-link doctor
- [ ] CLI/API

### M4 Project management — `feat/project-management`

- [ ] managed project / phase / work package / milestone models
- [ ] WBS and dependency DAG validation
- [ ] text schedule format and critical-path calculation
- [ ] terminal table、Mermaid Gantt、HTML table projection
- [ ] QCD baseline/current/forecast
- [ ] risk/opportunity/issue/decision registers
- [ ] completion criteria、constraints、assumptions、stakeholder fields
- [ ] NASA/JERGを参考にしたdocument template catalog
- [ ] GTD actionへのstable-ID link（state machineは共有しない）
- [ ] CLI/API

### M5 Confluence publishing — `feat/confluence-sync`

- [ ] provider-neutral publishable document contract
- [ ] Confluence frontmatter (`space_key`, `page_id`, `parent_id`, `title`)
- [ ] Cloud REST client、tokenはenvironment/keyringのみ
- [ ] Markdown↔Confluence storage-format conversion boundary
- [ ] dry-run、push、pull
- [ ] content hash/versionによるconflict detection
- [ ] project Gantt/QCD table projection
- [ ] fake server contract tests、credentialsなしacceptance

### M6 VS Code and integration — `feat/vscode-integration`

- [ ] command/task snippets for capture/add/status/focus/review
- [ ] workspace recommendations and keybinding examples
- [ ] API schema/client contract
- [ ] cross-feature dashboard
- [ ] export/import/backup and migration commands

### M7 Release quality — `feat/release-quality`

- [ ] user journey acceptance tests
- [ ] corrupt/crash/concurrency/recovery tests
- [ ] package install and clean-room smoke test
- [ ] user manual完成
- [ ] developer architecture/API/contribution manual完成
- [ ] changelog and v1 release checklist
- [ ] `dev/work-smarter-v1` → `main` merge

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
