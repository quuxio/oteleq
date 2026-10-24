"""Generated host composition retains real plans and failures without SDK inference."""

import copy
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_generation_java_actions as generated
import test_generation_java_graph as graphs
from test_generation_java_witness import identity
import generation
import java_action_run as run
import java_action_launch
import java_actions
import java_launch
import otelc_capture


class JavaActionRunTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='oeq-ar-', dir='/tmp')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.folder = self.root / 'attempt';self.folder.mkdir()
        self.runtime = self.root / 'r';self.runtime.mkdir(mode=0o700)
        self.entry = generated.entry()
        self.case = {'id': 'retained-case', 'arguments': [7]}
        bindings = java_action_launch.bindings_file(self.folder);bindings.parent.mkdir(mode=0o700)
        bindings.write_text('{}');bindings.chmod(0o600)
        (bindings.parent / 'compiler-inputs.json').write_text(json.dumps({'schema_version': 1,
            'profile': 'java-sync-private-handle-v1', 'bindings_sha256': otelc_capture.file_digest(bindings)}))

    def session(self, **options):
        session = run.Session(self.folder, self.runtime, self.entry, self.case, plain=True, **options)
        self.addCleanup(session.action.harness.close)
        return session

    def test_plain_host_plan_and_partial_records_are_owned_and_stable(self):
        session = self.session()
        self.assertEqual(session.action.case_id, java_actions.case_id(self.case))
        self.assertEqual(session.action.actions, tuple(java_actions.action_ids(self.case)))
        self.assertEqual(len(session.action.attempt_id), 64)
        self.assertEqual(session.environment()['OTELEQ_ACTION_CASE'], java_actions.case_id(self.case))
        with run.retained({'interaction': session}):
            pass
        self.assertEqual(len(session.audit()), 64)
        path = self.folder / run.DIRECTORY / run.RECORD
        value = json.loads(path.read_bytes())
        self.assertEqual(value['expected'], {})
        self.assertIsNone(value['identity'])
        self.assertEqual(value['controls'], [])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'record changed'):
            session.audit()

    def test_controllers_share_the_original_process_and_deadline(self):
        metrics = Mock()
        session = self.session(metrics=metrics)
        process = SimpleNamespace(pid=123)
        timeline = Mock()
        timeline.attach_mock(metrics, 'metrics')
        with patch.object(session.action, 'poll') as poll, patch.object(session.action, 'finish') as finish:
            timeline.attach_mock(poll, 'action_poll');timeline.attach_mock(finish, 'action_finish')
            session.poll(process, 123.5);session.finish(process)
            self.assertEqual([call[0] for call in timeline.mock_calls],
                             ['metrics.poll', 'action_poll', 'action_finish', 'metrics.finish'])
            poll.assert_called_once_with(process, 123.5)
            finish.assert_called_once_with(process)
        session.close()

    def test_primary_execution_or_cancellation_survives_a_retention_failure(self):
        session = self.session()
        for failure in (RuntimeError('application failure'), KeyboardInterrupt('cancelled')):
            with patch.object(session, 'close', side_effect=OSError('retention denied')):
                with self.assertRaises(type(failure)) as caught:
                    with run.retained({'interaction': session}):
                        raise failure
                self.assertIs(caught.exception, failure)
                self.assertIn('retention denied', failure.__notes__[0])
        session.close()
        with run.retained({}):
            pass

    def test_failed_execution_still_retains_the_available_control_replies(self):
        session = self.session()
        session.action.controls = [{'operation': 'status', 'arguments': [], 'reply': {'evidence': 'partial'}}]
        failure = RuntimeError('stopped before release')
        with self.assertRaises(RuntimeError) as caught:
            with run.retained({'interaction': session}):
                raise failure
        self.assertIs(caught.exception, failure)
        session.audit()
        root = self.folder / run.DIRECTORY
        value = json.loads((root / run.RECORD).read_bytes())
        self.assertEqual(value['controls'][0]['file'], 'controls-0.json')
        self.assertEqual(json.loads((root / value['controls'][0]['file']).read_bytes()), session.action.controls)
        (root / 'extra').write_text('unexpected')
        with self.assertRaises(ValueError):
            session.audit()

    def test_identical_byte_replacement_of_a_retained_control_file_is_detected(self):
        session = self.session();session.action.controls = [{'reply': 'original'}];session.close()
        path = self.folder / run.DIRECTORY / 'controls-0.json'
        replacement = path.with_name('replacement');replacement.write_bytes(path.read_bytes());replacement.chmod(0o600)
        replacement.replace(path)
        with self.assertRaisesRegex(ValueError, 'record changed'):
            session.audit()

    def test_compiler_publication_cannot_change_after_preparation_or_execution(self):
        session = self.session();session.close()
        path = java_action_launch.bindings_file(self.folder).parent / 'compiler-inputs.json'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'compiled action inputs changed'):
            session.audit()

    def test_reply_chunks_preserve_every_row_and_enforce_file_and_aggregate_limits(self):
        rows = [{'index': index, 'reply': 'abc'} for index in range(4)]
        with patch.object(run, 'MAX_RECORD', 40):
            chunks = run.control_chunks(rows)
            self.assertEqual([item for chunk in chunks for item in json.loads(chunk)], rows)
            self.assertTrue(all(len(chunk) <= 40 for chunk in chunks))
            with patch.object(run, 'MAX_CONTROL_FILES', 1), self.assertRaisesRegex(ValueError, 'history'):
                run.control_chunks(rows)
            with self.assertRaisesRegex(ValueError, 'record'):
                run.control_chunks([{'reply': 'x' * 50}])
        self.assertEqual(run.control_chunks([]), [])
        session = self.session()
        with patch.object(run, 'MAX_RECORD', 10), self.assertRaisesRegex(ValueError, 'byte budget'):
            session.close()

    def test_instrumented_inputs_are_derived_before_any_harness_or_sdk_control(self):
        self.entry['otelc_function'] = 'example.Work.target(int)'
        project = self.folder / 'project';project.mkdir()
        app = {'bindings': {'example.Work': {'source': str(project / 'Work.java'), 'policy_path': 'Work.java'}}}
        (self.folder / java_launch.APPLICATION_FILE).write_text(json.dumps(app))
        (self.folder / java_launch.LAUNCH_FILE).write_text('{}')
        (self.folder / 'policy.toml').write_text('schema_version = 3\n')
        expected = {**dict(identity().hashes), 'route_binding_sha256': '8' * 64}
        with patch('java_action_run.java_action_launch.verify', return_value=expected) as verify:
            session = run.Session(self.folder, self.runtime, self.entry, self.case, plain=False)
            self.addCleanup(session.action.harness.close)
        self.assertEqual(verify.call_args.kwargs['owner'], 'example.Work')
        self.assertEqual(verify.call_args.kwargs['application'], app)
        self.assertEqual(session.action.expected, expected)
        self.assertEqual(session.action.controls, [])
        session.close();session.audit()

    def test_invalid_selection_or_failed_controller_creation_cannot_leave_an_open_harness(self):
        with self.assertRaises(ValueError):
            run.Session(self.folder, None, self.entry, self.case, plain=True)
        with patch('java_action_run.java_action.Harness') as harness:
            with patch('java_action_run.java_action_session.Session', side_effect=ValueError('invalid expected profile')):
                with self.assertRaises(ValueError):
                    run.Session(self.folder, self.runtime, self.entry, self.case, plain=True)
            harness.return_value.close.assert_called_once_with()
        with self.assertRaises(ValueError):
            run.Session(self.folder, self.runtime, {'java_witness_profile': 'unknown'}, self.case, plain=True)

    def test_typed_outcomes_are_parsed_without_producer_input(self):
        raw = b'before\nreturn:java.lang.Integer:OA==\nafter\n'
        self.assertEqual(run.outcomes(raw, {**self.entry, 'globals': []}, self.case), [False])
        raw = b'before\nerror:java.lang.IllegalStateException:string:utf16:006e006f\nafter\n'
        self.assertEqual(run.outcomes(raw, {**self.entry, 'globals': []}, self.case), [True])
        entry = graphs.entry();payload = graphs.capture()
        self.assertEqual(run.outcomes(json.dumps(payload).encode(), entry, self.case), [False])
        entry['sequence_configuration'] = [{'action': 'call'}, {'action': 'call'}]
        steps = [{key: copy.deepcopy(value) for key, value in payload.items() if key != 'java_receiver_schema_version'}
                 for _ in range(2)]
        for index, step in enumerate(steps):step.update(id='step-' + str(index), action='call')
        payload.update(java_receiver_schema_version=2, steps=steps)
        case = {**self.case, 'sequence': [{'action': 'call'}] * 2}
        self.assertEqual(run.outcomes(json.dumps(payload).encode(), entry, case), [False, False])
        with self.assertRaises(ValueError):run.outcomes(json.dumps(payload).encode(), entry, self.case)
        with self.assertRaises(ValueError):run.outcomes(raw, self.entry, case)
        with self.assertRaises(ValueError):run.outcomes(b'broken', self.entry, self.case)

    def test_execution_options_add_actions_after_the_existing_metric_controller(self):
        environment = {}
        options = generation.execution_options(self.entry, self.case, 'baseline', self.folder, self.runtime,
                                               [], environment)
        self.addCleanup(options['interaction'].action.harness.close)
        self.assertTrue(options['record_process'])
        self.assertIsInstance(options['interaction'], run.Session)
        self.assertEqual(environment['OTELEQ_ACTION_IDS'].split(','), java_actions.action_ids(self.case))
        options['interaction'].close()

    def test_raw_receiver_is_stopped_before_retention_and_primary_errors_are_preserved(self):
        events, records = [], ('endpoint', [('route', b'body')], [])
        @contextmanager
        def receiver(**options):
            events.append('start')
            try:
                yield records
            finally:
                events.append('stop')
        def retain(*arguments):
            self.assertEqual(arguments, (self.folder, records[1], records[2]))
            events.append('retained')
        with patch('generation.capture.receiver', receiver), patch('generation.capture.retain_http', retain):
            with generation.retained_receiver(self.folder, {}) as actual:
                self.assertIs(actual, records)
            self.assertEqual(events, ['start', 'stop', 'retained'])
            events.clear()
            failure = KeyboardInterrupt('stopped')
            with self.assertRaises(KeyboardInterrupt) as caught:
                with generation.retained_receiver(self.folder, {}):
                    raise failure
            self.assertIs(caught.exception, failure)
            self.assertEqual(events, ['start', 'stop', 'retained'])
            with patch('generation.capture.retain_http', side_effect=OSError('disk full')):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    with generation.retained_receiver(self.folder, {}):
                        raise failure
                self.assertIs(caught.exception, failure)
                self.assertIn('disk full', failure.__notes__[0])


if __name__ == '__main__':
    unittest.main()
