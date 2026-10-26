"""Review the frozen SDK object errno correction without rebuilding it."""

import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time

BASE = Path('/Users/sclarke/github/otelc-qualification/2026-10-25/native-object-errno')
OUT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/sdk-object-review-acb13d7-02')
OUT.mkdir(exist_ok=False)
index = json.loads((BASE / 'source-acb13d7.json').read_text())
source = Path(index['source'])


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fact(path):
    value = path.lstat()
    return [digest(path), value.st_dev, value.st_ino, value.st_mode,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def verify():
    for relative, expected in index['original_facts'].items():
        assert fact(source / relative) == expected, relative
    for group in ('product_facts', 'dependency_facts'):
        for name, expected in index[group].items():
            assert fact(Path(name)) == expected, name
    assert digest(Path(index['archive'])) == index['archive_sha256']


def disable_core():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


started = time.monotonic()
verify()
results = []
for label, executable, expected in (
    ('negative-control', BASE / 'before-01/objects-before', -6),
    ('corrected-engine', BASE / 'after-01/objects-after', 0),
):
    environment = dict(os.environ, LLVM_PROFILE_FILE=str(OUT / f'{label}-%m-%p.profraw'))
    completed = subprocess.run([str(executable)], cwd=OUT, env=environment,
                               capture_output=True, timeout=90, preexec_fn=disable_core)
    (OUT / f'{label}.stdout').write_bytes(completed.stdout)
    (OUT / f'{label}.stderr').write_bytes(completed.stderr)
    results.append({'name': label, 'returncode': completed.returncode,
                    'expected_returncode': expected})
    assert completed.returncode == expected, results[-1]
    if expected == -6:
        assert b'engine->Destroyed(token, unwinding) && errno == ECHILD' in completed.stderr, completed.stderr.decode(errors='replace')
verify()
result = {
    'status': 'clear', 'head': index['head'], 'base': index['base'],
    'archive_sha256': index['archive_sha256'], 'seconds': round(time.monotonic() - started, 3),
    'changed_paths_reviewed': [
        'adapters/native/src/object_runtime.cpp',
        'adapters/native/launcher/src/runtime.cpp',
        'adapters/native/tests/object_runtime_test.cpp',
    ],
    'executions': results,
    'preservation': {'source_files': len(index['original_facts']),
                     'component_products': len(index['product_facts']),
                     'dependency_archives': len(index['dependency_facts']),
                     'all_original_bytes_and_file_facts_held': True},
    'scope': 'Independent review of errno guards and maintained engine regression. '
             'The same current test fails against the original engine and passes '
             'with the freshly compiled ObjectRuntime object linked before unchanged archives.',
    'limits': 'No new shared SDK, compiler fixture, ABI integration or application '
              'qualification is established by these existing engine executables. '
              'Fresh SDK/ABI checks and required CI remain with the SDK owner.',
    'findings': [],
    'prior_review_harness_failure': 'The first local review attempt expected the '
        'admission assertion, but the old engine actually failed the maintained '
        'completion errno assertion. Its original stderr and profile are preserved '
        'in sdk-object-review-acb13d7; the product was not changed.',
}
(OUT / 'review.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'status': result['status'], 'seconds': result['seconds'],
                  'review': str(OUT / 'review.json'),
                  'sha256': digest(OUT / 'review.json'), 'executions': results}))
