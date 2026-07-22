# Developer guide

## Architecture

Work SmarterはPython modular monolithです。

- `work_smarter.storage`: feature-neutral Markdown、JSONL、atomic write、lock
- `work_smarter.composition`: enabled featureのcodec/hook合成
- `work_smarter.gtd`: GTD aggregateとworkflow
- `work_smarter.project_management`: managed project boundary
- `work_smarter.api`: typed HTTP adapter
- `work_smarter.cli`: keyboard/script adapter

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
- [TASK.md](../../TASK.md)
- [Feature contract ADR](../architecture/0002-feature-contract.md)

public interfaceを変更した場合はCLI help、OpenAPI、user docs、schema migrationの4点を確認します。
