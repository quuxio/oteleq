"""Keep the actual owned launch context while isolating OS process operations."""
import json,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from otelc import python_benchmark as subject
from otelc.config import Policy

root=Path(__file__).parent;policy=Policy.load(root/'source/examples/otelc.toml')
valid={'phase':'closed','sdk_phase':'closed','pid':321,'sdk_pid':456,'producer_checkpoint_available':True,
       'shutdown_completed':True,'shutdown_complete':True,'shutdown_failed':False,'operation_pending':False,
       **{key:0 for key in ('handoff_incomplete','protocol_errors','reply_lost','operation_failures','export_failed','in_flight_exports','flush_failed','in_flight_flushes')},
       'producer':{'active_functions':0,'runtime_losses':{'lost':0},'handoff':{'attempted':0,'accepted':0,'lost':0},
                   'span_observation':{'sampled_started':0,'sampled_ended':0,'handed_off':0},'lifetimes':{'lost':0}},
       'traces':{'failed':0,'pending':0},'metric_collection':{'failed':0,'pending':0},
       'span_accounting':{'received':0,'sdk_exported':0,'queue_pending':0,'queue_dropped':0,'queue_evidence':'derived_after_shutdown'}}
results=[]
for fail_body in (False,True):
    order=[];owner=SimpleNamespace(pid=123,stdin=mock.Mock(),stdout=mock.Mock())
    process=SimpleNamespace(pid=321,sdk_pid=456,sdk_report=None,owner=owner)
    original=RuntimeError('controlled measured-body failure')
    def completed(*args,**options):order.append('completed');process.sdk_report=valid
    validate=subject.validate_drain
    def check(report,*args,**options):order.append('validate_none' if report is None else 'validate_report');return validate(report,*args,**options)
    with tempfile.TemporaryDirectory() as temporary, \
         mock.patch.object(subject.launch.prepared,'command',return_value=['controlled-owner']), \
         mock.patch.object(subject.launch.subprocess,'Popen',return_value=owner), \
         mock.patch.object(subject.launch,'start',return_value=process), \
         mock.patch.object(subject.launch.files,'write'), \
         mock.patch.object(subject.launch.benchmark,'stop',side_effect=lambda *a:order.append('application_stop')), \
         mock.patch.object(subject.launch.prepared,'stop_group',side_effect=lambda *a:order.append('owner_stop')), \
         mock.patch.object(subject.launch,'completed',side_effect=completed) as finalise, \
         mock.patch.object(subject,'validate_drain',side_effect=check):
        caught=None
        try:
            with subject.application(policy,Path(temporary)/'runtime',plain=False):
                if fail_body:raise original
        except BaseException as error:caught=error
    row={'body_failed':fail_body,'order':order,'completed_calls':finalise.call_count,'exception_type':None if caught is None else type(caught).__name__,
         'original_exception_preserved':caught is original,'sdk_report_available':process.sdk_report is not None}
    results.append(row)
assert results[0]['completed_calls']==1 and results[0]['exception_type'] is None
assert results[1]['completed_calls']==1 and results[1]['exception_type']=='RuntimeError' and results[1]['original_exception_preserved']
(root/'real-manager-probe.json').write_text(json.dumps({'application_started':False,'results':results},indent=2)+'\n')
print(json.dumps(results))
