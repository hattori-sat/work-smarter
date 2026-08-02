"""User-overridable Markdown body templates for knowledge notes."""

from __future__ import annotations

from pathlib import Path

from work_smarter.knowledge.models import KnowledgeNoteType
from work_smarter.storage.workspace import Workspace

DEFAULT_TEMPLATES: dict[KnowledgeNoteType, str] = {
    KnowledgeNoteType.NOTE: """## Summary

## Details

## Related
""",
    KnowledgeNoteType.DECISION: """## Context

## Decision

## Consequences

## Alternatives considered
""",
    KnowledgeNoteType.HOW_TO: """## Goal

## Prerequisites

## Procedure

## Verification
""",
    KnowledgeNoteType.REFERENCE: """## Summary

## Extracts

## Sources
""",
    KnowledgeNoteType.MEETING_NOTE: """## Attendees

## Agenda

## Notes

## Decisions

## Actions
""",
}


def template_path(workspace: Workspace, note_type: KnowledgeNoteType | str) -> Path:
    requested = KnowledgeNoteType(note_type)
    return workspace.root / "templates" / "knowledge" / f"{requested.value}.md"


def initialize_knowledge_templates(workspace: Workspace) -> None:
    """Install missing defaults without replacing a user's edited templates."""

    directory = workspace.root / "templates" / "knowledge"
    directory.mkdir(parents=True, exist_ok=True)
    for note_type, content in DEFAULT_TEMPLATES.items():
        path = template_path(workspace, note_type)
        if not path.exists():
            path.write_text(content, encoding="utf-8")


def render_knowledge_template(
    workspace: Workspace,
    note_type: KnowledgeNoteType | str,
    **values: str,
) -> str:
    """Render the current user template with intentionally simple placeholders."""

    requested = KnowledgeNoteType(note_type)
    path = template_path(workspace, requested)
    template = path.read_text(encoding="utf-8") if path.is_file() else DEFAULT_TEMPLATES[requested]
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{ " + key + " }}", value.strip())
    return rendered.strip() + "\n"


__all__ = [
    "DEFAULT_TEMPLATES",
    "initialize_knowledge_templates",
    "render_knowledge_template",
    "template_path",
]
