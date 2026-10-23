"""Explicit archive/materialisation commands for cold qualification evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tarfile
import zlib

from ci import evidence_archive as archive


def main(argv: list[str] | None = None) -> int:
    """Print a reviewable JSON result or a nonzero refusal; never execute metadata."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("pack", "verify", "restore", "status", "evict"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--index-sha256")
    parser.add_argument("--confirm-cold", action="store_true",
                        help="confirm that all corpus readers and writers have stopped")
    arguments = parser.parse_args(argv)
    if arguments.operation == "pack":
        if arguments.selection is None or arguments.index_sha256 or arguments.confirm_cold:
            parser.error("pack requires --selection and does not remove originals")
    elif arguments.selection is not None or not arguments.index_sha256:
        parser.error("non-pack operations require --index-sha256, without --selection")
    if arguments.confirm_cold and arguments.operation != "evict":
        parser.error("--confirm-cold applies only to evict")
    try:
        if arguments.operation == "pack":
            result = archive.pack(arguments.root, arguments.selection, arguments.store)
        elif arguments.operation == "evict":
            result = archive.evict(arguments.root, arguments.store, arguments.index_sha256,
                                   cold=arguments.confirm_cold)
        else:
            operation = archive.materialise if arguments.operation == "restore" else getattr(archive, arguments.operation)
            result = operation(arguments.root, arguments.store, arguments.index_sha256)
    except (OSError, ValueError, EOFError, tarfile.TarError, zlib.error) as error:
        print(json.dumps({"operation": arguments.operation, "status": "refused", "reason": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps({"operation": arguments.operation, "status": "complete", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
