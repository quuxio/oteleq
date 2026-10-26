"""Verify final SDK candidate's consumed Python/native/build input blobs and modes."""
import hashlib,json,os,stat,subprocess
from pathlib import Path
R=Path(__file__).resolve().parent
HEAD='e8e5861615ded40ebc5c50d68482ad703abdd419'
BASE='ce4cf749279c1b4416ca79e18c194c8c908471f6'
WRAPPER=['/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider/.venv/bin/python','/Users/sclarke/github/oteleq-qualification/2026-10-20/pause-for-reboot/quux-oteleq-gh.py']
ENV={**os.environ,'XDG_CACHE_HOME':'/Users/sclarke/github/oteleq-qualification/work/gh-cache'}
def api(path):
 result=subprocess.run(WRAPPER+['api','repos/quuxio/otelc/'+path],env=ENV,capture_output=True,check=True,timeout=60)
 return json.loads(result.stdout)
commit=api('git/commits/'+HEAD);assert commit['sha']==HEAD
tree=api('git/trees/'+commit['tree']['sha']+'?recursive=1');assert tree['sha']==commit['tree']['sha'] and tree['truncated'] is False
rows={row['path']:row for row in tree['tree']};assert len(rows)==len(tree['tree'])
fixed={'bin/quux-otelc','requirements.txt','requirements-dev.txt','ci/build_python_inputs.py','ci/native_encoder.py','ci/native_origin_chain.py'}
def selected(name):
 return name in fixed or (name.startswith('otelc/') and name.endswith('.py')) or (name.startswith('native/python/') and name.endswith(('.c','.h')))
remote={n for n,row in rows.items() if selected(n) and row['type']!='tree'}
base_index=json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-24/python-cached-origin-research/source-cache-ci-repair.json').read_text());assert base_index['head']==BASE
expected={n for n in base_index['files'] if selected(n)};assert remote==expected
results=[]
for version in ['312','314']:
 source=R/('provider-ce4cf74-'+version);catalogue=json.loads((R/f'portable-full-{version}-17b137b/matrix/provider-inputs.json').read_text())
 checked={}
 for name in sorted(expected):
  path=source/name;content=path.read_bytes();digest=hashlib.sha256(content).hexdigest();assert digest==base_index['files'][name]==catalogue[name]
  blob=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
  mode='100755' if path.stat().st_mode&stat.S_IXUSR else '100644'
  assert rows[name]['type']=='blob' and rows[name]['sha']==blob and rows[name]['mode']==mode,(name,mode,rows[name])
  checked[name]={'sha256':digest,'git_blob':blob,'mode':mode}
 results.append({'runtime':version,'checked_static_inputs':len(checked),'inputs':checked})
proof={'candidate':HEAD,'candidate_tree':commit['tree']['sha'],'qualified_sdk':BASE,'same_consumed_Python_native_builder_sources_and_modes':True,'exact_selected_path_sets_held':True,'runtime_checks':results,'new_application_launches':0,'scope':'Static consumed-input source compatibility bridge only. Existing frozen ce4 product bytes and their actual qualified execution remain the runtime evidence. Final candidate was not re-executed here; unrelated Go/CI/docs files and whole SDK/language admission are not claimed.'}
p=R/'sdk-e8e5861-consumed-input-bridge.json';p.write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps({'candidate':HEAD,'tree':commit['tree']['sha'],'inputs_each':len(expected),'new_applications':0,'receipt_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}),flush=True)
