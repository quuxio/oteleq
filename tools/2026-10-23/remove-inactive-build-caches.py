"""Remove explicitly inventoried inactive build caches and retain coverage data."""
from pathlib import Path
import datetime,hashlib,json,os,shutil,subprocess
ROOT=Path('/Users/sclarke/github/oteleq-qualification')
DATE=ROOT/'2026-10-23'
plan=json.loads((DATE/'disk-build-cache-candidates.json').read_text())
result=subprocess.run(['lsof','-nP','-Fpn'],capture_output=True,text=True,check=True)
opened=[Path(line[1:]) for line in result.stdout.splitlines() if line.startswith('n') and line[1:].startswith(str(ROOT))]
record={'started_at':datetime.datetime.now(datetime.UTC).isoformat(),'available_bytes_before':os.statvfs(ROOT).f_bavail*os.statvfs(ROOT).f_frsize,'removed':[],'preserved_coverage':[],'skipped':[]}
receipt=DATE/'inactive-build-cache-cleanup.json'
assert not receipt.exists()
def save():receipt.write_text(json.dumps(record,indent=2)+'\n')
for row in plan['candidates']:
    path=Path(row['path'])
    assert path.is_relative_to(ROOT) and not path.is_symlink() and path.name.startswith(('target-runtime-','target-cli-'))
    if row['preserve_for_current_delivery'] or any(p==path or p.is_relative_to(path) for p in opened):
        record['skipped'].append(row);continue
    assert path.is_dir()
    for directory,_,names in os.walk(path):
        for name in names:
            item=Path(directory)/name
            if item.suffix in ('.profraw','.profdata') or name in ('lcov.info','cobertura.xml','coverage.xml','coverage.json'):
                assert item.is_file() and not item.is_symlink()
                destination=DATE/'cache-retained-coverage'/item.relative_to(ROOT)
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(item,destination)
                digest=hashlib.sha256(item.read_bytes()).hexdigest()
                assert hashlib.sha256(destination.read_bytes()).hexdigest()==digest
                record['preserved_coverage'].append({'original':str(item),'retained':str(destination),'bytes':item.stat().st_size,'sha256':digest})
    record['removing']=row;save()
    shutil.rmtree(path)
    assert not path.exists()
    record['removed'].append(row);record.pop('removing');save()
record.update(finished_at=datetime.datetime.now(datetime.UTC).isoformat(),available_bytes_after=os.statvfs(ROOT).f_bavail*os.statvfs(ROOT).f_frsize,removed_allocated_kib=sum(row['allocated_kib'] for row in record['removed']))
record['available_bytes_delta']=record['available_bytes_after']-record['available_bytes_before']
record['allocation_note']='Directory allocation sums are measured before removal. Volume free-space delta can include concurrent otelc cleanup; do not attribute that full delta solely to this task.'
save()
print(json.dumps({k:v for k,v in record.items() if k not in ('preserved_coverage','skipped','removed')},indent=2))
print(json.dumps({'removed_directories':len(record['removed']),'coverage_files_retained':len(record['preserved_coverage']),'skipped':len(record['skipped'])}))
