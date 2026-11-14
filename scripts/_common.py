import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Windows pipes default to cp1252, which cannot encode the emoji that superset-extensions prints.
for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = ROOT / "extensions" / "semantic-layer"
BACKEND_DIR = EXTENSION_DIR / "backend"
BACKEND_SRC = BACKEND_DIR / "src"
FRONTEND_DIR = EXTENSION_DIR / "frontend"

_MANIFEST = json.loads((EXTENSION_DIR / "extension.json").read_text(encoding="utf-8"))
EXTENSION_ID = f"{_MANIFEST['publisher']}.{_MANIFEST['name']}"
BUNDLE_PATH = ROOT / "extensions" / f"{_MANIFEST['name']}-{_MANIFEST['version']}.supx"

SUPERSET_SERVICE = "superset"
CONTAINER_EXTENSIONS_DIR = "/app/superset_home/extensions"
CONTAINER_BUNDLE_PATH = f"{CONTAINER_EXTENSIONS_DIR}/{BUNDLE_PATH.name}"
SUPERSET_URL = os.getenv("SUPERSET_URL", f"http://localhost:{os.getenv('SUPERSET_PORT', '8089')}")
API_PREFIX = f"/extensions/{_MANIFEST['publisher']}/{_MANIFEST['name']}"


@dataclass(frozen=True)
class Extension:
    directory: Path
    name: str
    publisher: str
    version: str

    @property
    def bundle(self) -> Path:
        return ROOT / "extensions" / f"{self.name}-{self.version}.supx"

    @property
    def provenance(self) -> Path:
        return self.bundle.with_suffix(".provenance.json")

    @property
    def identifier(self) -> str:
        return f"{self.publisher}.{self.name}"

    @property
    def container_bundle(self) -> str:
        return f"{CONTAINER_EXTENSIONS_DIR}/{self.bundle.name}"


def extensions() -> tuple[Extension, ...]:
    result = []
    for directory_name in ("ai-agents", "semantic-layer"):
        directory = ROOT / "extensions" / directory_name
        manifest = json.loads((directory / "extension.json").read_text(encoding="utf-8"))
        result.append(Extension(directory, manifest["name"], manifest["publisher"], manifest["version"]))
    return tuple(result)


def source_fingerprint(extension: Extension) -> dict[str, str]:
    """Hash inputs that can change either bundled backend or compiled frontend."""
    paths = [extension.directory / "extension.json", extension.directory / "requirements.txt"]
    for directory_name in ("backend/src", "frontend/src"):
        paths.extend(path for path in (extension.directory / directory_name).rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
    paths.extend(path for path in (extension.directory / "frontend").glob("*") if path.is_file())
    paths.extend(path for path in (extension.directory / "backend").glob("*") if path.is_file())
    return {path.relative_to(extension.directory).as_posix(): sha256_file(path) for path in sorted(set(paths)) if path.is_file()}


def bundle_problems(extension: Extension) -> list[str]:
    if not extension.bundle.exists():
        return [f"{extension.bundle.name} is missing"]
    if not extension.provenance.exists():
        return [f"{extension.provenance.name} is missing; rebuild the bundle"]
    try:
        provenance = json.loads(extension.provenance.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"{extension.provenance.name} is invalid"]
    problems = []
    if provenance.get("bundle_sha256") != sha256_file(extension.bundle):
        problems.append(f"{extension.bundle.name} differs from its build record")
    previous = provenance.get("sources")
    current = source_fingerprint(extension)
    if not isinstance(previous, dict):
        problems.append(f"{extension.provenance.name} has no source hashes")
    else:
        problems.extend(f"{extension.name}: source changed: {name}" for name in sorted(current.keys() | previous.keys()) if current.get(name) != previous.get(name))
    try:
        bundle = zipfile.ZipFile(extension.bundle)
    except zipfile.BadZipFile:
        return problems + [f"{extension.name}: bundle is not a valid zip archive"]
    with bundle:
        bundled_names = set(bundle.namelist())
        for source in (extension.directory / "backend" / "src").rglob("*"):
            if source.is_file() and source.suffix in {".py", ".json", ".md"} and "__pycache__" not in source.parts:
                name = f"backend/src/{source.relative_to(extension.directory / 'backend' / 'src').as_posix()}"
                if name not in bundled_names or bundle.read(name) != source.read_bytes():
                    problems.append(f"{extension.name}: bundled backend differs: {name}")
        frontend_names = [name for name in bundled_names if name.startswith("frontend/dist/") and not name.endswith("/")]
        if not frontend_names:
            problems.append(f"{extension.name}: bundle has no frontend assets")
        for name in frontend_names:
            staged = extension.directory / "dist" / name
            if not staged.is_file() or staged.read_bytes() != bundle.read(name):
                problems.append(f"{extension.name}: staged frontend differs: {name}")
    return problems


def step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr, flush=True)
    sys.exit(1)


def resolve_command(command: list[str]) -> list[str]:
    """Resolve the executable through PATH and PATHEXT, so `npm` finds `npm.cmd` on Windows."""
    executable = shutil.which(command[0])
    return [executable, *command[1:]] if executable else command


def run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    check: bool = True,
    capture: bool = False,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    print(f"$ {' '.join(command)}", flush=True)
    result = subprocess.run(
        resolve_command(command),
        check=False,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=stdin,
        capture_output=capture,
    )
    if check and result.returncode != 0:
        if capture:
            print(result.stdout, result.stderr, sep="\n", file=sys.stderr)
        fail(f"command exited with {result.returncode}: {' '.join(command)}")
    return result


def compose(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    return run(["docker", "compose", *args], **kwargs)


def require_superset_running() -> None:
    result = compose("ps", "--status", "running", "--services", capture=True)
    if SUPERSET_SERVICE not in result.stdout.split():
        fail("the superset service is not running; start it with `docker compose up -d`")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def container_sha256(path: str) -> str | None:
    result = compose("exec", "-T", SUPERSET_SERVICE, "sh", "-c", 'if [ -f "$1" ]; then sha256sum "$1"; else printf "ABSENT\\n"; fi', "sh", path, capture=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"could not inspect installed bundle: {path}")
    output = result.stdout.strip()
    if output == "ABSENT":
        return None
    digest = output.split()[0] if output else ""
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise RuntimeError(f"invalid installed bundle hash: {path}")
    return digest


def wait_for_health(timeout: float = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{SUPERSET_URL}/health", timeout=5) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(3)
    fail(f"Superset did not report healthy at {SUPERSET_URL}/health within {timeout:.0f}s")
