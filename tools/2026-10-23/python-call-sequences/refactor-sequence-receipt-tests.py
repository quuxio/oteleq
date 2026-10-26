"""Share independent receipt fixtures and fault checks between language tests."""
from pathlib import Path
import ast
ROOT=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-call-sequences')
python=(ROOT/'tests/test_generation_python_sequence_qualification.py').read_text()
start=python.index("            cli, provider = folder / 'cli', folder / 'provider'")
end=python.index('            self.assertEqual(qualifier.verify_operations(folder, cli), 34)',start)
block=python[start:end]
block='\n'.join(line[8:] for line in block.splitlines())+'\n'
block=block.replace('qualifier.function(method)','function_id(method)').replace('qualifier.METHODS','METHODS').replace('qualifier.CONTROL_VERDICTS','CONTROL_VERDICTS')
block=block.replace("('cases', 'edge-one', 'edge-thirty-two', 'edge-rich-thirty-two', 'rebound-class')","('cases', 'edge-one', 'edge-thirty-two', *refusals)").replace("name in ('edge-rich-thirty-two', 'rebound-class')",'name in refusals')
start=python.index("            for fault in ('missing', 'exit', 'argv', 'verdict'):")
end=python.index("\n\n\nif __name__",start)
faults=python[start:end]
faults='\n'.join(line[8:] for line in faults.splitlines())+'\n'
faults=faults.replace('self.','test.').replace('qualifier.verify_operations(folder, cli)','verify(folder, cli)')
header='''"""Independent fixed command receipts and adversarial checks for sequence qualifiers."""
import json
from pathlib import Path
import sys
from collections.abc import Callable
import unittest

METHODS = ('identity', 'secret', 'transient', 'fail', 'recursive', 'touch')
CONTROL_VERDICTS = {
    'missing-call': (3, 'inconclusive'), 'reordered-calls': (3, 'inconclusive'),
    'missing-field': (1, 'different_observed'), 'missing-method-witness': (3, 'inconclusive'),
    'undeclared-intermediate-error': (2, 'blocked'),
}


def write_receipts(folder: Path, function_id: Callable[[str], str], refusals: tuple[str, ...]) -> Path:
    """Construct literal expected commands without asking the verifier for its own contract."""
'''
helper=header+block+'    return cli\n\n\ndef reject_bad_receipts(test: unittest.TestCase, verify: Callable, folder: Path, cli: Path) -> None:\n    """Missing terminals, wrong exits, changed argv and false verdicts must refuse."""\n'+faults
compile(helper,'sequence_receipt_fixture.py','exec')
(ROOT/'tests/sequence_receipt_fixture.py').write_text(helper)
for language in ('python','cpp'):
    path=ROOT/f'tests/test_generation_{language}_sequence_qualification.py'
    source=path.read_text()
    source=source.replace('import unittest\n','import unittest\n\nfrom sequence_receipt_fixture import write_receipts, reject_bad_receipts\n')
    start=source.index("            cli, provider = folder / 'cli', folder / 'provider'")
    end=source.index('            self.assertEqual(qualifier.verify_operations(folder, cli),',start)
    refusals="('edge-rich-thirty-two', 'rebound-class')" if language=='python' else "('edge-rich-thirty-two',)"
    source=source[:start]+f'            cli = write_receipts(folder, qualifier.function, {refusals})\n'+source[end:]
    start=source.index("            for fault in ('missing', 'exit', 'argv', 'verdict'):")
    end=source.index("\n\n\nif __name__",start)
    source=source[:start]+'            reject_bad_receipts(self, qualifier.verify_operations, folder, cli)'+source[end:]
    compile(source,path.name,'exec')
    path.write_text(source)
print('Shared independent route fixtures and fault checks; Python strict and C++ historical tests remain separate.')
