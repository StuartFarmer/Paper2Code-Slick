import json
from pathlib import Path

import pytest

from eval.run import snapshot_baseline


def test_baseline_snapshot_excludes_outputs_and_secrets(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in [
        "codes/workflow.py",
        "codes/prompts/repair.j2",
        "pyproject.toml",
        "uv.lock",
        "requirements.txt",
        ".env",
        "outputs/result.py",
        "run.log",
    ]:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    first = snapshot_baseline(tmp_path / "first", source=source)
    assert set(first) == {
        "codes/workflow.py",
        "codes/prompts/repair.j2",
        "pyproject.toml",
        "uv.lock",
        "requirements.txt",
    }
    assert (tmp_path / "first/codes/prompts/repair.j2").read_text() == "codes/prompts/repair.j2"
    (source / "codes/prompts/repair.j2").write_text("changed")
    second = snapshot_baseline(tmp_path / "second", source=source)
    assert first["codes/prompts/repair.j2"] != second["codes/prompts/repair.j2"]
    assert json.loads((tmp_path / "first/manifest.json").read_text())["files"] == first
    with pytest.raises(FileExistsError):
        snapshot_baseline(tmp_path / "first", source=source)


def test_snapshot_rejects_symlinked_source(tmp_path):
    source = tmp_path / "source"
    (source / "codes").mkdir(parents=True)
    (source / "codes/leak.py").symlink_to(Path(__file__))
    with pytest.raises(ValueError, match="symlink"):
        snapshot_baseline(tmp_path / "copy", source=source)
