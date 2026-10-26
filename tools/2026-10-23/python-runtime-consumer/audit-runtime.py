"""Recompute exact-commit retained runtime evidence without new applications."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
SOURCE = BASE / 'source-72a6001'
sys.path[:0] = [str(SOURCE / 'adapters/generation'), str(SOURCE / 'examples'), str(SOURCE / 'tests')]
import generation
import python_execution
import python_health
import python_inputs
import python_prepared
import python_provider
import python_telemetry
import qualify_python_provider_runtime as qualifier
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


def audit(context: str, provider: str, version: str) -> dict:
    folder = BASE / context
    root = BASE / ('provider-' + provider + '-' + version)
    report = generation.read(folder / 'report.json')
    assert report['actual_application_launches'] == 12 and report['actual_sdk_launches'] == 6
    assert report['source_profile_status'] == 'blocked' and report['source_origin'] == 'unavailable'
    assert report['python_hexversion'] == sys.hexversion
    catalogue = generation.read(folder / 'input-catalogue.json')
    tools = {'python': Path(sys.executable).absolute()}
    assert python_inputs.artefacts(root, tools) == catalogue
    pids, sdk_pids, owners, launches = [], [], [], []
    refusals = spans = metric_points = responses = 0
    for case in qualifier.CASES:
        for repeat in range(2):
            pair = folder / (case + '-' + str(repeat))
            for plain in (True, False):
                lane = pair / ('baseline' if plain else 'instrumented')
                project = lane / 'application'
                assert generation.manifest(project) == {'entry.py': hashlib.sha256(qualifier.source(case)).hexdigest()}
                expected = generation.read(lane / 'expected-request.json')
                service = 'oteleq-python-runtime-' + case + '-' + pair.name
                endpoint = expected['policy']['export']['endpoint']
                entry = {'language': 'python', 'python_backend': 'prepared', 'path': 'entry.py', 'otelc_function': 'entry.workload'}
                policy = python_provider.configuration(entry, endpoint, service)
                environment = generation.capture.environment(lane, tools, service, root)
                intent = python_prepared.Intent(root, project, lane / 'runtime', Path('entry.py'), root, tools['python'],
                    report['interpreter'], policy, lane / 'policy.toml', environment, plain)
                assert python_provider.same(expected, python_prepared.expected_request(intent))
                value = generation.capture.strict_json((lane / 'prepare/stdout').read_bytes())
                known = generation.read(lane / 'owner/process.json')
                caller = generation.read(lane / 'owner-input.json')
                result = generation.read(lane / 'owner-result.json')
                command = python_prepared.expected_command(intent)
                assert known == {'pid': known['pid'], 'argv': command}
                assert caller['argv'] == command and caller['python_hexversion'] == sys.hexversion
                stdout, stderr = (lane / 'owner/stdout').read_bytes(), (lane / 'owner/stderr').read_bytes()
                assert result == {'returncode': 0, 'stdout_sha256': hashlib.sha256(stdout).hexdigest(),
                                  'stderr_sha256': hashlib.sha256(stderr).hexdigest()}
                assert (stdout, stderr) == (b'raw\x00\xff|' + qualifier.CASES[case][2] + b'\n', b'err\x00\xfe\n')
                owner = python_execution.Owner(known['pid'], caller['parent_pid'], tuple(command), result['returncode'], sys.hexversion)
                execution = python_execution.read(intent, value, owner, catalogue)
                pids.append(execution.application_pid); owners.append(owner.pid)
                rows = generation.read(lane / 'raw-otlp.json')
                bodies = []
                for index, row in enumerate(rows):
                    assert row['file'] == str(index) + '.bin'
                    raw = (lane / 'raw-otlp' / row['file']).read_bytes()
                    assert len(raw) == row['size'] and hashlib.sha256(raw).hexdigest() == row['sha256']
                    bodies.append((row['path'], raw))
                http = generation.read(lane / 'http-responses.json')
                assert http['scope'] == 'server response headers; client acknowledgement is not observed'
                assert http['clock'] == 'monotonic_ns' and http['unrecorded_events'] == 0 and len(http['events']) == len(bodies)
                assert {event['body_index'] for event in http['events']} == set(range(len(bodies)))
                for event in http['events']:
                    assert event['status'] == 200 and event['headers_write_failed'] is False
                    assert event['path'] == bodies[event['body_index']][0]
                    assert 0 < event['request_started_ns'] <= event['body_received_ns'] <= event['response_started_ns'] <= event['headers_written_ns'] <= event['handler_finished_ns']
                responses += len(http['events'])
                checked = generation.read(lane / 'checked.json')
                if plain:
                    assert not bodies and checked['received'] is None and execution.sdk_pid is None
                else:
                    decoded = python_telemetry.decode(bodies, execution, service, {1: 'entry.workload'}, ExportTraceServiceRequest, ExportMetricsServiceRequest)
                    assert decoded['code_calls'] == {1: qualifier.CASES[case][3]} and decoded['code_errors'] == {1: qualifier.CASES[case][4]}
                    assert decoded['roots'] == 1 and json.loads(json.dumps(decoded)) == checked['decoded']
                    python_health.read(intent.runtime, execution, python_health.policy_digest(policy), decoded['received'])
                    refused = qualifier.controls(intent, value, owner, catalogue, execution, bodies, service, decoded['received'])
                    assert len(refused) == 8 and refused == checked['altered_evidence_refused']
                    refusals += len(refused); spans += decoded['received']['spans']; metric_points += decoded['received']['metric_points']
                    sdk_pids.append(execution.sdk_pid); launches.append(execution.launch_id)
    assert len(pids) == len(set(pids)) == 12 and len(sdk_pids) == len(set(sdk_pids)) == 6
    assert len(owners) == len(set(owners)) == 12 and len(set(pids + sdk_pids + owners)) == 30
    assert len(set(launches)) == 6 and refusals == report['altered_evidence_refusals'] == 48
    assert python_inputs.artefacts(root, tools) == catalogue
    before = generation.read(BASE / 'source-72a6001-manifest.json')
    assert all(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest for name, digest in before.items())
    raw_manifest = {}
    for directory, names, files in os.walk(folder):
        names.sort()
        for name in sorted(files):
            path = Path(directory) / name
            assert not path.is_symlink() and path.is_file()
            raw_manifest[path.relative_to(folder).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = BASE / (context + '-raw-sha256.json')
    generation.write(manifest, raw_manifest)
    result = {'context': context, 'provider': provider, 'python': sys.version, 'applications': 12, 'SDKs': 6,
        'spans': spans, 'metric_points': metric_points, 'altered_evidence_refusals': refusals, 'http_response_headers_written': responses,
        'client_acknowledgement': 'unobserved', 'raw_files': len(raw_manifest), 'raw_manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
        'catalogue_entries': len(catalogue), 'source_files_held': len(before), 'new_application_launches': 0, 'source_profile_status': 'blocked'}
    generation.write(BASE / (context + '-audit.json'), result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('provider'); parser.add_argument('version'); args = parser.parse_args()
    print(json.dumps(audit('qualified-72a6001-' + args.provider + '-' + args.version, args.provider, args.version)))
