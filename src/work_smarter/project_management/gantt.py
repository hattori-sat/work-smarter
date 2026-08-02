"""Gantt renderer port and the built-in offline HTML adapter."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from work_smarter.project_management.models import ManagedProject, ScheduleProjection
from work_smarter.project_management.projections import render_html_gantt


class GanttRenderer(Protocol):
    media_type: str
    format: str

    def render(
        self,
        project: ManagedProject,
        schedule: ScheduleProjection,
        *,
        today: date | None = None,
    ) -> str: ...


class HtmlGanttRenderer:
    media_type = "text/html"
    format = "gantt_html"

    def render(
        self,
        project: ManagedProject,
        schedule: ScheduleProjection,
        *,
        today: date | None = None,
    ) -> str:
        return render_html_gantt(project, schedule, today=today)


__all__ = ["GanttRenderer", "HtmlGanttRenderer"]
