"""User-overridable Markdown body templates for GTD records."""

from __future__ import annotations

from pathlib import Path

from work_smarter.storage.workspace import Workspace

DEFAULT_TEMPLATES = {
    "task.md": """## Intent

{{ intent }}

## Why

## Goal

## Desired Outcome

## Constraints

## Assumptions

## Definition of Done

## Notes

## Result / Evidence
""",
    "project.md": """## Outcome

{{ outcome }}

## Project support

Captured from `{{ source_id }}`.
""",
}


def initialize_gtd_templates(workspace: Workspace) -> None:
    directory = workspace.root / "templates" / "gtd"
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in DEFAULT_TEMPLATES.items():
        path = directory / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")


def render_gtd_template(workspace: Workspace, name: str, **values: str) -> str:
    default = DEFAULT_TEMPLATES.get(name)
    if default is None:
        raise ValueError(f"Unknown GTD template: {name}")
    path = workspace.root / "templates" / "gtd" / name
    template = path.read_text(encoding="utf-8") if path.is_file() else default
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{ " + key + " }}", value.strip())
    return rendered.strip() + "\n"


def template_path(workspace: Workspace, name: str) -> Path:
    return workspace.root / "templates" / "gtd" / name
