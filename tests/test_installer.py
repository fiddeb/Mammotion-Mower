"""Exercise installation and update rollback with real POSIX shell commands."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/package-homeassistant.sh"


def install(target, *, env=None):
    return subprocess.run(["sh", str(SCRIPT), str(target)], capture_output=True, text=True, env=env)


def test_install_with_spaces_and_without_development_caches(tmp_path):
    target = tmp_path / "Home Assistant" / "custom_components" / "mammotion_openapi"
    result = install(target)
    assert result.returncode == 0, result.stderr
    source = ROOT / "custom_components/mammotion_openapi"
    expected = {
        file.relative_to(source): file.read_bytes()
        for file in source.rglob("*")
        if file.is_file() and file.suffix in (".py", ".json", ".yaml")
    }
    actual = {
        file.relative_to(target): file.read_bytes() for file in target.rglob("*") if file.is_file()
    }
    assert actual == expected
    assert not list(target.parent.glob(".mammotion_openapi.*"))


def test_update_preserves_backup_and_other_integrations(tmp_path):
    parent = tmp_path / "custom_components"
    target = parent / "mammotion_openapi"
    target.mkdir(parents=True)
    (target / "obsolete.py").write_text("previous version")
    other = parent / "another_integration"
    other.mkdir()
    (other / "keep.txt").write_text("keep")
    result = install(target)
    assert result.returncode == 0, result.stderr
    assert not (target / "obsolete.py").exists()
    backups = list(parent.glob(".mammotion_openapi.backup.*/mammotion_openapi"))
    assert len(backups) == 1
    assert (backups[0] / "obsolete.py").read_text() == "previous version"
    assert (other / "keep.txt").read_text() == "keep"


def test_wrong_destination_is_rejected(tmp_path):
    target = tmp_path / "config"
    target.mkdir()
    marker = target / "configuration.yaml"
    marker.write_text("keep")
    assert install(target).returncode != 0
    assert marker.read_text() == "keep"


def test_symlink_destination_is_rejected(tmp_path):
    parent = tmp_path / "custom_components"
    parent.mkdir()
    original = tmp_path / "original"
    original.mkdir()
    target = parent / "mammotion_openapi"
    target.symlink_to(original, target_is_directory=True)
    assert install(target).returncode != 0
    assert target.is_symlink()
    assert not list(original.iterdir())


def test_failed_replacement_restores_previous_version(tmp_path):
    target = tmp_path / "custom_components/mammotion_openapi"
    target.mkdir(parents=True)
    (target / "previous.py").write_text("previous version")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_mv = fake_bin / "mv"
    fake_mv.write_text(
        "#!/bin/sh\n"
        'case "$2" in */.mammotion_openapi.install.*) exit 1 ;; esac\n'
        'exec /bin/mv "$@"\n'
    )
    fake_mv.chmod(0o755)
    result = install(target, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"})
    assert result.returncode != 0
    assert (target / "previous.py").read_text() == "previous version"
    assert not list(target.parent.glob(".mammotion_openapi.*"))


def test_existing_lock_prevents_overlapping_install(tmp_path):
    parent = tmp_path / "custom_components"
    lock = parent / ".mammotion_openapi.install.lock"
    lock.mkdir(parents=True)
    assert install(parent / "mammotion_openapi").returncode != 0
    assert lock.exists()
    assert not (parent / "mammotion_openapi").exists()
