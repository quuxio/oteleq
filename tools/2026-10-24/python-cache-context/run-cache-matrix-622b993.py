"""Actual ordinary-loader decisions with complete scalar oracles on a frozen CLI."""
import hashlib,json,os,py_compile,subprocess,sys
from pathlib import Path
R=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-cache-context')
LABEL=sys.argv[1];F=R/('cache-matrix-'+LABEL+'-01');F.mkdir(mode=0o700)
CLI=R/'runtime-622b993/quux-oteleq';PROVIDER=R/('provider-ce4cf74-'+LABEL)
ENV={**os.environ,'OTELEQ_PYTHON':sys.executable,'OTELEQ_CLI':str(CLI),'PYTHONDONTWRITEBYTECODE':'1'}
OLD='counter=0\ndef workload(value:int)->int:\n global counter\n counter+=value\n return value*2+3\n'
NEW=OLD.replace('value*2+3','value*2+4');TIME=1_700_000_000_123456789
MODES={'timestamp':py_compile.PycInvalidationMode.TIMESTAMP,'checked':py_compile.PycInvalidationMode.CHECKED_HASH,'unchecked':py_compile.PycInvalidationMode.UNCHECKED_HASH}
def facts(source):
 return {str(p.relative_to(source)):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'mtime_ns':p.stat().st_mtime_ns,'mode':p.stat().st_mode,'inode':p.stat().st_ino} for p in source.rglob('*') if p.is_file()}
def command(folder,name,args):
 result=subprocess.run(list(map(str,args)),env=ENV,capture_output=True,timeout=180,check=False)
 for suffix,content in [('stdout',result.stdout),('stderr',result.stderr),('exit',str(result.returncode).encode()+b'\n')]: (folder/(name+'.'+suffix)).write_bytes(content)
 return result
rows=[]
for name in ('timestamp','checked','unchecked','missing','stale-timestamp','stale-checked','older-unchecked','invalid-magic'):
 folder=F/name;folder.mkdir();source=folder/'application';source.mkdir();target=source/'target.py';target.write_text(OLD);os.utime(target,ns=(TIME,TIME))
 kind=name.removeprefix('stale-').removeprefix('older-');kind='timestamp' if kind=='invalid-magic' else kind
 if kind!='missing':
  cached=Path(py_compile.compile(str(target),doraise=True,invalidation_mode=MODES[kind]))
  if name.startswith(('stale-','older-')):
   target.write_text(NEW);updated=TIME+2_000_000_000 if name=='stale-timestamp' else TIME;os.utime(target,ns=(updated,updated))
  elif name=='invalid-magic':cached.write_bytes(b'BAD!'+cached.read_bytes()[4:])
 before=facts(source);value=18 if name.startswith('stale-') else 17
 policy=folder/'equivalence.toml';policy.write_text('schema_version=1\nlanguages=["python"]\n[generation]\nseed=123\ncases_per_function=1\n[adapters.python]\nbackend="prepared"\nprofile="python-native-cache-origins-v3"\n[functions]\ninclude=["*workload*"]\n[[fixtures]]\nfunction="*workload*"\ncases=[[7]]\nexpected_baseline={kind="return_value",value={kind="integer",type="python.int",value="'+str(value)+'",signed=true}}\n[limits]\ncase_timeout_ms=30000\n')
 planned=command(folder,'plan',[CLI,'plan','--source',source,'--otelc-root',PROVIDER,'--workspace-parent',folder,'--config',policy]);assert planned.returncode==0,planned.stderr
 workspace=Path(planned.stdout.decode().strip());generated=command(folder,'generate',[CLI,'generate','--workspace',workspace]);assert generated.returncode==0,generated.stderr
 ran=command(folder,'run',[CLI,'run','--workspace',workspace,'--report-dir',folder/'comparison']);report=json.loads((folder/'comparison/report.json').read_text());assert report['source_preserved'] and len(report['cases'])==1 and not report['blocked']
 row={'mode':name,'exit_code':ran.returncode,'workspace':str(workspace),'source_cache_facts_preserved':facts(source)==before,'error':report['cases'][0].get('error'),'actual_launches':0,'matches':[]}
 assert row['source_cache_facts_preserved']
 for p in (folder/'comparison').glob('*/python-runtime'): assert False,str(p)
 for path in (folder/'comparison').glob('*/*/python-verified-origins.json'):
  d=json.loads(path.read_text());row['actual_launches']+=1;row['matches'].extend(m['input_binding'] for s in d['selected'] for m in s['matches'])
 if ran.returncode==0:
  def graph(counter,result=False):
   roots={'arguments':{'ref':0},'global:counter':{'type':'int','value':str(counter)}}
   if result:roots['result']={'type':'int','value':str(value)}
   return {'roots':roots,'nodes':[{'type':'builtins.list','items':[{'type':'int','value':'7'}]}]}
  expected={'before':graph(0),'after':graph(7),'outcome':{'kind':'return','value':graph(7,True)}}
  actual=list((folder/'comparison').glob('*/*/observation'));assert len(actual)==4
  assert all(json.loads(p.read_text())==expected for p in actual)
  binding='source-compiler' if name in ('missing','stale-timestamp','stale-checked','invalid-magic') else 'cache-read'
  assert row['actual_launches']==4 and row['matches'] and set(row['matches'])=={binding},row
 rows.append(row);(F/'progress.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(row),flush=True)
(F/'result.json').write_text(json.dumps({'head':'622b9935fea0f11afcaf7b1c678904c7d951ee34','rows':rows,'all_passed':all(r['exit_code']==0 for r in rows)},indent=2)+'\n')
