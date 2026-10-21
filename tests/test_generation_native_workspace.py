"""Fresh copied roots rebind application inputs while preserving frozen provenance."""
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
import native_project
import native_workspace


def execute(command, directory):
    return subprocess.run(command, cwd=directory, capture_output=True, check=False, timeout=120)


class NativeWorkspaceTests(unittest.TestCase):
    def test_rebinding_moves_only_application_paths_and_does_not_mutate_discovery(self):
        original, project = Path('/original/app'), Path('/fresh/app')
        unit = {'dependencies': {
            '/original/app/main.c': {'resolved': '/original/app/main.c', 'source_relative': 'main.c', 'sha256': 'a'},
            '/original/application/foreign.h': {'resolved': '/sdk/foreign.h', 'source_relative': None, 'sha256': 'b'}},
            'probes': [{'source': '/original/app/main.c', 'target': '/original/app/present.h', 'name': 'present.h'},
                       {'source': '/sdk/header.h', 'target': None, 'name': 'absent.h'}]}
        prepared = {'source_root': str(original)}
        before = copy.deepcopy(unit)
        state = native_workspace.expected_inputs(prepared, unit, project)
        self.assertEqual(unit, before)
        self.assertEqual(state['dependencies']['/fresh/app/main.c']['resolved'], '/fresh/app/main.c')
        self.assertEqual(state['dependencies']['/original/application/foreign.h']['resolved'], '/sdk/foreign.h')
        self.assertEqual(state['probes'][0]['target'], '/fresh/app/present.h')
        self.assertEqual(state['probes'][1]['source'], '/sdk/header.h')
        self.assertIsNone(state['probes'][1]['target'])

    def test_actual_detached_copy_rechecks_new_headers_and_retained_metadata(self):
        with tempfile.TemporaryDirectory(prefix='native detached inputs ') as temporary:
            base = Path(temporary).resolve()
            source, retained = base / 'source', base / 'retained'
            (source / 'build').mkdir(parents=True)
            (source / 'present.h').write_text('unused positive probe\n')
            (source / 'app.c').write_text('#if __has_include("present.h") && !__has_include("absent.h")\n'
                                        'int selected(void){return 7;}\n#else\nint selected(void){return 9;}\n#endif\n')
            compiler = Path(os.environ.get('OTELC_CLANG') or shutil.which('clang'))
            database = source / 'build/compile_commands.json'
            database.write_text(json.dumps([{'directory': str(source), 'file': 'app.c',
                'arguments': [str(compiler), '-std=c11', '-c', 'app.c', '-o', 'build/app.o']}]))
            options = native_project.settings({'compilation_database': 'build/compile_commands.json',
                       'targets': [{'name': 'one', 'units': [{'source': 'app.c'}]}]})
            prepared = native_project.prepare(source, options, 'c', compiler, retained, execute)
            frozen = copy.deepcopy(prepared)
            project = base / 'detached'
            shutil.copytree(source, project)
            shutil.rmtree(source)
            native_workspace.verify_copy(prepared, retained, project, base / 'clean-check', execute)
            self.assertEqual(prepared, frozen)
            self.assertFalse(source.exists())
            (project / 'absent.h').write_text('new negative-probe input\n')
            with self.assertRaisesRegex(ValueError, 'preprocessor search results changed'):
                native_workspace.verify_copy(prepared, retained, project, base / 'new-header-check', execute)
            (project / 'absent.h').unlink()
            (project / 'present.h').write_text('altered positive probe\n')
            with self.assertRaisesRegex(ValueError, 'private project input changed'):
                native_workspace.verify_copy(prepared, retained, project, base / 'altered-check', execute)
            (project / 'present.h').write_text('unused positive probe\n')
            key = next(iter(prepared['units']))
            (retained / 'units' / key / 'metadata.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'retained compiler metadata changed'):
                native_workspace.verify_copy(prepared, retained, project, base / 'metadata-check', execute)
            with self.assertRaisesRegex(ValueError, 'outside application source'):
                native_workspace.verify_copy(prepared, retained, project, project / 'unsafe', execute)
            changed = copy.deepcopy(prepared)
            changed['compiler']['sha256'] = 'bad'
            with self.assertRaisesRegex(ValueError, 'selected compiler changed'):
                native_workspace.verify_copy(changed, retained, project, base / 'compiler-check', execute)


if __name__ == '__main__':
    unittest.main()
