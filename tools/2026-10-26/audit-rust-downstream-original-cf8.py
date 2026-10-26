"""Audit original hosted Rust caller entities with the independent consumer reader."""

import copy
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

BASE = Path('/Users/sclarke/github/oteleq-qualification')
SDK = Path('/Users/sclarke/github/otelc-qualification')
SOURCE = BASE / 'work/oteleq-rust-generated-caller'
OUT = BASE / '2026-10-26/rust-downstream-original-cf8'
HEAD = 'cf8fdb766b5683bd079548f72bdedade985987b6'
RUN = 40267139532
CASES = {
    'linux': (121391893746, 12626494990, '0d1e31b76065184e479f8577932811b93ecd6eac8bfcf720087b024b07a8f5fb'),
    'macos': (121391893586, 12627047591, '3482a6e106bae4498d99b6bca09d8adbfac44b06882b112ed828ecef25e72c5a'),
}
SERVICE = 'otelc-rust-prepared-generated-caller'
FUNCTION = 'original/application.rs::original::workload'
sys.path[:0] = [str(SOURCE / 'adapters/generation'), str(SOURCE / 'examples')]
import native_protocol
import native_telemetry
import rust_telemetry
from otelc_capture import strict_json
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


def gh(endpoint: str, name: str) -> dict:
    """Preserve current official metadata through the account-verifying wrapper."""
    argv = [str(BASE / '2026-10-24/python-live-metrics/env-312/bin/python'),
            str(BASE / '2026-10-20/pause-for-reboot/quux-oteleq-gh.py'), 'api', endpoint]
    environment = os.environ | {'XDG_CACHE_HOME': str(BASE / 'work/gh-cache')}
    result = subprocess.run(argv, env=environment, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    (OUT / name).write_text(result.stdout)
    return strict_json(result.stdout)


def audit(host: str, case: tuple, source: dict) -> dict:
    """Check all ZIP bytes, every HTTP entity and the complete chosen service."""
    job, artifact, sha = case
    job_data = gh(f'repos/quuxio/otelc/actions/jobs/{job}', host + '-job.json')
    assert job_data['run_id'] == RUN and job_data['status'] == 'completed' and job_data['conclusion'] == 'success'
    archive_data = gh(f'repos/quuxio/otelc/actions/artifacts/{artifact}', host + '-artifact.json')
    assert archive_data['workflow_run']['id'] == RUN and archive_data['workflow_run']['head_sha'] == HEAD
    assert archive_data['digest'] == 'sha256:' + sha
    path = SDK / '2026-10-26/rust-generated-callers' / (host + '-original.zip')
    before = path.stat()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        assert len(names) == len(set(names)) and len(names) <= 16384
        member_hashes = {}
        for item in infos:
            name = Path(item.filename)
            assert not name.is_absolute() and '..' not in name.parts and not item.flag_bits & 1
            assert not stat.S_ISLNK(item.external_attr >> 16) and item.file_size <= 32 * 1024 * 1024
            if not item.is_dir(): member_hashes[item.filename] = hashlib.sha256(archive.read(item)).hexdigest()
        assert archive.read('head.txt').decode().strip() == HEAD
        prefix = 'public-case/test_prepared_real_generated_caller_keeps_original_module_and_excludes_helpers/False/'
        document = lambda name: strict_json(archive.read(name).decode())
        request = document(prefix + 'rust-request.json')
        final = document(prefix + 'rust-execution.json')
        assert request['plain'] is False and final['inputs_rechecked'] is True and final['released'] is True
        assert final['process_exit_code'] == final['supervisor_exit_code'] == 0 and final['failures'] == {}
        assert final['request_sha256'] == native_protocol.digest(request)
        health = final['sdk_health']
        observed = []
        entities = 0
        for index, name in enumerate(sorted(n for n in names if n.startswith('public-case/otlp-http/') and n.endswith('.json'))):
            metadata = document(name)
            assert set(metadata) == {'schema_version', 'sequence', 'received_at_unix_ns', 'path',
                'content_encoding', 'body_bytes', 'body_sha256', 'scope'}
            assert type(metadata['schema_version']) is int and metadata['schema_version'] == 1
            assert type(metadata['sequence']) is int and metadata['sequence'] == index
            assert metadata['path'] in ('/v1/traces', '/v1/metrics')
            assert metadata['scope'] == 'received HTTP entity before content decoding; not response/SDK receipt'
            raw = archive.read(name.removesuffix('.json') + '.http-body')
            assert len(raw) == metadata['body_bytes'] and hashlib.sha256(raw).hexdigest() == metadata['body_sha256']
            assert metadata['content_encoding'] in ('', 'gzip')
            body = gzip.decompress(raw) if metadata['content_encoding'] == 'gzip' else raw
            assert len(body) <= native_telemetry.MAX_BYTES
            decoder = ExportTraceServiceRequest if metadata['path'] == '/v1/traces' else ExportMetricsServiceRequest
            message = decoder.FromString(body)
            groups = message.resource_spans if metadata['path'] == '/v1/traces' else message.resource_metrics
            services = {native_telemetry.attributes(group.resource.attributes)['service.name'] for group in groups}
            assert services
            if SERVICE in services:
                assert services == {SERVICE}, 'cannot select one service by rewriting an original body'
                observed.append((metadata['path'], body))
            entities += 1
        caller = document('public-case/caller-inputs.json')
        for role, suffix in (('original', 'original/application.rs'), ('generated', 'drivers/main.rs')):
            raw = archive.read('public-case/caller-compilation/' + suffix)
            assert len(raw) == caller[role]['size'] and hashlib.sha256(raw).hexdigest() == caller[role]['sha256']
        build = document('public-case/caller-compiled/rust-source-build.json')
        assert build['selected'] == [FUNCTION] and build['inputs'] == sorted(
            [caller['original'], caller['generated']], key=lambda row: row['path'])
        producer = document(prefix + 'rust-prepared.json')['producer']
        expected = {name: facts[0] for name, facts in source['source_facts'].items()
                    if name.startswith('otelc/') and name.endswith('.py') and name.count('/') == 1}
        actual = {'otelc/' + Path(row['path']).name: row['sha256'] for row in producer}
        assert actual == expected and len(producer) == len(actual)
        receipt = rust_telemetry.observe(observed, request['policy'], (FUNCTION,), (FUNCTION,),
                                         health, pid=final['application']['pid'])
        assert receipt['functions'] == {FUNCTION: 1} and receipt['spans'] == 1 and receipt['metric_points'] == 4
        rejected = []
        for section, key, value in [('function_accounting', 'registered', '2'),
                                    ('metric_exports', 'units_succeeded', '5')]:
            mutated = copy.deepcopy(health); mutated[section][key] = value
            try:
                rust_telemetry.observe(observed, request['policy'], (FUNCTION,), (FUNCTION,),
                                      mutated, pid=final['application']['pid'])
            except ValueError:
                rejected.append(section)
            else:
                raise AssertionError('altered original-health units were accepted')
    after = path.stat()
    facts = lambda row: (row.st_dev, row.st_ino, row.st_mode, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
    assert facts(before) == facts(after) and hashlib.sha256(path.read_bytes()).hexdigest() == sha
    return {'host': host, 'head': HEAD, 'run': RUN, 'job': job, 'artifact': artifact,
            'whole_zip_sha256': sha, 'original_zip_members_crc_checked': len(member_hashes),
            'member_sha256': member_hashes, 'original_http_entities_checked': entities,
            'generated_caller_receipt': receipt, 'altered_health_refusals': rejected,
            'producer_files_bound_to_frozen_source': len(expected)}


def main() -> None:
    """Retain current producer/source identity and original Linux/macOS observations."""
    OUT.mkdir(exist_ok=False)
    source = json.loads((SDK / '2026-10-26/rust-generated-callers/source/source.json').read_text())
    assert source['head'] == HEAD
    spec = importlib.util.spec_from_file_location('source_guard', BASE / '2026-10-26/review-python-label-bound.py')
    guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
    held = guard.check_source(source)
    reader = SOURCE / 'adapters/generation/rust_telemetry.py'
    reader_hash = hashlib.sha256(reader.read_bytes()).hexdigest()
    run = gh(f'repos/quuxio/otelc/actions/runs/{RUN}', 'run.json')
    assert run['head_sha'] == HEAD and run['status'] == 'completed' and run['conclusion'] == 'success'
    results = [audit(host, value, source) for host, value in CASES.items()]
    assert guard.check_source(source) == held and hashlib.sha256(reader.read_bytes()).hexdigest() == reader_hash
    result = {'status': 'pass for original generated public Rust caller function receipt',
              'consumer_reader_sha256': reader_hash, 'source_preservation': held, 'hosts': results,
              'new_application_launches': 0, 'compiler_builds': 0, 'sdk_builds': 0,
              'limits': 'Retained original bytes and historical runner statements only. No fresh kernel/stat '
              'recertification, executable-image proof, full compiler/dependency closure, original HTTP '
              'headers/responses, Collector forwarding or oteleq generated/backend admission. '
              'Other services and drop/live schedules are outside this fixed-function receipt audit.'}
    (OUT / 'review.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': result['status'], 'hosts': [
        {k: item[k] for k in ('host', 'original_http_entities_checked', 'producer_files_bound_to_frozen_source')}
        | {'spans': item['generated_caller_receipt']['spans'],
           'metric_points': item['generated_caller_receipt']['metric_points']} for item in results]}))


if __name__ == '__main__':
    main()
