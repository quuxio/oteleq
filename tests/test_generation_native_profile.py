"""Public native plans retain real build inputs through generation and detached export."""
import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'adapters/generation'),
                str(Path(__file__).resolve().parents[1] / 'examples')]
import generation
import native_profile
import native_project
import policy
import typed_capture


class NativeProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='public native project ')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source, self.provider = self.base / 'application', self.base / 'provider'
        self.provider.mkdir()
        for name in ('src', 'include', 'build/generated'):
            (self.source / name).mkdir(parents=True)
        self.cli = self.base / 'cli'
        self.cli.write_text('fixed CLI identity')
        environment = patch.dict(os.environ, {'OTELEQ_EXECUTABLE': str(self.cli)})
        environment.start()
        self.addCleanup(environment.stop)

    def plan(self, language='c', *, orphan=False, volatile=False, all_generated=False):
        cpp = language == 'cpp'
        extension = '.C' if cpp else '.c'
        compiler = Path(os.environ.get('OTELC_CLANGXX' if cpp else 'OTELC_CLANG')
                        or shutil.which('clang++' if cpp else 'clang'))
        selected = {'clang++' if cpp else 'clang': compiler}
        if cpp:
            selected['cpp-demangler'] = compiler.resolve().with_name('llvm-cxxfilt')
        include = 'build/include' if all_generated else 'include'
        units = 'build/units' if all_generated else 'src'
        (self.source / include).mkdir(parents=True, exist_ok=True)
        (self.source / units).mkdir(parents=True, exist_ok=True)
        (self.source / include / 'state.h').write_text('extern int total;int sibling(int);\n' +
            ('inline' if cpp else 'static inline') + ' int header_selected(short amount){return amount;}\n')
        (self.source / 'build/generated/settings.h').write_text('#define OFFSET 4\n')
        sources = [units + '/one' + extension, units + '/two' + extension]
        (self.source / sources[0]).write_text('#include "state.h"\n#include "settings.h"\n'
            'static int local=3;int selected(int value){local+=value;return sibling(value)+local+OFFSET;}\nint main(void){}\n')
        (self.source / sources[1]).write_text('#include "state.h"\nint total=7;static int local=4;\n'
            'int sibling(int value){local+=value;total+=value;return total;}\n' +
            ('volatile int hidden=1;\n' if volatile else ''))
        if orphan:
            (self.source / ('orphan' + extension)).write_text('unknown selected build context\n')
        database = [{'directory': str(self.source / 'build'), 'file': '../' + name,
                     'arguments': [str(compiler), '-I', '../' + include, '-I', 'generated',
                                   '-std=c++17' if cpp else '-std=c11', '-O0', '-c', '../' + name,
                                   '-o', str(index) + '.o']} for index, name in enumerate(sources)]
        (self.source / 'build/compile_commands.json').write_text(json.dumps(database))
        configuration = self.base / 'equivalence.toml'
        configuration.write_text('languages=[' + json.dumps(language) + ']\n'
            '[functions]\ninclude=["selected*","header_selected*"]\n'
            '[[fixtures]]\nfunction="selected*"\nsource=' + json.dumps(sources[0]) + '\ncases=[[5]]\n'
            '[adapters.' + language + ']\ncompilation_database="build/compile_commands.json"\n'
            '[[adapters.' + language + '.targets]]\nname="application"\nunits=[' +
            ','.join('{source=' + json.dumps(name) + '}' for name in sources) + ']\n')
        args = argparse.Namespace(source=self.source, otelc_root=self.provider,
            workspace_parent=self.base, config=configuration, language=None, exclude=[], cases=1)
        with patch.object(generation.capture, 'selected_tools', return_value=selected), \
             patch.object(generation.capture, 'artefacts', return_value={'fixture': 'fixed'}), \
             patch.object(native_profile, 'capability', return_value={'operation': 'rename-main', 'help_sha256': 'unit-stub'}), \
             redirect_stdout(io.StringIO()) as output:
            generation.plan(args)
        return Path(output.getvalue().strip())

    def test_generate_export_detach_and_build_retains_generated_inputs_and_all_state(self):
        workspace = self.plan()
        data = generation.read(workspace / generation.PLAN_FILE)
        self.assertIn('build/compile_commands.json', data['source_manifest'])
        self.assertIn('build/generated/settings.h', data['source_manifest'])
        self.assertEqual(len({entry['id'] for entry in data['inventory']}), len(data['inventory']))
        selected = next(entry for entry in data['inventory'] if entry['name'] == 'selected')
        self.assertEqual(selected['status'], 'ready')
        self.assertEqual(len(selected['globals']), 3)
        headers = [entry for entry in data['inventory'] if entry['name'] == 'header_selected']
        self.assertEqual(len(headers), 2)
        self.assertTrue(all(entry['status'] == 'ready' for entry in headers))
        with redirect_stdout(io.StringIO()):
            generation.generate(argparse.Namespace(workspace=workspace))
        cases = generation.read(workspace / 'tests/corpus.json')
        self.assertEqual(len(cases), 3)
        case = next(case for case in cases if case['function_id'] == selected['id'])
        preview = workspace / 'tests/harnesses' / case['id']
        self.assertFalse((preview / 'project').exists())
        self.assertEqual(generation.read(preview / 'recipe.json')['project'], str(workspace / 'snapshot'))
        destination = self.base / 'exported'
        with redirect_stdout(io.StringIO()) as output:
            generation.export_tests(argparse.Namespace(workspace=workspace, destination=destination, apply=False))
        self.assertIn(native_profile.DIRECTORY, json.loads(output.getvalue())['copy'])
        with redirect_stdout(io.StringIO()):
            generation.export_tests(argparse.Namespace(workspace=workspace, destination=destination, apply=True))
        shutil.rmtree(self.source)
        _, detached = generation.load_workspace(destination, generated=True)
        folder = self.base / 'baseline'
        folder.mkdir()
        project = folder / 'project'
        shutil.copytree(destination / 'snapshot', project)
        observation = folder / 'observation'
        environment = {**os.environ, 'OTELEQ_OBSERVATION': str(observation)}
        command = native_profile.build(generation, destination, detached, selected, case, project,
                                       ['unused-sdk'], environment, folder, 'baseline')
        result = subprocess.run(command, cwd=project, env=environment, capture_output=True, check=False, timeout=20)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b'', b''))
        before, outcome, after = typed_capture.scalar_capture(observation.read_bytes(), selected)
        for item in selected['globals']:
            root = 'global:' + item['name']
            initial = 7 if item['name'] == 'total' else 3 if item['unit'] == selected['unit'] else 4
            self.assertEqual(before['roots'][root]['value'], str(initial))
            self.assertEqual(after['roots'][root]['value'], str(initial + 5))
        self.assertEqual(outcome['graph']['roots']['result']['value'], '24')
        self.assertEqual(len(generation.read(folder / generation.BUILD_IDENTITIES)['outputs']), 6)
        native_profile.verify_build(generation, folder)
        generation.load_workspace(destination, generated=True)
        generation.clean(argparse.Namespace(workspace=destination))
        self.assertFalse(destination.exists())

    def test_cpp_h_headers_and_uppercase_units_use_the_actual_compile_language(self):
        workspace = self.plan('cpp')
        data = generation.read(workspace / generation.PLAN_FILE)
        headers = [entry for entry in data['inventory'] if entry['path'] == 'include/state.h'
                   and entry['name'] == 'header_selected']
        self.assertEqual(len(headers), 2)
        self.assertTrue(all(entry['language'] == 'cpp' and entry['status'] == 'ready' for entry in headers))
        self.assertTrue(any(entry['path'] == 'src/one.C' and entry['otelc_function'] == 'selected(int)'
                            for entry in data['inventory']))

    def test_orphan_source_and_unsupported_sibling_storage_are_visible_blockers(self):
        workspace = self.plan(orphan=True, volatile=True)
        entries = generation.read(workspace / generation.PLAN_FILE)['inventory']
        orphan = next(entry for entry in entries if entry.get('inventory_gap'))
        self.assertEqual(orphan['status'], 'blocked')
        self.assertIn('declared target', orphan['reason'])
        selected = next(entry for entry in entries if entry['name'] == 'selected')
        self.assertEqual(selected['status'], 'blocked')
        self.assertIn('hidden', selected['reason'])

    def test_changed_generated_input_or_retained_context_cannot_load_or_clean(self):
        workspace = self.plan()
        generated = self.source / 'build/generated/settings.h'
        original = generated.read_bytes()
        generated.write_text('#define OFFSET 9\n')
        with self.assertRaisesRegex(ValueError, 'compiler input changed'):
            generation.load_workspace(workspace)
        generated.write_bytes(original)
        path = next((workspace / native_profile.DIRECTORY / 'c/units').glob('*/metadata.json'))
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'retained native context changed'):
            generation.load_workspace(workspace)
        with self.assertRaisesRegex(ValueError, 'native context was edited'):
            generation.clean(argparse.Namespace(workspace=workspace))
        self.assertTrue(workspace.exists())

    def test_native_policy_is_optional_explicit_and_round_trips(self):
        self.assertNotIn('c', policy.load(None)['adapters'])
        configured = policy.validate({'adapters': {'c': {'compilation_database': 'build/compile_commands.json',
            'targets': [{'name': 'one', 'units': [{'source': 'app.c'}]}]}}})
        self.assertEqual(policy.validate(configured), configured)
        with self.assertRaisesRegex(ValueError, 'targets require'):
            policy.validate({'adapters': {'cpp': {'targets': [{'name': 'one', 'units': [{'source': 'app.cpp'}]}]}}})

    def test_required_build_inputs_can_be_the_entire_source_tree(self):
        workspace = self.plan(all_generated=True)
        data = generation.read(workspace / generation.PLAN_FILE)
        self.assertTrue(all(name.startswith('build/') for name in data['source_manifest']))
        self.assertTrue(any(entry['status'] == 'ready' and entry['name'] == 'selected' for entry in data['inventory']))

    def test_missing_sdk_operation_refuses_before_compiling_application_code(self):
        retained = self.base / 'retained'
        retained.mkdir()
        command = []

        def absent(arguments, directory):
            command.extend(arguments)
            return subprocess.CompletedProcess(arguments, 2, b'', b'unknown object command')

        with self.assertRaisesRegex(ValueError, 'does not provide'):
            native_profile.capability(generation, self.provider, retained, absent)
        self.assertEqual(command[-3:], ['object', 'rename-main', '--help'])
        self.assertTrue((retained / 'object-transform-request.json').is_file())


if __name__ == '__main__':
    unittest.main()
