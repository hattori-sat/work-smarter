from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from work_smarter.cli import app

runner = CliRunner()


def _fake_marp_cli(path: Path) -> Path:
    path.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

source = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
pathlib.Path(sys.argv[3]).write_text(
    "<!doctype html><html><body>" + source + "</body></html>",
    encoding="utf-8",
)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _common(workspace: Path) -> list[str]:
    return ["--workspace", str(workspace), "--json", "knowledge"]


def _initialize(workspace: Path) -> None:
    initialized = runner.invoke(app, ["--workspace", str(workspace), "init"])
    assert initialized.exit_code == 0, initialized.output


def test_knowledge_cli_manages_notes_with_prefixes_and_pure_json(tmp_path: Path) -> None:
    _initialize(tmp_path)
    common = _common(tmp_path)

    created = runner.invoke(
        app,
        [
            *common,
            "add",
            "Release decision",
            "--type",
            "decision",
            "--body",
            "# Decision\n\nShip the canary first.",
            "--tag",
            "Release",
            "--alias",
            "ship-plan",
            "--source",
            "url=https://example.com/release",
        ],
    )
    assert created.exit_code == 0, created.output
    document = json.loads(created.stdout)
    note_id = document["note"]["id"]
    assert document["note"]["note_type"] == "decision"
    assert document["note"]["tags"] == ["release"]
    assert document["note"]["sources"][0]["kind"] == "url"

    shown = runner.invoke(app, [*common, "show", note_id[:12]])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.stdout)["note"]["id"] == note_id

    shown_by_alias = runner.invoke(app, [*common, "show", "ship-plan"])
    assert shown_by_alias.exit_code == 0, shown_by_alias.output
    assert json.loads(shown_by_alias.stdout)["note"]["id"] == note_id

    updated = runner.invoke(
        app,
        [
            *common,
            "update",
            note_id[:12],
            "--title",
            "Canary release decision",
            "--tag",
            "delivery",
            "--alias",
            "canary-plan",
        ],
    )
    assert updated.exit_code == 0, updated.output
    updated_document = json.loads(updated.stdout)
    assert updated_document["note"]["title"] == "Canary release decision"
    assert updated_document["note"]["tags"] == ["delivery"]

    listed = runner.invoke(
        app,
        [*common, "list", "--type", "decision", "--tag", "delivery"],
    )
    assert listed.exit_code == 0, listed.output
    assert [item["note"]["id"] for item in json.loads(listed.stdout)] == [note_id]

    searched = runner.invoke(
        app,
        [*common, "search", "canary", "--field", "title"],
    )
    assert searched.exit_code == 0, searched.output
    assert json.loads(searched.stdout)[0]["matched_fields"] == ["title"]


def test_knowledge_cli_links_and_backlinks_use_human_prefixes(tmp_path: Path) -> None:
    _initialize(tmp_path)
    common = _common(tmp_path)
    target = json.loads(runner.invoke(app, [*common, "add", "Canonical design"]).stdout)
    source = json.loads(runner.invoke(app, [*common, "add", "Implementation notes"]).stdout)
    target_id = target["note"]["id"]
    source_id = source["note"]["id"]

    linked = runner.invoke(
        app,
        [
            *common,
            "link",
            source_id[:12],
            target_id[:12],
            "--type",
            "supports",
            "--label",
            "Implementation evidence",
        ],
    )
    assert linked.exit_code == 0, linked.output
    link = json.loads(linked.stdout)["note"]["links"][0]
    assert link == {
        "target_id": target_id,
        "relation": "supports",
        "label": "Implementation evidence",
    }

    backlinks = runner.invoke(app, [*common, "backlinks", target_id[:12]])
    assert backlinks.exit_code == 0, backlinks.output
    assert json.loads(backlinks.stdout)[0]["source"]["note"]["id"] == source_id

    checked = runner.invoke(app, [*common, "doctor"])
    assert checked.exit_code == 0, checked.output
    report = json.loads(checked.stdout)
    assert report["valid"] is True
    assert report["counts"]["notes"] == 2


def test_knowledge_cli_promotes_any_workspace_record_without_copying_files(
    tmp_path: Path,
) -> None:
    _initialize(tmp_path)
    task = runner.invoke(
        app,
        [
            "--workspace",
            str(tmp_path),
            "--json",
            "add",
            "Investigate retry policy",
            "--tag",
            "reliability",
        ],
    )
    assert task.exit_code == 0, task.output
    task_id = json.loads(task.stdout)["created"][0]["id"]

    promoted = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "promote",
            task_id[:12],
            "--type",
            "reference",
            "--tag",
            "investigation",
            "--alias",
            "retry-research",
        ],
    )
    assert promoted.exit_code == 0, promoted.output
    document = json.loads(promoted.stdout)
    assert document["note"]["title"] == "Investigate retry policy"
    assert document["note"]["note_type"] == "reference"
    assert document["note"]["sources"][0]["kind"] == "entity"
    assert document["note"]["sources"][0]["locator"] == task_id


def test_knowledge_cli_renders_marp_to_stdout_and_safe_output_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _initialize(tmp_path)
    common = _common(tmp_path)
    created = runner.invoke(
        app,
        [
            *common,
            "add",
            "API reliability report",
            "--type",
            "technical_report",
            "--body",
            "## Outcome\n\nError rates fell.\n",
        ],
    )
    note_id = json.loads(created.stdout)["note"]["id"]

    rendered = runner.invoke(
        app,
        [*common, "presentation", "render", note_id[:12], "--theme", "uncover"],
    )
    assert rendered.exit_code == 0, rendered.output
    payload = json.loads(rendered.stdout)
    assert payload["source_id"] == note_id
    assert payload["mode"] == "technical_report"
    assert payload["theme"] == "uncover"
    assert payload["markdown"].startswith("---\nmarp: true\n")

    output = tmp_path / "exports" / "reliability.marp.md"
    exported = runner.invoke(
        app,
        [
            "--workspace",
            str(tmp_path),
            "knowledge",
            "presentation",
            "render",
            note_id[:12],
            "--output",
            str(output),
        ],
    )
    assert exported.exit_code == 0, exported.output
    assert exported.stdout.strip() == str(output)
    assert output.read_text(encoding="utf-8").startswith("---\nmarp: true\n")

    refused = runner.invoke(
        app,
        [
            "--workspace",
            str(tmp_path),
            "knowledge",
            "presentation",
            "render",
            note_id,
            "--output",
            str(output),
        ],
    )
    assert refused.exit_code == 2
    assert "pass --force to overwrite" in refused.output

    unsafe_theme = runner.invoke(
        app,
        [
            "--workspace",
            str(tmp_path),
            "knowledge",
            "presentation",
            "render",
            note_id,
            "--theme",
            "default\npaginate: false",
        ],
    )
    assert unsafe_theme.exit_code == 2
    assert "Invalid value for --theme" in unsafe_theme.output
    assert "Traceback" not in unsafe_theme.output

    fake_marp = _fake_marp_cli(tmp_path / "fake-marp")
    monkeypatch.setenv("WORK_SMARTER_MARP_CLI", str(fake_marp))
    html_output = tmp_path / "exports" / "reliability.html"
    html_rendered = runner.invoke(
        app,
        [
            *common,
            "presentation",
            "render",
            note_id[:12],
            "--format",
            "html",
            "--output",
            str(html_output),
        ],
    )
    assert html_rendered.exit_code == 0, html_rendered.output
    html_payload = json.loads(html_rendered.stdout)
    assert html_payload["source_id"] == note_id
    assert html_payload["media_type"] == "text/html"
    assert html_payload["html"].startswith("<!doctype html>")
    assert html_output.read_text(encoding="utf-8") == html_payload["html"]
