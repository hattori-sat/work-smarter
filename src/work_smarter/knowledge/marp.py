"""Optional Marp CLI adapter for compiling presentation projections."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from work_smarter.knowledge.errors import (
    MarpCompilationError,
    MarpCompilerUnavailableError,
)
from work_smarter.knowledge.models import MarpPresentation


def _failure_detail(completed: subprocess.CompletedProcess[str]) -> str:
    detail = (completed.stderr or completed.stdout).strip()
    if not detail:
        detail = f"Marp CLI exited with status {completed.returncode}"
    return detail[:1000]


@dataclass(frozen=True, slots=True)
class MarpCliCompiler:
    """Compile HTML with fixed Marp CLI arguments and no shell expansion."""

    executable: str = "marp"
    timeout_seconds: float = 30.0

    @classmethod
    def from_environment(cls) -> MarpCliCompiler:
        """Read a single executable name/path, never a shell command string."""

        return cls(executable=os.environ.get("WORK_SMARTER_MARP_CLI", "marp").strip() or "marp")

    def compile_html(self, presentation: MarpPresentation) -> str:
        resolved = shutil.which(self.executable)
        if resolved is None:
            raise MarpCompilerUnavailableError(
                f"Marp CLI {self.executable!r} is not available; install it or set "
                "WORK_SMARTER_MARP_CLI to its executable path"
            )

        with tempfile.TemporaryDirectory(prefix="work-smarter-marp-") as temporary:
            directory = Path(temporary)
            source = directory / "presentation.marp.md"
            output = directory / "presentation.html"
            source.write_text(presentation.markdown, encoding="utf-8")
            try:
                completed = subprocess.run(
                    [resolved, str(source), "--output", str(output)],
                    cwd=directory,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                raise MarpCompilationError(
                    f"Marp CLI exceeded the {self.timeout_seconds:g}s timeout"
                ) from exc
            except OSError as exc:
                raise MarpCompilerUnavailableError(
                    f"Marp CLI {self.executable!r} could not be started"
                ) from exc

            if completed.returncode != 0:
                raise MarpCompilationError(_failure_detail(completed))
            if not output.is_file():
                raise MarpCompilationError("Marp CLI completed without producing HTML")
            html = output.read_text(encoding="utf-8")
            if not html.strip():
                raise MarpCompilationError("Marp CLI produced an empty HTML document")
            return html


__all__ = ["MarpCliCompiler"]
