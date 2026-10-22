"""Validate metadata-only compiler reads and retained emission artifacts."""

from pathlib import Path

import node_source
import otelc_capture as capture


def validate(value: dict, source_digest: str, provider: Path, backend: str, directory: Path, *, cwd: Path) -> None:
    """A compiler receipt describes inspected emission, never an SDK launch."""
    require = node_source.require
    require(backend in ("native", "api"), "unknown compiler inspection backend")
    require(type(value) is dict and set(value) == {"profile", "compiler", "configuration_reads"}
            and value["profile"] == "module-format-only-v1", "invalid compiler inspection profile")
    compiler = value["compiler"]
    fields = {"backend", "version", "compiler_path", "cwd", "transformer_profile", "files"}
    fields.add("argv" if backend == "native" else "method")
    require(type(compiler) is dict and set(compiler) == fields
            and all(type(compiler[key]) is str for key in ("backend", "version", "compiler_path", "cwd", "transformer_profile"))
            and compiler["backend"] == backend
            and compiler["version"] == {"native": "7.0.2", "api": "6.0.3"}[backend]
            and compiler["transformer_profile"] == "none", "compiler inspection recipe differs")
    executable = Path(compiler["compiler_path"])
    require(executable.is_absolute() and executable.is_file()
            and executable.resolve(strict=True).is_relative_to(provider.resolve()),
            "inspected compiler is outside the selected provider")
    require(compiler["cwd"] == str(cwd.resolve()), "compiler inspection working directory differs")
    if backend == "api":
        require(compiler["method"] == "transpileModule", "unknown API compiler operation")
    else:
        argv = compiler["argv"]
        require(type(argv) is list and len(argv) == 3 and argv[0] == str(executable)
                and argv[1] == "--project" and type(argv[2]) is str,
                "native inspection used a different compiler operation")
    validate_files(compiler["files"], source_digest, backend, directory)
    validate_reads(value["configuration_reads"])


def validate_files(files: dict, source_digest: str, backend: str, directory: Path) -> None:
    """Compiler artifacts retain their original content-addressed roles and bytes."""
    require = node_source.require
    expected = {"input", "options", "output", "map"} | ({"preparation_map"} if backend == "native" else set())
    require(type(files) is dict and set(files) == expected, "incomplete compiler inspection artifacts")
    for record in files.values():
        require(type(record) is dict and set(record) in ({"file", "sha256", "size"}, {"file", "sha256", "size", "path"})
                and type(record["sha256"]) is str and len(record["sha256"]) == 64
                and all(char in "0123456789abcdef" for char in record["sha256"])
                and record["file"] == record["sha256"] + ".txt"
                and type(record["size"]) is int and record["size"] >= 0
                and ("path" not in record or type(record["path"]) is str and Path(record["path"]).is_absolute()),
                "invalid compiler inspection artifact identity")
        path = directory / record["file"]
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == record["size"]
                and capture.file_digest(path) == record["sha256"], "compiler inspection artifact changed")
    require(files["input"]["sha256"] == source_digest, "inspected compiler input differs from original source")


def validate_reads(reads: list) -> None:
    """Configuration reads remain present or absent exactly as inspected."""
    require = node_source.require
    require(type(reads) is list, "missing compiler configuration reads")
    names = []
    for record in reads:
        require(type(record) is dict and type(record.get("requested_path")) is str,
                "invalid compiler configuration identity")
        requested = Path(record["requested_path"])
        require(requested.is_absolute(), "compiler configuration path must be absolute")
        names.append(str(requested))
        if record.get("kind") == "absent_config":
            require(set(record) == {"requested_path", "kind"} and not requested.exists(),
                    "absent compiler configuration appeared")
        else:
            require(set(record) == {"requested_path", "resolved_path", "kind", "sha256", "size"}
                    and record["kind"] == "compiler_config" and type(record["resolved_path"]) is str
                    and type(record["size"]) is int and record["size"] >= 0
                    and type(record["sha256"]) is str
                    and str(requested.resolve(strict=True)) == record["resolved_path"]
                    and requested.stat().st_size == record["size"]
                    and capture.file_digest(requested) == record["sha256"],
                    "compiler configuration changed after inspection")
    require(len(names) == len(set(names)), "duplicate compiler configuration read")


def configuration_signature(value: dict, root: Path) -> list[dict]:
    """Compare copied config identities while keeping foreign origins explicit."""
    result = []
    for record in value["configuration_reads"]:
        item = {key: content for key, content in record.items() if key not in ("requested_path", "resolved_path")}
        for key in ("requested_path", "resolved_path"):
            if key in record:
                path = Path(record[key])
                item[key] = {"relative": path.relative_to(root).as_posix()} if path.is_relative_to(root) else {"external": str(path)}
        result.append(item)
    return sorted(result, key=lambda item: str(item["requested_path"]))
