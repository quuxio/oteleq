"""Exercise public prepare-only APIs and independent Go recipe readers, without apps."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
CONSUMER = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-source-provider')
SDK = ROOT.parent / 'go-benchmark-review-fdd434b/fixed-source-b95780c'
sys.path[:0] = [str(CONSUMER / 'adapters/generation'), str(CONSUMER / 'examples')]
import go_build as build
import go_files as files
import go_prepared as prepared
import python_prepared

BOOTSTRAP = ('import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);'
             'from otelc.config import Policy;from otelc import prepared_go;'
             'value=prepared_go.prepare(Policy.parse(json.loads(Path(sys.argv[2]).read_text())),'
             'Path(sys.argv[3]),build_directory=Path(sys.argv[4]),'
             'plain=sys.argv[5]=="baseline",arguments=("literal argument","--flag"));'
             'print(json.dumps(value,sort_keys=True))')


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def run():
    output = ROOT / 'prototype-preparation-01'
    output.mkdir(mode=0o700)
    started = time.monotonic()
    index = json.loads((SDK.parent / 'fixed-source-b95780c-index.json').read_text())
    source = {name: files.file(SDK / name)[:2] for name in index['files']}
    assert all(value[0]['sha256'] == index['files'][name] for name, value in source.items())
    tools, _ = files.read(SDK / 'build/go-upstream/toolchain.json')
    assert tools['go'] == '/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go'
    assert tools['weaver'] == str(SDK / 'build/go-upstream/bin/otelc')
    assert tools['bundle_sha256'] == '4a928c69ce269e37c98413c93159713fa7bcd8169c5d6b4de167305dc5ca9bb2'
    settings, _ = files.read(ROOT / 'build-reader-real-01/settings.stdout')
    modules = json.loads((ROOT / 'build-reader-real-01/modules.stdout').read_text())
    build_intent = build.Intent(ROOT / 'prototype-execution-01/bundle',
        files.freeze(ROOT / 'prototype-execution-01/application'), files.freeze(SDK / 'adapters/go'), '.',
        (build.Target('example.com/oteleqfixture.Add', 'main.go', 5, 1),), tools, settings, [modules],
        files.freeze(ROOT / 'prototype-build-01/bundle/context'))
    actual = build.read(build_intent)
    producer = files.freeze(SDK / 'otelc')
    policy = {'schema_version': 3, 'languages': ['go'],
        'resource': {'service_name': 'oteleq-go-consumer-prepared-prototype'},
        'export': {'endpoint': 'http://127.0.0.1:1', 'interval_ms': 1000, 'timeout_ms': 1000, 'shutdown_timeout_ms': 10000},
        'sources': {'include': ['**/*.go'], 'exclude': []},
        'functions': {'include': ['example.com/oteleqfixture.Add'], 'exclude': []},
        'metrics': {'collection': True, 'emission': True, 'histogram_boundaries_seconds': [1e-6, 1e-5, 1e-4, .001, .01, .1, 1.]},
        'traces': {'enabled': True, 'sample_ratio': 1.0}, 'context': {'tasks': False, 'http': False},
        'lifetimes': {'enabled': False, 'include': [], 'exclude': [], 'max_live': 4096, 'release_methods': ['close']},
        'benchmark': {'iterations': 10000, 'samples': 15, 'warmup': 5}}
    write(output / 'caller-policy.json', policy)
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('OTEL', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
    environment['OTELEQ_GO_BUILD_SENTINEL'] = str(output / 'unexpected-application-start')
    results = []
    for plain in (True, False):
        lane = output / ('baseline' if plain else 'instrumented')
        lane.mkdir(mode=0o700)
        intent = prepared.Intent(actual, lane / 'runtime', producer, Path(sys.executable).absolute(),
            python_prepared.file_identity(Path(sys.executable).absolute()), policy, plain, ('literal argument', '--flag'))
        argv = [str(intent.python), '-I', '-S', '-B', '-c', BOOTSTRAP, str(SDK),
                str(output / 'caller-policy.json'), str(intent.runtime), str(actual.intent.directory), lane.name]
        write(lane / 'command.json', {'argv': argv, 'cwd': str(SDK), 'provider': index['head']})
        with (lane / 'stdout').open('xb') as stdout, (lane / 'stderr').open('xb') as stderr:
            process = subprocess.run(argv, cwd=SDK, env=environment, stdout=stdout, stderr=stderr, timeout=20)
        assert process.returncode == 0, (lane / 'stderr').read_text()
        response = json.loads((lane / 'stdout').read_text())
        accepted = prepared.verify(response, intent)
        accepted.verify()
        results.append({'lane': lane.name, 'exit_code': process.returncode,
                        'metadata_files_held': len(accepted.evidence), 'public_response_sha256': files.identity(lane / 'stdout')['sha256']})
    assert not (output / 'unexpected-application-start').exists()
    assert all(files.file(SDK / name)[:2] == value for name, value in source.items())
    actual.verify()
    producer.verify()
    source_hashes = {name: files.identity(CONSUMER / 'adapters/generation' / name)['sha256']
                     for name in ('go_provider.py', 'go_files.py', 'go_build.py', 'go_prepared.py')}
    write(output / 'result.json', {'result': 'passed', 'seconds': round(time.monotonic() - started, 3),
        'provider': index['head'], 'provider_source_files_held': len(source), 'consumer_sources': source_hashes,
        'lanes': results, 'new_target_applications': 0, 'metadata_helper_processes': 2,
        'actual_original_and_private_build_inputs_held': True,
        'scope': 'Development public prepare-only compatibility against frozen build2/config1/health3 provider. No application or embedded SDK was started. Independent helper transformation, generated runtime admission, broader execution and upcoming build3/config2/health4 qualification remain pending.'})
    print(json.dumps({'result': 'passed', 'lanes': len(results), 'new_target_applications': 0, 'metadata_helpers': 2, 'provider_source_files_held': len(source)}))


if __name__ == '__main__':
    run()
