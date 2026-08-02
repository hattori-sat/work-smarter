# HTTP API and typed client

## Outcome

FastAPIはCLI、VS Code、将来UIが共有するlocal application boundaryです。Domain rulesはserviceに置き、routeは
Pydantic request/response、stable error mapping、HTTP statusだけを担当します。

## Run locally

```bash
ws --workspace ./workspace server start --host 127.0.0.1 --port 8765
```

- OpenAPI: `GET /openapi.json`
- Swagger UI: `GET /docs`
- Health/migration: `GET /health`
- GTD: `/api/gtd/*`
- Knowledge: `/api/knowledge/*`
- Managed Project: `/api/projects/*`
- Operation journal: `/api/system/operations*`
- Outbox: `/api/system/outbox*`

V1 server commandはnon-loopback hostを拒否します。Authenticationを追加するADRなしにこの制約を緩めません。

## Adapter rules

1. Request/responseは`BaseModel(extra="forbid")`かdomain public modelを使用する。
2. `Any` response、prompt、human textをJSON bodyへ混ぜない。
3. Application serviceのtyped errorをroot exception handlerで404/409/400/503へ一貫mappingする。
4. Write invariantはworkspace lockまたはDatabase transaction内で検証する。
5. RouteからSQL、Markdown移動、provider SDKを直接呼ばない。
6. OpenAPI contract testでrequest bodyとresponse schemaを固定する。

## Typed loopback client

`WorkSmarterHttpClient`はsystem operation/outbox contractをPydantic modelへdecodeします。

```python
from work_smarter.http_client import WorkSmarterHttpClient

with WorkSmarterHttpClient("http://127.0.0.1:8765") as client:
    operations = client.list_operations()
```

Clientはloopback `http`だけを受け入れ、credential、query、fragment、application pathを拒否します。Transportを
injectできるため、testはnetworkを使わずcontractとerror decodingを検証できます。

## Operation and outbox semantics

- `GET /api/system/operations`: newest-first、bounded list。
- `GET /api/system/operations/{id}`: full operation ID。
- `POST /api/system/operations/recover`: pending intentをprojection照合して解決。
- `GET /api/system/outbox`: newest-first、bounded list。
- `POST /api/system/outbox`: `operation_id`でidempotent enqueue。
- `POST /api/system/outbox/run`: bounded claim/deliver/retry。

Outbox provider destinationはapplication compositionでinjectします。Credentialやprovider sync stateはordinary
frontmatterへ保存しません。

## Verification

```bash
.venv/bin/pytest tests/test_api.py tests/test_system_adapters.py
.venv/bin/python scripts/release_smoke.py
```

Facts: schema/OpenAPI、direct CLI、MockTransport client、installed wheelをtestします。
UNKNOWN: remote authenticationとmulti-user API conflict policyはV1範囲外です。
