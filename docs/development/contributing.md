# Contributing

## Branch and commit flow

```text
main → dev/<epic> → feat/<slice>
```

Feature workを`main`や`dev/*`へ直接commitしません。Acceptanceがgreenになったfeatureだけを`--no-ff`でdevへ
mergeし、release checklist完了後だけdevをmainへmergeします。CommitはConventional Commitsを使います。

## Required TDD loop

1. User-observable acceptance testを失敗させる。
2. Invariant、refusal、audit、persistence reloadのfocused testを追加する。
3. 最小のpublic service/Portを実装する。
4. CLI/API adapterとOpenAPI contractを追加する。
5. Refactor後に全suiteを実行する。
6. `TASK.md`とuser/developer docsを同じmaterial commitで更新する。

## Public boundaries

- CLI/HTTPはadapter、domain ruleはapplication service。
- Cross-feature relationはstable IDとpublic contractだけを使う。
- Domain moduleはFastAPI、`sqlite3`、provider SDKをimportしない。
- SQL statementはstatic literal、値はparameter binding。
- Structured stateはDatabase、narrative bodyはMarkdown。Frontmatterはread-only projection。
- Provider credentialをworkspace documentへ保存しない。
- `--json`はpromptせず、stdoutへhuman textを混ぜない。

## Local checks

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/pytest
.venv/bin/python scripts/release_smoke.py
```

## Review checklist

- Allowed/refused transitionとtyped errorがある。
- Audit activityとoperation journalがある。
- Reopen/backup restore後も同じpublic stateになる。
- Crashとconcurrency boundaryがtestされる。
- Malformed/unknown field/direct projection editをdoctorまたはmigrationが扱う。
- New dependencyは`pyproject.toml`へ分類し、requirements entry pointからinstallできる。
- User behaviorとarchitecture decisionを該当manual/ADRへ残す。

## Unknowns and escalation

Evidence不足は`UNKNOWN`と記録し、推測でremote security、schema authority、provider contractを決めません。
Published history rewrite、credential送信、external publish、destructive migrationは明示approvalなしに行いません。
