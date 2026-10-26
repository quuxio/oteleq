"""Record exact-source lifetime component validation without rebuilding SDKs."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time

ROOT = Path('/Users/sclarke/github/oteleq-qualification')
SOURCE = ROOT / 'work/oteleq-native-lifetime-receipt'
OUT = ROOT / '2026-10-25/native-lifetime-build/components-df6dc0d-01'
OUT.mkdir(exist_ok=False)
PYTHON = ROOT / '2026-10-24/python-live-metrics/env-312/bin/python'
PYTHON314 = ROOT / '2026-10-24/python-live-metrics/env-314/bin/python'
NODE = '/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node'
MARKDOWN = ROOT / 'work/oteleq-native-generated/ci/markdownlint/node_modules'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fact(path):
    value = path.lstat()
    return [digest(path), value.st_dev, value.st_ino, value.st_mode,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=SOURCE).decode().strip()


names = git('ls-files', '-z').rstrip('\0').split('\0')
before = {name: fact(SOURCE / name) for name in names}
state = {'status': 'running', 'head': git('rev-parse', 'HEAD'),
         'source': str(SOURCE), 'source_files': len(names), 'commands': [],
         'application_launches': 0, 'full_local_gate': 'pending shared storage headroom'}
assert state['head'] == 'df6dc0d2327f667b3aec2624645f0e8b4ec75c38'
assert not git('status', '--porcelain')
environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(SOURCE / 'tests'),
    NODE_PATH=str(MARKDOWN), PATH='/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin:'
    '/opt/homebrew/Cellar/node@24/24.21.0_2/bin:/opt/homebrew/opt/openjdk@21/bin:'
    '/opt/homebrew/opt/llvm@22/bin:/usr/bin:/bin:/opt/homebrew/bin')
commands = [
    ['make', 'native-lifetime-receipt-check', f'PYTHON={PYTHON}'],
    [str(PYTHON314), '-m', 'unittest', 'test_generation_native_lifetime_receipt',
     'test_generation_native_telemetry', 'test_generation_makefile', '-v'],
    ['make', 'lint', 'examples', f'PYTHON={PYTHON}', f'NODE={NODE}',
     f'MARKDOWNLINT={MARKDOWN}/.bin/markdownlint'],
    ['cargo', 'fmt', '--all', '--', '--check'],
    ['git', 'diff', '--check'],
]
started = time.monotonic()
try:
    for index, argv in enumerate(commands):
        begin = time.monotonic()
        with (OUT / f'{index}.stdout').open('xb') as stdout, (OUT / f'{index}.stderr').open('xb') as stderr:
            result = subprocess.run(argv, cwd=SOURCE, env=environment, stdout=stdout,
                                    stderr=stderr, timeout=600)
        state['commands'].append({'argv': argv, 'returncode': result.returncode,
                                  'seconds': round(time.monotonic() - begin, 3)})
        (OUT / 'status.json').write_text(json.dumps(state, indent=2) + '\n')
        assert result.returncode == 0, f'command {index} failed; original channels retained'
    assert {name: fact(SOURCE / name) for name in names} == before
    assert not git('status', '--porcelain')
    archive = OUT.parent / 'source-df6dc0d.tar'
    with tarfile.open(archive, mode='x') as target:
        for name in names:
            target.add(SOURCE / name, arcname=name, recursive=False)
    index = {'head': state['head'], 'source': str(SOURCE), 'archive': str(archive),
             'archive_sha256': digest(archive), 'files': {n: row[0] for n, row in before.items()},
             'original_facts': before}
    archive.with_suffix('.json').write_text(json.dumps(index, indent=2) + '\n')
    state.update(status='passed', original_source_facts_held=True,
                 archive_sha256=index['archive_sha256'])
except Exception as error:
    state.update(status='failed', error=f'{type(error).__name__}: {error}')
    raise
finally:
    state['seconds'] = round(time.monotonic() - started, 3)
    (OUT / 'status.json').write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps({key: state.get(key) for key in
                     ('status', 'head', 'source_files', 'seconds', 'archive_sha256', 'error')}))
