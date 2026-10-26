"""Independent bounded source and retained compiler-only result review."""
import hashlib,json,os,subprocess,sys,time,zipfile
from pathlib import Path,PurePosixPath
BASE=Path('/Users/sclarke/github/oteleq-qualification');ROOT=Path('/Users/sclarke/github/otelc-qualification/work/rust-lifetime-discovery')
OUT=BASE/'2026-10-25/sdk-rust-lifetime-discovery-6dcaa2b-review';OUT.mkdir()
v=json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/rust-lifetime-discovery/source.json').read_text())
def digest(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def held():
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==v['head']
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
 for name,wanted in v['source_facts'].items():
  p=ROOT/name;s=p.lstat()
  assert [digest(p),s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]==wanted,name
  assert [s.st_uid,s.st_gid,s.st_nlink]==v['extra_facts'][name],name
 assert digest(v['archive'])==v['archive_sha256']
held();checks=[];env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(ROOT)+':'+str(ROOT/'tests'))
def run(label,argv):
 tick=time.monotonic()
 with (OUT/(label+'.log')).open('wb') as f:r=subprocess.run(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=60)
 checks.append({'label':label,'argv':argv,'returncode':r.returncode,'seconds':time.monotonic()-tick});print(label,r.returncode,flush=True);assert r.returncode==0
for version in ('312','314'):
 python=str(BASE/f'2026-10-24/python-live-metrics/env-{version}/bin/python');cov=str(OUT/('coverage-'+version))
 run('python'+version,[python,'-m','coverage','run','--data-file='+cov,'--source=otelc.rust_lifetimes,ci.rust_sonar','-m','unittest','test_rust_lifetimes','test_rust_sonar','-v'])
 run('coverage'+version,[python,'-m','coverage','report','--data-file='+cov,'--show-missing','--fail-under=80'])
run('markdown',['/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node',str(BASE/'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js'),'README.md','docs/rust-drop-engine.md','docs/rust-lifetime-discovery.md'])
run('rustfmt',['/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin/rustfmt','--edition','2024','--check','native/rust/compiler/src/main.rs'])
run('diff-check',['git','diff',v['base'],v['head'],'--check'])
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from otelc import rust_lifetimes as reader
from ci import rust_lifetime_cases as fixture
artifact=BASE/'2026-10-25/sdk-rust-lifetime-discovery-6dcaa2b-artifact.zip'
archive_digest='698ae8056e8e918f2f465b358986a7677025b2d42e4786cf8de7b9a2fa0605a2'
assert digest(artifact)==archive_digest and artifact.stat().st_size==22887848
commands=[];index={}
with zipfile.ZipFile(artifact) as z:
 names=z.namelist();assert len(names)==len(set(names))==78
 assert z.read('head.txt').decode().strip()==v['head']
 for item in z.infolist():
  with z.open(item) as stream:index[item.filename]={'bytes':item.file_size,'sha256':hashlib.file_digest(stream,'sha256').hexdigest()}
 assert not any(name.endswith('-application') for name in names)
 tool=json.loads(z.read('profiles/lifetime-discovery/compiler-inputs.json'))
 compiler,= [name for name in tool if name.endswith('/otelc-rust-compiler')]
 assert index['compiler/debug/otelc-rust-compiler']['sha256']==tool[compiler]
 result=json.loads(z.read('profiles/lifetime-discovery-result.json'))
 assert result==dict(selected=4,tests_run=4,skipped=0,failures=0,errors=0,successful=True,application_launches=0)
 assert '8 passed; 0 failed; 0 ignored' in z.read('compiler-tests.log').decode()
 assert 'warning:' not in z.read('clippy.log').decode()
 roots=set()
 for name in sorted(n for n in names if n.endswith('.request.json')):
  stem=name.removesuffix('.request.json');prefix=str(PurePosixPath(name).parent)
  request=json.loads(z.read(name));original=json.loads(z.read(prefix+'/original-inputs.json'))
  root=Path(request['root']);roots.add(str(root));inputs={}
  for old,wanted in original.items():
   relative=Path(old).relative_to(root).as_posix();raw=z.read(prefix+'/application/'+relative)
   assert hashlib.sha256(raw).hexdigest()==wanted
   assert raw==({'app.rs':fixture.APP,'model.rs':fixture.MODEL}[relative]).encode()
   inputs[old]=raw
  result=json.loads(z.read(stem+'.result.json'));argv=result['arguments']
  assert argv[0]==compiler and argv[1]==request['entry'] and request['entry']==str(root/'app.rs')
  assert argv[2:6]==['--crate-name','discovery','--edition=2024','--sysroot']
  assert argv[6]=='/home/runner/.rustup/toolchains/1.98.1-x86_64-unknown-linux-gnu'
  assert argv[7] in ('-Copt-level=0','-Copt-level=2','-Copt-level=3') and argv[8]=='-o'
  assert Path(argv[9]).name==PurePosixPath(stem).name+'-application'
  assert z.read(stem+'.stdout')==b''
  assert all(original[k]==val for k,val in request['sources'].items())
  if result['exit_code']==0:
   assert request['sources']==original and request['selected']==[]
   document=json.loads(z.read(stem+'.inventory.json'))
   assert document['sources']==original
   if request['mode']=='lifetime-inspect':
    copy=OUT/(PurePosixPath(prefix).name+'-'+PurePosixPath(stem).name+'.inventory.json')
    copy.write_bytes(z.read(stem+'.inventory.json'))
    checked=reader.inventory(copy,root,original,inputs)
    assert checked['pointer_width']==64 and checked['source_complete'] is False and checked['instrumentation_complete'] is False
    rows=[row for body in checked['bodies'] for row in body['locals']]
    sites=[site for body in checked['bodies'] for site in body['sites']]
    assert {'struct','enum','union'} <= {row['kind'] for row in rows}
    assert {'construction','move','copy','drop','call_argument','call_return'} <= {site['kind'] for site in sites}
    assert any(row['size']==0 and row['needs_drop'] for row in rows)
    assert any(row['layout_error'] and row['size'] is None and row['alignment'] is None for row in rows)
    assert any(site['cleanup'] for site in sites if site['kind']=='drop')
    assert any(site['projected'] for site in sites)
    assert {'const','async','expanded'} <= {skip['reason'] for skip in checked['skipped']}
    for row in rows:
     if row['compiler_type'].endswith('::Item'):
      assert row['size']==row['alignment']==4 and row['needs_drop'] is True
    assert not any(row['rendered_type'].endswith('Alias') for row in rows)
   else:
    assert request['mode']=='inspect' and document['kind']=='otelc.rust.compiler-inventory' and 'bodies' not in document
  else:
   assert stem+'.inventory.json' not in names
   stderr=z.read(stem+'.stderr')
   assert b'invalid Rust compiler component request' in stderr or b'compiler read an unbound Rust source' in stderr
  commands.append({'request':name,'mode':request['mode'],'exit_code':result['exit_code'],'optimisation':argv[7]})
 assert len(roots)==4 and len(commands)==7
 assert sum(row['exit_code']==0 for row in commands)==5
 rust=json.loads(z.read('rust-coverage.json'));files=[f for data in rust['data'] for f in data['files'] if f['filename'].endswith('/lifetimes.rs')]
 assert len(files)==1 and files[0]['summary']['lines']['count']==210 and files[0]['summary']['lines']['covered']==201
 python=json.loads(z.read('python-coverage.json'))['files']
 assert python['otelc/rust_lifetimes.py']['summary']['covered_lines']==119
 assert python['otelc/rust_lifetimes.py']['summary']['num_statements']==119
 assert python['ci/rust_lifetime_cases.py']['summary']['covered_lines']==111
 assert python['ci/rust_lifetime_cases.py']['summary']['num_statements']==113
(OUT/'retained-index.json').write_text(json.dumps(index,indent=2)+'\n')
held()
r={'head':v['head'],'base':v['base'],'status':'clear for bounded discovery and selection review','findings':[],'checks':checks,'source_files_preserved':len(v['source_facts']),'uid_gid_nlink_preserved':True,'archive_sha256':v['archive_sha256'],'sdk_builds':0,'compiler_builds':0,'local_application_launches':0,'retained_hosted':{'run':40216309337,'artifact':12607138461,'archive_sha256':archive_digest,'archive_bytes':22887848,'members':78,'all_member_bytes_hashed':True,'request_tests':8,'discovery_cases':4,'original_compiler_commands':commands,'application_launches':0,'compiler_map_matches_original_seal':True,'rust_lifetime_lines':{'covered':201,'total':210},'python_selector_statements':{'covered':119,'total':119},'python_cases_statements':{'covered':111,'total':113}},'scope':'Frozen source/literal selection review and historical compiler-only retained bytes; original runner paths stay metadata, not newly certified filesystem/product identities','limits':['No local compiler/SDK builds or application execution','No automatic MIR insertion, public lifetime launch, new frozen shipping provider or full SDK/runtime admission','Full protected checks, runtime/coverage and independent oteleq lifetime qualification remain required']}
(OUT/'review.json').write_text(json.dumps(r,indent=2)+'\n');print('REVIEW',digest(OUT/'review.json'),flush=True)
