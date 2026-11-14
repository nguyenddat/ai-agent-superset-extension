import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common
import deploy
from _common import Extension


def test_installed_bundle_probe_distinguishes_absence_from_failure(monkeypatch):
    monkeypatch.setattr(_common, "compose", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="ABSENT\n", stderr=""))
    assert _common.container_sha256("/extensions/example.supx") is None

    monkeypatch.setattr(_common, "compose", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="daemon unavailable"))
    with pytest.raises(RuntimeError, match="could not inspect installed bundle"):
        _common.container_sha256("/extensions/example.supx")


def test_restore_reinstalls_old_bundle_and_removes_new_bundle(tmp_path, monkeypatch):
    old_extension = Extension(tmp_path, "superset-ai-agent", "text-to-bi", "0.1.0")
    new_extension = Extension(tmp_path, "superset-semantic-layer", "text-to-bi", "0.1.0")
    backup = tmp_path / old_extension.bundle.name
    backup.write_bytes(b"old bundle")
    commands = []

    def fake_compose(*args, **kwargs):
        commands.append(args)
        if args[0] == "cp" and args[1].startswith("superset:"):
            Path(args[2]).write_bytes(backup.read_bytes())
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(deploy, "compose", fake_compose)
    monkeypatch.setattr(deploy, "wait_for_health", lambda: None)

    deploy._restore({old_extension: backup, new_extension: None})

    assert ("cp", str(backup), f"superset:{old_extension.container_bundle}") in commands
    assert ("run", "--rm", "--no-deps", "--entrypoint", "rm", "superset", "-f", new_extension.container_bundle) in commands
    assert ("up", "-d", "--no-deps", "superset") in commands


@pytest.mark.parametrize("failure", ["second_copy", "restart"])
def test_partial_release_restores_both_previous_bundles(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(_common, "ROOT", tmp_path)
    selected = tuple(Extension(tmp_path / name, f"superset-{name}", "text-to-bi", "0.1.0") for name in ("ai-agent", "semantic-layer"))
    for extension in selected:
        extension.bundle.parent.mkdir(parents=True, exist_ok=True)
        extension.bundle.write_bytes(f"new {extension.name}".encode())
    installed = {extension.container_bundle: f"old {extension.name}".encode() for extension in selected}
    restarts = []
    recoveries = []
    copies = []

    def fake_compose(*args, **kwargs):
        if args[0] == "cp":
            source, destination = args[1:]
            copies.append((source, destination))
            if source == str(selected[1].bundle) and failure == "second_copy":
                return SimpleNamespace(returncode=1, stderr="injected copy failure")
            if source.startswith("superset:"):
                Path(destination).write_bytes(installed[source.removeprefix("superset:")])
            else:
                installed[destination.removeprefix("superset:")] = Path(source).read_bytes()
        if args[0] == "restart":
            restarts.append(1)
            if failure == "restart" and len(restarts) == 1:
                raise SystemExit(1)
        if args[0] == "up":
            recoveries.append(1)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    monkeypatch.setattr(deploy, "extensions", lambda: selected)
    monkeypatch.setattr(deploy, "bundle_problems", lambda extension: [])
    monkeypatch.setattr(deploy, "_snapshot_metadata", lambda path: path.write_bytes(b"metadata snapshot"))
    monkeypatch.setattr(deploy, "require_superset_running", lambda: None)
    monkeypatch.setattr(deploy, "compose", fake_compose)
    monkeypatch.setattr(deploy, "container_sha256", lambda path: hashlib.sha256(installed[path]).hexdigest() if path in installed else None)
    monkeypatch.setattr(deploy, "wait_for_health", lambda: None)

    with pytest.raises(SystemExit):
        deploy.main([])

    assert installed == {extension.container_bundle: f"old {extension.name}".encode() for extension in selected}
    assert len(restarts) == (0 if failure == "second_copy" else 1)
    assert len(recoveries) == 1
    assert any(source.startswith("superset:") for source, _ in copies)


def test_restore_removes_bundle_that_was_not_previously_installed(tmp_path, monkeypatch):
    extension = Extension(tmp_path, "superset-ai-agent", "text-to-bi", "0.1.0")
    commands = []
    monkeypatch.setattr(deploy, "compose", lambda *args, **kwargs: commands.append(args) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(deploy, "wait_for_health", lambda: None)

    deploy._restore({extension: None})

    assert ("run", "--rm", "--no-deps", "--entrypoint", "rm", "superset", "-f", extension.container_bundle) in commands


def test_restore_works_while_superset_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "ROOT", tmp_path)
    old_extension = Extension(tmp_path, "superset-ai-agent", "text-to-bi", "0.1.0")
    new_extension = Extension(tmp_path, "superset-semantic-layer", "text-to-bi", "0.1.0")
    backup = tmp_path / old_extension.bundle.name
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(b"previous AI Agent")
    installed = {old_extension.container_bundle: b"new AI Agent", new_extension.container_bundle: b"new Semantic Layer"}
    running = False

    def fake_compose(*args, **kwargs):
        nonlocal running
        if args[0] == "exec" and not running:
            raise RuntimeError("service is not running")
        if args[0] == "cp":
            source, destination = args[1:]
            if source.startswith("superset:"):
                Path(destination).write_bytes(installed[source.removeprefix("superset:")])
            else:
                installed[destination.removeprefix("superset:")] = Path(source).read_bytes()
        if args[0] == "run":
            installed.pop(args[-1], None)
        if args[0] == "up":
            running = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(deploy, "compose", fake_compose)
    monkeypatch.setattr(deploy, "wait_for_health", lambda: None)

    deploy._restore({old_extension: backup, new_extension: None})

    assert running
    assert installed == {old_extension.container_bundle: b"previous AI Agent"}


def test_failed_metadata_snapshot_stops_before_bundle_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    monkeypatch.setattr(deploy, "extensions", lambda: (Extension(tmp_path, "superset-ai-agent", "text-to-bi", "0.1.0"),))
    monkeypatch.setattr(deploy, "bundle_problems", lambda extension: [])
    monkeypatch.setattr(deploy, "require_superset_running", lambda: None)
    monkeypatch.setattr(deploy, "_snapshot_metadata", lambda path: (_ for _ in ()).throw(RuntimeError("injected pg_dump failure")))
    def fake_compose(*args, **kwargs):
        if args[:4] == ("exec", "-T", "superset", "python"):
            return SimpleNamespace(returncode=0)
        pytest.fail("Docker copy or restart ran after failed metadata snapshot")

    monkeypatch.setattr(deploy, "compose", fake_compose)

    with pytest.raises(SystemExit):
        deploy.main([])


def test_missing_excel_runtime_stops_before_metadata_snapshot_or_bundle_copy(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    monkeypatch.setattr(deploy, "extensions", lambda: (Extension(tmp_path, "superset-semantic-layer", "text-to-bi", "0.1.0"),))
    monkeypatch.setattr(deploy, "bundle_problems", lambda extension: [])
    monkeypatch.setattr(deploy, "require_superset_running", lambda: None)
    monkeypatch.setattr(deploy, "_snapshot_metadata", lambda path: pytest.fail("metadata snapshot ran before runtime preflight"))
    monkeypatch.setattr(deploy, "compose", lambda *args, **kwargs: SimpleNamespace(returncode=1))

    with pytest.raises(SystemExit):
        deploy.main([])
    assert "missing openpyxl" in capsys.readouterr().err
