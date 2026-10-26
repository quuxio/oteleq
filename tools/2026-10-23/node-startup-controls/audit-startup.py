"""Recheck completed startup profiles without launching another application."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source-c9fef1f'
EXECUTOR = '88ca22d0853ea173c1f5974933333caaf1f3ba42'
VERIFIER = 'c9fef1fa5ab446a628a52647266e8774fdb48da8'
CLI = ROOT / 'quux-oteleq-88ca22d'
CLI_HASH = 'a1c7f718b81f89208505f615efd91014edac76be62439736b2cbec068fffc351'
STATES = ({'collection': True, 'emission': True},
          {'collection': False, 'emission': True},
          {'collection': True, 'emission': False},
          {'collection': False, 'emission': False})
STARTS = ('both-on', 'collection-off', 'emission-off', 'both-off')
sys.path[:0] = [str(SOURCE / 'tests'), str(SOURCE / 'adapters/generation'),
               str(SOURCE / 'examples')]
import qualify_node_controls as controls
import node_telemetry
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files_below(folder):
    for directory, names, files in os.walk(folder):
        names[:] = [name for name in names if not name.startswith('altered-')]
        for name in files:
            yield Path(directory) / name


def witness(attempt, entry):
    capture = read(attempt / 'http-capture.json')
    assert not capture['errors'], attempt
    bodies = [(row['path'], (attempt / row['file']).read_bytes())
              for row in capture['bodies']]
    policy = tomllib.loads((attempt / 'policy.toml').read_text())
    node_telemetry.witness(attempt, entry, bodies,
        policy['resource']['service_name'], ExportTraceServiceRequest)


def audit_profile(folder, row, states):
    assert row['actual_applications'] == 116 and row['source_preserved'] is True
    assert row['initial_metric_state'] == states[0]
    expected_ids = set(map(tuple, row['application_identities']))
    assert len(expected_ids) == len(row['application_identities']) == 116
    retained = row['retained_routes']
    assert retained['actual_applications'] == 52 and retained['evidence_refusals'] == 14
    assert retained['reduced_arguments'] == [1] and retained['changed_return'] == 43
    assert retained['source_preserved'] is True
    profile = folder / (row['language'] + '-' + row['compiler'])
    original = controls.source(row['language'])
    assert (profile / 'application' / ('controls' + row['suffix'])).read_text() == original
    changed_rows = [json.loads(line) for line in
        (profile / 'retained-routes/promoted-changed.stdout').read_text().splitlines()]
    assert len(changed_rows) == 5
    changed_reports = {Path(item['report']) for item in changed_rows[1:]}
    assert len(changed_reports) == 4
    changed_workspace = Path(changed_rows[0]['workspace'])
    assert (changed_workspace / 'snapshot' / ('controls' + row['suffix'])).read_text() == original.replace('return 42;', 'return 43;')
    reports, applications, bundles = [], [], []
    for path in files_below(profile):
        if path.name == 'report.json':
            reports.append(path)
        elif path.name == 'node-source-application.json':
            applications.append(path)
        elif path.name == 'typed-bundle.json':
            bundles.append(path)
    assert len(reports) == 27 and len(applications) == 120 and len(bundles) == 30
    report_ids = set()
    for path in reports:
        report = read(path)
        methods = {case['function'].rsplit('.', 1)[-1] for case in report['cases']}
        assert methods <= set(controls.oracle.METHODS) and methods
        report_ids |= controls.check_report(path, methods,
            result=43 if path in changed_reports else 42, states=states)
    assert report_ids == expected_ids
    actual_ids = set()
    for path in applications:
        attempt = path.parent
        app, request, receipt = read(path), read(attempt / 'node-source-request.json'), read(attempt / 'node-controls.json')
        actual_ids.add((request['runtime'], app['pid']))
        if not receipt['plain']:
            initial = receipt['steps'][0]['before']['history'][0]['status']
            assert {key: initial[key] for key in ('collection', 'emission')} == states[0]
    assert actual_ids == expected_ids
    comparisons = []
    for path in sorted(bundles):
        expected = read(path.parent / 'comparison.json')
        result = subprocess.run([str(CLI), 'compare-observations', str(path)],
            capture_output=True, text=True, timeout=10)
        assert result.returncode in (0, 1), (path, result.stderr)
        assert json.loads(result.stdout) == expected, path
        comparisons.append({'path': str(path.relative_to(ROOT)), 'sha256': digest(path),
            'exit': result.returncode, 'verdict': expected['verdict']})
    plan = read(Path(row['workspace']) / 'plan.json')
    entry = next(item for item in plan['inventory']
                 if item.get('otelc_function') == 'controls.Counter.difference')
    report = read(profile / 'comparison/report.json')
    case = next(item for item in report['cases'] if item['function'].endswith('.difference'))
    witness(profile / 'comparison' / case['case'] / 'instrumented_on-0', entry)
    refusals = []
    for attempt in sorted((profile / 'retained-routes').glob('altered-*')):
        name = attempt.name.removeprefix('altered-')
        recorded = read(profile / 'retained-routes' / (name + '.refusal.json'))
        assert recorded['refused'] is True
        try:
            witness(attempt, entry)
        except ValueError as error:
            assert str(error) == recorded['reason'], (attempt, str(error), recorded)
        else:
            raise AssertionError('Altered actual evidence was accepted: ' + str(attempt))
        refusals.append(name)
    assert len(refusals) == 14
    return {'profile': str(profile.relative_to(ROOT)), 'initial_metric_state': states[0],
        'actual_applications': len(actual_ids), 'raw_receipts': len(applications),
        'copied_receipts_excluded': len(applications) - len(actual_ids),
        'complete_application_reports_rechecked': len(reports),
        'actual_evidence_refusals_rechecked': refusals,
        'typed_comparisons_recomputed': len(comparisons), 'comparisons': comparisons}, actual_ids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--partial', action='store_true')
    args = parser.parse_args()
    index = read(ROOT / 'source-c9fef1f.json')
    assert index['commit'] == VERIFIER
    assert all(digest(SOURCE / name) == expected for name, expected in index['files'].items())
    assert digest(CLI) == CLI_HASH
    rows, all_ids, complete_runs = [], set(), 0
    for runtime in ('node24', 'node26'):
        for offset, start in enumerate(STARTS):
            folder = ROOT / ('controls-c9-' + runtime + '-' + start)
            final = folder / 'QUALIFICATION.json'
            if final.exists():
                record = read(final)
                assert record['actual_applications'] == 348 and len(record['profiles']) == 3
                assert record['cli_sha256'] == CLI_HASH
                complete_runs += 1
                profiles = record['profiles']
            else:
                assert args.partial, 'Missing final qualification: ' + str(folder)
                progress = folder / 'progress.json'
                profiles = read(progress) if progress.exists() else []
            states = STATES[offset:] + STATES[:offset]
            for profile in profiles:
                audited, identities = audit_profile(folder, profile, states)
                assert not all_ids & identities, 'Cross-profile application reuse'
                all_ids |= identities
                rows.append(audited)
                print(json.dumps({key: value for key, value in audited.items()
                    if key not in ('comparisons', 'actual_evidence_refusals_rechecked')}), flush=True)
    assert len(all_ids) == 116 * len(rows)
    if not args.partial:
        assert complete_runs == 8 and len(rows) == 24 and len(all_ids) == 2784
    assert all(digest(SOURCE / name) == expected for name, expected in index['files'].items())
    result = {'executor_commit': EXECUTOR, 'verifier_commit': VERIFIER,
        'cli_sha256': CLI_HASH, 'source_files_preserved': len(index['files']),
        'complete_runs': complete_runs, 'complete_profiles_rechecked': len(rows),
        'actual_applications': len(all_ids), 'raw_receipts': sum(row['raw_receipts'] for row in rows),
        'copied_receipts_excluded': sum(row['copied_receipts_excluded'] for row in rows),
        'actual_evidence_refusals_rechecked': 14 * len(rows),
        'typed_comparisons_recomputed': 30 * len(rows), 'profiles': rows,
        'partial': args.partial,
        'scope': 'Offline checks of completed actual corpora only; zero new application launches. Executor88ca and verifierC9 are distinct. Full provider/tool preservation and final delivery remain separate.'}
    name = 'partial-audit-c9.json' if args.partial else 'final-audit-c9.json'
    (ROOT / name).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'profiles'}), flush=True)


if __name__ == '__main__':
    main()
