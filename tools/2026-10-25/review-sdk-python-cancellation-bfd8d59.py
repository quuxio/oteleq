"""Independently check the frozen Python cancellation correction."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

OWNER = Path('/Users/sclarke/github/otelc-qualification/2026-10-25/python-cancellation-identity')
ROOT = Path('/Users/sclarke/github/otelc-qualification/work/python-cancellation-identity')
OUT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/sdk-python-cancellation-bfd8d59-review')
OUT.mkdir()
(OUT / 'controller.py').write_bytes(Path(__file__).read_bytes())
manifest = json.loads((OWNER / 'source.json').read_bytes())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> bytes:
    return subprocess.check_output(['git', *args], cwd=ROOT)


def preserve() -> dict:
    assert git('rev-parse', 'HEAD').decode().strip() == manifest['head']
    assert not git('status', '--porcelain').strip()
    extra = {}
    for name, expected in manifest['facts'].items():
        path = ROOT / name
        info = path.lstat()
        actual = [digest(path), info.st_dev, info.st_ino, info.st_mode,
                  info.st_size, info.st_mtime_ns, info.st_ctime_ns]
        assert actual == expected, name
        extra[name] = [info.st_uid, info.st_gid, info.st_nlink]
    assert digest(OWNER / 'source.tar') == manifest['archive_sha256']
    return extra


before = preserve()
changed = git('diff', '--name-only', manifest['base'], 'HEAD').decode().splitlines()
assert changed == ['docs/python-native.md', 'otelc/python_runtime.py',
                   'tests/test_python_cancellation.py'], changed
env = {key: value for key, value in os.environ.items()
       if not key.startswith(('GH_', 'GITHUB_', 'SONAR_', 'AWS_', 'OTEL', 'OTELEQ'))}
env.update(PYTHONPATH=os.pathsep.join(map(str, (ROOT, ROOT / 'tests'))),
           PYTHONDONTWRITEBYTECODE='1')
results = []
for tag in ('312', '314'):
    argv = list(manifest['checks'][tag]['command'])
    argv = [('--data-file=' + str(OUT / (tag + '.coverage')))
            if arg.startswith('--data-file=') else arg for arg in argv]
    start = time.monotonic()
    with (OUT / (tag + '.log')).open('xb') as output:
        result = subprocess.run(argv, cwd=ROOT, env=env, stdout=output,
                                stderr=subprocess.STDOUT, timeout=180)
    check = {'python': tag, 'argv': argv, 'exit_code': result.returncode,
             'seconds': round(time.monotonic() - start, 3)}
    results.append(check)
    print(json.dumps(check), flush=True)
    assert result.returncode == 0, tag
    coverage = subprocess.run([argv[0], '-m', 'coverage', 'json',
                              '--data-file=' + str(OUT / (tag + '.coverage')),
                              '-o', str(OUT / (tag + '-coverage.json'))],
                             cwd=ROOT, env=env, capture_output=True, text=True)
    assert coverage.returncode == 0, coverage.stderr
    report = json.loads((OUT / (tag + '-coverage.json')).read_text())
    covered = report['files']['otelc/python_runtime.py']['summary']['percent_covered']
    assert covered >= 80, covered
    check['runtime_statement_coverage'] = covered
after = preserve()
assert before == after
review = {
    'head': manifest['head'], 'base': manifest['base'], 'status': 'clear',
    'findings': [], 'changed': changed, 'source_files': len(before),
    'source_facts_preserved': True, 'uid_gid_nlink_preserved': True,
    'archive_sha256': manifest['archive_sha256'], 'independent_checks': results,
    'scope': 'Actual public Python CLI and focused runtime/monitor/health controls on Python 3.12 and 3.14; raw type ancestry, identity and hostile hook handling reviewed.',
    'trade_off': 'The bootstrap imports asyncio to pin its canonical cancellation class before application code. Import/startup visibility and overhead are real and remain outside the declared cancellation observations.',
    'limits': 'Not complete Python capability admission, current-source oteleq qualification, startup/import invisibility, fresh performance timing or exact-head full hosted CI. No large compiler/SDK build was requested.',
    'completed': datetime.now(timezone.utc).isoformat(),
}
(OUT / 'review.json').write_text(json.dumps(review, indent=2) + '\n')
print(json.dumps({'head': review['head'], 'status': review['status'],
                  'source_files': len(before), 'sha256': digest(OUT / 'review.json')}), flush=True)
