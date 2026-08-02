# Testing strategy

## TDD loop

1. user journeyまたはdomain invariantを失敗するtestで表す。
2. public application serviceを通して最小実装する。
3. CLI/API adapterの入出力contractを追加する。
4. persistence reload後も同じ状態になることを確認する。
5. refactorして全suiteを再実行する。

## Test layers

- domain/service: state transition、invariant、時間、関連
- storage: YAML strictness、atomicity、path safety、corruption
- structured persistence: one-time import、journal crash recovery、outbox lease/retry、backup reload
- adapter: CLI non-interactive/JSON、HTTP status/OpenAPI
- feature boundary: import direction、codec composition、disabled feature
- acceptance: captureからreview/publishまでのuser flow

## Required transition cases

- allowed transition
- refused transition and stable error
- persisted state after reopening workspace
- audit event and duration/history
- concurrent request behavior
- doctor behavior after direct file corruption

## Commands

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/pytest --cov=work_smarter --cov-report=term-missing
.venv/bin/python scripts/release_smoke.py
```

`release_smoke.py`は一時venvを作り、1.0 wheelとruntime dependencyをinstallし、console script、capture、
operation journal、backup/restore、doctorをsource treeの`PYTHONPATH`なしで実行する。
