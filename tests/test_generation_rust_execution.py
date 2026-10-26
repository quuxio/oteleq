"""Literal Rust health/start/release/final records bind caller-owned identities."""

import copy
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import rust_execution as execution
import rust_health
import rust_prepared as prepared
import test_generation_rust_prepared as preparation
from rust_build_fixture import digest, write


def publish(path: Path, value: dict) -> None:
    write(path, value)
    path.chmod(0o600)


def health(intent: prepared.Intent) -> dict:
    """Author the full Rust health wire record without calling an SDK renderer."""
    def exported(unit: str) -> dict:
        return {'exporters_observed': 1, 'unit': unit, 'batches_started': '2', 'batches_succeeded': '2',
                'batches_failed': '0', 'batches_pending': '0', 'units_started': '3',
                'units_succeeded': '3', 'units_failed': '0'}
    policy = intent.policy()
    selection = {key: policy[key] for key in ('sources', 'functions')}
    lifetime = intent.source().intent.lifetime
    if lifetime: selection['lifetimes'] = {key: policy['lifetimes'][key] for key in ('enabled', 'include', 'exclude')}
    value = {'schema_version': 5 if lifetime else 1, 'kind': 'otelc.runtime-health', 'language': 'rust',
        'scope': 'sdk_pipeline', 'pid': 23, 'policy_sha256': digest(policy), 'selection_sha256': digest(selection),
        'phase': 'final', 'sdk_attached': True, 'lifecycle': {'flush': 'succeeded', 'shutdown': 'succeeded'},
        'controls': {'schema_version': 1, 'pid': 23, 'collection': False, 'emission': False, 'effective_emission_off': True},
        'metric_flush': {'attempts': '2', 'failed_attempts': '0'},
        'span_accounting': {'processors_observed': 1, 'batch_processors_observed': 1,
            'sampled_started': '3', 'sampled_ended': '3', 'sampled_active': '0',
            'queue_pending': '0', 'queue_dropped': '0', 'queue_evidence': 'derived_after_shutdown'},
        'function_accounting': {'registered': '1', 'started': '3', 'ended': '3', 'active': '0',
            'lost': '0', 'invalid': '0', 'metadata_errors': '0', 'closed': True},
        'diagnostics': {'dropped': '0'}, 'trace_exports': exported('spans'), 'metric_exports': exported('metric_points'),
        'source_complete': False, 'downstream_receipt': 'unavailable', 'otlp_partial_rejection': 'unavailable'}
    if lifetime:
        value['drop_accounting'] = {'types': '1', 'admitted': '2', 'completed': '1', 'censored': '1',
            'live': '0', 'dropping': '0', 'ending': '0', 'lost': '0', 'duplicates': '0', 'invalid': '0',
            'closing': True, 'closed': True}
    return value


class RustExecutionTests(unittest.TestCase):
    def fixture(self, *, lifetime: bool = False, plain: bool = False):
        helper = preparation.RustPreparedTests('test_both_source_profiles_and_lanes_hold_literal_arguments_without_processes')
        self.addCleanup(helper.doCleanups)
        fixture, intent = helper.fixture(lifetime=lifetime, plain=plain)
        helper.publish(intent)
        launch = prepared.read(intent)
        owner = execution.Owner(22, 21, 23, tuple(prepared.command(launch)))
        # Literal statements are separate from actual kernel observations. The
        # session monitor supplies those observations before production binding.
        nonce = launch.value(prepared.REQUEST)['launch_id']
        supervisor = {'schema_version': 1, 'kind': 'otelc.rust.supervisor', 'pid': 22,
            'parent_pid': 21, 'process_group': 22, 'session': 22, 'launch_id': nonce}
        application = {'schema_version': 1, 'kind': 'otelc.rust.application', 'pid': 23,
            'parent_pid': 22, 'process_group': 23, 'session': 23, 'supervisor_pid': 22,
            'launch_id': nonce, 'image': launch.value(prepared.PLAN)['image'],
            'phase': 'waiting_exec', 'source_complete': False}
        for name, value in zip(execution.START_FILES, (supervisor, application)):
            publish(intent.runtime / name, value)
        return fixture, launch, owner

    def complete(self, started: execution.Started) -> dict:
        launch, owner = started.launch, started.owner
        app = launch.intent.runtime / 'app'; app.mkdir(mode=0o700)
        checkpoint = None if launch.intent.plain else health(launch.intent)
        if checkpoint is not None: publish(app / 'health.json', checkpoint)
        nonce = launch.value(prepared.REQUEST)['launch_id']
        acknowledgement = {'schema_version': 1, 'kind': 'otelc.rust.host-release',
                           'launch_id': nonce, 'pid': 23, 'supervisor_pid': 22}
        path = launch.intent.runtime / execution.RELEASE
        if path.exists():
            self.assertEqual(json.loads(path.read_text()), acknowledgement)
        else:
            publish(path, acknowledgement)
        value = {'schema_version': 1, 'kind': 'otelc.rust.execution', 'profile': 'rust1981-owned-standalone-v1',
            'request_sha256': digest(launch.value(prepared.REQUEST)), 'plan_sha256': digest(launch.value(prepared.PLAN)),
            'supervisor': json.loads((launch.intent.runtime / execution.START_FILES[0]).read_text()),
            'application': json.loads((launch.intent.runtime / execution.START_FILES[1]).read_text()),
            'released': True, 'process_exit_code': 0, 'supervisor_exit_code': 0, 'exec_verified': False,
            'sdk_health': checkpoint, 'inputs_rechecked': True, 'failures': {}, 'source_complete': False}
        publish(launch.intent.runtime / execution.FINAL, value)
        return value

    def test_all_profiles_and_lanes_hold_start_release_completion_without_inventing_image_proof(self) -> None:
        for lifetime in (False, True):
            for plain in (False, True):
                _, launch, owner = self.fixture(lifetime=lifetime, plain=plain)
                bound = execution.bind(launch, owner); expected = self.complete(bound)
                result = execution.finish(bound, 0); result.verify()
                self.assertEqual(result.final.value(), expected)
                self.assertFalse(result.final.value()['exec_verified'])
                self.assertEqual(result.health is None, plain)
                if result.health is not None:
                    self.assertEqual(result.health.value()['schema_version'], 5 if lifetime else 1)

    def test_start_owner_exact_types_groups_sessions_images_and_early_release_refuse(self) -> None:
        for kind in ('pid', 'command', 'parent', 'group', 'session', 'image', 'release', 'final'):
            _, launch, owner = self.fixture()
            if kind == 'pid': owner = replace(owner, pid=True)
            elif kind == 'command': owner = replace(owner, command=('foreign',))
            elif kind in ('release', 'final'):
                publish(launch.intent.runtime / (execution.RELEASE if kind == 'release' else execution.FINAL), {})
            else:
                path = launch.intent.runtime / execution.START_FILES[1]
                value = json.loads(path.read_text())
                key = {'parent': 'parent_pid', 'group': 'process_group', 'session': 'session', 'image': 'image'}[kind]
                value[key] = {} if kind == 'image' else 21
                publish(path, value)
            with self.subTest(kind=kind), self.assertRaises(ValueError): execution.bind(launch, owner)

    def test_every_completion_field_and_nonzero_or_unavailable_host_exit_refuses(self) -> None:
        _, launch, owner = self.fixture(); bound = execution.bind(launch, owner); original = self.complete(bound)
        path = launch.intent.runtime / execution.FINAL
        for key in original:
            publish(path, original | {key: 'foreign'})
            with self.subTest(key=key), self.assertRaises(ValueError): execution.finish(bound, 0)
        publish(path, original)
        for code in (True, None, 1, -9):
            with self.subTest(code=code), self.assertRaises(ValueError): execution.finish(bound, code)

    def test_plain_sdk_files_and_changed_original_acknowledgement_refuse(self) -> None:
        for name in ('health.json', 'plan.json', 'policy.json', 'control.json', 'release'):
            _, launch, owner = self.fixture(plain=True); bound = execution.bind(launch, owner); self.complete(bound)
            path = launch.intent.runtime / (execution.RELEASE if name == 'release' else 'app/' + name)
            publish(path, {})
            with self.subTest(name=name), self.assertRaises(ValueError): execution.finish(bound, 0)

    def test_original_start_final_release_and_health_facts_survive_restoration(self) -> None:
        for role in ('start', 'final', 'release', 'health'):
            _, launch, owner = self.fixture(); bound = execution.bind(launch, owner); self.complete(bound)
            accepted = execution.finish(bound, 0)
            path = launch.intent.runtime / {'start': execution.START_FILES[0], 'final': execution.FINAL,
                'release': execution.RELEASE, 'health': 'app/health.json'}[role]
            raw = path.read_bytes(); path.write_bytes(raw + b' ')
            with self.subTest(role=role), self.assertRaises(ValueError): accepted.verify()
            path.write_bytes(raw)
            with self.subTest(role=role, restored=True), self.assertRaises(ValueError): accepted.verify()

    def test_diagnostic_health_requires_exact_rust_profile_and_closed_loss_free_counters(self) -> None:
        _, launch, owner = self.fixture(lifetime=True)
        value = health(launch.intent)
        options = {'pid': 23, 'policy': value['policy_sha256'], 'selection': value['selection_sha256'], 'lifetime': True}
        self.assertIs(rust_health.validate(value, **options), value)
        substitutions = [('schema_version', 1), ('language', 'cpp'), ('pid', True), ('source_complete', 0),
            ('phase', 'running'), ('drop_accounting.dropping', '1'), ('drop_accounting.completed', '2'),
            ('drop_accounting.censored', '0'), ('drop_accounting.types', '0'), ('drop_accounting.closed', 1),
            ('drop_accounting.lost', '1'), ('drop_accounting.live', None), ('function_accounting.active', '1'),
            ('function_accounting.metadata_errors', '1'), ('controls.effective_emission_off', False),
            ('span_accounting.queue_pending', None), ('trace_exports.units_succeeded', '2'),
            ('metric_exports.units_failed', '1'), ('extra', False)]
        for key, substitute in substitutions:
            changed = copy.deepcopy(value); parts = key.split('.'); target = changed
            for part in parts[:-1]: target = target[part]
            target[parts[-1]] = substitute
            with self.subTest(key=key), self.assertRaises(ValueError): rust_health.validate(changed, **options)
        for changed in ({'pid': True}, {'lifetime': 1}, {'policy': 'foreign'}, {'selection': 'foreign'}):
            with self.assertRaises(ValueError): rust_health.validate(value, **(options | changed))
        with self.assertRaises(ValueError): rust_health.validate(value, **(options | {'lifetime': False}))


if __name__ == '__main__':
    unittest.main()
