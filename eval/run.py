"""Freeze an executable baseline without copying outputs or credentials."""

import hashlib
import json
import subprocess
from pathlib import Path


def snapshot_baseline(destination: Path, *, source: Path | None = None) -> dict[str, str]:
    source = source or Path(__file__).resolve().parents[1]
    names = {"pyproject.toml", "uv.lock", "requirements.txt", ".python-version"}
    names.update(
        str(path.relative_to(source))
        for pattern in ("*.py", "*.j2")
        for path in (source / "codes").rglob(pattern)
    )
    contents = {}
    for name in sorted(names):
        path = source / name
        if any(part.is_symlink() for part in [path, *path.parents] if part != source.parent):
            raise ValueError(f"Cannot snapshot symlink: {name}")
        if path.is_file():
            contents[name] = path.read_bytes()
    revision = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True
    )
    files = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in contents.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {
        "revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "files": files,
        "experimental_changes": ["typed design/task JSON healer"],
        "source_hash": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return files
