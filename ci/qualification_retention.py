"""Retire expired registered qualification bundles while preserving required evidence."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
from typing import Iterator
import uuid

from ci import qualification_bundle as bundle
from ci.qualification_paths import checked, storage_roots

DAYS = 30
KEEP_LATEST = 2
REGISTRY = "registry.jsonl"
LIMIT = 64 * 1024 * 1024
FIELDS = {"version", "root", "store", "receipt_sha256", "created_ns", "profile",
          "command_name", "exit_code", "source_revision"}


def home_for(path: Path) -> Path:
    """Select an independently configured home, never a record-selected directory."""
    matches = [root for root in storage_roots() if path.is_relative_to(root)]
    bundle.require(bool(matches), "no configured qualification home")
    return max(matches, key=lambda root: len(root.parts))


def _control(home: Path) -> Path:
    bundle.require(home in storage_roots(), "home is not configured qualification storage")
    directory = checked(home / (".oteleq-retention-" + str(os.getuid())), new=True)
    directory.mkdir(mode=0o700, exist_ok=True)
    value = directory.lstat()
    bundle.require(stat.S_ISDIR(value.st_mode) and value.st_uid == os.getuid()
                   and stat.S_IMODE(value.st_mode) == 0o700, "unsafe retention registry directory")
    return directory


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    descriptor = os.open(checked(path, new=True), os.O_WRONLY | os.O_CREAT
                         | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        value = os.fstat(descriptor)
        bundle.require(stat.S_ISREG(value.st_mode) and value.st_uid == os.getuid()
                       and value.st_nlink == 1, "unsafe retention lease")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def _source_revision() -> str | None:
    checkout = Path(__file__).resolve().parents[1]
    try:
        status = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain"],
                                capture_output=True, text=True, timeout=5, check=False)
        if status.returncode or status.stdout:
            return None
        result = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value) else None


def _profile(command: list[str], role: str) -> tuple[str, str]:
    retained, pending = [], None
    outputs = {"--report-dir", "--audit-dir"}
    paths = {"--otelc-root", "--cli", "--comparator", "--sdk-build", "--before-cli",
             "--legacy-root", "--unsupported-otelc-root"}
    for item in command:
        if pending in outputs:
            pending = None
        elif pending in paths:
            retained.append("<" + pending[2:] + ">")
            pending = None
        elif item in outputs:
            pending = item
        elif item in paths:
            retained.append(item)
            pending = item
        elif item.endswith(".py") or item == command[0]:
            retained.append(Path(item).name)
        else:
            retained.append(item)
    label = next((Path(item).name for item in retained if item.endswith(".py")),
                 Path(retained[0]).name)
    runtime = list(sys.version_info[:2])
    return hashlib.sha256(bundle.canonical([retained, runtime, role])).hexdigest(), label + " [" + role + "]"


def register(root: Path, result: dict, command: list[str], code: int, *, role: str) -> None:
    """Register a fully verified bundle before any original raw tree is removed."""
    home = home_for(root)
    directory = _control(home)
    profile, label = _profile(command, role)
    row = {"version": 1, "root": str(root), "store": result["store"],
           "receipt_sha256": result["receipt_sha256"], "created_ns": time.time_ns(),
           "profile": profile, "command_name": label, "exit_code": code,
           "source_revision": _source_revision()}
    with _locked(directory / "registry.lock"):
        descriptor = os.open(directory / REGISTRY, os.O_WRONLY | os.O_APPEND
                             | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "ab") as stream:
            value = os.fstat(stream.fileno())
            bundle.require(stat.S_ISREG(value.st_mode) and value.st_uid == os.getuid()
                           and value.st_nlink == 1 and value.st_size < LIMIT,
                           "unsafe or full retention registry")
            stream.write(bundle.canonical(row))
            stream.flush()
            os.fsync(stream.fileno())


def _validate(row: dict, home: Path) -> dict:
    bundle.require(type(row) is dict and set(row) == FIELDS
                   and type(row["version"]) is int and row["version"] == 1,
                   "invalid retention registry record")
    bundle.require(type(row["root"]) is str and type(row["store"]) is str
                   and type(row["command_name"]) is str
                   and (row["source_revision"] is None or (
                       type(row["source_revision"]) is str
                       and re.fullmatch(r"[0-9a-f]{40}", row["source_revision"]))),
                   "invalid retention identities")
    root, store = Path(row["root"]), Path(row["store"])
    bundle.require(root.is_absolute() and store.is_absolute()
                   and ".." not in root.parts and ".." not in store.parts
                   and root.is_relative_to(home) and store.parent == root.parent
                   and re.fullmatch(re.escape(root.name) + r"\.bundle-[0-9a-f]{32}", store.name),
                   "registry path is not an owned qualification bundle")
    if root.parent.exists():
        bundle.require(checked(root) == root and checked(store) == store,
                       "registry path is not canonical")
    bundle.require(type(row["created_ns"]) is int and row["created_ns"] > 0
                   and type(row["exit_code"]) is int and row["exit_code"] >= 0,
                   "invalid retention time/outcome")
    for key in ("profile", "receipt_sha256"):
        bundle.require(type(row[key]) is str and re.fullmatch(r"[0-9a-f]{64}", row[key]),
                       "invalid retention digest")
    return row


def _load(directory: Path, home: Path) -> list[dict]:
    path = directory / REGISTRY
    if not path.exists():
        return []
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        value = os.fstat(stream.fileno())
        bundle.require(stat.S_ISREG(value.st_mode) and value.st_uid == os.getuid()
                       and value.st_nlink == 1 and value.st_size <= LIMIT,
                       "unsafe or oversized retention registry")
        result = []
        for line in stream:
            bundle.require(len(line) <= 65536, "oversized retention registry row")
            result.append(_validate(json.loads(line), home))
    bundle.require(len({row["store"] for row in result}) == len(result),
                   "duplicate retention registry entry")
    return result


def published_revisions() -> set[str]:
    """Protect source revisions cited by the checkout's published qualification records."""
    checkout = Path(__file__).resolve().parents[1]
    result = subprocess.run(["git", "-C", str(checkout), "ls-files", "docs/qualification/*.json"],
                            capture_output=True, text=True, timeout=5, check=True)
    revisions = set()
    for name in result.stdout.splitlines():
        path = checkout / name
        bundle.require(path.parent == checkout / "docs/qualification"
                       and path.stat().st_size <= 4 * 1024**2, "unexpected published qualification file")
        revisions.update(re.findall(r'"([0-9a-f]{40})"', path.read_text()))
    return revisions


def _latest(records: list[dict]) -> set[str]:
    profiles = defaultdict(list)
    for row in records:
        if row["exit_code"] == 0:
            profiles[row["profile"]].append(row)
    return {row["store"] for group in profiles.values()
            for row in sorted(group, key=lambda value: value["created_ns"], reverse=True)[:KEEP_LATEST]}


def _reason(row: dict, latest: set[str], published: set[str], now: int) -> str | None:
    store = Path(row["store"])
    if not store.exists():
        return "missing"
    store = checked(store)
    if (store / "KEEP").exists() or (store / "KEEP").is_symlink():
        return "pinned"
    if row["exit_code"] != 0:
        return "failed attempt"
    if not row["source_revision"] or row["source_revision"] in published:
        return "published or unknown source"
    receipt = (store / bundle.RECEIPT).lstat()
    newest = max(row["created_ns"], receipt.st_mtime_ns, receipt.st_ctime_ns)
    if now - newest < DAYS * 86400 * 10**9:
        return "younger than 30 days"
    if row["store"] in latest:
        return "latest two for profile"
    if checked(Path(row["root"])).exists():
        return "raw tree still materialised"
    return None


def _retire(row: dict) -> int:
    root, store = checked(Path(row["root"])), checked(Path(row["store"]))
    lock = root.with_name(root.name + ".qualification.lock")
    with _locked(lock), bundle.lease(store, exclusive=True):
        bundle.require(not root.exists(), "qualification is materialised or active")
        bundle.require(not (store / "KEEP").exists() and not (store / "KEEP").is_symlink(),
                       "bundle was pinned during cleanup")
        receipt = bundle.authenticated(store, row["receipt_sha256"])
        bundle.require(receipt["root"] == str(root), "bundle root differs from registry")
        bundle.require(set(p.name for p in store.iterdir()) == {
            bundle.DATA, bundle.INDEX, bundle.RECEIPT, "bundle.lock"},
            "bundle contains unregistered data")
        sizes = []
        for path in store.iterdir():
            value = path.lstat()
            bundle.require(stat.S_ISREG(value.st_mode) and value.st_uid == os.getuid()
                           and value.st_nlink == 1, "unsafe retirement file")
            sizes.append(value.st_blocks * 512)
        shutil.rmtree(store)
        marker = root.with_name(root.name + ".compressed.json")
        if marker.is_file() and not marker.is_symlink():
            value = json.loads(marker.read_text())
            if value.get("store") == str(store) and value.get("receipt_sha256") == row["receipt_sha256"]:
                value.update(state="expired", expired_ns=time.time_ns())
                temporary = marker.with_name(marker.name + ".pending-" + uuid.uuid4().hex)
                temporary.write_bytes(bundle.canonical(value))
                os.replace(temporary, marker)
        return sum(sizes)


def _prune(directory: Path, home: Path, removed: set[str]) -> None:
    with _locked(directory / "registry.lock"):
        records = _load(directory, home)
        temporary = directory / ("registry-" + uuid.uuid4().hex)
        with temporary.open("xb") as stream:
            for row in records:
                if row["store"] not in removed:
                    stream.write(bundle.canonical(row))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / REGISTRY)


def _plan(records: list[dict], published: set[str]) -> tuple[list[dict], Counter, set[str]]:
    latest, now = _latest(records), time.time_ns()
    reasons, missing, candidates = Counter(), set(), []
    for row in records:
        reason = _reason(row, latest, published, now)
        if reason is None:
            candidates.append(row)
        else:
            reasons[reason] += 1
            if reason == "missing":
                missing.add(row["store"])
    return candidates, reasons, missing


def _apply(candidates: list[dict], reasons: Counter) -> tuple[set[str], int, list[dict]]:
    removed, allocated, errors = set(), 0, []
    for row in candidates:
        try:
            allocated += _retire(row)
            removed.add(row["store"])
        except BlockingIOError:
            reasons["active lease"] += 1
        except (OSError, ValueError) as error:
            errors.append({"store": row["store"], "error": str(error)})
    return removed, allocated, errors


def clean(home: Path, *, apply: bool = False) -> dict:
    """Plan by default; remove only expired, unpinned, authenticated managed successes."""
    directory = _control(home)
    with _locked(directory / "registry.lock"):
        records = _load(directory, home)
    candidates, reasons, missing = _plan(records, published_revisions())
    removed, allocated, errors = set(), 0, []
    if apply:
        removed, allocated, errors = _apply(candidates, reasons)
        if removed or missing:
            _prune(directory, home, removed | missing)
    result = {"home": str(home), "apply": apply, "examined": len(records),
              "retention_days": DAYS, "keep_latest_successes_per_profile": KEEP_LATEST,
              "candidates": [row["store"] for row in candidates],
              "removed_bundles": len(removed),
              "pruned_missing_registry_records": len(missing) if apply else 0,
              "reported_allocated_bytes_removed": allocated,
              "preserved": dict(reasons), "errors": errors,
              "unregistered_legacy_data": "never selected for automatic deletion"}
    if apply:
        record = directory / ("cleanup-" + str(time.time_ns()) + "-" + uuid.uuid4().hex + ".json.gz")
        with gzip.open(record, "xb") as stream:
            stream.write(bundle.canonical(result))
    return result


def clean_if_due(home: Path) -> dict | None:
    """Run at most once per day while qualifications are in use."""
    directory = _control(home)
    state = directory / "last-cleanup.json"
    with _locked(directory / "cleanup.lock"):
        now = time.time_ns()
        if state.is_file() and not state.is_symlink():
            last = json.loads(state.read_text())
            if now - last["checked_ns"] < 86400 * 10**9:
                return None
        result = clean(home, apply=True)
        temporary = directory / ("last-cleanup-" + uuid.uuid4().hex)
        temporary.write_bytes(bundle.canonical({"checked_ns": now}))
        os.replace(temporary, state)
        return result


def main(argv: list[str] | None = None) -> int:
    """Inspect or apply the fixed documented retention policy in one configured home."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = clean(args.home.resolve(strict=True), apply=args.apply)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "refused", "reason": str(error)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 2 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
