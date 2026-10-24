"""Qualify generated origin-profile receivers and retained workflows with literal oracles."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import generation
import python_inputs
import python_launch
import python_prepared
import python_provider
import python_selection
import qualify_python_sequences as legacy
import sequence_qualification as shared
from python_sequence_fixture import FUNCTIONS, METHODS, SOURCE, check_observation, function, raw_observation
from qualify_project_tests import command


def check_report(path: Path, count: int, *, steps: int = 2, compact: bool = False) -> int:
    """Compare every raw and typed boundary against the independent fixture oracle."""
    assert not compact
    report = generation.read(path)
    assert report['source_preserved'] and not report['blocked'] and len(report['cases']) == count
    assert len({case['function'] for case in report['cases']}) == count
    if count == len(METHODS):
        assert {case['function'] for case in report['cases']} == set(FUNCTIONS)
    observed = 0
    for case in report['cases']:
        method = FUNCTIONS[case['function']]
        assert case['exit_code'] == int(method == 'transient')
        assert case['receiver_fixture']['arguments'] == [10]
        bundle = generation.read(path.parent / case['case'] / 'typed-bundle.json')['cases'][0]
        shared.check_contract(bundle, {'arguments', 'receiver', 'global:created', 'static:Counter.total',
                                      'static:Counter.instances', 'static:Counter.shared'}, steps)
        creation = 'src.pkg.state.' + ('make_counter' if method == 'secret' else 'Counter.__init__')
        for lane in ('baseline', 'instrumented_on'):
            assert len(bundle[lane]) == 2
            for index, attempt in enumerate(bundle[lane]):
                observed += 1
                active = lane == 'instrumented_on'
                folder = path.parent / case['case'] / (lane + '-' + str(index))
                assert generation.read(folder / 'observation') == raw_observation(
                    method, case['arguments'][0], active, steps=steps), str(folder)
                check_observation(attempt['observation'], method, case['arguments'][0], active, steps=steps)
                execution = attempt['execution']
                assert execution['channels']['stdout'] == execution['channels']['stderr'] == []
                if active:
                    expected = steps + (int(case['arguments'][0] > 0) + int(steps == 2) if method == 'recursive' else 0)
                    witness = execution['witness']
                    assert witness['functions'] == {case['function']: expected, creation: 1}
                    assert witness['spans'] == expected + 1 and witness['pending'] == 0
                    assert not any(witness['losses'].values())
                else:
                    assert execution['witness'] is None
    return observed


def framework(workspace: Path, folder: Path, name: str, count: int = len(METHODS)) -> int:
    """The deliberate same-return intermediate mutation must fail the unittest."""
    return shared.framework(workspace, folder, name, count, check_report)


def expected_selection(folder: Path, entry: dict) -> tuple:
    """Use literal fixture bytes and caller-owned facts sealed before execution."""
    facts = generation.read(folder / python_launch.ORIGIN_FILE)
    assert facts['python_hexversion'] == sys.hexversion and facts['optimisation'] == 0
    method = FUNCTIONS[entry['otelc_function']]
    assert entry['path'] == 'src/pkg/state.py' and entry['name'] == 'Counter.' + method
    lines = SOURCE.splitlines()
    target_line = next(index for index, text in enumerate(lines, 1) if text.startswith(' def ' + method + '('))
    factory = 'make_counter' if method == 'secret' else 'Counter.__init__'
    factory_line = next(index for index, text in enumerate(lines, 1)
                        if text.startswith('def make_counter(' if method == 'secret' else ' def __init__('))
    assert entry['line'] == target_line
    assert (entry['receiver_fixture']['source_function'], entry['receiver_fixture']['line']) == (factory, factory_line)
    expected = [(entry['name'], entry['line']),
                (entry['receiver_fixture']['source_function'], entry['receiver_fixture']['line'])]
    assert [(row['qualname'], row['line']) for row in facts['selected']] == expected
    selected = []
    for row in facts['selected']:
        path = folder / 'project/src/pkg/state.py'
        assert row['path_hex'] == os.fsencode(path).hex()
        assert row['sha256'] == hashlib.sha256(SOURCE.encode()).hexdigest()
        source = python_selection.Source(os.fsencode(path), SOURCE.encode(), row['device'], row['inode'],
                                         row['mtime_ns'], row['mode'])
        selected.append(python_selection.Selection(source, row['qualname'], row['line']))
    return facts, tuple(selected)


def recheck_attempt(folder: Path, entry: dict, provider: Path, catalogue: dict) -> dict:
    """Recompute source, owner, both signals and final health without new apps."""
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    actual = Path(generation.read(folder / 'command.json')[-1]).parent
    if actual != folder:
        # Shrinking retains a byte-identical copy of the original replay. It
        # remains evidence for that original launch, not a new process.
        assert 'original' in folder.parts and actual.is_dir()
        assert generation.manifest(folder) == generation.manifest(actual)
        return recheck_attempt(actual, entry, provider, catalogue)
    lane = folder.name.split('-')[0]
    assert lane in ('baseline', 'instrumented_on')
    policy = tomllib.loads((folder / 'policy.toml').read_text())
    service = policy['resource']['service_name']
    assert policy == python_provider.configuration(entry, policy['export']['endpoint'], service)
    tools = {'python': Path(sys.executable).absolute()}
    project = folder / 'project'
    environment = generation.capture.environment(project, tools, service, provider)
    environment.update(TMPDIR=str(folder / 'scratch'))
    info = generation.read(folder / 'python-interpreter.json')['observed']
    assert info['version'] == sys.version and info['cache_tag'] == sys.implementation.cache_tag
    # Independently observe the same selected framework launch spelling.
    assert info['argv0'] == sys.orig_argv[0]
    intent = python_prepared.Intent(provider, project, folder / 'python-runtime',
        Path('_oteleq_generated/driver.py'), provider, tools['python'], info, policy,
        folder / 'policy.toml', environment, lane == 'baseline', profile=python_provider.ORIGIN_PROFILE)
    facts, selected = expected_selection(folder, entry)
    assert facts['plain'] is intent.plain
    verified = generation.read(folder / 'python-verified-origins.json')
    run = python_launch.Run(intent, generation.read(folder / python_launch.LAUNCH_FILE), selected,
                            verified['expected_sha256'], facts['parent_pid'])
    def compare_receipt(path, value):
        assert generation.read(path) == value, str(path)
    readonly = SimpleNamespace(read=generation.read, write=compare_receipt)
    result = subprocess.CompletedProcess([], 0)
    checked = python_launch.verify(readonly, run, entry, folder, result, catalogue)
    capture = generation.read(folder / 'http-capture.json')
    bodies = []
    for row in capture['bodies']:
        raw = (folder / row['file']).read_bytes()
        bodies.append((row['path'], raw))
    assert not capture['errors']
    if intent.plain:
        assert not bodies
    else:
        witness = python_launch.witness(readonly, run, checked, folder, entry, bodies, service, ExportTraceServiceRequest)
        bundle = generation.read(folder.parent / 'typed-bundle.json')['cases'][0]
        repeat = int(folder.name.rsplit('-', 1)[1])
        assert witness == bundle[lane][repeat]['execution']['witness']
    return {'supervisor_pid': checked[0].owner.pid, 'application_pid': checked[0].application_pid,
            'sdk_pid': checked[0].sdk_pid, 'plain': intent.plain, 'runtime': str(intent.runtime)}


def retained(folder: Path, cli: Path, provider: Path, catalogue: dict) -> dict:
    """Account for every report and actual process, including framework replays."""
    reports = sorted(folder.rglob('report.json'))
    observations, comparisons = shared.compare_reports(folder, reports, cli, check_report, ())
    identities = []
    for path in reports:
        report = generation.read(path)
        entries = {row['otelc_function']: row for row in report['inventory']}
        for case in report['cases']:
            for lane in ('baseline', 'instrumented_on'):
                for repeat in range(2):
                    identities.append(recheck_attempt(path.parent / case['case'] / (lane + '-' + str(repeat)),
                                                       entries[case['function']], provider, catalogue))
    assert len(identities) == observations and observations > 100
    unique = {row['runtime']: row for row in identities}
    applications = {row['application_pid'] for row in unique.values()}
    owners = {row['supervisor_pid'] for row in unique.values()}
    sdks = {row['sdk_pid'] for row in unique.values() if not row['plain']}
    assert len(applications) == len(owners) == len(unique)
    assert len(sdks) == len(unique) // 2
    assert not applications & owners and not applications & sdks and not owners & sdks
    shared.verify_sources(folder)
    assert python_inputs.artefacts(provider, {'python': Path(sys.executable).absolute()}) == catalogue
    return {'claim': 'equivalence over these tests and observations', 'artefact_class': 'diagnostic',
        'actual_application_launches': len(unique), 'sdk_processes': len(sdks), 'reports': len(reports),
        'copied_original_observations': observations - len(unique),
        'complete_raw_and_typed_observations': observations, 'recomputed_comparisons': comparisons,
        'cases': len(METHODS), 'matching_cases': len(METHODS) - 1, 'same_return_mutation_controls': 1,
        'source_preserved': True, 'inputs_preserved': True, 'python_hexversion': sys.hexversion,
        'cli_sha256': generation.capture.file_digest(cli),
        'scope': 'Explicit origin-v2 synchronous plain receivers, source constructors/factories, serial calls, recursion and exceptions; generated, replayed, unittest, detached and reduced routes. Promotion, scalar/effect workflows, live controls, per-action attribution, cache loaders and shipping qualification remain separate.'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--otelc-root', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--recheck', action='store_true')
    args = parser.parse_args()
    if sys.flags.optimize:
        parser.error('qualification requires assertions; disable Python optimisation')
    cli, provider, folder = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if folder.is_relative_to(provider) or folder.is_relative_to(ROOT):
        parser.error('qualification output must be external to the application and SDK')
    tools = {'python': Path(sys.executable).absolute()}
    before = python_inputs.artefacts(provider, tools)
    if args.recheck:
        assert generation.read(folder / 'provider-inputs.json') == before
    else:
        folder.mkdir(mode=0o700)
        generation.write(folder / 'provider-inputs.json', before)
        os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli), PYTHONDONTWRITEBYTECODE='1')
        workspace = legacy.prepare(cli, provider, folder / 'cases', python_profile=python_provider.ORIGIN_PROFILE)
        source, target = shared.exercise_routes(cli, folder, workspace, METHODS, FUNCTIONS,
            check_report, legacy.controls, framework)
        path = source / 'src/pkg/state.py'
        original = path.read_bytes()
        try:
            path.write_bytes(original + b'\n# changed source must refuse\n')
            command([cli, 'replay', '--workspace', workspace, '--case', target['case']], folder, 'changed-source', 4)
        finally:
            path.write_bytes(original)
    result = retained(folder, cli, provider, before)
    generation.write(folder / ('retained-audit.json' if args.recheck else 'qualification.json'), result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
