"""A deliberately bounded Markdown/Confluence-storage conversion layer.

The converter supports the structures Work Smarter itself emits.  Unsupported
remote elements produce explicit warnings; they are never silently interpreted
as trusted HTML.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict


class ConversionWarning(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: Literal["unsafe_link", "unsupported_element", "unsupported_macro"]
    message: str


class ConversionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str
    warnings: list[ConversionWarning]


_LINK = re.compile(r"\[([^\]]+)]\(([^)]+)\)")
_CODE = re.compile(r"`([^`]+)`")
_STRONG = re.compile(r"\*\*(.+?)\*\*")
_EMPHASIS = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_UNORDERED = re.compile(r"^\s*[-*+]\s+(.+)$")
_ORDERED = re.compile(r"^\s*\d+[.)]\s+(.+)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_FENCE = re.compile(r"^```\s*([A-Za-z0-9_+.-]*)\s*$")


def _safe_link(value: str) -> bool:
    parsed = urlparse(html.unescape(value).strip())
    if parsed.scheme:
        return parsed.scheme.lower() in {"http", "https", "mailto"}
    return not value.lstrip().startswith(("//", "\\"))


def _inline_to_storage(text: str, warnings: list[ConversionWarning]) -> str:
    escaped = html.escape(text, quote=False)
    replacements: dict[str, str] = {}

    def reserve(rendered: str) -> str:
        token = f"\x00WS{len(replacements)}\x00"
        replacements[token] = rendered
        return token

    def code(match: re.Match[str]) -> str:
        return reserve(f"<code>{match.group(1)}</code>")

    escaped = _CODE.sub(code, escaped)

    def link(match: re.Match[str]) -> str:
        label, target = match.groups()
        raw_target = html.unescape(target).strip()
        if not _safe_link(raw_target):
            warnings.append(
                ConversionWarning(
                    code="unsafe_link",
                    message=f"Unsafe link scheme was rendered as text: {raw_target}",
                )
            )
            return f"{label} ({target})"
        return reserve(f'<a href="{html.escape(raw_target, quote=True)}">{label}</a>')

    escaped = _LINK.sub(link, escaped)
    escaped = _STRONG.sub(r"<strong>\1</strong>", escaped)
    escaped = _EMPHASIS.sub(r"<em>\1</em>", escaped)
    for token, rendered in replacements.items():
        escaped = escaped.replace(token, rendered)
    return escaped


def _table_cells(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def markdown_to_storage(markdown: str) -> ConversionResult:
    """Convert the safe, documented Markdown subset to storage-format markup."""

    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    warnings: list[ConversionWarning] = []
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        fence = _FENCE.match(line)
        if fence:
            language = fence.group(1)
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            code_text = "\n".join(code_lines).replace("]]>", "]]]]><![CDATA[>")
            language_parameter = (
                '<ac:parameter ac:name="language">' + html.escape(language) + "</ac:parameter>"
                if language
                else ""
            )
            output.append(
                '<ac:structured-macro ac:name="code">'
                + language_parameter
                + "<ac:plain-text-body><![CDATA["
                + code_text
                + "]]></ac:plain-text-body></ac:structured-macro>"
            )
            continue

        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            output.append(f"<h{level}>{_inline_to_storage(heading.group(2), warnings)}</h{level}>")
            index += 1
            continue

        if "|" in line and index + 1 < len(lines) and _TABLE_SEPARATOR.match(lines[index + 1]):
            headers = _table_cells(line)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_table_cells(lines[index]))
                index += 1
            header_markup = "".join(
                f"<th>{_inline_to_storage(cell, warnings)}</th>" for cell in headers
            )
            row_markup = "".join(
                "<tr>"
                + "".join(f"<td>{_inline_to_storage(cell, warnings)}</td>" for cell in row)
                + "</tr>"
                for row in rows
            )
            output.append(f"<table><tbody><tr>{header_markup}</tr>{row_markup}</tbody></table>")
            continue

        unordered = _UNORDERED.match(line)
        ordered = _ORDERED.match(line)
        if unordered or ordered:
            pattern = _UNORDERED if unordered else _ORDERED
            tag = "ul" if unordered else "ol"
            items: list[str] = []
            while index < len(lines):
                item = pattern.match(lines[index])
                if item is None:
                    break
                items.append(_inline_to_storage(item.group(1), warnings))
                index += 1
            output.append(f"<{tag}>" + "".join(f"<li>{item}</li>" for item in items) + f"</{tag}>")
            continue

        if not line.strip():
            index += 1
            continue

        paragraph = [line.strip()]
        index += 1
        while index < len(lines) and lines[index].strip():
            candidate = lines[index]
            if (
                _HEADING.match(candidate)
                or _FENCE.match(candidate)
                or _UNORDERED.match(candidate)
                or _ORDERED.match(candidate)
                or (
                    "|" in candidate
                    and index + 1 < len(lines)
                    and _TABLE_SEPARATOR.match(lines[index + 1])
                )
            ):
                break
            paragraph.append(candidate.strip())
            index += 1
        output.append(f"<p>{_inline_to_storage(' '.join(paragraph), warnings)}</p>")

    return ConversionResult(value="".join(output), warnings=warnings)


class _StorageParser(HTMLParser):
    _inline_tags = {"strong": "**", "b": "**", "em": "*", "i": "*", "code": "`"}
    _ignored_container_tags = {"tbody", "thead"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.warnings: list[ConversionWarning] = []
        self.list_stack: list[tuple[str, int]] = []
        self.link_target: str | None = None
        self.table_rows: list[list[str]] | None = None
        self.current_row: list[str] | None = None
        self.current_cell: list[str] | None = None
        self.current_cell_is_header = False
        self.table_has_header = False
        self.macro_kind: str | None = None
        self.macro_depth = 0
        self.macro_language = ""
        self.macro_code: list[str] = []
        self.capture_parameter = False
        self.capture_code = False

    def _append(self, value: str) -> None:
        if self.current_cell is not None:
            self.current_cell.append(value)
        else:
            self.output.append(value)

    def _warning(
        self,
        code: Literal["unsupported_element", "unsupported_macro"],
        message: str,
    ) -> None:
        self.warnings.append(ConversionWarning(code=code, message=message))

    @staticmethod
    def _attribute(attributes: list[tuple[str, str | None]], name: str) -> str | None:
        return next((value for key, value in attributes if key == name), None)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.macro_depth:
            self.macro_depth += 1
            if self.macro_kind == "code":
                if tag == "ac:parameter" and self._attribute(attrs, "ac:name") == "language":
                    self.capture_parameter = True
                elif tag == "ac:plain-text-body":
                    self.capture_code = True
            return

        if tag == "ac:structured-macro":
            name = self._attribute(attrs, "ac:name") or "unknown"
            self.macro_kind = name
            self.macro_depth = 1
            if name != "code":
                self._append(f"\n[Unsupported Confluence macro: {name}]\n")
                self._warning("unsupported_macro", f"Unsupported Confluence macro: {name}")
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._append("\n" + "#" * int(tag[1]) + " ")
        elif tag == "p":
            self._append("\n")
        elif tag in self._inline_tags:
            self._append(self._inline_tags[tag])
        elif tag == "a":
            self.link_target = self._attribute(attrs, "href") or ""
            self._append("[")
        elif tag in {"ul", "ol"}:
            self.list_stack.append((tag, 0))
            self._append("\n")
        elif tag == "li":
            if self.list_stack:
                kind, count = self.list_stack[-1]
                count += 1
                self.list_stack[-1] = (kind, count)
                self._append(f"{count}. " if kind == "ol" else "- ")
        elif tag == "br":
            self._append("\n")
        elif tag == "table":
            self.table_rows = []
            self.table_has_header = False
        elif tag == "tr" and self.table_rows is not None:
            self.current_row = []
        elif tag in {"th", "td"} and self.current_row is not None:
            self.current_cell = []
            self.current_cell_is_header = tag == "th"
            self.table_has_header = self.table_has_header or self.current_cell_is_header
        elif tag not in self._ignored_container_tags:
            self._warning("unsupported_element", f"Unsupported Confluence element: {tag}")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.macro_depth:
            if self.macro_kind == "code":
                if tag == "ac:parameter":
                    self.capture_parameter = False
                elif tag == "ac:plain-text-body":
                    self.capture_code = False
            self.macro_depth -= 1
            if self.macro_depth == 0:
                if self.macro_kind == "code":
                    language = self.macro_language.strip()
                    code = "".join(self.macro_code).strip("\n")
                    self._append(f"\n```{language}\n{code}\n```\n")
                self.macro_kind = None
                self.macro_language = ""
                self.macro_code = []
                self.capture_parameter = False
                self.capture_code = False
            return

        if re.fullmatch(r"h[1-6]", tag) or tag == "p":
            self._append("\n")
        elif tag in self._inline_tags:
            self._append(self._inline_tags[tag])
        elif tag == "a":
            self._append(f"]({self.link_target or ''})")
            self.link_target = None
        elif tag == "li":
            self._append("\n")
        elif tag in {"ul", "ol"}:
            if self.list_stack:
                self.list_stack.pop()
            self._append("\n")
        elif tag in {"th", "td"} and self.current_cell is not None:
            if self.current_row is not None:
                self.current_row.append("".join(self.current_cell).strip())
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            if self.table_rows is not None:
                self.table_rows.append(self.current_row)
            self.current_row = None
        elif tag == "table" and self.table_rows is not None:
            rows = self.table_rows
            self.table_rows = None
            if rows:
                width = max(len(row) for row in rows)
                normalized = [row + [""] * (width - len(row)) for row in rows]
                header = normalized[0]
                body = normalized[1:]
                self._append("\n| " + " | ".join(header) + " |\n")
                self._append("| " + " | ".join("---" for _ in header) + " |\n")
                for row in body:
                    self._append("| " + " | ".join(row) + " |\n")
                self._append("\n")

    def handle_data(self, data: str) -> None:
        if self.macro_depth:
            if self.capture_parameter:
                self.macro_language += data
            elif self.capture_code:
                self.macro_code.append(data)
            return
        self._append(data)

    def unknown_decl(self, data: str) -> None:
        """HTMLParser reports storage-format CDATA through this callback."""

        if self.macro_depth and self.capture_code and data.startswith("CDATA["):
            self.macro_code.append(data[len("CDATA[") :])
            return
        self._warning("unsupported_element", "Unsupported declaration in Confluence storage")

    def result(self) -> ConversionResult:
        value = "".join(self.output)
        value = re.sub(r"[ \t]+\n", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value).strip()
        return ConversionResult(value=value + ("\n" if value else ""), warnings=self.warnings)


def storage_to_markdown(storage: str) -> ConversionResult:
    """Convert supported storage markup to Markdown and report every loss boundary."""

    parser = _StorageParser()
    parser.feed(storage)
    parser.close()
    return parser.result()


__all__ = [
    "ConversionResult",
    "ConversionWarning",
    "markdown_to_storage",
    "storage_to_markdown",
]
