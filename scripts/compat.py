"""Check both extension sources and bundles against the real Superset runtime.

Usage: uv run scripts/compat.py

The local pytest suite runs on Python 3.12 with stubbed Superset modules, so it cannot see API drift in Superset
6.1 or syntax that Python 3.10 rejects. This script:

1. compares source fingerprints and bundled backend/frontend assets for both extensions;
2. compares both deployed bundles with the host bundles;
3. copies backend/src into the Superset container, compiles every module with the container's Python 3.10, and
   imports every module inside a Superset app context, so each `from superset... import` resolves against
   the real Superset 6.1 code.
"""

import argparse

from _common import (
    BUNDLE_PATH,
    SUPERSET_SERVICE,
    bundle_problems,
    compose,
    container_sha256,
    extensions,
    fail,
    require_superset_running,
    sha256_file,
    step,
)

CONTAINER_SRC = "/tmp/semantic-layer-compat"
PACKAGE = "text_to_bi.superset_semantic_layer"
REPORT_PREFIXES = ("Python ", "Compiled ", "Imported ", "PROBLEM ", "    ")

CONTAINER_SCRIPT = r"""
import importlib
import os
import sys
import traceback
from pathlib import Path

SRC = Path(sys.argv[1])
PACKAGE = sys.argv[2]
problems = []

print(f"Python {sys.version.split()[0]}")
files = sorted(
    path for path in (SRC / Path(*PACKAGE.split("."))).rglob("*.py") if "__pycache__" not in path.parts
)
for path in files:
    try:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    except SyntaxError as exc:
        problems.append(f"syntax {path.relative_to(SRC)}:{exc.lineno}: {exc.msg}")
print(f"Compiled {len(files)} modules")

if PACKAGE == "text_to_bi.superset_semantic_layer":
    try:
        importlib.import_module("openpyxl")
    except Exception:
        problems.append("runtime dependency openpyxl is unavailable")

# Load the stack's real configuration with extensions disabled, so Superset neither imports the deployed bundle
# (its supx:// import hook would shadow the source) nor registers the same API blueprints twice.
config_path = SRC.parent / "superset_config_compat.py"
config_path.write_text(
    "import os\n"
    "exec(open(os.environ['COMPAT_BASE_CONFIG'], encoding='utf-8').read())\n"
    "FEATURE_FLAGS = {**globals().get('FEATURE_FLAGS', {}), 'ENABLE_EXTENSIONS': False}\n",
    encoding="utf-8",
)
os.environ["COMPAT_BASE_CONFIG"] = os.environ.get("SUPERSET_CONFIG_PATH", "/app/pythonpath/superset_config.py")
os.environ["SUPERSET_CONFIG_PATH"] = str(config_path)

from superset.app import create_app

app = create_app()
with app.app_context():
    sys.path.insert(0, str(SRC))

    for path in files:
        parts = path.relative_to(SRC).with_suffix("").parts
        module_name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        try:
            module = importlib.import_module(module_name)
        except Exception:
            lines = traceback.format_exc().strip().splitlines()
            problems.append(f"import {module_name}:\n    " + "\n    ".join(lines[-3:]))
            continue
        module_file = getattr(module, "__file__", None)
        if module_file and not Path(module_file).is_relative_to(SRC):
            problems.append(f"import {module_name}: resolved to {module_file}, not the copied source")
    print(f"Imported {len(files)} modules")

for problem in problems:
    print(f"PROBLEM {problem}")
sys.exit(1 if problems else 0)
"""


def _bundle_state_failures(
    bundle_exists: bool,
    source_drift: list[str],
    host_hash: str | None,
    deployed_hash: str | None,
    bundle_name: str = BUNDLE_PATH.name,
) -> list[str]:
    failures = []
    if not bundle_exists:
        failures.append(f"{bundle_name} does not exist; run `uv run scripts/build.py`")
    elif source_drift:
        failures.append("the host bundle is stale; run `uv run scripts/build.py`")
    if bundle_exists and deployed_hash != host_hash:
        failures.append(
            "the deployed bundle is missing or differs from the host bundle; run `uv run scripts/deploy.py`"
        )
    return failures


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    require_superset_running()
    failures = []
    for extension in extensions():
        step(f"Checking {extension.name} bundle provenance and deployed hash")
        source_drift = bundle_problems(extension)
        print("\n".join(source_drift) if source_drift else "Host bundle matches source and staged assets.")
        host_hash = sha256_file(extension.bundle) if extension.bundle.exists() else None
        deployed_hash = container_sha256(extension.container_bundle) if extension.bundle.exists() else None
        failures.extend(
            f"{extension.name}: {failure}"
            for failure in _bundle_state_failures(
                extension.bundle.exists(), source_drift, host_hash, deployed_hash, extension.bundle.name
            )
        )

        step(f"Compiling and importing {extension.name} against Superset")
        container_source = f"/tmp/{extension.name}-compat"
        backend_source = extension.directory / "backend" / "src"
        package = "text_to_bi.superset_ai_agent" if extension.name == "superset-ai-agent" else PACKAGE
        compose("exec", "-T", "-u", "root", SUPERSET_SERVICE, "rm", "-rf", container_source)
        compose("cp", str(backend_source), f"{SUPERSET_SERVICE}:{container_source}")
        result = compose(
            "exec", "-T", SUPERSET_SERVICE, "python", "-", container_source, package,
            stdin=CONTAINER_SCRIPT, check=False, capture=True,
        )
        report = [line for line in result.stdout.splitlines() if line.startswith(REPORT_PREFIXES)]
        print("\n".join(report))
        if result.returncode != 0:
            failures.append(f"{extension.name}: source is not compatible with Superset runtime")
            if not any(line.startswith("PROBLEM") for line in report):
                print("\n".join((result.stdout + result.stderr).splitlines()[-30:]))

    step("Summary")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        fail("compatibility checks failed")
    print("The source compiles and imports against the Superset runtime.")


if __name__ == "__main__":
    main()
