# Workspace and Markdown

各taskは `tasks/<stable-id>.md` の1ファイルです。Databaseはstatus、relation、schedule等のstructured
state、Markdown本文はgoal、制約、メモ、結果、証拠等のnarrativeを保持します。FrontmatterはDatabaseから
生成されるread-only projectionです。

## Safe direct editing

VS CodeではMarkdown本文とuser templateを直接編集できます。Frontmatterを変更してもDatabase stateには
反映されず、次のCLI/API writeで再投影されます。新しいentity fileを手作業で置いても、legacy cutover完了後は
自動importされません。Structured fieldはCLI/APIを使ってください。

```bash
ws doctor
```

doctorがerrorを返した場合、その文書をCLI/APIが任意解釈して更新することはありません。

## Recovery and delivery status

```bash
ws system operation list
ws system operation recover
ws system outbox list
```

Operationが`failed`なら通常例外として拒否されており、reopenで勝手に再実行されません。`pending`はprocess
crashの可能性があり、workspace openまたは`recover`がMarkdown projectionとの一致を検証します。

Local server経由で同じsystem contractを使う場合は次のように指定します。

```bash
ws --server-url http://127.0.0.1:8765 system operation list
```

V1はloopback URLだけを許可します。

## Templates

`templates/gtd/task.md` と `templates/gtd/project.md` は自由に変更できます。`ws init`は既存templateを
上書きしません。schema fieldはtemplateではなくapplicationが管理します。

## Feature横断の状況を見る

`overview` はGTD、Knowledge、managed projectの公開serviceを通じて、件数と要注意項目を一度に
表示します。feature間のprivate modelは共有しません。

```bash
ws --workspace ./my-workspace --json overview
```

## Backup、restore、migration

workspace全体はchecksummed ZIPとしてexportできます。Markdown/YAML、設定、append-only event、
一貫したSQLite snapshotを含み、再生成可能なcache、lock、SQLite sidecar、
`.work-smarter/secrets/`は含みません。

```bash
ws --workspace ./my-workspace workspace export ./backup.ws.zip
ws --workspace ./restored workspace import ./backup.ws.zip
ws --workspace ./restored workspace migrate
```

import先は空でなければなりません。importは展開前にmanifest、各fileのSHA-256、archive path、
SQLite integrityとschema versionを検査し、改ざん・欠落・path traversal・破損Databaseを拒否します。
`migrate` はworkspace lockを取得し、全documentを現在のpublic schemaで検証・再保存します。
migration前には必ずexportしてください。

## Database backend

初期backendはSQLiteです。Workspaceの`.work-smarter/config.yml`でbackendとnon-secret locationを
選択できます。

```yaml
database:
  backend: sqlite
  location: .work-smarter/work-smarter.db
```

Microsoft Access等はadapterを追加すると選択できますが、現在built-inされていません。未導入のbackendを
指定するとserverは明示的なconfiguration errorを返します。Passwordや接続tokenはconfigへ書かず、
adapterがenvironmentまたはOS credential storeから取得します。

完全なformat contractはdeveloper reference
[Workspace format 0.1](../reference/workspace-format.md)にあります。
