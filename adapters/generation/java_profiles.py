"""Explicit independently fixed recipes for the two prepared Java providers."""
import hashlib
from pathlib import Path
import zipfile

STOCK = "stock-methods-v1"
SAFE = "safe-methods-v1"
ARCHIVES = "archive-methods-v1"
PATCH = "adapters/java/target/java-extension-0.2.0-SNAPSHOT-bootstrap-patch.jar"
PARSER = "io/opentelemetry/javaagent/shaded/io/opentelemetry/api/trace/propagation/internal/W3CTraceContextEncoding.class"
PARSER_SHA256 = "bb56f27410ee111a92ab5c172eacb136f1e69795d4e84906a036d7d3b1b42712"
LICENCES = {"META-INF/LICENSE.opentelemetry": "licenses/Apache-2.0-opentelemetry.txt",
            "META-INF/NOTICE.opentelemetry": "licenses/opentelemetry-parser-NOTICE.txt"}


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError("Java prepared profile: " + reason)


def name(value: object) -> str:
    """Provider metadata and filenames cannot select another launch recipe."""
    require(type(value) is str and value in (STOCK, SAFE, ARCHIVES), "unknown profile")
    return value


def corrected(value: object) -> bool:
    """Both later profiles use the qualified advice and bootstrap parser patch."""
    return name(value) in (SAFE, ARCHIVES)


def settings(value: dict) -> dict:
    """Keep existing defaults and require an explicit prepared backend for profiles."""
    backend = value.get("backend", "legacy")
    if "profile" not in value:
        return {"backend": backend}
    require(backend == "prepared", "profile requires the prepared backend")
    return {"backend": backend, "profile": name(value["profile"])}


def patch_inputs(root: Path) -> list[Path]:
    """Accept only the pinned shaded parser and its declared licence/notice files."""
    path = root / PATCH
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 262144,
            "missing or unsafe bootstrap parser patch")
    required = {PARSER, *LICENCES}
    try:
        with zipfile.ZipFile(path) as archive:
            rows = archive.infolist()
            names = [row.filename for row in rows]
            require(len(set(names)) == len(names) and len(names) <= 32
                    and {entry for entry in names if not entry.endswith("/")} == required
                    and all(any(file.startswith(entry) for file in required) for entry in names if entry.endswith("/")),
                    "unexpected bootstrap patch entries")
            require(all(row.orig_filename == row.filename and not row.flag_bits & 1
                        and row.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                        and row.file_size <= (16384 if row.filename == PARSER else 65536) for row in rows),
                    "unsupported or oversized bootstrap patch entry")
            require(hashlib.sha256(archive.read(PARSER)).hexdigest() == PARSER_SHA256,
                    "bootstrap parser digest differs")
            for entry, source in LICENCES.items():
                original = root / source
                require(original.is_file() and not original.is_symlink()
                        and 0 < original.stat().st_size <= 65536
                        and archive.read(entry) == original.read_bytes(), "bootstrap licence/notice differs")
    except zipfile.BadZipFile as error:
        raise ValueError("Java prepared profile: invalid bootstrap patch JAR") from error
    return [path, *(root / source for source in LICENCES.values())]
