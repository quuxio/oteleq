"""Freeze and check the current caller component without rebuilding an SDK."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time

ROOT = Path('/Users/sclarke/github/oteleq-qualification')
SOURCE = ROOT / 'work/oteleq-native-lifetime-caller'
OUT = ROOT / '2026-10-25/native-lifetime-build/components-12c50cf-01'
OUT.mkdir(exist_ok=False)
PYTHON = ROOT / '2026-10-24/python-live-metrics/env-312/bin/python'
PYTHON314 = ROOT / '2026-10-24/python-live-metrics/env-314/bin/python'
MARKDOWN = ROOT / 'work/oteleq-native-generated/ci/markdownlint/node_modules'
NODE = '/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node'


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
head = git('rev-parse', 'HEAD')
assert head == '12c50cf90d3008bcb6aacf0fb414851e7810c201' and not git('status', '--porcelain')
archive = OUT.parent / 'source-12c50cf.tar'
with tarfile.open(archive, 'x') as target:
    for name in names:
        target.add(SOURCE / name, arcname=name, recursive=False)
index = {'head': head, 'base': '92a796ca902b5c382a2478045bdb2ac7650b7932',
         'source': str(SOURCE), 'archive': str(archive), 'archive_sha256': digest(archive),
         'files': {name: row[0] for name, row in before.items()}, 'original_facts': before}
archive.with_suffix('.json').write_text(json.dumps(index, indent=2) + '\n')
state = {'status': 'running', 'head': head, 'source_files': len(names), 'commands': [],
         'application_launches': 0, 'sdk_builds': 0, 'archive_sha256': index['archive_sha256'],
         'previous_312_focused': {'tests': 14, 'seconds': 154.713,
             'new_and_shared_module_statement_coverage': 100,
             'log': 'caller-focused-312-01.log',
             'log_sha256': digest(OUT.parent / 'caller-focused-312-01.log')},
         'full_local_gate': 'Additional complete macOS gate pending12GiB storage start margin'}
environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(SOURCE / 'tests'),
    NODE_PATH=str(MARKDOWN), OTELC_CLANG='/opt/homebrew/opt/llvm@22/bin/clang',
    OTELC_CLANGXX='/opt/homebrew/opt/llvm@22/bin/clang++',
    PATH='/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin:'
         '/opt/homebrew/Cellar/node@24/24.21.0_2/bin:/opt/homebrew/opt/llvm@22/bin:'
         '/opt/homebrew/opt/openjdk@21/bin:/usr/bin:/bin:/opt/homebrew/bin')
commands = [
    [str(PYTHON314), '-m', 'unittest', 'test_generation_native_lifetime_caller',
     'test_generation_native_callers', 'test_generation_makefile', '-v'],
    ['make', 'lint', 'examples', f'PYTHON={PYTHON}', f'NODE={NODE}',
     f'MARKDOWNLINT={MARKDOWN}/.bin/markdownlint'],
    ['cargo', 'fmt', '--all', '--', '--check'], ['git', 'diff', '--check'],
]
started = time.monotonic()
try:
    for step, argv in enumerate(commands):
        begin = time.monotonic()
        with (OUT / f'{step}.stdout').open('xb') as stdout, (OUT / f'{step}.stderr').open('xb') as stderr:
            result = subprocess.run(argv, cwd=SOURCE, env=environment, stdout=stdout, stderr=stderr, timeout=600)
        state['commands'].append({'argv': argv, 'returncode': result.returncode,
                                  'seconds': round(time.monotonic() - begin, 3)})
        (OUT / 'status.json').write_text(json.dumps(state, indent=2) + '\n')
        assert result.returncode == 0, f'command{step} failed; original channels retained'
    assert {name: fact(SOURCE / name) for name in names} == before
    assert not git('status', '--porcelain')
    state.update(status='passed', original_source_facts_held=True)
except Exception as error:
    state.update(status='failed', error=f'{type(error).__name__}: {error}')
    raise
finally:
    state['seconds'] = round(time.monotonic() - started, 3)
    (OUT / 'status.json').write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps({key: state.get(key) for key in
                     ('status', 'head', 'source_files', 'seconds', 'archive_sha256', 'error')}))
