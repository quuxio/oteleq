"""Generated caller intent stays explicit, typed and independent of SDK replies."""

import hashlib
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import test_generation_java_handle_callers as compiled
import generation
import harness
import java_action
import java_action_session
import java_actions as actions
import java_profiles
import java_witness
import policy


def entry():
    return {'language': 'java', 'java_backend': 'prepared', 'java_profile': java_profiles.SAFE,
            actions.FIELD: java_witness.HANDLE_PROFILE, 'package': 'example', 'path': 'Work.java',
            'name': 'Work.target', 'parameters': ['int'], 'output': 'int', 'globals': []}


class JavaGeneratedActionTests(unittest.TestCase):
    def test_private_static_access_is_bound_only_for_an_explicit_ordinary_handle_target(self):
        value = {**entry(), 'java_static': True, 'java_private': True, 'java_constructor': False,
                 'java_receiver_reason': '', 'reason': 'private method needs an access fixture'}
        actions.bind_static(value)
        self.assertEqual(value['reason'], '')
        for changes in ({'java_static': False}, {'java_static': 1}, {'java_private': False},
                        {'java_constructor': True}, {'java_receiver_reason': 'inherited storage'},
                        {'reason': 'generic or abstract method needs a fixture'}):
            candidate = {**value, 'reason': 'private method needs an access fixture', **changes}
            before = candidate['reason'];actions.bind_static(candidate)
            self.assertEqual(candidate['reason'], before)
        candidate = {**value, 'reason': 'private method needs an access fixture'}
        candidate.pop(actions.FIELD);actions.bind_static(candidate)
        self.assertEqual(candidate['reason'], 'private method needs an access fixture')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);(root / 'Work.java').write_text('class Work {}')
            function = {**value, 'reason': 'private method needs an access fixture', 'line': 1}
            config = policy.validate({'adapters': {'java': {'backend': 'prepared', 'profile': java_profiles.SAFE,
                'witness_profile': java_witness.HANDLE_PROFILE}}})
            discovered = {'globals': [], 'entrypoints': [], 'package': 'example'}
            selected = generation.inventory_entry(function, discovered, 'Work.java', 'java', 'a' * 64,
                                                 root, argparse.Namespace(configuration=config, cases=1))
            self.assertEqual(selected['status'], 'ready', selected['reason'])

    def test_selection_is_explicit_and_requires_the_matching_prepared_profile(self):
        self.assertEqual(actions.settings({}), {})
        self.assertFalse(actions.enabled({}))
        for profile in (java_profiles.SAFE, java_profiles.ARCHIVES):
            options = {'backend': 'prepared', 'profile': profile, 'witness_profile': java_witness.HANDLE_PROFILE}
            self.assertEqual(policy.adapters({'java': options})['java']['witness_profile'], java_witness.HANDLE_PROFILE)
        for changes in ({'backend': 'legacy'}, {'profile': java_profiles.STOCK}, {'profile': None},
                        {'witness_profile': True}, {'witness_profile': java_witness.PROFILE}):
            options = {'backend': 'prepared', 'profile': java_profiles.SAFE,
                       'witness_profile': java_witness.HANDLE_PROFILE, **changes}
            with self.subTest(options=options), self.assertRaises(ValueError):
                policy.adapters({'java': options})
        changed = {**entry(), 'language': 'go'}
        with self.assertRaises(ValueError):
            actions.enabled(changed)

    def test_source_declarations_and_actual_binary_names_remain_separate(self):
        value = entry()
        source, declared, route = actions.members(value)
        self.assertEqual(declared['target'], {'owner': 'example/Work', 'name': 'target', 'descriptor': '(I)I'})
        self.assertEqual(declared['wrapper']['owner'], 'example/OteleqDriver')
        self.assertEqual(route.reference_kind, 6)
        self.assertNotIn('io.quux.otelc', source)
        self.assertEqual(actions.declarations(value, 'example.Work', ['example.Work'])[0], declared)
        with self.assertRaises(ValueError):
            actions.declarations(value, 'example.Other', ['example.Other'])
        nested = {**value, 'name': 'Outer.Work.target', 'receiver_class': 'Outer.Work',
                  'receiver_fixture': {}, 'output': 'Outer.Work[][]', 'java_models': [{'name': 'Outer.Work'}]}
        declared, route = actions.declarations(nested, 'example.Outer$Work', ['example.Outer$Work'])
        self.assertEqual(declared['target']['descriptor'], '(I)[[Lexample/Outer$Work;')
        self.assertEqual(declared['wrapper']['descriptor'], '(Lexample/Outer$Work;I)[[Lexample/Outer$Work;')
        self.assertEqual(route.reference_kind, 5)
        with self.assertRaises(ValueError):
            actions.references(nested, [])
        with self.assertRaises(ValueError):
            actions.references(nested, ['example.Outer$Work', 'example.Outer.Work'])
        self.assertEqual(actions.qualified({'package': ''}, 'Work'), 'Work')
        self.assertEqual(actions.qualified({'package': 'example'}, 'example.Work'), 'example.Work')

    def test_action_ids_bind_the_case_and_cover_all_sixty_four_scopes_plus_a_barrier(self):
        case = {'id': 'a' * 64}
        first = actions.action_ids(case)
        self.assertEqual(first, actions.action_ids(case))
        self.assertEqual(len(first), 2)
        self.assertNotEqual(first, actions.action_ids({'id': 'b' * 64}))
        self.assertNotEqual(actions.action_ids({**case, 'arguments': [7]}),
                            actions.action_ids({**case, 'arguments': [8]}))
        case['sequence'] = [{'action': 'call'} for _ in range(64)]
        ids = actions.action_ids(case)
        self.assertEqual(len(ids), 65)
        self.assertEqual(len(set(ids)), 65)
        with tempfile.TemporaryDirectory(prefix='oeqa-', dir='/tmp') as temporary:
            wire = java_action.Harness(Path(temporary).resolve() / 'wire', actions.case_id(case), 'c' * 64, ids)
            wire.close()
        for invalid in (None, {}, {'id': True}, {'id': 'a' * 64, 'sequence': []},
                        {'id': 'a' * 64, 'sequence': [None]},
                        {'id': 'a' * 64, 'sequence': [{'action': 'release'}]},
                        {'id': 'a' * 64, 'sequence': [{'action': 'call'}] * 65}):
            with self.subTest(case=invalid), self.assertRaises(ValueError):
                actions.action_ids(invalid)

    @unittest.skipUnless(compiled.JAVA and compiled.JAVAC, 'selected full JDK is unavailable')
    def test_declared_reference_returns_preserve_receiver_and_array_identity(self):
        compiled.JavaHandleCallerTests.execute(self, ['int'], 'Work',
            'class Work {int calls;private Work target(int amount){calls+=amount;return this;}}',
            'Work receiver=new Work();if(oteleqEnvelope(receiver,7)!=receiver || receiver.calls!=7)throw new AssertionError("alias changed");',
            instance=True, references={'Work': 'Work'})
        compiled.JavaHandleCallerTests.execute(self, [], 'Work[][]',
            'class Work {static Work[][] values={{new Work()}};private static Work[][] target(){return values;}}',
            'if(oteleqEnvelope()!=Work.values)throw new AssertionError("array identity changed");',
            references={'Work': 'Work'})
        compiled.JavaHandleCallerTests.execute(self, [], 'String',
            'class String {} class Work {static String value=new String();private static String target(){return value;}}',
            'if(oteleqEnvelope()!=Work.value)throw new AssertionError("source type was replaced by java.lang.String");',
            references={'String': 'String'})

    @unittest.skipUnless(compiled.JAVA and compiled.JAVAC, 'selected full JDK is unavailable')
    def test_generated_static_worker_keeps_the_observation_and_private_control_separate(self):
        with tempfile.TemporaryDirectory(prefix='oeqga-', dir='/tmp') as temporary:
            root = Path(temporary).resolve()
            project = root / 'project';project.mkdir()
            original = 'package example;class Work {static int calls;private static int target(int x){calls++;return x+1;}}'
            (project / 'Work.java').write_text(original)
            selected = {**entry(), 'globals': [{'name': 'Work.calls'}]}
            driver = harness.materialise(project, selected, [7])
            classes = root / 'classes';classes.mkdir()
            subprocess.run([compiled.JAVAC, '-d', str(classes), str(project / 'Work.java'),
                            str(driver), str(driver.with_name('OteleqRendezvous.java'))],
                           capture_output=True, check=True, timeout=20)
            case = {'id': 'source-case', 'source_sha256': hashlib.sha256(original.encode()).hexdigest(), 'arguments': [7]}
            ids = actions.action_ids(case)
            wire = java_action.Harness(root / 'wire', actions.case_id(case), 'b' * 64, ids)
            try:
                session = java_action_session.Session(wire, None, {}, plain=True)
                observation = root / 'observation'
                result = generation.execute([compiled.JAVA, '-cp', str(classes), 'example.OteleqDriver'], project,
                    {**os.environ, **session.environment(), 'OTELEQ_OBSERVATION': str(observation)},
                    root / 'process', timeout=15, record_process=True, interaction=session)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, b'');self.assertEqual(result.stderr, b'')
                self.assertEqual(observation.read_text(), 'before\nWork.calls:java.lang.Integer:MA==\nreturn:java.lang.Integer:OA==\nafter\nWork.calls:java.lang.Integer:MQ==\n')
                self.assertEqual((project / 'Work.java').read_text(), original)
                self.assertIsNotNone(session.terminal)
            finally:
                wire.close()

    @unittest.skipUnless(compiled.JAVA and compiled.JAVAC, 'selected full JDK is unavailable')
    def test_generated_receiver_sequence_keeps_private_factory_state_and_return_aliases(self):
        source = '''class Counter {
private int value;private static int total;Counter self=this;
private Counter(int start){value=start;}
private static Counter make(int start){return new Counter(start);}
private Counter run(int amount){value+=amount;total+=amount;return this;}
}'''
        with tempfile.TemporaryDirectory(prefix='oeqgr-', dir='/tmp') as temporary:
            root = Path(temporary).resolve()
            (root / 'Counter.java').write_text(source)
            parsed = subprocess.run([compiled.JAVA, compiled.REPO / 'adapters/generation/Discover.java', root / 'Counter.java'],
                                    cwd=root, capture_output=True, check=True, timeout=30)
            discovered = json.loads(parsed.stdout);discovered['entrypoints'] = []
            options = {'backend': 'prepared', 'profile': java_profiles.SAFE, 'witness_profile': java_witness.HANDLE_PROFILE}
            config = policy.validate({'languages': ['java'], 'adapters': {'java': options},
                'functions': {'include': ['Counter.run(int)']},
                'fixtures': [{'function': 'Counter.run(int)', 'cases': [[7]],
                    'receiver': {'factory': 'make', 'arguments': [10]},
                    'sequence': [{'action': 'call', 'arguments': 'case' if amount == 7 else [amount]}
                                 for amount in (7, 2, 1)]}]})
            function = next(item for item in discovered['functions'] if item['name'] == 'Counter.run')
            selected = generation.inventory_entry(function, discovered, 'Counter.java', 'java', 'a' * 64,
                root, argparse.Namespace(configuration=config, cases=1))
            self.assertEqual(selected['status'], 'ready', selected['reason'])
            case = generation.generation_case(selected, 0, [7])
            driver = harness.materialise(root, selected, [7])
            built = subprocess.run([compiled.JAVAC, 'Counter.java', str(driver), str(driver.with_name('OteleqRendezvous.java'))],
                                   cwd=root, capture_output=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stderr)
            wire = java_action.Harness(root / 'wire', actions.case_id(case), 'b' * 64, actions.action_ids(case))
            try:
                session = java_action_session.Session(wire, None, {}, plain=True)
                output = root / 'observation'
                result = generation.execute([compiled.JAVA, '-cp', str(root), 'OteleqDriver'], root,
                    {**os.environ, **session.environment(), 'OTELEQ_OBSERVATION': str(output)},
                    root / 'process', timeout=15, record_process=True, interaction=session)
                self.assertEqual(result.returncode, 0, result.stderr)
                raw = json.loads(output.read_bytes())
                self.assertEqual(len(raw['steps']), 3)
                for step, before, after, total in zip(raw['steps'], (10, 17, 19), (17, 19, 20), (7, 9, 10)):
                    self.assertEqual(step['before']['nodes'][0]['fields']['value']['value'], str(before))
                    self.assertEqual(step['after']['nodes'][0]['fields']['value']['value'], str(after))
                    self.assertEqual(step['after']['roots']['static:Counter.total']['value'], str(total))
                    self.assertEqual(step['outcome']['value']['roots']['result'], step['outcome']['value']['roots']['receiver'])
                self.assertEqual((root / 'Counter.java').read_text(), source)
                self.assertEqual(len(wire.records), 4)
            finally:
                wire.close()

    @unittest.skipUnless(compiled.JAVA and compiled.JAVAC, 'selected full JDK is unavailable')
    def test_unsupported_target_error_cannot_run_its_formatter_or_complete_the_case(self):
        source = '''package example;class Work {
static class Bad extends Error {public String toString(){System.out.print("APP_CALLBACK");return "BAD_FORMATTED";}}
private static int target(int amount){throw new Bad();}
}'''
        with tempfile.TemporaryDirectory(prefix='oeqge-', dir='/tmp') as temporary:
            root = Path(temporary).resolve();(root / 'Work.java').write_text(source)
            driver = harness.materialise(root, entry(), [7]);classes = root / 'classes';classes.mkdir()
            built = subprocess.run([compiled.JAVAC, '-d', str(classes), str(root / 'Work.java'), str(driver),
                                   str(driver.with_name('OteleqRendezvous.java'))], capture_output=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stderr)
            case = {'id': 'unsupported-error', 'arguments': [7]}
            wire = java_action.Harness(root / 'wire', actions.case_id(case), 'b' * 64, actions.action_ids(case))
            try:
                session = java_action_session.Session(wire, None, {}, plain=True)
                with self.assertRaisesRegex(ValueError, 'before completing its harness actions'):
                    generation.execute([compiled.JAVA, '-cp', str(classes), 'example.OteleqDriver'], root,
                        {**os.environ, **session.environment(), 'OTELEQ_OBSERVATION': str(root / 'observation')},
                        root / 'process', timeout=15, record_process=True, interaction=session)
                self.assertEqual((root / 'process/stdout').read_bytes(), b'')
                stderr = (root / 'process/stderr').read_bytes()
                self.assertIn(b'target throwable requires another codec', stderr)
                self.assertNotIn(b'BAD_FORMATTED', stderr)
                self.assertFalse((root / 'observation').exists())
                self.assertIsNone(session.terminal)
            finally:
                wire.close()


if __name__ == '__main__':
    unittest.main()
