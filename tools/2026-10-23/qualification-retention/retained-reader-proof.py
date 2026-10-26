"""Use frozen retained readers; refuse every subprocess and preserve raw files."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest import mock

parser=argparse.ArgumentParser();parser.add_argument('--language',choices=('node','java'),required=True)
parser.add_argument('--phase',choices=('before','after'),required=True);args=parser.parse_args()
base=Path(__file__).parent
if args.language=='node':
 previous=base.parent/'node-metric-controls';source=previous/'source-a295b0e'
 root=previous/'controls-a295-node24'
else:
 previous=base.parent/'java-startup-controls';source=previous/'source-bb1fb96'
 root=previous/'qualification-bb1fb96-stock-emission-off'
sys.path[:0]=[str(base/'source-367b599'),str(source/'tests'),str(source/'adapters/generation'),str(source/'examples')]
from ci import evidence_files as files
from ci import evidence_index as records
manifest=json.loads(source.with_suffix('.json').read_text())
def verify_sources():
 for name,digest in manifest['files'].items():
  if hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest: raise ValueError('frozen reader changed: '+name)
 return len(manifest['files'])
source_count=verify_sources()
plans=json.loads((base/'cold-selection-plan.json').read_text())['groups']
plan=next(row for row in plans if row['root']==str(root))
if hashlib.sha256(Path(plan['selection']).read_bytes()).hexdigest()!=plan['selection_sha256']: raise ValueError('selection changed')
names=records.selection(Path(plan['selection']),root)
originals=[files.read(root,name)[0] for name in names]
with mock.patch('subprocess.Popen',side_effect=AssertionError('retained reader cannot launch subprocesses')):
 if args.language=='node':
  import node_launch
  for name in names:
   path=root/name;prefix=path.name.removesuffix('-launch.json')
   inputs=node_launch.read(path.with_name(prefix+'-inputs.json'))
   recorded=inputs['launch_manifest'];original=Path(recorded['path'])
   if not original.is_relative_to(root): raise ValueError('manifest identity left the fixed corpus')
   node_launch.same(node_launch.file_identity(original),recorded,'frozen SDK launch binding differs')
   node_launch.read(path)
  result={'selected_launch_receipts_checked':len(names),'reader':'node_launch.read/same/file_identity'}
 else:
  import qualify_java_controls as controls
  import qualify_java_startup as startup
  states=startup.startup_states('emission-off')
  result=controls.verify_prepared(root/'corpus',lambda *values:controls.verify_receipt(*values,states=states))
for item in originals:
 if files.read(root,item['path'])[0]!=item: raise ValueError('raw file changed during reader proof')
if args.phase=='after':
 before=json.loads((base/('retained-reader-before-'+args.language+'.json')).read_text())
 if before['files']!=originals or before['result']!=result: raise ValueError('retained reader/raw identities changed')
output={'phase':args.phase,'corpus':str(root),'selection_sha256':plan['selection_sha256'],
 'reader_commit':manifest.get('commit',manifest.get('head')),'reader_source_files_preserved':verify_sources(),
 'result':result,'files':originals,'new_application_launches':0,
 'scope':'Frozen original-path launch binding/archive-byte/health readers; independent original content/metadata contracts preserved. No new execution or provider admission.'}
path=base/('retained-reader-'+args.phase+'-'+args.language+'.json')
with path.open('x') as stream: json.dump(output,stream,indent=2);stream.write('\n')
print(json.dumps({'phase':args.phase,'language':args.language,'source_files':source_count,'files':len(names),'result':result}))
