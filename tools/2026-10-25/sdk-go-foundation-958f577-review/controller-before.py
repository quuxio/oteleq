"""Independently check the held Go extraction and literal integration boundaries."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types

ROOT = Path('/Users/sclarke/github/otelc-qualification/work/go-foundation-delivery')
OWNER = Path('/Users/sclarke/github/otelc-qualification/2026-10-25/go-foundation-delivery')
OUT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/sdk-go-foundation-958f577-review')
PYTHON = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python')
HEAD = '958f5778ebc62d568f94d114997c5f92eb0dd551'
OLD = '2481cfeb9c21662c1af68a8e2a5324ed79cf6308'
OUT.mkdir()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=ROOT)


def facts(path):
    info = path.lstat()
    return [digest(path.read_bytes()), info.st_dev, info.st_ino, info.st_mode,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def preserved():
    return all(facts(ROOT / name) == held for name, held in manifest['original_facts'].items())


manifest = json.loads((OWNER / 'source-958f577.json').read_text())
assert git('rev-parse', 'HEAD').decode().strip() == HEAD
assert not git('status', '--porcelain').strip()
assert preserved()
assert digest(Path(manifest['archive']).read_bytes()) == manifest['archive_sha256']
reuse = json.loads((OWNER / 'reuse.json').read_text())
assert reuse['source_head'] == OLD
identities = []
for name in reuse['reused_files']:
    old = git('show', OLD + ':' + name)
    current = (ROOT / name).read_bytes()
    identities.append({'path': name, 'old_sha256': digest(old), 'new_sha256': digest(current), 'same': old == current})
different = [row['path'] for row in identities if not row['same']]
assert different == ['tests/test_go_health.py'], different
assert sum(row['same'] for row in identities) == 58
(OUT / 'reuse-identities.json').write_text(json.dumps(identities, indent=2) + '\n')

production = sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / 'adapters/go').rglob('*.go')
                    if not path.name.endswith('_test.go'))
assert len(production) == 16
makefile = (ROOT / 'Makefile').read_text()
for package in ('metriccontrol', 'pipeline', 'probe', 'runtime'):
    assert package + '/*.go' in makefile
assert 'if (files!=16 || failed)' in makefile
for module in ('go_context_bundle', 'go_telemetry_bundle', 'go_runtime_config', 'go_health'):
    assert "--include='*/otelc/" + module + ".py' --fail-under=80" in makefile
for module in ('build_go_upstream', 'go_scope_patch'):
    assert "--include='*/ci/" + module + ".py' --fail-under=80" in makefile
assert 'go list -deps -mod=readonly ./...' in makefile and 'x\\/crypto\\/openpgp' in makefile
properties = dict(line.split('=', 1) for line in (ROOT / 'sonar-project.properties').read_text().splitlines()
                  if line and not line.startswith('#'))
assert 'adapters/go' in properties['sonar.sources'].split(',')
assert 'adapters/go' in properties['sonar.tests'].split(',')
assert 'adapters/go/**/*_test.go' in properties['sonar.test.inclusions'].split(',')

environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(ROOT / 'tests')}
command = [str(PYTHON), '-m', 'coverage', 'run', '--data-file=' + str(OUT / 'bounded.coverage'),
    '--source=otelc.go_context_bundle,otelc.go_telemetry_bundle,otelc.go_runtime_config,otelc.go_health,ci.build_go_upstream,ci.go_scope_patch',
    '-m', 'unittest', 'test_go_context_bundle', 'test_go_upstream_builder', 'test_go_runtime_config',
    'test_go_health', 'test_go_scope_patch', 'test_health.HealthShapeTests',
    'test_go_telemetry_bundle.GoTelemetryBundleTests.test_changed_frame_and_clone_refuse_before_generating_a_bridge', '-v']
started = time.monotonic()
with (OUT / 'bounded.log').open('wb') as output:
    result = subprocess.run(command, cwd=ROOT, env=environment, stdout=output, stderr=subprocess.STDOUT, check=False)
assert result.returncode == 0
seconds = time.monotonic() - started
subprocess.run([str(PYTHON), '-m', 'coverage', 'json', '--data-file=' + str(OUT / 'bounded.coverage'),
                '-o', str(OUT / 'coverage.json')], cwd=ROOT, env=environment, check=True)
coverage = json.loads((OUT / 'coverage.json').read_text())
assert all(row['summary']['percent_covered'] >= 80 for row in coverage['files'].values())

sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from otelc import health
from test_go_health import report

old_source = (ROOT / 'otelc/health.py').read_text().replace(
    "value.get('schema_version') not in (2, 4)", "value.get('schema_version') not in (2, 3)")
old_reader = types.ModuleType('literal_old_health_budget')
exec(compile(old_source, 'literal_old_health_budget.py', 'exec'), old_reader.__dict__)
value = report()
raw = json.dumps(value, indent=32).encode()
assert 4096 < len(raw) <= health.MAX_REPORT
with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary); directory.chmod(0o700)
    path = directory / 'health.json'; path.write_bytes(raw); path.chmod(0o600)
    try:
        old_reader.read(path)
    except ValueError as error:
        assert 'oversized version-one' in str(error)
        old_refusal = str(error)
    else:
        raise AssertionError('old budget unexpectedly accepted schema4')
    assert health.read(path) == value
    path.write_bytes(b' ' * (health.MAX_REPORT + 1))
    try:
        health.read(path)
    except ValueError:
        pass
    else:
        raise AssertionError('oversized report accepted')

assert preserved() and not git('status', '--porcelain').strip()
assert digest(Path(manifest['archive']).read_bytes()) == manifest['archive_sha256']
findings = [
    {'priority': 2, 'file': 'docs/go-source.md', 'line': 76,
     'finding': 'The new guide names schema3 although the runtime/readers require schema4.'},
    {'priority': 2, 'file': 'docs/go-sdk-controls.md', 'line': 44,
     'finding': 'The foundation-only delivery claims connected public builds/launch/benchmarks and links the absent go-http.md; these belong to later stacked changes.'},
]
review = {'head': HEAD, 'base': manifest['base'], 'status': 'changes_requested', 'findings': findings,
    'scope': 'Held-source reuse identity plus new Make/Sonar/common-health integration and bounded literal tests',
    'byte_identical_reused_files': 58, 'changed_reused_file': different,
    'owned_go_production_files': len(production), 'bounded_methods': 33, 'seconds': seconds,
    'health_budget_control': {'bytes': len(raw), 'old_refusal': old_refusal, 'corrected_accepts': True, 'oversized_refuses': True},
    'source_files_preserved': len(manifest['files']), 'archive_sha256': manifest['archive_sha256'],
    'compiler_builds': 0, 'sdk_builds': 0, 'go_workload_launches': 0,
    'limits': 'Not an independent actual Go/compiler/SDK rebuild, full final-head gate, public launch/benchmark/OTLP qualification or language admission.'}
(OUT / 'review.json').write_text(json.dumps(review, indent=2) + '\n')
print(json.dumps(review, indent=2))
