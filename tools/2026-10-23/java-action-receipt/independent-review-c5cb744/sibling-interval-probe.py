from pathlib import Path
import copy,json,sys
base=Path(__file__).resolve().parent
source=base/'source'
sys.path[:0]=[str(source/'adapters/generation'),str(source/'examples'),str(source/'tests')]
from test_generation_java_action_receipt import fixture,qualify
results=[]
for overlap in (False,True):
 report,message=fixture(recursive=True)
 scope=report['scopes'][0]
 role=message.resource_spans[0].scope_spans[0].spans[2]
 method=message.resource_spans[0].scope_spans[1].spans[1]
 role.end_time_unix_nano=350
 method.end_time_unix_nano=300
 other_role=copy.deepcopy(role);other_method=copy.deepcopy(method)
 other_role.span_id=bytes.fromhex('7'*16)
 other_method.span_id=bytes.fromhex('8'*16)
 other_method.parent_span_id=other_role.span_id
 other_role.start_time_unix_nano=200 if overlap else 400
 other_role.end_time_unix_nano=700
 other_method.start_time_unix_nano=250 if overlap else 450
 other_method.end_time_unix_nano=650
 message.resource_spans[0].scope_spans[0].spans.append(other_role)
 message.resource_spans[0].scope_spans[1].spans.append(other_method)
 for key in ('started_ids','ended_ids','exported_ids'):scope[key].extend(['7'*16,'8'*16])
 scope['target_entries']='3'
 try:
  value=qualify(report,message)
  accepted=True
 except ValueError as error:
  value={'error':str(error)};accepted=False
 results.append({'overlapping_sibling_calls':overlap,'accepted':accepted,'expected_acceptance':not overlap,'result':value})
print(json.dumps({'head':'c5cb744213b98555476fe87a957f29319c4e69f3','results':results}))
