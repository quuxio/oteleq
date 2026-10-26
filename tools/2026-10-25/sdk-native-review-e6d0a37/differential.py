"""Compare refactored command records and validation with the exact published parent."""
import copy
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import tempfile
import types
from unittest import mock
from otelc import native_units
from test_native_units import fixture

source = subprocess.check_output(['git','show','21c218c31e82ee779ecfbf87a4288391ffb6e9f3:otelc/native_units.py'])
old = types.ModuleType('original_units')
exec(compile(source,'21c218c:otelc/native_units.py','exec'),old.__dict__)
comparisons=0
with tempfile.TemporaryDirectory() as temporary:
 base=Path(temporary).resolve()
 for language,overlay in [('c',False),('cpp',False),('cpp',True)]:
  here=base/(language+str(overlay)); here.mkdir()
  root,recipe=fixture(here,language,private_overlay=overlay)
  for renames in itertools.product((False,True),repeat=2):
   for flags in ([],['-pthread','-lm']):
    candidate=copy.deepcopy(recipe)
    for unit,rename in zip(candidate['units'],renames): unit['rename_main']=rename
    candidate['link']['flags']=flags
    assert native_units.validate(candidate,root)==old.validate(candidate,root)
    assert native_units.steps(candidate,here/'out',{'directory':'/llvm22'},'/plugin',Path('/sdk.so'))==old.steps(candidate,here/'out',{'directory':'/llvm22'},'/plugin',Path('/sdk.so'))
    comparisons+=1
 # Run the maintained malformed-recipe/overlay assertions against both validators.
 import unittest
 import test_native_units
 for module in (old,native_units):
  suite=unittest.defaultTestLoader.loadTestsFromTestCase(test_native_units.NativeUnitRecipeTests)
  with mock.patch.object(test_native_units,'native_units',module):
   result=unittest.TextTestRunner(verbosity=2).run(suite)
  assert result.wasSuccessful() and not result.skipped
result={'original':'21c218c31e82ee779ecfbf87a4288391ffb6e9f3','original_native_units_sha256':hashlib.sha256(source).hexdigest(),'exact_command_and_valid_recipe_comparisons':comparisons,'maintained_recipe_methods_against_each_version':3,'malformed_recipe_overlay_assertions':'passed against both exact parent and correction','application_builds':0}
Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/sdk-native-review-e6d0a37/differential-result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
