"""Independent ordinary fixture and full scalar oracle for the native SDK probe."""
import native_context
import native_project


class OrdinaryFixture:
    def prepare(self, language):
        self.language = language
        tools = capture.selected_tools(PROVIDER, language)
        compiler = tools['clang++' if language == 'cpp' else 'clang']
        extension = '.cpp' if language == 'cpp' else '.c'
        sources = ['src/one' + extension, 'src/two' + extension]
        (self.root / 'include/state.h').write_text('extern int total;int sibling(int);\n')
        selected = 'int selected(short amount){local+=amount;return sibling(amount)+local;}\n'
        if language == 'cpp':
            selected = 'namespace work{static int local=3;' + selected + 'int selected(int amount){return -999;}}\n'
        else:
            selected = 'static int local=3;' + selected
        (self.root / sources[0]).write_text('#include "state.h"\n' + selected + 'int main(void){}\n'
            '#define int broken_type\n#define __builtin_memcpy_inline(a,b,c) broken_copy\n')
        (self.root / sources[1]).write_text('#include "state.h"\nint total=7;static int local=4;\n'
            'int sibling(int amount){local+=amount;total+=amount;return total;}\n')
        database = [{'directory': str(self.root / 'build'), 'file': '../' + name,
            'arguments': [str(compiler), '-I', '../include', '-std=c++17' if language == 'cpp' else '-std=c11',
                          '-O0', '-c', '../' + name, '-o', str(index) + '.o']}
                    for index, name in enumerate(sources)]
        (self.root / 'build/compile_commands.json').write_text(json.dumps(database))
        options = native_project.settings({'compilation_database': 'build/compile_commands.json',
            'targets': [{'name': 'application', 'units': [{'source': name} for name in sources]}]})

        def query(command, directory, **kwargs):
            return subprocess.run(command, cwd=directory, capture_output=True, timeout=120, check=False,
                                  input=kwargs.get('input_data'))

        evidence = self.base / 'evidence'
        prepared = native_project.prepare(self.root, options, language, compiler, evidence, query)
        inventory = native_context.target_inventory(prepared, evidence, tools.get('cpp-demangler'), query)
        chosen = next(item for item in inventory if item['function']['name'] ==
                      ('work::selected' if language == 'cpp' else 'selected') and item['function']['parameters'] == ['short'])
        entry = {**chosen['function'], 'language': language, 'globals': chosen['globals'],
                 'unit': chosen['unit'], 'target': chosen['target']}
        self.own = next(item['name'] for item in entry['globals'] if item['internal'] and item['unit'] == entry['unit'])
        self.sibling = next(item['name'] for item in entry['globals'] if item['internal'] and item['unit'] != entry['unit'])
        return prepared, entry, inventory

    def assert_roots(self, graph, own, sibling, total):
        expected = {'global:total': total, 'global:' + self.own: own, 'global:' + self.sibling: sibling}
        assert set(graph['roots']) == set(expected)
        assert graph['nodes'] == []
        for name, value in expected.items():
            assert graph['roots'][name] == {'kind': 'integer', 'type': self.language + '.int',
                                            'value': str(value), 'bits': 32, 'signed': True}


NativeWorkersTests = OrdinaryFixture
