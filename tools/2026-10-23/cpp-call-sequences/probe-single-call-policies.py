"""Read-only effective policy/options map for every retained compatibility entry."""
import argparse,hashlib,json,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--corpus',type=Path,required=True);a=p.parse_args()
sys.path[:0]=[str(a.source/'adapters/generation'),str(a.source/'examples')]
import generation
rows={};plans=0
for path in sorted(a.corpus.rglob('plan.json')):
 plan=json.loads(path.read_text());plans+=1
 for entry in plan['inventory']:
  if entry['language']!='cpp' or entry['status']!='ready':continue
  assert 'sequence_configuration' not in entry
  text=generation.policy(entry,'http://127.0.0.1:1234',service='compatibility-probe')
  key=str(path.relative_to(a.corpus))+'#'+entry['id']
  assert key not in rows
  rows[key]={'policy_sha256':hashlib.sha256(text.encode()).hexdigest(),'receiver_options':generation.attempt_receiver_options(entry,None)}
assert rows
print(json.dumps({'plans':plans,'entries':rows},sort_keys=True))
