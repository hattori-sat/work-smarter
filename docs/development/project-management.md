# Project management internals

`project_management` はGTDとは別のentity boundaryです。serviceが不変条件とappend-only eventを扱い、`projections.py`はtable/Mermaid/HTML/Markdownを副作用なしで生成します。NASA/JAXA資料は個人向けの軽量なtraceability profileとして参照しただけで、規格適合を主張しません。

## Scheduling and Gantt

Schedulingはproject-local `WorkingCalendar`上のtickへ正規化し、FS/SS/FF/SFを同じprecedence
constraintへ変換してforward/backward passします。`ScheduleProjection`はearliest/latest、total/free
float、critical path、project finishを返します。`explain_schedule`はdriving predecessor、relation、
lead/lag、休日skip、明示date constraintを返します。

`GanttRenderer`がapplication側のport、`HtmlGanttRenderer`が組込みadapterです。出力はCDN不要の
self-contained HTMLであり、authoritative Markdownを書き換えません。詳細な式と判断は
[ADR 0006](../architecture/0006-explainable-offline-gantt.md)を参照してください。
