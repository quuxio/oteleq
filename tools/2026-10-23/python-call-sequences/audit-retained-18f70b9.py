"""Audit retained complete Python corpora without starting application workers."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).parent
SOURCE = ROOT / 'source-18f70b9'
CLI = ROOT / 'quux-oteleq-18f70b9'
sys.path[:0] = [str(SOURCE / 'tests'), str(SOURCE / 'adapters/generation'), str(SOURCE / 'examples')]
import qualify_python_sequences as sequences
import qualify_receivers as receivers
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(folder: Path) -> dict[str, str]:
    files = sorted(path for path in folder.rglob('*') if path.is_file())
    assert all(not path.is_symlink() for path in files)
    return {str(path.relative_to(folder)): sha(path) for path in files}


def compatible_receipts(folder: Path) -> int:
    checked = 0
    for command in folder.rglob('instrumented_on-*/command.json'):
        attempt = command.parent
        observed = json.loads((attempt / 'typed-observation.json').read_text())
        function = observed['function_id']
        expected_errors = int(function.endswith('.fail'))
        captured = json.loads((attempt / 'http-capture.json').read_text())
        assert captured['errors'] == []
        spans, counts = [], {}
        for body in captured['bodies']:
            raw = (attempt / body['file']).read_bytes()
            if body['path'] == '/v1/traces':
                decoded = ExportTraceServiceRequest.FromString(raw)
                spans += [span for resource in decoded.resource_spans for scope in resource.scope_spans for span in scope.spans]
            else:
                assert body['path'] == '/v1/metrics'
                decoded = ExportMetricsServiceRequest.FromString(raw)
                for resource in decoded.resource_metrics:
                    for scope in resource.scope_metrics:
                        for metric in scope.metrics:
                            if metric.name in ('otelc.function.calls', 'otelc.function.duration'):
                                kind = metric.WhichOneof('data')
                                assert kind == ('sum' if metric.name.endswith('calls') else 'histogram')
                                counts.setdefault(metric.name, []).extend(point.as_int if kind == 'sum' else point.count for point in getattr(metric, kind).data_points)
        assert len(spans) == 1 and spans[0].name == function and not spans[0].parent_span_id
        span = spans[0]
        assert len(span.trace_id) == 16 and any(span.trace_id) and len(span.span_id) == 8 and any(span.span_id)
        assert 0 < span.start_time_unix_nano <= span.end_time_unix_nano
        assert (span.status.code == 2) == bool(expected_errors)
        assert set(counts) == {'otelc.function.calls', 'otelc.function.duration'}
        assert all(values and max(values) == 1 for values in counts.values())
        runtime = json.loads((attempt / 'runtime.json').read_text())
        assert runtime['language'] == 'python' and type(runtime['pid']) is int and runtime['pid'] > 0
        assert runtime['function_calls'] == 1 and runtime['export_finished'] is True
        assert runtime['export_loss'] == 0 and not any(runtime['losses'].values())
        assert runtime['functions'] == {function: {'count': 1, 'unwinds': expected_errors}}
        assert runtime['traces'] == {'active_trees': 0, 'completed_trees': 1, 'losses': {}, 'queued_trees': 0, 'sampled_out_roots': 0, 'pending_contexts': 0}
        checked += 1
    return checked


def compatible(folder: Path) -> dict:
    comparisons = observations = 0
    reports = sorted(folder.rglob('report.json'))
    for path in reports:
        report = json.loads(path.read_text())
        if path.is_relative_to(folder / 'missing-factory') or path.is_relative_to(folder / 'wrong-class'):
            continue
        observations += receivers.check_report(path, len(report['cases']))
        for case in report['cases']:
            result = subprocess.run([str(CLI), 'compare-observations', str(path.parent / case['case'] / 'typed-bundle.json')], capture_output=True, check=False, timeout=30)
            assert result.returncode == case['exit_code'] and json.loads(result.stdout) == case['comparison']
            comparisons += 1
    raw = [p for p in folder.rglob('command.json') if p.parent.name.startswith(('baseline-', 'instrumented_on-'))]
    identities = {sha(p) for p in raw}
    assert len(reports) == 19 and observations == 84 and comparisons == 21
    assert len(raw) == 85 and len(identities) == 81
    for path in folder.rglob('plan.json'):
        plan = json.loads(path.read_text())
        assert all(sha(Path(plan['source']) / name) == expected for name, expected in plan['source_manifest'].items())
    wrong = json.loads((folder / 'wrong-class/comparison/report.json').read_text())
    assert wrong['source_preserved'] and len(wrong['cases']) == 1 and wrong['cases'][0]['exit_code'] == 4
    assert len(list((folder / 'wrong-class/comparison').rglob('command.json'))) == 1
    assert not list((folder / 'wrong-class/comparison').rglob('observation'))
    missing = json.loads((folder / 'missing-factory/comparison/report.json').read_text())
    assert missing['source_preserved'] and len(missing['blocked']) == 1 and not missing['cases']
    assert compatible_receipts(folder) == 42
    return {'reports': len(reports), 'typed_observations': observations, 'comparisons_recomputed': comparisons, 'raw_attempt_folders': len(raw), 'actual_application_launches': len(identities), 'copied_attempts_excluded': len(raw) - len(identities), 'raw_instrumented_receipts': 42, 'complete_raw_and_typed_oracles': True}


def main() -> None:
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    provider = runpy.run_path(str(ROOT / 'run-corpus-18f70b9.py'))['verify']()
    result = {'commit': provider['consumer_commit'], 'started_at': datetime.datetime.now(datetime.UTC).isoformat(), 'new_application_launches': 0, 'identities': provider, 'corpora': {}}
    for name, label in (('qualification-18f70b9-quiet', 'ordered'), ('compatibility-18f70b9', 'single-call')):
        folder = ROOT / name
        before = manifest(folder)
        audit = sequences.retained(folder, CLI) if label == 'ordered' else compatible(folder)
        after = manifest(folder)
        assert before == after, name
        target = ROOT / (name + '-raw-sha256.json')
        with target.open('x') as stream:
            json.dump(before, stream, indent=2)
            stream.write('\n')
        result['corpora'][label] = {'folder': name, **audit, 'raw_records_preserved': len(before), 'raw_manifest': target.name, 'raw_manifest_sha256': sha(target), 'raw_files_unchanged': True}
    assert runpy.run_path(str(ROOT / 'run-corpus-18f70b9.py'))['verify']() == provider
    result['finished_at'] = datetime.datetime.now(datetime.UTC).isoformat()
    with (ROOT / 'retained-audit-18f70b9.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
