"""Recheck the preserved peer reproduction without launching application code."""
import argparse
import json
from pathlib import Path
import sys
import tomllib

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--expect-rejection', action='store_true')
args = parser.parse_args()
sys.path[:0] = [str(args.source / 'adapters/generation'), str(args.source / 'examples')]
import node_telemetry
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

proof = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/oteleq-review-03e95bc/disabled-export-counter-actual.json')
original = json.loads(proof.read_bytes())
application = Path(original['original_actual_attempt'])
plans = list(Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/node-metric-controls/smoke-js-v3').glob('oteleq-run-*/plan.json'))
assert len(plans) == 1
plan = json.loads(plans[0].read_bytes())
function = json.loads((application / 'typed-observation.json').read_bytes())['function_id']
entry = next(row for row in plan['inventory'] if row['otelc_function'] == function)
results = {}
for name, attempt in [('original', application), ('altered', Path(original['altered_attempt']))]:
    http = json.loads((attempt / 'http-capture.json').read_bytes())
    assert not http['errors']
    bodies = [(row['path'], (attempt / row['file']).read_bytes()) for row in http['bodies']]
    service = tomllib.loads((attempt / 'policy.toml').read_text())['resource']['service_name']
    try:
        node_telemetry.witness(attempt, entry, bodies, service, ExportTraceServiceRequest)
    except ValueError as error:
        results[name] = {'accepted': False, 'reason': str(error)}
    else:
        results[name] = {'accepted': True}
assert results['original']['accepted']
assert results['altered']['accepted'] is not args.expect_rejection
if args.expect_rejection:
    assert 'drained emission-off window' in results['altered']['reason']
record = {'consumer_source': str(args.source), 'peer_proof': str(proof),
          'results': results, 'actual_application_relaunches': 0}
args.output.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
