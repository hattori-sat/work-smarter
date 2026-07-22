"""Safe Markdown frontmatter parsing and atomic writing."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from work_smarter.errors import InvalidDocumentError


class UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects silently overwritten duplicate keys."""


def _construct_unique_mapping(
    loader: UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True, slots=True)
class MarkdownDocument:
    metadata: dict[str, Any]
    body: str


def parse_markdown(text: str, *, source: str = "<memory>") -> MarkdownDocument:
    """Parse a Markdown document with mandatory YAML frontmatter."""

    normalized = text.replace("\r\n", "\n")
    lines = normalized.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise InvalidDocumentError(f"{source}: document must start with YAML frontmatter")

    closing_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        raise InvalidDocumentError(f"{source}: YAML frontmatter has no closing delimiter")

    yaml_text = "".join(lines[1:closing_index])
    try:
        loaded = yaml.load(yaml_text, Loader=UniqueKeySafeLoader) or {}
    except yaml.YAMLError as exc:
        raise InvalidDocumentError(f"{source}: invalid YAML frontmatter: {exc}") from exc
    if not isinstance(loaded, dict):
        raise InvalidDocumentError(f"{source}: frontmatter must be a mapping")

    body = "".join(lines[closing_index + 1 :])
    if body.startswith("\n"):
        body = body[1:]
    return MarkdownDocument(metadata=loaded, body=body.rstrip() + ("\n" if body.strip() else ""))


def render_markdown(metadata: dict[str, Any], body: str = "") -> str:
    """Render deterministic, human-editable Markdown with safe YAML values."""

    yaml_text = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=100,
    ).rstrip()
    rendered = f"---\n{yaml_text}\n---\n"
    clean_body = body.strip("\n")
    if clean_body:
        rendered += f"\n{clean_body}\n"
    return rendered


def read_markdown(path: Path) -> MarkdownDocument:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidDocumentError(f"Cannot read {path}: {exc}") from exc
    return parse_markdown(text, source=str(path))


def write_markdown(path: Path, metadata: dict[str, Any], body: str = "") -> None:
    """Atomically replace a Markdown document in its destination directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = render_markdown(metadata, body)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(rendered)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    except OSError as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise InvalidDocumentError(f"Cannot write {path}: {exc}") from exc
