"""Rust preparation records confirm independent caller choices without launching code."""

import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import native_inputs
import rust_owned_build
import rust_prepared as prepared
import test_generation_rust_owned_build as owned_fixture
from rust_build_fixture import digest, write
from test_generation_rust_tools import fact


class RustPreparedTests(unittest.TestCase):
    def fixture(self, *, lifetime: bool = False, plain: bool = False, arguments: tuple[str, ...] = ()):
        helper = owned_fixture.RustOwnedBuildTests('test_both_literal_source_profiles_bind_the_fixed_gate_without_execution')
        self.addCleanup(helper.doCleanups)
        fixture, intent = helper.fixture(lifetime=lifetime)
        helper.publish(fixture, intent)
        built = rust_owned_build.read(intent)
        producer = fixture.sdk.root / 'otelc'
        for name in prepared.REQUIRED:
            path = producer / name
            if not path.exists(): path.write_text('literal producer; never imported: ' + name)
        python = fixture.base / 'python/bin/python'
        python.parent.mkdir(parents=True)
        python.write_bytes(b'literal Python; never executed')
        policy = copy.deepcopy(fixture.policy)
        policy['resource']['service_name'] = 'runtime-service'
        policy['metrics'].update(collection=False, emission=False)
        configuration = fixture.base / 'runtime-policy.toml'
        lines = ['schema_version=3', 'languages=["rust"]']
        for name, values in policy.items():
            if type(values) is dict:
                lines += ['[' + name + ']', *[key + '=' + json.dumps(value) for key, value in values.items()]]
        configuration.write_text('\n'.join(lines) + '\n')
        held = prepared.freeze(built, fixture.base / 'runtime', python, configuration, policy,
                               plain=plain, arguments=arguments, wait_ms=12345)
        return fixture, held

    def publish(self, intent: prepared.Intent) -> tuple[dict, dict, dict]:
        intent.runtime.mkdir(mode=0o700)
        image = intent.source().intent.output / ('plain' if intent.plain else 'instrumented')
        request = {'schema_version': 1, 'kind': 'otelc.rust.request', 'profile': 'rust1981-owned-standalone-v1',
            'build': fact(intent.build.intent.output / 'rust-owned-build.json'), 'runtime': str(intent.runtime),
            'policy': intent.policy(), 'arguments': list(intent.arguments), 'plain': intent.plain,
            'wait_ms': 12345, 'launch_id': 'abc12345' * 4}
        plan = {'schema_version': 1, 'kind': 'otelc.rust.plan', 'profile': 'rust1981-owned-standalone-v1',
            'request_sha256': digest(request), 'cwd': str(intent.source().intent.project),
            'argv': [str(image), *intent.arguments], 'image': fact(image), 'source_complete': False}
        manifest = {'schema_version': 1, 'kind': 'otelc.rust.prepared', 'profile': 'rust1981-owned-standalone-v1',
            'request_sha256': digest(request), 'plan_sha256': digest(plan),
            'interpreter': fact(intent.interpreter.path), 'interpreter_spelling': str(intent.python.path),
            'producer': [fact(path) for path in sorted((intent.source().intent.sdk.root / 'otelc').glob('*.py'))],
            'source_complete': False}
        for name, value in zip(prepared.RECORDS, (request, plan, manifest)):
            path = intent.runtime / name; write(path, value); path.chmod(0o600)
        return request, plan, manifest

    def test_both_source_profiles_and_lanes_hold_literal_arguments_without_processes(self) -> None:
        arguments = ('a space', '$(literal)', '`literal`', '--flag', '\u00b5')
        for lifetime in (False, True):
            for plain in (False, True):
                fixture, intent = self.fixture(lifetime=lifetime, plain=plain, arguments=arguments)
                with patch.object(subprocess, 'Popen', side_effect=AssertionError('must not launch')):
                    values = self.publish(intent); accepted = prepared.read(intent)
                    self.assertEqual(tuple(accepted.value(name) for name in prepared.RECORDS), values)
                    self.assertEqual(prepared.command(accepted), [str(intent.python.path), '-I', '-S',
                        str(fixture.sdk.root / 'otelc/rust_supervisor.py'), str(intent.runtime)])
                    accepted.verify()
                value = accepted.value(prepared.REQUEST); value['policy']['sources'].clear()
                self.assertEqual(accepted.value(prepared.REQUEST), values[0])
                self.assertEqual(accepted.intent.image().path.name, 'plain' if plain else 'instrumented')
                with self.assertRaises(ValueError): accepted.value('foreign.json')

    def test_all_closed_record_fields_and_exact_primitive_types_are_checked(self) -> None:
        _, intent = self.fixture(); values = self.publish(intent)
        changes = ((prepared.REQUEST, 'schema_version', True), (prepared.REQUEST, 'plain', 0),
            (prepared.REQUEST, 'wait_ms', True), (prepared.REQUEST, 'launch_id', 'g' * 32),
            (prepared.REQUEST, 'arguments', ['foreign']), (prepared.REQUEST, 'build', {}),
            (prepared.REQUEST, 'extra', False), (prepared.PLAN, 'argv', ['foreign']),
            (prepared.PLAN, 'cwd', '/foreign'), (prepared.PLAN, 'source_complete', 0),
            (prepared.PLAN, 'image', {}), (prepared.PREPARED, 'producer', []),
            (prepared.PREPARED, 'interpreter_spelling', '/foreign/python'),
            (prepared.PREPARED, 'plan_sha256', '0' * 64))
        for name, key, changed in changes:
            path = intent.runtime / name; original = values[prepared.RECORDS.index(name)]
            write(path, original | {key: changed})
            with self.subTest(name=name, key=key), self.assertRaises(ValueError): prepared.read(intent)
            write(path, original)

    def test_rehashed_changed_policy_and_image_cannot_replace_caller_intent(self) -> None:
        _, intent = self.fixture(); originals = self.publish(intent)
        for kind in ('policy', 'image'):
            request, plan, manifest = copy.deepcopy(originals)
            if kind == 'policy': request['policy']['functions']['include'] = ['foreign']
            else: plan['argv'][0] = '/never-read/image'
            plan['request_sha256'] = digest(request)
            manifest.update(request_sha256=digest(request), plan_sha256=digest(plan))
            for name, value in zip(prepared.RECORDS, (request, plan, manifest)): write(intent.runtime / name, value)
            with self.subTest(kind=kind), self.assertRaises(ValueError): prepared.read(intent)

    def test_original_record_build_policy_interpreter_and_producer_facts_survive_restoration(self) -> None:
        for role in ('request', 'policy', 'producer', 'python', 'owned', 'image'):
            _, intent = self.fixture(); self.publish(intent); accepted = prepared.read(intent)
            path = {'request': intent.runtime / prepared.REQUEST, 'policy': intent.policy_file.path,
                'producer': intent.producer[0].path, 'python': intent.python.path,
                'owned': intent.build.intent.output / 'rust-owned-build.json', 'image': intent.image().path}[role]
            raw = path.read_bytes(); path.write_bytes(raw + b' ')
            with self.subTest(role=role), self.assertRaises(ValueError): accepted.verify()
            path.write_bytes(raw)
            with self.subTest(role=role, restored=True), self.assertRaises(ValueError): accepted.verify()

    def test_publications_require_private_single_link_records_and_keep_pending_distinct(self) -> None:
        _, intent = self.fixture(); self.publish(intent)
        path = intent.runtime / prepared.REQUEST
        staging = intent.runtime / '.staging'; os.link(path, staging)
        with self.assertRaises(native_inputs.PublicationPending): prepared.read(intent)
        staging.unlink()
        prepared.read(intent)
        path.chmod(0o644)
        with self.assertRaises(ValueError): prepared.read(intent)

    def test_used_unknown_or_changed_runtime_and_record_denominators_refuse(self) -> None:
        _, intent = self.fixture(); self.publish(intent); accepted = prepared.read(intent)
        path = intent.runtime / 'rust-supervisor-start.json'; path.write_text('used')
        with self.assertRaises(ValueError): prepared.read(intent)
        with self.assertRaises(ValueError): prepared.command(accepted)
        path.unlink()
        with self.assertRaises(ValueError): replace(accepted, records=accepted.records[::-1]).verify()
        with self.assertRaises(ValueError): replace(accepted, directory_facts=()).verify()
        intent.runtime.chmod(0o755)
        with self.assertRaises(ValueError): accepted.verify()

    def test_added_missing_or_linked_sdk_producer_sources_are_not_adopted(self) -> None:
        for kind in ('added', 'missing', 'linked'):
            fixture, intent = self.fixture(); self.publish(intent); accepted = prepared.read(intent)
            producer = fixture.sdk.root / 'otelc'
            if kind == 'added': (producer / 'foreign.py').write_text('foreign')
            elif kind == 'missing': (producer / 'rust_supervisor.py').unlink()
            else:
                path = producer / 'prepared_rust.py'; path.unlink(); path.symlink_to(producer / '__main__.py')
            with self.subTest(kind=kind), self.assertRaises(ValueError): accepted.verify()

    def test_runtime_selection_arguments_flags_and_budget_remain_independent(self) -> None:
        _, intent = self.fixture(lifetime=True)
        for changed in (replace(intent, plain=1), replace(intent, wait_ms=True), replace(intent, wait_ms=300001),
            replace(intent, arguments=['not-a-tuple']), replace(intent, arguments=('a\0',)),
            replace(intent, arguments=('x',) * 4097), replace(intent, arguments=('x' * 1048577,))):
            with self.assertRaises(ValueError): changed.verify()
        policy = intent.policy(); policy['lifetimes']['include'] = ['foreign']
        with self.assertRaises(ValueError): replace(intent, policy_json=json.dumps(policy)).verify()
        with self.assertRaises(ValueError): prepared.read(None)
        with self.assertRaises(ValueError): prepared.freeze(None, intent.runtime, intent.python.path,
            intent.policy_file.path, intent.policy(), plain=False)
        with self.assertRaises(ValueError): prepared.command(None)

    def test_physical_runtime_boundaries_protect_all_original_inputs_before_publication(self) -> None:
        fixture, intent = self.fixture()
        for root in (fixture.project, fixture.output, fixture.sdk.root / 'otelc', fixture.sdk.directory,
            fixture.tools.directory, fixture.sysroot, intent.build.intent.output, intent.python.path.parent):
            with self.subTest(root=root), self.assertRaises(ValueError): replace(intent, runtime=root / 'run').verify()
        alias = fixture.base / 'alias'; alias.symlink_to(fixture.project, target_is_directory=True)
        with self.assertRaises(ValueError): replace(intent, runtime=alias / 'run').verify()
        self.publish(intent)
        with self.assertRaises(ValueError): prepared.freeze(intent.build, intent.runtime, intent.python.path,
            intent.policy_file.path, intent.policy(), plain=False)

    def test_selected_interpreter_alias_keeps_spelling_and_original_target_facts(self) -> None:
        fixture, intent = self.fixture()
        alias = fixture.base / 'venv/bin/python'; alias.parent.mkdir(parents=True)
        alias.symlink_to(intent.python.path)
        selected = prepared.freeze(intent.build, intent.runtime, alias, intent.policy_file.path,
                                   intent.policy(), plain=True, wait_ms=12345)
        values = self.publish(selected); accepted = prepared.read(selected)
        self.assertEqual(prepared.command(accepted)[0], str(alias))
        self.assertEqual(values[2]['interpreter']['path'], str(intent.python.path))
        alias.unlink(); alias.symlink_to(intent.python.path)
        with self.assertRaises(ValueError): accepted.verify()

    def test_new_frozen_runtime_policy_cannot_change_compiled_selection(self) -> None:
        _, intent = self.fixture(lifetime=True)
        original = intent.policy_file.content.decode()
        changed = intent.policy()
        changed['functions']['include'] = ['foreign']
        # Keep a newly frozen policy internally consistent so the compiled-selector
        # comparison, rather than the original file-fact guard, rejects it.
        text = original.replace('include=["otelc_app::*"]', 'include=["foreign"]', 1)
        self.assertNotEqual(text, original)
        intent.policy_file.path.write_text(text)
        with self.assertRaisesRegex(ValueError, 'compiled source/function/type selection'):
            prepared.freeze(intent.build, intent.runtime, intent.python.path, intent.policy_file.path,
                            changed, plain=False)


if __name__ == '__main__':
    unittest.main()
