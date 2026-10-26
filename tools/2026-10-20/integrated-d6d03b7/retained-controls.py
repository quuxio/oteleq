import copy,json,shutil,sys
from pathlib import Path
from unittest.mock import patch
repo=Path('/Users/sclarke/github/oteleq-qualification/2026-10-20/integrated-d6d03b7/consumer')
sys.path.insert(0,str(repo/'examples'))
import otelc_capture as c
import otelc_rust_build as rb
p=Path(__file__).resolve().parent
f=p/'rust'
plan=json.loads(next(f.glob('oteleq-run-*/plan.json')).read_text())
for module in (c,rb):assert plan['artefacts']['rust']['observer:'+Path(module.__file__).name]==c.file_digest(Path(module.__file__))
r=json.loads((f/'comparison/report.json').read_text());case=r['cases'][0]
attempt=f/'comparison'/case['case']/'instrumented_on-0'
original=attempt/'scratch/rust-bundle'
project=Path(json.loads((attempt/'working-directory.json').read_text()))
provider=Path(plan['otelc_root'])
tools={key:Path(value) for key,value in plan['tools']['rust'].items()}
env=c.environment(project,tools,'oteleq-retained-controls',provider);env['TMPDIR']=str(attempt/'scratch')
metadata=c.build_document(original/'build.json');source=Path(metadata['source'])
expected=c.rust_manifest(provider,project,source,original,tools,expected_function=case['function'],environment=env)
assert expected['selected_function']==case['function']
controls=p/'retained-controls';controls.mkdir()
def write(folder,name,d):
 (folder/name).write_text(json.dumps(d))
def edit(folder,name,keys,value):
 d=c.build_document(folder/name);target=d
 for key in keys[:-1]:target=target[key]
 target[keys[-1]]=value;write(folder,name,d)
 if name!='build.json':
  m=c.build_document(folder/'build.json');m['compiler_driver'][name.removesuffix('.json').replace('compiler-request','request')+'_sha256']=c.file_digest(folder/name);write(folder,'build.json',m)
selected=next(index for index,row in enumerate(c.build_document(original/'inventory.json')['functions']) if row['selected'])
cases=[('request-policy','compiler-request.json',('policy','functions','include'),['wrong.target']),('request-source','compiler-request.json',('sources',str(source)),'0'*64),('request-discovery','compiler-request.json',('discovery_argv',),[]),('inventory-source','inventory.json',('sources',),{}),('inventory-name','inventory.json',('functions',selected,'compiler_name'),'unrelated'),('inventory-emitted','inventory.json',('functions',selected,'emitted'),False),('inventory-role','inventory.json',('functions',selected,'selected'),False),('inventory-position','inventory.json',('functions',selected,'body_start_column'),999999),('compiler-version','build.json',('compiler','version'),'untrusted rustc'),('compiler-output','build.json',('compiler','argv',metadata['compiler']['argv'].index('-o')+1),'/outside/application'),('manifest-backend','build.json',('backend',),'llvm')]
results=[]
for name,filename,keys,value in cases:
 folder=controls/name;shutil.copytree(original,folder);edit(folder,filename,keys,value)
 with patch.object(rb,'execute',wraps=rb.execute) as executed:
  try:c.rust_manifest(provider,project,source,folder,tools,expected_function=case['function'],environment=env)
  except ValueError as error:results.append({'control':name,'refused':str(error)})
  else:raise AssertionError('accepted '+name)
  assert all(call.args[0]==[tools['rustc'],'-vV'] for call in executed.call_args_list)
for name in ('profile-bytes','profile-downgrade','linked-inventory'):
 folder=controls/name;shutil.copytree(original,folder)
 if name=='profile-bytes':write(folder,'profile.json',c.build_document(folder/'profile.json'))
 elif name=='profile-downgrade':
  m=c.build_document(folder/'build.json');m['schema_version']=1;del m['backend'];del m['compiler_driver'];write(folder,'build.json',m)
 else:
  (folder/'inventory.json').unlink();(folder/'inventory.json').symlink_to(original/'inventory.json')
 try:c.rust_manifest(provider,project,source,folder,tools,expected_function=case['function'],environment=env)
 except ValueError as error:results.append({'control':name,'refused':str(error)})
 else:raise AssertionError('accepted '+name)
assert len(results)==14
record={'actual_application_launches':0,'runtime_commit':'2e3e0561ba213d26eabd81b659d6fe8764c5a1b8','actual_retained_bundle_controls':results,'scope':'deliberately altered retained evidence; not new application runs'}
(controls/'controls.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
