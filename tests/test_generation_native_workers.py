"""Compile real private target workers, including sibling state and source macros."""
import copy
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
import native_context
import native_project
import native_workers
import typed_capture


def execute(command, directory, **kwargs):
    return subprocess.run(command, cwd=directory, capture_output=True, check=False,
                          timeout=120, input=kwargs.get('input_data'))


class NativeWorkersTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='native target workers ')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'original'
        for name in ('src', 'include', 'build'):
            (self.root / name).mkdir(parents=True)

    def prepare(self, language, *, throws=False, presence_probe=False, probe_exists=False):
        cpp = language == 'cpp'
        compiler = Path(os.environ.get('OTELC_CLANGXX' if cpp else 'OTELC_CLANG')
                        or shutil.which('clang++' if cpp else 'clang'))
        extension = '.cpp' if cpp else '.c'
        sources = ['src/one' + extension, 'src/two' + extension]
        (self.root / 'include/state.h').write_text('extern int total;int sibling(int);\n')
        function = ('int selected(short amount){local+=amount;int value=sibling(amount);' +
                    ('throw std::invalid_argument("failure");' if throws else '') + 'return value+local;}\n')
        if cpp:
            function = ('namespace work{static int local=3;' + function +
                        'int selected(int amount){return -999;}}\n')
        else:
            function = 'static int local=3;' + function
        probe = ('#if __has_include("optional.h")\nint optional_present=1;\n#else\nint optional_present=0;\n#endif\n'
                 if presence_probe else '')
        if probe_exists:
            (self.root / 'include/optional.h').write_text('/* existence-only compiler input */\n')
        (self.root / sources[0]).write_text('#include "state.h"\n' + probe +
            ('#include <stdexcept>\n' if throws else '') +
            function + 'int main(void){}\n' +
            '#define int broken_type\n#define __builtin_memcpy_inline(a,b,c) broken_copy\n')
        (self.root / sources[1]).write_text('#include "state.h"\nint total=7;static int local=4;\n'
            'int sibling(int amount){local+=amount;total+=amount;return total;}\n'
            'int copies=0;void* memcpy(void* out,const void* in,unsigned long size){copies++;'
            'for(unsigned long i=0;i<size;i++)((char*)out)[i]=((const char*)in)[i];return out;}\n')
        records = [{'directory': str(self.root / 'build'), 'file': '../' + name,
                    'arguments': [str(compiler), '-I', '../include', '-std=c++17' if cpp else '-std=c11',
                                  '-O0', '-c', '../' + name, '-o', str(index) + '.o']}
                   for index, name in enumerate(sources)]
        (self.root / 'build/compile_commands.json').write_text(json.dumps(records))
        options = native_project.settings({'compilation_database': 'build/compile_commands.json',
            'targets': [{'name': 'application', 'units': [{'source': name} for name in sources]}]})
        evidence = self.base / 'evidence'
        prepared = native_project.prepare(self.root, options, language, compiler, evidence, execute)
        inventory = native_context.target_inventory(prepared, evidence,
            compiler.resolve().with_name('llvm-cxxfilt') if cpp else None, execute)
        chosen = next(item for item in inventory if item['function']['name'] ==
                      ('work::selected' if cpp else 'selected') and item['function']['parameters'] == ['short'])
        entry = {**chosen['function'], 'language': language, 'globals': chosen['globals'],
                 'unit': chosen['unit'], 'target': chosen['target']}
        self.project = self.base / 'private'
        shutil.copytree(self.root, self.project)
        return prepared, entry, inventory

    def build_run(self, prepared, entry, arguments, directory):
        before = {str(path.relative_to(self.project)): native_project.digest(path)
                  for path in self.project.rglob('*') if path.is_file()}
        recipe = native_workers.materialise(self.project, prepared, entry, arguments, directory)
        for step in recipe['steps']:
            result = execute(step['command'], step['directory'])
            self.assertEqual(result.returncode, 0, step['kind'] + ': ' + result.stderr.decode(errors='replace'))
        observation = directory / 'observation'
        result = subprocess.run([recipe['binary']], cwd=self.project, capture_output=True, check=False,
                                timeout=20, env={**os.environ, 'OTELEQ_OBSERVATION': str(observation)})
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertEqual(result.stdout, b'')
        self.assertEqual(result.stderr, b'')
        self.assertEqual(before, {str(path.relative_to(self.project)): native_project.digest(path)
                                 for path in self.project.rglob('*') if path.is_file()})
        for path, expected in prepared['local_inputs'].items():
            self.assertEqual(native_project.digest(self.root / path), expected)
        self.assertEqual(len(recipe['steps']), 6)
        return typed_capture.scalar_capture(observation.read_bytes(), entry), recipe

    def assert_roots(self, graph, own, sibling, total):
        values = graph['roots']
        self.assertEqual(values['global:total']['value'], str(total))
        self.assertEqual(values['global:copies']['value'], '0')
        internal = [int(item['value']) for name, item in values.items() if name.startswith('global:unit:')]
        self.assertEqual(sorted(internal), sorted([own, sibling]))

    def test_c_real_target_captures_all_state_without_calling_application_memcpy(self):
        prepared, entry, inventory = self.prepare('c')
        (before, outcome, after), recipe = self.build_run(prepared, entry, [5], self.base / 'worker')
        self.assert_roots(before, 3, 4, 7)
        self.assert_roots(after, 8, 9, 12)
        self.assertEqual(outcome['graph']['roots']['result']['value'], '20')
        for step in recipe['steps']:
            if step['kind'] == 'compile':
                self.assertEqual(step['command'][1:6], ['-I', '../include', '-std=c11', '-O0', '-ivfsoverlay'])
        main = next(item for item in inventory if item['function']['name'] == 'main')
        main_entry = {**main['function'], 'language': 'c', 'globals': main['globals'],
                      'unit': main['unit'], 'target': main['target']}
        (_, result, _), _ = self.build_run(prepared, main_entry, [], self.base / 'main-worker')
        self.assertEqual(result['graph']['roots']['result']['value'], '0')

    def test_cpp_real_target_binds_exact_overload_and_preserves_internal_roots(self):
        prepared, entry, _ = self.prepare('cpp')
        self.assertEqual(entry['cpp_function']['source_file'], 'src/one.cpp')
        (before, outcome, after), _ = self.build_run(prepared, entry, [5], self.base / 'worker')
        self.assert_roots(before, 3, 4, 7)
        self.assert_roots(after, 8, 9, 12)
        self.assertEqual(outcome['graph']['roots']['result']['value'], '20')

    def test_cpp_exception_keeps_the_complete_after_state(self):
        prepared, entry, _ = self.prepare('cpp', throws=True)
        (before, outcome, after), _ = self.build_run(prepared, entry, [5], self.base / 'worker')
        self.assert_roots(before, 3, 4, 7)
        self.assert_roots(after, 8, 9, 12)
        self.assertEqual(outcome['kind'], 'error')
        self.assertEqual(outcome['graph']['nodes'][0]['type'], 'cpp.std::invalid_argument')
        self.assertEqual(outcome['graph']['nodes'][0]['fields']['message']['hex'], b'failure'.hex())

    def test_missing_state_and_changed_private_inputs_refuse_before_output(self):
        prepared, entry, _ = self.prepare('c')
        directory = self.base / 'refused'
        changed = copy.deepcopy(entry)
        with self.assertRaisesRegex(ValueError, 'call requires a fixture'):
            native_workers.materialise(self.project, prepared, {**entry, 'reason': 'macro callable'}, [5], directory)
        self.assertFalse(directory.exists())
        for alteration in ({'inaccessible': True}, {'private': True}, {'type': 'volatile int'},
                           {'type': 'int*'}, {'unit': 'foreign'}):
            changed['globals'][0] = {**entry['globals'][0], **alteration}
            with self.assertRaises(ValueError):
                native_workers.materialise(self.project, prepared, changed, [5], directory)
            self.assertFalse(directory.exists())
        with self.assertRaisesRegex(ValueError, 'separate private source copy'):
            native_workers.materialise(self.root, prepared, entry, [5], directory)
        (self.project / 'include/state.h').write_text('int altered;\n')
        with self.assertRaisesRegex(ValueError, 'private build input changed'):
            native_workers.materialise(self.project, prepared, entry, [5], directory)
        self.assertFalse(directory.exists())

    def test_header_free_helpers_support_const_bool_void_and_logical_source_names(self):
        for language in ('c', 'cpp'):
            with self.subTest(language=language):
                cpp = language == 'cpp'
                compiler = Path(os.environ.get('OTELC_CLANGXX' if cpp else 'OTELC_CLANG')
                                or shutil.which('clang++' if cpp else 'clang'))
                root = self.base / language
                root.mkdir()
                source = root / ('app.cpp' if cpp else 'app.c')
                boolean = 'bool' if cpp else '_Bool'
                source.write_text('const int initial=7;int state=1;\n'
                    'void selected(' + boolean + ' value){state+=value;\n'
                    'if(__builtin_strcmp(__FILE__,__BASE_FILE__)!=0)state=-999;}\n')
                key = 'unit'
                unit = {'source': source.name, 'directory': '.',
                        'flags': ['-std=c++17' if cpp else '-std=c11', '-O0']}
                prepared = {'language': language, 'source_root': str(root), 'units': {key: unit},
                            'compiler': {'path': str(compiler)},
                            'local_inputs': {source.name: native_project.digest(source)},
                            'targets': [{'name': 'plain', 'units': [key], 'link_flags': []}]}
                entry = {'language': language, 'name': 'selected', 'parameters': [boolean],
                         'output': 'void', 'target': 'plain', 'unit': key, 'globals': [
                             {'name': name, 'expression': name, 'type': type_, 'unit': key}
                             for name, type_ in (('initial', 'const int'), ('state', 'int'))]}
                self.project = self.base / (language + '-private')
                shutil.copytree(root, self.project)
                recipe = native_workers.materialise(self.project, prepared, entry, [True], self.base / (language + '-worker'))
                for step in recipe['steps']:
                    result = execute(step['command'], step['directory'])
                    self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                observation = self.base / (language + '-observation')
                result = subprocess.run([recipe['binary']], capture_output=True, check=False, timeout=20,
                    env={**os.environ, 'OTELEQ_OBSERVATION': str(observation)})
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                before, outcome, after = typed_capture.scalar_capture(observation.read_bytes(), entry)
                self.assertEqual(before['roots']['global:state']['value'], '1')
                self.assertEqual(after['roots']['global:state']['value'], '2')
                self.assertEqual(after['roots']['global:initial']['value'], '7')
                self.assertEqual(outcome['graph']['roots']['result']['kind'], 'unit')
                # External VFS filenames must not replace the real source spelling.
                original = next(step for step in recipe['steps'] if step['kind'] == 'compile')
                result = execute([*original['command'][:-4], '-E', str(self.project / source.name)], self.project)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                self.assertIn(str(self.project / source.name).encode(), result.stdout)
                self.assertNotIn(str(self.base / (language + '-worker') / (key + source.suffix)).encode(), result.stdout)

    def test_instrumented_object_transform_is_delegated_to_the_sdk(self):
        prefix = ['otelc', '--config', '/retained/policy.toml', '--language', 'c']
        step = {'kind': 'rename-main', 'input': '/retained/original.o', 'output': '/retained/renamed.o',
                'command': ['llvm-objcopy', 'untrusted-placeholder']}
        self.assertEqual(native_workers.instrumented_command(step, prefix, 'c'), [*prefix, 'object',
            'rename-main', '/retained/original.o', '--output', '/retained/renamed.o',
            '--symbol', '__oteleq_original_main'])
        for kind in ('compile', 'driver', 'link'):
            step = {'kind': kind, 'command': ['clang++', '-O0', 'source.cpp', '-o', '/retained/output']}
            self.assertEqual(native_workers.instrumented_command(step, prefix, 'cpp'),
                             [*prefix, 'clang++', *step['command'][1:]])
        with self.assertRaisesRegex(ValueError, 'language'):
            native_workers.instrumented_command(step, prefix, 'rust')
        with self.assertRaisesRegex(ValueError, 'unknown build step'):
            native_workers.instrumented_command({'kind': 'unknown'}, prefix, 'c')


if __name__ == '__main__':
    unittest.main()
