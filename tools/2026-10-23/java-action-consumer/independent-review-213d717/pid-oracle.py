from pathlib import Path
import itertools,json,sys,tempfile
base=Path(__file__).resolve().parent
source=base/'source'
sys.path[:0]=[str(source/'adapters/generation'),str(source/'examples'),str(source/'tests')]
import java_witness as witness
from test_generation_java_witness import final_report,reply
results=[]
with tempfile.TemporaryDirectory(dir='/tmp') as temporary:
 root=Path(temporary).resolve();root.chmod(0o700)
 for actual,frozen,outer,header in itertools.product((123,124),repeat=4):
  original=reply();original['pid']=frozen
  identity=witness.Identity.bind(original,{name:original[name] for name in witness.HASH_FIELDS},pid=frozen)
  document=final_report();document['pid']=outer;document['producer']['pid']=header
  path=root/'witness-health.json';path.write_text(json.dumps(document));path.chmod(0o600)
  expected=len({actual,frozen,outer,header})==1
  try:
   witness.read_final(root,pid=actual,identity=identity)
   accepted=True
  except ValueError:accepted=False
  assert accepted==expected,(actual,frozen,outer,header,expected,accepted)
  results.append({'actual':actual,'frozen':frozen,'outer':outer,'header':header,'accepted':accepted})
print(json.dumps({'python':sys.version.split()[0],'cases':len(results),'accepted':sum(r['accepted'] for r in results),'refused':sum(not r['accepted'] for r in results),'results':results}))
