"""Alter retained Python controls/OTLP in memory, preserving every original file."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib
from types import SimpleNamespace
from unittest.mock import patch

import generation
import python_control_receipt
import python_launch
import python_prepared
import python_provider
import qualify_python_generated_origins as origins


def context(folder: Path, entry: dict, provider: Path, catalogue: dict, selected, caches) -> tuple:
    """Reconstruct the checked native execution without an application launch."""
    policy = tomllib.loads((folder / 'policy.toml').read_text())
    service = policy['resource']['service_name']
    assert policy == python_provider.configuration(entry, policy['export']['endpoint'], service)
    tools = {'python': Path(sys.executable).absolute()}
    project = folder / 'project'
    environment = generation.capture.environment(project, tools, service, provider)
    environment['TMPDIR'] = str(folder / 'scratch')
    info = generation.read(folder / 'python-interpreter.json')['observed']
    assert info == origins.interpreter_probe()
    intent = python_prepared.Intent(provider, project, folder / 'python-runtime',
        Path('_oteleq_generated/driver.py'), provider, tools['python'], info, policy,
        folder / 'policy.toml', environment, False, profile=entry['python_profile'])
    facts, selection = selected(folder, entry)
    verified = generation.read(folder / 'python-verified-origins.json')
    run = python_launch.Run(intent, generation.read(folder / python_launch.LAUNCH_FILE), selection,
        verified['expected_sha256'], facts['parent_pid'], caches(folder, entry, facts) if caches else None)
    readonly = SimpleNamespace(read=generation.read, write=origins.compare_receipt)
    checked = python_launch.verify(readonly, run, entry, folder, subprocess.CompletedProcess([], 0), catalogue)
    transport = generation.read(folder / 'http-capture.json')
    assert not transport['errors']
    bodies = [(row['path'], (folder / row['file']).read_bytes()) for row in transport['bodies']]
    return readonly, run, checked, service, bodies


def variants(record: dict) -> dict[str, dict]:
    """Each mutation changes exactly the named control obligation."""
    result = {}
    changed = copy.deepcopy(record); changed['steps'].pop()
    result['missing-step'] = changed
    changed = copy.deepcopy(record); changed['pid'] += 1
    result['wrong-application-pid'] = changed
    changed = copy.deepcopy(record)
    initial = changed['steps'][0]['before']['history'][0]['response']
    initial['collection'] = not initial['collection']
    result['wrong-startup-collection'] = changed
    changed = copy.deepcopy(record)
    off = next(row for row in changed['steps'] if not all(row['requested'].values()))
    off['after']['held_ns'] = 0
    result['short-disabled-window'] = changed
    changed = copy.deepcopy(record); changed['steps'][0]['after']['settled']['sdk_pid'] += 1
    result['wrong-live-sdk-pid'] = changed
    changed = copy.deepcopy(record)
    off = next(row for row in changed['steps'] if not row['requested']['emission'])
    off['before']['history'][2]['response']['effective_emission_off'] = False
    result['missing-export-drain-barrier'] = changed
    changed = copy.deepcopy(record)
    changed['steps'][1]['requested']['collection'] = not changed['steps'][1]['requested']['collection']
    result['changed-requested-state'] = changed
    return result


def check(folder: Path, entry: dict, provider: Path, catalogue: dict, destination: Path,
          *, selected, caches=None) -> dict:
    """A positive retained witness must pass before any altered bytes are refused."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    readonly, run, checked, service, bodies = context(folder, entry, provider, catalogue, selected, caches)
    witness = lambda value: python_launch.witness(readonly, run, checked, folder, entry, value,
                                                  service, ExportTraceServiceRequest)
    witness(bodies)
    record = generation.read(folder / 'python-controls.json')
    destination.mkdir()
    refused = {}
    for name, value in variants(record).items():
        encoded = json.dumps(value, allow_nan=False).encode()
        (destination / (name + '.json')).write_bytes(encoded)
        with patch.object(python_control_receipt, 'read_owned', return_value=encoded):
            try:
                witness(bodies)
            except ValueError as error:
                refused[name] = str(error)
        assert name in refused, name + ' did not refuse altered retained controls'
    changed = []
    for route, raw in bodies:
        if route == '/v1/metrics':
            message = ExportMetricsServiceRequest.FromString(raw)
            for resource in message.resource_metrics:
                for scope in resource.scope_metrics:
                    for metric in scope.metrics:
                        if metric.name == 'otelc.function.calls':
                            for point in metric.sum.data_points:
                                point.as_int += 1
            raw = message.SerializeToString()
        changed.append((route, raw))
    altered = {'extra-collected-call': changed}
    changed = []
    creator = python_provider.creator(entry)
    for route, raw in bodies:
        if route == '/v1/traces':
            message = ExportTraceServiceRequest.FromString(raw)
            for resource in message.resource_spans:
                for scope in resource.scope_spans:
                    retained = [span for span in scope.spans if span.name != creator]
                    del scope.spans[:]
                    scope.spans.extend(retained)
            raw = message.SerializeToString()
        changed.append((route, raw))
    altered['missing-creation-trace'] = changed
    for name, values in altered.items():
        manifest = []
        for index, ((route, raw), (_, original)) in enumerate(zip(values, bodies)):
            if raw != original:
                filename = name + '-' + str(index) + '.bin'
                (destination / filename).write_bytes(raw)
                manifest.append({'index': index, 'route': route, 'file': filename,
                                 'sha256': hashlib.sha256(raw).hexdigest()})
        assert manifest
        generation.write(destination / (name + '.json'), {'replaced_bodies': manifest})
        try:
            witness(values)
        except ValueError as error:
            refused[name] = str(error)
        assert name in refused, name + ' did not refuse altered raw telemetry'
    result = {'refused': refused, 'count': len(refused), 'new_target_applications': 0,
              'scope': 'Seven modified retained-control byte records and two modified raw OTLP corpora; '
                       'control-file reads are substituted in memory. All native/source/SDK checks use '
                       'the original files. This is decoder refusal evidence, not a new execution.'}
    generation.write(destination / 'refusals.json', result)
    return result
