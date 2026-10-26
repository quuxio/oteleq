"""Run literal tagged main/library experiments from one frozen consumer build."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parent
INDEX = json.loads((ROOT / 'source-c8c1e89.json').read_text())
CONSUMER = Path(INDEX['source'])
SDK = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-reuse-review-d2ec6bf/source')
SDK_INDEX = json.loads((SDK.parent / 'inputs-before.json').read_text())
CLI = ROOT / 'target/debug/quux-oteleq'
PYTHON = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python')
GO = Path('/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go')
DESTINATION = ROOT / 'public-01'
DESTINATION.mkdir()
ENVIRONMENT = dict(os.environ, OTELEQ_PYTHON=str(PYTHON), OTELC_PYTHON=str(PYTHON), OTELC_GO=str(GO),
                   OTELEQ_CLI=str(CLI), PYTHONDONTWRITEBYTECODE='1', PATH=str(GO.parent) + os.pathsep + os.environ['PATH'])


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def facts(path):
    data = path.read_bytes()
    value = path.stat()
    return {'sha256': hashlib.sha256(data).hexdigest(), 'facts': [value.st_dev, value.st_ino,
        value.st_mode, value.st_uid, value.st_gid, value.st_size, value.st_mtime_ns, value.st_ctime_ns]}


def inputs():
    tools = json.loads((SDK / 'build/go-upstream/toolchain.json').read_text())
    return {'consumer': {name: facts(CONSUMER / name) for name in INDEX['files']},
            'sdk': {name: facts(SDK / name) for name in SDK_INDEX['files']},
            'tools': {str(path): facts(path) for path in [SDK / 'build/go-upstream/toolchain.json',
                       *[Path(tools[name]) for name in ('go', 'weaver', 'bundle')]]}, 'cli': facts(CLI)}


state = {'head': INDEX['head'], 'sdk_head': SDK_INDEX['head'], 'status': 'running', 'commands': [],
         'reports': [], 'started': datetime.now(timezone.utc).isoformat()}
before = inputs()
write(DESTINATION / 'inputs-before.json', before)
assert all(before['consumer'][name]['sha256'] == digest for name, digest in INDEX['files'].items())


def command(folder, name, words):
    argv = list(map(str, words))
    write(folder / (name + '-command.json'), argv)
    state['phase'] = str(folder.relative_to(DESTINATION)) + '/' + name
    write(DESTINATION / 'status.json', state)
    start = time.monotonic()
    with (folder / (name + '.stdout')).open('xb') as stdout, (folder / (name + '.stderr')).open('xb') as stderr:
        result = subprocess.run(argv, cwd=CONSUMER, env=ENVIRONMENT, stdout=stdout, stderr=stderr, timeout=1800)
    state['commands'].append({'phase': state['phase'], 'exit_code': result.returncode,
                              'seconds': round(time.monotonic() - start, 3)})
    write(DESTINATION / 'status.json', state)
    assert result.returncode == 0, state['commands'][-1]
    return (folder / (name + '.stdout')).read_text().strip()


def audit(report, tags, package):
    data = json.loads(report.read_text())
    assert data['source_preserved'] and data['exit_code'] == 0 and not data['blocked'] and len(data['cases']) == 1
    case = data['cases'][0]
    assert case['exit_code'] == 0 and case['arguments'] == [21]
    entry = next(item for item in data['inventory'] if item['name'] == 'Add')
    assert entry['go_options']['build_tags'] == tags
    folder = report.parent / case['case']
    bundle = json.loads((folder / 'typed-bundle.json').read_text())['cases'][0]
    function = 'example.test/tagged' + ('/counter' if package == 'counter' else '') + '.Add'
    applications = []
    for lane in ('baseline', 'instrumented_on'):
        assert len(bundle[lane]) == 2
        for index, attempt in enumerate(bundle[lane]):
            current = folder / (lane + '-' + str(index))
            observed = attempt['observation']
            assert not observed['gaps'] and observed['function_id'] == function
            assert set(observed['before']['roots']) == {'global:Total', 'global:Asset'}
            for boundary, total in (('before', '0'), ('after', '28')):
                roots = observed[boundary]['roots']
                assert roots['global:Total'] == {'bits': 64, 'kind': 'integer', 'signed': True, 'type': 'go.int', 'value': total}
                assert roots['global:Asset'] == {'kind': 'string', 'type': 'go.string', 'encoding': 'raw_bytes', 'value': '7061796c6f6164'}
                assert observed[boundary]['nodes'] == []
            assert observed['outcome']['kind'] == 'return'
            result = observed['outcome']['graph']['roots']['result']
            assert result == {'bits': 64, 'kind': 'integer', 'signed': True, 'type': 'go.int', 'value': '29'}
            assert observed['outcome']['graph']['roots']['global:Total'] == observed['after']['roots']['global:Total']
            assert (current / 'stdout').read_bytes() == (current / 'stderr').read_bytes() == b''
            build = json.loads((current / 'go-build/build.json').read_text())
            assert build['schema_version'] == 5 and build['build_tags'] == tags
            inventory = json.loads((current / 'go-build/inspection/inventory.json').read_text())
            assert inventory['schema_version'] == 2 and inventory['build_tags'] == tags
            prefix = 'counter/' if package == 'counter' else ''
            assert prefix + 'choice.go' in inventory['compiler_inputs'] and prefix + 'asset.txt' in inventory['compiler_inputs']
            assert prefix + 'choice_default.go' not in inventory['compiler_inputs']
            for recipe in build['commands'][-2:]:
                assert [word for word in recipe['argv'] if word.startswith('-tags=')] == ['-tags=' + ','.join(tags)]
            assert (current / 'go-build/private/otel.instrumentation.go').read_text().startswith('//go:build !' + tags[0] + '\n')
            start = json.loads((current / 'go-runtime/oteleq-go-start.json').read_text())
            owner = start['owner']
            assert start['kernel']['application'] == {'pid': owner['application_pid'], 'parent_pid': owner['pid'], 'process_group': owner['pid']}
            assert start['kernel']['supervisor'] == {'pid': owner['pid'], 'parent_pid': owner['parent_pid'], 'process_group': owner['pid']}
            native = json.loads((current / 'go-runtime/go-application-start.json').read_text())
            applications.append(native['launch_id'])
            if lane == 'baseline':
                assert attempt['execution']['witness'] is None and not (current / 'go-verified-telemetry.json').exists()
            else:
                receipt = json.loads((current / 'go-verified-telemetry.json').read_text())
                assert receipt['sdk_pid'] == owner['application_pid'] and receipt['functions'] == {function: 1} and receipt['spans'] == 1
                assert not any(receipt['losses'].values()) and receipt['pending'] == 0
                assert receipt['health']['exported']['sdk_metric_points'] is None
    assert len(set(applications)) == 4
    return {'report': str(report), 'tags': tags, 'package': package, 'applications': applications,
            'report_sha256': hashlib.sha256(report.read_bytes()).hexdigest()}


try:
    for name, tags, package in (('combined', ['feature', 'tools', '\u03c0'], 'main'),
                                 ('tools-only', ['tools'], 'counter'), ('unicode-only', ['\u03c0'], 'main')):
        folder = DESTINATION / name
        folder.mkdir()
        application = folder / 'application'
        source = application / ('counter' if package == 'counter' else '')
        source.mkdir(parents=True)
        (application / 'go.mod').write_text('module example.test/tagged\n\ngo 1.26.0\n')
        (source / 'api.go').write_text('package ' + package + '\nvar Total int\nfunc Add(value int)int{Total+=value+adjustment();return Total+1}\n'
                                      + ('func main(){}\n' if package == 'main' else ''))
        constraint = ' && '.join(tags)
        (source / 'choice.go').write_text('//go:build ' + constraint + '\n\npackage ' + package + '\nimport _ "embed"\n//go:embed asset.txt\nvar Asset string\nfunc adjustment()int{return len(Asset)}\n')
        (source / 'choice_default.go').write_text('//go:build !(' + constraint + ')\n\npackage ' + package + '\nvar Asset="wrong"\nfunc adjustment()int{return 100}\n')
        (source / 'asset.txt').write_text('payload')
        original = {p.relative_to(application).as_posix(): facts(p) for p in source.rglob('*') if p.is_file()}
        original['go.mod'] = facts(application / 'go.mod')
        policy = folder / 'policy.toml'
        policy.write_text('schema_version=1\nlanguages=["go"]\n[adapters.go]\nbackend="source-v1"\nmodule_roots=["."]\n'
                           + 'build_tags=' + json.dumps(list(reversed(tags))) + '\nbuild_timeout_ms=900000\n[functions]\ninclude=["*.Add"]\n'
                           + '[[fixtures]]\nfunction="*.Add"\ncases=[[21]]\nexpected_baseline={kind="return",value=29}\n')
        workspace = Path(command(folder, 'plan', [CLI, 'plan', '--source', application, '--otelc-root', SDK, '--config', policy, '--workspace-parent', folder]))
        plan = json.loads((workspace / 'plan.json').read_text())
        assert len([item for item in plan['inventory'] if item['status'] == 'ready']) == 1 and not any(item['status'] == 'blocked' for item in plan['inventory'])
        command(folder, 'generate', [CLI, 'generate', '--workspace', workspace])
        command(folder, 'run', [CLI, 'run', '--workspace', workspace, '--report-dir', folder / 'comparison'])
        state['reports'].append(audit(folder / 'comparison/report.json', tags, package))
        assert original == {name: facts(application / name) for name in original}
    launch_ids = [identity for record in state['reports'] for identity in record['applications']]
    assert len(launch_ids) == len(set(launch_ids)) == 12
    state['actual_applications'] = 12
    state['actual_sdk_processes'] = 6
    state['status'] = 'passed'
except Exception as error:
    state['status'], state['error'] = 'failed', repr(error)
finally:
    after = inputs()
    write(DESTINATION / 'inputs-after.json', after)
    state['preservation'] = {name: before[name] == after[name] for name in before}
    if not all(state['preservation'].values()):
        state['status'] = 'failed'
    state['finished'] = datetime.now(timezone.utc).isoformat()
    write(DESTINATION / 'status.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
