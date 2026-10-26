import json,sys
from pathlib import Path
repo=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-rust-compiler')
sys.path.insert(0,str(repo/'tests'))
import qualify_rust_semantics as q
from qualify_generation import command
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest as Decoder
p=Path(__file__).resolve().parent
provider=Path('/Users/sclarke/github/otelc-qualification/2026-10-20/rust-public-compiler/candidate-50635ef/provider')
tools={'rustc':Path('/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin/rustc')}
results=[]
for kind,folder in [('semantics',p/'public-semantics-corrected/semantics'),('aliases',p/'public-aliases-final/aliases')]:
 data=json.loads((folder/'observations.json').read_text());case=data['case']
 assert set(case)=={'baseline','instrumented_on'} and all(len(rows)==2 for rows in case.values())
 for lane,rows in case.items():
  for index,attempt in enumerate(rows):
   f=folder/(lane+'-'+str(index));project=f/'project';source=project/('semantics.rs' if kind=='semantics' else 'main.rs')
   expected=q.semantic_oracle(source.read_text()) if kind=='semantics' else {'first':28,'second':28}
   assert expected==data['oracle']==json.loads((f/'stdout').read_bytes())
   assert (f/'stderr').read_bytes()==b''
   assert attempt['source_sha256_before']==attempt['source_sha256_after']==q.capture.file_digest(source)
   assert attempt['channels']['stdout']==list((f/'stdout').read_bytes()) and attempt['channels']['stderr']==[]
   manifest=json.loads((f/'http-capture.json').read_text());assert not manifest['errors']
   bodies=[(row['path'],(f/row['file']).read_bytes()) for row in manifest['bodies']]
   if lane=='baseline':assert not bodies
   else:
    services={a.value.string_value for path,body in bodies if path==q.capture.TRACE_PATH for rs in Decoder.FromString(body).resource_spans for a in rs.resource.attributes if a.key=='service.name'}
    assert len(services)==1
    service=services.pop();assert service.startswith('oteleq-rust-semantic-')
    runtime=q.capture.build_document(f/'runtime.json')
    assert q.runtime_witness(bodies,runtime,q.SEMANTIC_NAMES if kind=='semantics' else q.ALIAS_NAMES,service,Decoder,kind)==attempt['witness']
    files=[source] if kind=='semantics' else [source,project/'shared.rs',project/'first/shared.rs',project/'second/shared.rs']
    env=q.capture.environment(project,tools,service,provider)
    actual=q.verify_bundle(provider,project,source,f/'bundle',tools,env,q.SEMANTIC_NAMES if kind=='semantics' else q.ALIAS_NAMES,{str(path):q.capture.file_digest(path) for path in files})
    assert actual==json.loads((f/'provenance.json').read_text())
 bundle=folder/'bundle.json';bundle.write_text(json.dumps(q.comparison_bundle(folder,kind,case,data['oracle']),indent=2)+'\n')
 command([p/'quux-oteleq','compare-workload',bundle],folder,'comparison-final')
 results.append({'workload':kind,'actual_application_launches':4,'raw_folder':str(folder.relative_to(p)),'comparator_exit':0})
record={'runtime_commit':'20b0e9856e6f7f2e0e5df66085580ca7741ab1d8','provider_commit':'50635ef0eccfe063eddf164a9e82520a78f2c6f1','accepted_application_launches':8,'workloads':results,'qualifier_sha256':q.capture.file_digest(Path(q.__file__)),'revalidation_sha256':q.capture.file_digest(Path(__file__)),'scope':'independent retained-byte revalidation and actual Rust comparator; no application reruns'}
(p/'public-qualification.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
