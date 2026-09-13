"""What the platform does when R cannot be sandboxed.

These need no kernel support: they are about refusing to run R, and saying
which of the several possible reasons applies. The confinement itself is
covered by test_r_sandbox.py, which skips where Landlock cannot be enforced.
"""

from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services import rproject


@pytest.fixture(autouse=True)
def forget_the_probe():
    """The answer is cached per process; each test asks afresh."""
    rproject._sandbox_check = None
    settings = get_settings()
    before = (settings.r_scripts_enabled, settings.r_binary, settings.r_sandbox_required)
    yield
    (
        settings.r_scripts_enabled,
        settings.r_binary,
        settings.r_sandbox_required,
    ) = before
    rproject._sandbox_check = None


def _stub(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_r_off_says_so_first(monkeypatch):
    settings = get_settings()
    settings.r_scripts_enabled = False
    assert "switched off" in rproject.unavailable_reason()
    assert rproject.available() is False


def test_a_missing_launcher_asks_for_a_rebuild_not_an_apt_install(monkeypatch):
    """The old message sent people to apt-get, which would not help.

    With R_BINARY naming the sandbox, absence means the image predates it.
    """
    settings = get_settings()
    settings.r_scripts_enabled = True
    settings.r_binary = rproject.SANDBOX_BINARY
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    reason = rproject.unavailable_reason()
    assert "rebuilding" in reason and "docker compose build" in reason
    assert "apt-get" not in reason


def test_a_bare_rscript_is_refused(tmp_path, monkeypatch):
    """Pointing R_BINARY at real Rscript must not quietly unconfine everything."""
    settings = get_settings()
    settings.r_scripts_enabled = True
    settings.r_binary = "Rscript"
    fake = _stub(tmp_path / "Rscript", 'echo "R scripting front-end"\n')
    monkeypatch.setattr(shutil, "which", lambda _name: str(fake))

    reason = rproject.unavailable_reason()
    assert "does not name the SurveyHQ sandbox launcher" in reason
    assert rproject.available() is False


def test_a_host_that_cannot_enforce_is_told_which_check_failed(tmp_path, monkeypatch):
    """Identifies itself, but the kernel will not have it."""
    settings = get_settings()
    settings.r_scripts_enabled = True
    settings.r_binary = rproject.SANDBOX_BINARY
    fake = _stub(
        tmp_path / rproject.SANDBOX_BINARY,
        f'if [ "$1" = "--surveyhq-sandbox-probe" ]; then echo "{rproject.SANDBOX_PROBE}"; exit 0; fi\n'
        'if [ "$1" = "--surveyhq-sandbox-selftest" ]; then\n'
        '  echo "landlock-unavailable: errno=38 (Function not implemented)." >&2\n'
        '  exit 1\n'
        'fi\n',
    )
    monkeypatch.setattr(shutil, "which", lambda _name: str(fake))

    reason = rproject.unavailable_reason()
    assert "cannot be enforced on this host" in reason
    assert "landlock-unavailable" in reason
    assert "surveyhq-check-r-sandbox" in reason
    assert rproject.available() is False


def test_a_working_launcher_allows_r(tmp_path, monkeypatch):
    settings = get_settings()
    settings.r_scripts_enabled = True
    settings.r_binary = rproject.SANDBOX_BINARY
    fake = _stub(
        tmp_path / rproject.SANDBOX_BINARY,
        f'if [ "$1" = "--surveyhq-sandbox-probe" ]; then echo "{rproject.SANDBOX_PROBE}"; exit 0; fi\n'
        'if [ "$1" = "--surveyhq-sandbox-selftest" ]; then echo "landlock-abi=5 rscript=ok"; exit 0; fi\n',
    )
    monkeypatch.setattr(shutil, "which", lambda _name: str(fake))

    assert rproject.unavailable_reason() == ""
    assert rproject.available() is True


def test_the_confinement_can_be_given_up_deliberately(tmp_path, monkeypatch):
    """R_SANDBOX_REQUIRED=false is the documented way back to unconfined R.

    It exists so a host that cannot enforce Landlock has a path other than
    reverting the feature, and it is off by default.
    """
    settings = get_settings()
    settings.r_scripts_enabled = True
    settings.r_binary = "Rscript"
    settings.r_sandbox_required = False
    fake = _stub(tmp_path / "Rscript", 'echo "R scripting front-end"\n')
    monkeypatch.setattr(shutil, "which", lambda _name: str(fake))

    assert rproject.unavailable_reason() == ""
    assert rproject.available() is True


def test_the_launcher_source_builds_and_answers_its_probe(tmp_path):
    """The C in backend/sandbox compiles clean and identifies itself.

    Landlock is not exercised here - that needs a kernel that allows it - but a
    launcher that does not build is a launcher that reaches no image.
    """
    source = Path(__file__).resolve().parents[1] / "sandbox" / "r-sandbox.c"
    assert source.exists()
    if shutil.which("cc") is None:
        pytest.skip("no C compiler")
    built = tmp_path / "surveyhq-r-sandbox"
    compile_result = subprocess.run(
        ["cc", "-O2", "-Wall", "-Wextra", "-Werror", str(source), "-lseccomp", "-o", str(built)],
        capture_output=True, text=True, check=False,
    )
    if compile_result.returncode != 0:
        if "seccomp.h" in compile_result.stderr or "-lseccomp" in compile_result.stderr:
            pytest.skip("libseccomp-dev is not installed on this machine")
        pytest.fail(compile_result.stderr)
    probe = subprocess.run([str(built), "--surveyhq-sandbox-probe"],
                           capture_output=True, text=True, check=False)
    assert probe.returncode == 0
    assert probe.stdout.strip() == rproject.SANDBOX_PROBE
