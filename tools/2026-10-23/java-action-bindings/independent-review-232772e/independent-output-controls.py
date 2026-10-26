from pathlib import Path
from unittest.mock import patch
import json,os,sys
base=Path(__file__).resolve().parent
sys.path[:0]=[str(base/'source/tests'),str(base/'source/adapters/generation'),str(base/'source/examples')]
from test_generation_java_action_bindings import JavaActionBindingsTests
import java_action_bindings as bindings
rows=[]
for variant in ('different_in_place','identical_replacement','fifo_replacement'):
 case=JavaActionBindingsTests();case.setUp(); original=bindings.witness.private_snapshot; calls=0
 def mutate(runtime,name,maximum):
  global calls
  snapshot=original(runtime,name,maximum);calls+=1
  if calls==1:
   path=runtime/name
   if variant=='different_in_place':path.write_bytes(b'{"changed":true}')
   else:
    path.unlink()
    if variant=='identical_replacement':path.write_bytes(snapshot.raw);path.chmod(0o600)
    else:os.mkfifo(path,0o600)
  return snapshot
 try:
  with patch.object(bindings.witness,'private_snapshot',side_effect=mutate):
   try:case.compile()
   except ValueError as error:
    rows.append({'variant':variant,'refused':True,'reason':str(error),'record_present':(case.root/'bindings/compiler-inputs.json').exists()})
   else:raise AssertionError('changed output accepted')
 finally:case.doCleanups()
print(json.dumps(rows))
