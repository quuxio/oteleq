"""Synthetic launch contracts supplement the separate real SDK preparation probe."""

import copy
import hashlib
import json
import os
from pathlib import Path
import unittest

import test_generation_java_launch as base
import java_action_bindings as compiler
import java_action_launch as action
import java_actions
import java_launch as launch
import java_profiles
import java_provider as provider
import java_witness


class JavaActionLaunchTests(unittest.TestCase):
    def setUp(self):
        base.JavaLaunchTests.setUp(self)
        self.entry.update(name='App.selected', package='', parameters=['int'], output='int',
                          java_profile=java_profiles.SAFE, java_witness_profile=java_witness.HANDLE_PROFILE)
        self.data = provider.configuration(self.entry, 'http://127.0.0.1:54321', 'case')
        for name in (java_profiles.PATCH, provider.HELPER, 'otelc/cli_bootstrap.py'):
            path = self.root / name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(b'trusted unit tool')
        (self.runtime / 'agent.properties').write_text(launch.properties(
            launch.agent_values(self.data, 'App', 'selected', java_profiles.SAFE, action=True)))
        (self.runtime / 'plan.properties').write_text(launch.properties(launch.plan_values(self.runtime, self.data, self.selection)))
        declared, route = java_actions.declarations(self.entry, 'App', list(self.application['bindings']))
        roles = {}
        for role, row in declared.items():
            class_sha = self.application['bindings'][row['owner']]['class_sha256']
            method_sha = hashlib.sha256(role.encode()).hexdigest()
            fields = [java_witness.HANDLE_PROFILE, role, *(row[key] for key in ('owner', 'name', 'descriptor')), class_sha, method_sha]
            roles[role] = {**row, 'class_sha256': class_sha, 'method_sha256': method_sha,
                           'probe_id': hashlib.sha256('\n'.join(fields).encode()).hexdigest()}
        self.document = {'schema_version': 3, 'kind': 'otelc.java-witness-bindings', 'profile': java_witness.HANDLE_PROFILE,
                         'bindings': roles, 'route': route.metadata(declared, roles)}
        self.path = action.bindings_file(self.folder);self.path.parent.mkdir(mode=0o700)
        self.path.write_text(json.dumps(self.document));self.path.chmod(0o600)
        record = {'schema_version': 1, 'profile': java_witness.HANDLE_PROFILE, 'bindings_sha256': provider.capture.file_digest(self.path)}
        (self.path.parent / 'compiler-inputs.json').write_text(json.dumps(record))
        self.value = base.JavaLaunchTests.value(self)
        self.value['argv'] = launch.expected_argv(self.root, self.java, self.classes, 'OteleqDriver', self.runtime,
            self.data, 'App', 'selected', False, java_profiles.SAFE, action=True)
        paths = [self.java, self.root / provider.AGENT, self.root / java_profiles.PATCH, self.root / provider.EXTENSION,
                 self.runtime / 'agent.properties', self.runtime / 'plan.properties', self.runtime / 'selection.json',
                 self.root / provider.HELPER, self.path]
        inputs = [launch.identity(path) for path in paths]
        hashes = {'build_sha256': provider.digest(self.value['application']), 'policy_sha256': provider.digest(self.data),
                  'selection_sha256': provider.digest(self.selection), 'tooling_sha256': provider.digest(inputs)}
        values = {'schema_version': '3', 'profile': java_witness.HANDLE_PROFILE, 'socket': str(self.runtime / 'witness.sock'),
                  **{name: hashes[name + '_sha256'] for name in ('build', 'policy', 'selection', 'tooling')}}
        for role, row in roles.items():
            values.update({role + '.' + key: item for key, item in row.items()})
            values[role + '.origin'] = self.classes.as_uri().replace('file:///', 'file:/', 1) + '/'
        values.update({'route.' + key: str(item) for key, item in self.document['route'].items()})
        (self.runtime / 'witness.properties').write_text(launch.properties(values))
        self.metadata = {'schema_version': 3, 'kind': 'otelc.java-witness-launch', 'profile': java_witness.HANDLE_PROFILE,
                         'socket': values['socket'], 'final_report': str(self.runtime / 'witness-health.json'), **hashes,
                         'route': self.document['route'], 'bindings': roles, 'bindings_sha256': record['bindings_sha256'],
                         'runtime_confirmation_required': True, 'receiver_confirmation_required': True}
        self.rewrite_metadata(self.metadata)
        self.value['tooling'] = inputs + [launch.identity(self.runtime / name) for name in ('witness.properties', 'witness.json')]

    def rewrite_metadata(self, value):
        (self.runtime / 'witness.json').write_text(json.dumps(value))

    def verify(self, value):
        launch.verify(value, root=self.root, project=self.project, folder=self.folder, tools=self.tools,
                      runtime=self.runtime, entry=self.entry, data=self.data, plain=False)

    def refresh_tail(self, value):
        value['tooling'][-2:] = [launch.identity(self.runtime / name) for name in ('witness.properties', 'witness.json')]

    def test_complete_action_launch_has_independent_inputs_and_fixed_isolated_cli(self):
        self.verify(self.value)
        expected = provider.cli(self.root, self.entry)
        self.assertEqual(expected[1:4], ['-I', '-S', '-B'])
        self.assertEqual(expected[-1], self.root / 'otelc/cli_bootstrap.py')
        with action.preserved_bindings(self.folder):
            self.assertEqual(len(action.seals(self.folder)), 2)
        self.assertEqual(len(action.tooling(self.root, self.folder, self.runtime)), 4)

    def test_rehashed_metadata_fields_and_scalar_type_changes_refuse(self):
        edits = (('schema_version', 3.0), ('profile', java_witness.PROFILE), ('socket', '/foreign/socket'),
                 ('final_report', '/foreign/final'), ('runtime_confirmation_required', 1),
                 ('receiver_confirmation_required', False), ('build_sha256', '0' * 64), ('extra', True))
        for key, item in edits:
            changed = copy.deepcopy(self.metadata);changed[key] = item
            value = copy.deepcopy(self.value);self.rewrite_metadata(changed);self.refresh_tail(value)
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.verify(value)
        self.rewrite_metadata(self.metadata)

    def test_rehashed_property_changes_and_missing_tooling_refuse(self):
        path = self.runtime / 'witness.properties'
        path.write_text(path.read_text() + 'unexpected=1\n')
        value = copy.deepcopy(self.value);self.refresh_tail(value)
        with self.assertRaisesRegex(ValueError, 'fixed action properties'):
            self.verify(value)
        value = copy.deepcopy(self.value);value['tooling'].pop(-3)
        with self.assertRaises(ValueError):
            self.verify(value)

    def test_unsafe_links_modes_sizes_and_unknown_input_names_refuse(self):
        path = self.runtime / 'witness.json';raw = path.read_bytes()
        for mode in (0o600, 0o644):
            path.chmod(mode)
            self.assertEqual(action.snapshot(self.runtime, path.name).raw, raw)
        path.chmod(0o666)
        with self.assertRaises(ValueError):action.snapshot(self.runtime, path.name)
        path.chmod(0o644);os.link(path, self.runtime / 'alias')
        with self.assertRaises(ValueError):action.snapshot(self.runtime, path.name)
        (self.runtime / 'alias').unlink();path.unlink();path.symlink_to(self.manifest)
        with self.assertRaises(OSError):action.snapshot(self.runtime, path.name)
        path.unlink();path.write_bytes(b'x' * (action.MAX_INPUT + 1))
        with self.assertRaises(ValueError):action.snapshot(self.runtime, path.name)
        for name in ('../witness.json', 'unknown.json'):
            with self.assertRaises(ValueError):action.snapshot(self.runtime, name)

    def test_preparation_mutation_refuses_and_cancellation_keeps_the_primary_error(self):
        with self.assertRaisesRegex(ValueError, 'publication differs'):
            with action.preserved_bindings(self.folder):
                self.path.write_text('{}')
        self.path.write_text(json.dumps(self.document))
        original = KeyboardInterrupt('controlled cancellation')
        with self.assertRaises(KeyboardInterrupt) as caught:
            with action.preserved_bindings(self.folder):
                self.path.write_text('{}')
                raise original
        self.assertIs(caught.exception, original)
        self.assertTrue(any('input audit also failed' in note for note in original.__notes__))
