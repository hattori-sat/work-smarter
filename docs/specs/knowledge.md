# Knowledge feature specification

- Status: Implemented on `feat/knowledge`
- Date: 2026-07-23
- Scope: single-user, local-first Knowledge M3

## Outcome

GTDの実行状態と混ぜずに、再利用可能な情報をstrictなMarkdown entityとして保存し、type、tag、alias、
source、stable-ID link、backlink、検索から再発見できるようにする。

## Success criteria

1. Knowledgeが独自のmodel、repository codec、service、template、CLI、HTTP contractを持つ。
2. 1 noteを1 Markdownとして保存し、VS Codeで安全に直接編集できる。
3. note、decision、how-to、reference、meeting-noteを用途別templateから作れる。
4. tagとaliasを正規化し、title/tag/body/aliasを検索できる。
5. workspace entityへのoutbound linkを検証し、backlinkを導出できる。
6. generic workspace recordをprivate feature modelへの依存なしでKnowledgeへpromoteできる。
7. hand editで生じるorphan、broken、duplicate、ambiguous linkをdoctorで発見できる。
8. write invariantはworkspace lock内でserviceが適用し、成功eventをappend-only logへ残す。

## Facts

- Knowledge noteの正本は`knowledge/notes/<id>.md`である。
- frontmatter schemaは`KnowledgeNote` schema version 1で、unknown fieldを拒否する。
- 本文は任意のUTF-8 Markdownである。
- Knowledge packageをimportしてもGTD packageをimportしない。
- cross-feature relationはstable IDとgeneric `EntityRecord` public attributesだけを使う。
- fresh workspaceは`gtd`と`knowledge`を有効にする。既存configのfeature listは暗黙変更しない。
- current searchは永続indexを持たず、note集合をcase-insensitive substring scanする。

## Inferences

- KnowledgeをGTD referenceと別entityにすることで、「実行を要求しない情報」と「GTD clarifyの履歴」を
  独立して発展させられる。
- directory taxonomyを深くするより、flatなstable pathと複数tag/linkを使う方が、分類変更でfile moveを
  発生させずに済む。
- backlinkを保存せずoutbound linkから導出すれば、direct edit後にinverse edgeが古くなる問題を避けられる。

## Hypotheses and unknowns

- Hypothesis: 個人規模では逐次substring searchで十分な応答時間を保てる。
- Hypothesis: 5種類のnote typeで、初期dogfoodingの大半を無理なく分類できる。
- UNKNOWN: note数が何件になった時点で検索indexが必要になるか。
- UNKNOWN: semantic searchとautomatic link suggestionが、誤関連の確認costを上回る価値を持つか。
- UNKNOWN: Markdown writeとevent appendの間でprocessが停止した場合の一般的なrecovery/outbox方式。

## Considered implementation paths

### Path A: GTD referenceを拡張する

既存のclarify decisionを再利用できる一方、Knowledgeのlink graph、source、revisionをGTD schemaとlifecycleへ
混ぜることになる。

### Path B: independent Knowledge entity

独自schemaとserviceを持ち、必要な時だけstable IDでGTDなどを参照する。codecとAPIは増えるが、GTD state
machineを変えずにKnowledgeを拡張できる。

Decision: Path B。`knowledge/gtd/`のGTD referenceと`knowledge/notes/`のKnowledge noteを別ownerとする。

### Backlink alternatives

- persisted inverse edge: readは速いが、direct editと2-file updateで不整合になりやすい。
- derived backlink: read時にscanが必要だが、outbound linkだけが正本になる。

Decision: derived backlink。performanceが問題になった場合も、再構築可能なindexとして追加する。

## Entity contract

```yaml
schema_version: 1
id: KN-8A2F1C77B410
kind: knowledge_note
note_type: decision
title: Canary release decision
tags:
- release
aliases:
- ship-plan
links:
- target_id: TASK-20260723-102030-A1B2C3
  relation: supports
  label: Execution evidence
sources:
- kind: url
  locator: https://example.com/runbook
  title: Release runbook
created_at: '2026-07-23T01:20:30Z'
updated_at: '2026-07-23T01:25:00Z'
revision: 2
```

| Field | Contract |
|---|---|
| `schema_version` | current valueは`1` |
| `id` | workspace-global stable ID。既定は`KN-` + 12桁hex |
| `kind` | literal `knowledge_note` |
| `note_type` | `note`, `decision`, `how_to`, `reference`, `meeting_note` |
| `title` | trim後nonblank |
| `tags` | trim、lowercase、重複除去、sort |
| `aliases` | trim、case-insensitive重複除去。Knowledge note間で一意 |
| `links` | stable target ID、relation、optional label |
| `sources` | provider-neutral kind、locator、optional title |
| timestamps | timezone-aware、`updated_at >= created_at` |
| `revision` | create時1、updateごとに1増加 |

Link relationは`related_to | supports | contradicts | supersedes | derived_from`。Source kindは
`entity | url | file | citation | other`である。

## Invariants

- stable IDは全workspace entityに対してcase-insensitiveに一意でなければならない。
- aliasはKnowledge note間でcase-insensitiveに一意でなければならない。
- link targetはwrite時に存在し、workspace内で一意でなければならない。
- self linkと、同じ`(relation, target_id)`のduplicate linkを拒否する。
- explicit update fieldだけを置換する。collectionに空listを渡すとclearする。
- bodyは末尾改行を正規化する。body未指定createだけがtype templateを使う。
- create、update、promoteのinvariant checkとMarkdown writeはworkspace lock内で行う。

## Search contract

Search fieldは`title | tag | body | alias`。queryと対象文字列をcasefoldし、substring matchしたnoteを
workspace orderで返す。hitには`matched_fields`、note、body、relative pathを含める。

現在はranking、tokenization、stemming、regex、fuzzy match、semantic searchを行わない。tag filterを複数
指定したlistは、指定tagをすべて持つnoteだけを返す。

## Link, backlink, and doctor contract

Knowledgeが保存するのはoutbound `links[]`だけである。backlink queryは全Knowledge noteをscanし、指定
entity IDを指すlinkごとにsource documentとlinkを返す。

Doctor codeとseverityは次の通り。

| Code | Severity | Meaning |
|---|---|---|
| `orphan` | warning | valid link/backlinkもsourceもない |
| `duplicate_link` | warning | 同じrelation/targetがdirect editで重複した |
| `broken_link` | error | target IDが存在しない |
| `ambiguous_link` | error | target IDがworkspace内で重複している |

sourceを1件以上持つnoteはorphanとしない。`valid`はerrorが0件であることを意味し、warningは許容する。

## Promotion contract

Source recordはpublic attributeとしてnonblankな`id`、`kind`、`title`とMarkdown bodyを持つ。Knowledgeは
source featureのprivate modelをimportしない。

Promotionはsource bodyをcopyし、`kind=entity`、`locator=<source-id>`のSourceReferenceを先頭へ追加する。
同一source IDを参照するpromotionが1件ならidempotently同じdocumentを返し、2件以上ならmanual edit conflict
として拒否する。promotionはsnapshot copyであり、sourceとの継続同期ではない。

## Events

| Event | Meaning |
|---|---|
| `knowledge.note.created` | 新規noteを書いた |
| `knowledge.note.updated` | field/bodyを置換しrevisionを進めた |
| `knowledge.note.promoted` | generic workspace recordからnoteを作った |

Eventは`.work-smarter/events.ndjson`へ追記する。現在snapshotはMarkdown、履歴はeventがauthorityである。

## Public adapters

CLIは`ws knowledge`配下に`add`, `show`, `list`, `search`, `update`, `link`, `backlinks`, `promote`,
`doctor`を持つ。full IDとunique prefixを受け付け、Knowledge queryはexact unique aliasも受け付ける。
root `--json` modeはpromptやhuman textをstdoutへ混ぜない。

HTTPは次のtyped routeを持つ。

| Intent | Route |
|---|---|
| create / list | `POST /api/knowledge/notes`, `GET /api/knowledge/notes` |
| get / replace fields | `GET /api/knowledge/notes/{id}`, `PATCH /api/knowledge/notes/{id}` |
| search | `GET /api/knowledge/search?q=...&field=...` |
| backlinks | `GET /api/knowledge/backlinks/{target_id}` |
| promote | `POST /api/knowledge/records/{record_id}/promote` |
| doctor | `GET /api/knowledge/doctor` |

Request modelはunknown fieldを拒否し、OpenAPI responseは`KnowledgeDocument`などのpublic Pydantic modelで型付け
する。missing entityは404、Knowledge domain conflict/link errorは400へmappingする。

## Non-goals for M3

- Confluenceや他providerへのpush/pull、credential、remote revision mapping
- binary attachment ownershipとcontent extraction
- full-text/semantic index、ranking、graph visualization
- multi-user permission、remote collaboration、merge conflict resolution
- automatic taxonomy、automatic link suggestion

