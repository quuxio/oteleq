"""Generated Python orchestration cannot substitute producer-selected intent."""

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / 'adapters/generation'), str(REPO / 'examples')]
import generation
import python_launch as launch
import python_telemetry
import qualify_python_generated_origins as qualifier
from test_generation_python_execution import VERSION, fixture
from test_generation_python_provider import response
from test_generation_python_telemetry import traces


def entry() -> dict:
    return {'language': 'python', 'python_backend': 'prepared', 'python_profile': launch.provider.ORIGIN_PROFILE,
            'path': 'entry.py', 'name': 'workload', 'line': 1, 'otelc_function': 'entry.workload'}


def negotiated(value: dict) -> dict:
    """Supply literal, complete public negotiation independently of launch output."""
    provider = launch.provider
    policy = provider.configuration(value, 'http://127.0.0.1:4318', 'oteleq-python-provider')
    return {**value, 'python_provider': {'status': 0,
        'request': provider.policy(value, 'http://127.0.0.1:4318', 'oteleq-python-provider'),
        'protocols': provider.ORIGIN_PROTOCOLS, 'stdout': json.dumps(response(policy)), 'resolved': response(policy)}}


def interpreter_response() -> bytes:
    return json.dumps({'version': sys.version, 'cache_tag': sys.implementation.cache_tag,
                       'argv0': '/actual/framework/python'}).encode()


def wire_run(root: Path, *, plain: bool = False) -> tuple:
    """Use independent synthetic J2 wire fixtures and real consumer readers."""
    intent, document, owner, catalogue = fixture(root, plain=plain, profile=launch.provider.ORIGIN_PROFILE)
    folder = root / 'attempt'; folder.mkdir()
    generation.write(folder / launch.ORIGIN_FILE, {'declared': 'before launch'})
    generation.write(folder / launch.LAUNCH_FILE, document)
    generation.write(folder / 'python-expected-request.json', launch.prepared.expected_request(intent))
    generation.write(folder / 'process.json', {'pid': owner.pid, 'argv': list(owner.argv)})
    selected = launch.selected_source(intent.project, entry())
    run = launch.Run(intent, document, selected, generation.capture.file_digest(folder / launch.ORIGIN_FILE), owner.parent_pid)
    return run, folder, catalogue


class PythonLaunchTests(unittest.TestCase):
    def test_retained_receipts_normalise_code_keys_and_preserve_integer_value_types(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'receipt.json'
            value = {'code_calls': {1: 3, 2: 4, 10: 9}, 'code_errors': {1: 0, 2: 0, 10: 1}}
            generation.write(path, value)
            before = path.read_bytes()
            qualifier.compare_receipt(path, value)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(generation.read(path)['code_calls'], {'1': 3, '2': 4, '10': 9})
            for changed in ({**value, 'code_calls': {1: 2, 2: 4, 10: 9}},
                            {**value, 'code_errors': {1: False, 2: 0, 10: 1}},
                            {**value, 'code_calls': {1: 3, 2: 4, 11: 9}}, {'code_calls': value['code_calls']}):
                generation.write(path, changed)
                with self.subTest(changed=changed), self.assertRaises(AssertionError):
                    qualifier.compare_receipt(path, value)
            with self.assertRaises(ValueError):
                qualifier.compare_receipt(path, {'code_calls': {1: 2, '1': 3}})

    def test_qualifier_observes_native_argv0_instead_of_its_own_launch_spelling(self):
        with patch.dict(qualifier.os.environ, {'PATH': 'tools', 'PYTHONPATH': 'hook', 'GH_TOKEN': 'fake'}, clear=True), \
             patch.object(qualifier.subprocess, 'run', return_value=SimpleNamespace(stdout=interpreter_response())) as run:
            value = qualifier.interpreter_probe()
        self.assertEqual(value['argv0'], '/actual/framework/python')
        self.assertEqual(run.call_args.args[0][:5], [str(Path(sys.executable).absolute()), '-I', '-S', '-B', '-c'])
        self.assertEqual(run.call_args.kwargs['env'], {'PATH': 'tools'})
        self.assertTrue(run.call_args.kwargs['check'])

    def test_qualifier_refuses_oversized_or_incorrect_interpreter_probe_results(self):
        for raw in (b' ' * 4097, b'null', b'{}', b'{"version":"foreign","cache_tag":"foreign","argv0":"python"}'):
            with self.subTest(raw=raw[:40]), \
                 patch.object(qualifier.subprocess, 'run', return_value=SimpleNamespace(stdout=raw)), \
                 self.assertRaises(AssertionError):
                qualifier.interpreter_probe()

    def test_selected_source_includes_exact_existing_factory_and_constructor_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); (root / 'entry.py').write_text('source')
            for name in ('make_counter', 'Counter.__init__'):
                chosen = {**entry(), 'name': 'Counter.add', 'line': 7,
                          'receiver_fixture': {'source_function': name, 'line': 3}}
                selected = launch.selected_source(root, chosen)
                self.assertEqual([(item.qualname, item.line) for item in selected], [('Counter.add', 7), (name, 3)])
                self.assertEqual(selected[0].source, selected[1].source)
            self.assertEqual(len(launch.selected_source(root, {**entry(), 'receiver_fixture': {'source_function': None}})), 1)

    def test_actual_wire_readers_bind_both_lanes_and_preserve_selected_code_ids(self):
        for plain in (False, True):
            with self.subTest(plain=plain), tempfile.TemporaryDirectory() as temporary:
                run, folder, catalogue = wire_run(Path(temporary).resolve(), plain=plain)
                with patch.object(launch, 'sys', SimpleNamespace(hexversion=VERSION)):
                    execution, functions = launch.verify(generation, run, entry(), folder,
                        subprocess.CompletedProcess([], 0), catalogue)
                self.assertEqual(functions, {} if plain else {1: 'entry.workload'})
                value = generation.read(folder / 'python-verified-origins.json')
                self.assertEqual(value['application_pid'], execution.application_pid)
                self.assertEqual(value['selected'][0]['matches'], [
                    {'root': 77, 'execution': 91, 'member': 9, 'sdk': None if plain else 1}])

    def test_altered_prelaunch_facts_launch_process_source_and_parent_refuse(self):
        mutations = ('facts', 'launch', 'request', 'process', 'source', 'parent', 'exit', 'selection')
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                run, folder, catalogue = wire_run(Path(temporary).resolve())
                chosen, result = entry(), subprocess.CompletedProcess([], 0)
                if mutation in ('facts', 'launch'):
                    generation.write(folder / (launch.ORIGIN_FILE if mutation == 'facts' else launch.LAUNCH_FILE), {})
                elif mutation == 'request':
                    generation.write(folder / 'python-expected-request.json', {})
                elif mutation == 'process':
                    generation.write(folder / 'process.json', {'pid': 502, 'argv': ['foreign']})
                elif mutation == 'source':
                    (run.intent.project / 'entry.py').write_text('changed')
                elif mutation == 'parent':
                    run = replace(run, parent_pid=900)
                elif mutation == 'exit':
                    result.returncode = 1
                else:
                    chosen = {**chosen, 'line': 2}
                with patch.object(launch, 'sys', SimpleNamespace(hexversion=VERSION)), self.assertRaises(ValueError):
                    launch.verify(generation, run, chosen, folder, result, catalogue)

    def test_prepare_has_fixed_isolated_api_and_does_not_execute_returned_argv(self):
        for lane in ('baseline', 'instrumented_on'):
            with self.subTest(lane=lane), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                sdk, project, folder = (root / name for name in ('sdk', 'project', 'attempt'))
                for directory in (sdk, project, folder):
                    directory.mkdir()
                (project / 'entry.py').write_text('def workload(): return 1\n')
                driver = project / 'driver.py'; driver.write_text('generated caller')
                config = folder / 'policy.toml'; config.write_text('schema_version=3\n')
                def prepare_only(*args, **kwargs):
                    if args[3].name == 'python-interpreter':
                        return subprocess.CompletedProcess([], 0, interpreter_response(), b'')
                    (folder / 'python-runtime').mkdir(mode=0o700)
                    return subprocess.CompletedProcess([], 0, b'{"command":["untrusted"]}', b'')
                workflow = SimpleNamespace(write=generation.write, execute=Mock(side_effect=prepare_only))
                tools = {'python': Path(sys.executable).absolute()}
                with patch.object(launch.prepared, 'verify') as verify, \
                     patch.object(launch.prepared, 'expected_request', return_value={'independent': 'request'}), \
                     patch.object(launch.python_inputs, 'artefacts', return_value={'frozen': 'digest'}):
                    run = launch.prepare(workflow, sdk, project, negotiated(entry()), driver, tools,
                                         {'PYTHONDONTWRITEBYTECODE': '1'}, folder, config, lane, {'frozen': 'digest'})
                command = workflow.execute.call_args.args[0]
                self.assertEqual(command[:6], [tools['python'], '-I', '-S', '-B', '-c', launch.BOOTSTRAP])
                self.assertEqual(command[6:], [sdk, config, folder / 'python-runtime', project, Path('driver.py'),
                                              'plain' if lane == 'baseline' else 'instrumented'])
                self.assertEqual(run.intent.profile, launch.provider.ORIGIN_PROFILE)
                self.assertEqual(run.intent.plain, lane == 'baseline')
                self.assertEqual(run.intent.interpreter['argv0'], '/actual/framework/python')
                self.assertEqual(run.selected[0].source.content, b'def workload(): return 1\n')
                self.assertEqual(verify.call_args.args, (run.launch, run.intent, {'frozen': 'digest'}))
                self.assertNotIn('untrusted', launch.prepared.expected_command(run.intent))

    def test_prepare_refuses_other_interpreters_optimisation_failed_api_and_changed_inputs(self):
        for fault in ('python', 'optimisation', 'api', 'catalogue', 'source'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                (root / 'entry.py').write_text('def workload(): return 1\n')
                config = root / 'policy.toml'; config.write_text('schema_version=3\n')
                tools = {'python': Path('/other/python') if fault == 'python' else Path(sys.executable).absolute()}
                environment = {'PYTHONOPTIMIZE': 'invalid'} if fault == 'optimisation' else {}
                def execute(*args, **kwargs):
                    if args[3].name == 'python-interpreter':
                        return subprocess.CompletedProcess([], 0, interpreter_response(), b'')
                    if fault == 'source':
                        (root / 'entry.py').write_text('changed')
                    return subprocess.CompletedProcess([], 1 if fault == 'api' else 0, b'{}', b'')
                workflow = SimpleNamespace(write=generation.write, execute=execute)
                with patch.object(launch.prepared, 'verify'), \
                     patch.object(launch.prepared, 'expected_request', return_value={}), \
                     patch.object(launch.python_inputs, 'artefacts', return_value={'changed': 'input'} if fault == 'catalogue' else {}), \
                     self.assertRaises(ValueError):
                    launch.prepare(workflow, root, root, negotiated(entry()), root / 'entry.py', tools,
                                   environment, root, config, 'baseline', {})

    def test_interpreter_probe_cannot_use_environment_hooks_or_fabricated_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            for response_value, status in (({}, 0), ({'version': 'other', 'cache_tag': 'wrong', 'argv0': 'python'}, 0),
                                            ({'version': sys.version, 'cache_tag': sys.implementation.cache_tag, 'argv0': None}, 0),
                                            (json.loads(interpreter_response()), 1)):
                workflow = SimpleNamespace(write=generation.write, execute=Mock(return_value=
                    subprocess.CompletedProcess([], status, json.dumps(response_value).encode(), b'')))
                with self.subTest(response=response_value, status=status), self.assertRaises(ValueError):
                    launch.interpreter(workflow, Path(sys.executable), folder,
                        {'PATH': 'tools', 'PYTHONPATH': 'hook', 'OTELC_ROOT': 'external', 'GH_TOKEN': 'not-used'}, folder)
                self.assertEqual(workflow.execute.call_args.args[2], {'PATH': 'tools'})

    def test_witness_requires_declared_root_counts_and_separate_direct_health(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            run = SimpleNamespace(intent=SimpleNamespace(runtime=folder, policy={'schema_version': 3}, profile=launch.provider.ORIGIN_PROFILE))
            value = {'received': {'spans': 1}, 'functions': {'entry.workload': 1}}
            health = {'runtime_losses': {'incomplete': 0}, 'pending': 0}
            bodies = [('/v1/traces', traces().SerializeToString())]
            with patch.object(python_telemetry, 'decode', return_value=value), \
                 patch.object(launch.python_health, 'read', return_value=health) as read:
                result = launch.witness(generation, run, (object(), {1: 'entry.workload'}), folder,
                                         entry(), bodies, 'case', ExportTraceServiceRequest)
                self.assertEqual(result['functions'], {'entry.workload': 1})
                self.assertEqual(result['pending'], 0)
                self.assertEqual(read.call_args.args[-1], {'spans': 1})
                wrong = {**entry(), 'sequence_configuration': [{'action': 'call'}, {'action': 'call'}]}
                with self.assertRaisesRegex(ValueError, 'invocation roots'):
                    launch.witness(generation, run, (object(), {}), folder, wrong, bodies, 'case', ExportTraceServiceRequest)

    def test_prepared_build_cannot_fall_through_to_legacy(self):
        with self.assertRaisesRegex(ValueError, 'owned launch'):
            generation.build_command(None, None, entry(), None, None, None, None, None, None, 'baseline')
        self.assertEqual(generation.execution_options(entry(), {}, 'baseline', None, None, [], {}), {'record_process': True})

    def test_neither_lane_can_qualify_without_verified_origin_execution(self):
        result = subprocess.CompletedProcess([], 0, b'', b'')
        for lane in ('baseline', 'instrumented_on'):
            with self.subTest(lane=lane), self.assertRaisesRegex(ValueError, 'verified generated Python execution'):
                generation.qualify_attempt({}, entry(), lane, Path('/unused'), result, [], [], 'case', None)

    def test_source_creation_must_finish_before_independent_selected_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            run = SimpleNamespace(intent=SimpleNamespace(runtime=folder, policy={}, profile=launch.provider.ORIGIN_PROFILE))
            chosen = {**entry(), 'receiver_fixture': {'source_function': 'make_counter', 'line': 4}}
            message = traces(); scope = message.resource_spans[0].scope_spans[0]
            target = scope.spans[0]; target.start_time_unix_nano = 3; target.end_time_unix_nano = 4
            factory = scope.spans.add(); factory.CopyFrom(target)
            factory.name = 'entry.make_counter'; factory.span_id = b'f' * 8
            factory.trace_id = b'c' * 16; factory.start_time_unix_nano = 1; factory.end_time_unix_nano = 2
            value = {'received': {'spans': 2}, 'functions': {'entry.workload': 1, 'entry.make_counter': 1}}
            with patch.object(python_telemetry, 'decode', return_value=value), \
                 patch.object(launch.python_health, 'read', return_value={'runtime_losses': {}, 'pending': 0}):
                def witness():
                    return launch.witness(generation, run, (object(), {}), folder, chosen,
                        [('/v1/traces', message.SerializeToString())], 'case', ExportTraceServiceRequest)
                self.assertEqual(witness()['spans'], 2)
                factory.end_time_unix_nano = 4
                with self.assertRaisesRegex(ValueError, 'did not complete'):
                    witness()


if __name__ == '__main__':
    unittest.main()
