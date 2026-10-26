"""Independent complete graph oracle with an explicitly bounded GC turn count."""
import copy
import hashlib
import json
from pathlib import Path
import struct

BASE=Path(__file__).resolve().parent/'public-collection-initial'
def number(value):return {'type':'float64','bits':struct.pack('>d',value).hex()}
MISSING=object()
def graph(argument,value,result=MISSING):
 roots={'arguments':{'ref':0},'receiver':{'ref':1} if value is not None else {'type':'null'}}
 nodes=[{'type':'array','fields':[['0',number(argument),True,True,True],['length',number(1),True,False,False]],'prototype':'Array','extensible':True}]
 if value is not None:nodes.append({'type':'object','fields':[['value',number(value),True,True,True],['self',{'ref':1},True,True,True]],'prototype':'declared:seq.Counter','extensible':True})
 if result is not MISSING:roots['result']=result
 return {'roots':roots,'nodes':nodes}
def step(index,action,argument,before,after,result):
 return {'id':'step-'+str(index),'action':action,'gaps':[],'before':graph(argument,before),'outcome':{'kind':'return','value':graph(argument,after,result)},'after':graph(argument,after)}
steps=[step(0,'call',7,10,17,number(17)),step(1,'call',2,17,19,number(19)),step(2,'release',2,19,None,{'type':'undefined'}),step(3,'collect',2,None,None,{'type':'boolean','value':True})]
expected={'before':steps[0]['before'],'outcome':steps[1]['outcome'],'after':steps[-1]['after'],'steps':steps}
rows=[]
for profile in sorted(p for p in BASE.iterdir() if p.is_dir()):
 paths=sorted((profile/'report').rglob('observation'));assert len(paths)==4
 for p in paths:
  observed=json.loads(p.read_bytes());collection=observed['steps'][-1].pop('collection')
  assert set(collection)=={'completed','rounds'} and collection['completed'] is True and type(collection['rounds']) is int and 1<=collection['rounds']<=64
  assert observed==expected,p
  request=json.loads((p.parent/'node-source-request.json').read_bytes())
  assert request['gc_fixture'] is True and (p.parent/'stdout').read_bytes()==(p.parent/'stderr').read_bytes()==b''
  if not request['plain']:
   report=json.loads((p.parent/'node-runtime/node-status.json').read_bytes())
   assert report['lifetimes']=={'admitted':1,'gc_completed':1,'resource_completed':0,'current_live':0,'open_resources':0,'tracked_instances':0,'tracked_constructors':0,'failed_initialisations':0,'failed_releases':0,'censored':0,'lost':0,'losses':{}}
   assert report['function_completions']==3 and report['span_accounting']['received']==4
 rows.append({'profile':profile.name,'literal_observations':len(paths),'ordered_calls':2,'observed_collection':True,'gc_rounds_contract':'integer 1..64, not an independently fixed timing value'})
(BASE/'independent-observation-review.json').write_text(json.dumps({'profiles':rows,'actual_applications':12,'accepted':False},indent=2)+'\n')
print(json.dumps(rows))
