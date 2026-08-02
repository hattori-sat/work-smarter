"""Read-only presentation projections owned by the Knowledge feature."""

from __future__ import annotations

import re

from work_smarter.knowledge.models import (
    KnowledgeDocument,
    KnowledgePresentationMode,
    MarpPresentation,
)

_FENCE = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})")


def _one_line(value: str) -> str:
    return " ".join(value.splitlines()).strip()


def _slides_from_body(body: str) -> str:
    """Start one slide per level-two section while retaining source Markdown."""

    normalized = body.strip("\n").rstrip()
    if not normalized:
        return ""

    output: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in normalized.splitlines():
        fence = _FENCE.match(line)
        if fence_character is None:
            if line.startswith("## ") and len(line) > 3:
                output.extend(("---", ""))
            if fence is not None:
                marker = fence.group("marker")
                fence_character = marker[0]
                fence_length = len(marker)
        elif fence is not None:
            marker = fence.group("marker")
            remainder = line[fence.end() :]
            if (
                marker[0] == fence_character
                and len(marker) >= fence_length
                and not remainder.strip()
            ):
                fence_character = None
                fence_length = 0
        output.append(line)
    return "\n".join(output)


def render_marp_presentation(
    document: KnowledgeDocument,
    *,
    mode: KnowledgePresentationMode | str = KnowledgePresentationMode.TECHNICAL_REPORT,
    theme: str = "default",
    paginate: bool = True,
) -> MarpPresentation:
    """Render a deterministic Marp document without changing its source note."""

    requested_mode = KnowledgePresentationMode(mode)
    # Construct first so untrusted theme text is validated before interpolation into YAML.
    presentation = MarpPresentation(
        source_id=document.note.id,
        source_revision=document.note.revision,
        mode=requested_mode,
        theme=theme,
        paginate=paginate,
        markdown="pending",
    )
    body_slides = _slides_from_body(document.body)
    lines = [
        "---",
        "marp: true",
        f"theme: {presentation.theme}",
        f"paginate: {str(presentation.paginate).lower()}",
        "---",
        f"<!-- Source: {document.note.id}@{document.note.revision} -->",
        "",
        f"# {_one_line(document.note.title)}",
        "",
        "Technical report",
    ]
    if body_slides:
        lines.extend(("", body_slides))
    markdown = "\n".join(lines).rstrip() + "\n"
    return presentation.model_copy(update={"markdown": markdown})


__all__ = ["render_marp_presentation"]
