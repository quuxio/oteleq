"""Real native compile commands retain flags, variants, paths and target membership."""
import copy
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'adapters/generation'),
                str(Path(__file__).resolve().parents[1] / 'examples')]
import native_project


class NativeProjectTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='native project ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / 'src').mkdir()
        (self.root / 'include').mkdir()
        (self.root / 'build').mkdir()
        (self.root / 'include/config.h').write_text('#define OFFSET 4\n')
        (self.root / 'src/app.c').write_text('#include "config.h"\nint selected(int value){return value+OFFSET+AMOUNT;}\n')
        self.compiler = Path(os.environ.get('OTELC_CLANG') or shutil.which('clang')).absolute()
        self.record = {'directory': str(self.root / 'build'), 'file': '../src/app.c',
                       'arguments': [str(self.compiler), '-I', '../include', '-DAMOUNT=3', '-O0', '-std=c11',
                                     '-MMD', '-MF', 'app.d', '-MT', 'app.o', '-c', '../src/app.c', '-o', 'app.o']}
        self.configuration = {'compilation_database': 'build/compile_commands.json',
                              'targets': [{'name': 'core', 'units': [{'source': 'src/app.c'}], 'link_flags': ['-lm']}]}
        self.write_database([self.record])

    def write_database(self, records):
        (self.root / 'build/compile_commands.json').write_text(json.dumps(records))

    def load(self, language='c', compiler=None):
        return native_project.load(self.root, native_project.settings(self.configuration), language, compiler or self.compiler)

    def test_actual_private_compile_preserves_includes_defines_mode_and_optimisation(self):
        context = self.load()[0]
        unit = context['units'][0]
        self.assertEqual(unit['flags'], ['-I', '../include', '-D', 'AMOUNT=3', '-O0', '-std=c11'])
        self.assertEqual(unit['directory'], 'build')
        self.assertEqual(unit['source'], 'src/app.c')
        self.assertEqual(unit['output'], 'build/app.o')
        self.assertEqual(context['link_flags'], ['-lm'])
        with tempfile.TemporaryDirectory(prefix='native private ') as temporary:
            project = Path(temporary).resolve()
            shutil.copytree(self.root, project, dirs_exist_ok=True)
            output = project / 'build/app.o'
            command = native_project.compile_arguments(unit, project, self.compiler, project / unit['source'], output)
            result = subprocess.run(command, cwd=project / unit['directory'], capture_output=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.is_file())
            self.assertFalse((self.root / 'build/app.o').exists())
            self.assertFalse((project / 'build/app.d').exists())
            driver = project / 'caller.c'
            driver.write_text('int selected(int);int main(void){return selected(2)==9?0:1;}\n')
            binary = project / 'application'
            linked = subprocess.run([self.compiler, driver, output, '-o', binary], capture_output=True, timeout=30, check=False)
            self.assertEqual(linked.returncode, 0, linked.stderr)
            self.assertEqual(subprocess.run([binary], capture_output=True, check=False, timeout=10).returncode, 0)

    def test_posix_command_string_and_arguments_precedence_never_execute_shell(self):
        record = copy.deepcopy(self.record)
        record['command'] = shlex.join(record.pop('arguments'))
        self.write_database([record])
        self.assertEqual(self.load()[0]['units'][0]['flags'], ['-I', '../include', '-D', 'AMOUNT=3', '-O0', '-std=c11'])
        record['arguments'] = self.record['arguments']
        record['command'] = 'touch SHOULD_NOT_EXIST'
        self.write_database([record])
        self.assertEqual(self.load()[0]['units'][0]['source'], 'src/app.c')
        self.assertFalse((self.root / 'SHOULD_NOT_EXIST').exists())

    def test_output_selector_binds_one_real_variant_and_never_chooses_first(self):
        other = copy.deepcopy(self.record)
        other['arguments'] = [item.replace('AMOUNT=3', 'AMOUNT=8').replace('app.o', 'other.o') for item in other['arguments']]
        self.write_database([self.record, other])
        with self.assertRaisesRegex(ValueError, 'unique database variant'):
            self.load()
        self.configuration['targets'][0]['units'][0]['output'] = 'build/other.o'
        selected = self.load()[0]['units'][0]
        self.assertIn('AMOUNT=8', selected['flags'])
        self.assertEqual(selected['output'], 'build/other.o')

    def test_changed_compiler_paths_extra_sources_actions_and_unsafe_flags_refuse(self):
        bad = [
            ['-fpass-plugin=plugin.so'], ['@flags.rsp'], ['-D', '@flags.rsp'], ['-Xclang', '-load'],
            ['-shared'], ['-flto'], ['-fsanitize=address'], ['-fprofile-generate'], ['-oanything'],
            ['-I', str(self.root.parent)], ['-c'], ['-o', 'second.o'], ['../src/app.c'],
        ]
        for arguments in bad:
            record = copy.deepcopy(self.record)
            record['arguments'].extend(arguments)
            self.write_database([record])
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.load()
        self.write_database([self.record])
        with self.assertRaisesRegex(ValueError, 'selected qualified compiler'):
            self.load(compiler=Path('/not/the/selected/compiler'))

    def test_long_compiler_options_cannot_be_reinterpreted_as_joined_include_paths(self):
        for name in ('-pch', '-after', '-'):
            (self.root / 'build' / name).mkdir()
        for flag in ('-include-pch', '-isystem-after', '-I-'):
            record = copy.deepcopy(self.record)
            record['arguments'].append(flag)
            self.write_database([record])
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'unsupported project compiler flag'):
                self.load()

    def test_metadata_and_target_validation_is_strict_and_inputs_remain_unchanged(self):
        original = (self.root / 'src/app.c').read_bytes()
        for update in ({'extra': True}, {'directory': 'build'}, {'file': '../missing.c'}, {'output': 'wrong.o'}):
            record = {**self.record, **update}
            self.write_database([record])
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.load()
        self.assertEqual((self.root / 'src/app.c').read_bytes(), original)
        self.write_database([])
        with self.assertRaisesRegex(ValueError, 'command count'):
            self.load()
        for configuration in ({'compilation_database': '../escape.json', 'targets': []},
                              {'targets': self.configuration['targets']},
                              {**self.configuration, 'targets': []},
                              {**self.configuration, 'targets': self.configuration['targets']*2}):
            with self.subTest(configuration=configuration), self.assertRaises(ValueError):
                native_project.settings(configuration)

    def test_mixed_database_retains_only_the_explicit_target_language_and_membership(self):
        unrelated = {'directory': str(self.root), 'file': 'other.cpp',
                     'arguments': ['unselected-other-compiler', '-c', 'other.cpp', '-o', 'other.o']}
        self.write_database([unrelated, self.record])
        self.assertEqual(self.load()[0]['units'][0]['source'], 'src/app.c')
        path = self.root / 'build/compile_commands.json'
        path.write_text('[{"directory":"first","directory":"second","file":"source.c"}]')
        with self.assertRaises(ValueError):
            self.load()

    def test_cpp_database_preserves_its_existing_language_mode(self):
        compiler = Path(os.environ.get('OTELC_CLANGXX') or shutil.which('clang++')).absolute()
        (self.root / 'src/app.cpp').write_text('int selected(int value){return value;}\n')
        self.record.update(file='../src/app.cpp', arguments=[str(compiler), '-O2', '-std=c++20', '-c', '../src/app.cpp', '-o', 'app.o'])
        self.configuration['targets'][0]['units'] = [{'source': 'src/app.cpp'}]
        self.write_database([self.record])
        self.assertEqual(self.load('cpp', compiler)[0]['units'][0]['flags'], ['-O2', '-std=c++20'])

    def test_preparation_binds_actual_headers_database_tools_and_ordered_target_units(self):
        with tempfile.TemporaryDirectory(prefix='native evidence ') as temporary:
            def execute(command, directory):
                return subprocess.run(command, cwd=directory, capture_output=True, check=False, timeout=120)
            evidence = Path(temporary)
            prepared = native_project.prepare(self.root, native_project.settings(self.configuration), 'c', self.compiler,
                                              evidence, execute)
            self.assertEqual(set(prepared['local_inputs']), {'build/compile_commands.json', 'src/app.c', 'include/config.h'})
            self.assertEqual(len(prepared['units']), 1)
            self.assertEqual(prepared['targets'][0]['units'], list(prepared['units']))
            self.assertEqual(prepared['external_inputs'], {})
            native_project.verify(prepared, evidence, execute)
            header = self.root / 'include/config.h'
            original = header.read_bytes()
            header.write_text('#define OFFSET 99\n')
            with self.assertRaisesRegex(ValueError, 'build input changed'):
                native_project.verify(prepared, evidence, execute)
            header.write_bytes(original)
            database = self.root / 'build/compile_commands.json'
            database.write_text(database.read_text() + ' ')
            with self.assertRaisesRegex(ValueError, 'build input changed'):
                native_project.verify(prepared, evidence, execute)

    def test_retargeting_a_used_header_symlink_invalidates_the_frozen_input_binding(self):
        header = self.root / 'include/config.h'
        original = header.read_bytes()
        header.unlink()
        for name in ('first.h', 'second.h'):
            (header.parent / name).write_bytes(original)
        header.symlink_to('first.h')
        with tempfile.TemporaryDirectory(prefix='native alias evidence ') as temporary:
            def execute(command, directory):
                return subprocess.run(command, cwd=directory, capture_output=True, check=False, timeout=120)
            evidence = Path(temporary)
            prepared = native_project.prepare(self.root, native_project.settings(self.configuration), 'c', self.compiler,
                evidence, execute)
            native_project.verify(prepared, evidence, execute)
            header.unlink()
            header.symlink_to('second.h')
            with self.assertRaisesRegex(ValueError, 'input path changed'):
                native_project.verify(prepared, evidence, execute)

    def test_existence_only_bytes_missing_probes_and_search_precedence_remain_bound(self):
        (self.root / 'src/app.c').write_text('#if __has_include("present.h") && !__has_include("absent.h")\n'
            'int selected(void){return 7;}\n#else\nint selected(void){return 9;}\n#endif\n')
        present = self.root / 'include/present.h'
        present.write_text('#error this file is only probed, never included\n')
        original = present.read_bytes()
        with tempfile.TemporaryDirectory(prefix='native probe evidence ') as temporary:
            def execute(command, directory):
                return subprocess.run(command, cwd=directory, capture_output=True, check=False, timeout=120)
            evidence = Path(temporary)
            prepared = native_project.prepare(self.root, native_project.settings(self.configuration), 'c',
                                              self.compiler, evidence, execute)
            self.assertIn('include/present.h', prepared['local_inputs'])
            unit = next(iter(prepared['units'].values()))
            self.assertEqual({item['name'] for item in unit['probes']}, {'present.h', 'absent.h'})
            present.write_bytes(original + b'changed\n')
            with self.assertRaisesRegex(ValueError, 'build input changed'):
                native_project.verify(prepared, evidence, execute)
            present.write_bytes(original)
            absent = self.root / 'include/absent.h'
            absent.write_text('now present\n')
            with self.assertRaisesRegex(ValueError, 'preprocessor search results changed'):
                native_project.verify(prepared, evidence, execute)
            absent.unlink()
            shadow = self.root / 'src/present.h'
            shadow.write_bytes(original)
            with self.assertRaisesRegex(ValueError, 'preprocessor search results changed'):
                native_project.verify(prepared, evidence, execute)
            shadow.unlink()
            native_project.verify(prepared, evidence, execute)
            key = next(iter(prepared['units']))
            metadata = evidence / 'units' / key / 'metadata.json'
            metadata.write_bytes(metadata.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'retained compiler metadata changed'):
                native_project.verify(prepared, evidence, execute)


if __name__ == '__main__':
    unittest.main()
