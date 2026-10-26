"""Public native orchestration freezes commands and retains owned execution checks."""

from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import generation
import native_session
import native_source
import native_source_run as run
import sequences


class NativeSourceRunTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.project = self.base / 'project'; self.project.mkdir()
        self.folder = self.base / 'attempt'; self.folder.mkdir()
        self.options = native_source.settings({'backend': 'prepared', 'sdk_build': str(self.base / 'sdk-build')})
        self.entry = {'language': 'c', 'path': 'selected.c', 'otelc_function': 'selected', 'status': 'ready'}
        native_source.configure(self.entry, self.options)
        self.config = self.folder / 'policy.toml'
        self.config.write_text(native_source.policy(self.entry, 'http://127.0.0.1:4318', 'actual-service'))
        self.tools = {'python-host': self.base / 'python'}
        self.data = {'otelc_root': str(self.base / 'sdk'), 'native_projects': {'c': {'directories': []}},
                     'source_sha256': 'original', 'configuration': {'limits': {'max_capture_bytes': 4096}}}

    def prepare(self, lane='baseline', status=0, *, case=None, bodies=None):
        caller = Mock()
        caller.intent.output = self.folder / 'native-build'
        caller.intent.recipe.return_value = {'schema_version': 1, 'kind': 'independent-test-recipe'}
        build = Mock(); build.intent.output = caller.intent.output
        build.file.return_value.gate_identity.return_value = {'identity': 'original-input'}
        intent = SimpleNamespace(runtime=self.folder / 'native-runtime')
        prepared = Mock(); prepared.intent = intent
        session = SimpleNamespace(execution=Mock())
        workflow = SimpleNamespace(write=generation.write, BUILD_IDENTITIES=generation.BUILD_IDENTITIES,
                                   execute=Mock(side_effect=lambda argv, *args, **kwargs:
                                                subprocess.CompletedProcess(argv, status, b'', b'')))
        sdk = SimpleNamespace(directory=self.base / 'sdk-build')

        def capture_sdk(root, language, tools, options, folder, execute):
            execute(['fixed-compiler', '--version'], folder)
            return sdk

        with ExitStack() as stack:
            stack.enter_context(patch.object(run.native_source, 'sdk', side_effect=capture_sdk))
            frozen = stack.enter_context(patch.object(run.native_unit_caller, 'freeze'))
            stack.enter_context(patch.object(run.native_unit_caller, 'prepare', return_value=caller))
            stack.enter_context(patch.object(run.native_unit_build, 'read', return_value=build))
            freeze = stack.enter_context(patch.object(run.native_prepared, 'freeze', return_value=intent))
            stack.enter_context(patch.object(run.native_prepared, 'read', return_value=prepared))
            stack.enter_context(patch.object(run.native_session, 'Session', return_value=session))
            result = run.prepare(workflow, self.base, self.data, self.entry, case or {'arguments': [5]}, self.project,
                                 self.tools, {'ORIGINAL': 'value'}, self.folder, self.config, lane,
                                 **({'bodies': bodies} if bodies is not None else {}))
        return result, workflow, frozen, freeze

    def test_public_builder_and_preparer_use_fixed_argv_and_original_policy(self):
        result, workflow, frozen, freeze = self.prepare()
        commands = [list(map(str, call.args[0])) for call in workflow.execute.call_args_list]
        prefix = list(map(str, native_source.cli(Path(self.data['otelc_root']), self.tools)))
        self.assertEqual(commands[0], ['fixed-compiler', '--version'])
        self.assertEqual(commands[1], prefix + ['--config', str(self.config), 'native-build', '--language', 'c',
            '--root', str(self.project), '--recipe', str(self.folder / 'native-recipe.json'),
            '--output', str(self.folder / 'native-build'), '--sdk-build', self.options['sdk_build']])
        self.assertEqual(commands[2], prefix + ['--config', str(self.config), 'native-run', '--build',
            str(self.folder / 'native-build'), '--runtime', str(self.folder / 'native-runtime'), '--prepare-only', '--plain'])
        self.assertEqual(frozen.call_args.args[-2], [5])
        self.assertEqual(freeze.call_args.args[-1]['resource'], {'service_name': 'actual-service'})
        self.assertTrue(freeze.call_args.kwargs['plain'])
        result.caller.recheck.assert_called_once_with(self.folder / 'native-after-build-inputs', result.execute)
        result.verify(self.folder)
        result.caller.recheck.assert_called_with(self.folder / 'native-after-execution-inputs', result.execute)
        self.assertEqual(generation.read(self.folder / 'native-tooling/0/command.json')['timeout_ms'], 180000)
        for call in workflow.execute.call_args_list:
            self.assertEqual(call.args[2], {'ORIGINAL': 'value'})
            self.assertEqual(call.kwargs['timeout'], 180)
        result.session.execution = None
        with self.assertRaisesRegex(ValueError, 'owned completion'):
            result.verify(self.folder)

    def test_instrumented_preparation_never_uses_plain_or_legacy_command(self):
        _, workflow, _, freeze = self.prepare('instrumented_on')
        self.assertNotIn('--plain', workflow.execute.call_args.args[0])
        self.assertFalse(freeze.call_args.kwargs['plain'])

    def test_failed_producer_command_retains_command_and_refuses(self):
        with self.assertRaisesRegex(ValueError, 'retained compiler channels'):
            self.prepare(status=1)
        self.assertTrue((self.folder / 'native-tooling/0/command.json').is_file())
        self.assertFalse((self.folder / 'native-recipe.json').exists())

    def test_owned_session_is_mandatory_and_both_groups_cleanup_on_error(self):
        with self.assertRaisesRegex(ValueError, 'owned session'):
            generation.execution_options(self.entry, {}, 'baseline', self.folder, None, [], {})
        session = object.__new__(native_session.Session)
        expected = {'record_process': True, 'interaction': session}
        self.assertEqual(generation.execution_options(self.entry, {}, 'baseline', self.folder, None, [], {},
                                                      native_session=session), expected)
        with patch.object(session, 'close') as close:
            with self.assertRaisesRegex(RuntimeError, 'application failed'):
                with generation.native_cleanup(SimpleNamespace(session=session)):
                    raise RuntimeError('application failed')
        close.assert_called_once()
        with generation.native_cleanup(None):
            pass  # Legacy execution has no additional native process group.

    def test_public_qualification_requires_owned_runtime_and_bound_direct_receipt(self):
        (self.folder / 'observation').write_bytes(b'boundary-observation')
        completed = subprocess.CompletedProcess([], 0, b'', b'')
        arguments = (self.data, self.entry, 'instrumented_on', self.folder, completed, [], [], 'actual-service', None)
        with self.assertRaisesRegex(ValueError, 'owned native execution'):
            generation.qualify_attempt(*arguments)
        owned = run.Run(Mock(), Mock(), SimpleNamespace(execution=object()), Mock())
        with patch.object(generation.native_telemetry, 'witness', return_value={'spans': 1}) as witness:
            observed = generation.qualify_attempt(*arguments, native_runtime=owned)
        self.assertEqual(observed['witness'], {'spans': 1})
        witness.assert_called_once_with(owned.session.execution, [], 'actual-service', ('selected.c::selected',), folder=self.folder)
        with patch.object(generation.native_telemetry, 'witness', return_value=None):
            generation.qualify_attempt(self.data, self.entry, 'baseline', self.folder, completed, [], [], 'actual-service', None,
                                       native_runtime=owned)

    def controlled_entry(self):
        self.entry['expected_baseline'] = {'kind': 'return'}
        self.entry['sequence_configuration'] = [{'action': 'call', 'arguments': 'case',
            'metrics': {'collection': flag, 'emission': True}} for flag in (True, False)]

    def test_controlled_preparation_receives_the_frozen_case_and_original_receiver(self):
        self.controlled_entry()
        case = {'arguments': [5], 'sequence': sequences.concrete(self.entry, [5], lambda entry, args: args)}
        bodies = []
        with patch.object(run.native_live, 'Session') as live:
            result, _, _, _ = self.prepare(case=case, bodies=bodies)
        self.assertIs(result.controls, live.return_value)
        self.assertEqual(live.call_args.args[2:5], (self.entry, case['sequence'], [5]))
        self.assertIs(live.call_args.args[5], bodies)
        self.assertEqual(live.call_args.args[6], 4096)

    def test_executor_adds_only_the_native_live_bindings_for_controlled_calls(self):
        self.controlled_entry()
        owner = object.__new__(native_session.Session)
        owner.controls = SimpleNamespace(environment=lambda: {'OTELEQ_NATIVE_CONTROL_ROOT': '/private/case'})
        environment = {'ORIGINAL': 'value'}
        options = generation.execution_options(self.entry, {}, 'baseline', self.folder, None, [], environment,
                                               native_session=owner)
        self.assertIs(options['interaction'], owner)
        self.assertEqual(environment, {'ORIGINAL': 'value', 'OTELEQ_NATIVE_CONTROL_ROOT': '/private/case'})

    def test_public_qualification_passes_every_declared_native_root_to_the_live_reader(self):
        self.controlled_entry()
        (self.folder / 'observation').write_bytes(b'boundary-observation')
        owned = run.Run(Mock(), Mock(), SimpleNamespace(execution=object()), Mock(), controls=Mock())
        completed = subprocess.CompletedProcess([], 0, b'', b'')
        with patch.object(run.native_control_receipt, 'witness', return_value={'spans': 2}) as witness:
            observed = generation.qualify_attempt(self.data, self.entry, 'instrumented_on', self.folder,
                completed, [], [], 'actual-service', None, native_runtime=owned)
        self.assertEqual(observed['witness'], {'spans': 2})
        self.assertEqual(witness.call_args.args[4], ('selected.c::selected',) * 2)

    def test_native_capture_reserves_every_live_flush_trace_and_periodic_request(self):
        self.controlled_entry()
        for language in ('c', 'cpp'):
            for count in (1, 2, 16, 32):
                entry = {**self.entry, 'language': language,
                         'sequence_configuration': [self.entry['sequence_configuration'][0]] * count}
                options = generation.attempt_receiver_options(entry, None)
                with self.subTest(language=language, calls=count):
                    self.assertEqual(options['max_requests'], run.native_live.MAX_TELEMETRY_REQUESTS)
                    self.assertGreater(options['max_requests'], 4 * count)
                    self.assertNotIn('max_bytes', options)
                    self.assertNotIn('allow_chunked', options)
            single = {key: value for key, value in entry.items() if key != 'sequence_configuration'}
            self.assertEqual(generation.attempt_receiver_options(single, None), {})


if __name__ == '__main__':
    unittest.main()
