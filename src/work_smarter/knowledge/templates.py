"""User-overridable Markdown body templates for knowledge notes."""

from __future__ import annotations

from pathlib import Path

from work_smarter.knowledge.models import (
    KnowledgeNoteType,
    MarpPresentationTemplate,
)
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
    KnowledgeNoteType.TECHNICAL_REPORT: """## Executive Summary

## Objective

## Method

## Results

## Evidence

## Limitations and Unknowns

## Conclusion

## Next Actions

## Sources
""",
}

DEFAULT_PRESENTATION_TEMPLATES: dict[MarpPresentationTemplate, str] = {
    MarpPresentationTemplate.SCIENTIFIC: """section {
  --ws-accent: #005ea8;
  --ws-accent-soft: #d9ecf7;
  --ws-ink: #102a43;
  --ws-muted: #52606d;
  --ws-surface: #f7f9fb;
  --ws-rule: #bcccdc;
  align-content: start;
  align-items: stretch;
  background: var(--ws-surface);
  color: var(--ws-ink);
  font-family: Inter, "Noto Sans JP", "Hiragino Sans", "Yu Gothic", Arial, sans-serif;
  font-size: 24px;
  justify-content: flex-start;
  line-height: 1.38;
  padding: 52px 68px 46px;
}

section.title {
  border-top: 10px solid var(--ws-accent);
  padding-top: 62px;
}

h1,
h2,
h3 {
  color: var(--ws-ink);
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.16;
  margin: 0 0 24px;
}

h1 {
  border-bottom: 4px solid var(--ws-accent);
  font-size: 44px;
  padding-bottom: 14px;
}

h2 {
  border-bottom: 2px solid var(--ws-rule);
  font-size: 36px;
  padding-bottom: 12px;
}

h3 {
  color: var(--ws-accent);
  font-size: 28px;
  margin-bottom: 16px;
}

p,
ul,
ol {
  margin-bottom: 18px;
  margin-top: 0;
}

li {
  margin: 8px 0;
  padding-left: 4px;
}

ul {
  list-style: none;
  padding-left: 0;
}

ul ul {
  margin-top: 8px;
  padding-left: 34px;
}

ul > li {
  padding-left: 30px;
  position: relative;
}

ul > li::before {
  color: var(--ws-accent);
  content: "■";
  font-size: 0.68em;
  left: 2px;
  position: absolute;
  top: 0.3em;
}

ul ul > li::before {
  content: "●";
}

ul ul ul > li::before {
  content: "▲";
}

strong {
  color: var(--ws-accent);
}

section img,
section svg {
  display: block;
  margin: 10px auto 4px;
  max-height: 430px;
  max-width: 92%;
  object-fit: contain;
}

section p:has(> img),
section p:has(> svg) {
  text-align: center;
}

table {
  border-collapse: collapse;
  font-size: 20px;
  margin: 10px auto 4px;
  max-width: 100%;
  width: max-content;
}

th,
td {
  border: 1px solid var(--ws-rule);
  padding: 9px 14px;
  text-align: left;
}

th {
  background: var(--ws-accent-soft);
  color: var(--ws-ink);
}

section:has(table ~ table) table {
  font-size: 18px;
  margin: 8px auto 3px;
}

section:has(table ~ table) th,
section:has(table ~ table) td {
  padding: 6px 10px;
}

blockquote {
  background: #ffffff;
  border-left: 6px solid var(--ws-accent);
  color: var(--ws-ink);
  margin: 18px 0;
  padding: 14px 20px;
}

pre {
  background: #eef2f6;
  border: 1px solid var(--ws-rule);
  border-radius: 6px;
  font-size: 19px;
  line-height: 1.35;
  padding: 16px 20px;
}

code {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
}

small,
figcaption,
section p:has(> em:only-child) {
  color: var(--ws-muted);
  display: block;
  font-size: 16px;
  margin: 0 auto 16px;
  text-align: center;
  width: 100%;
}

a {
  color: var(--ws-accent);
}

section::after {
  color: var(--ws-muted);
  font-size: 14px;
  right: 28px;
}
""",
}


def template_path(workspace: Workspace, note_type: KnowledgeNoteType | str) -> Path:
    requested = KnowledgeNoteType(note_type)
    return workspace.root / "templates" / "knowledge" / f"{requested.value}.md"


def presentation_template_path(
    workspace: Workspace,
    template: MarpPresentationTemplate | str,
) -> Path:
    requested = MarpPresentationTemplate(template)
    return workspace.root / "templates" / "knowledge" / "presentations" / f"{requested.value}.css"


def initialize_knowledge_templates(workspace: Workspace) -> None:
    """Install missing defaults without replacing a user's edited templates."""

    directory = workspace.root / "templates" / "knowledge"
    directory.mkdir(parents=True, exist_ok=True)
    for note_type, content in DEFAULT_TEMPLATES.items():
        path = template_path(workspace, note_type)
        if not path.exists():
            path.write_text(content, encoding="utf-8")
    for template, content in DEFAULT_PRESENTATION_TEMPLATES.items():
        path = presentation_template_path(workspace, template)
        path.parent.mkdir(parents=True, exist_ok=True)
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


def render_presentation_template(
    workspace: Workspace,
    template: MarpPresentationTemplate | str,
) -> str:
    """Read a user-overridable presentation CSS template."""

    requested = MarpPresentationTemplate(template)
    path = presentation_template_path(workspace, requested)
    content = (
        path.read_text(encoding="utf-8")
        if path.is_file()
        else DEFAULT_PRESENTATION_TEMPLATES[requested]
    )
    return content.strip() + "\n"


__all__ = [
    "DEFAULT_TEMPLATES",
    "DEFAULT_PRESENTATION_TEMPLATES",
    "initialize_knowledge_templates",
    "render_knowledge_template",
    "render_presentation_template",
    "presentation_template_path",
    "template_path",
]
