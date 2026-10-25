"""Public lifetime orchestration only; mocked producers do not qualify execution."""

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
import native_inputs
import native_lifetime_intent
import native_lifetime_policy as policy
import native_source
import native_source_run as run
from test_generation_native_lifetime_policy import observation


class NativeLifetimeRunTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()

    def context(self, language='cpp', lane='baseline', *, declarations=None):
        folder = self.base / (language + '-' + lane); folder.mkdir()
        project = folder / 'project'; project.mkdir()
        profile = policy.OBJECT if language == 'cpp' else policy.RESOURCE
        options = native_source.settings({'backend': 'prepared', 'profile': profile,
            'sdk_build': str(self.base / 'sdk-build'), 'lifetimes': {'include': ['Item']}})
        entry = {'language': language, 'path': 'work.cpp' if language == 'cpp' else 'work.c',
                 'otelc_function': 'work(int)' if language == 'cpp' else 'work', 'status': 'ready'}
        native_source.configure(entry, options)
        policy.bind(entry, [observation(language)] if declarations is None else declarations)
        entry[policy.SOURCES] = {'include': [entry['path']], 'exclude': []}
        case = {'arguments': [5], policy.EXPECTATIONS: policy.expectations(entry[policy.EXPECTATIONS], language)}
        config = folder / 'policy.toml'
        config.write_text(native_source.policy(entry, 'http://127.0.0.1:4318', 'actual-service'))
        data = {'otelc_root': str(self.base / 'sdk'), 'native_projects': {language: {'directories': []}}}
        return folder, project, entry, case, config, data

    def prepare(self, language='cpp', lane='baseline', *, declarations=None, mutate_expected=False):
        folder, project, entry, case, config, data = self.context(language, lane, declarations=declarations)
        events = []
        tools = {'python-host': self.base / 'python'}
        context = SimpleNamespace(output=folder / 'native-build',
                                  recipe=Mock(return_value={'schema_version': 1, 'kind': 'caller-recipe'}))
        caller = Mock(); caller.intent.base = context
        frontend = Mock(); sdk = SimpleNamespace(directory=self.base / 'sdk-build')
        build = Mock(); build.file.return_value.gate_identity.return_value = {'identity': 'actual-image'}
        preparation = SimpleNamespace(runtime=folder / 'native-runtime')
        launch = Mock(); launch.intent = preparation
        session = SimpleNamespace(execution=Mock())
        roots = (entry['otelc_runtime_function'],)
        expected = Mock(); expected.roots = roots
        values = tuple(native_lifetime_intent.Observation('c:@S@Item', 'Item', (0,), (0,), True,
            False if language == 'cpp' else None) for _ in entry[policy.EXPECTATIONS])

        def resolve(intent, declarations):
            self.assertIs(intent, caller.intent)
            self.assertEqual(declarations, entry[policy.EXPECTATIONS])
            events.append('independent-expectations')
            return values

        def execute(argv, *args, **kwargs):
            if 'native-build' in argv:
                record = native_inputs.read(folder / 'expected-lifetimes-before-build.json', private=True)
                self.assertEqual(record.value()['observations'], [row.data() for row in values])
                events.append('SDK-build')
                if mutate_expected:
                    record.file.path.write_bytes(record.file.content)
            elif 'native-run' in argv:
                events.append('SDK-prepare')
            return subprocess.CompletedProcess(argv, 0, b'', b'')

        def freeze_expected(actual, path, root_names, observations):
            self.assertIs(actual, launch)
            self.assertEqual(root_names, roots)
            self.assertEqual(observations, values)
            events.append('prelaunch-expectations')
            return expected

        workflow = SimpleNamespace(write=generation.write, BUILD_IDENTITIES=generation.BUILD_IDENTITIES,
                                   execute=Mock(side_effect=execute))
        with ExitStack() as stack:
            stack.enter_context(patch.object(run.native_source, 'sdk', return_value=sdk))
            stack.enter_context(patch.object(run.native_unit_caller, 'freeze'))
            unit = stack.enter_context(patch.object(run.native_unit_caller, 'prepare', side_effect=AssertionError('wrong caller')))
            frontend_prepare = stack.enter_context(patch.object(run.native_lifetime_frontend, 'prepare', return_value=frontend))
            stack.enter_context(patch.object(run.native_lifetime_caller, 'prepare', return_value=caller))
            stack.enter_context(patch.object(run.native_lifetime_policy, 'resolve', side_effect=resolve))
            stack.enter_context(patch.object(run.native_unit_build, 'read', side_effect=AssertionError('wrong build reader')))
            build_read = stack.enter_context(patch.object(run.native_lifetime_build, 'read', return_value=build))
            prepared_freeze = stack.enter_context(patch.object(run.native_prepared, 'freeze', return_value=preparation))
            stack.enter_context(patch.object(run.native_prepared, 'read', return_value=launch))
            stack.enter_context(patch.object(run.native_lifetime_intent, 'freeze', side_effect=freeze_expected))
            stack.enter_context(patch.object(run.native_session, 'Session', return_value=session))
            result = run.prepare(workflow, self.base, data, entry, case, project, tools, {}, folder, config, lane)
        return SimpleNamespace(result=result, caller=caller, frontend=frontend, events=events, unit=unit,
            frontend_prepare=frontend_prepare, build_read=build_read, prepared_freeze=prepared_freeze,
            folder=folder, expected=expected, values=values, workflow=workflow)

    def test_both_profiles_and_lanes_freeze_expectations_before_sdk_application_build(self):
        for language in ('cpp', 'c'):
            for lane in ('baseline', 'instrumented_on'):
                with self.subTest(language=language, lane=lane):
                    value = self.prepare(language, lane)
                    self.assertEqual(value.events, ['independent-expectations', 'SDK-build', 'SDK-prepare',
                                                    'prelaunch-expectations'])
                    value.unit.assert_not_called()
                    value.build_read.assert_called_once_with(value.caller.intent)
                    self.assertEqual(value.frontend_prepare.call_args.args[1], 'object' if language == 'cpp' else 'resource')
                    self.assertEqual(value.prepared_freeze.call_args.kwargs, {'plain': lane == 'baseline'})
                    self.assertIs(value.result.lifetimes, value.expected)
                    value.result.expected_before_build.verify()
                    value.result.verify(value.folder)
                    value.frontend.verify.assert_called()
                    value.expected.verify.assert_called_once()
                    value.caller.recheck.assert_called_with(value.folder / 'native-after-execution-inputs', value.result.execute)

    def test_explicit_zero_observations_still_take_the_lifetime_route(self):
        value = self.prepare('c', declarations=[])
        self.assertEqual(value.values, ())
        self.assertIs(value.result.lifetimes, value.expected)
        self.assertEqual(value.result.expected_before_build.value()['observations'], [])

    def test_missing_or_changed_declarations_refuse_before_any_sdk_read(self):
        folder, project, entry, case, config, data = self.context()
        for change in ('missing-entry', 'missing-case', 'changed-case'):
            selected = dict(entry); altered = dict(case)
            if change == 'missing-entry':
                del selected[policy.EXPECTATIONS]
            elif change == 'missing-case':
                del altered[policy.EXPECTATIONS]
            else:
                altered[policy.EXPECTATIONS] = []
            with self.subTest(change=change), patch.object(run.native_source, 'sdk') as sdk:
                with self.assertRaises(ValueError):
                    run.prepare(SimpleNamespace(), self.base, data, selected, altered, project, {}, {}, folder, config, 'baseline')
                sdk.assert_not_called()

    def test_changed_prebuild_expectation_file_cannot_be_recertified_after_sdk_build(self):
        with self.assertRaisesRegex(ValueError, 'original native file'):
            self.prepare(mutate_expected=True)

    def test_lifetime_receipt_routes_directly_and_binds_service_and_root(self):
        value = self.prepare()
        result = value.result
        result.prepared.intent = SimpleNamespace(policy=lambda: {'resource': {'service_name': 'actual-service'}})
        bodies = [b'original OTLP']; roots = value.expected.roots
        verified = {'decoder': 'independent lifetime reader', 'raw_otlp_sha256': 'a' * 64,
            'functions': {roots[0]: 2}, 'spans': 3, 'losses': {'lifetime_lost': 0},
            'pending': 0, 'lifetimes': [{'complete': True}], 'sdk_pid': 42}
        with patch.object(run.native_lifetime_receipt, 'witness', return_value=verified) as witness, \
                patch.object(run.native_telemetry, 'witness', side_effect=AssertionError('function-only fallback')):
            observed = result.witness(bodies, 'actual-service', roots, value.folder)
            self.assertEqual(set(observed), set(run.native_telemetry.WITNESS_FIELDS))
            self.assertEqual(observed, {**{name: verified[name] for name in run.native_telemetry.WITNESS_FIELDS}, 'spans': 2})
            self.assertEqual(generation.read(value.folder / 'native-verified-lifetimes.json'), verified)
            witness.assert_called_once_with(result.session.execution, value.expected, bodies)
            for service, targets in (('wrong-service', roots), ('actual-service', ('wrong-root',))):
                with self.subTest(service=service, targets=targets), self.assertRaises(ValueError):
                    result.witness(bodies, service, targets, value.folder)
        with patch.object(run.native_lifetime_receipt, 'witness', return_value=None):
            self.assertIsNone(result.witness([], 'actual-service', roots, value.folder))


if __name__ == '__main__':
    unittest.main()
