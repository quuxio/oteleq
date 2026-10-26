"""Recompute all retained comparisons and count real receipts after qualification."""
import hashlib
import json
from pathlib import Path
import subprocess

root=Path(__file__).parent
head='a295b0e0147e481e7950691589fc17e5f5afb8d2'
cli=root/'quux-oteleq-a295b0e'
index=json.loads((root/'source-a295b0e.json').read_bytes())
assert index['commit']==head
for name,expected in index['files'].items():
    assert hashlib.sha256((root/'source-a295b0e'/name).read_bytes()).hexdigest()==expected,name
assert hashlib.sha256(cli.read_bytes()).hexdigest()=='a4ae5102c2678907147f1782496ef7ef2238a5824cca806b38c6bccd092453bd'
all_ids=set()
corpora=[]
comparisons=[]
for runtime in ('node24','node26'):
    folder=root/('controls-a295-'+runtime)
    q=json.loads((folder/'QUALIFICATION.json').read_bytes())
    assert q['actual_applications']==348 and len(q['profiles'])==3
    assert q['cli_sha256']==hashlib.sha256(cli.read_bytes()).hexdigest()
    ids=set()
    refusals=0
    for profile in q['profiles']:
        assert profile['actual_applications']==116 and profile['source_preserved'] is True
        assert len(profile['application_identities'])==len(set(map(tuple,profile['application_identities'])))==116
        new=set(map(tuple,profile['application_identities']))
        assert not ids & new
        ids |= new
        extended=profile['retained_routes']
        assert extended['actual_applications']==52 and extended['evidence_refusals']==13
        assert extended['reduced_arguments']==[1] and extended['changed_return']==43 and extended['source_preserved'] is True
        refusals += extended['evidence_refusals']
        original=(folder/(profile['language']+'-'+profile['compiler'])/'application'/('controls'+profile['suffix']))
        source=root/'source-a295b0e/tests/qualify_node_controls.py'
        import sys
        sys.path.insert(0,str(source.parent))
        from qualify_node_controls import source as fixture_source
        assert original.read_text()==fixture_source(profile['language'])
    actual=set()
    raw_attempts=0
    for path in folder.rglob('node-source-application.json'):
        if any(part.startswith('altered-') for part in path.parts):continue
        app=json.loads(path.read_bytes())
        request=json.loads((path.parent/'node-source-request.json').read_bytes())
        actual.add((request['runtime'],app['pid']))
        raw_attempts+=1
    assert actual==ids and len(ids)==348 and not ids & all_ids
    all_ids |= ids
    count=0
    for path in sorted(folder.rglob('typed-bundle.json')):
        expected=json.loads((path.parent/'comparison.json').read_bytes())
        completed=subprocess.run([str(cli),'compare-observations',str(path)],capture_output=True,text=True,timeout=10)
        assert completed.returncode in (0,1),(path,completed.returncode,completed.stderr)
        actual=json.loads(completed.stdout)
        assert actual==expected,path
        comparisons.append({'path':str(path.relative_to(root)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'exit':completed.returncode,'verdict':actual['verdict']})
        count+=1
    corpora.append({'runtime':runtime,'actual_applications':len(ids),'raw_retained_attempts':raw_attempts,'profiles':len(q['profiles']),'actual_evidence_refusals':refusals,'typed_comparisons_recomputed':count,'qualification_sha256':hashlib.sha256((folder/'QUALIFICATION.json').read_bytes()).hexdigest()})
assert len(all_ids)==696 and sum(row['actual_evidence_refusals'] for row in corpora)==78
record={'head':head,'source_files_preserved':len(index['files']),'cli_sha256':hashlib.sha256(cli.read_bytes()).hexdigest(),'corpora':corpora,'actual_applications':len(all_ids),'actual_evidence_refusals':78,'typed_comparisons_recomputed':len(comparisons),'comparisons':comparisons,'scope':'Recomputed retained typed comparisons and literal graph/telemetry qualifier records from the exact executed a295 source. No new application launches in this audit.'}
(root/'final-audit-a295.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({key:value for key,value in record.items() if key!='comparisons'}),flush=True)
