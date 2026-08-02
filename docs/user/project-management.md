# Project management

`ws pm` はGTDの複数アクション・プロジェクトとは別の、管理対象プロジェクト用機能です。phase、work package、milestone、依存関係、クリティカルパス、QCD、risk/issue/decision、要求とV&V証跡をMarkdown正本から管理します。

例: `ws pm create "Release R1" --goal "安全に出荷" --criterion "スポンサー承認"`。`ws pm schedule ID --format mermaid` でテキストのガントを生成できます。
