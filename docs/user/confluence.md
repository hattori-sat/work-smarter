# Confluence Cloud

MarkdownのfrontmatterにConfluenceのspace/page mappingを保持し、`ws confluence configure`, `plan`, `push`, `pull` で公開・取得します。認証情報は環境変数 `WORK_SMARTER_CONFLUENCE_BASE_URL`, `WORK_SMARTER_CONFLUENCE_EMAIL`, `WORK_SMARTER_CONFLUENCE_API_TOKEN` から読み、文書には保存しません。

競合時は自動上書きせず停止します。`--dry-run`、`--force`、pull時の`--accept-loss`を明示してください。
