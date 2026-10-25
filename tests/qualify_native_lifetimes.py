"""Exercise genuine public native lifetime workflows with literal state oracles.

This first corpus covers one completed Item per synchronous scalar call. The
consumer checks direct lifetime telemetry; a separate independent raw lifetime
audit and broader zero/censored/startup/live profiles remain required.
"""

import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import native_prepared_receipt as retained
import qualification_storage
from qualify_project_tests import command, toml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
from otelc_capture import path_within

CASES = (('c-completed', 'c', False), ('cpp-completed', 'cpp', False), ('c-state', 'c', True))
SDK_HEAD = 'acb13d7735526448209df37b7e6b98e5717befdb'
PROFILES = {'c': 'native-resources-owned-v1', 'cpp': 'native-objects-owned-v1'}


def digest(path: Path) -> str:
    """Hash only a caller-selected ordinary file."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def source_facts(root: Path) -> dict:
    """Freeze tracked source; build caches and producer-selected paths are excluded."""
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().rstrip('\0').split('\0')
    return {name: retained.identity(root / name) for name in names}


def fixture(folder: Path, language: str, difference: bool, sdk: Path) -> tuple[Path, Path]:
    """Ordinary uninstrumented sources acquire one Item and expose scalar state."""
    if language not in PROFILES:
        raise ValueError('native lifetime corpus requires c or cpp')
    source = folder / 'source'
    for name in ('src', 'include', 'build'):
        (source / name).mkdir(parents=True)
    extension = '.cpp' if language == 'cpp' else '.c'
    relative, helper = 'src/app' + extension, 'src/keep' + extension
    declaration = ('struct Item { int value; explicit Item(int n):value(n){} ~Item(){value=0;} };\n'
                   if language == 'cpp' else 'struct Item { int value; };\n')
    (source / 'include/item.h').write_text('#ifndef NATIVE_ITEM_H\n#define NATIVE_ITEM_H\n' + declaration +
        'void keep_item(struct Item *item);\n#endif\n')
    # The external call prevents -O2 from eliding the intended allocation. Both
    # lanes use the same ordinary two-unit recipe, without link-time optimisation.
    (source / helper).write_text('#include "item.h"\nvoid keep_item(struct Item *item){(void)item;}\n')
    acquire = ('{Item item(amount);keep_item(&item);state+=item.value;}' if language == 'cpp' else
               'struct Item *item=malloc(sizeof *item);if(!item)return -1;'
               'item->value=amount;keep_item(item);state+=item->value;free(item);')
    mutation = 'if(getenv("OTELC_NATIVE_PLAN_FD"))state++;' if difference else ''
    (source / relative).write_text('#include <stdlib.h>\n#include <errno.h>\n#include "item.h"\n' +
        'int state=7;int observed_errno=0;\nint selected(int amount){errno=ECHILD;' + acquire +
        'observed_errno=errno;' + mutation + 'return 42;}\n')
    compiler = os.environ.get('OTELC_CLANGXX' if language == 'cpp' else 'OTELC_CLANG')
    if compiler is None:
        prefix = '/opt/homebrew/opt/llvm@22/bin/' if sys.platform == 'darwin' else '/usr/lib/llvm-22/bin/'
        compiler = prefix + ('clang++' if language == 'cpp' else 'clang')
    units = [relative, helper]
    write(source / 'build/compile_commands.json', [{'directory': str(source / 'build'), 'file': '../' + name,
        'arguments': [compiler, '-I', '../include', '-std=c++17' if language == 'cpp' else '-std=c11',
                      '-O2', '-fexceptions', '-pthread', '-c', '../' + name, '-o', str(index) + '.o']}
        for index, name in enumerate(units)])
    expected = {'type': 'Item', 'creation_path': [0], 'release_path': [0], 'complete': True}
    if language == 'cpp':
        expected['exception_exit'] = False
    configuration = {'schema_version': 1, 'languages': [language],
        'functions': {'include': ['selected*']},
        'fixtures': [{'language': language, 'source': relative, 'function': 'selected*', 'cases': [[5]],
                      'domains': [{'kind': 'integer', 'minimum': 0, 'maximum': 5}], 'lifetimes': [expected]}],
        'adapters': {language: {'backend': 'prepared', 'profile': PROFILES[language],
                               'sdk_build': str(sdk), 'lifetimes': {'include': ['Item']},
                               'compilation_database': 'build/compile_commands.json',
                               'targets': [{'name': 'application', 'units': [{'source': name} for name in units],
                                            'link_flags': ['-pthread']}]}}}
    config = folder / 'generation.toml'
    config.write_text('\n'.join(key + '=' + toml(value) for key, value in configuration.items()) + '\n')
    return source, config


def scalar(language: str, value: int) -> dict:
    return {'kind': 'integer', 'type': language + '.int', 'value': str(value), 'bits': 32, 'signed': True}


class Audit:
    """Count original launches once and retain copied-report and file identities."""

    def __init__(self, root: Path, provider: Path):
        self.registry = retained.Oracle(root, provider)
        self.records = {}
        self.files = {}

    def attempt(self, report: Path, folder: Path, entry: dict, lane: str, witness,
                arguments: tuple[int, ...]) -> None:
        original = self.registry.original(report)
        actual = original.parent / folder.relative_to(report.parent)
        runtime = actual / 'native-runtime'
        request = retained.read(runtime / 'native-request.json')
        application = retained.read(runtime / 'native-application-start.json')
        finished = retained.read(runtime / 'oteleq-native-finish.json')
        assert request['plain'] is (lane == 'baseline') and request['runtime'] == str(runtime)
        assert application['launch_id'] == request['launch_id'] and application['pid'] > 1
        assert finished['application_pid'] == application['pid'] and finished['application_exit_code'] == 0
        held = {'pid': application['pid'], 'folder': str(actual), 'plain': request['plain']}
        assert self.records.setdefault(request['launch_id'], held) == held
        caller = retained.read(actual / 'native-caller/caller.json')
        assert caller['entry'] == entry and caller['arguments'] == list(arguments)
        if lane == 'baseline':
            assert witness is None and not (runtime / 'app/health.json').exists()
            assert retained.read(actual / 'http-capture.json') == {'errors': [], 'bodies': []}
        else:
            verified = retained.read(actual / 'native-verified-lifetimes.json')
            assert witness['functions'] == verified['functions'] == {entry['otelc_runtime_function']: 1}
            assert witness['spans'] == 1 and verified['spans'] == 2 and verified['sdk_pid'] == application['pid']
            assert witness['pending'] == 0 and not any(witness['losses'].values())
            assert witness['raw_otlp_sha256'] == verified['raw_otlp_sha256']
            rows = verified['lifetimes']; assert len(rows) == 1
            expected = {'type_usr': 'c:@S@Item', 'name': 'Item', 'creation_path': [0], 'release_path': [0],
                'complete': True, 'exception_exit': False if entry['language'] == 'cpp' else None,
                'instance': '1', 'boundary': 'destructor_entry' if entry['language'] == 'cpp' else 'free_entry'}
            assert {key: rows[0][key] for key in expected} == expected
            assert type(rows[0]['duration_ns']) is int and rows[0]['duration_ns'] >= 0
            assert verified['health'] == retained.read(runtime / 'app/health.json')
            counters = verified['health']['object_accounting' if entry['language'] == 'cpp' else 'resource_accounting']
            assert all(counters[key] == str(value) for key, value in
                       {'types': 1, 'admitted': 1, 'completed': 1, 'censored': 0}.items())
        for path in (actual / 'expected-lifetimes-before-build.json', actual / 'expected-lifetimes.json'):
            retained.identity(path, private=True)
        for path in actual.rglob('*'):
            if path.is_file():
                value = retained.identity(path, owned=True)
                assert self.files.setdefault(str(path), value) == value

    def finish(self) -> dict:
        for path, facts in self.files.items():
            assert retained.identity(Path(path), owned=True) == facts
        return {'actual_application_records': len(self.records), 'original_evidence_files_held': len(self.files),
                'records': self.records, 'copied_reports': sorted(self.registry.archived),
                'scope': 'Independent literal application state, launch denominator and original file preservation; consumer-checked lifetime receipt'}


def arguments(value: object) -> tuple[int, ...]:
    """The declared scalar domain is independent of report and trial outcomes."""
    assert type(value) is list and len(value) == 1 and type(value[0]) is int and 0 <= value[0] <= 5
    return tuple(value)


def check_report(path: Path, difference: bool, audit: Audit, *, expected: tuple[int, ...] = (5,)) -> int:
    """Equal-but-wrong returns, state, errno, missing repeats or receipt counts refuse."""
    report = retained.read(path)
    assert report['verdict'] == ('different_observed' if difference else 'equivalent_observed')
    assert len(report['cases']) == 1
    result = report['cases'][0]; entry = result['entry']; language = entry['language']
    assert entry['native_options']['profile'] == PROFILES[language]
    assert {row['name'] for row in entry['globals']} == {'state', 'observed_errno'}
    bundle = retained.read(path.parent / result['case'] / 'typed-bundle.json')['cases'][0]
    assert arguments(result['arguments']) == expected
    amount, = expected
    initial = {'global:state': scalar(language, 7), 'global:observed_errno': scalar(language, 0)}
    assert set(bundle['contract']['required_roots']) == set(initial)
    for lane in ('baseline', 'instrumented_on'):
        assert len(bundle[lane]) == 2
        after = {'global:state': scalar(language, 7 + amount + int(difference and lane == 'instrumented_on')),
                 'global:observed_errno': scalar(language, errno.ECHILD)}
        for index, attempt in enumerate(bundle[lane]):
            observed = attempt['observation']
            assert observed['gaps'] == [] and observed['before'] == {'roots': initial, 'nodes': []}
            assert observed['after'] == {'roots': after, 'nodes': []}
            assert observed['outcome'] == {'kind': 'return', 'graph': {'roots': {
                **after, 'result': scalar(language, 42)}, 'nodes': []}}
            execution = attempt['execution']
            assert execution['capture_complete'] and execution['channels'] == {'stdout': [], 'stderr': []}
            assert execution['termination'] == {'kind': 'exit', 'code': 0}
            audit.attempt(path, path.parent / result['case'] / (lane + '-' + str(index)),
                          entry, lane, execution['witness'], expected)
    return 4


def framework(workspace: Path, folder: Path, label: str, difference: bool, audit: Audit,
              *, expected: tuple[int, ...] = (5,)) -> int:
    output = command([sys.executable, '-I', '-B', workspace / 'tests/test_equivalence.py'],
                     folder, label, expected=int(difference))
    rows = [json.loads(line) for line in output.splitlines()]
    assert len(rows) == 1
    return check_report(Path(rows[0]['report']), difference, audit, expected=expected)


def exercise(cli: Path, provider: Path, sdk: Path, root: Path) -> dict:
    audit = Audit(root, provider); results = []
    for name, language, difference in CASES:
        folder = root / name; folder.mkdir()
        source, config = fixture(folder, language, difference, sdk)
        original = {str(path.relative_to(source)): digest(path) for path in source.rglob('*') if path.is_file()}
        workspace = Path(command([cli, 'plan', '--source', source, '--otelc-root', provider,
                                  '--workspace-parent', folder, '--config', config], folder, 'plan'))
        command([cli, 'generate', '--workspace', workspace], folder, 'generate')
        report = folder / 'comparison'
        command([cli, 'run', '--workspace', workspace, '--report-dir', report], folder, 'run', expected=int(difference))
        check_report(report / 'report.json', difference, audit)
        framework(workspace, folder, 'generated-framework', difference, audit)
        target = retained.read(report / 'report.json')['cases'][0]['case']
        replay = json.loads(command([cli, 'replay', '--workspace', workspace, '--case', target],
                                     folder, 'replay', expected=int(difference)))
        check_report(Path(replay['report']), difference, audit)
        exported = folder / 'exported'
        command([cli, 'export-tests', '--workspace', workspace, '--destination', exported, '--apply'], folder, 'export')
        assert {str(path.relative_to(source)): digest(path) for path in source.rglob('*') if path.is_file()} == original
        shutil.rmtree(source)
        framework(exported, folder, 'detached-framework', difference, audit)
        if difference:
            reduced = folder / 'shrinking'
            command([cli, 'shrink', '--workspace', exported, '--case', target, '--report-dir', reduced,
                     '--trials', '8'], folder, 'shrink', expected=1)
            summary = retained.read(reduced / 'shrink.json')
            assert summary['original_arguments'] == [5] and summary['reduced_arguments'] == [0]
            assert summary['status'] == 'candidate_rule_minimal' and summary['source_preserved']
            check_report(reduced / 'original/report.json', True, audit, expected=(5,))
            check_report(reduced / 'confirmation/report.json', True, audit, expected=(0,))
            for trial in summary['trials']:
                check_report(Path(trial['report']), True, audit, expected=arguments(trial['arguments']))
            framework(Path(summary['workspace']), folder, 'reduced-framework', True, audit, expected=(0,))
        results.append({'name': name, 'language': language, 'difference': difference})
    summary = audit.finish()
    return {'claim': 'equivalence over these tests and observations', 'cases': results,
            'actual_application_launches': summary['actual_application_records'], 'audit': summary,
            'consumer_cli_sha256': digest(cli), 'sdk_source': SDK_HEAD,
            'consumer_source': subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                cwd=Path(__file__).resolve().parents[1]).decode().strip(),
            'routes': ['generated', 'framework', 'replay', 'detached', 'scalar-reduction'],
            'remaining': ['independent complete raw lifetime audit and evidence refusals', 'current-source promotion',
                          'zero/censored/exception/startup/live profiles', 'shipping, broader platforms and completion checklist'],
            'qualification_tier': 'genuine public workflow development; no broader profile admission'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--otelc-root', type=Path, required=True)
    parser.add_argument('--sdk-build', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--min-free-bytes', type=int, default=qualification_storage.MIN_FREE_BYTES)
    args = parser.parse_args()
    provider, cli = args.otelc_root.resolve(strict=True), args.cli.resolve(strict=True)
    root, sdk = args.report_dir.resolve(), args.sdk_build.resolve()
    assert not root.exists() and not sdk.exists()
    assert not any(path_within(root, path) or path_within(sdk, path)
                   for path in (provider, Path(__file__).resolve().parents[1]))
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=provider).decode().strip() == SDK_HEAD
    for source in (provider, Path(__file__).resolve().parents[1]):
        assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=source).strip(), 'source checkout is dirty'
    root.mkdir(mode=0o700, parents=True)
    held = {str(path): source_facts(path) for path in (provider, Path(__file__).resolve().parents[1])}
    write(root / 'original-source-facts.json', held)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli), PYTHONDONTWRITEBYTECODE='1')
    with qualification_storage.budget(args.min_free_bytes):
        command([sys.executable, '-B', '-m', 'otelc.native_launch', '--output', sdk], root, 'sdk-build',
                environment={'PYTHONPATH': str(provider)})
        sdk_files = {str(path): retained.identity(path) for path in
                     (sdk / 'native-sdk-build.json', sdk / 'libotelc_native_runtime.so')}
        assert retained.read(sdk / 'native-sdk-build.json')['coverage'] is False
        write(root / 'sdk-original-products.json', sdk_files)
        result = exercise(cli, provider, sdk, root)
        assert {str(path): source_facts(path) for path in map(Path, held)} == held
        assert {name: retained.identity(Path(name)) for name in sdk_files} == sdk_files
        write(root / 'qualification.json', result)
        print(json.dumps(result))


if __name__ == '__main__':
    main()
