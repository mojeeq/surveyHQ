"""Security regression tests for the R process sandbox.

The confinement tests need a kernel that can enforce Landlock, so they
skip where it cannot. What can be checked anywhere - that the platform
refuses to run R unconfined, and says why - is in
test_r_sandbox_policy.py, which has no such requirement.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SANDBOX = Path(os.environ.get("SURVEYHQ_R_SANDBOX", "/usr/local/bin/surveyhq-r-sandbox"))


def _can_enforce() -> bool:
    """Whether this host can actually apply the sandbox.

    The confinement tests below assert that R is *denied* things. On a host
    where Landlock cannot be installed the launcher refuses to start at all,
    so those assertions would pass for the wrong reason - nothing ran. Skipping
    is honest; a green tick that means "R never started" is not.
    """
    if not SANDBOX.exists() or not Path("/usr/bin/Rscript").exists():
        return False
    probe = subprocess.run(
        [str(SANDBOX), "--surveyhq-sandbox-selftest"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(
    not _can_enforce(),
    reason="needs the compiled sandbox, R, and a kernel that can enforce Landlock",
)


def _run_r(workspace: Path, code: str) -> subprocess.CompletedProcess[str]:
    script = workspace / "sandbox-test.R"
    script.write_text(code, encoding="utf-8")
    return subprocess.run(
        [str(SANDBOX), "--vanilla", script.name],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_r_can_read_its_workspace_but_not_sibling_files(tmp_path: Path) -> None:
    workspace = tmp_path / "project-a"
    workspace.mkdir()
    (workspace / "inside.txt").write_text("visible", encoding="utf-8")
    secret = tmp_path / "project-b-secret.txt"
    secret.write_text("must not be visible", encoding="utf-8")

    result = _run_r(
        workspace,
        "inside <- tryCatch(readLines('inside.txt'), error=function(e) character()); "
        f"outside <- tryCatch(readLines({secret.as_posix()!r}), "
        "error=function(e) character()); "
        "cat(identical(inside, 'visible'), '|', length(outside) == 0)",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "TRUE | TRUE"


def test_r_cannot_create_network_socket(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    result = _run_r(
        workspace,
        "ok <- tryCatch({ con <- socketConnection(host='127.0.0.1', port=9, "
        "open='r+', blocking=TRUE, timeout=1); close(con); TRUE }, "
        "error=function(e) FALSE, warning=function(w) FALSE); cat(ok)",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "FALSE"


def test_r_cannot_write_runtime_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    result = _run_r(
        workspace,
        "target <- '/usr/local/bin/surveyhq-r-sandbox-write-test'; "
        "ok <- tryCatch({ writeLines('x', target); TRUE }, error=function(e) FALSE); "
        "cat(ok)",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "FALSE"


def test_launcher_identifies_itself() -> None:
    result = subprocess.run(
        [str(SANDBOX), "--surveyhq-sandbox-probe"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "surveyhq-r-sandbox-v1"
