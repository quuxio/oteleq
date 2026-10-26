"""Keep archive operations inside explicitly designated qualification storage."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile


def storage_roots() -> set[Path]:
    """Select storage independently of CLI paths; never infer authority from a path argument."""
    roots = {Path(tempfile.gettempdir()).resolve()}
    for name in ("RUNNER_TEMP", "OTELEQ_QUALIFICATION_HOME"):
        if value := os.environ.get(name):
            folder = Path(value).resolve(strict=True)
            if not folder.is_dir() or folder == Path.home() or folder == Path("/"):
                raise ValueError(name + " must designate a dedicated existing storage directory")
            roots.add(folder)
    # The dedicated local workspace is also the maintained qualification home.
    # This comes from the running checkout, never from an archive/CLI record.
    checkout = Path(__file__).resolve().parents[1]
    roots.update(parent for parent in checkout.parents
                 if parent.name == "oteleq-qualification")
    sibling = checkout.parent / "oteleq-qualification"
    if sibling.is_dir():
        roots.add(sibling.resolve(strict=True))
    return roots - {Path.home().resolve(), Path("/")}


def checked(path: Path, *, new: bool = False) -> Path:
    """Resolve parents and require a strict descendant of a fixed storage root."""
    if not path.is_absolute():
        raise ValueError("qualification storage paths must be absolute")
    candidate = path.parent.resolve(strict=True) / path.name
    if path.name in (".", "..") or not any(
            candidate != root and candidate.is_relative_to(root)
            for root in storage_roots()):
        raise ValueError("path is outside qualification storage; configure OTELEQ_QUALIFICATION_HOME")
    if not new and candidate.is_symlink():
        raise ValueError("qualification storage path is a symbolic link")
    return candidate
