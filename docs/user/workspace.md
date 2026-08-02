# Workspace and Markdown

各taskは `tasks/<stable-id>.md` の1ファイルです。frontmatterは機械が読む状態、本文は人が読む
goal、制約、メモ、結果、証拠を保持します。

## Safe direct editing

VS Codeでの直接編集は正式に対応します。ただしID、kind、status固有必須fieldは壊さないでください。

```bash
ws doctor
```

doctorがerrorを返した場合、その文書をCLI/APIが任意解釈して更新することはありません。

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

完全なformat contractはdeveloper reference
[Workspace format 0.1](../reference/workspace-format.md)にあります。
