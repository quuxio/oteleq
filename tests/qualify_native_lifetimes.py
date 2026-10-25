"""Exercise genuine public native lifetime workflows with literal state oracles.

This corpus declares zero, one completed, one censored or one caught-unwind Item
per synchronous scalar call. The driver independently audits raw telemetry,
closed final health, promotion and altered copies. Genuine whole-corpus,
escaping-error, startup/live and broader qualification remain required.
"""

import argparse
import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import native_prepared_receipt as retained
import native_lifetime_audit as raw_audit
import native_lifetime_refusals as raw_refusals
import native_lifetime_cases as lifetime_cases
import qualification_storage
from qualify_project_tests import command as execute_command, toml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
from otelc_capture import path_within

CASES = (('c-completed', 'c', False), ('cpp-completed', 'cpp', False), ('c-state', 'c', True),
         ('c-zero', 'c', False), ('cpp-zero', 'cpp', False), ('c-censored', 'c', False),
         ('cpp-censored', 'cpp', False), ('cpp-unwind', 'cpp', False))
CASE_MODES = {'c-completed': 'completed', 'cpp-completed': 'completed', 'c-state': 'completed',
              'c-zero': 'zero', 'cpp-zero': 'zero', 'c-censored': 'censored',
              'cpp-censored': 'censored', 'cpp-unwind': 'unwind'}
SDK_HEAD = 'acb13d7735526448209df37b7e6b98e5717befdb'
PROFILES = {'c': 'native-resources-owned-v1', 'cpp': 'native-objects-owned-v1'}
BASE_CALLS = (('selected', 42),)
PROMOTED_CALLS = (('selected', 43), ('selected_extra', 44))


def command(argv: list, folder: Path, label: str, **options) -> str:
    """Expose stage timing without mixing SDK/application channels into driver output."""
    print(json.dumps({'phase': 'starting', 'case': folder.name, 'stage': label}), flush=True)
    started = time.monotonic()
    output = execute_command(argv, folder, label, **options)
    print(json.dumps({'phase': 'completed', 'case': folder.name, 'stage': label,
                      'seconds': round(time.monotonic() - started, 3)}), flush=True)
    return output


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


def fixture_facts(root: Path) -> dict:
    """Preserve the complete caller-owned fixture before and after each route."""
    return {path.relative_to(root).as_posix(): retained.identity(path)
            for path in root.rglob('*') if path.is_file()}


def fixture(folder: Path, language: str, difference: bool, sdk: Path, *, mode: str = 'completed') -> tuple[Path, Path]:
    """Ordinary sources follow one fixed lifetime boundary and expose scalar state."""
    if language not in PROFILES:
        raise ValueError('native lifetime corpus requires c or cpp')
    contract = lifetime_cases.expected(language, mode)
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
    if mode == 'zero':
        acquire = 'if(amount>0){' + acquire + '}'
    elif mode == 'censored':
        acquire = ('Item *item=new Item(amount);keep_item(item);state+=item->value;' if language == 'cpp'
                   else acquire.replace('free(item);', ''))
    elif mode == 'unwind':
        acquire = 'try{Item item(amount);keep_item(&item);state+=item.value;throw amount;}catch(int){}'
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
    declarations = [{'type': row['name'], **{key: row[key] for key in
                    ('creation_path', 'release_path', 'complete', 'exception_exit') if row[key] is not None}}
                    for row in contract['observations']]
    configuration = {'schema_version': 1, 'languages': [language],
        'functions': {'include': ['selected*']},
        'fixtures': [{'language': language, 'source': relative, 'function': 'selected*',
                      'cases': [list(contract['arguments'])],
                      'domains': [{'kind': 'integer', 'minimum': 0, 'maximum': 5}], 'lifetimes': declarations}],
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
        self.contexts = {}
        self.case_languages = {self.registry.root / name: language for name, language, _ in CASES}
        self.case_modes = {self.registry.root / name: CASE_MODES[name] for name, _, _ in CASES}

    def attempt(self, report: Path, folder: Path, entry: dict, lane: str, witness,
                expected_arguments: tuple[int, ...], *, function: str = 'selected', mode: str = 'completed') -> None:
        original = self.registry.original(report)
        actual = original.parent / folder.relative_to(report.parent)
        languages = [language for root, language in self.case_languages.items() if actual.is_relative_to(root)]
        assert languages == [entry['language']]
        assert [value for root, value in self.case_modes.items() if actual.is_relative_to(root)] == [mode]
        declared = lifetime_cases.expected(entry['language'], mode)
        runtime = actual / 'native-runtime'
        request = retained.read(runtime / 'native-request.json')
        application = retained.read(runtime / 'native-application-start.json')
        finished = retained.read(runtime / 'oteleq-native-finish.json')
        assert request['plain'] is (lane == 'baseline') and request['runtime'] == str(runtime)
        assert application['launch_id'] == request['launch_id']
        assert type(application['pid']) is int and 1 < application['pid'] < 2**31
        retained.same(finished['application_pid'], application['pid'])
        retained.same(finished['application_exit_code'], 0)
        held = {'pid': application['pid'], 'folder': str(actual), 'plain': request['plain'], 'mode': mode}
        caller = retained.read(actual / 'native-caller/caller.json')
        retained.same(caller['entry'], entry)
        assert arguments(caller['arguments']) == expected_arguments
        if lane == 'baseline':
            assert witness is None and not (runtime / 'app/health.json').exists()
            assert retained.read(actual / 'http-capture.json') == {'errors': [], 'bodies': []}
        else:
            verified = retained.read(actual / 'native-verified-lifetimes.json')
            for functions in (witness['functions'], verified['functions']):
                retained.same(functions, {entry['otelc_runtime_function']: 1})
            retained.same(witness['spans'], 1)
            retained.same(verified['spans'], declared['spans'])
            retained.same(verified['sdk_pid'], application['pid'])
            retained.same(witness['pending'], 0)
            for number in witness['losses'].values():
                retained.same(number, 0)
            assert witness['raw_otlp_sha256'] == verified['raw_otlp_sha256']
            rows = verified['lifetimes']; assert len(rows) == declared['admitted']
            if rows:
                expected = {**declared['observations'][0], 'instance': '1', 'boundary': declared['boundary']}
                retained.same({key: rows[0][key] for key in expected}, expected)
                assert type(rows[0]['duration_ns']) is int and rows[0]['duration_ns'] >= 0
            retained.same(verified['health'], retained.read(runtime / 'app/health.json'))
            counters = verified['health']['object_accounting' if entry['language'] == 'cpp' else 'resource_accounting']
            assert all(counters[key] == str(value) for key, value in
                       {'types': declared['admitted'], 'admitted': declared['admitted'],
                        'completed': declared['completed'], 'censored': declared['censored']}.items())
        held['raw_lifetime_receipt'] = raw_audit.verify(actual, entry, witness, plain=lane == 'baseline',
                                                      function=function, mode=mode)
        assert (held['raw_lifetime_receipt'] is None) is (lane == 'baseline')
        retained.same(self.records.setdefault(request['launch_id'], held), held)
        if lane != 'baseline':
            context = {'folder': str(actual), 'entry': copy.deepcopy(entry), 'witness': copy.deepcopy(witness),
                       'function': function, 'mode': mode}
            retained.same(self.contexts.setdefault(request['launch_id'], context), context)
        for path in (actual / 'expected-lifetimes-before-build.json', actual / 'expected-lifetimes.json'):
            retained.identity(path, private=True)
        for path in actual.rglob('*'):
            if path.is_file():
                value = retained.identity(path, owned=True)
                assert self.files.setdefault(str(path), value) == value

    def refusals(self, root: Path) -> dict:
        """Every declared language/boundary capture must refuse altered copies."""
        root.mkdir()
        by_profile = {}
        for context in self.contexts.values():
            language = context['entry']['language']
            profile = language + '-' + context['mode']
            if profile not in by_profile:
                by_profile[profile] = raw_refusals.run(Path(context['folder']), context['entry'],
                                                       context['witness'], root / profile,
                                                       function=context['function'], mode=context['mode'])
        assert set(by_profile) == {language + '-' + CASE_MODES[name] for name, language, _ in CASES}
        assert all(value['count'] == 14 and value['new_application_launches'] == 0 for value in by_profile.values())
        return by_profile

    def finish(self) -> dict:
        for path, facts in self.files.items():
            assert retained.identity(Path(path), owned=True) == facts
        return {'actual_application_records': len(self.records), 'original_evidence_files_held': len(self.files),
                'records': self.records, 'copied_reports': sorted(self.registry.archived),
                'raw_lifetime_receipts': sum(row['raw_lifetime_receipt'] is not None for row in self.records.values()),
                'scope': 'Independent literal application state, raw lifetime/function protobuf, closed SDK health, launch denominator and original file preservation'}


def arguments(value: object) -> tuple[int, ...]:
    """The declared scalar domain is independent of report and trial outcomes."""
    assert type(value) is list and len(value) == 1 and type(value[0]) is int and 0 <= value[0] <= 5
    return tuple(value)


def check_report(path: Path, difference: bool, audit: Audit, *, expected: tuple[int, ...] = (5,),
                 function: str = 'selected', contracts: tuple[tuple[str, int], ...] = BASE_CALLS,
                 mode: str = 'completed') -> int:
    """Equal-but-wrong returns, state, errno, missing repeats or receipt counts refuse."""
    report = retained.read(path)
    assert report['source_preserved'] is True and report['blocked'] == []
    assert report['claim'] == 'equivalence over these tests and observations'
    assert type(report['exit_code']) is int and report['exit_code'] == int(difference)
    assert len(report['cases']) == 1
    result = report['cases'][0]
    assert type(result['exit_code']) is int and result['exit_code'] == int(difference)
    assert result['comparison']['verdict'] == ('different_observed' if difference else 'equivalent_observed')
    assert contracts in (BASE_CALLS, PROMOTED_CALLS) and function in dict(contracts)
    entries = [entry for entry in report['inventory'] if entry['status'] == 'ready']
    assert len(entries) == len(contracts)
    languages = {entry['language'] for entry in entries}; assert len(languages) == 1
    language, = languages; assert language in PROFILES
    expected_functions = {name + ('(int)' if language == 'cpp' else '') for name, _ in contracts}
    assert {entry['otelc_function'] for entry in entries} == expected_functions
    assert len({entry['id'] for entry in entries}) == len(entries)
    selected = function + ('(int)' if language == 'cpp' else '')
    entry, = [entry for entry in entries if entry['otelc_function'] == selected]
    assert result['function'] == entry['otelc_function'] == selected
    assert result['case'] == entry['id'] + '-0'
    assert entry['native_options']['profile'] == PROFILES[language]
    assert {row['name'] for row in entry['globals']} == {'state', 'observed_errno'}
    bundle = retained.read(path.parent / result['case'] / 'typed-bundle.json')['cases'][0]
    assert arguments(result['arguments']) == expected
    amount, = expected
    initial = {'global:state': scalar(language, 7), 'global:observed_errno': scalar(language, 0)}
    retained.same(sorted(bundle['contract']['required_roots']), sorted(initial))
    for lane in ('baseline', 'instrumented_on'):
        assert len(bundle[lane]) == 2
        after = {'global:state': scalar(language, 7 + amount + int(difference and lane == 'instrumented_on')),
                 'global:observed_errno': scalar(language, errno.ECHILD)}
        for index, attempt in enumerate(bundle[lane]):
            observed = attempt['observation']
            retained.same(observed['gaps'], [])
            retained.same(observed['before'], {'roots': initial, 'nodes': []})
            retained.same(observed['after'], {'roots': after, 'nodes': []})
            retained.same(observed['outcome'], {'kind': 'return', 'graph': {'roots': {
                **after, 'result': scalar(language, dict(contracts)[function])}, 'nodes': []}})
            execution = attempt['execution']
            assert execution['capture_complete'] is True
            retained.same(execution['channels'], {'stdout': [], 'stderr': []})
            retained.same(execution['termination'], {'kind': 'exit', 'code': 0})
            audit.attempt(path, path.parent / result['case'] / (lane + '-' + str(index)),
                          entry, lane, execution['witness'], expected, function=function, mode=mode)
    return 4


def framework(workspace: Path, folder: Path, label: str, difference: bool, audit: Audit,
              *, expected: tuple[int, ...] = (5,), mode: str = 'completed') -> int:
    output = command([sys.executable, '-I', '-B', workspace / 'tests/test_equivalence.py'],
                     folder, label, expected=int(difference))
    rows = [json.loads(line) for line in output.splitlines()]
    assert len(rows) == 1
    return check_report(Path(rows[0]['report']), difference, audit, expected=expected, mode=mode)


def promotion(cli: Path, workspace: Path, source: Path, folder: Path, language: str,
              difference: bool, audit: Audit, *, mode: str = 'completed') -> dict:
    """Require fresh original/relocated builds, changed returns and a new callable."""
    folder.mkdir()
    original_facts = fixture_facts(source)
    bundle = folder / 'project-tests'
    argv = [cli, 'promote', '--workspace', workspace, '--source', source, '--destination', bundle]
    planned = json.loads(command(argv, folder, 'promote-plan'))
    assert planned['mode'] == 'dry-run' and planned['files'] and not bundle.exists()
    retained.same(fixture_facts(source), original_facts)
    command([*argv, '--apply'], folder, 'promote-apply')
    retained.same(fixture_facts(source), original_facts)
    parent = folder / 'current-workspaces'; parent.mkdir()
    reports = []

    def current(application: Path, label: str, contracts: tuple[tuple[str, int], ...]) -> int:
        held = fixture_facts(application)
        previous = set(audit.records)
        output = command([sys.executable, '-I', '-B', bundle / 'test_equivalence.py'], folder, label,
                         expected=int(difference), environment={'OTELEQ_SOURCE': str(application),
                                                               'OTELEQ_WORKSPACE_PARENT': str(parent)})
        rows = [json.loads(line) for line in output.splitlines()]
        assert len(rows) == len(contracts) + 1 and rows[0]['project_source'] == str(application)
        observed, seen = 0, []
        for row in rows[1:]:
            path = Path(row['report'])
            assert path.is_relative_to(parent) and path.name == 'report.json'
            value = retained.read(path)
            function = value['cases'][0]['function']
            allowed = {name + ('(int)' if language == 'cpp' else ''): name for name, _ in contracts}
            assert function in allowed
            name = allowed[function]
            observed += check_report(path, difference, audit, function=name, contracts=contracts,
                                     expected=lifetime_cases.expected(language, mode)['arguments'], mode=mode)
            seen.append(name); reports.append(str(path))
        assert sorted(seen) == sorted(name for name, _ in contracts)
        assert len(set(audit.records) - previous) == 4 * len(contracts)
        retained.same(fixture_facts(application), held)
        return observed

    launches = current(source, 'current-original', BASE_CALLS)
    changed = folder / 'current-source'
    shutil.copytree(source, changed)
    unit = changed / ('src/app.cpp' if language == 'cpp' else 'src/app.c')
    body = unit.read_text()
    assert body.count('return 42;') == 1
    updated = body.replace('return 42;', 'return 43;')
    extra = updated[updated.index('int selected(int amount)'):].replace('int selected(', 'int selected_extra(', 1)
    assert extra.count('return 43;') == 1
    unit.write_text(updated + '\n' + extra.replace('return 43;', 'return 44;'))
    database = changed / 'build/compile_commands.json'
    commands = retained.read(database)
    for row in commands:
        assert row['directory'] == str(source / 'build')
        row['directory'] = str(changed / 'build')
    write(database, commands)
    launches += current(changed, 'current-changed', PROMOTED_CALLS)
    assert launches == 12 and len(reports) == 3
    return {'application_observations': launches, 'reports': reports,
            'original_calls': dict(BASE_CALLS), 'changed_calls': dict(PROMOTED_CALLS),
            'fresh_current_source': True, 'relocated_compilation_database': True}


def exercise(cli: Path, provider: Path, sdk: Path, root: Path) -> dict:
    audit = Audit(root, provider); results = []
    for name, language, difference in CASES:
        folder = root / name; folder.mkdir()
        mode = CASE_MODES[name]; expected = lifetime_cases.expected(language, mode)['arguments']
        source, config = fixture(folder, language, difference, sdk, mode=mode)
        original = fixture_facts(source)
        workspace = Path(command([cli, 'plan', '--source', source, '--otelc-root', provider,
                                  '--workspace-parent', folder, '--config', config], folder, 'plan'))
        command([cli, 'generate', '--workspace', workspace], folder, 'generate')
        report = folder / 'comparison'
        command([cli, 'run', '--workspace', workspace, '--report-dir', report], folder, 'run', expected=int(difference))
        check_report(report / 'report.json', difference, audit, expected=expected, mode=mode)
        framework(workspace, folder, 'generated-framework', difference, audit, expected=expected, mode=mode)
        target = retained.read(report / 'report.json')['cases'][0]['case']
        replay = json.loads(command([cli, 'replay', '--workspace', workspace, '--case', target],
                                     folder, 'replay', expected=int(difference)))
        check_report(Path(replay['report']), difference, audit, expected=expected, mode=mode)
        exported = folder / 'exported'
        command([cli, 'export-tests', '--workspace', workspace, '--destination', exported, '--apply'], folder, 'export')
        promoted = promotion(cli, workspace, source, folder / 'promotion', language, difference, audit, mode=mode)
        retained.same(fixture_facts(source), original)
        shutil.rmtree(source)
        framework(exported, folder, 'detached-framework', difference, audit, expected=expected, mode=mode)
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
        results.append({'name': name, 'language': language, 'difference': difference, 'mode': mode, 'promotion': promoted})
    refusal_results = audit.refusals(root / 'raw-evidence-refusals')
    summary = audit.finish()
    assert summary['actual_application_records'] == 240 and summary['raw_lifetime_receipts'] == 120
    return {'claim': 'equivalence over these tests and observations', 'cases': results,
            'actual_application_launches': summary['actual_application_records'], 'audit': summary,
            'raw_evidence_refusals': refusal_results,
            'consumer_cli_sha256': digest(cli), 'sdk_source': SDK_HEAD,
            'consumer_source': subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                cwd=Path(__file__).resolve().parents[1]).decode().strip(),
            'routes': ['generated', 'framework', 'replay', 'detached', 'scalar-reduction', 'current-source-promotion'],
            'remaining': ['genuine qualification of all declared boundary, raw-audit, refusal and promotion routes',
                          'escaping target errors and all startup/live profiles', 'shipping, broader platforms and completion checklist'],
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
