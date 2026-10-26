from pathlib import Path
import copy,json,sys
base=Path(__file__).resolve().parent;source=base/'source'
sys.path[:0]=[str(source/'adapters/generation'),str(source/'examples'),str(source/'tests')]
from test_generation_java_action_receipt import fixture,qualify,expected,attribute
import java_action_receipt as receipt
rows=[]
def check(label,report,message,wanted,actions=None):
 try:qualify(report,message,actions=actions);accepted=True
 except ValueError:accepted=False
 assert accepted==wanted,(label,accepted,wanted)
 rows.append({'case':label,'accepted':accepted})
for shift,wanted in ((0,False),(989,False),(990,True),(991,True),(1500,True)):
 for reversed_arrival in (False,True):
  report,message=fixture();other=copy.deepcopy(report['scopes'][0]);other.update(cookie='a'*32,sequence='2',scope_id='b'*32,trace_id='7'*32);report['scopes'].append(other)
  resource=copy.deepcopy(message.resource_spans[0])
  for group in resource.scope_spans:
   for span in group.spans:
    span.trace_id=bytes.fromhex('7'*32);span.start_time_unix_nano+=shift;span.end_time_unix_nano+=shift
    attribute(span,receipt.SCOPE).string_value='b'*32
    attribute(span,receipt.PREFIX+'context_cookie').string_value='a'*32
  message.resource_spans.append(resource)
  if reversed_arrival:message.resource_spans.reverse()
  actions=[expected(),expected(action_id='a'*64,cookie='a'*32,sequence='2',scope_id='b'*32)]
  check(f'serial-shift-{shift}-reverse-arrival-{reversed_arrival}',report,message,wanted,actions)
for kind in ('resource-loss','scope-loss','duplicate-scope','unset-scope','valid-extra-scope'):
 report,message=fixture();resource=message.resource_spans[0];scope=resource.scope_spans[0].scope
 if kind=='resource-loss':resource.resource.dropped_attributes_count=1
 elif kind=='scope-loss':scope.dropped_attributes_count=1
 else:
  item=scope.attributes.add();item.key='independent-oracle'
  if kind!='unset-scope':item.value.string_value='kept'
  if kind=='duplicate-scope':scope.attributes.append(item)
 check(kind,report,message,kind=='valid-extra-scope')
print(json.dumps({'python':sys.version.split()[0],'cases':len(rows),'accepted':sum(r['accepted'] for r in rows),'refused':sum(not r['accepted'] for r in rows),'rows':rows}))
