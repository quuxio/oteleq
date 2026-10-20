"""The matched compiler inventories source and probes without running applications."""
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
import discovery
import native_frontend


def execute(command: list, directory: Path) -> subprocess.CompletedProcess:
    """Compiler queries have a separate bounded lifetime and never use a shell."""
    return subprocess.run(command, cwd=directory, capture_output=True, check=False, timeout=120)


class NativeFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='native frontend tools ')
        cls.addClassCleanup(temporary.cleanup)
        cls.base = Path(temporary.name).resolve()
        boundary = cls.base / 'application'
        boundary.mkdir()
        cls.compiler = Path(os.environ.get('OTELC_CLANG') or shutil.which('clang'))
        cls.cpp_compiler = Path(os.environ.get('OTELC_CLANGXX') or shutil.which('clang++'))
        cls.helper = cls.base / 'helper'
        cls.record = native_frontend.build(cls.compiler, cls.helper, boundary, execute)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='native frontend app ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()

    def inspect(self, source: str, *, cpp: bool = False, mode: str = 'ast',
                flags: list[str] | None = None, helper: Path | None = None) -> dict:
        name = 'app.cpp' if cpp else 'app.c'
        (self.project / name).write_text(source)
        unit = {'source': name, 'directory': '.',
                'compiler': str(self.cpp_compiler if cpp else self.compiler),
                'flags': flags or ['-std=c++17' if cpp else '-std=c11']}
        evidence = self.root / ('evidence-' + str(len(list(self.root.glob('evidence-*')))))
        return native_frontend.inspect(unit, self.project, self.record, helper or self.helper,
                                       evidence, execute, mode=mode)

    def test_positive_and_negative_include_probes_bind_unread_headers(self):
        present = self.project / 'present.h'
        present.write_text('#error this header must not be included\n')
        source = ('#if __has_include("present.h") && !__has_include("absent.h")\n'
                  'int selected(void){return 1;}\n#else\n#error incorrect search\n#endif\n')
        for mode in ('ast', 'inputs'):
            with self.subTest(mode=mode):
                data = self.inspect(source, mode=mode)
                self.assertEqual({Path(name).resolve() for name in data['files']},
                                 {self.project / 'app.c', present})
                probes = {item['name']: item for item in data['probes']}
                self.assertEqual(set(probes), {'present.h', 'absent.h'})
                self.assertEqual(Path(probes['present.h']['target']).resolve(), present)
                self.assertIsNone(probes['absent.h']['target'])
                self.assertTrue(all(item['kind'] == 'include' and not item['angled'] for item in probes.values()))
                self.assertEqual(bool(data['ast']['inner']), mode == 'ast')

    def test_cpp_standard_headers_are_filtered_and_imported_types_are_canonical(self):
        source = ('#include <string>\n#include <cstdint>\n'
                  'using Small = std::int16_t;\n'
                  'Small selected(Small value){std::string text="x";return value+text.size();}\n')
        data = self.inspect(source, cpp=True)
        self.assertLess(len(json.dumps(data).encode()), 1024 * 1024)
        inventory = discovery.native_inventory(data['ast'], self.project / 'app.cpp', cpp=True)
        selected = next(item for item in inventory['functions'] if item['name'] == 'selected')
        self.assertEqual(selected['parameters'], ['short'])
        self.assertEqual(selected['output'], 'short')
        self.assertEqual(selected['cpp_function']['parameter_spellings'], ['Small'])
        self.assertEqual([item['name'] for item in inventory['functions']], ['selected'])

    def test_project_header_private_models_keep_physical_utf8_byte_ranges(self):
        header = self.project / 'counter.hpp'
        header.write_text('// utf8: \u03bb\nnamespace sample { class Counter { int value; public: '
                          'explicit Counter(int initial):value(initial){} '
                          'int add(short amount){return value+=amount;} }; }\n')
        data = self.inspect('#include "counter.hpp"\nint selected(int value){return value;}\n', cpp=True)
        inventory = discovery.native_inventory(data['ast'], header, cpp=True)
        record = inventory['cpp_records']['sample::Counter']
        self.assertTrue(record['physical'])
        self.assertEqual(header.read_bytes()[record['body_end']:record['body_end'] + 1], b'}')
        self.assertEqual(record['fields'][0]['canonical'], 'int')
        self.assertTrue(record['fields'][0]['physical'])
        method = next(item for item in inventory['functions'] if item['name'] == 'sample::Counter::add')
        self.assertEqual(method['parameters'], ['short'])
        self.assertEqual(method['output'], 'int')
        self.assertEqual(method['line'], 2)

    def test_conversion_operator_remains_a_visible_callable_gap(self):
        data = self.inspect('struct Value { operator int() const {return 7;} };\n'
                            'int selected(int value){return value;}\n', cpp=True)
        inventory = discovery.native_inventory(data['ast'], self.project / 'app.cpp', cpp=True)
        conversion = next((item for item in inventory['functions'] if item['native_kind'] == 'CXXConversionDecl'), None)
        self.assertIsNotNone(conversion, 'a source conversion operator cannot disappear from callable accounting')
        self.assertEqual(conversion['name'], 'Value::operator int')
        self.assertEqual(conversion['output'], 'int')
        self.assertTrue(conversion['reason'])
        self.assertEqual(conversion['cpp_function']['kind'], 'CXXConversionDecl')

    def test_retained_namespace_graphs_survive_repeated_inventory_growth(self):
        source = ''.join('namespace unit' + str(index) + ' {struct Value{int state;}; '
                         'int selected(short value){return value;} }\n' for index in range(65))
        data = self.inspect(source, cpp=True)
        inventory = discovery.native_inventory(data['ast'], self.project / 'app.cpp', cpp=True)
        self.assertEqual({item['name'] for item in inventory['functions']},
                         {'unit' + str(index) + '::selected' for index in range(65)})
        self.assertEqual(len(inventory['cpp_records']), 65)
        self.assertTrue(all(item['parameters'] == ['short'] and item['output'] == 'int'
                            for item in inventory['functions']))
        self.assertTrue(all(item['physical'] and item['fields'][0]['canonical'] == 'int'
                            for item in inventory['cpp_records'].values()))

    def test_discovery_never_executes_application_static_initialisers(self):
        marker = self.project / 'INITIALISER_RAN'
        source = ('#include <cstdio>\nint initialise(){auto f=std::fopen("INITIALISER_RAN","w");'
                  'if(f)std::fclose(f);return 7;}\nint state=initialise();\n'
                  'int selected(int value){return state+value;}\n')
        data = self.inspect(source, cpp=True)
        self.assertTrue(data['complete'])
        self.assertFalse(marker.exists())
        self.assertEqual(sorted(path.name for path in self.project.iterdir()), ['app.cpp'])

    def test_embed_inputs_are_observed_or_an_unsupported_compiler_refuses(self):
        (self.project / 'resource.bin').write_bytes(b'\x01\x02')
        (self.project / 'empty.bin').write_bytes(b'')
        source = ('#if __has_embed("resource.bin") != 1 || __has_embed("empty.bin") != 2 '
                  '|| __has_embed("absent.bin") != 0\n#error bad resource search\n#endif\n'
                  'const unsigned char bytes[]={\n#embed "resource.bin"\n};\n'
                  'int selected(void){return bytes[0];}\n')
        if self.record['clang_major'] < 19:
            with self.assertRaisesRegex(ValueError, 'compiler query failed'):
                self.inspect(source, flags=['-std=c23'])
            return
        data = self.inspect(source, flags=['-std=c23'])
        probes = {(item['kind'], item['name']): item['target'] for item in data['probes']}
        self.assertEqual(set(probes), {('has-embed', 'resource.bin'), ('has-embed', 'empty.bin'),
                                      ('has-embed', 'absent.bin'), ('embed', 'resource.bin')})
        self.assertIsNone(probes['has-embed', 'absent.bin'])
        self.assertEqual(Path(probes['has-embed', 'empty.bin']).resolve(), self.project / 'empty.bin')
        self.assertEqual(Path(probes['embed', 'resource.bin']).resolve(), self.project / 'resource.bin')

    def test_owned_helper_relocates_and_changed_assets_refuse(self):
        relocated = self.root / 'retained-helper'
        shutil.copytree(self.helper, relocated)
        native_frontend.verify(self.record, relocated)
        self.assertTrue(self.inspect('int selected(void){return 7;}\n', helper=relocated)['complete'])
        for name in self.record['assets']:
            path = relocated / name
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'helper asset changed'):
                native_frontend.verify(self.record, relocated)
            path.write_bytes(original)

    def test_wrong_compiler_escape_mode_and_syntax_errors_refuse(self):
        for source, options, reason in (
                ('int selected(void){return 1;}\n', {'mode': 'unknown'}, 'mode'),
                ('not a valid translation unit', {}, 'compiler query failed')):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.inspect(source, **options)
        unit = {'source': '../outside.c', 'directory': '.', 'compiler': str(self.compiler), 'flags': []}
        with self.assertRaisesRegex(ValueError, 'paths escape'):
            native_frontend.inspect(unit, self.project, self.record, self.helper, self.root / 'escape', execute)
        unit['compiler'] = '/a/different/compiler'
        with self.assertRaisesRegex(ValueError, 'different compiler'):
            native_frontend.inspect(unit, self.project, self.record, self.helper, self.root / 'compiler', execute)


class NativeFrontendDocumentTests(unittest.TestCase):
    def document(self) -> dict:
        return {'schema_version': 1, 'clang_major': 22, 'complete': True, 'files': ['/source/app.c'],
                'probes': [{'kind': 'include', 'source': '/source/app.c', 'offset': 1,
                            'name': 'absent.h', 'angled': False, 'target': None}],
                'ast': {'kind': 'TranslationUnitDecl', 'inner': []}}

    def test_metadata_must_be_complete_bounded_and_strictly_typed(self):
        valid = self.document()
        self.assertEqual(native_frontend.document(json.dumps(valid).encode(), 22), valid)
        alterations = [
            {'extra': True}, {'schema_version': True}, {'clang_major': 18}, {'complete': False},
            {'files': []}, {'files': [None]}, {'files': [[]]}, {'files': ['bad\0path']},
            {'files': ['/source/app.c'] * 2}, {'probes': None}, {'ast': {'kind': 'Other', 'inner': []}},
            {'ast': {'kind': 'TranslationUnitDecl', 'inner': [1]}},
        ]
        for change in alterations:
            with self.subTest(change=change), self.assertRaises(ValueError):
                native_frontend.document(json.dumps({**valid, **change}).encode(), 22)
        for change in ({'kind': 'unknown'}, {'source': '/other.c'}, {'offset': True}, {'offset': -1},
                       {'target': '/unrecorded.h'}, {'name': ''}, {'angled': 1}, {'extra': True}):
            data = copy.deepcopy(valid)
            data['probes'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                native_frontend.document(json.dumps(data).encode(), 22)
        with self.assertRaises(ValueError):
            native_frontend.document(b'{"complete":true,"complete":true}', 22)
        with self.assertRaisesRegex(ValueError, 'byte budget'):
            native_frontend.document(b' ' * (native_frontend.MAX_METADATA_BYTES + 1), 22)


if __name__ == '__main__':
    unittest.main()
