# Database persistence and SQL safety

## Outcome

Database lifecycleをprovider-neutral Portへ分離し、SQLite等のadapterごとにonline backup、migration、
SQL injection防止をinfrastructure boundaryで管理します。

## Port and adapter selection

Workspaceは次の設定でbackendを選択します。

```yaml
database:
  backend: sqlite
  location: .work-smarter/work-smarter.db
```

- `DatabaseBackend`はstatus、migration、snapshot、verificationだけを公開します。
- `DatabaseBackendRegistry`はbuilt-in SQLiteとentry point `work_smarter.database_backends`を合成します。
- Domain repositoryはこのPortへSQLを渡しません。Use case別Repository Portを別途定義します。
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

- Domain repository追加後のquery performanceとindex構成は実測前のためUNKNOWNです。
- Database schema migration失敗時の自動rollback/restore policyはUNKNOWNです。
- Microsoft Access adapterのdriver、対応OS、transaction/snapshot能力はUNKNOWNです。
