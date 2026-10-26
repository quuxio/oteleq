"""Stage one bounded ZIP selection for existing strict filesystem auditors."""

from contextlib import contextmanager
from collections.abc import Callable
import ctypes
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from typing import Iterator
import zipfile

import qualification_archive_selection as selection

RESERVE_BYTES = 512 * 1024**2
MAX_MEMBERS = 100000
MAX_SELECTED_BYTES = 512 * 1024**2
MAX_MEMBER_BYTES = 64 * 1024**2


def require(condition: bool, reason: str) -> None:
    """Refuse unavailable, unsafe or over-budget working sets."""
    if not condition:
        raise ValueError(reason)


def facts(path: Path) -> tuple:
    """Reads can change access time; retain the original identity and write facts."""
    row = path.lstat()
    return (row.st_dev, row.st_ino, row.st_mode, row.st_size, row.st_mtime_ns,
            row.st_ctime_ns, row.st_uid, row.st_gid, row.st_nlink)


def wanted(bundle: zipfile.ZipFile, namespace: str) -> tuple[list, list]:
    """Select the same complete evidence denominator as the original verifier."""
    entries = bundle.infolist()
    require(0 < len(entries) <= MAX_MEMBERS and
            len({row.filename for row in entries}) == len(entries),
            'excessive or duplicate ZIP members')
    for row in entries:
        name = PurePosixPath(row.filename)
        require(bool(name.parts) and not name.is_absolute() and '..' not in name.parts
                and row.filename.rstrip('/') == name.as_posix() and '\\' not in row.filename
                and name.parts[0] in (namespace + '-evidence', namespace + '-sdk'),
                'unsafe, noncanonical or foreign ZIP member')
        require(not stat.S_ISLNK(row.external_attr >> 16) and not row.flag_bits & 1,
                'linked or encrypted ZIP member')
    chosen = [row for row in entries if not row.is_dir() and
              (PurePosixPath(row.filename).suffix in selection.SUFFIXES or
               PurePosixPath(row.filename).name == 'observation')]
    require(0 < len(chosen) <= 50000 and
            0 < sum(row.file_size for row in chosen) <= MAX_SELECTED_BYTES and
            all(0 <= row.file_size <= MAX_MEMBER_BYTES for row in chosen),
            'empty or excessive temporary evidence selection')
    return entries, chosen


def copy_on_write() -> Callable[[Path, Path], None] | None:
    """Use the macOS clone operation; ordinary files remain the other-host path."""
    if sys.platform != 'darwin':
        return None
    library = ctypes.CDLL(None, use_errno=True)
    clone = getattr(library, 'clonefile', None)
    if clone is None:
        return None
    clone.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    clone.restype = ctypes.c_int

    def create(source: Path, target: Path) -> None:
        if clone(os.fsencode(source), os.fsencode(target), 0) != 0:
            number = ctypes.get_errno()
            raise OSError(number, os.strerror(number), str(target))

    return create


def space_required(parent: Path, rows: list, hashes: dict[str, str], cloned: bool) -> int:
    """Require payload capacity; enforce the hard reserve before every write.

    Copy-on-write metadata allocation is filesystem-specific. A pessimistic
    inode/directory estimate can reject a working set that fits. Per-file and
    per-chunk guards stop and clean the working set if actual allocation cannot
    preserve the reserve. The extra 16 MiB covers small audit outputs.
    """
    sizes = [size for _, size in {(hashes[row.filename], row.file_size) for row in rows}] if cloned else [row.file_size for row in rows]
    return sum(sizes) + 16 * 1024**2


@contextmanager
def staged(archive: Path, expected_sha256: str, *, namespace: str,
           directory: Path | None = None) -> Iterator[dict]:
    """Retain the original ZIP and remove only this audit's temporary working set.

    This is offline byte validation, never a compiler/SDK/application build.
    Existing build floors do not change. Historical runner facts remain data.
    """
    require(namespace in ('native-lifetime', 'native-metric'), 'unknown archive namespace')
    require(type(expected_sha256) is str and
            re.fullmatch('[a-f0-9]{64}', expected_sha256) is not None,
            'missing independent original archive digest')
    require(isinstance(archive, Path) and archive.is_absolute() and
            archive.resolve(strict=True) == archive and archive.is_file()
            and not archive.is_symlink(), 'noncanonical original archive')
    original = facts(archive)
    require(selection.sha256(archive) == expected_sha256, 'original ZIP differs from independent digest')
    parent = Path(tempfile.gettempdir()).resolve(strict=True) if directory is None else directory
    require(isinstance(parent, Path) and parent.is_absolute() and parent.resolve(strict=True) == parent
            and parent.is_dir() and not parent.is_symlink(), 'noncanonical temporary parent')
    with zipfile.ZipFile(archive) as bundle:
        entries, chosen = wanted(bundle, namespace)
        hashes = {}
        for row in chosen:
            with bundle.open(row) as source:
                hashes[row.filename] = hashlib.file_digest(source, 'sha256').hexdigest()
        clone = copy_on_write()
        require(shutil.disk_usage(parent).free >= RESERVE_BYTES + space_required(parent, chosen, hashes, clone is not None),
                'insufficient space for bounded temporary selection')
        with tempfile.TemporaryDirectory(prefix='oteleq-archive-audit-', dir=parent) as temporary:
            root = Path(temporary).resolve(strict=True)
            root.chmod(0o700)
            files = {}
            contents = {}
            for row in chosen:
                require(shutil.disk_usage(parent).free >= RESERVE_BYTES + 1024**2,
                        'temporary selection reached storage reserve')
                target = root / row.filename
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                key = hashes[row.filename], row.file_size
                if key in contents and clone is not None:
                    # Clones have separate inodes and one link, including private
                    # publications. Their shared extents never link source inputs.
                    require(shutil.disk_usage(parent).free >= RESERVE_BYTES + 4096,
                            'temporary selection reached storage reserve')
                    clone(contents[key], target)
                    require(target.stat().st_nlink == 1 and
                            target.stat().st_ino != contents[key].stat().st_ino,
                            'temporary clone is not an independent ordinary file')
                    files[row.filename] = {'sha256': key[0], 'bytes': row.file_size}
                    continue
                digest = hashlib.sha256()
                size = 0
                with bundle.open(row) as source, target.open('xb') as output:
                    target.chmod(0o600)
                    while data := source.read(1024**2):
                        require(shutil.disk_usage(parent).free >= RESERVE_BYTES + len(data) + 1024**2,
                                'temporary selection reached storage reserve')
                        size += len(data)
                        require(size <= row.file_size, 'ZIP member exceeded its declared size')
                        output.write(data)
                        digest.update(data)
                require(size == row.file_size, 'incomplete ZIP member')
                require(digest.hexdigest() == hashes[row.filename], 'ZIP member changed between reads')
                files[row.filename] = {'sha256': digest.hexdigest(), 'bytes': size}
                contents[key] = target
            require(shutil.disk_usage(parent).free >= RESERVE_BYTES,
                    'temporary selection reached storage reserve')
            index = {'archive': str(archive), 'archive_sha256': expected_sha256,
                     'archive_members': len(entries),
                     'archive_directories': sum(row.is_dir() for row in entries),
                     'selected_members': len(files),
                     'selected_bytes': sum(row['bytes'] for row in files.values()),
                     'root': str(root), 'files': files,
                     'working_storage': {'unique_contents': len(contents),
                         'unique_content_bytes': sum(size for _, size in contents),
                         'kind': 'Independent temporary copy-on-write files' if clone is not None else 'Independent ordinary temporary files'},
                     'copy_lifetime': 'Temporary for this audit; original ZIP is the persistent byte source',
                     'scope': 'Original bytes only; no historical runner stat or kernel recertification'}

            def verify() -> None:
                require(facts(archive) == original, 'original ZIP identity or write facts changed')
                selection.verify(index, expected_sha256, namespace=namespace)

            verify()
            try:
                yield index
            except BaseException as error:
                try:
                    verify()
                except Exception as preservation_error:
                    error.add_note('temporary evidence preservation also failed: ' + str(preservation_error))
                raise
            else:
                verify()
