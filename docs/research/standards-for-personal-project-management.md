# NASA/JAXAの公開文書を個人プロジェクト管理へ適用するための調査

- 調査日: 2026-07-23
- Status: Research recommendation
- 対象: `project_management` feature
- 適合性: NASA/JAXAへの規格適合を主張しない

## Outcome

Work Smarterのmanaged projectには、NASA/JAXAの組織・承認構造を再現するのではなく、
成果物中心の分解、根拠に基づくgate、QCD、V&V、risk/issue/decision、baseline/changeを残す
`NASA/JAXA-inspired personal engineering profile`を採用する。

これは個人が日常的に使える軽さを保ちながら、次の連鎖を追跡可能にするためのprofileである。

`goal → decomposition → plan → evidence → decision → controlled change → result`

GTD projectは「複数actionを要するoutcome」、managed projectはWBS、schedule、QCD、review、
configurationを持つ別featureとする。両者はstable IDによる公開relationだけで結び、互いのprivate
modelやstate machineを共有しない。

## Success criteria

- 規程、handbook、current web evidence、推論、仮説、UNKNOWNを区別できる。
- 厳格なagency-shaped modelと個人向けlightweight profileを比較し、選択理由を説明できる。
- WBS、schedule、QCD、gate、V&V、register、baseline/changeをMarkdown/YAMLへ写像できる。
- 各invariantをuser-observableなtestまたは`doctor`検査へ写像できる。
- GTD、knowledge、publishing、User Story Mapping、TBPと独立したfeature境界を維持できる。
- NASA/JAXAへの適合、認証、正式なtailoring承認を示唆しない。

## Hypotheses

以下は出典が保証する事実ではなく、Work Smarterで検証すべきproduct hypothesesである。

| ID | Hypothesis | 検証方法 |
|---|---|---|
| H1 | capture時の必須項目を少なくし、commit/gate時にrigorを要求すると継続利用しやすい | 4週間の実利用でcapture時間、未整理率、離脱率を測る |
| H2 | 個人でもevidence付きgateとdecision recordにより、惰性の継続と前提忘れを減らせる | gate後の手戻り理由と「判断根拠不明」の件数を振り返る |
| H3 | product-oriented WBSとactionを分離すると、成果物と日々の作業を混同しにくい | orphan action、完了actionを持つ未完成成果物、WBS変更回数を観察する |
| H4 | baseline/current/forecastを分離したQCDは、単一の進捗率より自己予測の改善に役立つ | effort誤差、納期予測誤差、criteria充足率をreviewごとに比較する |
| H5 | dependency入力が不完全な場合、critical path表示は精密に見える誤情報になる | dependency coverageを表示し、coverageと予測誤差の関係を調べる |

## Verification plan

### Research verification

- requirementの根拠にはNASA NODIS、NASA NTRS、NASA公式サイト、JAXA安全・信頼性推進部の
  公開文書だけを使う。
- 文書番号、発効日、失効予定日、改訂日が確認できる場合は併記する。
- directiveとhandbookを同じ強さで扱わない。
- 2026-07-23時点でpublic page同士の整合を確認できないものは`UNKNOWN`とする。

### Product verification

- state transitionごとにallowed、refused、audit event、persistence reloadをtestする。
- direct-editable schemaごとにmalformed、unknown field、migration、`doctor`をtestする。
- DAG、baseline、gate、V&V、registerのinvariantをdomain/application serviceでtestし、CLI/HTTPは
  同じserviceのadapterとしてcontract testする。
- Gantt、critical path、QCD表はauthoritative stateではなく再生成可能なprojectionとしてtestする。

## Execution

### Evidence labels

- **FACT**: 引用した公式公開文書または公式web pageから確認できた内容。
- **INFERENCE**: 複数のFACTをWork Smarterの設計へ適用した判断。
- **HYPOTHESIS**: 実利用でまだ検証されていないproduct仮説。
- **UNKNOWN**: 公開情報だけでは、現行性、意味、または実装上の最適解を確定できない事項。

### Facts — NASA

1. **FACT — lifecycleとdecision gate**

   NPR 7120.5Fはspace flight program/projectのlife cycle、Key Decision Point、control plan、
   baseline、rebaseline、decision memorandumを定義する。reviewは資料を作ること自体ではなく、
   次段階への判断に必要な状態と根拠を評価する仕組みとして扱われる。

2. **FACT — systems engineeringはtailoring可能なprocess set**

   NPR 7123.1Dは17のsystems engineering processを定義し、technical planning、requirements、
   interface、risk、configuration、technical assessment、decision analysis、V&V等を扱う。
   適用対象やrigorはprojectに応じたtailoringを前提とする。

3. **FACT — verificationとvalidationは別の問い**

   NPR 7123.1Dでは、verificationはspecified requirementへの適合を確認し、validationは
   intended useとintended environmentにおいて意図した目的を満たすかを確認する活動として区別される。
   requirement、verification method、result、evidenceのtraceを保持する必要がある。

4. **FACT — small projectは管理意味論を残してscale downできる**

   NASA Project Planning and Control Handbook Appendix Cは、small projectでdocumentation量、
   reviewの回数とformality、WBSの深さ、tool、EVM適用等をscaleする考え方を示す。
   したがって「小さいから管理をなくす」だけが選択肢ではない。

5. **FACT — WBSは成果物中心**

   NASA Work Breakdown Structure HandbookはWBSをproduct-orientedな階層分解として扱う。
   phase、組織、単なる作業一覧を主軸にしたWBSは推奨されない。WBS dictionaryとstableなcodeにより、
   technical、cost、schedule、riskを同じ成果物へ関連付ける。

6. **FACT — scheduleはlogic networkとbaselineを持つ**

   NASA Schedule Management Overviewはschedule managementを複数の継続機能として説明し、
   baseline integrated master schedule、依存logic、critical path methodを扱う。
   同pageは2026-04-28更新であり、この調査では**current web evidence**として使う。
   これはSchedule Management Handbookの正確な文書番号・revisionを確定する根拠ではない。

7. **FACT — riskとissueを区別する**

   NPR 8000.4Cはriskを、現在のconditionから将来のdepartureとconsequenceへつながる不確実性として
   表現し、likelihood、consequence、owner、response、trigger、reviewを管理する。処置には
   `accept / mitigate / watch / research / escalate / close`が含まれる。undesired consequenceが既に
   発生した、または対処しなければほぼ確実なものはissueとして扱う。

8. **FACT — decisionは選択肢と根拠を残す**

   NPR 8000.4Cはrisk-informed decision makingでalternatives、criteria、risk information、
   trade、rationaleを評価し、decision basisを記録する考え方を示す。

9. **FACT — NASAの上位管理軸はliteralなQCDではない**

   NASAのproject management文書は主にtechnical performance、cost、schedule、riskを統合管理する。
   Work Smarterの`quality / cost / delivery`という名前はNASA用語の複製ではない。

### Facts — JAXA

1. **FACT — public document category**

   JAXA安全・信頼性推進部の公開indexでは、JMRはprogram management要求文書、JERGは
   technical requirement/guidelineとして分類される。個別文書の適用範囲と強さは文書ごとに確認する
   必要があり、JERG全体への適合という単一の主張はできない。

2. **FACT — purpose、success、constraint、assumptionを明示する**

   JERG-2-100「システム設計標準」は目的・成功基準、制約、前提、risk、resource/margin、
   cost、schedule、team等を明らかにし、life-cycle outputとreviewへつなげる考え方を示す。
   不確かな前提はriskになり得るが、assumption/constraintそのものも識別、管理、共有する。

3. **FACT — V&V traceを残す**

   JERG-2-100はrequirement/specificationとverification内容・結果をtraceできること、
   intended operationを含めたvalidationを考慮することを示す。

4. **FACT — configurationとbaselineを制御する**

   JMR-006A「コンフィギュレーション管理標準」はconfiguration itemの識別、baseline、変更の
   review/approval/reflection、status accounting、記録、auditを扱う。technical change、deviation、
   waiverを区別し、変更がperformance、cost、schedule/delivery、safety、reliability、interface等へ
   与える影響を評価する。

5. **FACT — tailoringとQCDへの影響**

   JERG-0-053「コンフィギュレーション管理ハンドブック」はproject特性に応じたtailoringを説明し、
   管理されない変更がquality、cost、deliveryへ悪影響を与え得ることを示す。

### Inferences for Work Smarter

1. **INFERENCE — 適用単位**

   NASA/JAXAの組織、役職、承認boardを再現せず、意味論とtraceだけを採る。profile名は
   `NASA/JAXA-inspired personal engineering profile`とし、`compliant`、`certified`、
   `JERG準拠`等の表示をしない。

2. **INFERENCE — rigorを遅延させる**

   `capture/explore`ではtitle、goal程度で作成可能にし、baselineを置く`commit` gateで
   completion criteria、WBS、QCD、risk、V&V approachをvalidatorにより要求する。

3. **INFERENCE — Git historyだけでは変更判断を表せない**

   Gitはfile差分を残せるが、変更理由、検討案、QCD/risk impact、承認判断をdomain eventとして
   保証しない。baseline後の変更には明示的なchange requestとappend-only audit eventが必要である。

4. **INFERENCE — QCDはproduct projectionとして定義する**

   NASAのtechnical/cost/schedule/riskとJAXA文書のquality/cost/deliveryへの影響を、個人向けに
   `quality / cost / delivery`へ写像する。QCDは一つの曖昧なhealth scoreではなく、測定日と根拠を持つ
   三つのviewとして扱う。

5. **INFERENCE — opportunity disposition**

   NASA Risk Management Handbookはopportunityの概念を扱うが、Work Smarterでの
   `exploit / enhance / share / accept / close`はproduct-defined vocabularyとする。
   NPR 8000.4Cのnormativeなrisk dispositionをそのままopportunityへ転用したものとは主張しない。

6. **INFERENCE — projectionとsource of truthを分離する**

   Markdown/YAMLとappend-only audit eventをauthoritativeとし、Gantt、critical path、QCD table、
   Confluence/HTML viewは再生成可能なprojectionとする。

### Unknowns

- **UNKNOWN — NPR 7120.5FとNID 7120.148の現行関係**:
  NPR 7120.5Fのmain pageはNID 7120.148に注意するよう示す一方、公開NID PDFには
  2025-12-09のexpirationが記載され、NPR 7120.5Fのpageには2027-02-03のexpirationが記載される。
  2026-07-23時点のpublic pagesだけでは正確なauthorityを確定できない。この調査はNIDを現行requirement
  として実装根拠にしない。
- **UNKNOWN — Schedule Management Handbookの正確な現行revision**:
  NASA公式guidance pageにはdownloadがあるが、解析可能な公開情報だけではreport number/revisionを
  確定できなかった。2026-04-28更新のSchedule Management Overviewだけをcurrent web evidenceとする。
- **UNKNOWN — JAXA内部文書の現行性**:
  `BDB-06007B システムズエンジニアリングの基本的な考え方`、project management実施要領、
  `JMR-011 Risk Management Handbook`は他の公開文書から存在を参照できるが、現在のpublic indexで
  現行revision/fileを確認できない。実装の直接根拠にしない。
- **UNKNOWN — JMR-005A noticeの正確な適用状態**:
  現在配布されるfileにはnoticeが含まれるが、この調査ではnoticeを含む現行適用状態を確定していない。
- **UNKNOWN — 個人向けgateの最適数**:
  5段階は初期profileであり、実利用データなしに唯一の正解とはしない。
- **UNKNOWN — EVMの価値**:
  一人のprojectでformal EVMを必須にする費用対効果は未検証であり、初期profileには含めない。

### Compared implementation paths

| 観点 | Path A: agency-shaped strict model | Path B: lightweight traceable profile |
|---|---|---|
| Lifecycle | NASAのphase/KDP/review acronymに近い固定構造 | genericでconfigurableな5段階とevidence gate |
| Process | 17 SE process、個別plan、formal boardを広くmodel化 | WBS、schedule、QCD、V&V、register、changeの核だけをmodel化 |
| Authority | 複数組織、独立review team、formal approvalを前提 | decision authorityはdefault `self`、必要時に外部reviewerをlink |
| Data entry | 高い。空欄または形式的入力になりやすい | captureは軽く、commit/change/closeで必要なrigorを要求 |
| Traceability | 高い | 意味論とstable IDを保つ範囲で高い |
| Personal use | 過剰になりやすい | 主要use caseに合う |
| Future enterprise use | agency-specificな構造が別組織で足かせになり得る | public contractsとprofile追加で拡張可能 |
| Misrepresentation risk | 見た目だけの「NASA/JAXA準拠」を招きやすい | inspired profileと明記しやすい |
| Decision | 採用しない。将来のoptional profile候補 | **defaultとして採用** |

Path Bを選ぶ。small-project tailoringの考え方に沿ってdocumentation/formalityを減らす一方、
stable identity、evidence、baseline、decision、change historyという管理意味論は残す。

### Chosen lightweight profile

#### Feature boundary

- `managed_project`は独立aggregateとする。
- GTD task/action、knowledge、published documentとのrelationはstable IDとrelation typeだけを持つ。
- `managed_project`からGTD private modelをimportしない。
- provider credentialとConfluence固有sync stateをproject frontmatterへ置かない。

#### Lifecycle and gates

default lifecycleは次の5段階とする。名称はprofile設定で変更可能にし、NASAのphase/KDP名とは同一視しない。

1. `explore`: purpose、users/stakeholders、success criteria、options、rough QCD、主要assumption/riskを明らかにする。
2. `commit`: scope、requirement、WBS、schedule、QCD baseline、V&V approachを置く。
3. `deliver`: 成果物を作り、verification、variance、risk、changeを管理する。
4. `operate`: intended useでvalidationし、residual issueと運用責任を確認する。
5. `close`: outcome、未完obligation、lesson、archive状態を記録する。

各gateは次を持つ。

- stable ID、name、target/actual date
- entrance criteriaとsuccess criteria
- evidence IDs
- open exceptionsとwaiver/changeへのlink
- decision: `go / hold / rework / stop`
- rationale、decided-at、decision authority
- gateで確定したimmutable baseline revision

#### Project records

最小のpublic recordsを次とする。nested recordにもstable IDを与え、後から別entityへ分離してもrelationを
壊さない。

- `managed_project`
- `phase`
- `wbs_element`
- `work_package`
- `schedule_activity`
- `milestone`
- `gate_review`
- `qcd_snapshot`
- `requirement`
- `verification_record`
- `risk`、`opportunity`、`issue`、`decision`
- `assumption`、`constraint`
- `change_request`
- `evidence_record`

#### WBS and work packages

- WBSはproduct/service/deliverableを分解し、activity listにしない。
- work packageはdeliverable、owner、acceptance/completion criteria、estimateを持つ。
- schedule activityはWBS/work packageをstable IDで参照する。
- WBS codeは表示用のhierarchical code、stable IDはidentityとして分離する。親変更でIDを変えない。
- DAG cycle、duplicate ID、orphan reference、self dependencyを拒否する。

#### Schedule and Gantt

- activityはduration/estimate、dependency、constraint、baseline/current/actual dateを持つ。
- dependency typeは`FS / SS / FF / SF`とlagへ拡張可能にし、初期UIは`FS`を中心にする。
- logic networkからearliest/latest、float、critical path、delayを再計算する。
- baseline、actual、current forecastを上書きで混ぜない。
- Ganttはderived projectionであり、Mermaid、terminal table、HTML/Confluence tableを同じschedule stateから作る。
- dependency coverageが低い場合、critical pathの不確実性を表示する。

#### QCD

各snapshotは`as_of`、`basis`、`baseline/current/forecast`を持つ。

- `quality`: completion/acceptance criteria、verification result、defect/issue、technical measure、margin
- `cost`: currency costとpersonal effortを別系列で記録し、estimate/actual/forecastを比較
- `delivery`: target/baseline/forecast date、milestone、critical path、schedule variance

単一の「90%完了」のような値だけをsource of truthにしない。health色はmetricから導出し、
metric不足時は`unknown`とする。

#### Risk, opportunity, issue, and decision

`risk`はcondition、possible departure、affected objective/asset、consequenceを分離して記録し、
likelihood、consequence/severity、owner、response、trigger、next review、statusを持つ。

`issue`は既に発生したundesired stateとして、impact、containment、corrective action、owner、target、
evidence、related riskを持つ。riskをissueへ遷移させても元riskとhistoryを削除しない。

`opportunity`はbeneficial consequenceの不確実性として管理するが、disposition vocabularyは
Work Smarter独自であることをschema/helpに明記する。

`decision`は次を持つ。

- question
- alternatives
- criteria
- evidence IDs
- selected alternative
- rationale
- assumptions/constraints
- QCD/risk impact
- revisit trigger
- supersedes decision ID

#### Assumptions and constraints

- assumptionはstatement、validation criterion、owner、next review/evidence、statusを持つ。
- invalidated assumptionは自動削除せず、risk/issue/changeへのrelationを求める。
- constraintはstatement、type/source、hard/soft、owner、active stateを持つ。
- assumptionをrisk欄だけへ埋めず、独立してquery/reviewできるようにする。

#### Requirements and V&V

- requirementはstable ID、statement、source、rationale、acceptance criteria、parent/derived relationを持つ。
- verification recordはmethod、procedure/reference、expected result、evidence、result、reviewer、dateを持つ。
- method vocabularyは`test / analysis / inspection / demonstration / review`を初期値とする。
- validation recordはintended use、environment、stakeholder/user、observed outcomeを追加する。
- `verified`と`validated`を同じbooleanへ統合しない。

#### Baseline and change control

gateでacceptedになったscope、WBS、schedule、QCD、requirement、configurationをbaseline revisionとして
snapshot化する。baseline後のdirect mutationは拒否し、次のchange recordを通す。

- kind: `technical_change / deviation / waiver / correction`
- reason、affected stable IDs、before/after
- requirement/interface/QCD/risk/V&V impact
- alternatives、rationale、authority、effective time
- append-only audit eventとresulting baseline revision

`deviation`は実施前に既知のbaseline逸脱を認める判断、`waiver`は判明したnonconformanceを受け入れる
判断として区別する。すべてのMarkdown documentをconfiguration itemにするのではなく、gateで登録した
control対象だけをbaselineへ含める。

### Implementation and verification mapping

以下は規格適合表ではなく、公開文書から抽出したdesign conceptをproduct contractへ写像した実装計画である。

| Source concept | Work Smarter construct | Public invariant / behavior | Verification |
|---|---|---|---|
| product-oriented WBS | `wbs_element`, `work_package` | parent graphはacyclic、IDは一意、deliverable/criteriaを保持 | cycle、duplicate、orphan、reload test |
| WBSと作業の分離 | `schedule_activity.wbs_id` | activityは成果物を参照するがWBS nodeそのものではない | create/query/API contract test |
| schedule logic | typed dependency DAG | self/cycleを拒否し、lagを含む順序を再計算 | refused transition、CPM fixture test |
| schedule baseline | baseline/current/actual fields | baselineをforecastで上書きしない | serialization、variance、reload test |
| decision gate | `gate_review` | criteria/evidence/exceptionなしの`go`をvalidatorが拒否 | allowed/refused/audit/reload test |
| decision basis | `decision` | alternatives、criteria、selected、rationaleを保持 | malformed/unknown-field test |
| technical/cost/schedule integration | `qcd_snapshot` | as-ofとbasis必須、baseline/current/forecastを分離 | derived health/variance test |
| requirement trace | requirement relation graph | parent/source/evidence IDをtrace可能 | orphan、cycle、trace report test |
| verification | `verification_record` | passにはexpected resultとevidenceが必要 | pass-without-evidence refusal test |
| validation | distinct validation record/type | verification済みでもvalidation済みとはみなさない | separate-state acceptance test |
| risk process | `risk` register item | condition/departure/consequence、owner、reviewを保持 | stale review、invalid disposition doctor test |
| realized uncertainty | `issue` register item | issueはriskと別kind、relation/historyを保持 | promotion/link/audit/reload test |
| opportunity | `opportunity` register item | product-defined dispositionをriskと混同しない | enum/API schema test |
| assumption management | `assumption` | validation evidence/statusを保持し、invalidatedを削除しない | invalidation/audit/doctor test |
| constraint management | `constraint` | active/inactive履歴とsource/typeを保持 | transition/reload test |
| configuration baseline | baseline revision | accepted revisionはimmutable | direct mutation refusal test |
| controlled change | `change_request` | impact/rationale/authorityなしのacceptを拒否 | allowed/refused/audit/reload test |
| persistent evidence | `evidence_record` | stable IDとrecorded-atを持ちcriteriaから参照可能 | orphan/duplicate/timestamp test |
| personal authority | `decision_authority=self` default | single-userでも誰の判断かを省略しない | default/override serialization test |
| cross-feature integration | public relation contract | stable IDのみを保持しprivate modelをimportしない | architecture/import boundary test |
| text source of truth | Markdown/YAML + NDJSON events | projectionを削除しても再生成可能 | rebuild equivalence test |
| direct edit safety | strict schema + migration | malformed/unknown fieldsを黙って捨てない | codec and `doctor` test |

### `doctor` checks

最低限、次をuser-facingなrepair hintと共に報告する。

- malformed schema、unsupported schema version、unknown field
- duplicate stable ID、orphan/ambiguous relation
- WBS cycle、schedule dependency cycle、self dependency
- baseline drift、baseline後のunrecorded mutation
- criteriaを満たすevidence不足、verification method/result不足
- `verified`と`validated`の不整合
- risk review期限超過、owner不在、invalid disposition
- invalidated assumptionに対するrisk/issue/change未登録
- gateのopen criteria、open exception、decision basis不足
- QCD snapshotのmeasurement date/basis不足

### Official sources

#### NASA directives and official guidance

- [NPR 7120.5F — NASA Space Flight Program and Project Management Requirements w/Change 4](https://nodis3.gsfc.nasa.gov/displayDir.cfm?Internal_ID=N_PR_7120_005F_&page_name=main),
  effective 2021-08-03, page expiration 2027-02-03.
  [Chapter 2](https://nodis3.gsfc.nasa.gov/displayDir.cfm?Internal_ID=N_PR_7120_005F_&page_name=Chapter2)
- [NID 7120.148](https://nodis3.gsfc.nasa.gov/OPD_Docs/NID_7120_148_.pdf),
  public PDF expiration 2025-12-09。現行authorityは前述のとおりUNKNOWN。
- [NPR 7123.1D — NASA Systems Engineering Processes and Requirements Updated w/Change 2](https://nodis3.gsfc.nasa.gov/displayDir.cfm?Internal_ID=N_PR_7123_001D_&page_name=main),
  effective 2023-07-05, page expiration 2028-07-05.
  [Chapter 3](https://nodis3.gsfc.nasa.gov/displayDir.cfm?Internal_ID=N_PR_7123_001D_&page_name=Chapter3),
  [Appendix G](https://nodis3.gsfc.nasa.gov/displayDir.cfm?Internal_ID=N_PR_7123_001D_&page_name=AppendixG)
- [NPR 8000.4C — Agency Risk Management Procedural Requirements](https://nodis3.gsfc.nasa.gov/displayDir.cfm?Internal_ID=N_PR_8000_004C_&page_name=main),
  effective 2022-04-19, page expiration 2027-04-19.
  [Chapter 3](https://nodis3.gsfc.nasa.gov/displayDir.cfm?Internal_ID=N_PR_8000_004C_&page_name=Chapter3)
- [NASA/SP-2016-6105 Rev 2 — NASA Systems Engineering Handbook](https://ntrs.nasa.gov/citations/20170001761),
  published 2017-02-17。directiveではなくguidance。
- [NASA/SP-2016-3424 — Project Planning and Control Handbook](https://www.nasa.gov/wp-content/uploads/2024/09/ppc-handbook-1-5-17.pdf),
  December 2016。URLのupload pathは文書revisionを意味しない。
- [NASA/SP-20210023927 — Work Breakdown Structure Handbook](https://www.nasa.gov/wp-content/uploads/2023/08/nasa-work-breakdown-structure-handbook.pdf),
  November 2021.
- [NASA Schedule Management Overview](https://www.nasa.gov/ocfo/ppc-corner/schedule-management-overview/),
  page last updated 2026-04-28。この調査ではcurrent web evidenceとしてのみ使用。
- [NASA PP&C Guidance Documents](https://www.nasa.gov/ocfo/ppc-corner/ppc-guidance-documents/),
  page last updated 2026-05-18.
- [NASA/SP-20240014019 — Risk Management Handbook, Part 1](https://ntrs.nasa.gov/citations/20240014019),
  published 2024-11-01.
- [NASA/SP-20240014326 — Risk Management Handbook, Part 2](https://ntrs.nasa.gov/citations/20240014326),
  published 2024-11-01.
- [NASA Safety and Mission Assurance — Risk Management](https://sma.nasa.gov/sma-disciplines/risk-management),
  current official landing page。landing pageとNTRSでPart Iのdisplay numberに差があるため、本文では
  NTRS citation IDを優先した。

#### JAXA public technical documents

- [JAXA 安全・信頼性推進部 — 技術文書一覧](https://sma.jaxa.jp/techdoc.html)
- [JERG-2-100 — システム設計標準](https://sma.jaxa.jp/TechDoc/Docs/JAXA-JERG-2-100.pdf),
  enacted 2016-05-20.
- [JMR-006A — コンフィギュレーション管理標準](https://sma.jaxa.jp/TechDoc/Docs/JAXA-JMR-006A.pdf),
  revision A, 2026-03-30.
- [JERG-0-053 — コンフィギュレーション管理ハンドブック](https://sma.jaxa.jp/TechDoc/Docs/JAXA-JERG-0-053.pdf),
  2026-03-30.
- [JMR-004D — 信頼性プログラム標準](https://sma.jaxa.jp/TechDoc/Docs/JAXA-JMR-004D.pdf),
  revision D, 2024-12-23。補助資料。
- [JMR-005A — 品質保証プログラム標準（notice付き配布file）](https://sma.jaxa.jp/TechDoc/Docs/JAXA-JMR-005A_N4.pdf),
  revision A, 2008-06-10。noticeの現行適用状態はUNKNOWN。
- [JERG-2-500A — 制御系設計標準](https://sma.jaxa.jp/TechDoc/Docs/JAXA-JERG-2-500A.pdf),
  revision A, 2013-03-29。tailoringに関する補助資料であり、本profileの中核根拠ではない。

## Conclusion

個人向けの価値は、NASA/JAXAのformalityを模倣することではなく、成果物、根拠、判断、変更を
後から追えるようにすることにある。defaultはlightweight profileとし、captureを妨げない一方、
commit、change、closeではvalidatorによりrigorを要求する。

将来、より厳格なprofileを追加する場合も、同じstable IDs、public contracts、audit events、projectionを
利用し、NASA/JAXAの名称や適合性をUI上で安易に主張しない。現時点での規格適合性は**なし**、
NPR/NIDの正確な現行関係と一部JAXA内部文書の現行性は**UNKNOWN**である。
