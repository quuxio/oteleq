"""Retained-only generated action checks; no application or producer is started."""

import hashlib
import json
from pathlib import Path
import sys
import tomllib

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / 'adapters/generation'), str(REPO / 'examples')]
import java_action_bindings as compiler
import java_action_receipt as receipt
import java_action_telemetry as telemetry
import java_actions
import java_control_receipt
import java_health
import java_provider
import java_witness as witness
import otelc_capture as capture
import typed_capture
import java_action_fixture as fixture


def read(path: Path):
    return capture.strict_json(path.read_bytes())


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root: Path) -> dict:
    paths = sorted(root.rglob('*'))
    assert all(not path.is_symlink() for path in paths)
    return {path.relative_to(root).as_posix(): sha(path) for path in paths if path.is_file()}


def build(folder: Path) -> None:
    """Bind retained class products to the complete compiler source inventory."""
    record = read(folder / 'build-identities.json')
    assert inventory(folder / 'project') == record['source_sha256']
    assert inventory(folder / 'scratch/classes') == record['classes_sha256']
    for name, field in (('java-compiler.json', 'compiler_metadata_sha256'),
                        ('java-compiler-identity.json', 'compiler_identity_sha256'),
                        ('prepared-application.json', 'prepared_application_sha256')):
        assert sha(folder / name) == record[field]
    identity = read(folder / 'java-compiler-identity.json')
    metadata = read(folder / 'java-compiler.json')
    assert metadata == capture.strict_json((folder / 'build/stdout').read_bytes()) and metadata['success'] is True
    original = folder_from_application(folder)
    application = read(folder / 'prepared-application.json')
    assert len(application['bindings']) == len(record['classes_sha256']) == len(metadata['outputs'])
    for owner, binding in application['bindings'].items():
        relative = Path(binding['source']).relative_to(original / 'project')
        assert sha(folder / 'project' / relative) == binding['source_sha256']
        assert sha(folder / 'scratch/classes' / (owner.replace('.', '/') + '.class')) == binding['class_sha256']
        assert binding['provenance'] == 'oteleq.jdk-file-manager-v1:' + record['compiler_identity_sha256']
    assert identity['compiler_metadata_sha256'] == record['compiler_metadata_sha256']
    # Compiler/JDK identities are independently frozen by the run-level tool
    # manifest; retained compiler copies must still match the opened inputs.
    for name, digest in identity['inputs_sha256'].items():
        path = Path(name)
        selected = folder / path.relative_to(original) if path.is_relative_to(original) else path
        assert sha(selected) == digest


def folder_from_application(folder: Path) -> Path:
    application = read(folder / 'prepared-application.json')
    classes = Path(application['classpath'][0])
    assert classes.parts[-2:] == ('scratch', 'classes')
    return classes.parent.parent


def runtime(folder: Path) -> dict:
    """Recheck the archive independently, preserving the original runtime paths."""
    archived = read(folder / 'runtime-archive.json')
    original = Path(archived['original'])
    assert original.name == 'r' and original.parent.name.startswith('oej-') and not original.exists()
    assert set(inventory(folder / 'sdk-runtime')) == set(archived['files'])
    for name, identity in archived['files'].items():
        assert identity['path'] == str(original / name)
        assert sha(folder / 'sdk-runtime' / name) == identity['sha256']
    return archived


def host(folder: Path, case: dict, pid: int, *, plain: bool) -> tuple[dict, list]:
    """Check the entire ordinary harness plan and retained control history."""
    root = folder / 'java-actions'
    value = witness.read_private(root, 'record.json', witness.MAX_FINAL)
    fields = {'schema_version', 'profile', 'plain', 'case_id', 'attempt_id', 'actions', 'expected',
              'compiler_inputs', 'identity', 'harness', 'armed', 'completed', 'terminal', 'controls'}
    assert set(value) == fields and type(value['schema_version']) is int and value['schema_version'] == 1
    assert value['profile'] == fixture.PROFILE and value['plain'] is plain
    assert value['case_id'] == java_actions.case_id(case) and witness.hex_id(value['attempt_id'], 64)
    assert value['actions'] == java_actions.action_ids(case)
    assert len(value['harness']) == len(value['actions'])
    for index, row in enumerate(value['harness']):
        assert row['pid'] == pid and row['case_id'] == value['case_id'] and row['attempt_id'] == value['attempt_id']
        assert row['action_id'] == value['actions'][index]
        witness.counter(row['thread_id'], positive=True)
        words = row['ready'].removesuffix('\n').split(' ')
        assert row['ready'].endswith('\n') and len(words) == 8 and words[:2] == ['2', 'ready']
        assert words[3:] == [row['case_id'], row['attempt_id'], row['action_id'], str(pid), row['thread_id']]
        assert row['release'] == row['ready'].replace('2 ready ', '2 release ', 1)
    assert value['terminal'] == {key: item for key, item in value['harness'][-1].items() if key != 'release'}
    assert value['compiler_inputs'] == {'bindings_sha256': sha(folder / 'action-bindings/bindings.json'),
                                      'record_sha256': sha(folder / 'action-bindings/compiler-inputs.json')}
    controls, names = [], {'record.json'}
    for index, record in enumerate(value['controls']):
        name = 'controls-' + str(index) + '.json'
        assert record['file'] == name and set(record) == {'file', 'sha256'}
        raw = witness.private_snapshot(root, name, witness.MAX_FINAL).raw
        assert hashlib.sha256(raw).hexdigest() == record['sha256']
        controls.extend(capture.strict_json(raw));names.add(name)
    assert names == {path.name for path in root.iterdir()}
    if plain:
        assert not controls and value['identity'] is None and value['expected'] == {}
        assert value['armed'] == value['completed'] == []
    return value, controls


def scoped(folder: Path, entry: dict, case: dict, value: dict, controls: list,
           bodies: list, service: str, failed: list[bool]) -> tuple[dict, witness.Identity, list]:
    """Bind final SDK data to separately retained compiler and host expectations."""
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    launch = read(folder / 'prepared-launch.json')
    application = read(folder / 'prepared-application.json')
    owner, method = entry['otelc_function'].split('(', 1)[0].rsplit('.', 1)
    declarations, route = java_actions.declarations(entry, owner, list(application['bindings']))
    bindings = read(folder / 'action-bindings/bindings.json')
    compiler.verify(bindings, declarations, application, folder / 'scratch/classes', profile=fixture.PROFILE, route=route)
    metadata = read(folder / 'sdk-runtime/witness.json')
    expected = {key: metadata[key] for key in ('build_sha256', 'selection_sha256', 'policy_sha256', 'tooling_sha256')}
    expected.update({role + '_probe_id': bindings['bindings'][role]['probe_id'] for role in compiler.ROLES})
    expected['route_binding_sha256'] = bindings['route']['sha256']
    assert expected == value['expected'] and metadata['bindings'] == bindings['bindings'] and metadata['route'] == bindings['route']
    assert expected['build_sha256'] == java_provider.digest(launch['application'])
    assert expected['tooling_sha256'] == java_provider.digest(launch['tooling'][:-2])
    assert expected['policy_sha256'] == java_provider.digest(tomllib.loads((folder / 'policy.toml').read_text()))
    assert expected['selection_sha256'] == java_provider.digest({'methods': {owner: [method]}, 'types': [], 'resources': []})
    saved = value['identity']
    assert dict(saved['hashes']) == expected and saved['pid'] == value['harness'][0]['pid']
    identity = witness.Identity(saved['runtime_id'], saved['pid'], tuple(map(tuple, saved['hashes'])), saved['profile'])
    identifiers = set()
    for row in controls:
        reply = witness.reply(row['reply'], row['reply']['request_id'], profile=fixture.PROFILE)
        witness.command(row['operation'], tuple(row['arguments']), reply['request_id'], profile=fixture.PROFILE)
        identity.check(reply)
        assert reply['request_id'] not in identifiers
        identifiers.add(reply['request_id'])
    assert len(value['armed']) == len(value['completed']) == len(failed)
    control_history(value, controls, identity)
    actions = []
    for index, (armed, completed, error) in enumerate(zip(value['armed'], value['completed'], failed)):
        ready, scope = armed['ready'], armed['scope']
        assert ready == {key: item for key, item in value['harness'][index].items() if key != 'release'}
        assert scope['phase'] == 'armed' and scope['route_verified'] is False
        identity.check(completed)
        actions.append(receipt.Action(value['actions'][index], value['case_id'], value['attempt_id'], ready['thread_id'],
            scope['cookie'], scope['sequence'], scope['scope_id'], error))
    final = witness.read_final(folder / 'sdk-runtime', pid=identity.pid, identity=identity)
    received = receipt.qualify(final, identity, actions, receipt.Target(owner, method), bodies,
                               service=service, decoder=ExportTraceServiceRequest.FromString)
    return received, identity, actions


def control_history(value: dict, rows: list, identity: witness.Identity) -> None:
    """A retry or copied completion cannot replace a call's pre-release context."""
    position, pending, status = 0, None, None
    for row in rows:
        operation, reply = row['operation'], row['reply']
        if operation == 'status':
            assert pending is None and status is None and position < len(value['armed'])
            ready, armed = value['armed'][position]['ready'], value['armed'][position]['scope']
            status = witness.context(reply, identity, thread_id=ready['thread_id'],
                                     cookie=armed['cookie'], sequence=armed['sequence'])
            assert status['phase'] == 'ready' and status['route_verified'] is False
            assert all(status[key] is None for key in ('scope_id', 'case_id', 'attempt_id'))
        elif operation == 'arm':
            assert pending is None and status is not None
            ready, pending = value['armed'][position]['ready'], value['armed'][position]['scope']
            assert reply['scope'] == pending
            expected = value['expected']
            arguments = [identity.runtime_id, pending['cookie'], pending['sequence'], value['case_id'], value['attempt_id'],
                expected['build_sha256'], expected['selection_sha256'], expected['tooling_sha256'],
                expected['wrapper_probe_id'], expected['policy_sha256'], ready['thread_id'], expected['route_binding_sha256']]
            assert row['arguments'] == arguments
            status = None
        else:
            assert operation == 'end' and pending is not None
            assert row['arguments'] == [identity.runtime_id, pending['scope_id']]
            retry = reply['error'] in ('root_active', 'incomplete')
            scope = witness.context({**reply, 'error': None} if retry else reply, identity,
                thread_id=pending['thread_id'], cookie=pending['cookie'], sequence=pending['sequence'],
                case_id=value['case_id'], attempt_id=value['attempt_id'], scope_id=pending['scope_id'])
            if retry:
                assert not scope['producer_complete']
            else:
                assert scope['producer_complete'] and reply == value['completed'][position]
                position += 1;pending = None
    assert pending is status is None and position == len(value['armed'])


def attempt(folder: Path, entry: dict, case: dict, observed: dict, *, plain: bool) -> dict:
    """Read and validate actual retained evidence without re-running application code."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    build(folder);runtime(folder)
    contract = {key: observed[key] for key in ('case_id', 'function_id', 'fixture_sha256')}
    assert typed_capture.observation((folder / 'observation').read_bytes(), entry, contract) == observed
    assert read(folder / 'typed-observation.json') == observed
    process, launch = read(folder / 'process.json'), read(folder / 'prepared-launch.json')
    assert type(process['pid']) is int and process['pid'] > 0
    assert process['argv'] == launch['argv'] == read(folder / 'command.json') and launch['plain'] is plain
    captured = read(folder / 'http-capture.json');assert captured['errors'] == []
    bodies = [(row['path'], (folder / row['file']).read_bytes()) for row in captured['bodies']]
    value, controls = host(folder, case, process['pid'], plain=plain)
    assert (folder / 'stdout').read_bytes() == (folder / 'stderr').read_bytes() == b''
    if plain:
        assert not bodies
        return {'pid': process['pid'], 'spans': 0, 'scopes': 0}
    policy = tomllib.loads((folder / 'policy.toml').read_text())
    service = policy['resource']['service_name']
    failed = ([step['outcome']['kind'] == 'error' for step in observed['steps']] if 'steps' in observed
              else [observed['outcome']['kind'] == 'error'])
    received, _, _ = scoped(folder, entry, case, value, controls, bodies, service, failed)
    sizes = list(fixture.SIZES) if entry['otelc_function'] == fixture.COUNTER else [1]
    assert [row['target_entries'] for row in received['actions']] == sizes and received['unscoped_spans'] == 0
    target = receipt.Target(*entry['otelc_function'].split('(', 1)[0].rsplit('.', 1))
    methods = telemetry.method_receipt(bodies, target, ExportTraceServiceRequest.FromString,
                                      ExportMetricsServiceRequest.FromString, service=service)
    record = java_control_receipt.read(folder, entry, process['pid'], bodies, plain=False) if 'sequence_configuration' in entry else None
    collected = telemetry.metric_counts(methods, received, record, bodies)
    expected = sum(size for size, step in zip(sizes, case['sequence']) if step['metrics']['collection']) if record else 1
    assert collected == expected and methods['selected_spans'] == sum(sizes) and methods['unscoped_selected_spans'] == 0
    health = java_health.read(folder / 'sdk-runtime')
    java_health.qualify(health, pid=process['pid'], policy_sha256=launch['policy_sha256'],
        selection_sha256=launch['selection_sha256'], trace_batches=received['trace_batches'], spans=received['spans'],
        metric_batches=received['metric_batches'], metric_points=methods['metric_points'])
    if entry['java_profile'] == 'archive-methods-v1':
        helper = read(folder / 'helper-proof/binding.json')
        assert helper['packages'] and sha(folder / 'sdk-runtime/helpers-extension.jar') == helper['generated_sha256']
    return {'pid': process['pid'], 'spans': received['spans'], 'scopes': len(received['actions']), 'collected': collected}
