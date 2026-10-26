"""Check retained real build3 helpers and deterministic old-reader negative controls."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tarfile
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
SOURCE=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-source-provider')
SDK=ROOT.parent/'go-http2-review-33d74f2/source'
sys.path[:0]=[str(SOURCE/'adapters/generation'),str(SOURCE/'examples'),str(SOURCE/'tests')]
import go_build as build
import go_files as files
from test_generation_go_source_build import fixture,write

index=json.loads((ROOT/'source-ab2de7c.json').read_text())
assert all(hashlib.sha256((SOURCE/n).read_bytes()).hexdigest()==digest for n,digest in index['files'].items())
provider=json.loads((ROOT.parent/'go-http2-review-33d74f2/source-index.json').read_text())
before={name:files.file(SDK/name)[:2] for name in provider['files']}
assert all(value[0]['sha256']==provider['files'][name] for name,value in before.items())
folder=ROOT/'hooks-retained-audit-ab2de7c';folder.mkdir(mode=0o700)
real=ROOT/'prototype-build3-03'
tools,_=files.read(SDK/'build/go-upstream/toolchain.json')
assert tools['go']=='/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go'
assert tools['weaver']==str(SDK/'build/go-upstream/bin/otelc')
assert tools['bundle_sha256']=='4a928c69ce269e37c98413c93159713fa7bcd8169c5d6b4de167305dc5ca9bb2'
settings,_=files.read(real/'settings.stdout')
raw=(real/'modules.stdout').read_text().strip();modules=[]
while raw:
 row,end=json.JSONDecoder().raw_decode(raw);modules.append(row);raw=raw[end:].lstrip()
intent=build.Intent(real/'bundle',files.freeze(real/'application'),files.freeze(SDK/'adapters/go'),'.',
 (build.Target('example.com/oteleqfixture.Add','main.go',4,1),),tools,settings,modules,
 files.freeze(ROOT/'prototype-build-01/bundle/context'))
with patch('subprocess.run',side_effect=AssertionError('retained reader executed command')),patch('subprocess.Popen',side_effect=AssertionError('reader launched target')):
 checked=build.read(intent);checked.verify()
assert not (real/'unexpected-application-start').exists()
oldindex=json.loads((ROOT/'source-262457d.json').read_text())
for name in ['adapters/generation/go_files.py','adapters/generation/go_provider.py']:
 assert index['files'][name]==oldindex['files'][name]
with tarfile.open(ROOT/'source-262457d.tar') as archive:
 raw=archive.extractfile('adapters/generation/go_build.py').read()
assert hashlib.sha256(raw).hexdigest()==oldindex['files']['adapters/generation/go_build.py']
oldpath=folder/'old_go_build.py';oldpath.write_bytes(raw)
spec=importlib.util.spec_from_file_location('old_go_build',oldpath)
old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
controls=[]
for case in ['changed_helper','changed_rules','missing_helper','extra_private_source']:
 with tempfile.TemporaryDirectory(prefix=case+'-',dir=folder) as temporary:
  current,receipt,_=fixture(Path(temporary).resolve())
  private=current.directory/'private';helper=next(private.glob('zz_*.go'))
  if case=='changed_helper':helper.write_bytes(helper.read_bytes()+b'// altered generated helper\n')
  elif case=='changed_rules':
   path=private/'otelc_rules/otelc.yaml';path.write_bytes(path.read_bytes()+b'rule_extra: {}\n')
  elif case=='missing_helper':helper.unlink()
  else:(private/'hidden.go').write_text('package main\nfunc init(){panic(1)}\n')
  receipt['private_inputs']=files.freeze(private).identities;write(current.directory/'build.json',receipt)
  arguments={**vars(current),'targets':tuple(old.Target(**vars(target)) for target in current.targets)}
  historical=old.Intent(**arguments)
  with patch('subprocess.run',side_effect=AssertionError('negative reader executed command')),patch('subprocess.Popen',side_effect=AssertionError('negative reader launched target')):
   old.read(historical).verify()
   try:build.read(current)
   except ValueError as error:reason=str(error)
   else:raise AssertionError('new reader accepted '+case)
  controls.append({'case':case,'old262_accepted':True,'current_refused':True,'reason':reason})
assert all(files.file(SDK/name)[:2]==value for name,value in before.items())
assert all(hashlib.sha256((SOURCE/n).read_bytes()).hexdigest()==digest for n,digest in index['files'].items())
result={'head':index['head'],'result':'passed','source_files_held':len(index['files']),
 'provider':provider['head'],'provider_files_bytes_and_facts_held':len(before),
 'authentic_build_schema':checked.receipt['schema_version'],'authentic_compiler_evidence_files':len(checked.evidence),
 'authentic_generated_files_independently_reproduced':4,'controls':controls,'new_target_applications':0,
 'scope':'Independent retained real build3 helper/rule compatibility and four old-reader controls. Original retained artifacts unchanged. Earlier context bytes are caller-pinned, not independently reconstructed here; complete owned/generated execution and qualification remain open.'}
(folder/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
