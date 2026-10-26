"""Review reused Go source and public integration without compiler workloads."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

SOURCE = Path('/Users/sclarke/github/otelc-qualification/work/go-public-delivery')
OWNER = Path('/Users/sclarke/github/otelc-qualification/2026-10-25/go-public-delivery')
OUT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/sdk-go-public-cc8b19f-review')
PYTHON = '/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python'
OUT.mkdir()
(OUT / 'controller.py').write_bytes(Path(__file__).read_bytes())
manifest = json.loads((OWNER / 'source-cc8b19f.json').read_text())
reuse = json.loads((OWNER / 'reuse.json').read_text())


def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=SOURCE)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def preserve():
    assert git('rev-parse', 'HEAD').decode().strip() == manifest['head']
    assert not git('status', '--porcelain').strip()
    for name, expected in manifest['original_facts'].items():
        path = SOURCE / name; info = path.lstat()
        assert [digest(path.read_bytes()), info.st_dev, info.st_ino, info.st_mode,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns] == expected, name
    assert digest(Path(manifest['archive']).read_bytes()) == manifest['archive_sha256']


preserve()
rows = []
for name, old_digest in reuse['reused_files'].items():
    old = git('show', reuse['source_head'] + ':' + name)
    assert digest(old) == old_digest
    current = (SOURCE / name).read_bytes()
    rows.append({'path': name, 'old_sha256': old_digest, 'new_sha256': digest(current), 'same': old == current})
changed = [row['path'] for row in rows if not row['same']]
assert changed == ['otelc/go_build.py', 'otelc/go_source.py', 'otelc/prepared_go.py', 'tests/test_go_scope_build.py']
assert sum(row['same'] for row in rows) == 44
(OUT / 'reuse-identities.json').write_text(json.dumps(rows, indent=2) + '\n')

makefile = (SOURCE / 'Makefile').read_text()
modules = ('otelc/go_build', 'otelc/go_source', 'otelc/go_build_tags', 'otelc/go_prepared_tools',
           'otelc/go_supervisor', 'otelc/prepared_go', 'otelc/go_http_bundle', 'otelc/path_boundaries',
           'ci/check_go_http')
assert all("--include='*/" + name + ".py' --fail-under=80" in makefile for name in modules)
assert 'go-public-check:' in makefile
properties = dict(line.split('=', 1) for line in (SOURCE / 'sonar-project.properties').read_text().splitlines()
                  if line and not line.startswith('#'))
tests = [str(path.relative_to(SOURCE)) for directory in ('adapters/go-source', 'adapters/go-http')
         for path in sorted((SOURCE / directory).rglob('*_test.go'))]
patterns = properties['sonar.test.inclusions'].split(',')
# Translate only the documented simple path patterns used by this repository.
def matches(path, pattern):
    expression = re.escape(pattern).replace(r'\*\*/', '(?:.*/)?').replace(r'\*', '[^/]*').replace(r'\?', '[^/]')
    return re.fullmatch(expression, path) is not None

omitted = [name for name in tests if not any(matches(name, pattern) for pattern in patterns)]
assert len(omitted) == len(tests) > 0
(OUT / 'sonar-test-denominator.json').write_text(json.dumps({'patterns': patterns,
    'all_new_go_tests': tests, 'omitted': omitted,
    'official_reference': 'https://docs.sonarsource.com/sonarqube-cloud/managing-your-projects/project-analysis/setting-analysis-scope/excluding-files-based-on-patterns'}, indent=2) + '\n')

command = json.loads((OWNER / 'bounded-03.json').read_text())['argv']
command[0] = PYTHON
command = [('--data-file=' + str(OUT / 'bounded.coverage')) if word.startswith('--data-file=') else word
           for word in command]
environment = {**os.environ, 'PYTHONPATH': str(SOURCE / 'tests'), 'PYTHONDONTWRITEBYTECODE': '1'}
started = time.monotonic()
with (OUT / 'bounded.log').open('wb') as stream:
    result = subprocess.run(command, cwd=SOURCE, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=False)
assert result.returncode == 0
seconds = time.monotonic() - started
subprocess.run([PYTHON, '-m', 'coverage', 'json', '--data-file=' + str(OUT / 'bounded.coverage'),
                '-o', str(OUT / 'coverage.json')], cwd=SOURCE, env=environment, check=True)
log = (OUT / 'bounded.log').read_text()
methods = int(re.search(r'Ran (\d+) tests?', log)[1])
assert methods == 38
preserve()
review = {'head': manifest['head'], 'base': manifest['base'], 'status': 'changes_requested',
    'findings': [{'priority': 2, 'file': 'sonar-project.properties', 'line': 9,
                  'finding': 'Add the new Go inspector and HTTP test inclusion patterns. All five new Go test files are filtered out by the current test inclusions and excluded from source.'}],
    'inherited_docs': 'Foundation docs corrections at8dc580c independently clear; carry those corrections through the published stack.',
    'source_reuse': {'old': reuse['source_head'], 'same_files': 44, 'changed_copies_reviewed': changed},
    'review_scope': ['Source extraction identities', 'Physical source/output boundaries in API and CLI before source/compiler/request/installer effects',
                    'Prepared tooling/tag/scope descriptors and source-preserving controls', 'Make coverage floors, Sonar test families and CLI/config integration'],
    'bounded_methods': methods, 'seconds': seconds, 'source_files_preserved': len(manifest['files']),
    'archive_sha256': manifest['archive_sha256'], 'compiler_builds': 0, 'sdk_builds': 0,
    'go_workload_launches': 0, 'python_test_children': 'Owned cancellation helpers only',
    'limits': 'Not fresh Go/compiler/SDK builds, public workflow/HTTP/OTLP qualification, complete module coverage or language admission.'}
(OUT / 'review.json').write_text(json.dumps(review, indent=2) + '\n')
print(json.dumps(review, indent=2))
