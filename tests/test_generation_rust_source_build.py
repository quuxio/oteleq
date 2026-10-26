"""Independent standalone Rust recipes and pre-build source/MIR binding regressions."""

import copy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import rust_build_recipe as recipe
import rust_source_build as build
from rust_build_fixture import Fixture, write


class RustSourceBuildTests(unittest.TestCase):
    def fixture(self, *, lifetime: bool = False) -> Fixture:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Fixture(Path(temporary.name).resolve(), lifetime=lifetime)

    def test_both_literal_profiles_bind_all_original_inputs_and_channels_without_execution(self) -> None:
        for lifetime in (False, True):
            with self.subTest(lifetime=lifetime):
                fixture = self.fixture(lifetime=lifetime)
                with patch.object(subprocess, 'Popen', side_effect=AssertionError('must not execute')):
                    fixture.build()
                    held = build.read(fixture.intent)
                    self.assertEqual(held.manifest(), fixture.value)
                    held.verify()
                changed = held.manifest(); changed['policy']['languages'].clear()
                self.assertEqual(held.manifest()['policy']['languages'], ['rust'])
                self.assertEqual(held.intent.bindings() is None, not lifetime)

    def test_closed_manifest_and_all_caller_denominators_refuse_rehashed_substitution(self) -> None:
        fixture = self.fixture(); fixture.build()
        original = copy.deepcopy(fixture.value)
        substitutions = {'schema_version': True, 'kind': 'foreign', 'profile': recipe.PROFILES[1],
            'root': '/foreign', 'entry': '/foreign.rs', 'policy': fixture.policy | {'languages': ['cpp']},
            'policy_sha256': '0' * 64, 'selection_sha256': '0' * 64, 'tools': {}, 'sdk': {},
            'inputs': [], 'requests': [], 'selected': [], 'optimisation': True,
            'inventories': [], 'products': [], 'source_complete': 0, 'extra': False}
        for key, value in substitutions.items():
            fixture.value = original | {key: value}; fixture.publish()
            with self.subTest(key=key), self.assertRaises(ValueError): build.read(fixture.intent)
        fixture.value = copy.deepcopy(original); del fixture.value['policy']; fixture.publish()
        with self.assertRaises(ValueError): build.read(fixture.intent)

    def test_every_fixed_compiler_command_and_cwd_is_checked(self) -> None:
        fixture = self.fixture(lifetime=True); fixture.build()
        for label, _ in recipe.commands(fixture.intent):
            path = fixture.output / (label + '.command.json')
            original = json.loads(path.read_text())
            for changed in (original | {'arguments': original['arguments'] + ['--cfg=wrong']},
                            original | {'cwd': '/foreign'}, original | {'extra': False}):
                write(path, changed)
                with self.subTest(label=label), self.assertRaises(ValueError): build.read(fixture.intent)
            write(path, original)

    def test_compiler_result_types_failures_and_budgets_refuse(self) -> None:
        fixture = self.fixture(); fixture.build()
        path = fixture.output / 'plain.result.json'
        original = json.loads(path.read_text())
        for key, value in (('pid', True), ('pid', 1), ('exit_code', False), ('exit_code', 1),
                           ('seconds', True), ('seconds', -1), ('seconds', 1201), ('extra', None)):
            write(path, original | {key: value})
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): build.read(fixture.intent)

    def test_rehashed_request_fields_never_replace_original_intent(self) -> None:
        fixture = self.fixture(lifetime=True); fixture.build()
        for mode in ('inspect', 'lifetime-inspect', 'lifetime-weave'):
            path = fixture.output / (mode + '-request.json')
            original = json.loads(path.read_text())
            for key, value in (('root', '/foreign'), ('selected', ['foreign']), ('sources', {}),
                               ('output', '/never-read'), ('schema_version', True)):
                write(path, original | {key: value}); fixture.rehash(path)
                with self.subTest(mode=mode, key=key), self.assertRaises(ValueError): build.read(fixture.intent)
            write(path, original); fixture.rehash(path)

    def test_equal_changed_inspect_and_weave_cannot_replace_independent_declarations(self) -> None:
        fixture = self.fixture(); fixture.build()
        for mode in ('inspect', 'weave'):
            path = fixture.output / (mode + '-inventory.json')
            value = json.loads(path.read_text()); value['definitions'][0]['end'] += 1
            write(path, value); fixture.rehash(path)
        with self.assertRaises(ValueError): build.read(fixture.intent)

    def test_rehashed_full_MIR_body_and_local_binding_changes_refuse(self) -> None:
        fixture = self.fixture(lifetime=True); fixture.build()
        path = fixture.output / 'lifetime-inspect-inventory.json'
        value = json.loads(path.read_text()); value['bodies'][0]['sites'][-1]['cleanup'] = True
        write(path, value); fixture.rehash(path)
        with self.assertRaises(ValueError): build.read(fixture.intent)
        write(path, fixture.original.lifetime); fixture.rehash(path)
        path = fixture.output / 'lifetime-weave-inventory.json'
        value = json.loads(path.read_text()); value['lifetimes'][fixture.original.function['identity']]['2'] = 'foreign::Type'
        write(path, value); fixture.rehash(path)
        with self.assertRaises(ValueError): build.read(fixture.intent)

    def test_original_manifest_output_and_preinspection_changes_cannot_be_repaired(self) -> None:
        for role in ('manifest', 'product', 'channel', 'source', 'inspection', 'MIR'):
            fixture = self.fixture(lifetime=True); fixture.build(); held = build.read(fixture.intent)
            path = {'manifest': fixture.output / recipe.MANIFEST, 'product': fixture.output / 'plain',
                'channel': fixture.output / 'plain.stdout', 'source': fixture.original.main,
                'inspection': fixture.inspection.file.path, 'MIR': fixture.life_inspection.file.path}[role]
            original = path.read_bytes(); path.write_bytes(original + b' ')
            with self.subTest(role=role), self.assertRaises(ValueError): held.verify()
            path.write_bytes(original)
            with self.subTest(role=role, restored=True), self.assertRaises(ValueError): held.verify()

    def test_dependency_channel_checks_complete_original_paths_before_foreign_reads(self) -> None:
        fixture = self.fixture(); fixture.build()
        path = fixture.output / 'original.d'
        for raw in (b'', b'wrong', b'out: /never-read\n', b'out: unfinished\\', b'out: \0',
                    ('out: ' + str(fixture.original.main) + '\n').encode(), b'out: a\n# env-dep:SECRET=value\n'):
            path.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError): build.read(fixture.intent)
        project = Path('/original')
        recipe.dependency_paths(b'out: a\\ b.rs dollar$$.rs back\\\\slash.rs \\\n a\\ b.rs\n', project,
            (project / 'a b.rs', project / 'back\\slash.rs', project / 'dollar$.rs'))

    def test_new_physical_output_is_required_and_input_trees_are_protected(self) -> None:
        fixture = self.fixture()
        for root in (fixture.project, fixture.tools.directory, fixture.sdk.directory, fixture.sysroot,
                     fixture.sdk.toolchain.directory.parent, fixture.sdk.root / 'native/rust',
                     fixture.sdk.root / 'otelc', fixture.sdk.root / 'adapters/native', fixture.sdk.root / 'native/llvm'):
            with self.subTest(root=str(root)), self.assertRaises(ValueError):
                replace(fixture.intent, output=root / 'new-output').verify()
        alias = fixture.base / 'source-alias'; alias.symlink_to(fixture.project, target_is_directory=True)
        with self.assertRaises(ValueError): replace(fixture.intent, output=alias / 'new-output').verify()
        case_alias = fixture.project.with_name(fixture.project.name.upper())
        if case_alias.exists():
            with self.assertRaises(ValueError): replace(fixture.intent, output=case_alias / 'new-output').verify()
        with self.assertRaises(ValueError): replace(fixture.intent, output=fixture.inspection.file.path.parent).verify()
        fixture.output.mkdir()
        with self.assertRaises(ValueError): fixture.freeze()

    def test_caller_policy_entry_dependencies_and_lifetime_mode_remain_explicit(self) -> None:
        fixture = self.fixture()
        for altered in (replace(fixture.intent, optimisation=True), replace(fixture.intent, entry=fixture.base / 'foreign.rs'),
                        replace(fixture.intent, dependencies=()), replace(fixture.intent, lifetime_inspection=fixture.inspection),
                        replace(fixture.intent, sdk=replace(fixture.sdk, platform='darwin'))):
            with self.assertRaises(ValueError): altered.verify()
        with self.assertRaises(ValueError): build.read(None)
        for changed in (fixture.policy | {'schema_version': True}, fixture.policy | {'languages': ['cpp']},
                        fixture.policy | {'context': {'tasks': True, 'http': False}},
                        fixture.policy | {'lifetimes': fixture.policy['lifetimes'] | {'enabled': 0}}):
            with self.assertRaises(ValueError): build.policy(changed)
        (fixture.project / 'Cargo.toml').write_text('literal unsupported Cargo project')
        with self.assertRaises(ValueError): fixture.intent.verify()
        lifetime = self.fixture(lifetime=True)
        disabled = lifetime.policy | {'lifetimes': lifetime.policy['lifetimes'] | {'exclude': ['**']}}
        with self.assertRaises(ValueError): replace(lifetime.intent, policy_json=json.dumps(disabled)).verify()

    def test_missing_or_linked_fixed_channels_are_not_adopted(self) -> None:
        fixture = self.fixture(); fixture.build()
        path = fixture.output / 'plain.stderr'; path.unlink()
        with self.assertRaises(FileNotFoundError): build.read(fixture.intent)
        foreign = fixture.base / 'foreign'; foreign.write_bytes(b'')
        path.symlink_to(foreign)
        with self.assertRaises(ValueError): build.read(fixture.intent)


if __name__ == '__main__':
    unittest.main()
