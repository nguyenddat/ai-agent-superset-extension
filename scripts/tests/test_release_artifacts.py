import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common


def test_provenance_detects_backend_and_frontend_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "ROOT", tmp_path)
    directory = tmp_path / "extensions" / "ai-agents"
    (directory / "backend" / "src").mkdir(parents=True)
    (directory / "frontend" / "src").mkdir(parents=True)
    (directory / "extension.json").write_text('{}', encoding="utf-8")
    backend = directory / "backend" / "src" / "entrypoint.py"
    frontend = directory / "frontend" / "src" / "App.tsx"
    backend.write_text("value = 1", encoding="utf-8")
    frontend.write_text("export const App = 1", encoding="utf-8")
    extension = _common.Extension(directory, "superset-ai-agent", "text-to-bi", "0.1.0")
    staged = directory / "dist" / "frontend" / "dist" / "main.js"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"compiled")
    with zipfile.ZipFile(extension.bundle, "w") as bundle:
        bundle.write(backend, "backend/src/entrypoint.py")
        bundle.write(staged, "frontend/dist/main.js")
    extension.provenance.write_text(
        json.dumps({
            "bundle_sha256": _common.sha256_file(extension.bundle),
            "sources": _common.source_fingerprint(extension),
        }),
        encoding="utf-8",
    )

    assert _common.bundle_problems(extension) == []
    backend.write_text("value = 2", encoding="utf-8")
    frontend.write_text("export const App = 2", encoding="utf-8")
    problems = _common.bundle_problems(extension)
    assert any("entrypoint.py" in problem for problem in problems)
    assert any("App.tsx" in problem for problem in problems)


def test_a_backend_only_extension_needs_no_frontend_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "ROOT", tmp_path)
    directory = tmp_path / "extensions" / "text-to-bi"
    (directory / "backend" / "src").mkdir(parents=True)
    (directory / "extension.json").write_text('{}', encoding="utf-8")
    backend = directory / "backend" / "src" / "entrypoint.py"
    backend.write_text("value = 1", encoding="utf-8")
    extension = _common.Extension(directory, "superset-text-to-bi", "text-to-bi", "0.1.0")
    with zipfile.ZipFile(extension.bundle, "w") as bundle:
        bundle.write(backend, "backend/src/entrypoint.py")
    extension.provenance.write_text(
        json.dumps({
            "bundle_sha256": _common.sha256_file(extension.bundle),
            "sources": _common.source_fingerprint(extension),
        }),
        encoding="utf-8",
    )

    assert _common.bundle_problems(extension) == []
    (directory / "frontend").mkdir()
    assert _common.bundle_problems(extension) == ["superset-text-to-bi: bundle has no frontend assets"]


def test_text_to_bi_is_released_with_the_other_extensions():
    assert [extension.name for extension in _common.extensions()][-1] == "superset-text-to-bi"


def test_provenance_detects_replaced_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "ROOT", tmp_path)
    directory = tmp_path / "extensions" / "semantic-layer"
    directory.mkdir(parents=True)
    (directory / "extension.json").write_text('{}', encoding="utf-8")
    extension = _common.Extension(directory, "superset-semantic-layer", "text-to-bi", "0.1.0")
    extension.bundle.write_bytes(b"new bundle")
    extension.provenance.write_text(
        json.dumps({"bundle_sha256": "old hash", "sources": _common.source_fingerprint(extension)}), encoding="utf-8",
    )

    assert any("differs from its build record" in problem for problem in _common.bundle_problems(extension))
