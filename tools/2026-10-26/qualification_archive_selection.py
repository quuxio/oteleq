"""Bind a complete retained selection directly to a caller-pinned original ZIP."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile


SUFFIXES = {'.json', '.protobuf', '.observation', '.c', '.cpp', '.h', '.hpp',
            '.toml', '.exit', '.py', '.tar', '.txt'}


def sha256(path: Path) -> str:
    """Hash a complete ordinary file without materialising its contents."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(condition: bool, reason: str) -> None:
    """Reject incomplete or inconsistent retained archive evidence."""
    if not condition:
        raise ValueError(reason)


def verify(index: dict, expected_archive_sha256: str, *, namespace: str) -> dict:
    """Stream every fixed selected member against both its index and byte copy.

    The caller supplies the original GitHub digest independently of the local
    index. Historical runner metadata is not restored or recertified here.
    """
    require(namespace in ('native-lifetime', 'native-metric'), 'unknown archive namespace')
    require(type(expected_archive_sha256) is str and
            re.fullmatch('[a-f0-9]{64}', expected_archive_sha256) is not None,
            'missing independent original archive digest')
    archive, selected = Path(index['archive']), Path(index['root'])
    require(all(type(index[key]) is int and index[key] >= 0 for key in
                ('archive_members', 'archive_directories', 'selected_members', 'selected_bytes')),
            'invalid archive selection denominator types')
    require(sha256(archive) == expected_archive_sha256 == index['archive_sha256'],
            'original archive differs from the independently supplied digest')
    require(selected.is_absolute() and selected.resolve(strict=True) == selected
            and selected.is_dir() and not selected.is_symlink(), 'noncanonical retained root')
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        require(0 < len(entries) <= 100000, 'excessive archive member denominator')
        require(len({row.filename for row in entries}) == len(entries), 'duplicate ZIP members')
        require(len(entries) == index['archive_members'], 'changed archive member denominator')
        require(sum(row.is_dir() for row in entries) == index['archive_directories'],
                'changed archive directory denominator')
        for row in entries:
            path = PurePosixPath(row.filename)
            require(not path.is_absolute() and '..' not in path.parts and
                    row.filename.rstrip('/') == path.as_posix() and '\\' not in row.filename,
                    'unsafe or noncanonical archive member')
            require(path.parts[0] in (namespace + '-evidence', namespace + '-sdk'),
                    'foreign archive root')
            require(not stat.S_ISLNK(row.external_attr >> 16) and not row.flag_bits & 1,
                    'linked or encrypted ZIP member')
        wanted = {row.filename: row for row in entries if not row.is_dir() and
                  (PurePosixPath(row.filename).suffix in SUFFIXES or
                   PurePosixPath(row.filename).name == 'observation')}
        require(set(wanted) == set(index['files']), 'incomplete or extra retained selection')
        total = sum(row.file_size for row in wanted.values())
        require(0 < total <= 512 * 1024**2 and len(wanted) <= 50000,
                'excessive selected evidence')
        require(index['selected_members'] == len(wanted) and index['selected_bytes'] == total,
                'changed selected evidence denominator')
        for name, row in wanted.items():
            fact = index['files'][name]
            require(0 <= row.file_size <= 64 * 1024**2 and
                    type(fact['bytes']) is int and fact['bytes'] == row.file_size,
                    'changed selected member size')
            with bundle.open(row) as stream:
                original_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
            require(original_hash == fact['sha256'], 'selected index differs from original ZIP member')
            copy = selected / name
            require(copy.resolve(strict=True) == copy and copy.is_file() and not copy.is_symlink(),
                    'linked or missing retained member')
            require(copy.stat().st_size == row.file_size and sha256(copy) == original_hash,
                    'retained copy differs from original ZIP member')
    require(sha256(archive) == expected_archive_sha256, 'original archive changed during verification')
    return {'original_archive_sha256': expected_archive_sha256,
            'archive_members': len(entries), 'selected_members_streamed': len(wanted),
            'selected_bytes_streamed': total,
            'scope': 'Complete fixed selection streamed from caller-pinned ZIP and matched to index plus retained byte copies; no historical stat/kernel recertification.'}
