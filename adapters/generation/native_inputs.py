"""Stable native source, product and private-record reads owned by the consumer."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat

from native_protocol import encoded, require
from otelc_capture import strict_json

MAX_FILE = 256 * 1024 * 1024
MAX_RECORD = 16 * 1024 * 1024


class PublicationPending(FileNotFoundError):
    """The SDK has linked a complete record but has not removed its staging link."""


def signature(info: os.stat_result) -> tuple:
    """Access time is excluded; replacement, write and link changes are retained."""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


@dataclass(frozen=True)
class File:
    """Only immutable primitive facts are held; returned identity dictionaries are new."""

    path: Path
    resolved: Path
    sha256: str
    size: int
    facts: tuple
    path_facts: tuple
    symlink: str | None
    maximum: int
    allow_links: bool
    private: bool
    content: bytes | None

    def identity(self) -> dict:
        """Public native file identity preserves a selected tool's leaf symlink."""
        value = {'path': str(self.path), 'resolved_path': str(self.resolved),
                 'sha256': self.sha256, 'size': self.size}
        if self.symlink is not None:
            value['symlink'] = self.symlink
        return value

    def tool_identity(self) -> dict:
        """LLVM toolchain records use the actual resolved tool and three fields."""
        return {'path': str(self.resolved), 'sha256': self.sha256, 'size': self.size}

    def gate_identity(self) -> dict:
        """The public gate/build binding also retains original inode and write facts."""
        return {**self.identity(), 'device': self.facts[0], 'inode': self.facts[1],
                'mode': self.facts[2], 'uid': self.facts[3], 'gid': self.facts[4],
                'mtime_ns': self.facts[6], 'ctime_ns': self.facts[7], 'links': self.facts[8]}

    def verify(self) -> None:
        """Recheck original bytes, target facts and any selected alias."""
        require(capture(self.path, maximum=self.maximum, allow_links=self.allow_links,
                        private=self.private, keep=self.content is not None) == self,
                'original native file bytes or filesystem facts changed: ' + str(self.path))


def capture(path: Path, *, maximum: int = MAX_FILE, allow_links: bool = False,
            private: bool = False, keep: bool = False) -> File:
    """Read a bounded regular file without waiting on FIFOs or following a late swap."""
    require(isinstance(path, Path), 'native input requires a Path')
    require(path.is_absolute() and '..' not in path.parts
            and type(maximum) is int and 1 <= maximum <= MAX_FILE, 'invalid native input path or byte budget')
    resolved = path.resolve(strict=True)
    original = path.lstat()
    require(allow_links or resolved == path and not stat.S_ISLNK(original.st_mode),
            'native input must have a canonical ordinary path')
    symlink = os.readlink(path) if stat.S_ISLNK(original.st_mode) else None
    descriptor = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_size <= maximum, 'special or oversized native input')
        if private:
            require(not allow_links and before.st_uid == os.getuid() and before.st_nlink == 1
                    and stat.S_IMODE(before.st_mode) == 0o600, 'native record requires an owned mode0600 single-link file')
        digest, size, blocks = hashlib.sha256(), 0, []
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            while block := stream.read(1024 * 1024):
                size += len(block)
                require(size <= maximum, 'native input grew beyond its byte budget')
                digest.update(block)
                if keep:
                    blocks.append(block)
        require(size == before.st_size and path.resolve(strict=True) == resolved
                and signature(before) == signature(os.fstat(descriptor)) == signature(resolved.lstat())
                and signature(original) == signature(path.lstat())
                and (os.readlink(path) if path.is_symlink() else None) == symlink,
                'native input changed while reading')
    finally:
        os.close(descriptor)
    return File(path, resolved, digest.hexdigest(), size, signature(before), signature(original),
                symlink, maximum, allow_links, private, b''.join(blocks) if keep else None)


@dataclass(frozen=True)
class Record:
    """Decoded values are fresh copies, tied to the original raw record and file facts."""

    file: File

    def value(self) -> dict:
        """Return a fresh finite JSON object without mutable aliases."""
        value = strict_json(self.file.content)
        require(type(value) is dict, 'native metadata must be a JSON object')
        encoded(value)
        return value

    def verify(self) -> None:
        """Keep decoded values bound to the original stable read."""
        self.file.verify()
        self.value()


def read(path: Path, *, private: bool = False, maximum: int = MAX_RECORD) -> Record:
    """Decode one stable ordinary JSON record without changing its evidence."""
    result = Record(capture(path, maximum=maximum, private=private, keep=True))
    result.value()
    return result


def published(path: Path, *, maximum: int = MAX_RECORD) -> Record:
    """Poll private SDK publications without capturing temporary two-link facts."""
    require(isinstance(path, Path) and path.is_absolute()
            and type(maximum) is int and 1 <= maximum <= MAX_FILE, 'invalid native publication read')
    info = path.lstat()
    if (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_size <= maximum and info.st_nlink == 2):
        raise PublicationPending('native metadata publication is pending')
    return read(path, private=True, maximum=maximum)


def directory(path: Path) -> tuple:
    """A private runtime keeps its original canonical directory and permissions."""
    require(path.is_absolute() and path.resolve(strict=True) == path, 'native runtime must be canonical')
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
            'native runtime must be an owned mode0700 directory')
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid
