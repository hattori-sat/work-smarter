# Developer guide

## Architecture

Work SmarterはFastAPI local application serverを持つPython modular monolithです。

Target Architectureへの移行方針は
[ADR 0003](../architecture/0003-hybrid-source-of-truth-and-local-application-server.md)を参照してください。
SQLiteとMarkdownは情報種別ごとに正本を分担します。Registered entityのstructured state/activityはDatabase、
narrative本文はMarkdownが正本です。FrontmatterとJSONLは互換projectionです。

- `work_smarter.storage`: feature-neutral Markdown、JSONL、atomic write、lock
- `work_smarter.composition`: enabled featureのcodec/hook合成
- `work_smarter.gtd`: GTD aggregateとworkflow
- `work_smarter.knowledge`: independent Knowledge schema、graph、search projection
- `work_smarter.knowledge.presentations`: read-only Marp presentation projection
- `work_smarter.project_management`: managed project boundary
- `work_smarter.api`: GTDとKnowledge routerをmountするtyped HTTP host
- `work_smarter.cli`: feature subcommandをmountするkeyboard/script host
- `work_smarter.shared.persistence`: database Port、adapter registry、provider別migration/backup
- `work_smarter.shared.outbox`: leased claim/retry/idempotent completion worker
- `work_smarter.http_client`: loopback-only typed API transport

新featureはgeneric storageへmodelを追加せず、`EntitySpec`をcomposition rootへ登録します。

## Setup

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/pytest
```

`pyproject.toml`がpackage dependency rangeの正本です。`requirements.txt`と
`requirements-dev.txt`はpipを使うruntime/development環境の標準entry pointであり、前者は`.`、
後者は`.[dev]`をinstallします。macOS/iCloud配下でhidden `.pth`が無視される環境でもconsole scriptが
壊れないよう、既定はeditable installに依存しません。source変更後は同じinstall commandを再実行します。
Gantt HTMLは組込みrendererのためNode/CDN dependencyを追加しません。

## Delivery

- [Branching](branching.md)
- [Testing](testing.md)
- [Database persistence and SQL safety](database.md)
- [HTTP API and typed client](api.md)
- [Contributing](contributing.md)
- [Selectable database adapters ADR](../architecture/0004-selectable-database-adapters.md)
- [Marp technical report projection ADR](../architecture/0005-marp-technical-reports-as-projections.md)
- [Explainable offline Gantt ADR](../architecture/0006-explainable-offline-gantt.md)
- [Database authority, journal, and outbox ADR](../architecture/0007-database-authority-journal-and-outbox.md)
- [Developing the GTD workflow](gtd-workflow.md)
- [Developing Knowledge](knowledge.md)
- [Developing project management](project-management.md)
- [Confluence publishing](confluence.md)
- [VS Code integration](vscode.md)
- [GTD workflow specification](../specs/gtd-workflow.md)
- [Knowledge specification](../specs/knowledge.md)
- [GTD completion and Gantt specification](../specs/gtd-completion-and-gantt.md)
- [TASK.md](../../TASK.md)
- [Feature contract ADR](../architecture/0002-feature-contract.md)

public interfaceを変更した場合はCLI help、OpenAPI、user docs、schema migrationの4点を確認します。

Release前の検証と既知の制約は [release checklist](release.md) に集約します。
