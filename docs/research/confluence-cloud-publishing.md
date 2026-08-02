# Confluence Cloud publishing research

- 調査日: 2026-07-23
- Status: implementation input
- 対象: single-user Confluence Cloud

## Outcome

Work SmarterはConfluence Cloud REST API v2のpage/space endpointを使い、Markdownを正本、
Confluence pageを公開先とする。同期はblind overwriteではなく、local content hash、最後に同期したremote
version/hash、現在のremote version/hashを比較し、双方に変更があれば停止する。

文書先頭にはprovider-neutralなpublication envelopeとConfluence固有targetを置く。API token、last-synced
hash、remote snapshotはfrontmatterへ置かず、credentialはenvironment、再構築可能な同期状態は
`.work-smarter/sync/confluence/`へ分離する。

## Success criteria

- `space_key`, `page_id`, `parent_id`, publish titleをMarkdown frontmatterでreviewできる。
- page create/update/readにREST v2を使い、remote versionを明示的に扱う。
- `dry-run`はremote readを許すが、local/remote/stateを変更しない。
- 初回push、反復push、pull、no-op、local-ahead、remote-ahead、two-sided conflictを区別する。
- `--force`なしで既知のremote変更またはlocal変更を破壊しない。
- tokenをfile、event、exception、CLI argument、HTTP responseへ保存・表示しない。
- fake transport contract testだけで全同期分岐を再現でき、実credentialをtestに要求しない。

## Facts

- Confluence Cloud REST API v2はpage createを`POST /wiki/api/v2/pages`、page read/updateを
  `GET|PUT /wiki/api/v2/pages/{id}`として公開する。
- page createは`spaceId`, `title`, optional `parentId`, `body`を受け、storage representationを指定できる。
- page readには`body-format` queryがあり、storage bodyとversionを取得できる。
- current page updateは`id`, `status`, `title`, `body`, 次の`version.number`を要求する。
- Atlassianはcurrent page更新時、remote draftとのcontent reconciliationを試み、差が大きい場合は
  提供contentがdraftを上書きし得ると明記している。
- REST API v2のspace listは`keys` queryを受けるため、human-readable `space_key`からnumeric
  `spaceId`を解決できる。
- 個人scriptのbasic authenticationはAtlassian account emailとAPI tokenを使う。password authではない。
  Atlassianは一般配布appにはOAuth 2.0/Forge等を推奨している。

公式資料:

- [Confluence Cloud REST API v2 — Page](https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-page/)
- [Confluence Cloud REST API v2 — Space](https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-space/)
- [Basic auth for REST APIs](https://developer.atlassian.com/cloud/confluence/basic-auth-for-rest-apis/)

## Inferences

- single-user private toolの初期profileではemail + API tokenをenvironmentから読む実装が最小である。
  将来配布app化する場合は同じclient interfaceへOAuth credential providerを追加する。
- remote draft reconciliationがあるため、HTTPのversion checkだけに依存せず、同期済みhashとの比較を
  application側で行う必要がある。
- `space_key`は人が編集するmappingに適するが、page create requestには`spaceId`が必要なので、push時に
  space endpointで解決し、一意でない／存在しない場合はwrite前に拒否する。
- Confluence bodyをMarkdownの正本にしない。pullは明示操作であり、変換lossとconflictをpreviewする。

## Hypotheses

- Knowledge noteとmanaged project reportを主なpublish対象にすれば、初期利用の大半を覆える。
- headings、paragraphs、lists、code blocks、tables、links、emphasisを往復できれば、個人文書の初期用途には
  十分である。
- remote macroや複雑なeditor nodeをraw HTMLとして保全し、loss warningを返せば、黙って削除するより安全である。

## UNKNOWN

- Confluence editorが生成するすべてのstorage XMLをlosslessにMarkdownへ戻す一般解はない。
- tenant固有app、macro、extension node、legacy contentの変換範囲はfake contract testだけでは保証できない。
- Atlassianのrate limit値はtenant/endpoint/時期により変わり得るため、固定回数を仕様にしない。
- Marketplace配布またはmulti-user化した場合の認証・token storage policyは初期single-user profileの範囲外。

## Compared implementation paths

### REST v1 content API

既存例が多くstorage-format操作も可能だが、新規実装でpage identity/version contractをv1へ固定する理由が
弱い。

### REST v2 page/space API

pageとspaceのtyped contractが明示され、current Cloud APIとしてdocumentedである。初期実装に採用する。

### Atlas Doc Formatを正本にする

modern editor表現に近い一方、Work Smarterのtext-first Markdown正本と乖離し、手編集が難しい。

### Storage representationを境界形式にする

XML/HTML-like textとして変換・testしやすい。対応subsetとloss warningを明示して採用する。

### Sync stateをfrontmatterへ全保存する

reviewしやすいが、hash/version/snapshotが文書差分を汚し、remote編集のたびにauthoritative documentを
変更する。

### Mappingだけfrontmatter、同期状態はsidecar

user intentとremote identityは文書先頭、機械的stateは`.work-smarter`に分離できる。採用する。

## Frontmatter contract

Provider-neutral envelopeの例:

```yaml
publications:
- provider: confluence
  target:
    space_key: ENG
    page_id: '123456'
    parent_id: '120000'
    title: Release decision
```

`page_id`はcreate前だけ省略可能。`space_key`は必須、`parent_id`とtitle overrideはoptionalである。
unknown provider target fieldはprovider adapterが拒否する。

次はfrontmatterへ保存しない。

- email、API token、Authorization header
- numeric `spaceId` cache
- last local/remote hash
- last remote version
- remote base body

## Conflict state machine

| Local vs last sync | Remote vs last sync | Push | Pull |
|---|---|---|---|
| unchanged | unchanged | no-op | no-op |
| changed | unchanged | update remote | local-ahead。通常はno-op |
| unchanged | changed | remote-ahead。停止 | update local |
| changed | changed | conflict。停止 | conflict。停止 |

初回で`page_id`がないpushはcreate。`page_id`があるがsidecarがない場合はuntracked remoteとして停止し、
explicit adopt/pullを要求する。`--force`は対象方向の内容破棄を明示するが、dry-runとは同時指定できない。

HTTP 409、412、429、5xx、timeoutでは同期stateを進めない。write responseを検証してからfrontmatterの
new `page_id`とsidecarを更新する。local frontmatter更新とsidecar更新の間のcrash recoveryはevent/state
reconciliationで検出し、次回doctorが修復候補を出す。

## Verification plan

- fake transportでspace resolution、create payload、read body-format、update next versionを固定する。
- credential missing、unsafe base URL、401/403/404/409/429、malformed JSONをdomain errorへ変換する。
- conversionはUnicode、HTML escaping、code fence、table、link、unsupported element warningをtestする。
- dry-run前後でremote calls、workspace bytes、sidecar bytes、event countを比較する。
- all conflict matrix cells、force、idempotent no-op、create後page-id writebackをtestする。
- exception/message/JSON outputにtoken文字列が含まれないことをtestする。

## Conclusion

Confluence integrationはfile copyではなく、明示的なpublication mapping、限定変換、version/hashによる
同期protocolとして実装する。Markdown正本とlocal-firstを維持し、Cloud APIやeditor固有部分はinjectable
adapterへ閉じ込める。
