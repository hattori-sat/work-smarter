# Jira work-item concepts applied to personal GTD

調査日: 2026-07-23

## Facts from Atlassian documentation

- Jira work itemはtitle、description、required/optional fieldsを持ち、workflowを通って完了へ進む。
  Child work itemで作業を分割できる。
  - https://support.atlassian.com/jira-software-cloud/docs/create-a-work-item-and-a-subtask/
- Workflowはstatus、transition、condition、validator、post-functionで状態変更を制御する。
  validator失敗時は遷移しない。
  - https://support.atlassian.com/jira-cloud-administration/docs/edit-an-issue-workflow/
- Work item linksは`blocks / is blocked by / relates to / duplicates`等で依存と関係を表す。
  - https://support.atlassian.com/jira-software-cloud/docs/link-issues/
- Original estimate、remaining、work logにより見積りと実績を比較できる。
  - https://support.atlassian.com/jira-software-cloud/docs/log-time-on-an-issue/
- Fieldを標準化するとreportしやすく、自由記述fieldは表記揺れを起こしやすい。
  - https://support.atlassian.com/jira-cloud-administration/docs/edit-or-delete-a-custom-field/

## Inferences for Work Smarter

### Adopt

- typed work itemとstable ID
- explicit status transition + validator
- parent/childとtyped links
- original estimate、remaining、immutable work log
- structured fields for report対象、Markdown body for narrative
- transition historyとcompletion resolution/evidence

### Adapt for a single person

- `assignee`ではなく`owner=self`をdefaultとし、waiting-forだけexternal partyを持つ。
- Jira priority 5段階をそのまま採用せず、commitment、due、impact、urgencyを分ける。
- sprint velocityではなく、cycle time、WIP、waiting age、estimate errorを自己改善に使う。
- subtaskを無制限にnestせず、GTD actionとmanaged-project WBSを分離する。
- create時のrequired fieldは少なくし、clarify/着手transitionで必要条件を検証する。

### Do not adopt

- permission scheme、reporter、watcher、notification noise
- team assignmentを前提とするworkflow
- story pointを個人の生産性scoreにする運用
- field追加で全情報を構造化し、captureを遅くすること
- Jiraと同じ万能issue aggregateへGTDとproject scheduleを押し込むこと

## Proposed personal-work ticket

構造化field:

- identity: id、schema version、work type
- intent: title、goal、desired outcome
- readiness: context、energy、estimate、not-before、schedule、due
- rigor: constraints、assumptions、risks、completion criteria
- relation: GTD project、parent、blocks、depends-on、relates-to
- flow: status、resolution、started/completed timestamps
- waiting: party、request、requested-at、expected-by、follow-up、escalation
- evidence: result summary、evidence links
- metrics: immutable work logsとtransition history

本文にはWhy / Goal / Constraints / Assumptions / Definition of Done / Notes / Result / Evidenceを置く。
frontmatterとの重複は避け、report/queryに必要な項目だけをfrontmatterへ置く。

## Unknowns to validate

- goalとdesired outcomeを別fieldにする価値が、個人taskでも常にあるか。
- constraint/assumptionをlist fieldにするか、本文sectionだけにするか。
- waiting response履歴をticket本文にappendするか、独立event projectionにするか。
