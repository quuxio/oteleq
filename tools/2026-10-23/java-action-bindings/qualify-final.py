"""Run the final frozen consumer bridge against one frozen real SDK compiler."""
import hashlib,json,os,subprocess
from pathlib import Path
root=Path(__file__).resolve().parent
head='232772ec8939fe99c230c1ae8512736f287e4d8e'
source=root/('source-'+head[:7]);meta=json.loads(source.with_suffix('.json').read_text())
assert meta['head']==head
sdk=Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-action-review-7815a84/source-7815a84')
pythons={'312':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python','314':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python'}
assert all(hashlib.sha256((source/name).read_bytes()).hexdigest()==sha for name,sha in meta['files'].items())
record={'head':head,'source_files':len(meta['files']),'runs':[]}
environment={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','OTELC_JAVA':'/opt/homebrew/opt/openjdk@21/bin/java','OTELC_JAVAC':'/opt/homebrew/opt/openjdk@21/bin/javac','PATH':'/opt/homebrew/opt/openjdk@21/bin:/opt/homebrew/bin:/usr/bin:/bin'}
for runtime,python in pythons.items():
    report=root/('actual-'+head[:7]+'-'+runtime);log=report.with_suffix('.log')
    command=[python,'tests/qualify_java_action_bindings.py','--otelc-root',str(sdk),'--report-dir',str(report)]
    with log.open('wb') as stream:
        result=subprocess.run(command,cwd=source,env=environment,stdout=stream,stderr=subprocess.STDOUT)
    assert result.returncode==0,(runtime,log)
    qualification=report/'qualification.json';data=json.loads(qualification.read_text())
    assert len(data['cases'])==3 and [case['accepted'] for case in data['cases']]==[True,False,False]
    assert data['application_started'] is False and data['sources_preserved'] is True
    assert all(hashlib.sha256((source/name).read_bytes()).hexdigest()==sha for name,sha in meta['files'].items())
    row={'runtime':runtime,'command':command,'exit_code':result.returncode,'cases':3,'application_started':False,'sources_preserved':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),'qualification_sha256':hashlib.sha256(qualification.read_bytes()).hexdigest()}
    record['runs'].append(row);(root/('actual-'+head[:7]+'.json')).write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(row),flush=True)
