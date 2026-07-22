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

完全なformat contractはdeveloper reference
[Workspace format 0.1](../reference/workspace-format.md)にあります。
