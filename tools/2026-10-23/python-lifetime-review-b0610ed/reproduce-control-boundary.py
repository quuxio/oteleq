"""Real SDK reproduction of a GC event arriving during the control handoff."""
import gc,json,sys,tempfile
from pathlib import Path
source=Path(__file__).parent/'source';sys.path[:0]=[str(source),str(source/'tests')]
from otelc.config import Policy
from otelc.python_sdk_process import SdkProcess
from otelc.python_runtime import PythonRuntime
from test_java_integration import Capture
from test_python_lifetime_components import Item,PythonLifetimeComponentTests
capture=Capture();sdk=None;runtime=None
try:
 with tempfile.TemporaryDirectory() as temporary:
  policy=Policy.parse({'schema_version':3,'sources':{'include':['test_python_lifetime_components.py']},'lifetimes':{'enabled':True,'include':['*']},'traces':{'enabled':False},'metrics':{'collection':True,'emission':True},'export':{'endpoint':'http://127.0.0.1:'+str(capture.server.server_port),'interval_ms':100000}})
  sdk=SdkProcess.start(policy,Path(temporary).resolve()/'sdk');runtime=PythonRuntime(policy,sdk.channel,root=source/'tests')
  helper=PythonLifetimeComponentTests();helper.runtime=runtime;helper.tracker=runtime.lifetimes
  item=Item();helper.admit(item);holder=[item];del item
  original=sdk.channel.writer.send;observed=[]
  def send(record):
   if record.get('kind')=='controls' and record['collection'] is False:
    holder.clear();gc.collect();observed.extend(event.collect for event in runtime.lifetimes._pending if hasattr(event,'collect'))
   return original(record)
  sdk.channel.writer.send=send
  runtime.controls(False,True);runtime.controls(True,True);sdk.channel.request('flush')
  runtime.close();report=sdk.wait_report()
  completed=[point.value if hasattr(point,'value') else point.as_int for request in capture.metrics for resource in request.resource_metrics for scope in resource.scope_metrics for metric in scope.metrics if metric.name=='otelc.lifetime.completed' for point in metric.sum.data_points]
  result={'commit':'b0610eda1f3192b14ba591f63cc31fd625e0fb45','collection_at_actual_gc':observed,'gc_completed':report['producer']['lifetimes']['gc_completed'],'losses':report['producer']['lifetimes']['losses'],'final_phase':report['phase'],'completed_metric_values':completed,'expected_completed_metric':1}
  print(json.dumps(result));(Path(__file__).parent/'control-boundary-reproducer.json').write_text(json.dumps(result,indent=2)+'\n')
finally:
 if sdk is not None:sdk.abort()
 capture.close()
