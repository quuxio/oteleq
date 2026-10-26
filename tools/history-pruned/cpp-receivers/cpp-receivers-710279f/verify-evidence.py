"""Revalidate frozen source, every retained attempt and complete C++ value oracles."""
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent
ACTUAL = ROOT / "actual"
CONSUMER = ROOT / "consumer"
MAINTAINED = CONSUMER / 'tests'
sys.path[:0] = [str(CONSUMER / 'adapters/generation'), str(CONSUMER / 'examples'), str(MAINTAINED)]
import harness
import typed_capture
import qualify_cpp_receivers as qualification


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text())


runtime = read(ROOT / 'runtime.json')
assert digest(ROOT / 'quux-oteleq') == runtime['cli_sha256']
assert digest(ROOT / 'consumer-source.tar') == runtime['source_archive_sha256']
sources = 0
with tarfile.open(ROOT / 'consumer-source.tar') as archive:
    for member in archive:
        assert not Path(member.name).is_absolute() and '..' not in Path(member.name).parts
        if member.isdir():
            continue
        assert member.isfile()
        path = CONSUMER / member.name
        assert path.is_file() and not path.is_symlink()
        assert path.read_bytes() == archive.extractfile(member).read()
        sources += 1

assert digest(MAINTAINED / 'qualify_cpp_receivers.py') == digest(CONSUMER / 'tests/qualify_cpp_receivers.py')

positive_reports = refusal_reports = attempts = build_records = 0
commands = []
command_paths = defaultdict(list)
with tempfile.TemporaryDirectory(prefix='cpp-evidence-', dir=ROOT) as temporary:
    for report_path in sorted(ACTUAL.rglob('report.json')):
        report = read(report_path)
        assert report['source_preserved']
        workspace = Path(report['workspace'])
        plan = read(workspace / 'plan.json')
        assert plan['cli_sha256'] == runtime['cli_sha256']
        for name, path in plan['tools']['cpp'].items():
            assert digest(Path(path)) == plan['artefacts']['cpp']['tool:' + name]
        assert report['source_sha256'] == plan['source_sha256']
        for relative, expected in plan['source_manifest'].items():
            assert digest(Path(plan['source']) / relative) == expected
            assert digest(workspace / 'snapshot' / relative) == expected
        if any(part.startswith('refusal-') for part in report_path.relative_to(ACTUAL).parts):
            refusal_reports += 1
            continue
        count = qualification.check_bindings(report_path, len(report['cases'])) if report_path.is_relative_to(ACTUAL / 'bindings') else qualification.check_report(report_path, len(report['cases']))[0]
        positive_reports += 1
        attempts += count
        for case in report['cases']:
            folder = report_path.parent / case['case']
            typed = read(folder / 'typed-bundle.json')['cases'][0]
            raw = read(folder / 'bundle.json')['cases'][0]
            entry = next(item for item in plan['inventory'] if item['otelc_function'] == typed['contract']['function_id'] and item['status'] == 'ready')
            assert typed['contract']['case_id'] == case['case'] and case['case'].startswith(entry['id'] + '-')
            assert entry['status'] == 'ready' and entry['otelc_function'] == case['function']
            assert raw['expected_functions'] == {case['function']: 1}
            for lane in ('baseline', 'instrumented_on'):
                for index, (captured, observed) in enumerate(zip(raw[lane], typed[lane])):
                    attempt = folder / (lane + '-' + str(index))
                    assert captured['source_sha256_before'] == captured['source_sha256_after'] == plan['source_sha256']
                    assert captured['termination'] == {'code': 0, 'kind': 'exit'} and captured['capture_complete']
                    channels = captured['channels']
                    assert bytes(channels['state-and-outcome']) == (attempt / 'observation').read_bytes()
                    assert bytes(channels['stdout']) == (attempt / 'stdout').read_bytes()
                    assert bytes(channels['stderr']) == (attempt / 'stderr').read_bytes()
                    assert typed_capture.observation(bytes(channels['state-and-outcome']), entry, typed['contract']) == observed['observation']
                    assert read(attempt / 'typed-observation.json') == observed['observation']
                    expected_execution = {**captured, 'channels': {key: value for key, value in channels.items() if key != 'state-and-outcome'}}
                    assert expected_execution == observed['execution']
                    expected = Path(temporary) / str(attempts) / str(build_records)
                    expected.mkdir(parents=True)
                    target = expected / entry['path']
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(workspace / 'snapshot' / entry['path'], target)
                    harness.materialise(expected, entry, case['arguments'])
                    actual_sources = {path.relative_to(attempt / 'project').as_posix(): digest(path)
                                      for path in (attempt / 'project').rglob('*') if path.is_file()}
                    expected_sources = {path.relative_to(expected).as_posix(): digest(path)
                                        for path in expected.rglob('*') if path.is_file()}
                    assert actual_sources == expected_sources
                    build_records += len(expected_sources)

for path in sorted(ACTUAL.rglob('command.json')):
    if not path.parent.name.startswith(('baseline-', 'instrumented_on-')):
        continue
    command = read(path)
    binary = Path(command[-1])
    assert binary.is_relative_to(ACTUAL) and binary.is_file() and not binary.is_symlink()
    assert digest(binary) == read(path.parent / 'build-identities.json')['application']
    command_digest = digest(path)
    commands.append(command_digest)
    command_paths[command_digest].append(path)

assert positive_reports == 36 and refusal_reports == 10
assert attempts == 232
counts = qualification.verify_launches(ACTUAL, 235)
assert len(commands) == 239 and len(set(commands)) == 235
duplicates = [paths for paths in command_paths.values() if len(paths) > 1]
assert len(duplicates) == 4 and all(len(paths) == 2 for paths in duplicates)
for paths in duplicates:
    assert sum(path.is_relative_to(ACTUAL / 'shrinking/original') for path in paths) == 1
    assert sum(path.is_relative_to(ACTUAL / 'cases') for path in paths) == 1
assert read(ACTUAL / 'shrinking/shrink.json')['reduced_arguments'] == [0]

manifest = {path.relative_to(ACTUAL).as_posix(): digest(path)
            for path in sorted(ACTUAL.rglob('*')) if path.is_file()}
(ROOT / 'raw-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
result = {'source_files_verified': sources, 'qualified_reports_verified': positive_reports,
          'refusal_reports_verified': refusal_reports, 'qualified_retained_attempts_verified': attempts,
          'qualified_actual_launches': 228, 'copied_original_shrink_attempts': 4,
          'original_copy_relationships_verified': 4,
          **counts, 'refused_application_launches': 7, 'private_source_records_verified': build_records,
          'raw_records': len(manifest), 'raw_manifest_sha256': digest(ROOT / 'raw-manifest.json'),
          'runtime_commit': runtime['source_commit'], 'source_preserved': True,
          'verifier_sha256': digest(Path(__file__)), 'corrected_qualifier_sha256': digest(MAINTAINED / 'qualify_cpp_receivers.py'),
          'scope': 'Frozen completed driver; full original/binding corpus, binary/source/tool checks and complete independent value oracles.'}
(ROOT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result), flush=True)
