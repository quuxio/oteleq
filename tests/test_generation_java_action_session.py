"""Serial host control must bind each actual readiness before releasing a call."""

import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_generation_java_handle_witness as handles
import test_generation_java_handle_callers as compiled
import test_generation_java_witness as direct
import java_action_session as subject
import java_witness as witness


class Harness:
    """In-memory control boundary; real JDK transport has separate regression tests."""

    def __init__(self):
        self.case_id, self.attempt_id = 'e' * 64, 'f' * 64
        self.actions, self.position, self.released = ('1' * 64, '2' * 64, '3' * 64), 0, []
        self.available = True

    def environment(self):
        return {'harness': 'independent'}

    def poll(self, process, deadline):
        if not self.available or self.position == len(self.actions):
            return None
        return {'case_id': self.case_id, 'attempt_id': self.attempt_id, 'pid': process.pid,
                'action_id': self.actions[self.position], 'thread_id': '41'}

    def release(self, deadline):
        self.released.append(self.position)
        self.position += 1

    def finish(self, process):
        witness.require(self.position == len(self.actions), 'unfinished private harness')


class Producer:
    """Closed protocol records, independent of the session's expected hashes."""

    def __init__(self, profile):
        self.profile, self.position, self.scope, self.waits = profile, 0, None, []
        self.edits = {}

    def request(self, path, operation, *args, deadline, profile):
        witness.command(operation, args, 'a' * 32, profile=profile)
        value = handles.reply(current=False) if profile == witness.HANDLE_PROFILE else direct.reply(current=False)
        if operation == 'status':
            self.scope = direct.scope(False)
            self.scope.update(cookie=format(self.position + 1, '032x'), sequence=str(self.position + 1))
            if profile == witness.HANDLE_PROFILE:
                self.scope['route_verified'] = False
        elif operation == 'arm':
            self.scope.update(phase='armed', scope_id=format(self.position + 16, '032x'),
                              case_id=args[3], attempt_id=args[4])
        elif operation == 'end':
            if self.waits:
                value['error'] = self.waits.pop(0)
            else:
                self.scope = {**direct.scope(), **{key: self.scope[key] for key in
                              ('cookie', 'sequence', 'thread_id', 'scope_id', 'case_id', 'attempt_id')}}
                if profile == witness.HANDLE_PROFILE:
                    self.scope['route_verified'] = True
                self.position += 1
        value['scope'] = copy.deepcopy(self.scope)
        for key, item in self.edits.get(operation, {}).items():
            if key.startswith('scope.'):
                value['scope'][key[6:]] = item
            else:
                value[key] = item
        return witness.reply(value, 'a' * 32, profile=profile)


class JavaActionSessionTests(unittest.TestCase):
    def make(self, *, plain=False, profile=witness.HANDLE_PROFILE):
        harness = Harness()
        header = handles.reply() if profile == witness.HANDLE_PROFILE else direct.reply()
        expected = {} if plain else {key: header[key] for key in witness.hash_fields(profile)}
        session = subject.Session(harness, Path('/owned/runtime'), expected, plain=plain, profile=profile)
        return session, Producer(profile), SimpleNamespace(pid=123)

    def complete(self, session, process):
        for _ in range(3):
            session.poll(process, 100.)
        session.finish(process)

    def test_both_explicit_protocols_bind_before_release_and_keep_outcomes_separate(self):
        for profile in (witness.PROFILE, witness.HANDLE_PROFILE):
            session, producer, process = self.make(profile=profile)
            with patch.object(witness, 'request', side_effect=producer.request):
                self.complete(session, process)
            self.assertEqual(session.harness.released, [0, 1, 2])
            self.assertEqual([row['operation'] for row in session.controls], ['status', 'arm', 'end', 'status', 'arm', 'end'])
            actions = session.receipt_actions([False, True])
            self.assertEqual([item.action_id for item in actions], list(session.actions[:-1]))
            self.assertEqual([item.failed for item in actions], [False, True])
            self.assertEqual(session.environment(), {'harness': 'independent'})
            self.assertTrue(all(item.thread_id == '41' for item in actions))
            self.assertNotEqual(actions[0].scope_id, actions[1].scope_id)

    def test_baseline_uses_the_same_harness_without_sdk_queries_or_claims(self):
        session, producer, process = self.make(plain=True)
        with patch.object(witness, 'request') as request:
            self.complete(session, process)
        request.assert_not_called()
        self.assertIsNone(session.identity)
        self.assertEqual(session.completed, [])
        with self.assertRaises(ValueError):
            session.receipt_actions([False, False])

    def test_pending_root_or_export_cannot_release_the_next_action(self):
        session, producer, process = self.make()
        producer.waits = ['root_active', 'incomplete']
        with patch.object(witness, 'request', side_effect=producer.request):
            session.poll(process, 100.)
            for _ in range(2):
                session.poll(process, 100.)
                self.assertEqual(session.harness.position, 1)
            session.poll(process, 100.)
            session.poll(process, 100.)
            session.finish(process)
        self.assertEqual(len(session.completed), 2)

    def test_foreign_context_or_altered_arm_never_releases_the_call(self):
        changes = [('status', 'pid', 124), ('status', 'route_binding_sha256', '0' * 64),
                   ('status', 'scope.thread_id', '42'), ('status', 'scope.phase', 'entered'),
                   ('status', 'scope.route_verified', True), ('status', 'scope', None),
                   ('arm', 'scope.case_id', '0' * 64), ('arm', 'scope.phase', 'ready'),
                   ('arm', 'scope.route_verified', True), ('arm', 'error', 'arm_identity_mismatch')]
        for operation, key, replacement in changes:
            session, producer, process = self.make()
            producer.edits = {operation: {key: replacement}}
            with self.subTest(operation=operation, field=key), patch.object(witness, 'request', side_effect=producer.request):
                with self.assertRaises(ValueError):
                    session.poll(process, 100.)
                self.assertEqual(session.harness.position, 0)

    def test_failed_or_foreign_end_cannot_advance_the_next_action(self):
        for key, value in (('error', 'scope_mismatch'), ('scope.thread_id', '42'),
                           ('scope.scope_id', '0' * 32), ('scope.case_id', '0' * 64)):
            session, producer, process = self.make()
            with self.subTest(field=key), patch.object(witness, 'request', side_effect=producer.request):
                session.poll(process, 100.)
                producer.edits = {'end': {key: value}}
                with self.assertRaises(ValueError):
                    session.poll(process, 100.)
                self.assertEqual(session.harness.position, 1)

    def test_transient_end_still_requires_the_exact_pending_context(self):
        edits = (('scope', None), ('scope.thread_id', '42'), ('scope.cookie', '0' * 32),
                 ('scope.sequence', '2'), ('scope.scope_id', '0' * 32),
                 ('scope.case_id', '0' * 64), ('scope.attempt_id', '0' * 64))
        for profile in (witness.PROFILE, witness.HANDLE_PROFILE):
            for error in ('root_active', 'incomplete'):
                for key, value in edits:
                    session, producer, process = self.make(profile=profile)
                    producer.waits = [error]
                    with self.subTest(profile=profile, error=error, field=key), \
                            patch.object(witness, 'request', side_effect=producer.request):
                        session.poll(process, 100.)
                        producer.edits = {'end': {key: value}}
                        with self.assertRaises(ValueError):
                            session.poll(process, 100.)
                        self.assertEqual(session.harness.position, 1)
                        self.assertEqual(session.completed, [])

    def test_transient_end_cannot_also_claim_a_completed_action(self):
        for error in ('root_active', 'incomplete'):
            session, producer, process = self.make()
            with self.subTest(error=error), patch.object(witness, 'request', side_effect=producer.request):
                session.poll(process, 100.)
                producer.edits = {'end': {'error': error}}
                with self.assertRaisesRegex(ValueError, 'retry contradicted'):
                    session.poll(process, 100.)
                self.assertEqual(session.harness.position, 1)
                self.assertEqual(session.completed, [])

    def test_plan_changes_missing_readiness_and_early_exit_remain_incomplete(self):
        session, producer, process = self.make()
        session.harness.available = False
        with patch.object(witness, 'request') as request:
            session.poll(process, 100.)
        request.assert_not_called()
        with self.assertRaises(ValueError):
            session.finish(process)
        session.harness.actions = tuple(reversed(session.harness.actions))
        with self.assertRaises(ValueError):
            session.poll(process, 100.)

    def test_missing_or_mistyped_outcomes_cannot_become_receipt_expectations(self):
        session, producer, process = self.make()
        with patch.object(witness, 'request', side_effect=producer.request):
            self.complete(session, process)
        for invalid in (None, [], [False], [0, True], (False, True)):
            with self.subTest(outcomes=invalid), self.assertRaises(ValueError):
                session.receipt_actions(invalid)

    def test_control_reply_budgets_refuse_before_releasing_an_unarmed_call(self):
        for name, value in (('MAX_REPLIES', 1), ('MAX_REPLY_BYTES', 1)):
            session, producer, process = self.make()
            with self.subTest(budget=name), patch.object(subject, name, value), \
                    patch.object(witness, 'request', side_effect=producer.request):
                with self.assertRaisesRegex(ValueError, 'reply (count|bytes) exceeded'):
                    session.poll(process, 100.)
                self.assertEqual(session.harness.position, 0)
                self.assertEqual(session.completed, [])

    def test_invalid_profile_and_independent_input_shapes_refuse_before_control_io(self):
        harness = Harness()
        for options in ({'plain': None}, {'plain': False}, {'plain': False, 'profile': 'future'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                subject.Session(harness, None, {}, **options)
        harness.actions = ('1' * 64,)
        with self.assertRaises(ValueError):
            subject.Session(harness, None, {}, plain=True)

    @unittest.skipUnless(compiled.JAVA and compiled.JAVAC, 'selected full JDK is unavailable')
    def test_actual_plain_jvm_runs_the_typed_call_and_final_private_barrier(self):
        sessions = []
        def session(harness):
            result = subject.Session(harness, None, {}, plain=True)
            sessions.append(result)
            return result
        with patch.object(compiled, 'Release', side_effect=session):
            compiled.JavaHandleCallerTests.execute(self, ['int'], 'int',
                'class Work {static int calls;private static int target(int value){calls++;return value+1;}}',
                '''int value=oteleqEnvelope(7);
if(value!=8 || Work.calls!=1)throw new AssertionError("wrong application result");
OteleqRendezvous.awaitRelease(System.getenv("OTELEQ_ACTION_IDS").split(",")[1]);''', actions=2)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].terminal['action_id'], sessions[0].actions[-1])
        self.assertEqual(sessions[0].controls, [])


if __name__ == '__main__':
    unittest.main()
