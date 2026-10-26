"""Revalidate every retained native observation, private input and executable."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
ACTUAL = ROOT / 'native-actual'
CONSUMER = ROOT / 'consumer'
sys.path[:0] = [str(CONSUMER / 'adapters/generation'), str(CONSUMER / 'examples'), str(CONSUMER / 'tests')]
import harness
import qualify_native_types as qualification
import typed_capture


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text())


runtime = read(ROOT / 'runtime.json')
assert digest(ROOT / 'quux-oteleq') == runtime['cli_sha256']
report = read(ACTUAL / 'comparison/report.json')
assert qualification.check_report(ACTUAL / 'comparison/report.json') == 32
workspace = Path(report['workspace'])
plan = read(workspace / 'plan.json')
assert plan['cli_sha256'] == runtime['cli_sha256']
assert report['source_preserved'] and report['source_sha256'] == plan['source_sha256']
for relative, expected in plan['source_manifest'].items():
    assert digest(Path(plan['source']) / relative) == expected
    assert digest(workspace / 'snapshot' / relative) == expected
for language in ('c', 'cpp'):
    for name, path in plan['tools'][language].items():
        assert digest(Path(path)) == plan['artefacts'][language]['tool:' + name]
blocked = [entry for entry in plan['inventory'] if entry['status'] == 'blocked']
assert report['blocked'] == blocked and report['exit_code'] == 3
attempts = sources = 0
with tempfile.TemporaryDirectory(prefix='native-evidence-', dir=ROOT) as temporary:
    for case in report['cases']:
        folder = ACTUAL / 'comparison' / case['case']
        raw = read(folder / 'bundle.json')['cases'][0]
        typed = read(folder / 'typed-bundle.json')['cases'][0]
        entry = next(item for item in plan['inventory']
                     if item['status'] == 'ready' and case['case'].startswith(item['id'] + '-'))
        assert entry['otelc_function'] == case['function'] == typed['contract']['function_id']
        for lane in ('baseline', 'instrumented_on'):
            for index, (captured, observed) in enumerate(zip(raw[lane], typed[lane])):
                attempt = folder / (lane + '-' + str(index))
                assert captured['source_sha256_before'] == captured['source_sha256_after'] == plan['source_sha256']
                channels = captured['channels']
                for name, filename in (('state-and-outcome', 'observation'), ('stdout', 'stdout'), ('stderr', 'stderr')):
                    assert bytes(channels[name]) == (attempt / filename).read_bytes()
                assert typed_capture.observation(bytes(channels['state-and-outcome']), entry, typed['contract']) == observed['observation']
                assert read(attempt / 'typed-observation.json') == observed['observation']
                assert {**captured, 'channels': {key: value for key, value in channels.items()
                                               if key != 'state-and-outcome'}} == observed['execution']
                expected = Path(temporary) / str(attempts)
                shutil.copytree(workspace / 'snapshot', expected)
                harness.materialise(expected, entry, case['arguments'])
                actual_sources = {path.relative_to(attempt / 'project').as_posix(): digest(path)
                                  for path in (attempt / 'project').rglob('*') if path.is_file()}
                expected_sources = {path.relative_to(expected).as_posix(): digest(path)
                                    for path in expected.rglob('*') if path.is_file()}
                assert actual_sources == expected_sources
                sources += len(expected_sources)
                command = read(attempt / 'command.json')
                binary = Path(command[-1])
                assert binary.is_relative_to(ACTUAL) and binary.is_file() and not binary.is_symlink()
                assert digest(binary) == read(attempt / 'build-identities.json')['application']
                attempts += 1
commands = [path for path in ACTUAL.rglob('command.json')
            if path.parent.name.startswith(('baseline-', 'instrumented_on-'))]
assert attempts == len(commands) == len({digest(path) for path in commands}) == 32
manifest = {path.relative_to(ACTUAL).as_posix(): digest(path)
            for path in sorted(ACTUAL.rglob('*')) if path.is_file()}
(ROOT / 'native-raw-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
result = {'runtime_commit': runtime['source_commit'], 'actual_application_launches': attempts,
          'matching_cases': len(report['cases']), 'blocked_callables': len(blocked),
          'source_preserved': True, 'private_source_records_verified': sources,
          'raw_records': len(manifest), 'raw_manifest_sha256': digest(ROOT / 'native-raw-manifest.json'),
          'verifier_sha256': digest(Path(__file__)),
          'qualifier_sha256': digest(CONSUMER / 'tests/qualify_native_types.py'),
          'complete_value_oracles_verified': True}
(ROOT / 'native-verification.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result), flush=True)
