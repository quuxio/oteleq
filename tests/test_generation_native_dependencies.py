"""Actual JSON dependency scans preserve filenames and bind the selected compiler."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'adapters/generation'),
                str(Path(__file__).resolve().parents[1] / 'examples')]
import native_dependencies


class NativeDependencyTests(unittest.TestCase):
    def test_actual_clang_escaping_and_complete_header_hashes(self):
        with tempfile.TemporaryDirectory(prefix='native deps ') as temporary:
            base = Path(temporary).resolve()
            project = base / 'application'
            project.mkdir()
            names = ['a space.h', 'hash#.h', 'cash$.h', 'colon:.h', 'slash\\name.h']
            for index, name in enumerate(names):
                (project / name).write_text('#define VALUE_' + str(index) + ' 1\n')
            source = project / 'app.c'
            source.write_text(''.join('#include "' + name + '"\n' for name in names) + 'int selected(void){return 7;}\n')
            compiler = Path(os.environ.get('OTELC_CLANG') or shutil.which('clang'))
            scanner = compiler.resolve().with_name('clang-scan-deps')
            def execute(command, directory):
                return subprocess.run(command, cwd=directory, capture_output=True, check=False, timeout=30)
            result = native_dependencies.inspect({'source': 'app.c', 'directory': '.', 'flags': ['-std=c11']},
                                                 project, compiler, scanner, base / 'evidence', execute)
            self.assertEqual({item['source_relative'] for item in result.values()}, {'app.c', *names})
            for item in result.values():
                self.assertEqual(item['sha256'], hashlib.sha256(Path(item['resolved']).read_bytes()).hexdigest())
            self.assertEqual(sorted(path.name for path in project.iterdir()), sorted([*names, 'app.c']))
            self.assertTrue((base / 'evidence/dependencies.json').is_file())
            self.assertFalse((base / 'evidence/unused.o').exists())

    def document(self):
        return {'modules': [], 'translation-units': [{'commands': [{'clang-context-hash': 'context',
            'clang-module-deps': [], 'command-line': ['-cc1', 'app.c'], 'file-deps': ['/source/app.c'],
            'input-file': '/source/app.c', 'executable': '/tools/clang'}]}]}

    def test_unknown_modules_variants_inputs_compilers_and_invalid_arguments_refuse(self):
        for alteration in ('module', 'units', 'commands', 'input', 'compiler', 'unknown',
                           'empty-arguments', 'nul-argument', 'oversized-argument', 'oversized-context'):
            value = self.document()
            command = value['translation-units'][0]['commands'][0]
            if alteration == 'module':value['modules'] = [{}]
            elif alteration == 'units':value['translation-units'] *= 2
            elif alteration == 'commands':value['translation-units'][0]['commands'] *= 2
            elif alteration == 'input':command['input-file'] = '/other.c'
            elif alteration == 'compiler':command['executable'] = '/other/compiler'
            elif alteration == 'empty-arguments':command['command-line'] = []
            elif alteration == 'nul-argument':command['command-line'] = ['-cc1', 'bad\0argument']
            elif alteration == 'oversized-argument':command['command-line'] = ['x' * 8193]
            elif alteration == 'oversized-context':command['clang-context-hash'] = 'x' * 257
            else:command['ignored'] = True
            raw = json.dumps(value).encode()
            with self.subTest(alteration=alteration), self.assertRaises(ValueError):
                native_dependencies.dependency_paths(raw, Path('/source/app.c'), Path('/tools/clang'))
        raw = json.dumps(self.document()).encode()
        self.assertEqual(native_dependencies.dependency_paths(raw, Path('/source/app.c'), Path('/tools/clang')), ['/source/app.c'])

    def test_repeated_legitimate_includes_keep_one_file_identity(self):
        data = self.document()
        data['translation-units'][0]['commands'][0]['file-deps'] = ['/source/app.c', '/source/macros.def', '/source/macros.def']
        self.assertEqual(native_dependencies.dependency_paths(json.dumps(data).encode(), Path('/source/app.c'),
                         Path('/tools/clang')), ['/source/app.c', '/source/macros.def'])


if __name__ == '__main__':
    unittest.main()
