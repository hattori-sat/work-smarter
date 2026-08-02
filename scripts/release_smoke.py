"""Build and exercise the installed wheel in an isolated temporary environment."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="work-smarter-release-") as temporary:
        root = Path(temporary)
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        subprocess.run(
            [sys.executable, "-m", "venv", "--system-site-packages", str(root / "venv")],
            check=True,
            cwd=repository,
            env=environment,
        )
        python = root / "venv" / "bin" / "python"
        wheel_dir = root / "wheel"
        wheel_dir.mkdir()
        run(
            [
                str(python),
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(wheel_dir),
                str(repository),
            ],
            cwd=root,
            environment=environment,
        )
        wheels = sorted(wheel_dir.glob("work_smarter-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"Expected one wheel, found: {wheels}")
        run(
            [str(python), "-m", "pip", "install", str(wheels[0])],
            cwd=root,
            environment=environment,
        )
        ws = root / "venv" / "bin" / "ws"
        workspace = root / "workspace"
        run([str(ws), "--help"], cwd=root, environment=environment)
        run(
            [str(ws), "--workspace", str(workspace), "init"],
            cwd=root,
            environment=environment,
        )
        run(
            [
                str(ws),
                "--workspace",
                str(workspace),
                "gtd",
                "capture",
                "Installed wheel capture",
            ],
            cwd=root,
            environment=environment,
        )
        operations = run(
            [
                str(ws),
                "--workspace",
                str(workspace),
                "--json",
                "system",
                "operation",
                "list",
            ],
            cwd=root,
            environment=environment,
        )
        parsed = json.loads(operations)
        if not parsed or parsed[0]["status"] != "completed":
            raise RuntimeError(f"Installed operation journal smoke failed: {parsed}")
        archive = root / "release-smoke.ws.zip"
        restored = root / "restored"
        run(
            [
                str(ws),
                "--workspace",
                str(workspace),
                "workspace",
                "export",
                str(archive),
            ],
            cwd=root,
            environment=environment,
        )
        run(
            [
                str(ws),
                "--workspace",
                str(restored),
                "workspace",
                "import",
                str(archive),
            ],
            cwd=root,
            environment=environment,
        )
        doctor = run(
            [str(ws), "--workspace", str(restored), "--json", "doctor"],
            cwd=root,
            environment=environment,
        )
        if not json.loads(doctor)["valid"]:
            raise RuntimeError(f"Restored workspace doctor failed: {doctor}")
        print(f"release smoke passed: {wheels[0].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
