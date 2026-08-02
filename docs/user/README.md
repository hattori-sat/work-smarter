# Work Smarter user guide

Work Smarterは、個人の業務を頭の外へ出し、いま実行する1件へ集中するためのtext-first systemです。

## Start here

1. root [README](../../README.md) の手順でinstallとworkspace初期化を行う。
2. [GTD workflow](gtd-workflow.md) に従い、captureとquick-addを使い分ける。
3. 重要な業務は [Task tickets](task-tickets.md) でgoalと完了条件を定義する。
4. 再利用する情報は [Knowledge guide](knowledge.md) に従い、GTDとは別のnoteへ育てる。
5. Markdownを直接編集する場合は [Workspace guide](workspace.md) を確認する。
6. 管理プロジェクトは [Project management](project-management.md)、Confluence公開は [Confluence](confluence.md)、VS Code導線は [VS Code](vscode.md) を参照する。
7. Recovery、operation journal、outboxは [System operations](system-operations.md) を参照する。

## Mental model

- Inbox: まだ意味を決めない入口
- Action: 1回の着手で進められる物理的な行動
- GTD project: 2個以上のactionが必要な望ましい結果
- Waiting-for: 自分以外の応答・成果・条件が次の進行を握る状態
- Scheduled: その日時でなければ意味がないもの
- Someday/Maybe: commitmentしていない候補
- Reference/Knowledge: 行動を要求しない再利用可能な情報

GTDの`reference` dispositionはInboxを行動不要として整理した記録です。独立Knowledge noteは
`knowledge/notes/`でtype、tag、alias、source、linkを管理します。後から検索・再利用したい情報には
[Knowledge feature](knowledge.md)を使います。

Work Smarterはpriorityの数字だけで次の行動を決めません。context、使える時間、energy、期限、
commitment、依存関係から「いま実行可能か」を先に判定します。

日々は`ws today`、`ws focus`、`ws start`を使い、他者待ちやblockerは
[GTD workflow](gtd-workflow.md#waiting-for-without-memory-work)のinteractionとして記録します。週次reviewは
保存されるsessionなので、途中で終了しても同じ場所から再開できます。
