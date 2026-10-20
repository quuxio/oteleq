"""Explicit regular-package imports, source binding and passive worker regressions."""
import argparse
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
import generation
import harness
import policy
import python_project
import qualify_python_project


class PythonProjectTests(unittest.TestCase):
    def write(self, root, name, text=''):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_import_roots_are_explicit_canonical_and_source_relative(self):
        self.assertEqual(policy.load(None)['adapters']['python'], {'import_roots': []})
        configured = policy.validate({'adapters': {'python': {'import_roots': ['.', 'src']}}})
        self.assertEqual(configured['adapters']['python']['import_roots'], ['.', 'src'])
        for value in (None, {}, 'src', [1], [''], ['/tmp'], ['../src'], ['src/../lib'],
                      ['src/'], ['./src'], ['a//b'], ['src\\pkg'], ['C:src'], ['src', 'src']):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy.validate({'adapters': {'python': {'import_roots': value}}})
        for value in ([], {'unknown': []}):
            with self.assertRaises(ValueError):
                policy.validate({'adapters': {'python': value}})

    def test_regular_packages_initialisers_and_plain_modules_have_exact_import_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('src/pkg/__init__.py', 'src/pkg/inner/__init__.py',
                         'src/pkg/inner/api.py', 'src/app.py'):
                self.write(root, name)
            for path, name in [('src/pkg/inner/api.py', 'pkg.inner.api'),
                               ('src/pkg/inner/__init__.py', 'pkg.inner'), ('src/app.py', 'app')]:
                self.assertEqual(python_project.context(root, path, ['src']),
                                 {'module': name, 'roots': ['src']})

    def test_ambiguous_missing_namespace_invalid_and_shadowed_modules_are_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('src/pkg/api.py', 'src/bad-name.py', 'src/class.py', 'src/__init__.py'):
                self.write(root, name)
            for path, roots in [('elsewhere.py', ['src']), ('src/pkg/api.py', ['src']),
                                ('src/app.py', ['.', 'src']), ('src/bad-name.py', ['src']),
                                ('src/class.py', ['src']), ('src/__init__.py', ['src'])]:
                with self.subTest(path=path, roots=roots), self.assertRaises(ValueError):
                    python_project.context(root, path, roots)
            self.write(root, 'src/pkg/__init__.py')
            self.write(root, 'first/pkg/__init__.py')
            with self.assertRaisesRegex(ValueError, 'shadowed'):
                python_project.context(root, 'src/pkg/api.py', ['first', 'src'])
            self.write(root, 'first/pkg.py')
            (root / 'first/pkg/__init__.py').unlink()
            with self.assertRaisesRegex(ValueError, 'shadowed'):
                python_project.context(root, 'src/pkg/api.py', ['first', 'src'])

    def test_inventory_retains_context_and_selected_package_gaps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write(root, 'src/pkg/api.py', 'def selected(value:int)->int:return value+1\n')
            config = policy.validate({'adapters': {'python': {'import_roots': ['src']}}})
            parsed = discovery.python_inventory(path.read_text())
            parsed['entrypoints'] = []
            args = argparse.Namespace(configuration=config, cases=1)
            entry = generation.inventory_entry(parsed['functions'][0], parsed, 'src/pkg/api.py', 'python', 'a'*64, root, args)
            self.assertEqual(entry['status'], 'blocked')
            self.assertIn('namespace', entry['reason'])
            self.write(root, 'src/pkg/__init__.py')
            entry = generation.inventory_entry(parsed['functions'][0], parsed, 'src/pkg/api.py', 'python', 'a'*64, root, args)
            self.assertEqual(entry['status'], 'ready')
            self.assertEqual(entry['python_import'], {'module': 'pkg.api', 'roots': ['src']})
            config['functions']['exclude'] = ['*']
            entry = generation.inventory_entry(parsed['functions'][0], parsed, 'src/pkg/api.py', 'python', 'a'*64, root, args)
            self.assertEqual(entry['status'], 'excluded')
            self.assertNotIn('python_import', entry)

    def worker(self, root, path, roots=None):
        source = (root / path).read_text()
        parsed = discovery.python_inventory(source)
        function = next(row for row in parsed['functions'] if row['name'] == 'selected')
        entry = {**function, 'path': path, 'language': 'python', 'globals': parsed['globals']}
        if roots is not None:
            entry['python_import'] = python_project.context(root, path, roots)
        driver = harness.materialise(root, entry, [7])
        observation = root / 'observation.json'
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'OTELEQ_OBSERVATION': str(observation)}
        result = subprocess.run([sys.executable, driver], cwd=root, env=env,
                                capture_output=True, timeout=30, check=False)
        return result, observation

    def test_worker_uses_real_relative_and_absolute_package_imports_and_retains_mutation(self):
        for prefix, roots in [('', ['.']), ('src/', ['src'])]:
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.write(root, prefix+'pkg/__init__.py', 'BIAS=3\n')
                self.write(root, prefix+'pkg/helper.py', 'def twice(value):return value*2\n')
                self.write(root, prefix+'pkg/api.py', 'from .helper import twice\nfrom pkg import BIAS\nstate=0\ndef selected(value:int)->int:\n global state\n assert __package__=="pkg" and __name__=="pkg.api"\n state+=twice(value)+BIAS\n return state\n')
                result, path = self.worker(root, prefix+'pkg/api.py', roots)
                self.assertEqual(result.returncode, 0, result.stderr)
                observation = json.loads(path.read_text())
                self.assertEqual(observation['outcome']['kind'], 'return')
                self.assertEqual(observation['outcome']['value']['roots']['result'], {'type': 'int', 'value': '17'})
                self.assertNotEqual(observation['before'], observation['after'])
                self.assertFalse(list(root.rglob('__pycache__')))

    def test_legacy_standalone_loader_retains_its_synthetic_module_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, 'app.py', 'def selected(value:int)->int:\n assert __name__=="_oteleq_target"\n return value\n')
            result, path = self.worker(root, 'app.py')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(path.read_text())['outcome']['kind'], 'return')

    def test_interpreter_module_shadow_and_changed_module_origin_cannot_pass(self):
        for name, source, error in [('sys.py', 'def selected(value:int)->int:return value\n', 'resolved to a different'),
                                    ('app.py', '__file__="elsewhere.py"\ndef selected(value:int)->int:return value\n', 'has a different')]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.write(root, name, source)
                result, observation = self.worker(root, name, ['.'])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr.decode())
                self.assertFalse(observation.exists())

    def test_qualification_consumes_every_generated_case_summary(self):
        summaries = '\n'.join(json.dumps({'report': path}) for path in ('first/report.json', 'second/report.json'))
        with patch.object(qualify_python_project, 'command', return_value=summaries), \
                patch.object(qualify_python_project, 'check_report', return_value=4) as check:
            self.assertEqual(qualify_python_project.run_framework(Path('suite'), Path('evidence'), 'framework'), 8)
            self.assertEqual(check.call_count, 2)
            self.assertEqual(check.call_args_list[0].kwargs, {'expected_cases': 1})
        with patch.object(qualify_python_project, 'command', return_value='{}'):
            with self.assertRaises(AssertionError):
                qualify_python_project.run_framework(Path('suite'), Path('evidence'), 'framework')


if __name__ == '__main__':
    unittest.main()
