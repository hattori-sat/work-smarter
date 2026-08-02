# Project management

`ws project`（互換alias: `ws pm`）はGTDの複数アクション・プロジェクトとは別の、管理対象プロジェクト用機能です。phase、work package、milestone、依存関係、クリティカルパス、QCD、risk/issue/decision、要求とV&V証跡をMarkdown正本から管理します。

例: `ws pm create "Release R1" --goal "安全に出荷" --criterion "スポンサー承認"`。`ws pm schedule ID --format mermaid` でテキストのガントを生成できます。

## Working calendar and dependency

既存projectとの互換性のため既定は週7日です。月〜金を稼働日にする場合は次のように明示します。

```bash
ws project create "Release R1" --goal "安全に出荷" --criterion "承認済み" \
  --working-weekday 0 --working-weekday 1 --working-weekday 2 \
  --working-weekday 3 --working-weekday 4 --holiday 2026-08-11
```

dependency typeは`finish_to_start`、`start_to_start`、`finish_to_finish`、`start_to_finish`です。
正の`--lag`はlag、負はleadです。

```bash
ws project dependency add MP-123 WP-TEST WP-BUILD --type start_to_start --lag 1
ws project dependency explain MP-123 WP-TEST
```

## Interactive offline Gantt

```bash
ws project gantt export MP-123 --output reports/release-gantt.html
ws project gantt open MP-123
```

HTMLは単一fileで、network接続を要求しません。filterとzoomを持ち、today marker、baseline/current、
progress、delay、critical path、total/free float、milestone、dependency line、owner、Jira表示状態を確認できます。
Baselineは`ws project baseline create MP-123 --label "Approved plan"`で固定したschedule snapshotを
表示します。
