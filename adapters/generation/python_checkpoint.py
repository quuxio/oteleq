# Generated observer boilerplate is MIT licensed; see GENERATED-LICENSE.txt.
"""Yield one private Python worker boundary to its external test host."""

import os
from pathlib import Path
import stat
import time

ROOT_ENV = "OTELEQ_PYTHON_CONTROL_ROOT"
TOKEN_ENV = "OTELEQ_PYTHON_CONTROL_TOKEN"


def read_resume(path: Path, message: bytes) -> bool:
    """Refuse linked, non-private, incomplete or substituted acknowledgements."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return False
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size != len(message) or os.read(descriptor, len(message) + 1) != message):
            raise ValueError("invalid host control acknowledgement")
        after = path.lstat()
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns):
            raise ValueError("host control acknowledgement changed")
        return True
    finally:
        os.close(descriptor)


def checkpoint(phase: str) -> None:
    """Publish a complete boundary, then yield the GIL while the host controls SDKs.

    The external process monitor owns the common deadline and kills its entire
    group if a checkpoint is never released. Neither target code nor its output
    carries the rendezvous protocol.
    """
    suffix = phase.split("-", 1) if type(phase) is str else []
    if phase != "finish" and not (len(suffix) == 2 and suffix[0] in ("before", "after")
            and suffix[1].isdigit() and str(int(suffix[1])) == suffix[1] and 0 <= int(suffix[1]) < 32):
        raise ValueError("invalid Python checkpoint phase")
    root = Path(os.environ[ROOT_ENV])
    token = os.environ[TOKEN_ENV]
    metadata = root.lstat()
    if (not root.is_absolute() or root.resolve(strict=True) != root
            or not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700 or len(token) != 32
            or any(character not in "0123456789abcdef" for character in token)):
        raise ValueError("invalid Python checkpoint bindings")
    message = (token + " " + phase + "\n").encode("ascii")
    temporary = root / (phase + ".tmp")
    ready = root / (phase + ".ready")
    with temporary.open("xb") as stream:
        temporary.chmod(0o600)
        stream.write(message)
    # An existing boundary is an error, including an existing symbolic link.
    os.link(temporary, ready, follow_symlinks=False)
    temporary.unlink()
    while not read_resume(root / (phase + ".resume"), message):
        time.sleep(.001)
