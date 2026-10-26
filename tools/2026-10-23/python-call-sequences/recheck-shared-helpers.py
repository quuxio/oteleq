"""Use each corpus's originally recorded interpreter for exact retained receipt checks."""
import datetime,json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).parent
TESTS=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-call-sequences/tests')
rows=[('python','/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider/.venv/bin/python',ROOT/'qualification-18f70b9-quiet',ROOT/'quux-oteleq-18f70b9',{}),('cpp','/Users/sclarke/github/oteleq-qualification/2026-10-22/node-source-consumer-0f05020/validation-hash-env/bin/python',ROOT.parent/'cpp-call-sequences/qualification-50f01a7',ROOT.parent/'cpp-call-sequences/quux-oteleq-50f01a7',{'historical_source_expectation':True})]
record={'started_at':datetime.datetime.now(datetime.UTC).isoformat(),'new_application_launches':0,'corpora':{}}
for language,python,folder,cli,kwargs in rows:
    code='import json;from pathlib import Path;import qualify_'+language+'_sequences as q;print(json.dumps(q.retained(Path('+repr(str(folder))+'),Path('+repr(str(cli))+'),**'+repr(kwargs)+')))'
    result=subprocess.run([python,'-B','-c',code],cwd=TESTS,env=dict(os.environ,PYTHONPATH=str(TESTS)),capture_output=True,text=True,check=False)
    (ROOT/('shared-recheck-'+language+'.stderr')).write_text(result.stderr)
    (ROOT/('shared-recheck-'+language+'.stdout')).write_text(result.stdout)
    record['corpora'][language]={'exit_code':result.returncode,'interpreter':python,'result':json.loads(result.stdout) if result.returncode==0 else None}
    assert result.returncode==0,language
record['finished_at']=datetime.datetime.now(datetime.UTC).isoformat()
(ROOT/'shared-helper-retained-recheck.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
