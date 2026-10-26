"""Retain verified delivery, then prune only its superseded local work."""
import datetime
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

BASE = Path('/Users/sclarke/github/oteleq-qualification')
ROOT = Path(__file__).resolve().parent
CANONICAL = Path('/Users/sclarke/github/oteleq')
WORK = BASE / 'work/oteleq-rust-compiler'
HEAD = '32ab92acc1f2214e718e8edfbea544b5ceb15cbc'
MERGE = '2e3e0561ba213d26eabd81b659d6fe8764c5a1b8'


def read(path: Path):
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()


def verify_raw() -> int:
    records = read(ROOT / 'raw-manifest.json')
    for row in records:
        path = ROOT / row['path']
        if 'link' in row:
            assert path.is_symlink() and str(path.readlink()) == row['link']
        else:
            assert not path.is_symlink() and path.stat().st_size == row['bytes']
            assert oct(path.stat().st_mode & 0o777) == row['mode'] and digest(path) == row['sha256']
    return len(records)


expected = {'Documentation and design examples':15368,
            'Rust comparator and 80% product coverage':15368,
            'SonarCloud Code Analysis':12526}
for filename, commit in [('pr-final-checks.json', HEAD), ('main-checks.json', MERGE)]:
    checks = read(ROOT / filename)
    assert checks['total_count'] == 3 and len(checks['check_runs']) == 3
    for row in checks['check_runs']:
        assert row['name'] in expected and row['head_sha'] == commit
        assert row['app']['id'] == expected[row['name']] and row['conclusion'] == 'success'
        assert row['status'] == 'completed'
sonar = next(row for row in read(ROOT / 'sonar-main-branches.json')['branches'] if row['isMain'])
assert sonar['commit']['sha'] == MERGE and sonar['status']['qualityGateStatus'] == 'OK'
assert read(ROOT / 'sonar-main-issues.json')['paging']['total'] == 0
merged = read(ROOT / 'merged-pr.json')
assert merged['mergedBy']['login'] == 'quuxio' and merged['mergeCommit']['oid'] == MERGE
assert git(CANONICAL, 'rev-parse', 'HEAD') == MERGE and not git(CANONICAL, 'status', '--porcelain')
assert git(CANONICAL, 'rev-parse', 'HEAD^{tree}') == git(CANONICAL, 'rev-parse', HEAD + '^{tree}')
assert git(WORK, 'rev-parse', 'HEAD') == HEAD and not git(WORK, 'status', '--porcelain')
assert not git(WORK, 'stash', 'list')
for name in ('generated', 'fixed', 'semantics', 'legacy'):
    state = read(ROOT / (name + '-state.json'))
    assert state['state'] == 'completed' and state['exit_code'] == 0
assert read(ROOT / 'gate-state.json')['state'] == 'completed'
kept = verify_raw()
assert kept == 2845
receipt = {'completed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'pr':'https://github.com/quuxio/oteleq/pull/36','reviewed_head':HEAD,
           'merge_commit':MERGE,'merged_by':'quuxio','tree':git(CANONICAL,'rev-parse','HEAD^{tree}'),
           'runtime':read(ROOT / 'runtime.json'),'qualification':read(ROOT / 'verification.json'),
           'local_gate':read(ROOT / 'gate-verified.json'),
           'required_pr_checks':3,'required_main_checks':3,'sonar_unresolved':0,
           'canonical_clean':True,'optional_review':'No GitHub review produced; direct review under standing user authority, no required check bypass.',
           'visual_review':'Actual Chrome screenshot inspected; four matching cases, visible denominators and diagnostic limits; JUnit4, failures0, errors0, skips0.',
           'project_complete':False}
(ROOT / 'DELIVERED.json').write_text(json.dumps(receipt,indent=2)+'\n')
plans = read(BASE / 'history-pruned/rust-compiler-cleanup-plan.json')
for plan in plans:
    root = Path(plan['path'])
    assert root.parent == BASE / '2026-10-20'
    assert root.name in ('rust-compiler-20b0e98', 'rust-compiler-72efbcf')
    for record in plan['preserved_summary_records']:
        copy = BASE / 'history-pruned/rust-compiler' / root.name / record['path']
        assert digest(copy) == record['sha256']
for path in (WORK, Path('/private/tmp/oteleq-java-report-preview-profile')):
    files = [p for p in path.rglob('*') if p.is_file() and not p.is_symlink()]
    plans.append({'path':str(path),'regular_files':len(files),
                  'allocated_bytes':sum(p.stat().st_blocks*512 for p in files),
                  'reason':'Completed owned work clone fully merged, or stopped isolated report-preview profile.'})
free_before = shutil.disk_usage(BASE).free
for plan in plans:
    path = Path(plan['path'])
    assert path.resolve() == path and path != ROOT and not path.is_symlink()
    shutil.rmtree(path)
    assert not path.exists()
assert verify_raw() == kept
result = {'deleted_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'items':plans,'allocated_bytes_removed':sum(p['allocated_bytes'] for p in plans),
          'free_space_change_bytes':shutil.disk_usage(BASE).free - free_before,
          'accepted_records_verified_before_and_after':kept,
          'final_manifest_sha256':digest(ROOT/'raw-manifest.json'),
          'git_history_rewritten':False,'peer_providers_modified':False}
(BASE/'history-pruned/PURGE-20261020-rust.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='items'}))
