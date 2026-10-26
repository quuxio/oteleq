"""Freeze the two public test-only corrections and verify every other SDK input."""
import base64,hashlib,json,os,subprocess
from pathlib import Path
R=Path(__file__).resolve().parent;source=R/'source';head='503dbb8622e31390ad153146594c1d284b76c547'
base=json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-24/python-cached-origin-research/source-cache-ci-repair.json').read_text())
assert all(hashlib.sha256((source/n).read_bytes()).hexdigest()==h for n,h in base['files'].items())
wrapper=['/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider/.venv/bin/python','/Users/sclarke/github/oteleq-qualification/2026-10-20/pause-for-reboot/quux-oteleq-gh.py']
env={**os.environ,'XDG_CACHE_HOME':'/Users/sclarke/github/oteleq-qualification/work/gh-cache'}
changed=['tests/fixtures/python_cache_startup_failure.c','tests/test_python_cached_origins.py']
expected=dict(base['files'])
for name in changed:
 response=subprocess.run(wrapper+['api','repos/quuxio/otelc/contents/'+name+'?ref='+head],capture_output=True,env=env,check=True,timeout=60)
 data=json.loads(response.stdout);assert data['encoding']=='base64' and data['path']==name
 content=base64.b64decode(data['content']);assert hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()==data['sha']
 (source/name).write_bytes(content);expected[name]=hashlib.sha256(content).hexdigest()
assert all(hashlib.sha256((source/n).read_bytes()).hexdigest()==h for n,h in expected.items())
(R/'source.json').write_text(json.dumps({'head':head,'base':base['head'],'changed':changed,'files':expected},indent=2)+'\n')
print('All389 SDK source files verified; only the two reviewed test corrections applied.',flush=True)
