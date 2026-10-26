from pathlib import Path
import copy,json,sys
root=Path(__file__).resolve().parent
sys.path[:0]=[str(root/'source/tests'),str(root/'source/adapters/generation'),str(root/'source/examples')]
import java_witness as w
import test_generation_java_handle_witness as h
bound=h.identity()
functions=[("reply",h.reply(),lambda v:w.reply(v,"a"*32,profile=w.HANDLE_PROFILE)),("scope",h.reply()["scope"],lambda v:w.read_scope(v,profile=w.HANDLE_PROFILE)),("final",h.final_report(),lambda v:w.final_report(v,pid=123,identity=bound))]
rows=[]
for label,value,read in functions:
 assert read(copy.deepcopy(value))==value
 refused=0
 candidates=[None,False,0,"",[],{},dict(value,unexpected=True)]
 for key in value:
  candidate=value.copy();del candidate[key];candidates.append(candidate)
 class ForeignDict(dict):pass
 candidates.append(ForeignDict(value))
 for candidate in candidates:
  try:read(candidate)
  except ValueError:refused+=1
  else:raise AssertionError((label,type(candidate)))
 rows.append({"reader":label,"valid":1,"closed_shape_refusals":refused})
print(json.dumps(rows))
