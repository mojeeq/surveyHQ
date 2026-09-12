"""Security regression tests for the R process sandbox."""

from __future__ import annotations

import http.server
import socketserver
import subprocess
import threading
from pathlib import Path

import pytest


WRAPPER = Path(__file__).resolve().parents[1] / "bin" / "surveyhq-rscript"


pytestmark = pytest.mark.skipif(
    not Path("/usr/bin/bwrap").exists() or not Path("/usr/bin/Rscript").exists(),
    reason="bubblewrap and R are required for the sandbox integration tests",
)


def _run_r(workspace: Path, code: str) -> subprocess.CompletedProcess[str]:
    script = workspace / "sandbox-test.R"
    script.write_text(code, encoding="utf-8")
    return subprocess.run(
        ["bash", str(WRAPPER), "--vanilla", script.name],
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
        "cat(file.exists('inside.txt'), '|', "
        f"file.exists({secret.as_posix()!r}))",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "TRUE | FALSE"


def test_r_has_no_outbound_or_host_loopback_network(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()

    class QuietHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"host-network")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    with socketserver.TCPServer(("127.0.0.1", 0), QuietHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        result = _run_r(
            workspace,
            "options(timeout=2); "
            f"u <- 'http://127.0.0.1:{port}/'; "
            "ok <- tryCatch({ readLines(u, warn=FALSE); TRUE }, "
            "error=function(e) FALSE, warning=function(w) FALSE); cat(ok)",
        )
        server.shutdown()
        thread.join(timeout=2)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "FALSE"


def test_wrapper_is_not_writable_by_the_r_process(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    result = _run_r(
        workspace,
        "cat(file.access('/usr/local/bin', 2) == 0)",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "FALSE"
