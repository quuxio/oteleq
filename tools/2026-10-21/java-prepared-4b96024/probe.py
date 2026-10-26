"""Run an actual oteleq receiver worker through the public prepared-Java CLI."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading

sys.path[:0] = ['/Users/sclarke/github/oteleq/adapters/generation', '/Users/sclarke/github/oteleq/examples']
import discovery
import generation
import harness
import java_receivers
import otelc_capture as capture
import typed_capture
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

ROOT = Path(__file__).resolve().parent
PROVIDER = ROOT / 'prepared-provider'
JAVA = Path('/opt/homebrew/opt/openjdk@21/bin/java')
JAVAC = JAVA.with_name('javac')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def main():
    if sys.flags.optimize:
        raise ValueError('Qualification requires assertions')
    folder = ROOT / 'worker-v3'
    folder.mkdir(mode=0o700)
    project = folder / 'project'
    project.mkdir()
    app = project / 'App.java'
    app.write_text('''final class App {
 private int value;
 private static int total=0;
 App(int seed){value=seed;}
 int add(int amount){value+=amount;total+=amount;return value;}
}
''')
    source_hash = digest(app)
    environment = {'PATH':'/opt/homebrew/opt/openjdk@21/bin:/opt/homebrew/bin:/usr/bin:/bin',
        'JAVA_HOME':'/opt/homebrew/opt/openjdk@21','PYTHONPATH':str(PROVIDER),'PYTHONDONTWRITEBYTECODE':'1',
        'HOME':str(folder),'TMPDIR':str(folder),'LANG':'C.UTF-8','TZ':'UTC'}
    def execute(argv, cwd, **kwargs):
        return generation.execute(argv, cwd, environment, **kwargs)
    parsed = discovery.discover(app, 'java', PROVIDER, {'java':JAVA}, execute)
    write(folder / 'inventory.json', parsed)
    entry = dict(next(item for item in parsed['functions'] if item['name']=='App.add'))
    entry.update(language='java', path='App.java', package='', globals=parsed['globals'])
    java_receivers.bind(entry, parsed, {'factory':'App','arguments':[10]}, harness.concrete_arguments)
    harness.materialise(project, entry, [3])
    classes = folder / 'classes'
    classes.mkdir()
    empty = folder / 'empty-sourcepath'
    empty.mkdir()
    bindings, build_records = {}, []
    for source in (app, project / 'OteleqDriver.java'):
        before = {p.relative_to(classes).as_posix():digest(p) for p in classes.rglob('*.class')}
        argv = [JAVAC,'-proc:none','-implicit:none','-sourcepath',empty,'-classpath',classes,'-d',classes,source]
        result = execute(argv, project, folder=folder / ('compile-' + source.stem))
        assert result.returncode == 0, result.stderr
        after = {p.relative_to(classes).as_posix():digest(p) for p in classes.rglob('*.class')}
        assert all(after[name]==value for name,value in before.items())
        produced = {name:value for name,value in after.items() if name not in before}
        assert produced
        record = {'argv':list(map(str,argv)), 'compiler_sha256':digest(JAVAC.resolve()), 'source_sha256':digest(source), 'products_sha256':produced}
        build_records.append(record)
        for name,value in produced.items():
            binary = name[:-6].replace('/','.')
            bindings[binary] = {'source':str(source),'policy_path':source.name if source==app else '_oteleq_generated/'+source.name,
                'source_sha256':digest(source),'class_sha256':value,'provenance':json.dumps(record,sort_keys=True)}
    write(folder / 'compiler-bindings.json', build_records)
    manifest = folder / 'application.json'
    write(manifest, {'schema_version':1,'main_class':'OteleqDriver','classpath':[str(classes)],'bindings':bindings})
    products = {str(p):digest(p) for p in classes.rglob('*.class')}
    server = capture.CaptureServer(max_requests=128)
    serving = threading.Thread(target=server.serve_forever,daemon=True)
    serving.start()
    observations = []
    contract = {'observation_schema_version':1,'case_id':'prepared-receiver','function_id':'App.add(int)',
        'fixture_sha256':hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest(),
        'required_roots':typed_capture.required_roots(entry),'expected_baseline':{'kind':'return'}}
    write(folder/'contract.json',contract)
    try:
        for plain in (True,False):
            lane = folder / ('baseline' if plain else 'instrumented')
            lane.mkdir()
            policy = lane / 'policy.toml'
            policy.write_text(f'''schema_version=3
languages=["java"]
[resource]
service_name="oteleq-prepared-worker"
[sources]
include=["App.java"]
exclude=[]
[functions]
include=["App.add(int)"]
exclude=[]
[metrics]
collection=true
emission=true
[traces]
enabled=true
sample_ratio=1.0
[lifetimes]
enabled=false
[export]
endpoint="http://127.0.0.1:{server.server_port}"
interval_ms=100
timeout_ms=1000
''')
            runtime = Path('/private/tmp') / ('eqj-' + os.urandom(5).hex())
            argv = [sys.executable,'-m','otelc','--config',policy,'java','--manifest',manifest,'--runtime',runtime,'--prepare-only']
            if plain: argv.append('--plain')
            result = execute(argv, PROVIDER, folder=lane/'prepare')
            assert result.returncode==0, result.stderr
            launch = capture.strict_json(result.stdout)
            write(lane/'launch.json',launch)
            assert launch['plain'] is plain and launch['main_class']=='OteleqDriver'
            assert launch['control_socket'] is None if plain else launch['control_socket']==str(runtime/'control.sock')
            env = {**environment,'OTELEQ_OBSERVATION':str(lane/'observation')}
            result = generation.execute(launch['argv'], project, env, folder=lane/'application', timeout=45)
            assert result.returncode==0, result.stderr
            assert not result.stdout
            observed = (lane/'observation').read_bytes()
            observations.append(observed)
            write(lane/'typed-observation.json', typed_capture.observation(observed,entry,contract))
            assert digest(app)==source_hash and all(digest(Path(path))==sha for path,sha in products.items())
            assert (runtime/'class-load.log').is_file()
            shutil.copytree(runtime,lane/'runtime')
            write(lane/'runtime-original.json',str(runtime))
            if plain: assert not server.bodies
        assert observations[0]==observations[1]
        server.require_complete()
    finally:
        server.shutdown();server.server_close();serving.join(timeout=2)
        capture.retain_http(folder,server.bodies,server.errors,server.requests)
        decoded=[]
        for path,raw in server.bodies:
            message=ExportTraceServiceRequest() if path=='/v1/traces' else ExportMetricsServiceRequest()
            message.ParseFromString(raw)
            decoded.append({'path':path,'message':MessageToDict(message,preserving_proto_field_name=True)})
        write(folder/'decoded-otlp.json',decoded)
    write(folder/'capture-complete.json',{'scope':'Generated Java receiver worker; plain/on source and class preservation; complete offline value/telemetry oracle pending','source_unchanged':digest(app)==source_hash,'class_count':len(products),'http_requests':len(server.bodies)})


if __name__=='__main__':main()
