"""Recheck retained direct-route Go metric arithmetic without launching an app."""
import hashlib
import json
from pathlib import Path
import sys
import tomllib
from types import SimpleNamespace

BASE = Path(__file__).resolve().parent
SOURCE = BASE / 'source-cfd8c7e'
sys.path[:0] = [str(SOURCE / 'adapters/generation'), str(SOURCE / 'tests'), str(SOURCE / 'examples')]
import go_live_fixture as fixture
import go_telemetry

ROOT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-live-controls')
PREFIXES = [(ROOT / 'matrix-2065261-01', state) for state in ('both-on', 'collection-off')]
PREFIXES += [(ROOT / 'startup-additional-a400885-01', state) for state in ('emission-off', 'both-off')]
NAMES = {'example.test/live/counter.New', *(fixture.runtime_function(name) for name in fixture.METHODS)}


def identity(path):
    info = path.stat()
    return [hashlib.file_digest(path.open('rb'), 'sha256').hexdigest(), info.st_dev, info.st_ino,
            info.st_mode, info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink]


held, observations, ids = {}, [], set()
for prefix, state in PREFIXES:
    attempts = sorted((prefix / state / 'comparison').glob('*/instrumented_on-*'))
    assert len(attempts) == 4
    for folder in attempts:
        manifest = folder / 'http-capture.json'
        policy_path = folder / 'policy.toml'
        request = folder / 'go-runtime/go-request.json'
        for path in (manifest, policy_path, request): held[str(path)] = identity(path)
        record = json.loads(manifest.read_text()); assert not record['errors']
        policy = tomllib.loads(policy_path.read_text())
        launch = json.loads(request.read_text())['launch_id']
        assert launch not in ids; ids.add(launch)
        bodies = []
        for index, row in enumerate(record['bodies']):
            assert row['file'] == 'otlp-' + str(index) + '.protobuf'
            path = folder / row['file']; assert path.resolve() == path
            held[str(path)] = identity(path)
            bodies.append((row['path'], path.read_bytes()))
        run = SimpleNamespace(sdk_version='1.47.0', prepared=SimpleNamespace(intent=SimpleNamespace(policy=policy)))
        series, _, points = go_telemetry.metric_series(bodies, run, policy['resource']['service_name'], NAMES)
        totals = go_telemetry.cumulative_totals(series)
        observations.append({'startup': state, 'folder': str(folder), 'launch_id': launch,
            'metric_points': points, 'duration_series': sum(key[0] == go_telemetry.DURATION for key in totals)})
assert held == {name: identity(Path(name)) for name in held}
value = {'status': 'passed', 'reader_head': 'cfd8c7ee08f2e3764d0a82667c9a63a9e3f51361',
         'retained_sdk_attempts': len(ids), 'metric_points': sum(row['metric_points'] for row in observations),
         'files_and_facts_held': len(held), 'new_application_launches': 0, 'observations': observations,
         'scope': 'New histogram/service reader checks retained direct-route protobufs from all4startup states. No whole-workflow or current-source runtime qualification; original ENOSPC attempts remain failed.'}
(BASE / 'retained-histograms.json').write_text(json.dumps(value, indent=2) + '\n')
print(json.dumps({key: value[key] for key in ['status', 'retained_sdk_attempts', 'metric_points', 'files_and_facts_held', 'new_application_launches']}))
