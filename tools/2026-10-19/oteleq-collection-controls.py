from pathlib import Path
import copy,hashlib,json,subprocess,sys
from types import SimpleNamespace as NS
sys.path.insert(0,'/private/tmp/oteleq-review-work/examples')
import otelc_capture as capture
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest as Decoder

manifest_path=Path('/private/tmp/otelc-python-collection-final-manifest.json')
manifest=json.loads(manifest_path.read_text());root=Path(manifest['root'])
def verify_provider(expected):
    if subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()!=expected['provider_commit']:
        raise ValueError('frozen provider head changed')
    for name,digest in expected['sha256'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:raise ValueError('frozen provider content changed: '+name)
    interpreter=expected['interpreter']
    if hashlib.sha256(Path(interpreter['path']).read_bytes()).hexdigest()!=interpreter['sha256']:raise ValueError('interpreter changed')
verify_provider(manifest)
p=Path(sys.argv[1])/'python'
spec=json.loads((p/'corpus.json').read_text())['fixture']
bundle=json.loads((p/'bundle.json').read_text());comparison=json.loads((p/'comparison.json').read_text())
assert comparison['verdict']=='equivalent_observed'
assert len(bundle['cases'][0]['baseline'])==len(bundle['cases'][0]['instrumented_on'])==2
for lane in ('baseline','instrumented_on'):
    for index,attempt in enumerate(bundle['cases'][0][lane]):
        folder=p/f'{lane}-{index}'
        assert attempt['termination']=={'kind':'exit','code':0} and attempt['capture_complete']
        capture.otelc_collection.expected_channels(NS(stdout=(folder/'stdout').read_bytes(),stderr=(folder/'stderr').read_bytes()),spec['channels'])
        assert attempt['source_sha256_before']==attempt['source_sha256_after']==manifest['sha256'][spec['source']]
        http=json.loads((folder/'http-capture.json').read_text());assert not http['errors']
        if lane=='baseline':assert not http['bodies'] and attempt['witness'] is None
        else:
            commands=json.loads((folder/'commands.json').read_text());service=commands['service']
            bodies=[(body['path'],(folder/body['file']).read_bytes()) for body in http['bodies']]
            report=json.loads((folder/'runtime.json').read_text())
            assert capture.witness(bodies,report,spec,service,Decoder,'python')==attempt['witness']

folder=p/'instrumented_on-0';service=json.loads((folder/'commands.json').read_text())['service']
http=json.loads((folder/'http-capture.json').read_text())
original=[(body['path'],(folder/body['file']).read_bytes()) for body in http['bodies']]
status=json.loads((folder/'runtime.json').read_text())
controls=p.parent/'controls';controls.mkdir()
results=[]
def reject(name,callback,document):
    destination=controls/name;destination.mkdir()
    (destination/'control.json').write_text(json.dumps({'kind':'deliberately altered retained observations; not another target execution',**document},indent=2)+'\n')
    try:callback()
    except ValueError as error:results.append({'name':name,'rejected':True,'reason':str(error)})
    else:raise AssertionError('invalid control passed: '+name)
def changed_spans(change):
    bodies=[];changed=False
    for path,raw in original:
        if path=='/v1/traces':
            message=Decoder.FromString(raw)
            for resource in message.resource_spans:
                for scope in resource.scope_spans:
                    for index,node in enumerate(scope.spans):
                        if node.name==spec['collection']['span'] and not changed:
                            change(scope.spans,index,node);changed=True;break
            raw=message.SerializeToString()
        bodies.append((path,raw))
    assert changed
    return bodies
changes={
 'missing_creation_link':lambda nodes,index,node:node.ClearField('links'),
 'wrong_creation_link':lambda nodes,index,node:setattr(node.links[0],'span_id',b'z'*8),
 'missing_collection_span':lambda nodes,index,node:nodes.pop(index),
 'wrong_collection_boundary':lambda nodes,index,node:setattr(next(a for a in node.attributes if a.key=='otelc.lifetime.boundary').value,'string_value','close'),
}
for name,change in changes.items():
    bodies=changed_spans(change)
    reject(name,lambda:capture.witness(bodies,status,spec,service,Decoder,'python'),{'expected':'incomplete telemetry cannot pass'})
    for index,(_,raw) in enumerate(bodies):(controls/name/f'otlp-{index}.protobuf').write_bytes(raw)
for name,key,value in [('missing_completion','completed',2),('censored_collection','censored',1),('live_instance','current_live',1),('pending_constructor','active_constructors',1),('failed_initialisation','failed_initialisations',1),('malformed_counter','completed',True),('lifetime_loss','losses',{'incomplete':1})]:
    report=copy.deepcopy(status);report['lifetimes'][key]=value
    reject(name,lambda:capture.witness(original,report,spec,service,Decoder,'python'),{'runtime':report})
for name,stdout,stderr in [('identical_wrong_stdout',b'collections=2; value=6; layouts=true\n',b''),('unexpected_stderr',b'collections=3; value=6; layouts=true\n',b'warning\n')]:
    reject(name,lambda:capture.otelc_collection.expected_channels(NS(stdout=stdout,stderr=stderr),spec['channels']),{'stdout_hex':stdout.hex(),'stderr_hex':stderr.hex(),'applies_to_both_lanes':True})
identities=capture.artefacts(root,'python',capture.selected_tools(root,'python'))
wrong=identities.copy();wrong['target/debug/quux-otelc']='0'*64
reject('provider_content_identity_mismatch',lambda:capture.stable(root,'python',capture.selected_tools(root,'python'),wrong),{'expected_identity':wrong['target/debug/quux-otelc']})
wrong=copy.deepcopy(manifest);wrong['provider_commit']='0'*40
reject('provider_head_mismatch',lambda:verify_provider(wrong),{'expected_head':wrong['provider_commit']})
verify_provider(manifest)
summary={'claim':'equivalence over these tests and observations','provider_commit':manifest['provider_commit'],'provider_sha256':manifest['sha256'],'interpreter':manifest['interpreter'],'manifest_files_unchanged':len(manifest['sha256']),'baseline_attempts':2,'instrumented_attempts':2,'spans_per_on_run':4,'roots_per_on_run':4,'function_calls_per_on_run':1,'completed_collections_per_on_run':3,'errors_per_on_run':0,'all_exits':0,'zero_losses_pending_live_censored':True,'controls':results}
(p.parent/'qualification.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({'provider':summary['provider_commit'],'matching_attempts':4,'controls_rejected':len(results),'provider_files_unchanged':len(manifest['sha256'])}))
