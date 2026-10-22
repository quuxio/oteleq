"""Bounded byte identities for ordinary Java classpath JARs and directories."""
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
from urllib.parse import unquote, urlsplit
import zipfile

MAX_FILES = 20000
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_CLASS_BYTES = 16 * 1024 * 1024
CLASS_BUDGET_ERROR = "class definition exceeds its byte budget"
MANIFEST = "META-INF/MANIFEST.MF"
RECORD_FIELDS = ("kind", "files", "classes", "directories")


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError("Java classpath: " + reason)


def digest(path: Path) -> str:
    """Read a stable regular file without using application loaders or formatters."""
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_FILE_BYTES,
            "input is not a bounded regular file: " + str(path))
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    after = path.lstat()
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    require(identity(before) == identity(after), "input changed during reading")
    return value.hexdigest()


def manifest(root: Path) -> dict[str, str]:
    """Retain every resource byte and refuse links or unbounded directory trees."""
    require(root.is_dir() and root.resolve() == root and not root.is_symlink(), "unsafe class directory")
    result, size, count = {}, 0, 0
    for directory, names, files in os.walk(root):
        count += len(names) + len(files)
        require(count <= MAX_FILES, "classpath directory exceeds its entry budget")
        names.sort()
        parent = Path(directory)
        require(not any((parent / name).is_symlink() for name in names + files), "symlink in classpath directory")
        for name in sorted(files):
            path = parent / name
            size += path.lstat().st_size
            require(size <= MAX_TOTAL_BYTES, "classpath directory exceeds its byte budget")
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def binary_name(name: str) -> str | None:
    """Module metadata is not an ordinary classpath class definition."""
    if not name.endswith(".class") or name == "module-info.class" or name.startswith("META-INF/"):
        return None
    parts = name[:-6].split("/")
    require(all(part and part not in (".", "..") and not any(char.isspace() for char in part) for part in parts),
            "unsupported binary class name")
    require(not name.startswith("java/"), "classpath cannot replace java.* definitions")
    return ".".join(parts)


def jar_classes(path: Path) -> dict:
    """Keep the original JAR, refusing hidden classpaths and unqualified MR layouts."""
    require(path.suffix.lower() == ".jar" and path.stat().st_size <= MAX_FILE_BYTES, "expected a bounded JAR")
    try:
        with zipfile.ZipFile(path) as archive:
            rows = archive.infolist()
            names = [row.filename for row in rows]
            require(len(rows) <= MAX_FILES and len(names) == len(set(names)), "too many or duplicate JAR entries")
            require(sum(row.file_size for row in rows) <= MAX_TOTAL_BYTES, "expanded JAR exceeds its budget")
            result = {}
            for row in rows:
                jar_entry(row)
                name = binary_name(row.filename)
                if name is not None:
                    require(row.file_size <= MAX_CLASS_BYTES, CLASS_BUDGET_ERROR)
                    result[name] = {"entry": row.filename, "sha256": hashlib.sha256(archive.read(row)).hexdigest()}
            if MANIFEST in names:
                manifest_header(archive.read(MANIFEST))
            return result
    except (zipfile.BadZipFile, UnicodeDecodeError) as error:
        raise ValueError("Java classpath: invalid JAR") from error


def jar_entry(row: zipfile.ZipInfo, *, allow_versioned: bool = False) -> None:
    """JAR names are logical paths; none can request implicit host file lookup."""
    name = row.filename
    path = PurePosixPath(name)
    require(name == row.orig_filename and name and not path.is_absolute()
            and "\\" not in name and ".." not in path.parts and "\x00" not in name,
            "unsafe JAR entry")
    require(not row.flag_bits & 1 and row.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
            "unsupported JAR encryption or compression")
    folded = name.casefold()
    require(allow_versioned or not folded.startswith("meta-inf/versions/"),
            "multi-release JARs require a qualified producer profile")
    require(folded != "meta-inf/index.list", "implicit JAR indexes are unsupported")
    require(folded != MANIFEST.casefold() or name == MANIFEST, "noncanonical manifest path")
    if name == MANIFEST:
        require(row.file_size <= 1024 * 1024, "JAR manifest exceeds its byte budget")


def manifest_header(raw: bytes) -> None:
    """A manifest cannot add undeclared dependencies through folded attributes."""
    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").replace("\n ", "")
    require(not any(line.casefold().startswith("class-path:") for line in text.splitlines()),
            "implicit JAR Class-Path is unsupported")


def jar_members(path: Path) -> dict[str, str]:
    """Catalogue physical class members without deciding compiler/runtime selection."""
    require(path.suffix.lower() == ".jar", "expected a bounded JAR")
    original = digest(path)
    try:
        with zipfile.ZipFile(path) as archive:
            rows = archive.infolist()
            names = [row.filename for row in rows]
            require(len(rows) <= MAX_FILES and len(names) == len(set(names)),
                    "too many or duplicate JAR entries")
            require(sum(row.file_size for row in rows) <= MAX_TOTAL_BYTES,
                    "expanded JAR exceeds its budget")
            result = {}
            for row in rows:
                jar_entry(row, allow_versioned=True)
                if row.filename.endswith(".class") and not row.is_dir():
                    require(row.file_size <= MAX_CLASS_BYTES, CLASS_BUDGET_ERROR)
                    result[row.filename] = hashlib.sha256(archive.read(row)).hexdigest()
            if MANIFEST in names:
                manifest_header(archive.read(MANIFEST))
    except (zipfile.BadZipFile, UnicodeDecodeError) as error:
        raise ValueError("Java classpath: invalid JAR") from error
    require(digest(path) == original, "JAR changed while cataloguing members")
    return result


def inspect(path: Path) -> dict:
    """Inventory the full immutable input and its ordinary binary definitions."""
    require(path.is_absolute() and path.resolve() == path and not path.is_symlink()
            and os.pathsep not in str(path) and "*" not in str(path), "unsafe classpath location")
    if path.is_dir():
        files = manifest(path)
        classes = {}
        for entry, sha in files.items():
            name = binary_name(entry)
            if name is not None:
                require((path / entry).stat().st_size <= MAX_CLASS_BYTES, CLASS_BUDGET_ERROR)
                classes[name] = {"entry": entry, "sha256": sha}
        directories = sorted(item.relative_to(path).as_posix() for item in path.rglob("*") if item.is_dir())
        return {"kind": "directory", "files": files, "classes": classes, "directories": directories}
    sha = digest(path)
    classes = jar_classes(path)
    require(digest(path) == sha, "JAR changed while cataloguing classes")
    return {"kind": "jar", "files": {"": sha}, "classes": classes, "directories": []}


def class_reads(reads: object, entries: list[dict]) -> None:
    """Each actual javac classpath read must match its frozen archive or file byte."""
    require(type(reads) is dict and len(reads) <= MAX_FILES, "invalid compiler classpath read inventory")
    expected = {}
    for entry in entries:
        root = Path(entry["path"])
        # javac can read a different physical member from the runtime JarFile view.
        members = entry.get("members", {row["entry"]: row["sha256"] for row in entry["classes"].values()})
        for name, sha in members.items():
            expected[(str(root), name)] = sha
    for uri, sha in reads.items():
        require(type(uri) is str and type(sha) is str, "invalid compiler classpath read")
        if uri.startswith("jar:"):
            origin, separator, relative = uri[4:].rpartition("!/")
            require(bool(separator), "missing JAR class origin")
            key = (file_uri(origin), unquote(relative, errors="strict"))
        else:
            name = file_uri(uri)
            matches = [(str(Path(entry["path"])), Path(name).relative_to(entry["path"]).as_posix())
                       for entry in entries if entry["kind"] == "directory" and Path(name).is_relative_to(entry["path"])]
            require(len(matches) == 1, "compiler read an undeclared class directory")
            key, = matches
        require(expected.get(key) == sha, "compiler read different or undeclared dependency bytes")


def file_uri(value: str) -> str:
    """Only local canonical file locations can identify a compiler input."""
    parsed = urlsplit(value)
    require(parsed.scheme == "file" and not parsed.netloc and not parsed.query and not parsed.fragment,
            "foreign compiler class origin")
    path = Path(unquote(parsed.path, errors="strict"))
    require(path.is_absolute() and path.resolve() == path, "noncanonical compiler class origin")
    return str(path)
