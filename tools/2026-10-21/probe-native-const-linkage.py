"""Independently expose C++ internal constants being merged across compile units."""
from pathlib import Path
import sys

sys.path.insert(0, '/Users/sclarke/github/oteleq-qualification/work/oteleq-cpp-receivers/tests')
import test_generation_native_context as context_tests

case = context_tests.NativeContextTests()
case.setUp()
try:
    (case.root / 'include/state.h').write_text('inline const int shared=9;\n')
    for name, local, tick in (('one', 3, 11), ('two', 4, 12)):
        (case.root / ('src/' + name + '.cpp')).write_text('#include "state.h"\n'
            'const int local=' + str(local) + ';constexpr int tick=' + str(tick) + ';\n'
            'int ' + name + '(void){return local+tick+shared;}\n')
    prepared, inventory = case.prepare('cpp', ['src/one.cpp', 'src/two.cpp'])
    roots = inventory[0]['globals']
    print([(item['name'], item['internal'], item['type']) for item in roots], flush=True)
    assert len(roots) == 5, 'two local and two tick constants must retain all four unit identities plus shared'
    assert sum(item['internal'] for item in roots) == 4
finally:
    case.doCleanups()
