# ADR 0002: Feature composition and ownership

- Status: Accepted
- Date: 2026-07-23

## Outcome

GTD、project management、User Story Mapping、publishingを、同じworkspaceに配置できるが
互いのstate machineへ依存しないfeatureとして合成する。

## Facts

- GTD、Knowledge、Managed Project、publishingは実装済みであり、別々のstate machineを維持する。
- Markdownと監査eventは長期保存するため、directory・kind・IDの衝突は後から直しにくい。
- CLI、HTTP API、将来のVS Code UIは同じPython application serviceを使う。

## Considered paths

### Storageが全entity modelをclosed unionとして知る

最初は単純だが、新featureを追加するたびに共有storageを変更する。feature間の独立性を満たさない。

### Featureがcodecと所有directoryをcomposition rootへ登録する

初期構成は少し増えるが、generic storageはMarkdown/YAML/JSONL/lockingだけを担当できる。
新featureはhostとの公開contractを通じて追加できる。

## Decision

後者を採用する。

- `work_smarter.storage` はGTDをimportしない。
- 各featureは `EntitySpec(kind, model, directory)` と初期化hookを登録する。
- `work_smarter.composition` だけがenabled featureを選び、codec registryを組み立てる。
- entity kindとdirectoryはfeatureが所有する。GTDは `gtd_project` と `gtd/projects/` を使う。
- workspace内IDはfeatureをまたいで一意にする。kind名とevent typeはnamespaceを含める。
- relationは相手aggregateのstable IDだけを保持し、private Python objectを共有しない。
- unknown/disabled featureの文書を既知modelとして推測して読まない。

Python package entry point `work_smarter.features` はfeature discoveryに使う。ただし0.1では
built-in featureが主対象であり、第三者plugin compatibilityはまだ保証しない。

## Events

`.work-smarter/events.ndjson` はlegacy domainではappend-onlyのローカル監査履歴である。event typeは
`gtd.task.started` のようにnamespace化し、envelopeに `schema_version` を持たせる。

Target ArchitectureではDatabase activity eventとtransactional outboxへdomain単位で移行する。
正本の切替規則は[ADR 0003](0003-hybrid-source-of-truth-and-local-application-server.md)に従う。

これはまだ信頼できるfeature間message busではない。将来subscriberを動かす場合は、Markdown更新と
event発行の間でcrashしても欠落しないtransactional outbox、再送、idempotencyを別ADRで決める。

## Publishing boundary

Confluence adapterはGTD aggregateを直接同期せず、将来のpublishable document contractを読む。
page ID、space ID、version、content hashなどprovider固有stateは `.work-smarter/providers/confluence/`
配下のsidecarへ置き、一般文書のfrontmatterをprovider都合で汚染しない。

## Consequences

- 新featureはstorageを編集せず独自codec/directoryを追加できる。
- hostのCLI/API surfaceを動的に合成するcontractは今後実装が必要である。
- event logをintegration busだと誤認してはならない。
- external plugin compatibility、Windows locking、crashをまたぐ複数file transactionはUNKNOWNである。
