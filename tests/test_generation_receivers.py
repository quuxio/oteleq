"""Declared receiver construction and passive instance boundary observation."""
import argparse
from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapters/generation'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
import discovery
import generation as gen
import harness
import observe
import policy
import shrinking
import typed_capture

SOURCE = '''class Counter:
 def __init__(self,start:int):
  self.value=start
  self.alias=self
 def add(self,amount:int)->int:
  self.value+=amount
  return self.value
def make_counter(start:int)->Counter:
 return Counter(start)
'''


class ReceiverTests(unittest.TestCase):
    def candidate(self, root, source=SOURCE, declaration=None):
        path = root / 'app.py'
        path.write_text(source)
        parsed = discovery.python_inventory(source)
        parsed['entrypoints'] = []
        fixture = {'function': 'app.Counter.add', 'cases': [[7]],
                   'domains': [{'kind': 'integer', 'minimum': 0, 'maximum': 32}],
                   'receiver': {'factory': 'make_counter', 'arguments': [10]}}
        if declaration is not None:
            fixture['receiver'] = declaration
        config = policy.validate({'languages': ['python'], 'functions': {'include': ['app.Counter.add']},
                                  'fixtures': [fixture]})
        args = argparse.Namespace(configuration=config, cases=1)
        function = next(item for item in parsed['functions'] if item['name'] == 'Counter.add')
        entry = gen.inventory_entry(function, parsed, 'app.py', 'python', 'a'*64, root, args)
        return entry, parsed, config

    def worker(self, root, source=SOURCE, declaration=None):
        entry, _, _ = self.candidate(root, source, declaration)
        self.assertEqual(entry['status'], 'ready', entry['reason'])
        driver = harness.materialise(root, entry, [7])
        path = root / 'observation.json'
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'OTELEQ_OBSERVATION': str(path)}
        result = subprocess.run([sys.executable, driver], cwd=root, env=env,
                                capture_output=True, timeout=30, check=False)
        return result, path, entry

    def test_receiver_policy_is_explicit_and_never_accepts_external_lookup_or_opaque_inputs(self):
        self.assertEqual(policy.receiver({'factory': 'make'}), {'factory': 'make', 'arguments': []})
        for value in (None, [], {}, {'factory': 'pkg.make'}, {'factory': 'class'}, {'factory': 'make()'},
                      {'factory': 'make', 'unknown': 1}, {'factory': 'make', 'arguments': {}},
                      {'factory': 'make', 'arguments': [None]}, {'factory': 'make', 'arguments': [float('inf')]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy.receiver(value)
        self.assertEqual(policy.receiver({'factory': 'make', 'arguments': [True, 1, 1.5, 'x']})['arguments'], [True, 1, 1.5, 'x'])

    def test_inventory_removes_only_implicit_self_and_requires_a_valid_factory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry, parsed, _ = self.candidate(root)
            self.assertEqual(entry['parameters'], ['int'])
            self.assertEqual(entry['receiver_fixture']['arguments'], [10])
            self.assertEqual(entry['receiver_fixture']['factory'], 'make_counter')
            self.assertEqual(entry['status'], 'ready')
            method = next(row for row in parsed['functions'] if row['name'] == 'Counter.add')
            self.assertTrue(method['reason'])
            for declaration in ({'factory': 'missing'}, {'factory': 'make_counter', 'arguments': []},
                                {'factory': 'make_counter', 'arguments': [True]}):
                changed, _, _ = self.candidate(root, declaration=declaration)
                self.assertEqual(changed['status'], 'blocked')
            duplicate, _, _ = self.candidate(root, SOURCE + 'def make_counter(start:int):return Counter(start)\n')
            self.assertEqual(duplicate['status'], 'blocked')
            decorated, _, _ = self.candidate(root, SOURCE.replace('def make_counter', '@staticmethod\ndef make_counter'))
            self.assertEqual(decorated['status'], 'blocked')

    def test_async_decorated_nested_constructor_and_non_python_routes_remain_blocked(self):
        source = '''class Counter:
 def __init__(self):pass
 @staticmethod
 def static(value:int):return value
 async def async_method(self):pass
 def yielded(self):yield 1
 def variadic(self,*args):pass
 def __hidden(self):pass
def outer():
 def nested(self):pass
 return 1
'''
        parsed = discovery.python_inventory(source)
        for item in parsed['functions']:
            if item['name'] == 'outer':
                continue
            self.assertNotIn('python_receiver_class', item)
            self.assertTrue(item['reason'])
        candidate = {'language': 'go', 'reason': ''}
        gen.receiver_fixture(candidate, {'functions': []}, {'factory': 'make', 'arguments': []})
        self.assertIn('ordinary Python', candidate['reason'])

    def test_each_worker_constructs_fresh_receiver_state_and_observes_alias_cycles(self):
        for _ in range(2):
            with tempfile.TemporaryDirectory() as temporary:
                result, path, entry = self.worker(Path(temporary))
                self.assertEqual(result.returncode, 0, result.stderr)
                raw = json.loads(path.read_text())
                before = typed_capture.dynamic_graph(raw['before'], 'python')
                after = typed_capture.dynamic_graph(raw['after'], 'python')
                for graph, expected in [(before, '10'), (after, '17')]:
                    receiver = graph['roots']['receiver']
                    node = next(row for row in graph['nodes'] if row['id'] == receiver['node_id'])
                    self.assertEqual(node['fields']['property:value']['value'], expected)
                    self.assertEqual(node['fields']['property:alias'], receiver)
                self.assertEqual(raw['outcome']['value']['roots']['result'], {'type': 'int', 'value': '17'})
                self.assertIn('receiver', typed_capture.required_roots(entry))
                self.assertEqual(result.stdout, b'')

    def test_returned_receiver_identity_is_shared_with_the_observed_instance(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, path, _ = self.worker(Path(temporary), SOURCE.replace('return self.value', 'return self'))
            self.assertEqual(result.returncode, 0, result.stderr)
            roots = typed_capture.dynamic_graph(json.loads(path.read_text())['outcome']['value'], 'python')['roots']
            self.assertEqual(roots['result'], roots['receiver'])

    def test_declared_class_statics_and_instance_aliases_share_the_boundary_graph(self):
        source = SOURCE.replace('class Counter:', 'class Counter:\n total=0\n shared=[]')
        source = source.replace('self.alias=self', 'self.alias=self\n  self.shared=Counter.shared')
        source = source.replace('self.value+=amount', 'self.value+=amount\n  Counter.total+=amount')
        with tempfile.TemporaryDirectory() as temporary:
            result, path, entry = self.worker(Path(temporary), source)
            self.assertEqual(result.returncode, 0, result.stderr)
            raw = json.loads(path.read_text())
            before = typed_capture.dynamic_graph(raw['before'], 'python')
            after = typed_capture.dynamic_graph(raw['after'], 'python')
            self.assertEqual(before['roots']['static:Counter.total']['value'], '0')
            self.assertEqual(after['roots']['static:Counter.total']['value'], '7')
            node = next(row for row in after['nodes'] if row['id'] == after['roots']['receiver']['node_id'])
            self.assertEqual(node['fields']['property:shared'], after['roots']['static:Counter.shared'])
            self.assertIn('static:Counter.total', typed_capture.required_roots(entry))
        with tempfile.TemporaryDirectory() as temporary:
            entry, _, _ = self.candidate(Path(temporary), SOURCE.replace('class Counter:', 'class Counter:\n first,second=1,2'))
            self.assertEqual(entry['status'], 'blocked')
            self.assertIn('static:Counter.<destructured>', entry['reason'])
        with tempfile.TemporaryDirectory() as temporary:
            entry, _, _ = self.candidate(Path(temporary), SOURCE.replace('class Counter:', 'class Counter:\n __private=1'))
            self.assertEqual(entry['status'], 'blocked')
            self.assertIn('static:Counter.__private', entry['reason'])

    def test_receiver_binding_and_graph_capture_do_not_call_dynamic_lookup_or_repr(self):
        source = SOURCE.replace(' def add', ''' def __getattribute__(self,name):
  if name in ("add","__dict__"):raise RuntimeError("CALLBACK")
  return object.__getattribute__(self,name)
 def __repr__(self):raise RuntimeError("CALLBACK")
 def add''')
        with tempfile.TemporaryDirectory() as temporary:
            result, path, _ = self.worker(Path(temporary), source)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(path.read_text())['outcome']['kind'], 'return')

    def test_source_constructors_need_no_new_factory_in_application_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, path, entry = self.worker(Path(temporary), declaration={'factory': 'Counter', 'arguments': [10]})
            self.assertEqual(entry['receiver_fixture']['kind'], 'constructor')
            self.assertEqual(entry['receiver_fixture']['source_function'], 'Counter.__init__')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(path.read_text())['outcome']['value']['roots']['result']['value'], '17')
        implicit = 'class Counter:\n def add(self,amount:int)->int:return amount\n'
        with tempfile.TemporaryDirectory() as temporary:
            result, path, entry = self.worker(Path(temporary), implicit, {'factory': 'Counter'})
            self.assertIsNone(entry['receiver_fixture']['source_function'])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(path.read_text())['outcome']['kind'], 'return')

    def test_constructor_custom_allocation_inheritance_and_runtime_rebinding_are_refused(self):
        controls = [SOURCE.replace('class Counter:', 'class Counter:\n def __new__(cls,*args):return object.__new__(cls)'),
                    'class Base:pass\n' + SOURCE.replace('class Counter:', 'class Counter(Base):'),
                    SOURCE.replace('def make_counter', ' __init__=lambda self,start:None\ndef make_counter')]
        for source in controls:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as temporary:
                result, path, _ = self.worker(Path(temporary), source, {'factory': 'Counter', 'arguments': [10]})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(path.exists())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = SOURCE.replace(' def __init__', ' @staticmethod\n def __init__')
            candidate, _, _ = self.candidate(root, source, {'factory': 'Counter', 'arguments': [10]})
            self.assertEqual(candidate['status'], 'blocked')

    def test_rebound_factories_methods_wrong_classes_and_custom_metaclasses_refuse_capture(self):
        controls = [SOURCE + 'make_counter=lambda start:Counter(start)\n',
                    SOURCE.replace('return Counter(start)', 'return object()'),
                    SOURCE.replace('return Counter(start)', 'Counter.add=lambda self,amount:0\n return Counter(start)'),
                    'class Meta(type):pass\n' + SOURCE.replace('class Counter:', 'class Counter(metaclass=Meta):'),
                    SOURCE.replace('return Counter(start)', 'instance=Counter(start)\n Counter.__qualname__="Other"\n return instance')]
        for source in controls:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as temporary:
                result, path, _ = self.worker(Path(temporary), source)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(path.exists())

    def test_factory_failure_and_opaque_receiver_state_never_become_matching_method_results(self):
        for source in [SOURCE.replace('return Counter(start)', 'raise ValueError("construction failed")'),
                       SOURCE.replace('class Counter:', 'class Counter:\n __slots__=("value","alias","__dict__")')]:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as temporary:
                result, path, _ = self.worker(Path(temporary), source)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(path.exists())

    def test_qualified_code_identity_cannot_resolve_a_missing_or_rebound_class_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'app.py'
            path.write_text(SOURCE)
            parsed = discovery.python_inventory(SOURCE)
            method = next(row for row in parsed['functions'] if row['name'] == 'Counter.add')
            code = observe.function_code(path, 'Counter.add', method['line'])
            self.assertEqual(code.co_qualname, 'Counter.add')
            with self.assertRaises(ValueError):
                observe.function_code(path, 'Counter.add', 999)

    def test_shrink_derivation_keeps_the_reviewed_factory_and_constructor_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            entry, _, config = self.candidate(Path(temporary))
            entry['id'] = 'target'
            original = {'configuration': config, 'configuration_sha256': gen.identity(config), 'inventory': [entry]}
            case = {'arguments': [7], 'id': 'target-0', 'receiver_fixture': entry['receiver_fixture']}
            derived = shrinking.derived_data(gen, original, entry, case)
            self.assertEqual(derived['configuration']['fixtures'][0]['receiver'], config['fixtures'][0]['receiver'])
            self.assertEqual(policy.validate(derived['configuration']), derived['configuration'])
            self.assertEqual(derived['inventory'][0]['receiver_fixture']['arguments'], [10])
            derived['configuration']['fixtures'][0]['receiver']['arguments'][0] = 20
            self.assertEqual(config['fixtures'][0]['receiver']['arguments'], [10])

    def test_corpus_export_and_fixture_identity_retain_constructor_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / 'application'
            source.mkdir()
            _, _, config = self.candidate(source)
            config_path = base / 'policy.toml'
            config_path.write_text('schema_version=1\nlanguages=["python"]\n[functions]\ninclude=["app.Counter.add"]\n[[fixtures]]\nfunction="app.Counter.add"\ncases=[[7]]\nreceiver={factory="make_counter",arguments=[10]}\n')
            sdk = base / 'sdk'
            sdk.mkdir()
            cli = base / 'cli'
            cli.write_text('chosen executable')
            with patch.dict(os.environ, {'OTELEQ_EXECUTABLE': str(cli)}), \
                    patch.object(gen.capture, 'selected_tools', return_value={'python': Path(sys.executable)}), \
                    patch.object(gen.capture, 'artefacts', return_value={'pinned': 'sha'}):
                output = io.StringIO()
                with redirect_stdout(output):
                    gen.plan(argparse.Namespace(source=source, otelc_root=sdk, workspace_parent=base,
                                                config=config_path, language=None, cases=None, exclude=[]))
                workspace = Path(output.getvalue().strip())
                with redirect_stdout(io.StringIO()):
                    gen.generate(argparse.Namespace(workspace=workspace))
                    gen.export_tests(argparse.Namespace(workspace=workspace, destination=base/'exported', apply=True))
                corpus = gen.read(workspace/'tests/corpus.json')
                self.assertEqual(len(corpus), 1)
                self.assertEqual(corpus[0]['receiver_fixture']['arguments'], [10])
                self.assertEqual(gen.read(base/'exported/tests/corpus.json'), corpus)
                altered = copy.deepcopy(corpus[0])
                altered['receiver_fixture']['arguments'] = [11]
                self.assertNotEqual(gen.identity(altered), gen.identity(corpus[0]))


if __name__ == '__main__':
    unittest.main()
