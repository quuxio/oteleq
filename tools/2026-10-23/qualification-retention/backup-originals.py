"""Create checked independent APFS clones before any original-path restore trial."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
base=Path(__file__).parent;sys.path.insert(0,str(base/'source-367b599'))
from ci import evidence_archive as archive
from ci import evidence_files as files
from ci import evidence_index as records
for name in ('evidence_archive','evidence_attributes','evidence_files','evidence_index','qualification_archive'):
 old=(base/'source-367b599/ci'/f'{name}.py').read_bytes()
 if old!=(base/'source-2b0f9f1/ci'/f'{name}.py').read_bytes():raise ValueError('production module changed')
anchors={'ca13d8326f7d49b3':'364671775f3772e4677ce40cd5a23df4b85fa036d56ce71c8a647c204972d825',
         'e78d8444c457f874':'2f8a7eab45826383dbadc1b6f392fc6716a20d5d895ead2a204fd82dc33719c8'}
backup_parent=base/'original-backups';backup_parent.mkdir(mode=0o700)
result={'phase':'preparing','original_paths_removed':0,'corpora':[]}
path=base/'original-backups.json'
for key,anchor in anchors.items():
 packed=json.loads((base/f'packed-{key}.json').read_text());root=Path(packed['root']);store=Path(packed['store'])
 if packed['index_sha256']!=anchor:raise ValueError('trusted index changed')
 archive.verify(root,store,anchor)
 index=records.index(store/'index.json',anchor,root)
 backup=backup_parent/key;backup.mkdir(mode=0o700)
 if root.stat().st_dev!=backup.stat().st_dev:raise ValueError('backup must be on the same APFS volume')
 count=0
 for item in index['files']:
  files.check(root,item)
  destination=backup/item['path'];destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
  if destination.exists() or destination.is_symlink():raise ValueError('backup target exists')
  subprocess.run(['/bin/cp','-cp',str(root/item['path']),str(destination)],check=True)
  original=files.check(root,item);cloned=files.check(backup,item)
  if original[1]==cloned[1] or destination.stat().st_nlink!=1:raise ValueError('backup is not independent')
  count+=1
 result['corpora'].append({'root':str(root),'store':str(store),'backup':str(backup),
   'index_sha256':anchor,'files':count,'bytes':sum(v['size'] for v in index['files'])})
 path.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'corpus':str(root),'checked_independent_clones':count,'original_paths_removed':0}),flush=True)
result['phase']='verified';path.write_text(json.dumps(result,indent=2)+'\n')
