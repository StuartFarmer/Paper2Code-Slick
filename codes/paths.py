"""Confine generated filenames to their controller-owned root."""

from pathlib import Path, PurePosixPath


def output_path(root: Path, filename: str) -> Path:
    """Confine model-supplied paths, including existing symlinks, to the output root."""
    relative = PurePosixPath(filename)
    if (
        not filename
        or relative.is_absolute()
        or "\\" in filename
        or any(part in ("", ".", "..") or part.startswith(".") for part in filename.split("/"))
    ):
        raise ValueError(f"Unsafe generated filename: {filename!r}")
    target = root / filename
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Generated filename escapes output directory: {filename!r}")
    current = target
    while current != root:
        if current.is_symlink():
            raise ValueError(f"Generated filename follows a symlink: {filename!r}")
        current = current.parent
    return target
