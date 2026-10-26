"""Round-trip copied real receipts only; never unlink original qualification files."""
import hashlib
import json
import os
from pathlib import Path
import sys

base=Path(__file__).parent
source=base/'source-6765646'
sys.path.insert(0,str(source))
from ci import evidence_archive as archive
from ci import evidence_files as files
from ci import evidence_index as records
from ci import evidence_attributes as attrs

proof=base/'copied-proof-6765646';proof.mkdir()
root=proof/'corpus';root.mkdir(mode=0o700)
store=proof/'archive'
inventory=json.loads((base.parent/'qualification-large-file-footprint.json').read_text())['files']
selected=[]
for filename in ('node-launch.json','node-plain-launch.json','class-load.log'):
    candidate=next(Path(v['path']) for v in inventory if Path(v['path']).name==filename)
    selected.append(candidate)
original_root=Path('/Users/sclarke/github/oteleq-qualification')
observations=[]
for ordinal,original in enumerate(selected):
    relative=str(original.relative_to(original_root))
    item,content,_=files.read(original_root,relative)
    name=f'{ordinal}/'+str(Path(relative).parent.name)+'/'+original.name
    destination=root/name;destination.parent.mkdir(parents=True,mode=0o700)
    fd=os.open(destination,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'wb',closefd=False) as stream: stream.write(content);stream.flush()
        attrs.write(fd,item['xattrs'])
        os.fchmod(fd,item['mode']);os.utime(fd,ns=(item['mtime_ns'],item['mtime_ns']))
    finally: os.close(fd)
    copied=files.read(root,name)[0]
    expected={**item,'path':name}
    if copied!=expected: raise ValueError('copy metadata differs')
    observations.append({'original_path':str(original),'original':item,'copy':copied})
selection=proof/'selection.json'
selection.write_text(json.dumps({'schema_version':1,'kind':records.KIND,'root':str(root),
    'paths':[v['copy']['path'] for v in observations]},indent=2)+'\n')
packed=archive.pack(root,selection,store);anchor=packed['index_sha256']
verified=archive.verify(root,store,anchor)
eviction=archive.evict(root,store,anchor,cold=True)
archived=archive.status(root,store,anchor)
restored=archive.materialise(root,store,anchor)
for observation in observations:
    if files.read(root,observation['copy']['path'])[0]!=observation['copy']: raise ValueError('restore differs')
    if files.read(original_root,observation['original']['path'])[0]!=observation['original']: raise ValueError('original changed')
parsed=[]
for observation in observations:
    path=root/observation['copy']['path']
    if path.suffix=='.json':
        value=json.loads(path.read_bytes());parsed.append({'path':str(path),'json_type':type(value).__name__})
    else:
        lines=path.read_text().splitlines();parsed.append({'path':str(path),'lines':len(lines)})
result={'head':'676564618d49bafaf4b7e16990f0da795f1017b2','copied_inputs':observations,
    'pack':packed,'verify':verified,'eviction':eviction,'archived_status':archived,'restore':restored,
    'readers':parsed,'all_original_bytes_metadata_preserved':True,'new_application_launches':0,
    'boundary':'Copied-receipt format/metadata proof; original-path frozen verifier compatibility remains separate.'}
(proof/'proof.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'files':len(observations),'original_bytes':packed['original_bytes'],
    'archive_bytes':packed['archive_bytes'],'restored':restored['restored'],'originals_preserved':True}))
