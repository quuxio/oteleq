"""Read-only recovery of a final summary-key error; original partial receipt stays intact."""
from pathlib import Path
import datetime,hashlib,json,runpy
ROOT=Path(__file__).parent
program=ROOT/'clone-older-retained-native-products.py'
helper=runpy.run_path(str(program));digest=helper['digest'];metadata=helper['metadata'];xattrs=helper['xattrs']
original=ROOT/'older-retained-native-cow-compaction.json'
partial=json.loads(original.read_text());partial_hash=digest(original)
inventory=json.loads((ROOT/'older-retained-native-product-duplicates.json').read_text())
logged={row['path']:row for row in partial['clones']}
canonical={};duplicates=[];checked=0
for row in inventory['products']:
    p=Path(row['path']);value=metadata(p);attrs=xattrs(p)
    assert digest(p)==row['sha256']
    if p.name=='application':assert json.loads((p.parent.parent/'build-identities.json').read_text())['application']==row['sha256']
    key=(p.name,row['sha256'],value['mode'],value['uid'],value['gid'],attrs)
    checked+=1
    if key not in canonical:canonical[key]=p;continue
    donor=canonical[key]
    assert value['inode']!=donor.stat().st_ino and value['links']==1
    if str(p) in logged:
        old=logged[str(p)];assert value['mode']==old['mode'] and value['mtime_ns']==old['mtime_ns'] and value['inode']==old['clone_inode']
    duplicates.append({'path':str(p),'canonical':str(donor),'sha256':row['sha256'],'bytes':row['bytes'],'inode':value['inode'],'links':1,'mode':value['mode'],'mtime_ns':value['mtime_ns'],'original_metadata_in_partial_receipt':str(p) in logged})
assert len(duplicates)==2012 and len(canonical)==296 and checked==2308
assert digest(original)==partial_hash
record={'observed_at':datetime.datetime.now(datetime.UTC).isoformat(),'audit_exit':0,'new_mutations':0,'original_controller_exit':1,'original_controller_error':'Final record.update used published_raw_records_verified_after while its assertion read planned_product_hashes_verified_after. The full clone loop and final2308-product hash check completed before that bookkeeping KeyError.','controller_sha256':digest(program),'original_partial_receipt_sha256':partial_hash,'original_partial_receipt_unchanged':True,'original_partial_clone_records':len(logged),'all_product_before_hashes_revalidated':checked,'canonical_identities':len(canonical),'complete_duplicate_paths':len(duplicates),'exact_duplicate_bytes_shared':sum(row['bytes'] for row in duplicates),'metadata_evidence':'All2012 clone-loop iterations checked original mode/uid/gid/flags/xattrs/ns-mtime and before/after content hashes. Independent recovery confirms stored original mode/mtime/inode for the2000 persisted iterations; final12 were checked in the original loop before the final summary-key error. No missing original values have been invented.','clones':duplicates}
with (ROOT/'older-native-cow-recovery-audit.json').open('x') as out:json.dump(record,out,indent=2);out.write('\n')
print(json.dumps({k:v for k,v in record.items() if k!='clones'},indent=2))
