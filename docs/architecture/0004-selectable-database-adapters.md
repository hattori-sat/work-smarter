# ADR 0004: Selectable database adapters behind explicit ports

- Status: Accepted
- Date: 2026-08-02
- Extends: ADR 0003

## Outcome

SQLiteを初期Database adapterとして維持しつつ、ApplicationとDomainを特定Database、driver、SQL方言へ
依存させない。将来Microsoft Access等のadapterをworkspace単位で選択できるようにする。

## Facts

- SQLiteは現在利用可能な唯一のbuilt-in backendである。
- 将来、Microsoft Accessを利用する可能性があるが、driver、ODBC/DAO、対応OSは未決定である。
- SQLite backup API、`PRAGMA`、WAL sidecar、migration DDLはSQLite固有である。
- Domain/Applicationが汎用SQL文字列を受け取る設計では、SQL dialectとinjection riskが境界外へ漏れる。

## Considered paths

### Application全体を一つのORMへ依存させる

共通CRUDは短くなるが、Accessを含む全backendのmigration、transaction、backup、型変換を同じ品質で
扱える保証はない。ORM固有APIが新しいlock-inになる。

### Backendごとの条件分岐をApplication Serviceへ置く

実装開始は速いが、use case、FastAPI、CLI、backupへ`if sqlite`／`if access`が拡散する。

### 明示的なPortとadapter registryを使う

adapterごとの実装量は増えるが、driverとSQLをinfrastructureへ閉じ込め、workspace設定からbackendを
選択できる。

## Decision

3番目を採用する。

1. `DatabaseBackend` Portはlifecycle、schema status、migration、snapshot、snapshot verificationを定義する。
2. `DatabaseBackendRegistry`がworkspace設定の`database.backend`をadapter factoryへ解決する。
3. Built-in SQLiteは`work_smarter.shared.persistence.sqlite`だけで`sqlite3`を使用する。
4. 外部adapterはPython entry point `work_smarter.database_backends`へfactoryを登録できる。
5. Backup manifestはbackend名とsnapshot memberを記録し、restoreは同じadapterで検証する。
6. Provider credentialをworkspace configへ保存しない。configはbackend名とnon-secret locationだけを持つ。
7. Domain CRUDでは汎用`Database.execute` Portを公開しない。V1はregistered Pydantic kindを扱う
   `StructuredStateStore`、activity、operation、outboxのuse-case Portをadapterが実装する。
8. SQLを使うadapterはstatic statementとparameter bindingの安全契約を守る。Access adapterも文字列連結で
   queryを生成しない。
9. Backend変更時のdata migrationは明示的なexport/verify/import operationとし、config変更だけで既存dataを
   暗黙変換しない。

Workspace設定例：

```yaml
database:
  backend: sqlite
  location: .work-smarter/work-smarter.db
```

`location`未指定時はadapterのlocal-first defaultを使用する。Backend変更後はserver restartを必要とする。

## Consequences

- FastAPI、CLI、workspace operationsはSQLite classをimportしない。
- SQLite固有のtransaction helperはSQLite adapter内部でのみ使用する。
- Access adapterはcore変更なしで追加できるが、Portの全contractと同じacceptance testsを満たす必要がある。
- Backup archiveはbackend metadataを持つ。旧SQLite archiveは互換fallbackで読める。
- 現在`access`を選択すると、adapter未導入を示すtyped errorになる。

## Unknowns

- Access adapterのdriver、ODBC/DAO選択、macOS/Linux上の利用可否はUNKNOWN。
- SQLiteからAccessへのdata migration formatと型変換規則はUNKNOWN。
- Accessのtransaction、concurrent writer、online snapshot能力はUNKNOWN。
- Domain別secondary index/read modelの必要性は利用規模の実測前のためUNKNOWN。
