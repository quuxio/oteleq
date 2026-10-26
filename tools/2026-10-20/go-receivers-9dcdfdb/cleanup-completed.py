"""Prune superseded owned Go corpora after verified delivery; keep accepted proof."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parents[1]
HISTORY = BASE / "history-pruned/go-receivers"
delivered = json.loads((ROOT / "DELIVERED.json").read_text())
assert delivered["merged_by"] == "quuxio" and delivered["required_main_checks"] == 3 and delivered["sonar_unresolved"] == 0
manifest = json.loads((ROOT / "raw-manifest.json").read_text())


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify():
    for name, record in manifest.items():
        path = ROOT / name
        if isinstance(record, dict):
            assert path.is_symlink() and str(path.readlink()) == record["symlink"]
            assert str(path.resolve(strict=True)) == record["resolved"]
        else:
            assert digest(path) == record


def size(path):
    count = allocated = 0
    for parent, folders, files in os.walk(path, followlinks=False):
        for name in files:
            info = (Path(parent) / name).lstat()
            count += 1
            allocated += info.st_blocks * 512
    return {"files": count, "allocated_bytes": allocated}


def remove_owned(path):
    """Go module cache directories are intentionally read-only after download."""
    for parent, folders, files in os.walk(path, followlinks=False):
        directory = Path(parent)
        info = directory.stat()
        assert info.st_uid == os.getuid()
        directory.chmod(stat.S_IMODE(info.st_mode) | stat.S_IRWXU)
    shutil.rmtree(path)


verify()
removed = []
for name in ("go-receivers-db56a65", "go-receivers-332230e"):
    path = ROOT.parent / name
    assert path.parent == ROOT.parent and path.is_dir() and not path.is_symlink()
    retained = HISTORY / name
    marker = path / "continuation-state.json"
    if not marker.exists():
        marker = retained / "continuation-state.json"
    state = json.loads(marker.read_text())
    assert state["state"] == "completed" and state["exit_code"] == 0
    retained.mkdir(parents=True, exist_ok=True)
    for file in path.iterdir():
        if file.is_file() and file.name != "quux-oteleq":
            shutil.copy2(file, retained / file.name)
    if (path / "reviewed-qualifier").is_dir():
        shutil.copytree(path / "reviewed-qualifier", retained / "reviewed-qualifier", dirs_exist_ok=True)
    (retained / "README.md").write_text("# Superseded Go development corpus\n\nRaw builds/caches were removed after PR38 delivery. The accepted schema-2 corpus remains under 2026-10-20/go-receivers-9dcdfdb. These retained counts and paths describe the historical run; its raw directories are no longer present.\n")
    record = {"path": str(path), **size(path), "retained_summary": str(retained)}
    remove_owned(path)
    removed.append(record)
work = BASE / "work/oteleq-go-receivers"
assert work.is_dir() and not work.is_symlink()
git = lambda *args: subprocess.check_output(["git", *args], cwd=work, text=True).strip()
assert not git("status", "--porcelain") and git("rev-parse", "HEAD") == delivered["reviewed_head"]
assert git("rev-parse", "HEAD^{tree}") == delivered["canonical"]["tree"]
record = {"path": str(work), **size(work), "source_published": delivered["merge_commit"]}
remove_owned(work)
removed.append(record)
verify()
receipt = {"date": datetime.datetime.now(datetime.timezone.utc).isoformat(), "removed": removed,
           "allocated_bytes_removed_during_resume": sum(item["allocated_bytes"] for item in removed),
           "prior_partial_removal": "Initial removal stopped at read-only owned Go module-cache directories; original du estimates were 8.3 GiB and 8.8 GiB for the two superseded corpora.",
           "accepted_records_verified_before_and_after": len(manifest),
           "accepted_runtime": delivered["runtime"]["commit"], "canonical_main": delivered["merge_commit"],
           "source_and_provider_preserved": True}
(BASE / "history-pruned/PURGE-20261020-go-receivers.json").write_text(json.dumps(receipt, indent=2) + "\n")
(ROOT / "cleanup.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt), flush=True)
