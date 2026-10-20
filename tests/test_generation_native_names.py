"""Application macros cannot replace compiler-bound observer identifiers."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapters/generation'))
import native_names


class NativeNameTests(unittest.TestCase):
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
