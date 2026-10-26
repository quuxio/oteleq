"""Check the exact frozen Go helper revision on both supported Python versions."""
from pathlib import Path
import hashlib,json,os,subprocess,time
root=Path(__file__).resolve().parent
source=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-source-provider')
index=json.loads((root/'source-ab2de7c.json').read_text())
env={**os.environ,'PYTHONPATH':os.pathsep.join(str(source/p) for p in ['tests','adapters/generation','examples']),'PYTHONDONTWRITEBYTECODE':'1'}
results=[]
for version in ['312','314']:
 python=root.parent/'python-live-metrics'/('env-'+version)/'bin/python'
 data=root/('hooks-final-'+version+'.coverage')
 argv=[str(python),'-m','coverage','run','--data-file='+str(data),'--source=go_provider,go_files,go_build,go_hooks,go_prepared,go_health','-m','unittest','-v','test_generation_go_hooks','test_generation_go_source_build','test_generation_go_prepared','test_generation_go_files','test_generation_go_health']
 started=time.monotonic()
 with (root/('hooks-final-'+version+'.log')).open('xb') as out:
  run=subprocess.run(argv,cwd=source,env=env,stdout=out,stderr=subprocess.STDOUT)
 report=root/('hooks-final-'+version+'.json')
 coverage=subprocess.run([str(python),'-m','coverage','json','--data-file='+str(data),'-o',str(report)],cwd=source,env=env,capture_output=True,text=True)
 assert coverage.returncode==0,coverage.stderr
 statements={n:v['summary']['percent_covered'] for n,v in json.loads(report.read_text())['files'].items()}
 held=all(hashlib.sha256((source/n).read_bytes()).hexdigest()==digest for n,digest in index['files'].items())
 result={'head':index['head'],'python':version,'exit_code':run.returncode,'seconds':round(time.monotonic()-started,3),'tests':53,'source_files_held':len(index['files']) if held else 0,'statement_percent':statements}
 results.append(result)
 (root/'hooks-final-results.json').write_text(json.dumps(results,indent=2)+'\n')
 print(json.dumps(result),flush=True)
 assert run.returncode==0 and held and all(value>=80 for value in statements.values())
