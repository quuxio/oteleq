from pathlib import Path
import copy,json,sys
base=Path(__file__).resolve().parent
sys.path[:0]=[str(base/'source/tests'),str(base/'source/adapters/generation'),str(base/'source/examples')]
import java_witness as w
import test_generation_java_witness as direct
import test_generation_java_handle_witness as handle
rows=[]
for selected in (w.PROFILE,w.HANDLE_PROFILE):
 for source in (w.PROFILE,w.HANDLE_PROFILE):
  value=direct.reply() if source==w.PROFILE else handle.reply()
  try:w.reply(value,'a'*32,profile=selected)
  except ValueError:accepted=False
  else:accepted=True
  assert accepted==(selected==source)
  rows.append({'selected':selected,'source':source,'accepted':accepted})
value=handle.reply();expected={key:value[key] for key in w.hash_fields(w.HANDLE_PROFILE)}
for route in ('0'*64,handle.ROUTE):
 requested={**expected,'route_binding_sha256':route}
 try:w.Identity.bind(value,requested,pid=123,profile=w.HANDLE_PROFILE)
 except ValueError:accepted=False
 else:accepted=True
 assert accepted==(route==handle.ROUTE)
 rows.append({'expected_route_matches':route==handle.ROUTE,'accepted':accepted})
for complete in (False,True):
 for proof in (False,True,0,1,None,'true'):
  scope=direct.scope(complete);scope['route_verified']=proof
  try:w.read_scope(scope,profile=w.HANDLE_PROFILE)
  except ValueError:accepted=False
  else:accepted=True
  expected_accept=type(proof)is bool and (not complete or proof)
  assert accepted==expected_accept
  rows.append({'complete':complete,'proof_type':type(proof).__name__,'proof':proof,'accepted':accepted})
print(json.dumps(rows))
