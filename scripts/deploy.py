"""Deploy both extension bundles to Superset, restoring prior bundles on failure.

Usage: uv run scripts/deploy.py

The two file copies and Superset restart are coordinated, but cannot be atomic. Previous bundles are saved
under .release-backups/. If verification fails, they are restored and Superset is started again. Database
migrations are not rolled back.
"""

import argparse
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from _common import (
    ROOT,
    Extension,
    bundle_problems,
    compose,
    container_sha256,
    extensions,
    fail,
    require_superset_running,
    resolve_command,
    sha256_file,
    step,
    wait_for_health,
)

LOG_ERROR_MARKERS = ("Traceback", "not a valid zip", "Failed to load extension")


def _snapshot_metadata(destination: Path) -> None:
    command = resolve_command(
        [
            "docker", "compose", "exec", "-T", "superset-db", "sh", "-c",
            'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc',
        ]
    )
    with destination.open("wb") as output:
        result = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.PIPE, check=False)
    if result.returncode or destination.stat().st_size == 0:
        raise RuntimeError(f"metadata snapshot failed: {result.stderr.decode(errors='replace').strip()}")
    with destination.open("rb") as snapshot:
        result = subprocess.run(
            resolve_command(["docker", "compose", "exec", "-T", "superset-db", "pg_restore", "--list"]),
            cwd=ROOT, stdin=snapshot, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False,
        )
    if result.returncode:
        raise RuntimeError(f"metadata snapshot validation failed: {result.stderr.decode(errors='replace').strip()}")
    print(f"Metadata snapshot: {destination} (sha256 {sha256_file(destination)})")


def _copy_checked(source: str, destination: str) -> None:
    result = compose("cp", source, destination, check=False, capture=True)
    if result.returncode:
        raise RuntimeError(f"docker compose cp failed: {result.stderr.strip()}")


def _verify_started(restarted_at: str, selected: tuple[Extension, ...]) -> None:
    wait_for_health()
    log = compose("logs", "--no-color", "--since", restarted_at, "superset", capture=True).stdout
    errors = [line for line in log.splitlines() if any(marker in line for marker in LOG_ERROR_MARKERS)]
    missing = [
        extension.identifier for extension in selected if f"Loaded extension '{extension.identifier}'" not in log
    ]
    if missing or errors:
        raise RuntimeError(f"startup verification failed; missing load lines: {missing}; error lines: {errors[-10:]}")


def _restore(previous: dict[Extension, Path | None]) -> None:
    step("Restoring previous bundles")
    for extension, backup in previous.items():
        if backup is None:
            # A failed restart can leave Superset stopped, so use a temporary service container
            # sharing the extensions volume.
            compose("run", "--rm", "--no-deps", "--entrypoint", "rm", "superset", "-f", extension.container_bundle)
        else:
            _copy_checked(str(backup), f"superset:{extension.container_bundle}")
            with tempfile.TemporaryDirectory(prefix="text-to-bi-verify-") as directory:
                copied_back = Path(directory) / extension.bundle.name
                _copy_checked(f"superset:{extension.container_bundle}", str(copied_back))
                if sha256_file(copied_back) != sha256_file(backup):
                    raise RuntimeError(f"restored {extension.name} bundle differs from backup")
    compose("up", "-d", "--no-deps", "superset")
    wait_for_health()


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    selected = extensions()
    problems = [problem for extension in selected for problem in bundle_problems(extension)]
    if problems:
        fail("stale or missing release artifacts:\n" + "\n".join(problems))
    require_superset_running()
    if compose("exec", "-T", "superset", "python", "-c", "import openpyxl", capture=True, check=False).returncode != 0:
        fail(
            "Superset image is missing openpyxl; "
            "rebuild it with `docker compose up -d --build superset` before deploying"
        )

    backup_directory = ROOT / ".release-backups" / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{os.getpid()}"
    backup_directory.mkdir(parents=True)
    print(f"Backup directory: {backup_directory}")
    try:
        step("Snapshotting Superset metadata before migrations")
        _snapshot_metadata(backup_directory / "superset-metadata.dump")
    except RuntimeError as error:
        fail(f"{error}; no bundle was copied")
    previous: dict[Extension, Path | None] = {}
    step("Backing up installed bundles")
    for extension in selected:
        old_hash = container_sha256(extension.container_bundle)
        if old_hash is None:
            previous[extension] = None
            continue
        backup = backup_directory / extension.bundle.name
        _copy_checked(f"superset:{extension.container_bundle}", str(backup))
        if sha256_file(backup) != old_hash:
            fail(f"backup of {extension.name} differs from installed bundle; backup directory: {backup_directory}")
        previous[extension] = backup

    try:
        step("Copying and verifying both bundles")
        for extension in selected:
            _copy_checked(str(extension.bundle), f"superset:{extension.container_bundle}")
            if container_sha256(extension.container_bundle) != sha256_file(extension.bundle):
                raise RuntimeError(f"installed {extension.name} bundle differs from host")
        step("Restarting Superset")
        restarted_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        compose("restart", "superset")
        _verify_started(restarted_at, selected)
    except (RuntimeError, SystemExit) as error:
        try:
            _restore(previous)
        except (RuntimeError, SystemExit) as restore_error:
            fail(
                f"release failed ({error}); rollback also failed ({restore_error}); "
                f"inspect backups at {backup_directory}"
            )
        fail(f"release failed ({error}); previous bundles restored")
    print("Superset loaded both extensions.")


if __name__ == "__main__":
    main()
