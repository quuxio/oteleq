"""Native preparation binds exact policy, binaries, arguments and SDK source files."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import native_build
import native_prepared as prepared
import native_provider_fixture as fixture


def setup(root: Path, *, plain: bool = False, arguments: tuple = ()):
    built = native_build.read(fixture.build(root))
    producer = built.intent.sdk.root / 'otelc'; producer.mkdir()
    for name in prepared.REQUIRED:
        (producer / name).write_text('unit producer source; never executed: ' + name)
    config = root / 'policy.toml'
    lines = ['schema_version=3', 'languages=["c","cpp"]']
    for name, values in fixture.POLICY.items():
        if type(values) is dict:
            lines += ['[' + name + ']', *[key + '=' + json.dumps(value) for key, value in values.items()]]
    config.write_text('\n'.join(lines) + '\n')
    intent = prepared.freeze(built, root / 'runtime', Path(sys.executable).absolute(), config, fixture.POLICY,
                             plain=plain, arguments=arguments, wait_ms=12345)
    intent.runtime.mkdir(mode=0o700)
    image = intent.build.file('plain' if plain else 'instrumented').path
    request = {'schema_version': 1, 'kind': 'otelc.native.request', 'profile': 'native-owned-v1',
        'build': fixture.identity(built.intent.output / 'native-source-build.json', gate=True),
        'runtime': str(intent.runtime), 'policy': fixture.POLICY, 'arguments': list(arguments),
        'plain': plain, 'wait_ms': 12345, 'launch_id': 'a' * 32}
    plan = {'schema_version': 1, 'kind': 'otelc.native.plan', 'profile': 'native-owned-v1',
        'request_sha256': fixture.digest(request), 'cwd': str(intent.build.intent.project),
        'argv': [str(image), *arguments], 'image': fixture.identity(image, gate=True), 'source_complete': False}
    manifest = {'schema_version': 1, 'kind': 'otelc.native.prepared', 'profile': 'native-owned-v1',
        'request_sha256': fixture.digest(request), 'plan_sha256': fixture.digest(plan),
        'interpreter': fixture.identity(Path(sys.executable).resolve(), gate=True),
        'interpreter_spelling': sys.executable,
        'producer': [fixture.identity(path, gate=True) for path in sorted(producer.glob('*.py'))], 'source_complete': False}
    for name, value in ((prepared.REQUEST, request), (prepared.PLAN, plan), (prepared.PREPARED, manifest)):
        path = intent.runtime / name; fixture.write(path, value); path.chmod(0o600)
    return intent


class NativePreparedTests(unittest.TestCase):
    def test_both_lanes_retain_literal_arguments_without_starting_processes(self):
        for plain in (True, False):
            with self.subTest(plain=plain), tempfile.TemporaryDirectory() as temporary:
                args = ('a space', '--literal', '$(not-a-command)', '`literal`')
                intent = setup(Path(temporary).resolve(), plain=plain, arguments=args)
                value = prepared.read(intent)
                self.assertEqual(value.value(prepared.PLAN)['argv'][1:], list(args))
                self.assertEqual(prepared.command(intent), [sys.executable, '-I', '-S',
                    str(intent.build.intent.sdk.root / 'otelc/native_supervisor.py'), str(intent.runtime)])
                value.value(prepared.REQUEST)['policy']['functions']['include'] = ['wrong']
                value.verify()
                with self.assertRaises(ValueError): value.value('unknown')

    def test_every_request_plan_and_preparation_substitution_is_refused(self):
        changes = ((prepared.REQUEST, 'plain', 1), (prepared.REQUEST, 'wait_ms', True),
            (prepared.REQUEST, 'launch_id', 'invalid'), (prepared.REQUEST, 'arguments', ['wrong']),
            (prepared.REQUEST, 'extra', True), (prepared.PLAN, 'argv', ['foreign-executable']),
            (prepared.PLAN, 'cwd', '/different'), (prepared.PLAN, 'source_complete', 0),
            (prepared.PREPARED, 'interpreter_spelling', '/different/python'),
            (prepared.PREPARED, 'producer', []), (prepared.PREPARED, 'request_sha256', '0' * 64))
        for name, key, altered in changes:
            with self.subTest(name=name, key=key), tempfile.TemporaryDirectory() as temporary:
                intent = setup(Path(temporary).resolve())
                path = intent.runtime / name; value = json.loads(path.read_bytes()); value[key] = altered
                fixture.write(path, value)
                with self.assertRaises(ValueError): prepared.read(intent)

    def test_rehashed_changed_selection_cannot_replace_frozen_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            intent = setup(Path(temporary).resolve())
            request = json.loads((intent.runtime / prepared.REQUEST).read_bytes())
            request['policy']['functions']['include'] = ['wrong']
            plan = json.loads((intent.runtime / prepared.PLAN).read_bytes())
            plan['request_sha256'] = fixture.digest(request)
            manifest = json.loads((intent.runtime / prepared.PREPARED).read_bytes())
            manifest.update(request_sha256=fixture.digest(request), plan_sha256=fixture.digest(plan))
            for name, value in ((prepared.REQUEST, request), (prepared.PLAN, plan), (prepared.PREPARED, manifest)):
                fixture.write(intent.runtime / name, value)
            with self.assertRaises(ValueError): prepared.read(intent)

    def test_original_runtime_record_directory_and_producer_facts_are_held(self):
        for kind in ('record', 'directory', 'producer', 'extra-producer', 'used-runtime'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                intent = setup(Path(temporary).resolve())
                accepted = prepared.read(intent)
                if kind == 'record':
                    path = intent.runtime / prepared.REQUEST; path.write_bytes(path.read_bytes())
                elif kind == 'directory': intent.runtime.chmod(0o755)
                elif kind == 'producer': intent.producer[0].path.write_text('changed producer')
                elif kind == 'extra-producer': (intent.build.intent.sdk.root / 'otelc/extra.py').write_text('extra')
                else: (intent.runtime / 'native-supervisor-start.json').write_text('already used')
                with self.assertRaises(ValueError):
                    prepared.read(intent) if kind == 'used-runtime' else accepted.verify()

    def test_intent_refuses_changed_source_selection_unsafe_arguments_and_runtime_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); intent = setup(root)
            kwargs = {'plain': False}
            def capture(runtime, policy=fixture.POLICY, **options):
                return prepared.freeze(intent.build, runtime, Path(sys.executable).absolute(), intent.policy_file.path,
                                       policy, **{**kwargs, **options})
            for options in ({'arguments': ['not-a-tuple']}, {'arguments': ('bad\0argument',)},
                            {'plain': 0}, {'wait_ms': True}, {'wait_ms': 300001}):
                with self.subTest(options=options), self.assertRaises(ValueError): capture(root / 'new-runtime', **options)
            for runtime in (intent.runtime, intent.build.intent.project / 'runtime', intent.build.intent.output / 'runtime'):
                with self.subTest(runtime=runtime), self.assertRaises(ValueError): capture(runtime)
            changed = copy.deepcopy(fixture.POLICY); changed['functions']['include'] = ['wrong']
            with self.assertRaises(ValueError): capture(root / 'new-runtime', changed)
            changed = copy.deepcopy(fixture.POLICY); changed['context']['http'] = True
            with self.assertRaises(ValueError): capture(root / 'new-runtime', changed)
            intent.policy_file.path.write_text('schema_version=3\nlanguages=["c"]\n')
            with self.assertRaises(ValueError): intent.verify()


if __name__ == '__main__':
    unittest.main()
