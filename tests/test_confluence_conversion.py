from __future__ import annotations

from work_smarter.confluence.conversion import markdown_to_storage, storage_to_markdown


def test_markdown_to_storage_converts_supported_blocks_and_escapes_raw_html() -> None:
    markdown = """# Release <script>alert(1)</script>

See [runbook](https://example.com/runbook) and `ws doctor`.

- first
- second **strong**

| Check | Result |
|---|---|
| tests | pass |

```python
print("<safe>")
```
"""

    result = markdown_to_storage(markdown)

    assert "<h1>Release &lt;script&gt;alert(1)&lt;/script&gt;</h1>" in result.value
    assert '<a href="https://example.com/runbook">runbook</a>' in result.value
    assert "<code>ws doctor</code>" in result.value
    assert "<ul><li>first</li><li>second <strong>strong</strong></li></ul>" in result.value
    assert "<table><tbody>" in result.value
    assert "<th>Check</th>" in result.value
    assert 'ac:name="language">python</ac:parameter>' in result.value
    assert 'print("&lt;safe&gt;")' not in result.value
    assert 'print("<safe>")' in result.value
    assert result.warnings == []


def test_generated_storage_round_trips_to_readable_markdown() -> None:
    original = """## Deploy

Run **tests** before release.

1. Build
2. Verify

| Q | D |
|---|---|
| green | 2026-08-01 |

```bash
ws doctor
```
"""

    storage = markdown_to_storage(original)
    restored = storage_to_markdown(storage.value)

    assert storage.warnings == []
    assert restored.warnings == []
    assert "## Deploy" in restored.value
    assert "Run **tests** before release." in restored.value
    assert "1. Build\n2. Verify" in restored.value
    assert "| Q | D |" in restored.value
    assert "```bash\nws doctor\n```" in restored.value


def test_unsafe_link_is_rendered_as_text_not_clickable() -> None:
    result = markdown_to_storage("[click](javascript:alert(1))\n")

    assert "href=" not in result.value
    assert "click (javascript:alert(1))" in result.value
    assert result.warnings[0].code == "unsafe_link"


def test_unsupported_remote_macro_is_preserved_as_text_with_warning() -> None:
    storage = (
        '<p>Before</p><ac:structured-macro ac:name="jira">'
        '<ac:parameter ac:name="key">ENG-1</ac:parameter>'
        "</ac:structured-macro><p>After</p>"
    )

    result = storage_to_markdown(storage)

    assert "Before" in result.value
    assert "[Unsupported Confluence macro: jira]" in result.value
    assert "After" in result.value
    assert any(warning.code == "unsupported_macro" for warning in result.warnings)


def test_storage_parser_rejects_active_html_without_emitting_it() -> None:
    result = storage_to_markdown('<script>alert("x")</script><p>Safe</p>')

    assert "<script>" not in result.value
    assert 'alert("x")' in result.value
    assert "Safe" in result.value
    assert any(warning.code == "unsupported_element" for warning in result.warnings)
