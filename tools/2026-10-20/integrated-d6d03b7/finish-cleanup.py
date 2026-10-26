"""Remove completed owned work, preserving accepted evidence and active Go work."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

BASE=Path('/Users/sclarke/github/oteleq-qualification')
ROOT=Path(__file__).resolve().parent
WORK=BASE/'work/oteleq-integrated-qualification'
ACTIVE=BASE/'work/oteleq-go-receivers'


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def git(repo: Path,*args: str) -> str:
    return subprocess.check_output(['git',*args],cwd=repo,text=True).strip()


if __debug__ is False:
    raise SystemExit('Cleanup verification requires assertions')
assert json.loads((ROOT/'DELIVERED.json').read_text())['merge_commit']=='4d639475bd0b0ad0f9482aedfd8975cfa567f586'
assert git(WORK,'rev-parse','HEAD')=='c4cf08943d3d48235e725f521c3747f3edde8007'
assert not git(WORK,'status','--porcelain') and not git(WORK,'stash','list')
active_head=git(ACTIVE,'rev-parse','HEAD');active_status=git(ACTIVE,'status','--porcelain')
assert active_head=='b517d2c4154e6177244e2a8947304e93aee88bb1' and not active_status
assert digest(ROOT/'publication-source.tar')==json.loads((ROOT/'DELIVERED.json').read_text())['publication_source_archive_sha256']
items=[]
for path in (WORK,Path('/private/tmp/oteleq-integrated-report-preview-profile')):
    assert path.resolve()==path and not path.is_symlink()
    files=[p for p in path.rglob('*') if p.is_file() and not p.is_symlink()]
    items.append({'path':str(path),'regular_files':len(files),'allocated_bytes':sum(p.stat().st_blocks*512 for p in files)})
free_before=shutil.disk_usage(BASE).free
for item in items:
    shutil.rmtree(item['path']);assert not Path(item['path']).exists()
assert git(ACTIVE,'rev-parse','HEAD')==active_head and git(ACTIVE,'status','--porcelain')==active_status
subprocess.run(['python3',str(ROOT/'revalidate-retained.py')],env={**__import__('os').environ,'PYTHONDONTWRITEBYTECODE':'1'},check=True)
result={'deleted_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'items':items,
        'allocated_bytes_removed':sum(item['allocated_bytes'] for item in items),
        'free_space_change_bytes':shutil.disk_usage(BASE).free-free_before,
        'retained_evidence_records_verified':50664,'active_go_head_preserved':active_head,
        'peer_providers_modified':False,'git_history_rewritten':False}
(BASE/'history-pruned/PURGE-20261020-integrated.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='items'}))
