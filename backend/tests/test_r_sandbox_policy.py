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


def test_the_opt_out_runs_r_rather_than_the_launcher(monkeypatch):
    """Giving up the sandbox must not leave the launcher as the executable.

    The host that sets R_SANDBOX_REQUIRED=false is the host whose kernel
    cannot enforce Landlock, and the launcher exits rather than run there. So
    an opt-out that still resolved to the launcher would be an opt-out of
    running R at all - which is what it was, until this test.
    """
    settings = get_settings()
    settings.r_scripts_enabled = True
    settings.r_binary = rproject.SANDBOX_BINARY  # the default
    settings.r_sandbox_required = False
    asked: list[str] = []

    def which(name):
        asked.append(name)
        return f"/usr/bin/{name}"

    monkeypatch.setattr(shutil, "which", which)
    assert rproject.binary() == "/usr/bin/Rscript"
    assert asked == ["Rscript"], "the launcher must not be what gets run"


def test_an_explicit_r_binary_is_still_honoured_when_opting_out(monkeypatch):
    """Only the default is swapped; a named binary stays named."""
    settings = get_settings()
    settings.r_scripts_enabled = True
    settings.r_binary = "/opt/R/bin/Rscript"
    settings.r_sandbox_required = False
    monkeypatch.setattr(shutil, "which", lambda name: name)
    assert rproject.binary() == "/opt/R/bin/Rscript"


def test_the_launcher_denies_truncate_below_landlock_abi_3(tmp_path):
    """ABI 1 and 2 do not mediate truncate(2); seccomp has to stand in.

    Linux 5.13 to 6.1 - which includes the 5.15 on Ubuntu 22.04 - has no
    LANDLOCK_ACCESS_FS_TRUNCATE, so a path-based truncate() would reach files
    the sandbox never allowed opening. Checked by reading the source rather
    than by running it, since the branch only fires on an old kernel.
    """
    source = (Path(__file__).resolve().parents[1] / "sandbox" / "r-sandbox.c").read_text()
    assert 'if (abi < 3) {' in source
    assert 'deny_syscall(ctx, "truncate", denied);' in source
    assert "install_syscall_sandbox(int abi)" in source


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
