"""User-editable Markdown body templates for managed projects."""

from __future__ import annotations

from pathlib import Path

from work_smarter.storage.workspace import Workspace

DEFAULT_MANAGED_PROJECT_TEMPLATE = """# {title}

## Goal and value

Describe why this outcome matters and how success will be observed.

## Scope

### In scope

-

### Out of scope

-

## Delivery strategy

Describe the lifecycle, reviews, verification, and release approach.

## Working agreements

Record decision authority, escalation paths, and communication cadence.

## Notes

Keep narrative context here; structured planning data remains in frontmatter.
"""

TEMPLATE_CATALOG: dict[str, str] = {
    "managed-project.md": DEFAULT_MANAGED_PROJECT_TEMPLATE,
    "charter.md": "# Project charter\n\n## Purpose\n\n## Authority\n\n## Success criteria\n",
    "requirements.md": (
        "# Requirements\n\n## Stakeholder needs\n\n## Requirements\n\n## Traceability\n"
    ),
    "wbs-dictionary.md": (
        "# WBS dictionary\n\n## Work package\n\n## Deliverables\n\n## Boundaries\n"
    ),
    "schedule-plan.md": "# Schedule plan\n\n## Dependencies\n\n## Milestones\n\n## Assumptions\n",
    "qcd-plan.md": "# QCD plan\n\n## Quality\n\n## Cost\n\n## Delivery\n\n## Scope\n",
    "risk-register.md": "# Risk and opportunity register\n\n## Identification\n\n## Response\n",
    "decision.md": "# Decision\n\n## Context\n\n## Options\n\n## Decision and rationale\n",
    "gate-review.md": (
        "# Gate review\n\n## Entry criteria\n\n## Evidence\n\n## Exceptions\n\n## Decision\n"
    ),
    "verification-validation-plan.md": (
        "# Verification and validation plan\n\n## Requirements\n\n## Methods\n\n## Evidence\n"
    ),
    "change-request.md": (
        "# Change request\n\n## Before and after\n\n## QCD impact\n\n## V&V impact\n"
    ),
    "closeout.md": "# Project closeout\n\n## Acceptance\n\n## QCD outcome\n\n## Lessons\n",
}


def managed_project_template_path(workspace: Workspace) -> Path:
    return workspace.root / "templates" / "project-management" / "managed-project.md"


def initialize_project_management_templates(workspace: Workspace) -> None:
    """Create defaults once and never overwrite a user's edited template."""

    directory = workspace.root / "templates" / "project-management"
    directory.mkdir(parents=True, exist_ok=True)
    for filename, content in TEMPLATE_CATALOG.items():
        path = directory / filename
        if not path.exists():
            path.write_text(content, encoding="utf-8")


def render_managed_project_template(workspace: Workspace, *, title: str) -> str:
    path = managed_project_template_path(workspace)
    if not path.exists():
        initialize_project_management_templates(workspace)
    return path.read_text(encoding="utf-8").replace("{title}", title)


__all__ = [
    "DEFAULT_MANAGED_PROJECT_TEMPLATE",
    "TEMPLATE_CATALOG",
    "initialize_project_management_templates",
    "managed_project_template_path",
    "render_managed_project_template",
]
