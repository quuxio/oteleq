"""Retain and audit every original failed metric shard without rerunning it."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

BASE = Path('/Users/sclarke/github/oteleq-qualification')
OUTPUT = BASE / '2026-10-25/native-metric-controls/hosted-be8993'
PYTHON = BASE / '2026-10-24/python-live-metrics/env-312/bin/python'
WRAPPER = BASE / '2026-10-20/pause-for-reboot/quux-oteleq-gh.py'
RUN = 40235178900
HEAD = 'be8993b59f3838ffc09a63aca0ac90379bd9a8bf'


def api(endpoint: str) -> bytes:
    environment = dict(os.environ, XDG_CACHE_HOME=str(BASE / 'work/gh-cache'))
    result = subprocess.run([str(PYTHON), str(WRAPPER), 'api', endpoint],
                            env=environment, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr.decode())
    return result.stdout


def saved_json(endpoint: str, name: str) -> dict:
    raw = api(endpoint)
    (OUTPUT / name).write_bytes(raw)
    return json.loads(raw)


def main() -> None:
    run = saved_json(f'repos/quuxio/oteleq/actions/runs/{RUN}', 'terminal-run.json')
    assert run['head_sha'] == HEAD and run['run_attempt'] == 1
    assert (run['status'], run['conclusion']) == ('completed', 'failure')
    jobs = saved_json(f'repos/quuxio/oteleq/actions/runs/{RUN}/jobs?per_page=100', 'terminal-jobs.json')
    assert jobs['total_count'] == len(jobs['jobs']) == 8
    assert len({row['id'] for row in jobs['jobs']}) == 8
    assert all((row['status'], row['conclusion']) == ('completed', 'failure') for row in jobs['jobs'])
    artifacts = saved_json(f'repos/quuxio/oteleq/actions/runs/{RUN}/artifacts?per_page=100', 'terminal-artifacts.json')
    expected = {f'native-metrics-{language}-{start}-{RUN}-1' for language in ('c', 'cpp')
                for start in ('11', '01', '10', '00')}
    assert artifacts['total_count'] == len(artifacts['artifacts']) == 8
    assert {row['name'] for row in artifacts['artifacts']} == expected
    assert len({row['id'] for row in artifacts['artifacts']}) == 8
    result = []
    for artifact in artifacts['artifacts']:
        path = OUTPUT / (artifact['name'] + '-' + str(artifact['id']) + '.zip')
        if not path.exists():
            path.write_bytes(api(f'repos/quuxio/oteleq/actions/artifacts/{artifact["id"]}/zip'))
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        assert len(raw) == artifact['size_in_bytes'] and 'sha256:' + digest == artifact['digest']
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            assert len(names) == len(set(names)) == 25
            assert archive.read('native-metric-evidence/sdk-build.exit') == b'0\n'
            assert archive.read('native-metric-evidence/normal/plan.exit') == b'4\n'
            failures = [name for name in names if name.endswith('/discovery-failure.json')]
            assert len(failures) == 1
            failure = json.loads(archive.read(failures[0]))
            assert failure == {'error': 'native prepared provider: native SDK record differs from its caller-held recipe',
                               'phase': 'native build context', 'schema_version': 1}
            assert not archive.read('native-metric-evidence/consumer-source-status.txt')
            assert not archive.read('native-metric-evidence/provider-source-status.txt')
            commands = [name for name in names if name.endswith('.started.json')]
            assert sorted(commands) == ['native-metric-evidence/normal/plan.started.json',
                                        'native-metric-evidence/sdk-build.started.json']
        row = {'artifact': artifact['name'], 'id': artifact['id'], 'path': str(path),
               'bytes': len(raw), 'sha256': digest, 'members': len(names),
               'sdk_build_exit': 0, 'plan_exit': 4, 'failure': failure,
               'application_launches': 0}
        result.append(row)
        (OUTPUT / 'terminal-shard-progress.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({key: row[key] for key in ('artifact', 'sdk_build_exit', 'plan_exit', 'application_launches')}), flush=True)
    receipt = {'head': HEAD, 'run': RUN, 'attempt': 1, 'status': 'original_failure_audited',
               'terminal_failed_shards': len(result), 'successful_sdk_builds': len(result),
               'native_application_launches': 0, 'shards': result,
               'scope': 'All original eight archives retained and checked; no run was restarted or relabelled.'}
    (OUTPUT / 'terminal-audit.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
