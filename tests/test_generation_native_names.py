"""Application macros cannot replace compiler-bound observer identifiers."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapters/generation'))
import native_names


class NativeNameTests(unittest.TestCase):
    def test_cpp_alternative_tokens_in_comments_strings_and_expressions_compile(self):
        words = 'and and_eq bitand bitor compl not not_eq or or_eq xor xor_eq'
        code = ('// ' + words + '\nconst char* text="' + words + '";\n'
                'int main(){int ordinary=0;bool valid=true and not false;'
                'return ordinary + (valid?0:1) + (text[0]==\'a\'?0:1);}\n')
        guard = native_names.undefinitions(code, cpp=True)
        self.assertTrue(all('#undef ' + word + '\n' not in guard for word in words.split()))
        self.assertIn('#undef ordinary\n', guard)
        with tempfile.TemporaryDirectory(prefix='cpp-macro-keywords-') as temporary:
            folder = Path(temporary)
            source = folder / 'app.cpp'
            source.write_text('#define ordinary compile_failure\n' + guard + code)
            compiler = os.environ.get('OTELC_CLANGXX') or shutil.which('clang++')
            built = subprocess.run([compiler, '-std=c++17', source, '-o', folder / 'app'],
                capture_output=True, check=False, timeout=30)
            self.assertEqual(built.returncode, 0, built.stderr.decode())
            result = subprocess.run([folder / 'app'], capture_output=True, check=False, timeout=10)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b'', b''))

    def test_c_keeps_macro_cleanup_for_cpp_alternative_spellings(self):
        words = 'and and_eq bitand bitor compl not not_eq or or_eq xor xor_eq'
        guard = native_names.undefinitions(words)
        self.assertEqual(set(guard.splitlines()), {'#undef ' + word for word in words.split()})
        with tempfile.TemporaryDirectory(prefix='c-macro-keywords-') as temporary:
            folder = Path(temporary)
            source = folder / 'app.c'
            source.write_text('#define and 99\n' + guard + 'int main(void){int and=0;return and;}\n')
            compiler = os.environ.get('OTELC_CLANG') or shutil.which('clang')
            built = subprocess.run([compiler, '-std=c11', source, '-o', folder / 'app'],
                capture_output=True, check=False, timeout=30)
            self.assertEqual(built.returncode, 0, built.stderr.decode())
            self.assertEqual(subprocess.run([folder / 'app'], check=False, timeout=10).returncode, 0)

    def test_exact_compiler_names_keep_unicode_and_dollar_spellings(self):
        actual = native_names.identifiers('int main(){return selected(value);}',
            ['scope::\u6570\u636e', '\U00020000', 'dollar$slot', '$root', 'operator()', 'bad-name', 'Thing<int>', ''])
        self.assertEqual(actual, {'int', 'main', 'return', 'selected', 'value',
                                  'scope', '\u6570\u636e', '\U00020000', 'dollar$slot', '$root'})

    def test_cleanup_is_sorted_unique_and_preserves_only_owned_macros(self):
        self.assertEqual(native_names.undefinitions('owned(z); z(); a();',
            ['scope::\u6570\u636e', 'z'], preserve=['owned']),
            '#undef a\n#undef scope\n#undef z\n#undef \u6570\u636e\n')


if __name__ == '__main__':
    unittest.main()
