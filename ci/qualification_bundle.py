"""Stream complete cold qualification trees into verified compressed bundles."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile
from typing import BinaryIO, Iterator

from ci import qualification_attributes as attributes
from ci.qualification_paths import checked

CHUNK = 1024 * 1024
DATA = "qualification.tar.gz"
INDEX = "files.jsonl.gz"
RECEIPT = "receipt.json"


@contextmanager
def lease(store: Path, *, exclusive: bool = False) -> Iterator[None]:
    """Coordinate retained readers and retirement without waiting on an active reader."""
    store = checked(store)
    value = store.stat()
    require(value.st_uid == os.getuid() and stat.S_IMODE(value.st_mode) == 0o700,
            "bundle must be an owned private directory")
    descriptor = os.open(store / "bundle.lock", os.O_WRONLY | os.O_CREAT
                         | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        value = os.fstat(descriptor)
        require(stat.S_ISREG(value.st_mode) and value.st_uid == os.getuid()
                and value.st_nlink == 1, "unsafe bundle lease")
        kind = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(descriptor, kind | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def require(condition: bool, message: str) -> None:
    """Refuse without relying on assertions or changing original evidence."""
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    """Hash a file without retaining its payload in memory."""
    path = checked(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "expected a regular bundle file")
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value: object) -> bytes:
    """Use a stable, finite JSON encoding for records."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      allow_nan=False, separators=(",", ":")).encode() + b"\n"


def entries(root: Path, name: str = ".") -> Iterator[tuple[str, Path]]:
    """Visit every directory, regular file and link; never follow a link."""
    path = root if name == "." else root / name
    yield name, path
    if stat.S_ISDIR(path.lstat().st_mode):
        for child in sorted(path.iterdir(), key=lambda p: p.name):
            relative = child.name if name == "." else name + "/" + child.name
            yield from entries(root, relative)


def identity(path: Path) -> list[int]:
    """Retain original physical facts as historical data, excluding access time."""
    value = path.lstat()
    return [value.st_dev, value.st_ino, value.st_mode, value.st_uid,
            value.st_gid, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_nlink, getattr(value, "st_flags", 0)]


def describe(name: str, path: Path) -> dict:
    """Capture bytes and metadata of one stable original node."""
    before = identity(path)
    mode = before[2]
    require(before[3] == os.getuid(), "qualification node is not owned: " + name)
    require(not mode & 0o7000 and not before[-1],
            "unsupported special permissions or flags: " + name)
    if stat.S_ISREG(mode):
        kind, content, link = "file", digest(path), None
    elif stat.S_ISDIR(mode):
        kind, content, link = "directory", None, None
    elif stat.S_ISLNK(mode):
        kind, content, link = "symlink", None, os.readlink(path)
    else:
        raise ValueError("active/special qualification node: " + name)
    values = attributes.read(path)
    require(identity(path) == before, "qualification changed while reading: " + name)
    return {"path": name, "kind": kind,
            "size": before[5] if kind == "file" else 0,
            "mode": stat.S_IMODE(mode), "uid": before[3], "gid": before[4],
            "mtime_ns": before[6], "sha256": content, "link": link,
            "xattrs": values, "original_identity": before}


def member_for(row: dict) -> tarfile.TarInfo:
    """Normalise archive headers; original metadata stays in the compressed index."""
    member = tarfile.TarInfo(row["path"])
    if row["kind"] == "file":
        member.size, member.mode = row["size"], 0o600
    elif row["kind"] == "directory":
        member.type, member.mode = tarfile.DIRTYPE, 0o700
    else:
        member.type, member.mode = tarfile.SYMTYPE, 0o777
        member.linkname = row["link"]
    return member


def _validate_attributes(values: object) -> None:
    require(type(values) is dict and len(values) <= 64, "invalid indexed attributes")
    size = 0
    for key, value in values.items():
        require(type(key) is str and type(value) is str
                and 0 < len(key) <= 510 and len(key) % 2 == len(value) % 2 == 0
                and all(c in "0123456789abcdef" for c in key + value)
                and b"\0" not in bytes.fromhex(key), "invalid attribute bytes")
        size += (len(key) + len(value)) // 2
    require(size <= 65536, "indexed attributes exceed budget")


def _validate_row(row: dict) -> None:
    require(type(row) is dict and set(row) == {
        "path", "kind", "size", "mode", "uid", "gid", "mtime_ns",
        "sha256", "link", "xattrs", "original_identity"}, "invalid index row")
    name = row["path"]
    require(type(name) is str and (name == "." or (
        name and not PurePosixPath(name).is_absolute()
        and ".." not in PurePosixPath(name).parts
        and PurePosixPath(name).as_posix() == name)), "unsafe indexed path")
    require(row["kind"] in ("file", "directory", "symlink")
            and type(row["size"]) is int and 0 <= row["size"] <= 2**40,
            "invalid indexed kind/size")
    require(all(type(row[key]) is int for key in ("mode", "uid", "gid", "mtime_ns"))
            and 0 <= row["mode"] <= 0o777 and row["uid"] == os.getuid()
            and 0 <= row["gid"] < 2**32 and 0 <= row["mtime_ns"] < 2**63,
            "invalid indexed metadata")
    require(type(row["original_identity"]) is list
            and len(row["original_identity"]) == 10
            and all(type(v) is int for v in row["original_identity"]),
            "invalid original physical facts")
    if row["kind"] == "file":
        require(type(row["sha256"]) is str and len(row["sha256"]) == 64
                and all(c in "0123456789abcdef" for c in row["sha256"])
                and row["link"] is None, "invalid file digest")
    else:
        require(row["sha256"] is None and row["size"] == 0
                and (type(row["link"]) is str if row["kind"] == "symlink"
                     else row["link"] is None), "invalid non-file index row")
    _validate_attributes(row["xattrs"])


def rows(stream: BinaryIO) -> Iterator[dict]:
    """Read bounded index lines without inflating the complete index to disk."""
    while line := stream.readline(262145):
        require(len(line) <= 262144, "oversized qualification index row")
        row = json.loads(line)
        _validate_row(row)
        yield row


def _verify_member(archive: tarfile.TarFile, row: dict) -> None:
    member = archive.next()
    expected = member_for(row)
    require(member is not None and member.name == row["path"]
            and member.type == expected.type and member.size == expected.size
            and member.mode == expected.mode and member.linkname == expected.linkname
            and member.uid == member.gid == member.mtime == 0
            and not member.uname and not member.gname and member.sparse is None
            and set(member.pax_headers) <= {"path", "linkpath"},
            "archive member differs: " + row["path"])
    if row["kind"] == "file":
        payload = archive.extractfile(member)
        require(payload is not None, "missing archive payload")
        with payload:
            require(hashlib.file_digest(payload, "sha256").hexdigest() == row["sha256"],
                    "archive payload differs: " + row["path"])
    archive.members.clear()


def _verify_members(index: BinaryIO, archive: tarfile.TarFile) -> tuple[int, int]:
    count = total = 0
    seen: dict[str, str] = {}
    for row in rows(index):
        name = row["path"]
        require(name not in seen, "duplicate indexed path")
        if not seen:
            require(name == "." and row["kind"] == "directory", "missing root directory")
        else:
            parent = PurePosixPath(name).parent.as_posix()
            require(seen.get(parent) == "directory", "missing or linked archive parent")
        seen[name] = row["kind"]
        _verify_member(archive, row)
        count += 1
        total += row["size"]
    require(archive.next() is None, "extra qualification archive member")
    tail = 0
    while chunk := archive.fileobj.read(CHUNK):
        tail += len(chunk)
        require(tail <= 10240 and not any(chunk), "unexpected archive trailer")
    return count, total


def authenticated(store: Path, expected: str) -> dict:
    """Authenticate the original fully verified representation without extracting it."""
    store = checked(store)
    require(digest(store / RECEIPT) == expected, "receipt SHA256 differs")
    receipt = json.loads((store / RECEIPT).read_text())
    require(type(receipt["schema_version"]) is int and receipt["schema_version"] == 1
            and receipt["kind"] == "oteleq.qualification.bundle", "unknown bundle schema")
    require(digest(store / DATA) == receipt["data_sha256"]
            and digest(store / INDEX) == receipt["index_sha256"], "bundle SHA256 differs")
    return receipt


def _verify(store: Path, expected: str) -> dict:
    receipt = authenticated(store, expected)
    with gzip.open(store / INDEX, "rb") as index, gzip.open(store / DATA, "rb") as data:
        with tarfile.open(fileobj=data, mode="r|") as archive:
            count, total = _verify_members(index, archive)
        require(data.read(1) == b"", "unexpected gzip suffix")
    require(count == receipt["entries"] and total == receipt["original_bytes"],
            "qualification denominator differs")
    return receipt


def verify(store: Path, expected: str) -> dict:
    """Lease and stream every member through both complete gzip trailers."""
    with lease(store):
        return _verify(store, expected)


def check_originals(root: Path, store: Path, *, closed_links: bool = False) -> None:
    """Recheck the complete original denominator and every original byte/metadata fact."""
    links: dict[tuple[int, int], list[int]] = {}
    with gzip.open(store / INDEX, "rb") as index:
        for actual, row in zip(entries(root), rows(index), strict=True):
            name, path = actual
            require(describe(name, path) == row, "original qualification changed: " + name)
            if row["kind"] == "file" and row["original_identity"][8] > 1:
                key = tuple(row["original_identity"][:2])
                counts = links.setdefault(key, [0, row["original_identity"][8]])
                counts[0] += 1
    require(not closed_links or all(found == total for found, total in links.values()),
            "raw removal would change a hardlink outside this qualification tree")


def _probe_node(path: Path, row: dict) -> None:
    if row["kind"] == "directory":
        path.mkdir(mode=0o700)
    elif row["kind"] == "symlink":
        os.symlink(row["link"], path)
    else:
        path.touch(mode=0o600)
    _metadata(path, row)
    value = path.lstat()
    require((stat.S_IMODE(value.st_mode), value.st_uid, value.st_gid,
             value.st_mtime_ns) == (row["mode"], row["uid"], row["gid"], row["mtime_ns"])
            and attributes.read(path) == row["xattrs"],
            "recorded metadata cannot be restored: " + row["path"])
    if row["kind"] == "directory":
        path.rmdir()
    else:
        path.unlink()


def prove_metadata(root: Path, store: Path) -> None:
    """Check each metadata class can be restored on the original output volume."""
    checked_metadata = set()
    with tempfile.TemporaryDirectory(prefix=".qualification-restore-", dir=root.parent) as temporary:
        path = Path(temporary) / "node"
        with gzip.open(store / INDEX, "rb") as index:
            for row in rows(index):
                signature = hashlib.sha256(canonical({key: row[key] for key in
                    ("kind", "mode", "uid", "gid", "xattrs")})).digest()
                if signature not in checked_metadata:
                    _probe_node(path, row)
                    checked_metadata.add(signature)


def pack(root: Path, store: Path, *, remove: bool = False) -> dict:
    """Compress all nodes, verify all bytes, then optionally retire the cold raw tree."""
    root, store = checked(root), checked(store, new=True)
    require(root.is_absolute() and root == root.resolve(strict=True)
            and root.is_dir() and not root.is_symlink(), "root must be a canonical directory")
    require(store.is_absolute() and store.parent == store.parent.resolve(strict=True)
            and not store.is_relative_to(root) and not root.is_relative_to(store),
            "bundle store must be new and outside the qualification tree")
    require(not Path.cwd().resolve().is_relative_to(root), "root contains the working checkout")
    require(not any(root.samefile(parent) for parent in
                    (store.parent, *store.parent.parents)),
            "bundle store physically overlaps the qualification tree")
    require(not any(root.samefile(parent) for parent in
                    (Path.cwd(), *Path.cwd().parents)),
            "qualification tree physically contains the working checkout")
    require(shutil.rmtree.avoids_symlink_attacks, "safe cold-tree removal is unsupported")
    store.mkdir(mode=0o700)
    count = total = 0
    with gzip.open(store / INDEX, "xb", compresslevel=6) as index, \
         tarfile.open(store / DATA, "x:gz", compresslevel=6,
                      format=tarfile.PAX_FORMAT) as archive:
        for name, path in entries(root):
            row = describe(name, path)
            member = member_for(row)
            if row["kind"] == "file":
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, "rb") as payload:
                    archive.addfile(member, payload)
            else:
                archive.addfile(member)
            require(identity(path) == row["original_identity"],
                    "qualification changed during compression: " + name)
            index.write(canonical(row))
            count += 1
            total += row["size"]
            archive.members.clear()
    receipt = {"schema_version": 1, "kind": "oteleq.qualification.bundle",
               "root": str(root), "entries": count, "original_bytes": total,
               "data_sha256": digest(store / DATA), "index_sha256": digest(store / INDEX),
               "compressed_bytes": sum((store / n).stat().st_size for n in (DATA, INDEX)),
               "restoration": "original bytes and metadata; inode/ctime/link facts remain historical"}
    (store / RECEIPT).write_bytes(canonical(receipt))
    expected = digest(store / RECEIPT)
    verify(store, expected)
    prove_metadata(root, store)
    check_originals(root, store, closed_links=remove)
    # Durably close all archive products before any original is unlinked.
    for name in (DATA, INDEX, RECEIPT):
        with (store / name).open("rb") as stream:
            os.fsync(stream.fileno())
    for folder in (store, store.parent):
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    if remove:
        shutil.rmtree(root)
    return {**receipt, "store": str(store), "receipt_sha256": expected,
            "raw_removed": remove}


def _restore(store: Path, expected: str, destination: Path) -> dict:
    """Restore only into a new private directory; never extract through archive links."""
    store, destination = checked(store), checked(destination, new=True)
    receipt = _verify(store, expected)
    require(destination.is_absolute()
            and destination.parent == destination.parent.resolve(strict=True),
            "destination must have a canonical existing parent")
    destination.mkdir(mode=0o700)
    directories, links = [], []
    with gzip.open(store / INDEX, "rb") as index, tarfile.open(store / DATA, "r|gz") as archive:
        for row in rows(index):
            member = archive.next()
            path = destination if row["path"] == "." else destination / row["path"]
            require(path.parent == path.parent.resolve(strict=True)
                    or path == destination, "restore parent is not a real directory")
            if row["kind"] == "directory":
                if path != destination:
                    path.mkdir(mode=0o700)
                directories.append((path, row))
            elif row["kind"] == "symlink":
                links.append((path, row))
            else:
                payload = archive.extractfile(member)
                require(payload is not None, "missing restore payload")
                with payload, path.open("xb") as output:
                    shutil.copyfileobj(payload, output, CHUNK)
                require(digest(path) == row["sha256"], "restored payload differs")
                _metadata(path, row)
            archive.members.clear()
    for path, row in links:
        os.symlink(row["link"], path)
        _metadata(path, row)
    for path, row in reversed(directories):
        _metadata(path, row)
    return {"restored": receipt["entries"], "destination": str(destination),
            "historical_physical_facts_recertified": False}


def restore(store: Path, expected: str, destination: Path) -> dict:
    """Protect the complete materialisation against concurrent stale-bundle cleanup."""
    with lease(store):
        return _restore(store, expected, destination)


def _metadata(path: Path, row: dict) -> None:
    path = checked(path, new=True)
    require(row["uid"] == os.getuid(), "restoration requires the original owner")
    if path.lstat().st_gid != row["gid"]:
        os.chown(path, -1, row["gid"], follow_symlinks=False)
    attributes.write(path, row["xattrs"])
    if row["kind"] != "symlink":
        os.chmod(path, row["mode"])
    os.utime(path, ns=(row["mtime_ns"], row["mtime_ns"]), follow_symlinks=False)


def main(argv: list[str] | None = None) -> int:
    """Expose explicit cold packing, complete verification and new-directory restoration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("pack", "verify", "restore"))
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--receipt-sha256")
    parser.add_argument("--confirm-cold", action="store_true")
    parser.add_argument("--remove-raw", action="store_true")
    args = parser.parse_args(argv)
    if args.operation == "pack":
        if args.root is None or not args.confirm_cold or args.receipt_sha256:
            parser.error("pack requires --root and --confirm-cold")
        result = pack(args.root, args.store, remove=args.remove_raw)
    else:
        if not args.receipt_sha256 or args.confirm_cold or args.remove_raw:
            parser.error("verify/restore require --receipt-sha256")
        if args.operation == "restore":
            if args.root is None:
                parser.error("restore requires a new --root destination")
            result = restore(args.store, args.receipt_sha256, args.root)
        else:
            result = verify(args.store, args.receipt_sha256)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
