"""Verify the combined cleanup without starting applications or changing retained evidence."""
from pathlib import Path
import datetime,hashlib,json,os,runpy
ROOT=Path('/Users/sclarke/github/oteleq-qualification');DATE=ROOT/'2026-10-23'
def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
expected={}
for parent,manifest in (
    (DATE/'cpp-call-sequences/qualification-50f01a7',DATE/'cpp-call-sequences/qualification-50f01a7-raw-manifest.json'),
    (DATE/'cpp-call-sequences/compatibility-70cbdbc',DATE/'cpp-call-sequences/compatibility-70cbdbc-raw-manifest.json'),
    (DATE/'python-call-sequences/qualification-18f70b9-quiet',DATE/'python-call-sequences/qualification-18f70b9-quiet-raw-sha256.json'),
    (DATE/'python-call-sequences/compatibility-18f70b9',DATE/'python-call-sequences/compatibility-18f70b9-raw-sha256.json')):
    for name,value in json.loads(manifest.read_text()).items():expected[str(parent/name)]=value
for name in ('older-retained-native-product-duplicates.json','other-inactive-product-cow-plan.json'):
    for row in json.loads((DATE/name).read_text())['products']:
        if row['path'] in expected:assert expected[row['path']]==row['sha256']
        expected[row['path']]=row['sha256']
for name,value in expected.items():assert sha(Path(name))==value,name
provider=runpy.run_path(str(DATE/'python-call-sequences/run-corpus-18f70b9.py'))['verify']()
cleanup=json.loads((DATE/'inactive-build-cache-cleanup.json').read_text())
for row in cleanup['removed']:assert not Path(row['path']).exists()
for row in cleanup['preserved_coverage']:assert sha(Path(row['retained']))==row['sha256']
cpp=json.loads((DATE/'cpp-retained-cow-compaction.json').read_text())
older=json.loads((DATE/'older-native-cow-recovery-audit.json').read_text())
other=json.loads((DATE/'other-inactive-product-cow-compaction.json').read_text())
assert other['exit_code']==0 and older['audit_exit']==0
shared=sum(d['exact_duplicate_bytes_shared'] for d in (cpp,older,other))
value=os.statvfs(ROOT)
record={'finished_at':datetime.datetime.now(datetime.UTC).isoformat(),'exit_code':0,'new_application_launches':0,'distinct_retained_hashes_verified':len(expected),'shared_provider_records_verified':sum(provider['provider_counts'].values()),'frozen_consumer_source_files_verified':provider['consumer_files'],'retained_coverage_files_verified':len(cleanup['preserved_coverage']),'inactive_cache_directories_removed':len(cleanup['removed']),'removed_cache_allocation_bytes':cleanup['removed_allocated_kib']*1024,'copy_on_write_duplicate_files':cpp['clone_files']+older['complete_duplicate_paths']+other['duplicate_files'],'exact_duplicate_bytes_arranged_as_cow':shared,'available_volume_bytes':value.f_bavail*value.f_frsize,'original_older_controller_exit':1,'older_retained_recovery_exit':0,'retention_command_validation':json.loads((DATE/'retention-command-check.json').read_text()),'remaining_data':'Unique raw observations/telemetry, byte-distinct tested binaries, compiler inventories, retained source and pinned SDK/dependency inputs remain. Node launch receipts and class logs have documented further indexed-compression opportunity; no raw paths were removed or silently archived.','allocation_note':'Do not equate COW byte totals or summed du directories with exclusive physical-space attribution; volume free space includes concurrent otelc/Docker cleanup.'}
with (DATE/'FINAL-FOOTPRINT-AUDIT.json').open('x') as out:json.dump(record,out,indent=2);out.write('\n')
print(json.dumps(record,indent=2))
