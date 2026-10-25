"""Explicit lifetime preparation and final health cannot downgrade to function-only."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import native_execution as execution
import native_health
import native_lifetime_build
import native_lifetime_fixture
import native_prepared as prepared
import native_provider_fixture as fixed
import native_telemetry
from test_generation_native_execution import health as function_health, write


def setup(root: Path, kind: str, *, plain: bool = False) -> prepared.Prepared:
    """Author literal preparation without using producer preparation renderers."""
    built = native_lifetime_build.read(native_lifetime_fixture.build(root, kind=kind))
    context = built.intent.base
    producer = context.sdk.root / 'otelc'
    producer.mkdir()
    for name in prepared.REQUIRED:
        (producer / name).write_text('literal producer; never executed: ' + name)
    policy = context.policy()
    config = root / 'policy.toml'
    lines = ['schema_version=3', 'languages=["c","cpp"]']
    for section, values in policy.items():
        if type(values) is dict:
            lines += ['[' + section + ']', *[key + '=' + json.dumps(value) for key, value in values.items()]]
    config.write_text('\n'.join(lines) + '\n')
    intent = prepared.freeze(built, root / 'runtime', Path(sys.executable).absolute(), config,
                             policy, plain=plain, arguments=('literal argument',), wait_ms=12345)
    intent.runtime.mkdir(mode=0o700)
    image = built.file('plain' if plain else 'instrumented').path
    request = {'schema_version': 1, 'kind': 'otelc.native.request', 'profile': 'native-owned-v1',
        'build': fixed.identity(context.output / 'native-source-build.json', gate=True),
        'runtime': str(intent.runtime), 'policy': policy, 'arguments': ['literal argument'],
        'plain': plain, 'wait_ms': 12345, 'launch_id': 'a' * 32}
    plan = {'schema_version': 1, 'kind': 'otelc.native.plan', 'profile': 'native-owned-v1',
        'request_sha256': fixed.digest(request), 'cwd': str(context.project),
        'argv': [str(image), 'literal argument'], 'image': fixed.identity(image, gate=True), 'source_complete': False}
    manifest = {'schema_version': 1, 'kind': 'otelc.native.prepared', 'profile': 'native-owned-v1',
        'request_sha256': fixed.digest(request), 'plan_sha256': fixed.digest(plan),
        'interpreter': fixed.identity(Path(sys.executable).resolve(), gate=True),
        'interpreter_spelling': sys.executable,
        'producer': [fixed.identity(path, gate=True) for path in sorted(producer.glob('*.py'))],
        'source_complete': False}
    for name, value in zip((prepared.REQUEST, prepared.PLAN, prepared.PREPARED), (request, plan, manifest)):
        write(intent.runtime / name, value)
    return prepared.read(intent)


def checkpoint(launch: prepared.Prepared, *, censored: int = 0) -> dict:
    """Keep completion and shutdown censorship as separate literal counters."""
    value = function_health(launch)
    kind = launch.intent.lifetime_kind()
    value['language'] = 'cpp' if kind == 'object' else 'c'
    value['selection_sha256'] = fixed.digest(launch.intent.selection())
    value[kind + '_accounting'] = {'types': '1', 'admitted': '3', 'completed': str(3 - censored),
        'live': '0', 'destroying' if kind == 'object' else 'releasing': '0', 'ending': '0',
        'censored': str(censored), 'lost': '0', 'duplicates': '0', 'invalid': '0',
        'closing': True, 'closed': True}
    return value


def completed(launch: prepared.Prepared, value: dict | None = None) -> execution.Execution:
    """Literal actual-owner expectations use the same fixed supervisor contract."""
    runtime = launch.intent.runtime
    owner = execution.Owner(22, 21, 23, tuple(prepared.command(launch.intent)))
    supervisor = {'schema_version': 1, 'kind': 'otelc.native.supervisor', 'pid': 22,
        'parent_pid': 21, 'process_group': 22, 'session': 22, 'launch_id': 'a' * 32}
    image = launch.intent.build.file('plain' if launch.intent.plain else 'instrumented').path
    application = {'schema_version': 1, 'kind': 'otelc.native.application', 'pid': 23,
        'parent_pid': 22, 'process_group': 23, 'session': 23, 'supervisor_pid': 22, 'launch_id': 'a' * 32,
        'image': fixed.identity(image, gate=True), 'phase': 'waiting_exec', 'source_complete': False}
    for name, row in zip(prepared.START_FILES, (supervisor, application)):
        write(runtime / name, row)
    started = execution.bind(launch, owner)
    (runtime / 'app').mkdir(mode=0o700)
    if not launch.intent.plain:
        value = checkpoint(launch) if value is None else value
        write(runtime / 'app/health.json', value)
    write(runtime / execution.RELEASE, {'schema_version': 1, 'kind': 'otelc.native.host-release',
        'launch_id': 'a' * 32, 'pid': 23, 'supervisor_pid': 22})
    write(runtime / execution.FINAL, {'schema_version': 1, 'kind': 'otelc.native.execution',
        'profile': 'native-owned-v1', 'request_sha256': fixed.digest(launch.value(prepared.REQUEST)),
        'plan_sha256': fixed.digest(launch.value(prepared.PLAN)), 'supervisor': supervisor,
        'application': application, 'released': True, 'process_exit_code': 0, 'supervisor_exit_code': 0,
        'exec_verified': False, 'sdk_health': value, 'inputs_rechecked': True, 'failures': {}, 'source_complete': False})
    return execution.finish(started, 0)


class NativeLifetimeExecutionTests(unittest.TestCase):
    def test_both_profiles_and_lanes_keep_their_original_build_and_selection(self):
        for kind in ('object', 'resource'):
            for plain in (False, True):
                with self.subTest(kind=kind, plain=plain), tempfile.TemporaryDirectory() as temporary:
                    launch = setup(Path(temporary).resolve(), kind, plain=plain)
                    self.assertEqual(launch.intent.lifetime_kind(), kind)
                    self.assertIs(launch.intent.context(), launch.intent.build.intent.base)
                    selection = launch.intent.selection()
                    self.assertEqual(selection['lifetimes'], {'enabled': True, 'include': ['Item'], 'exclude': []})
                    selection['lifetimes']['include'].clear()
                    self.assertEqual(launch.intent.selection()['lifetimes']['include'], ['Item'])
                    result = completed(launch)
                    self.assertEqual(result.health is None, plain)
                    result.verify()
                    if plain:
                        self.assertIsNone(native_telemetry.witness(result, [], 'native-telemetry-unit', ('workload',)))
                    else:
                        with self.assertRaisesRegex(ValueError, 'separate decoder'):
                            native_telemetry.witness(result, [], 'native-telemetry-unit', ('workload',))

    def test_runtime_cannot_disable_change_or_increase_compiled_lifetime_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            launch = setup(root, 'object')
            for key, value in (('enabled', False), ('include', ['Other']), ('exclude', ['Item']),
                               ('max_live', 8192), ('release_methods', ['dispose'])):
                policy = launch.intent.policy()
                policy['lifetimes'][key] = value
                with self.subTest(key=key), self.assertRaises(ValueError):
                    prepared.freeze(launch.intent.build, root / 'another-runtime', Path(sys.executable).absolute(),
                                    launch.intent.policy_file.path, policy, plain=False)
            with self.assertRaises(ValueError):
                prepared.context(launch.intent.build.intent)

    def test_complete_and_censored_counters_remain_distinct_for_both_profiles(self):
        for kind in ('object', 'resource'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                launch = setup(Path(temporary).resolve(), kind)
                for censored in (0, 1, 3):
                    value = checkpoint(launch, censored=censored)
                    options = {'language': value['language'], 'pid': 23, 'policy': value['policy_sha256'],
                               'selection': value['selection_sha256'], 'lifetime_kind': kind}
                    self.assertIs(native_health.validate(value, **options), value)
                    self.assertEqual(value[kind + '_accounting']['censored'], str(censored))
                final = completed(launch, checkpoint(launch, censored=1))
                self.assertEqual(final.health.value()[kind + '_accounting']['completed'], '2')

    def test_missing_foreign_pending_lost_and_rehashed_health_refuse(self):
        for kind in ('object', 'resource'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                launch = setup(Path(temporary).resolve(), kind)
                original = checkpoint(launch)
                field = kind + '_accounting'
                options = {'language': original['language'], 'pid': 23, 'policy': original['policy_sha256'],
                           'selection': original['selection_sha256'], 'lifetime_kind': kind}
                changes = [(key, '1') for key in ('live', 'ending', 'lost', 'duplicates', 'invalid',
                           'destroying' if kind == 'object' else 'releasing')]
                changes += [('closing', False), ('closed', 1), ('admitted', '4'), ('completed', '2'),
                            ('censored', '1'), ('types', '0'), ('types', True), ('types', '01')]
                for key, value in changes:
                    altered = copy.deepcopy(original)
                    altered[field][key] = value
                    with self.subTest(key=key), self.assertRaises(ValueError):
                        native_health.validate(altered, **options)
                for missing in original[field]:
                    altered = copy.deepcopy(original)
                    del altered[field][missing]
                    with self.subTest(missing=missing), self.assertRaises(ValueError):
                        native_health.validate(altered, **options)
                with self.assertRaises(ValueError):
                    native_health.validate(original, **{**options, 'lifetime_kind': None})
                with self.assertRaises(ValueError):
                    native_health.validate(original, **{**options, 'lifetime_kind': 'unknown'})
                altered = copy.deepcopy(original)
                altered[field]['extra'] = '0'
                with self.assertRaises(ValueError): native_health.validate(altered, **options)
                del altered[field]
                with self.assertRaises(ValueError): native_health.validate(altered, **options)
                altered = copy.deepcopy(original)
                altered['selection_sha256'] = fixed.digest({key: launch.intent.policy()[key]
                                                          for key in ('sources', 'functions')})
                with self.assertRaises(ValueError): completed(launch, altered)

    def test_empty_selected_lifetime_catalogue_cannot_report_admitted_instances(self):
        with tempfile.TemporaryDirectory() as temporary:
            launch = setup(Path(temporary).resolve(), 'resource')
            value = checkpoint(launch)
            value['resource_accounting'].update(types='0', admitted='0', completed='0')
            native_health.validate(value, language='c', pid=23, policy=value['policy_sha256'],
                                   selection=value['selection_sha256'], lifetime_kind='resource')


if __name__ == '__main__':
    unittest.main()
