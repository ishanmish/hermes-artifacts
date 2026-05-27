import json
from pathlib import Path

import pytest

from scripts import manage_artifacts


@pytest.fixture
def artifact_repo(tmp_path, monkeypatch):
    root = tmp_path
    manifest = root / "artifacts.json"
    (root / "reports").mkdir()
    (root / "reports" / "keep.html").write_text("keep", encoding="utf-8")
    (root / "reports" / "delete-me.html").write_text("delete", encoding="utf-8")
    manifest.write_text(
        json.dumps(
            [
                {"id": "keep", "title": "Keep", "path": "reports/keep.html"},
                {"id": "delete-me", "title": "Delete Me", "path": "reports/delete-me.html"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(manage_artifacts, "ROOT", root)
    monkeypatch.setattr(manage_artifacts, "MANIFEST", manifest)
    return root, manifest


def test_delete_artifact_removes_manifest_entry_and_file(artifact_repo):
    root, manifest = artifact_repo

    removed = manage_artifacts.delete_artifact("delete-me")

    assert removed == {"id": "delete-me", "title": "Delete Me", "path": "reports/delete-me.html"}
    assert json.loads(manifest.read_text(encoding="utf-8")) == [
        {"id": "keep", "title": "Keep", "path": "reports/keep.html"}
    ]
    assert not (root / "reports" / "delete-me.html").exists()
    assert (root / "reports" / "keep.html").exists()


def test_delete_artifact_dry_run_does_not_modify_manifest_or_file(artifact_repo):
    root, manifest = artifact_repo
    before = manifest.read_text(encoding="utf-8")

    removed = manage_artifacts.delete_artifact("delete-me", dry_run=True)

    assert removed["id"] == "delete-me"
    assert manifest.read_text(encoding="utf-8") == before
    assert (root / "reports" / "delete-me.html").exists()


def test_delete_artifact_rejects_missing_id(artifact_repo):
    with pytest.raises(KeyError, match="Artifact not found"):
        manage_artifacts.delete_artifact("missing")
