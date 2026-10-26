"""Freeze and check public-route source without compiler or SDK workloads."""

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time

BASE = Path('/Users/sclarke/github/oteleq-qualification')
SOURCE = BASE / 'work/oteleq-native-destructor-exit-expectations'
EVIDENCE = BASE / '2026-10-25/native-lifetime-build'
PY312 = BASE / '2026-10-24/python-live-metrics/env-312/bin/python'
PY314 = BASE / '2026-10-24/python-live-metrics/env-314/bin/python'
NODE = Path('/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node')
RUST = Path('/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin')
MODULES = BASE / 'work/oteleq-native-generated/ci/markdownlint/node_modules'


def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=SOURCE).decode().strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def facts(names):
    result = {}
    for name in names:
        path = SOURCE / name
        info = path.lstat()
        assert stat.S_ISREG(info.st_mode)
        result[name] = [digest(path), info.st_dev, info.st_ino, info.st_mode,
                        info.st_size, info.st_mtime_ns, info.st_ctime_ns,
                        info.st_uid, info.st_gid, info.st_nlink]
    return result


assert not git('status', '--porcelain')
head = git('rev-parse', 'HEAD')
names = git('ls-files', '-z').rstrip('\0').split('\0')
held = facts(names)
archive = EVIDENCE / ('source-' + head[:7] + '.tar')
with archive.open('xb') as output:
    subprocess.run(['git', 'archive', '--format=tar', 'HEAD'], cwd=SOURCE, stdout=output, check=True)
snapshot = {'head': head, 'base': git('rev-parse', 'HEAD^'), 'source': str(SOURCE),
            'archive': str(archive), 'archive_sha256': digest(archive), 'files': names,
            'original_facts': {name: row[:7] for name, row in held.items()},
            'extra_facts': {name: row[7:] for name, row in held.items()}}
(EVIDENCE / ('source-' + head[:7] + '.json')).write_text(json.dumps(snapshot, indent=2) + '\n')
destination = EVIDENCE / ('workflow-components-' + head[:7] + '-01')
destination.mkdir()
environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'NODE_PATH': str(MODULES),
               'PATH': str(NODE.parent) + ':' + str(RUST) + ':/opt/homebrew/bin:/usr/bin:/bin',
               'PYTHONPATH': str(SOURCE / 'tests')}
tests = ['test_generation_native_lifetime_boundaries', 'test_generation_native_lifetime_promotion', 'test_generation_native_lifetime_audit', 'test_generation_native_receipt_qualification', 'test_generation_native_lifetime_workflow', 'test_generation_native_lifetime_policy', 'test_generation_native_lifetime_frontend',
         'test_generation_native_lifetime_run', 'test_generation_native_source',
         'test_generation_native_source_run', 'test_generation_makefile']
commands = [
    [str(NODE), '--test', 'tests/workflow_syntax.test.mjs'],
    ['make', 'native-lifetime-public-check', 'native-lifetime-workflow-check', 'PYTHON=' + str(PY312)],
    [str(PY314), '-m', 'unittest', *tests, '-v'],
    ['make', 'examples', 'PYTHON=' + str(PY312), 'NODE=' + str(NODE)],
    [str(NODE), str(MODULES / 'markdownlint-cli/markdownlint.js'), '**/*.md',
     '--ignore', 'ci/markdownlint/node_modules/**'],
    [str(RUST / 'rustfmt'), '--edition', '2021', '--check', 'src/generation.rs'],
    ['git', 'diff', '--check'],
]
results = []
started = time.monotonic()
for index, command in enumerate(commands):
    log = destination / (str(index) + '.log')
    tick = time.monotonic()
    with log.open('wb') as output:
        result = subprocess.run(command, cwd=SOURCE, env=environment, stdout=output,
                                stderr=subprocess.STDOUT, check=False)
    results.append({'argv': command, 'returncode': result.returncode,
                    'seconds': time.monotonic() - tick, 'log': str(log)})
    print(index, result.returncode, flush=True)
    if result.returncode:
        break
preserved = facts(names) == held
result = {'head': head, 'commands': results, 'seconds': time.monotonic() - started,
          'source_files': len(names), 'original_source_facts_preserved': preserved,
          'clean_source': not git('status', '--porcelain'),
          'compiler_builds': 0, 'sdk_builds': 0, 'application_launches': 0,
          'scope': 'Literal metadata, mocked orchestration, recipes, examples and source checks only',
          'full_macos_gate': 'Not started; the 12 GiB start margin is unavailable'}
result['status'] = 'pass' if len(results) == len(commands) and all(
    row['returncode'] == 0 for row in results) and preserved and result['clean_source'] else 'fail'
(destination / 'status.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2), flush=True)
raise SystemExit(0 if result['status'] == 'pass' else 1)
