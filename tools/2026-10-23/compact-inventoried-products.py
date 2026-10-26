"""Apply the already characterised final exact-duplicate plan and verify every product."""
from pathlib import Path
import datetime,json,os,runpy,subprocess
ROOT=Path(__file__).parent
helper=runpy.run_path(str(ROOT/'clone-retained-cpp-products.py'))
sha=helper['digest'];metadata=helper['metadata'];xattrs=helper['xattrs']
plan_path=ROOT/'other-inactive-product-cow-plan.json'
rows=json.loads(plan_path.read_text())['products']
receipt=ROOT/'other-inactive-product-cow-compaction.json'
assert not receipt.exists()
opened=subprocess.run(['lsof','-nP','-Fpn'],capture_output=True,text=True,check=True)
active={line[1:] for line in opened.stdout.splitlines() if line.startswith('n')}
assert not {row['path'] for row in rows}.intersection(active)
record={'started_at':datetime.datetime.now(datetime.UTC).isoformat(),'plan_sha256':sha(plan_path),'available_bytes_before':helper['available'](),'clones':[],'scope':'Explicitly characterised inactive retained Go/Rust/helper products and opaque Go build-cache blobs. Sources, providers, module/dependency inputs and current caches excluded.'}
canonical={}
for row in rows:
    p=Path(row['path']);assert p.is_relative_to(ROOT.parent)
    before=metadata(p);attrs=xattrs(p)
    assert sha(p)==row['sha256']
    key=(p.name,row['sha256'],before['mode'],before['uid'],before['gid'],attrs)
    if key not in canonical:canonical[key]=p;continue
    donor=canonical[key];tmp=p.with_name('.'+p.name+'.cow-'+str(os.getpid()))
    assert not tmp.exists()
    record['pending']={'path':str(p),'before':before,'sha256':row['sha256']}
    receipt.write_text(json.dumps(record,indent=2)+'\n')
    try:
        if helper['lib'].clonefile(os.fsencode(donor),os.fsencode(tmp),1)!=0:raise OSError('clonefile failed')
        os.utime(tmp,ns=(before['atime_ns'],before['mtime_ns']))
        after=metadata(tmp)
        assert helper['preserved'](before,after) and xattrs(tmp)==attrs and sha(tmp)==row['sha256']
        assert after['inode'] not in (before['inode'],donor.stat().st_ino)
        current=metadata(p)
        assert all(current[k]==before[k] for k in ('inode','bytes','mtime_ns','mode','uid','gid'))
        os.replace(tmp,p)
        assert sha(p)==row['sha256']
        record['clones'].append({'path':str(p),'canonical':str(donor),'sha256':row['sha256'],'bytes':row['bytes'],'before':before,'after':metadata(p)})
        record.pop('pending');receipt.write_text(json.dumps(record,indent=2)+'\n')
    finally:
        if tmp.exists():tmp.unlink()
assert all(sha(Path(row['path']))==row['sha256'] for row in rows)
assert sha(plan_path)==record['plan_sha256']
record.update(exit_code=0,finished_at=datetime.datetime.now(datetime.UTC).isoformat(),products_verified_before_after=len(rows),canonical_identities=len(canonical),duplicate_files=len(record['clones']),exact_duplicate_bytes_shared=sum(row['bytes'] for row in record['clones']),available_bytes_after=helper['available']())
record['available_bytes_delta']=record['available_bytes_after']-record['available_bytes_before']
record['allocation_note']='Volume delta can include concurrent cleanup; exact_duplicate_bytes_shared is the content arranged into COW clones.'
receipt.write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({k:v for k,v in record.items() if k!='clones'},indent=2))
