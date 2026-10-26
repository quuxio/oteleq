"""Repeat the maintained retained audit twice and prove that no target was relaunched."""
import hashlib,json,subprocess,sys
from pathlib import Path
r=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-cache-context');repo=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-cache-context');label=sys.argv[1]
folder=r/('maintained-matrix-'+label+'-01');output=r/('final-retained-'+label+'-a9bfb86');output.mkdir(mode=0o700)
def starts():return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('python-application-start.json')}
before=starts();assert len(before)==32
for index in (1,2):
 command=[sys.executable,'-B',str(repo/'tests/qualify_python_caches.py'),'--recheck','--otelc-root',str(r/('provider-ce4cf74-'+label)),'--report-dir',str(folder),'--cli',str(r/'runtime-95d94ae/quux-oteleq')]
 result=subprocess.run(command,cwd=repo,capture_output=True,check=False,timeout=120)
 (output/(str(index)+'.stdout')).write_bytes(result.stdout);(output/(str(index)+'.stderr')).write_bytes(result.stderr);(output/(str(index)+'.exit')).write_text(str(result.returncode)+'\n')
 assert result.returncode==0,(index,result.stderr[-1200:]);assert starts()==before
 print('Retained pass',index,'complete;32 original application starts held,0 new applications.',flush=True)
 (output/('retained-audit-'+str(index)+'.json')).write_bytes((folder/'retained-audit.json').read_bytes())
(output/'result.json').write_text(json.dumps({'qualifier_head':'a9bfb86e0fb6998619e18153e312a9617c228c5d','runtime_head':'95d94aed4fa7e1319392cd8013003cefbcc76888','retained_audit_passes':2,'existing_applications':32,'new_applications':0,'all_start_record_hashes_held':True},indent=2)+'\n')
