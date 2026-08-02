from __future__ import annotations

from pathlib import Path

import pytest

from work_smarter.errors import InvalidDocumentError
from work_smarter.storage.frontmatter import parse_markdown, read_markdown, write_markdown


def test_markdown_round_trip_keeps_metadata_and_body(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    metadata = {
        "schema_version": 1,
        "id": "REF-1",
        "kind": "reference",
        "title": "日本語の資料",
        "tags": ["design", "設計"],
    }

    write_markdown(path, metadata, "# Heading\n\nBody\n")

    document = read_markdown(path)
    assert document.metadata == metadata
    assert document.body == "# Heading\n\nBody\n"


def test_duplicate_frontmatter_keys_are_rejected() -> None:
    document = """---
id: TASK-1
kind: task
kind: reference
---

Body
"""

    with pytest.raises(InvalidDocumentError, match="duplicate key"):
        parse_markdown(document, source="duplicate.md")


@pytest.mark.parametrize(
    "document, message",
    [
        ("plain Markdown", "must start"),
        ("---\nid: X\n", "no closing"),
        ("---\n- one\n- two\n---\n", "must be a mapping"),
    ],
)
def test_malformed_frontmatter_is_rejected(document: str, message: str) -> None:
    with pytest.raises(InvalidDocumentError, match=message):
        parse_markdown(document)
