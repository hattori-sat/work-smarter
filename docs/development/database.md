# Database persistence and SQL safety

## Outcome

Database lifecycleとstructured stateをprovider-neutral Portへ分離し、SQLite等のadapterごとにonline
backup、migration、operation recovery、outbox、SQL injection防止をinfrastructure boundaryで管理します。

## Port and adapter selection

Workspaceは次の設定でbackendを選択します。

```yaml
database:
  backend: sqlite
  location: .work-smarter/work-smarter.db
```

- `DatabaseBackend`はstatus、migration、snapshot、verificationを公開します。
- `DatabaseBackendRegistry`はbuilt-in SQLiteとentry point `work_smarter.database_backends`を合成します。
- `StructuredStateBackend` capabilityは`StructuredStateStore`を公開し、registered entity、activity、journal、
  outboxを扱います。Domain repositoryはSQLを受け取りません。
- `location`はcredentialを含まないlocal resourceだけに使用します。Password/tokenはenvironmentまたは
  OS credential storeからadapterが取得します。
- Backend設定の変更は既存dataを移行しません。明示的なmigration operationが必要です。

## Facts

- 初期adapterはworkspace内の`.work-smarter/work-smarter.db`を使うSQLiteです。
- Domain moduleは`sqlite3`をimportしません。
- BackupはSQLite backup APIでtransactionally consistentなsnapshotを作ります。
- Restoreはarchive展開前に`PRAGMA quick_check`とmigration metadataを検証します。
- `-wal`、`-shm`、`-journal`はbackup artifactではなく、archiveへ格納しません。
- Workspace外を参照するDatabase symlinkはbackup時に拒否します。
- Schema v2ではregistered entityのstructured payloadとactivity historyがDatabase正本です。
- Markdown本文はnarrative正本です。frontmatterとJSONLは互換projectionであり、cutover後の直接変更を
  structured stateへ再importしません。

## Operation journal

Entity writeは次のprotocolです。

1. Databaseへ一意なoperation intentを`pending`で保存する。
2. Markdown projectionをtemporary file + `fsync` + atomic replaceで保存する。
3. Entity state、infrastructure activity event、journal completionを同じDatabase transactionでcommitする。

通常のPython例外はoperationを`failed`へ固定します。`SystemExit`やprocess killで`pending`が残った場合だけ、
次回workspace openまたは`ws system operation recover`がprojectionを検証します。一致すればcomplete、
missing/mismatchならfailedです。Failed operationのfileをlegacy importで復活させることはありません。

```bash
ws --workspace ./workspace system operation list
ws --workspace ./workspace system operation show OP-...
ws --workspace ./workspace system operation recover
```

## Transactional outbox

```bash
ws --workspace ./workspace system outbox enqueue SYNC-123 \
  --destination confluence --type page.push --payload '{"page_id":"123"}'
ws --workspace ./workspace system outbox list
ws --workspace ./workspace system outbox run --limit 25
```

Workerはmessageを最大5分leaseし、provider call中はDatabase transactionを保持しません。Provider adapterは
`operation_id`をidempotency keyとして扱います。成功はcompleted、通常例外と未導入destinationはretry可能な
failedへ戻ります。Crashしたprocessing leaseは期限後に別workerがclaimできます。

`--server-url http://127.0.0.1:8765`を指定するとsystem CLIはtyped HTTP clientで同じAPI contractを使います。
Remote host、credentialを含むURL、application pathは拒否します。

## SQL injection contract

1. `execute`と`executemany`のSQL statementはsource code上のstatic string literalにします。
2. ID、title、filter、payload等の外部値は、文字列連結やformatを使わずplaceholderへbindします。

   ```python
   connection.execute(
       "SELECT id FROM activity_events WHERE aggregate_id = ?",
       (aggregate_id,),
   )
   ```

3. Table名、column名、sort方向はplaceholderへbindできません。必要な場合はpublic enumをclosed mapで
   完成済みのstatic statementへ変換します。任意文字列からidentifierを組み立てません。
4. User inputを`PRAGMA`、`executescript`、migration DDLへ渡しません。
5. APIやCLIへ任意SQL実行機能を公開しません。
6. `tests/test_sql_safety.py`はruntime interpolationまたは変数化されたstatementを拒否します。
7. SQLを利用する将来のAccess/ODBC adapterにも同じparameter binding contractを適用します。

## Inferences

- Parameter bindingはSQL構文のinjectionを防ぎますが、過大なresult setやLIKE wildcard等のsemantic abuseは
  別のvalidationが必要です。
- Static statement制約は少し冗長でも、single-user local applicationでの監査容易性を優先できます。

## Unknowns

- Domain別query performanceとsecondary index構成は実測前のためUNKNOWNです。
- Database schema migration失敗時の自動rollback/restore policyはUNKNOWNです。
- Microsoft Access adapterのdriver、対応OS、transaction/snapshot能力はUNKNOWNです。
