"""Qualify Go live controls through generated, retained and promoted test suites."""

import argparse
import copy
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import go_live_fixture as fixture
import go_live_qualification as oracle
import go_live_receipt as receipt
import go_source
import go_cache
import sequence_qualification as shared
import qualification_storage
from qualify_project_tests import command


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def controls(cli: Path, report: Path, folder: Path) -> None:
    """Alter real evidence to check missing calls/fields/witness and panic contracts."""
    case, = (row for row in receipt.read(report)['cases'] if row['function'] == fixture.function('identity'))
    original = receipt.read(report.parent / case['case'] / 'typed-bundle.json')
    for name, (exit_code, verdict) in shared.CONTROL_VERDICTS.items():
        changed = copy.deepcopy(original)
        typed, = changed['cases']
        if name == 'undeclared-intermediate-error':
            typed['contract']['steps'][-1]['expected_baseline'] = {'kind': 'return'}
        else:
            lanes = ('baseline', 'instrumented_on') if name in ('missing-call', 'reordered-calls') else ('instrumented_on',)
            for lane in lanes:
                for attempt in typed[lane]:
                    observed = attempt['observation']
                    if name == 'missing-call':
                        observed['steps'].pop()
                    elif name == 'reordered-calls':
                        observed['steps'].reverse()
                    elif name == 'missing-field':
                        graph = observed['steps'][0]['after']
                        graph['nodes'][16]['fields'].pop('value')
                        # Removing the source field also removes its sole
                        # storage node; an orphan would be incomplete capture.
                        graph['nodes'] = [node for node in graph['nodes'] if node['id'] != 'n17']
                    else:
                        attempt['execution']['witness']['functions'] = {}
        path = folder / (name + '.json')
        write(path, changed)
        actual = json.loads(command([cli, 'compare-observations', path], folder, name, exit_code))
        fixture.exact(actual['verdict'], verdict)


def current_suite(bundle: Path, source: Path, folder: Path, name: str,
                  check_report, *, changed: bool) -> None:
    output = command([sys.executable, '-I', '-B', bundle / 'test_equivalence.py'], folder, name, 1,
                     {'OTELEQ_SOURCE': str(source), 'OTELEQ_WORKSPACE_PARENT': str(folder)})
    rows = [json.loads(line) for line in output.splitlines()]
    methods = (*fixture.METHODS, 'added') if changed else fixture.METHODS
    receipt.require(len(rows) == len(methods) + 1 and rows[0]['project_source'] == str(source), 'incomplete promoted suite')
    seen = []
    for row in rows[1:]:
        path = Path(row['report'])
        check_report(path, 1, changed=changed)
        case, = receipt.read(path)['cases']
        seen.append(case['function'])
    fixture.exact(sorted(seen), sorted(fixture.function(method) for method in methods))


def framework(workspace: Path, folder: Path, name: str, count: int = len(fixture.METHODS),
              *, check_report) -> int:
    return shared.framework(workspace, folder, name, count, check_report)


def run(cli: Path, provider: Path, folder: Path, start: str, catalogue: dict, *, min_free_bytes: int = 0,
        cache_max_bytes: int = go_cache.DEFAULT_MAX_BYTES) -> None:
    """Exercise every maintained route without changing the original application."""
    folder.mkdir(mode=0o700)
    write(folder / 'provider-inputs.json', catalogue)
    cases = folder / 'cases'
    cases.mkdir(mode=0o700)
    inputs = oracle.make_source(cases / 'application')
    write(folder / 'independent-inputs.json', inputs)
    config = cases / 'equivalence.toml'
    cache = go_cache.settings({'directory': str(folder / 'compiler-cache'), 'max_bytes': cache_max_bytes})
    config.write_text(fixture.policy(start, min_free_bytes=min_free_bytes, build_cache=cache))
    workspace = shared.plan_generate(cli, provider, cases, cases / 'application', config, set(fixture.FUNCTIONS))
    check_report = partial(oracle.check_report, start=start, provider=provider)
    run_framework = partial(framework, check_report=check_report)
    shared.exercise_routes(cli, folder, workspace, fixture.METHODS, fixture.FUNCTIONS,
                           check_report, controls, run_framework)
    bundle = folder / 'project-tests'
    arguments = [cli, 'promote', '--workspace', workspace, '--source', cases / 'application', '--destination', bundle]
    planned = json.loads(command(arguments, folder, 'promote-plan'))
    receipt.require(planned['mode'] == 'dry-run' and bool(planned['files']) and not bundle.exists(), 'promotion wrote before apply')
    command([*arguments, '--apply'], folder, 'promote-apply')
    current_suite(bundle, cases / 'application', folder, 'current-original', check_report, changed=False)
    changed = oracle.make_source(folder / 'current-source', changed=True)
    write(folder / 'current-inputs.json', changed)
    current_suite(bundle, folder / 'current-source', folder, 'current-changed', check_report, changed=True)
    fixture.exact(oracle.source_facts(cases / 'application'), inputs)
    fixture.exact(oracle.source_facts(folder / 'current-source', changed=True), changed)


def check_operations(folder: Path, cli: Path, provider: Path) -> None:
    """Require every named operation's exact command and terminal exit receipt."""
    workspace = Path((folder / 'cases/plan.stdout').read_text().strip())
    receipt.require(workspace.is_relative_to(folder / 'cases'), 'foreign planned workspace')
    cases = {fixture.FUNCTIONS[row['function']]: row['case'] for row in receipt.read(folder / 'comparison/report.json')['cases']}
    reduced = Path(receipt.read(folder / 'shrink/shrink.json')['workspace'])
    fixture.exact(str(reduced), str(folder / 'shrink/workspace'))
    bundle = folder / 'project-tests'
    promote = [cli, 'promote', '--workspace', workspace, '--source', folder / 'cases/application', '--destination', bundle]
    expected = {
        'run': (1, [cli, 'run', '--workspace', workspace, '--report-dir', folder / 'comparison']),
        'framework': (1, [sys.executable, workspace / 'tests/test_equivalence.py']),
        'export': (0, [cli, 'export-tests', '--workspace', workspace, '--destination', folder / 'exported', '--apply']),
        'export-run': (1, [cli, 'run', '--workspace', folder / 'exported', '--report-dir', folder / 'export-comparison']),
        'export-framework': (1, [sys.executable, folder / 'exported/tests/test_equivalence.py']),
        'shrink': (1, [cli, 'shrink', '--workspace', workspace, '--case', cases['transient'], '--report-dir', folder / 'shrink', '--trials', '1']),
        'reduced-framework': (1, [sys.executable, reduced / 'tests/test_equivalence.py']),
        'reduced-replay': (1, [cli, 'replay', '--workspace', reduced, '--case', cases['transient']]),
        'promote-plan': (0, promote), 'promote-apply': (0, [*promote, '--apply']),
        'current-original': (1, [sys.executable, '-I', '-B', bundle / 'test_equivalence.py']),
        'current-changed': (1, [sys.executable, '-I', '-B', bundle / 'test_equivalence.py']),
        **{'replay-' + method: (int(method == 'transient'), [cli, 'replay', '--workspace', workspace, '--case', cases[method]])
           for method in fixture.METHODS},
        **{name: (value[0], [cli, 'compare-observations', folder / (name + '.json')])
           for name, value in shared.CONTROL_VERDICTS.items()},
    }
    fixture.exact(sorted(path.name.removesuffix('.started.json') for path in folder.glob('*.started.json')), sorted(expected))
    fixture.exact(sorted(path.stem for path in folder.glob('*.exit')), sorted(expected))
    for name, (exit_code, argv) in expected.items():
        fixture.exact(receipt.read(folder / (name + '.started.json')), {'argv': list(map(str, argv)), 'expected_exit': exit_code})
        receipt.require((folder / (name + '.exit')).read_text() == str(exit_code) + '\n', 'missing terminal operation')
        for suffix in ('stdout', 'stderr'):
            receipt.require((folder / (name + '.' + suffix)).is_file(), 'missing operation channel')
    for name, argv in (
        ('plan', [cli, 'plan', '--source', folder / 'cases/application', '--otelc-root', provider,
                  '--workspace-parent', folder / 'cases', '--config', folder / 'cases/equivalence.toml']),
        ('generate', [cli, 'generate', '--workspace', workspace]),
    ):
        fixture.exact(receipt.read(folder / 'cases' / (name + '.started.json')), {'argv': list(map(str, argv)), 'expected_exit': 0})
        receipt.require((folder / 'cases' / (name + '.exit')).read_text() == '0\n', 'incomplete plan/generation')


def check_routes(folder: Path) -> None:
    """A present operation must also test its complete, independently fixed corpus."""
    def check(path: Path, methods: tuple[str, ...], amount: int) -> None:
        receipt.require(path.is_relative_to(folder), 'foreign route report')
        rows = receipt.read(path)['cases']
        fixture.exact(sorted(row['function'] for row in rows), sorted(fixture.function(name) for name in methods))
        fixture.exact([row['arguments'] for row in rows], [[amount]] * len(methods))

    for name in ('comparison', 'export-comparison'):
        check(folder / name / 'report.json', fixture.METHODS, 7)
    for method in fixture.METHODS:
        summary = receipt.read(folder / ('replay-' + method + '.stdout'))
        check(Path(summary['report']), (method,), 7)
    for name in ('framework', 'export-framework', 'reduced-framework'):
        rows = [json.loads(line) for line in (folder / (name + '.stdout')).read_text().splitlines()]
        reduced = name == 'reduced-framework'
        methods = ('transient',) if reduced else fixture.METHODS
        receipt.require(len(rows) == len(methods), 'missing framework test')
        seen = []
        for row in rows:
            path = Path(row['report'])
            method = next(key for key in fixture.NAMES if fixture.function(key) == receipt.read(path)['cases'][0]['function'])
            check(path, (method,), 0 if reduced else 7)
            seen.append(method)
        fixture.exact(sorted(seen), sorted(methods))
    summary = receipt.read(folder / 'reduced-replay.stdout')
    check(Path(summary['report']), ('transient',), 0)
    for name, changed in (('current-original', False), ('current-changed', True)):
        rows = [json.loads(line) for line in (folder / (name + '.stdout')).read_text().splitlines()]
        methods = (*fixture.METHODS, 'added') if changed else fixture.METHODS
        source = folder / ('current-source' if changed else 'cases/application')
        receipt.require(len(rows) == len(methods) + 1 and rows[0]['project_source'] == str(source), 'incomplete current-source route')
        workspace = Path(rows[0]['workspace'])
        receipt.require(workspace.is_relative_to(folder), 'foreign current-source workspace')
        plan = receipt.read(workspace / 'plan.json')
        fixture.exact(plan['source'], str(source))
        fixture.exact(plan['source_manifest'], {name: hashlib.sha256(raw).hexdigest()
                                               for name, raw in fixture.sources(changed=changed).items()})
        seen = []
        for row in rows[1:]:
            path = Path(row['report'])
            document = receipt.read(path)
            fixture.exact(document['workspace'], str(workspace))
            method = next(key for key in fixture.NAMES if fixture.function(key) == document['cases'][0]['function'])
            check(path, (method,), 7)
            seen.append(method)
        fixture.exact(sorted(seen), sorted(methods))


def evidence_facts(folder: Path) -> dict:
    """Auditing cannot rewrite original evidence or repair its file identities."""
    result = {}
    for path in folder.rglob('*'):
        if path.is_file():
            info = path.stat()
            result[str(path.relative_to(folder))] = (receipt.digest(path), info.st_dev, info.st_ino,
                info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return result


def archived_original(reports: list[Path], folder: Path) -> dict[Path, Path]:
    """Bind the one shrink copy to actual launch IDs in the fixed report registry."""
    archived = folder / 'shrink/original/report.json'
    receipt.require(archived in reports, 'missing copied shrink report')

    def identities(path: Path) -> tuple:
        rows = receipt.read(path)['cases']
        receipt.require(len(rows) == 1, 'copied shrink report needs one case')
        case, = rows
        return tuple(receipt.read(path.parent / case['case'] / (lane + '-' + str(repeat)) /
                                  'go-runtime/go-application-start.json')['launch_id']
                     for lane in ('baseline', 'instrumented_on') for repeat in range(2))

    wanted = identities(archived)
    matches = [path for path in reports if path != archived
               and len(receipt.read(path)['cases']) == 1 and identities(path) == wanted]
    receipt.require(len(matches) == 1 and all(path.is_relative_to(folder) for path in reports),
                    'copied shrink report has no unique original launch evidence')
    original, = matches
    receipt.require(original.read_bytes() == archived.read_bytes(), 'copied shrink report changed')
    receipt.identical_archive(original.parent, archived.parent)
    return {archived: original}


def audit(cli: Path, provider: Path, folder: Path, destination: Path, start: str, catalogue: dict) -> dict:
    """Recompute all comparisons; count copied observations separately from launches."""
    fixture.exact(receipt.read(folder / 'provider-inputs.json'), catalogue)
    fixture.exact(oracle.source_facts(folder / 'cases/application'), receipt.read(folder / 'independent-inputs.json'))
    fixture.exact(oracle.source_facts(folder / 'current-source', changed=True), receipt.read(folder / 'current-inputs.json'))
    before = evidence_facts(folder)
    check_operations(folder, cli, provider)
    check_routes(folder)
    changed_reports = {Path(row['report']) for row in map(json.loads,
        (folder / 'current-changed.stdout').read_text().splitlines()) if 'report' in row}
    reports = sorted(folder.rglob('report.json'))
    receipt.require(len(reports) == 19 and len(changed_reports) == 3, 'incomplete retained report denominator')
    archived = archived_original(reports, folder)
    starts, identities, observed, comparisons = set(), {}, 0, 0
    for path in reports:
        document = receipt.read(path)
        options = {'original': archived[path]} if path in archived else {}
        observed += oracle.check_report(path, len(document['cases']), start=start, provider=provider,
                                        changed=path in changed_reports, **options)
        for case in document['cases']:
            case_folder = path.parent / case['case']
            for lane in ('baseline', 'instrumented_on'):
                for repeat in range(2):
                    attempt = case_folder / (lane + '-' + str(repeat))
                    selected = attempt / 'go-runtime/go-application-start.json'
                    starts.add(selected)
                    actual = receipt.read(selected)
                    existing = identities.setdefault(actual['launch_id'], actual)
                    fixture.exact(actual, existing)
            compare = destination / ('comparison-' + str(comparisons))
            compare.mkdir()
            actual = json.loads(command([cli, 'compare-observations', case_folder / 'typed-bundle.json'], compare, 'compare', case['exit_code']))
            fixture.exact(actual, case['comparison'])
            comparisons += 1
    receipt.require(set(folder.rglob('go-application-start.json')) == starts, 'unaccounted application record')
    fixture.exact([observed, comparisons, len(identities)], [84, 21, 80])
    receipt.require(sum(not row['plain'] for row in identities.values()) == 40, 'SDK process denominator changed')
    fixture.exact(evidence_facts(folder), before)
    return {'claim': 'equivalence over these tests and observations', 'artefact_class': 'diagnostic',
        'backend': 'source-scope-v1', 'startup': start, 'reports': len(reports),
        'actual_application_launches': len(identities), 'sdk_processes': 40,
        'complete_raw_and_typed_observations': observed, 'copied_original_observations': 4,
        'recomputed_comparisons': comparisons, 'altered_comparison_refusals': len(shared.CONTROL_VERDICTS),
        'new_application_launches_during_audit': 0, 'cli_sha256': receipt.digest(cli),
        'original_evidence_files_held': len(before),
        'scope': 'Synchronous private scalar receiver calls with builtin shadows, complete intermediate graphs, '
                 'primitive panic continuation and all four metric states. Generated, replay, unittest, detached '
                 'export, shrink and current-source promotion with changed bodies and new method discovery. '
                 'Other callable/build/context profiles, general invocation attribution and shipping qualification remain open.'}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ('otelc-root', 'report-dir', 'cli', 'audit-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--startup-state', choices=fixture.STARTS, default='both-on')
    parser.add_argument('--retained-only', action='store_true')
    parser.add_argument('--min-free-bytes', type=int, default=qualification_storage.MIN_FREE_BYTES,
                        help='free-space floor checked between commands and during Go builds (default: 8 GiB)')
    parser.add_argument('--cache-max-bytes', type=int, default=go_cache.DEFAULT_MAX_BYTES,
                        help='shared disposable SDK cache bound between builds (default: 1 GiB)')
    args = parser.parse_args(argv)
    if args.min_free_bytes < 0:
        parser.error('--min-free-bytes must be nonnegative')
    if not 1024 ** 2 <= args.cache_max_bytes <= 2 ** 63 - 1:
        parser.error('--cache-max-bytes must be from 1048576 to 9223372036854775807')
    if sys.flags.optimize:
        parser.error('qualification requires assertions; disable Python optimisation')
    cli, provider, folder, destination = (value.resolve() for value in
        (args.cli, args.otelc_root, args.report_dir, args.audit_dir))
    for root in (provider, oracle.ROOT):
        if folder.is_relative_to(root) or destination.is_relative_to(root):
            parser.error('qualification and audit output must be outside both source trees')
    if destination.is_relative_to(folder) or folder.is_relative_to(destination):
        parser.error('audit output must be separate from original evidence')
    destination.mkdir(mode=0o700)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli), PYTHONDONTWRITEBYTECODE='1')
    tools = {'go': Path(shutil.which('go') or '/missing-go'), 'python-host': Path(sys.executable).absolute()}
    catalogue = go_source.artefacts(provider, tools, backend='source-scope-v1')
    if not args.retained_only:
        with qualification_storage.budget(args.min_free_bytes):
            run(cli, provider, folder, args.startup_state, catalogue,
                min_free_bytes=args.min_free_bytes, cache_max_bytes=args.cache_max_bytes)
    result = audit(cli, provider, folder, destination, args.startup_state, catalogue)
    fixture.exact(go_source.artefacts(provider, tools, backend='source-scope-v1'), catalogue)
    write(destination / 'QUALIFICATION.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
