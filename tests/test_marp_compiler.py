from __future__ import annotations

from pathlib import Path

import pytest

from work_smarter.knowledge.errors import (
    MarpCompilationError,
    MarpCompilerUnavailableError,
)
from work_smarter.knowledge.marp import MarpCliCompiler
from work_smarter.knowledge.models import MarpPresentation


def _presentation(markdown: str = "---\nmarp: true\n---\n# Report\n") -> MarpPresentation:
    return MarpPresentation(
        source_id="KN-REPORT",
        source_revision=3,
        theme="default",
        markdown=markdown,
    )


def _executable(path: Path, source: str) -> Path:
    path.write_text("#!/usr/bin/env python3\n" + source, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_marp_cli_compiler_uses_fixed_arguments_and_returns_html(tmp_path: Path) -> None:
    compiler = _executable(
        tmp_path / "fake-marp",
        """import pathlib
import sys

assert len(sys.argv) == 4
assert sys.argv[2] == "--output"
source = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
pathlib.Path(sys.argv[3]).write_text(
    "<!doctype html><html><body>" + source + "</body></html>",
    encoding="utf-8",
)
""",
    )
    presentation = _presentation("---\nmarp: true\n---\n# $(touch unsafe)\n")

    html = MarpCliCompiler(executable=str(compiler)).compile_html(presentation)

    assert html.startswith("<!doctype html>")
    assert "# $(touch unsafe)" in html
    assert not (tmp_path / "unsafe").exists()


def test_marp_cli_compiler_reports_missing_and_failed_executables(tmp_path: Path) -> None:
    with pytest.raises(MarpCompilerUnavailableError, match="not available"):
        MarpCliCompiler(executable="definitely-not-a-marp-command").compile_html(_presentation())

    failing = _executable(
        tmp_path / "failing-marp",
        """import sys
sys.stderr.write("invalid deck")
raise SystemExit(7)
""",
    )
    with pytest.raises(MarpCompilationError, match="invalid deck"):
        MarpCliCompiler(executable=str(failing)).compile_html(_presentation())

    slow = _executable(
        tmp_path / "slow-marp",
        """import time
time.sleep(1)
""",
    )
    with pytest.raises(MarpCompilationError, match="timeout"):
        MarpCliCompiler(executable=str(slow), timeout_seconds=0.01).compile_html(_presentation())
