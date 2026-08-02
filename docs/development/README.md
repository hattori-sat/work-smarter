# Developer guide

## Architecture

Work SmarterはFastAPI local application serverを持つPython modular monolithです。

Target Architectureへの移行方針は
[ADR 0003](../architecture/0003-hybrid-source-of-truth-and-local-application-server.md)を参照してください。
SQLiteとMarkdownは情報種別ごとに正本を分担します。既存domainは移行完了までMarkdown/JSONLを正本とし、
SQLiteへ曖昧な二重書込みを行いません。

- `work_smarter.storage`: feature-neutral Markdown、JSONL、atomic write、lock
- `work_smarter.composition`: enabled featureのcodec/hook合成
- `work_smarter.gtd`: GTD aggregateとworkflow
- `work_smarter.knowledge`: independent Knowledge schema、graph、search projection
- `work_smarter.project_management`: managed project boundary
- `work_smarter.api`: GTDとKnowledge routerをmountするtyped HTTP host
- `work_smarter.cli`: feature subcommandをmountするkeyboard/script host
- `work_smarter.shared.persistence`: SQLite接続、transaction、forward-only migration

新featureはgeneric storageへmodelを追加せず、`EntitySpec`をcomposition rootへ登録します。

## Setup

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install '.[dev]'
.venv/bin/pytest
```

## Delivery

- [Branching](branching.md)
- [Testing](testing.md)
- [Developing the GTD workflow](gtd-workflow.md)
- [Developing Knowledge](knowledge.md)
- [Developing project management](project-management.md)
- [Confluence publishing](confluence.md)
- [VS Code integration](vscode.md)
- [GTD workflow specification](../specs/gtd-workflow.md)
- [Knowledge specification](../specs/knowledge.md)
- [TASK.md](../../TASK.md)
- [Feature contract ADR](../architecture/0002-feature-contract.md)

public interfaceを変更した場合はCLI help、OpenAPI、user docs、schema migrationの4点を確認します。

Release前の検証と既知の制約は [release checklist](release.md) に集約します。
