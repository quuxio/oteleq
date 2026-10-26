"""Restore actual cold paths from verified archives while keeping independent originals."""
import datetime,json,os,sys
from pathlib import Path
base=Path(__file__).parent;sys.path.insert(0,str(base/'source-367b599'))
from ci import evidence_archive as archive
from ci import evidence_files as files
from ci import evidence_index as records
backup=json.loads((base/'original-backups.json').read_text())
if backup['phase']!='verified':raise ValueError('original backups are incomplete')
anchors={'ca13d8326f7d49b3':'364671775f3772e4677ce40cd5a23df4b85fa036d56ce71c8a647c204972d825',
         'e78d8444c457f874':'2f8a7eab45826383dbadc1b6f392fc6716a20d5d895ead2a204fd82dc33719c8'}
result={'phase':'in_progress','runtime_commit':'367b599e7fe55a01364810f194b3e54e3c29ab8d',
 'original_bytes_preserved_in_independent_backups':True,'corpora':[],'new_application_launches':0}
status=base/'original-path-roundtrip.json'
def save():
 content=json.dumps(result,indent=2)+'\n'
 with status.open('w') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
save()
for row in backup['corpora']:
 root=Path(row['root']);store=Path(row['store']);preserved=Path(row['backup']);anchor=row['index_sha256']
 if anchors.get(store.name)!=anchor:raise ValueError('unexpected archive/index')
 value=records.index(store/'index.json',anchor,root)
 for item in value['files']:files.check(root,item);files.check(preserved,item)
 progress={**row,'phase':'backups_verified'};result['corpora'].append(progress);save()
 progress['eviction']=archive.evict(root,store,anchor,cold=True);progress['phase']='archived';save()
 unavailable=archive.status(root,store,anchor)
 if unavailable['present'] or len(unavailable['archived'])!=row['files']:raise ValueError('archived availability differs')
 progress['restore']=archive.materialise(root,store,anchor);progress['phase']='restored';save()
 for item in value['files']:files.check(root,item);files.check(preserved,item)
 progress['phase']='restored_bytes_metadata_and_backups_verified';save()
 print(json.dumps({'root':str(root),'restored':progress['restore']['restored'],
  'original_independent_backups_preserved':row['files']}),flush=True)
result['phase']='restored_pending_frozen_reader_recheck';result['finished_at']=datetime.datetime.now(datetime.UTC).isoformat();save()
