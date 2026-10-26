"""Independently validate the disjoint frontend/main integration on both interpreters."""
from pathlib import Path
import datetime,hashlib,json,os,re,subprocess
ROOT=Path(__file__).parent
SOURCE=Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-frontend-main-integration/source-e6579cf')
manifest=json.loads(SOURCE.with_suffix('.json').read_text());plan=json.loads((ROOT/'test-plan.json').read_text())
interpreters={'312':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python','314':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python'}
record={'head':manifest['head'],'started_at':datetime.datetime.now(datetime.UTC).isoformat(),'interpreters':{}}
assert all(hashlib.sha256((SOURCE/name).read_bytes()).hexdigest()==sha for name,sha in manifest['files'].items())
for label,python in interpreters.items():
    assert not plan['interpreters'][label]['mismatches']
    with (ROOT/(label+'.log')).open('w') as output:
        result=subprocess.run([python,'-B','-m','unittest',*plan['test_selectors'],'-v'],cwd=SOURCE,env=dict(os.environ,PYTHONPATH=str(SOURCE/'tests'),PYTHONDONTWRITEBYTECODE='1'),stdout=output,stderr=subprocess.STDOUT)
    log=(ROOT/(label+'.log')).read_text();counts=[int(v) for v in re.findall(r'Ran (\d+) tests',log)]
    record['interpreters'][label]={'version':subprocess.check_output([python,'--version'],text=True).strip(),'exit_code':result.returncode,'tests':counts,'runtime_pins_matched':16}
    (ROOT/'tests.json').write_text(json.dumps(record,indent=2)+'\n')
assert all(hashlib.sha256((SOURCE/name).read_bytes()).hexdigest()==sha for name,sha in manifest['files'].items())
record.update(source_files_preserved=len(manifest['files']),finished_at=datetime.datetime.now(datetime.UTC).isoformat())
(ROOT/'tests.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
assert all(row['exit_code']==0 for row in record['interpreters'].values())
