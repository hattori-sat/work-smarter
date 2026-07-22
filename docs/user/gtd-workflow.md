# GTD workflow

## Capture

判断を後回しにして頭を空にします。

```bash
ws capture "気になっていること"
```

すでに具体的な行動ならInboxを経由したprovenanceを保ったまま一発で作れます。

```bash
ws add "障害logを10分確認する" --context @computer --estimate 10
```

## Clarify

```bash
ws clarify
```

最古の項目が開きます。判断順序は次です。

1. 行動が必要か。
2. 2分以内なら今完了するか。
3. 自分が行うか、委任してwaiting-forにするか。
4. 1 actionか、複数actionを要するGTD projectか。
5. 実行可能な次の物理行動は何か。

scheduledは「その日にしたい」ではなく、「その日時にしか意味がない」場合だけ使います。

## Engage

```bash
ws status
ws focus --context @computer --minutes 30 --energy medium
ws start TASK-...
ws done TASK-...
```

doingは1件だけです。割込み時は元のtaskをstopするか、明示的に`--switch`します。

## Waiting-for

clarify時に相手または外部条件を記録し、依頼日時、期待期限、follow-up、escalationをticketへ
保持します。blockerが重なってもWaitingという委任文脈は失われず、reviewでは両方の観点に現れます。

応答が来たら次のactionへ戻します。

```bash
ws ready TASK-...
```

## Reflect

毎日 `ws status`、週に一度次を実行します。

```bash
ws review
ws review --complete
ws doctor
ws metrics
```

metricsは自分を罰するscoreではなく、見積りの癖、待ち時間、WIP、流れの詰まりを発見する材料です。
