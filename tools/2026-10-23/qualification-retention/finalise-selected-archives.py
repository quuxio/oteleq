"""Reclaim only the two fully restored/rechecked corpora and their checked backups."""
import datetime,json,os,subprocess,sys
from pathlib import Path
base=Path(__file__).parent;sys.path.insert(0,str(base/'source-367b599'))
from ci import evidence_archive as archive
from ci import evidence_files as files
from ci import evidence_index as records
anchors={'ca13d8326f7d49b3':'364671775f3772e4677ce40cd5a23df4b85fa036d56ce71c8a647c204972d825',
         'e78d8444c457f874':'2f8a7eab45826383dbadc1b6f392fc6716a20d5d895ead2a204fd82dc33719c8'}
roundtrip=json.loads((base/'original-path-roundtrip.json').read_text())
if roundtrip['phase']!='restored_pending_frozen_reader_recheck':raise ValueError('roundtrip incomplete')
proofs={}
for language in ('node','java'):
 before=json.loads((base/f'retained-reader-before-{language}.json').read_text())
 after=json.loads((base/f'retained-reader-after-{language}.json').read_text())
 if before['files']!=after['files'] or before['result']!=after['result'] or after['new_application_launches']!=0:raise ValueError('reader proof differs')
 proofs[after['corpus']]=after
rows=roundtrip['corpora']
if {Path(row['store']).name for row in rows}!=set(anchors):raise ValueError('unexpected corpora')
for row in rows:
 root=Path(row['root']);store=Path(row['store']);backup=Path(row['backup']);anchor=anchors[store.name]
 if row['index_sha256']!=anchor or backup!=base/'original-backups'/store.name:raise ValueError('unexpected recovery path/index')
 index=records.index(store/'index.json',anchor,root)
 if proofs[str(root)]['files']!=index['files']:raise ValueError('reader/index metadata mismatch')
 for item in index['files']:files.check(root,item);files.check(backup,item)
# The fixed operational checker executes no commands supplied by an index.
check=subprocess.run([sys.executable,str(base/'check-cold-open-files.py')],capture_output=True,text=True,check=True)
live=json.loads(check.stdout);live_receipt=json.loads(Path(live['receipt']).read_text())
if live_receipt['matched_commands'] or live_receipt['matched_open_files'] or live_receipt['lsof_stderr']:raise ValueError('corpus is not idle')
result={'phase':'reclaiming','live_proof':live,'runtime_commit':'367b599e7fe55a01364810f194b3e54e3c29ab8d',
 'publication_commit':'2b0f9f102c2d6e78ae9a41029cdd47f1000c41d4','new_application_launches':0,'corpora':[]}
status=base/'final-selected-archives.json'
def save():
 with status.open('w') as output:json.dump(result,output,indent=2);output.write('\n');output.flush();os.fsync(output.fileno())
save()
for row in rows:
 root=Path(row['root']);store=Path(row['store']);backup=Path(row['backup']);anchor=anchors[store.name]
 index=records.index(store/'index.json',anchor,root)
 progress={**row,'phase':'reclaiming_restored_copies'};result['corpora'].append(progress);save()
 progress['final_eviction']=archive.evict(root,store,anchor,cold=True);progress['phase']='raw_archived_backups_retained';save()
 available=archive.status(root,store,anchor)
 if available['present'] or len(available['archived'])!=row['files']:raise ValueError('final raw availability differs')
 directories=set()
 for item in index['files']:
  identity=files.check(backup,item);files.remove(backup,item,identity)
  for parent in (backup/item['path']).parents:
   if parent.is_relative_to(backup):directories.add(parent)
 for directory in sorted(directories,key=lambda path:len(path.parts),reverse=True):directory.rmdir()
 progress['phase']='archived_with_verified_restore_and_reader_proof';progress['independent_backups_removed']=row['files'];save()
 print(json.dumps({'root':str(root),'archived':row['files'],'backup_copies_removed':row['files']}),flush=True)
(base/'original-backups').rmdir()
result.update(phase='complete',finished_at=datetime.datetime.now(datetime.UTC).isoformat(),
 original_payload_bytes=sum(row['bytes'] for row in rows),
 archive_payload_bytes=sum((Path(row['store'])/'receipts.tar.gz').stat().st_size for row in rows))
result['logical_payload_reduction_bytes']=result['original_payload_bytes']-result['archive_payload_bytes']
result['storage_boundary']='Payload byte comparison; no exclusive attribution of whole-volume free-space changes or shared APFS extents.'
save();print(json.dumps({key:result[key] for key in ('phase','original_payload_bytes','archive_payload_bytes','logical_payload_reduction_bytes')}))
