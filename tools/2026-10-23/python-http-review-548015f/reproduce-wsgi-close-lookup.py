"""Compare native WSGI close attribute observations with the candidate frontend."""
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).parent
folder = root / 'close-lookup-reproducer'
folder.mkdir(mode=0o700)
application = folder / 'application'
application.mkdir()
entry = application / 'entry.py'
entry.write_text('''import json,threading,urllib.request
from wsgiref.simple_server import make_server,WSGIRequestHandler
class Body:
    lookups=0
    closes=0
    def __iter__(self): return iter([b'ok'])
    def __getattribute__(self,name):
        if name=='close': Body.lookups+=1
        return object.__getattribute__(self,name)
    def close(self): Body.closes+=1
class Quiet(WSGIRequestHandler):
    def log_message(self,*arguments): pass
def app(environ,start_response):
    start_response('200 OK',[('Content-Type','text/plain'),('Content-Length','2')])
    return Body()
server=make_server('127.0.0.1',0,app,handler_class=Quiet)
worker=threading.Thread(target=server.handle_request)
worker.start()
with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/') as response:
    body=response.read()
worker.join(5)
assert not worker.is_alive()
server.server_close()
print(json.dumps({'close_lookups':Body.lookups,'close_calls':Body.closes,'body':body.hex()}))
''')
configuration = folder / 'otelc.toml'
configuration.write_text('''schema_version=3
languages=['python']
[sources]
include=['*.py']
[functions]
include=['*never_selected*']
[metrics]
collection=false
emission=false
[traces]
enabled=false
[context]
http=true
''')
python = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python')
environment = {**os.environ, 'PYTHONPATH': str(root / 'source'), 'PYTHONDONTWRITEBYTECODE': '1'}
commands = {'baseline': [python, entry],
            'instrumented': [python, '-m', 'otelc', '--config', configuration, 'python',
                             '--root', application, '--entry', 'entry.py', '--runtime', folder / 'runtime']}
record = {'source_commit': '548015fdbb3a3549f3aa5914dc7b669db08b5c63', 'cases': {}}
for name, command in commands.items():
    result = subprocess.run(list(map(str, command)), cwd=application, env=environment,
                            capture_output=True, timeout=30)
    (folder / (name + '.stdout')).write_bytes(result.stdout)
    (folder / (name + '.stderr')).write_bytes(result.stderr)
    record['cases'][name] = {'exit': result.returncode, 'stdout': result.stdout.decode(),
                           'stderr': result.stderr.decode()}
report = json.loads((folder / 'runtime/sdk/python-sdk-status.json').read_bytes())
record['sdk_phase'] = report['phase']
record['runtime_losses'] = report['producer']['runtime_losses']
(folder / 'reproducer.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
