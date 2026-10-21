"""Real target inventories retain header declarations and state in sibling units."""
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


def execute(command, directory, **kwargs):
    return subprocess.run(command, cwd=directory, capture_output=True, check=False, timeout=120,
                          input=kwargs.get('input_data'))


class NativeContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='native target context ')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'application'
        for name in ('src', 'include', 'build'):
            (self.root / name).mkdir(parents=True)

    def prepare(self, language, units):
        compiler = Path(os.environ.get('OTELC_CLANGXX' if language == 'cpp' else 'OTELC_CLANG')
                        or shutil.which('clang++' if language == 'cpp' else 'clang'))
        records = [{'directory': str(self.root / 'build'), 'file': '../' + source,
                    'arguments': [str(compiler), '-I', '../include',
                        '-std=c++17' if language == 'cpp' else '-std=c11', '-O0', '-c', '../' + source,
                        '-o', str(index) + '.o']} for index, source in enumerate(units)]
        (self.root / 'build/compile_commands.json').write_text(json.dumps(records))
        options = native_project.settings({'compilation_database': 'build/compile_commands.json',
            'targets': [{'name': 'application', 'units': [{'source': source} for source in units]}]})
        evidence = self.base / 'evidence'
        prepared = native_project.prepare(self.root, options, language, compiler, evidence, execute)
        demangler = compiler.resolve().with_name('llvm-cxxfilt') if language == 'cpp' else None
        return prepared, native_context.target_inventory(prepared, evidence, demangler, execute)

    def test_c_target_deduplicates_externs_and_retains_distinct_internal_storage(self):
        (self.root / 'include/state.h').write_text('extern int total;\n')
        (self.root / 'src/one.c').write_text('#include "state.h"\nstatic int local=3;\n'
            'int selected(int value){local+=value;total+=value;return total+local;}\nint main(void){}\n')
        (self.root / 'src/two.c').write_text('#include "state.h"\nextern int total=7;static int local=4;\n'
            'int sibling(int value){local+=value;return local;}\n')
        prepared, inventory = self.prepare('c', ['src/one.c', 'src/two.c'])
        definitions = {item['function']['name'] for item in inventory if not item['function']['declaration_only']}
        self.assertEqual(definitions, {'selected', 'main', 'sibling'})
        selected = next(item for item in inventory if item['function']['name'] == 'selected')
        roots = selected['globals']
        self.assertEqual(len(roots), 3)
        total = next(item for item in roots if item['name'] == 'total')
        self.assertEqual(total['source_file'], 'src/two.c')
        self.assertEqual(len(total['declarations']), 3)
        self.assertTrue(total['definition'])
        self.assertEqual({item['expression'] for item in roots}, {'local', 'total'})
        self.assertEqual(len({item['name'] for item in roots if item['internal']}), 2)
        self.assertEqual({item['unit'] for item in roots}, set(prepared['units']))
        self.assertEqual(selected['files'], ['include/state.h', 'src/one.c', 'src/two.c'])
        self.assertEqual(selected['function']['source_file'], 'src/one.c')
        self.assertFalse(any((self.root / 'build').glob('*.o')))
        key = next(iter(prepared['units']))
        metadata = self.base / 'evidence/units' / key / 'metadata.json'
        moved = metadata.with_suffix('.original')
        metadata.rename(moved)
        metadata.symlink_to(moved)
        with self.assertRaisesRegex(ValueError, 'compiler metadata changed'):
            native_context.unit_inventory(prepared, key, self.base / 'evidence', None, execute)

    def test_cpp_headers_out_of_line_constructors_private_statics_and_gaps_remain_bound(self):
        (self.root / 'include/counter.h').write_text('class Counter{int value;static int total;public:'
            'explicit Counter(int initial);int add(short amount);};\n')
        (self.root / 'src/one.cpp').write_text('#include "counter.h"\n'
            'Counter::Counter(int initial):value(initial){}\nint Counter::total=0;\n'
            'int Counter::add(short amount){value+=amount;total+=amount;return value;}\n')
        (self.root / 'src/two.cpp').write_text('#include "counter.h"\nstatic int audit=9;\n'
            'thread_local int thread_state=1;\n'
            'template<class T>struct Holder{inline static int state=0;};\n'
            'int sibling(int amount){static int calls=0;calls++;Holder<int>::state++;return audit+amount;}\n')
        _, inventory = self.prepare('cpp', ['src/one.cpp', 'src/two.cpp'])
        method = next(item for item in inventory if item['function']['name'] == 'Counter::add'
                      and not item['function']['declaration_only'])
        self.assertEqual(method['function']['cpp_function']['compiler_identity'], 'Counter::add(short)')
        self.assertTrue(all('source_file' in item for item in method['models']['cpp_functions']))
        self.assertEqual(method['function']['parameters'], ['short'])
        record = method['models']['cpp_records']['Counter']
        self.assertEqual(record['source_file'], 'include/counter.h')
        constructor = next(item for item in record['constructors'] if not item['implicit'])
        self.assertEqual(constructor['initialised_fields'], ['value'])
        self.assertTrue(constructor['has_body'])
        total = next(item for item in method['globals'] if item['name'] == 'Counter::total')
        self.assertTrue(total['private'])
        self.assertEqual(total['source_file'], 'src/one.cpp')
        gaps = [item for item in method['globals'] if item.get('inaccessible')]
        self.assertTrue(any('thread-local' in item['name'] for item in gaps))
        self.assertTrue(any('static-local' in item['name'] for item in gaps))
        self.assertTrue(any('template storage' in item['reason'] for item in gaps))
        self.assertTrue(any(item['expression'] == 'audit' for item in method['globals']))

    def test_linked_type_conflicts_and_ambiguous_labels_are_not_silently_deduplicated(self):
        item = {'name': 'state', 'expression': 'state', 'type': 'int', 'symbol': 'state',
                'source_file': 'app.c', 'source_offset': 1, 'definition': True, 'internal': False}
        inventories = {'one': {'globals': [item]}, 'two': {'globals': [{**item, 'type': 'short'}]}}
        with self.assertRaisesRegex(ValueError, 'inconsistent compiler types'):
            native_context.target_globals({'units': ['one', 'two']}, inventories)
        inventories['two']['globals'] = [{**item, 'symbol': 'a_different_linked_symbol'}]
        with self.assertRaisesRegex(ValueError, 'ambiguous target storage labels'):
            native_context.target_globals({'units': ['one', 'two']}, inventories)

    def test_referenced_foreign_storage_remains_an_explicit_gap(self):
        (self.base / 'foreign.h').write_text('extern int foreign_state;\n')
        (self.root / 'src/app.c').write_text('#include "../../foreign.h"\n'
            'int selected(int amount){int local=amount;return local+foreign_state+foreign_state;}\n')
        _, inventory = self.prepare('c', ['src/app.c'])
        selected = next(item for item in inventory if item['function']['name'] == 'selected')
        self.assertEqual(len(selected['globals']), 1)
        root = selected['globals'][0]
        self.assertTrue(root['inaccessible'])
        self.assertIn('external-storage:foreign_state', root['name'])
        self.assertIn('foreign storage', root['reason'])

    def test_cpp_constexpr_and_const_roots_use_compiler_linkage_for_each_unit(self):
        (self.root / 'include/state.h').write_text('inline const int shared=9;\n')
        for name, local, tick in (('one', 3, 11), ('two', 4, 12)):
            (self.root / ('src/' + name + '.cpp')).write_text('#include "state.h"\n'
                'const int local=' + str(local) + ';constexpr int tick=' + str(tick) + ';\n'
                'int ' + name + '(void){return local+tick+shared;}\n')
        _, inventory = self.prepare('cpp', ['src/one.cpp', 'src/two.cpp'])
        roots = inventory[0]['globals']
        self.assertEqual(len(roots), 5)
        self.assertEqual(sum(item['internal'] for item in roots), 4)
        self.assertEqual({item['expression'] for item in roots if item['internal']}, {'local', 'tick'})
        self.assertEqual([item['name'] for item in roots if not item['internal']], ['shared'])

    def test_storage_requires_boolean_compiler_linkage_instead_of_a_name_heuristic(self):
        variable = {'kind': 'VarDecl', 'id': 'storage', 'name': 'state',
                    'loc': {'file': str(self.root / 'state.c'), 'offset': 0}, 'type': {'qualType': 'int'}}
        for value in (None, 'false', 0):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'compiler storage linkage is missing'):
                native_context.Storage({**variable, 'oteleq_internal_linkage': value}, self.root, {})


if __name__ == '__main__':
    unittest.main()
