"""Validate completed older receipts with the corrected, indexed verifier."""
import hashlib
import json
from pathlib import Path
import sys
import tomllib

root = Path(__file__).parent
source = root / 'source-a295b0e'
sys.path[:0] = [str(source / 'tests'), str(source / 'adapters/generation'), str(source / 'examples')]
import node_control_receipt
import node_telemetry
from qualify_node_controls import check_report
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

records, all_identities, receipts = [], set(), 0
for name in ('controls-09e-node24', 'controls-09e-node26'):
    folder = root / name
    qualified = json.loads((folder / 'QUALIFICATION.json').read_bytes())
    assert qualified['actual_applications'] == 192
    identities = set()
    for profile in qualified['profiles']:
        path = folder / (profile['language'] + '-' + profile['compiler'])
        plan = json.loads((Path(profile['workspace']) / 'plan.json').read_bytes())
        entries = {entry['otelc_function']: entry for entry in plan['inventory']}
        reports = sorted(path.rglob('report.json'))
        assert len(reports) == 13
        for report_path in reports:
            report = json.loads(report_path.read_bytes())
            identities |= check_report(report_path, {case['function'].rsplit('.', 1)[-1] for case in report['cases']})
            for case in report['cases']:
                entry = entries[case['function']]
                for lane in ('baseline', 'instrumented_on'):
                    for repeat in range(2):
                        attempt = report_path.parent / case['case'] / (lane + '-' + str(repeat))
                        http = json.loads((attempt / 'http-capture.json').read_bytes())
                        assert not http['errors']
                        bodies = [(row['path'], (attempt / row['file']).read_bytes()) for row in http['bodies']]
                        if lane == 'baseline':
                            node_control_receipt.read(attempt, entry, bodies, plain=True)
                        else:
                            service = tomllib.loads((attempt / 'policy.toml').read_text())['resource']['service_name']
                            node_telemetry.witness(attempt, entry, bodies, service, ExportTraceServiceRequest)
                        receipts += 1
    assert len(identities) == 192 and not all_identities & identities
    all_identities |= identities
    records.append({'corpus': name, 'actual_original_applications': len(identities)})
index = json.loads((root / 'source-a295b0e.json').read_bytes())
for name, digest in index['files'].items():
    assert hashlib.sha256((source / name).read_bytes()).hexdigest() == digest, name
record = {'verifier_commit': index['commit'], 'executor_commit': '09e3fcaaca634a4a12542524c7e872e97053947b',
          'corpora': records, 'retained_receipts_checked': receipts,
          'distinct_original_applications': len(all_identities), 'new_application_launches': 0,
          'scope': 'Corrected post-run verification of recorded09e executions; not new-revision execution qualification'}
assert receipts == len(all_identities) == 384
(root / 'counter-fixed-retained-recheck.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
