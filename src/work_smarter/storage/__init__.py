"""Text-first persistence for Work Smarter."""

from work_smarter.storage.events import Event, EventStore
from work_smarter.storage.frontmatter import (
    MarkdownDocument,
    parse_markdown,
    read_markdown,
    render_markdown,
    write_markdown,
)

__all__ = [
    "Event",
    "EventStore",
    "MarkdownDocument",
    "parse_markdown",
    "read_markdown",
    "render_markdown",
    "write_markdown",
]
