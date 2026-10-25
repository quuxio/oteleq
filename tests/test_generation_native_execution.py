"""Independent native ownership and final-health records with refusal controls."""

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]

import native_execution as execution
import native_health
import native_inputs as inputs
import native_prepared as prepared
import native_provider_fixture as fixture
from test_generation_native_prepared import setup


def write(path: Path, value: dict) -> None:
    fixture.write(path, value)
    path.chmod(0o600)


def health(launch: prepared.Prepared) -> dict:
    """A complete literal checkpoint, authored without the SDK health renderer."""
    def exported(unit):
        return {'exporters_observed': 1, 'unit': unit, 'batches_started': '2', 'batches_succeeded': '2',
                'batches_failed': '0', 'batches_pending': '0', 'units_started': '3',
                'units_succeeded': '3', 'units_failed': '0'}
    return {'schema_version': 1, 'kind': 'otelc.runtime-health', 'language': 'cpp', 'scope': 'sdk_pipeline',
        'pid': 23, 'policy_sha256': fixture.digest(launch.intent.policy()),
        'selection_sha256': fixture.digest({key: launch.intent.policy()[key] for key in ('sources', 'functions')}), 'phase': 'final',
        'sdk_attached': True, 'lifecycle': {'flush': 'succeeded', 'shutdown': 'succeeded'},
        'controls': {'schema_version': 1, 'pid': 23, 'collection': True, 'emission': True, 'effective_emission_off': False},
        'metric_flush': {'attempts': '2', 'failed_attempts': '0'},
        'span_accounting': {'processors_observed': 1, 'batch_processors_observed': 1,
            'sampled_started': '3', 'sampled_ended': '3', 'sampled_active': '0',
            'queue_pending': '0', 'queue_dropped': '0', 'queue_evidence': 'derived_after_shutdown'},
        'function_accounting': {'registered': '1', 'started': '3', 'ended': '3', 'active': '0',
            'lost': '0', 'invalid': '0', 'metadata_errors': '0', 'closed': True},
        'diagnostics': {'dropped': '0'}, 'trace_exports': exported('spans'), 'metric_exports': exported('metric_points'),
        'source_complete': False, 'downstream_receipt': 'unavailable', 'otlp_partial_rejection': 'unavailable'}


def start(root: Path, *, plain: bool = False):
    launch = prepared.read(setup(root, plain=plain))
    owner = execution.Owner(22, 21, 23, tuple(prepared.command(launch.intent)))
    supervisor = {'schema_version': 1, 'kind': 'otelc.native.supervisor', 'pid': 22,
                  'parent_pid': 21, 'process_group': 22, 'session': 22, 'launch_id': 'a' * 32}
    image = launch.intent.build.file('plain' if plain else 'instrumented').path
    application = {'schema_version': 1, 'kind': 'otelc.native.application', 'pid': 23,
        'parent_pid': 22, 'process_group': 23, 'session': 23, 'supervisor_pid': 22,
        'launch_id': 'a' * 32, 'image': fixture.identity(image, gate=True),
        'phase': 'waiting_exec', 'source_complete': False}
    for name, value in zip(prepared.START_FILES, (supervisor, application)):
        write(launch.intent.runtime / name, value)
    return launch, owner


def complete(started: execution.Started) -> dict:
    launch = started.launch
    runtime = launch.intent.runtime
    app = runtime / 'app'; app.mkdir(mode=0o700)
    value = None if launch.intent.plain else health(launch)
    if value is not None:
        write(app / 'health.json', value)
    acknowledgement = {'schema_version': 1, 'kind': 'otelc.native.host-release',
                       'launch_id': 'a' * 32, 'pid': 23, 'supervisor_pid': 22}
    if not (runtime / execution.RELEASE).exists():
        write(runtime / execution.RELEASE, acknowledgement)
    else:
        assert json.loads((runtime / execution.RELEASE).read_bytes()) == acknowledgement
    final = {'schema_version': 1, 'kind': 'otelc.native.execution', 'profile': 'native-owned-v1',
        'request_sha256': fixture.digest(json.loads((runtime / prepared.REQUEST).read_bytes())),
        'plan_sha256': fixture.digest(json.loads((runtime / prepared.PLAN).read_bytes())),
        'supervisor': json.loads((runtime / prepared.START_FILES[0]).read_bytes()),
        'application': json.loads((runtime / prepared.START_FILES[1]).read_bytes()),
        'released': True, 'process_exit_code': 0, 'supervisor_exit_code': 0, 'exec_verified': False,
        'sdk_health': value, 'inputs_rechecked': True, 'failures': {}, 'source_complete': False}
    write(runtime / execution.FINAL, final)
    return final


class NativeExecutionTests(unittest.TestCase):
    def test_owned_plain_and_woven_execution_retains_original_files(self):
        for plain in (True, False):
            with self.subTest(plain=plain), tempfile.TemporaryDirectory() as temporary:
                launch, owner = start(Path(temporary).resolve(), plain=plain)
                bound = execution.bind(launch, owner)
                expected = complete(bound)
                final = execution.finish(bound, 0)
                self.assertEqual(final.final.value(), expected)
                self.assertEqual(final.health is None, plain)
                final.verify()
                final.final.file.path.write_bytes(final.final.file.path.read_bytes())
                with self.assertRaises(ValueError): final.verify()

    def test_start_fields_types_process_group_and_early_release_are_refused(self):
        for kind in ('supervisor', 'group', 'session', 'pid', 'image', 'release', 'final', 'owner', 'command'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                launch, owner = start(Path(temporary).resolve())
                if kind in ('release', 'final'):
                    write(launch.intent.runtime / (execution.RELEASE if kind == 'release' else execution.FINAL), {})
                elif kind == 'owner': owner = execution.Owner(22, 22, 23, owner.command)
                elif kind == 'command': owner = execution.Owner(22, 21, 23, ('foreign-program',))
                else:
                    path = launch.intent.runtime / prepared.START_FILES[int(kind != 'supervisor')]
                    value = json.loads(path.read_bytes())
                    if kind == 'supervisor': value['pid'] = 23
                    elif kind == 'group': value['process_group'] = 22
                    elif kind == 'session': value['session'] = 22
                    elif kind == 'pid': value['pid'] = True
                    else: value['image']['sha256'] = '0' * 64
                    write(path, value)
                with self.assertRaises(ValueError): execution.bind(launch, owner)

    def test_every_final_field_and_actual_nonzero_exit_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            launch, owner = start(Path(temporary).resolve())
            bound = execution.bind(launch, owner)
            original = complete(bound)
            path = launch.intent.runtime / execution.FINAL
            for key in original:
                altered = copy.deepcopy(original)
                altered[key] = '<wrong>'
                write(path, altered)
                with self.subTest(key=key), self.assertRaises(ValueError): execution.finish(bound, 0)
            write(path, original)
            for code in (True, 1, -9, None):
                with self.subTest(code=code), self.assertRaises(ValueError): execution.finish(bound, code)

    def test_plain_sdk_records_and_altered_acknowledgement_are_refused(self):
        for name in ('health.json', 'control.json', 'policy.json', 'plan.json', 'acknowledgement'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                launch, owner = start(Path(temporary).resolve(), plain=True)
                bound = execution.bind(launch, owner); complete(bound)
                path = launch.intent.runtime / ('native-host-release.json' if name == 'acknowledgement' else 'app/' + name)
                write(path, {})
                with self.assertRaises(ValueError): execution.finish(bound, 0)


class NativeHealthTests(unittest.TestCase):
    def test_complete_health_is_checked_without_substituting_unavailable_counters(self):
        with tempfile.TemporaryDirectory() as temporary:
            launch, _ = start(Path(temporary).resolve())
            value = health(launch)
            options = {'language': 'cpp', 'pid': 23, 'policy': value['policy_sha256'], 'selection': value['selection_sha256']}
            self.assertIs(native_health.validate(value, **options), value)
            changes = [('schema_version', True), ('pid', True), ('language', 'c'), ('source_complete', 0),
                       ('policy_sha256', '0' * 64), ('selection_sha256', '0' * 64), ('phase', 'running'),
                       ('lifecycle', {'flush': 'failed', 'shutdown': 'succeeded'}),
                       ('function_accounting.active', '1'), ('function_accounting.closed', 1),
                       ('function_accounting.started', '4'), ('function_accounting.lost', None),
                       ('span_accounting.queue_pending', None), ('span_accounting.sampled_ended', '2'),
                       ('span_accounting.processors_observed', True), ('span_accounting.queue_evidence', 'unavailable'),
                       ('metric_exports.batches_started', '3'), ('trace_exports.units_failed', '1'),
                       ('metric_exports.exporters_observed', 0), ('metric_exports.unit', 'spans'),
                       ('controls.collection', 1), ('controls.effective_emission_off', True),
                       ('diagnostics.dropped', '1'), ('metric_flush.failed_attempts', '1')]
            for name, replacement in changes:
                altered = copy.deepcopy(value); target = altered; words = name.split('.')
                for word in words[:-1]: target = target[word]
                target[words[-1]] = replacement
                with self.subTest(name=name), self.assertRaises(ValueError): native_health.validate(altered, **options)
            for name in value:
                altered = copy.deepcopy(value); altered.pop(name)
                with self.subTest(missing=name), self.assertRaises(ValueError): native_health.validate(altered, **options)

    def test_counters_reject_noncanonical_types_and_uint64_overflow(self):
        for value in (None, True, 1, 1.0, '', '-1', '01', ' 1', '\u0661', str(1 << 64)):
            with self.subTest(value=value), self.assertRaises(ValueError): native_health.count(value)
        self.assertEqual(native_health.count(str((1 << 64) - 1)), (1 << 64) - 1)


class NativePublicationTests(unittest.TestCase):
    def test_pending_link_is_never_accepted_or_read_until_publication_completes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); path = root / 'start.json'
            write(path, {'complete': True}); staged = root / 'start.json.staging'
            os.link(path, staged)
            with self.assertRaises(inputs.PublicationPending): inputs.published(path)
            staged.unlink()
            value = inputs.published(path)
            self.assertEqual(value.value(), {'complete': True})
            with self.assertRaises(FileNotFoundError): inputs.published(root / 'missing')
            path.chmod(0o644)
            with self.assertRaises(ValueError): inputs.published(path)


if __name__ == '__main__':
    unittest.main()
