"""Build both extension bundles and record the source hashes used for each build.

Usage: uv run scripts/build.py
"""

import argparse
import json
import os
import subprocess

from _common import Extension, extensions, resolve_command, sha256_file, source_fingerprint, step


def _bundle(extension: Extension) -> None:
    real_run = subprocess.run

    def run_resolved(command, *args, **kwargs):
        if isinstance(command, list) and command:
            command = resolve_command(command)
        return real_run(command, *args, **kwargs)

    subprocess.run = run_resolved
    previous_cwd = os.getcwd()
    try:
        from superset_extensions_cli.cli import app

        os.chdir(extension.directory)
        app.main(["bundle", "--output", str(extension.bundle)], standalone_mode=False)
    finally:
        os.chdir(previous_cwd)
        subprocess.run = real_run


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    for extension in extensions():
        step(f"Bundling {extension.name}")
        sources = source_fingerprint(extension)
        _bundle(extension)
        if source_fingerprint(extension) != sources:
            raise RuntimeError(f"{extension.name} sources changed while building; run the build again")
        bundle_hash = sha256_file(extension.bundle)
        extension.provenance.write_text(
            json.dumps({"bundle_sha256": bundle_hash, "sources": sources}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Bundle: {extension.bundle}\nsha256: {bundle_hash}")


if __name__ == "__main__":
    main()
