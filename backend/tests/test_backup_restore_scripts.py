"""Run the actual operational scripts against a small Docker command double."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def installation(tmp_path):
    root = Path(__file__).resolve().parents[2]
    (tmp_path / "scripts").mkdir()
    for name in ("backup.sh", "restore.sh"):
        shutil.copy(root / "scripts" / name, tmp_path / "scripts" / name)
    (tmp_path / ".env").write_text(
        "ENCRYPTION_KEY=test-key\nEMAIL_FROM=SurveyHQ <noreply@example.org>\n"
    )
    (tmp_path / "volume").mkdir()
    (tmp_path / "volume" / "household.csv").write_text("id,value\n1,42\n")
    (tmp_path / "bin").mkdir()
    docker = tmp_path / "bin" / "docker"
    docker.write_text("""#!/usr/bin/env python3
import os, sys, subprocess, pathlib, shutil
root=pathlib.Path(os.environ['TEST_INSTALL'])
args=sys.argv[1:]
with (root/'commands').open('a') as log: log.write(' '.join(args)+'\\n')
if 'ps' in args: print('api\\nworker\\nworker-monitoring\\nbeat')
elif any('pg_dump' in arg for arg in args): print('-- known database dump')
elif any('psql' in arg for arg in args):
    (root/'restored.sql').write_bytes(sys.stdin.buffer.read())
    if os.environ.get('FAIL_RESTORE'): sys.exit(1)
elif 'tar' in args:
    if os.environ.get('FAIL_COPY'): sys.exit(1)
    sys.exit(subprocess.run(['tar','czf','-','-C',str(root/'volume'),'.']).returncode)
elif 'sh' in args:
    shutil.rmtree(root/'volume'); (root/'volume').mkdir()
    sys.exit(subprocess.run(['tar','xzf','-','-C',str(root/'volume')]).returncode)
elif 'python' in args and '-c' in args:
    environ = {**os.environ, 'ENCRYPTION_KEY': os.environ.get('TEST_ENCRYPTION_KEY', 'test-key')}
    sys.exit(subprocess.run([sys.executable, '-c', args[args.index('-c') + 1]], env=environ).returncode)
""")
    docker.chmod(0o755)
    return tmp_path, {
        **os.environ,
        "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        "TEST_INSTALL": str(tmp_path),
    }


def run(installation, name, *args, **env):
    root, environ = installation
    return subprocess.run(
        ["bash", str(root / "scripts" / name), *map(str, args)],
        cwd=root,
        env={**environ, **env},
        input="restore\n",
        capture_output=True,
        text=True,
    )


def test_copy_failure_cannot_produce_a_successful_backup(installation):
    root, _ = installation
    result = run(installation, "backup.sh", FAIL_COPY="1")
    assert result.returncode != 0
    assert not list((root / "backups").glob("*.tar.gz"))
    assert "Wrote" not in result.stdout
    commands = (root / "commands").read_text()
    assert "stop api worker worker-monitoring beat" in commands
    assert "start api worker worker-monitoring beat" in commands


def test_backup_restore_roundtrip_and_sql_failure(installation):
    root, _ = installation
    result = run(installation, "backup.sh")
    assert result.returncode == 0, result.stderr
    backup = next((root / "backups").glob("*.tar.gz"))
    (root / "volume" / "household.csv").write_text("corrupted")
    result = run(installation, "restore.sh", backup)
    assert result.returncode == 0, result.stderr
    assert (root / "volume" / "household.csv").read_text() == "id,value\n1,42\n"
    assert "-- known database dump" in (root / "restored.sql").read_text()
    (root / "commands").write_text("")
    result = run(installation, "restore.sh", backup, FAIL_RESTORE="1")
    assert result.returncode != 0
    commands = (root / "commands").read_text()
    assert "ON_ERROR_STOP=1 --single-transaction" in commands
    assert "start api" not in commands
    assert "Restore complete" not in result.stdout


def test_restore_refuses_a_different_encryption_key_before_stopping_writers(installation):
    root, _ = installation
    result = run(installation, "backup.sh")
    assert result.returncode == 0, result.stderr
    backup = next((root / "backups").glob("*.tar.gz"))
    (root / "commands").write_text("")
    result = run(installation, "restore.sh", backup, TEST_ENCRYPTION_KEY="different-key")
    assert result.returncode != 0
    assert "ENCRYPTION_KEY differs" in result.stderr
    assert "stop api" not in (root / "commands").read_text()
