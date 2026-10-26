"""Freeze the exact consumer commit and check its small reader component gates."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time


BASE = Path(__file__).resolve().parent
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-native-lifetime-build')
HEAD = '5a9fb8398ffe77f34b8b8a1134d292ec4437bd6c'
SOURCE = BASE / 'source-5a9fb83'
ARCHIVE = BASE / 'source-5a9fb83.tar'
OUTPUT = BASE / 'components-5a9fb83-01'
PYTHONS = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics')


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=REPO).decode().strip()


def facts(path):
    state = path.stat()
    assert not path.is_symlink() and path.is_file()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return [digest, state.st_dev, state.st_ino, state.st_mode, state.st_size,
            state.st_mtime_ns, state.st_ctime_ns]


assert git('rev-parse', 'HEAD') == HEAD and not git('status', '--porcelain')
names = git('ls-files', '-z').rstrip('\0').split('\0')
before = {name: facts(REPO / name) for name in names}
subprocess.run(['git', 'archive', '--format=tar', HEAD, '-o', str(ARCHIVE)], cwd=REPO, check=True)
SOURCE.mkdir(mode=0o700)
with tarfile.open(ARCHIVE) as archive:
    archive.extractall(SOURCE, filter='data')
frozen_before = {name: facts(SOURCE / name) for name in names}
assert all(before[name][0] == frozen_before[name][0] for name in names)
index = {'head': HEAD, 'base': git('rev-parse', 'HEAD^'), 'tree': git('rev-parse', 'HEAD^{tree}'),
         'source': str(REPO), 'frozen_source': str(SOURCE), 'archive': str(ARCHIVE),
         'archive_sha256': facts(ARCHIVE)[0], 'files': {name: row[0] for name, row in before.items()},
         'original_facts': before, 'frozen_facts': frozen_before}
write(BASE / 'source-5a9fb83.json', index)
OUTPUT.mkdir(mode=0o700)
environment = {key: value for key, value in os.environ.items()
               if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'AWS_', 'SONAR_'))}
environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(SOURCE / 'tests'))
commands = [
    ['make', 'native-lifetime-check', 'PYTHON=' + str(PYTHONS / 'env-312/bin/python')],
    [str(PYTHONS / 'env-314/bin/python'), '-m', 'unittest',
     'test_generation_native_lifetime_build', 'test_generation_native_units',
     'test_generation_makefile', '-v'],
    ['make', 'help'],
    ['git', 'diff', '--check'],
]
state = {'head': HEAD, 'status': 'running', 'started': datetime.now(timezone.utc).isoformat(),
         'scope': 'Exact-head reader regression/coverage, Python 3.14 compatibility and Make help. '
                  'Literal fixture products only; no genuine SDK builds or application launches.',
         'applications': 0, 'source_files': len(names), 'commands': []}
write(OUTPUT / 'status.json', state)
started = time.monotonic()
try:
    for index_, command in enumerate(commands):
        command_start = time.monotonic()
        cwd = REPO if command[0] == 'git' else SOURCE
        with (OUTPUT / f'{index_}.stdout').open('xb') as out, (OUTPUT / f'{index_}.stderr').open('xb') as err:
            result = subprocess.run(command, cwd=cwd, env=environment, stdout=out, stderr=err, timeout=600)
        state['commands'].append({'argv': command, 'cwd': str(cwd), 'exit_code': result.returncode,
                                  'seconds': round(time.monotonic() - command_start, 3)})
        write(OUTPUT / 'status.json', state)
        assert result.returncode == 0, f'component command {index_} failed'
    state['status'] = 'passed'
except Exception as error:
    state.update(status='failed', error=repr(error))
finally:
    after = {name: facts(REPO / name) for name in names}
    frozen_after = {name: facts(SOURCE / name) for name in names}
    state['preservation'] = {'original': before == after, 'frozen': frozen_before == frozen_after,
                             'head': git('rev-parse', 'HEAD') == HEAD}
    write(OUTPUT / 'inputs-after.json', {'original': after, 'frozen': frozen_after})
    if not all(state['preservation'].values()):
        state['status'] = 'failed'
    state.update(seconds=round(time.monotonic() - started, 3),
                 finished=datetime.now(timezone.utc).isoformat())
    write(OUTPUT / 'status.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
