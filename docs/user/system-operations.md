# System operations

通常はWork SmarterがDatabase migration、journal recovery、outbox retryを自動処理します。このページは
backup前、provider障害時、`failed`/`pending` operationを調べる場合のrunbookです。

## Check application health

```bash
ws server start --host 127.0.0.1 --port 8765
curl http://127.0.0.1:8765/health
```

`schema_version`と`latest_schema_version`が一致し、workspaceがinitializedなら通常状態です。

## Inspect an operation

```bash
ws --json system operation list
ws --json system operation show OP-...
ws system operation recover
```

- `completed`: Database stateとprojectionがcommit済み。
- `failed`: 通常例外またはprojection mismatchにより拒否済み。自動再実行しない。
- `pending`: processが途中終了した可能性がある。`recover`がfileを検証して判断する。

`failed`の原因を直した後は、元のdomain commandを新しいoperationとして再実行します。Journal rowを手で
変更しないでください。

## Inspect delivery

```bash
ws --json system outbox list
ws system outbox run --limit 25
```

Provider destinationがinstallされていない場合、messageは削除されずretry可能な`failed`になります。Credentialは
workspaceへ書かず、provider adapterがenvironmentまたはOS credential storeから取得します。

手動enqueueはintegration開発・復旧用です。

```bash
ws system outbox enqueue SYNC-20260803-1 \
  --destination fake \
  --type entity.changed \
  --payload '{"entity_id":"TASK-1"}'
```

同じ`operation_id`とpayloadの再enqueueは同じmessageを返します。異なるpayloadへのkey再利用は拒否されます。

## Use the local HTTP server

```bash
ws --server-url http://127.0.0.1:8765 --json system outbox list
```

Clientはloopback HTTPだけを許可します。Remote host、URL credential、query、fragment、application pathは
拒否されます。Remote運用はV1の対象外です。

## Recovery sequence

1. `ws workspace export`で現在状態をbackupする。
2. `ws system operation list`でpending/failedを確認する。
3. `ws system operation recover`を1回実行する。
4. Domain doctorを実行する。
5. Provider障害が解消済みなら`ws system outbox run`を実行する。
6. 解決しない場合、backupとoperation IDを保持し、Database/Markdownを手編集しない。

## Known boundaries

- Single-user local workspaceとPOSIX lockが前提です。
- Remote authentication、multi-user permission、distributed workerは未対応です。
- Markdown本文は直接編集可能ですがfrontmatterはread-only projectionです。
