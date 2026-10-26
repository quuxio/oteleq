"""Run an actual oteleq receiver worker through the public prepared-Java CLI."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading

GENERATOR = Path('/Users/sclarke/github/oteleq-qualification/2026-10-21/java-compiler-8843816/source')
sys.path[:0] = [str(GENERATOR / 'adapters/generation'), str(GENERATOR / 'examples')]
import discovery
import generation
import harness
import java_receivers
import java_build
import subprocess
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
    noisy = '--stderr-fixture' in sys.argv
    folder = ROOT / ('stderr-v1' if noisy else 'clean-v1')
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
    if noisy:
        noise = '[otel.javaagent 2026-10-21 00:00:00:000 +0000] [main] INFO io.opentelemetry.javaagent.tooling.VersionLogger - opentelemetry-javaagent - version: 2.32.0\nOpenJDK 64-Bit Server VM warning: Sharing is only supported for boot loader classes because bootstrap classpath has been appended\n'
        inserted = ''.join('java.lang.System.err.println(' + json.dumps(line) + ');' for line in noise.splitlines())
        app.write_text(app.read_text().replace('value+=amount;', inserted + 'value+=amount;'))
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
    classes = folder / 'scratch/classes'
    java_build.build(project, [app, project/'OteleqDriver.java'], 'OteleqDriver', JAVA,
                     classes, folder, environment, generation.execute)
    manifest = folder / 'prepared-application.json'
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
            argv = [sys.executable,'-m','otelc','--config',policy,'java','--manifest',manifest,'--runtime',runtime,'--prepare-only','--diagnostic-profile']
            if plain: argv.append('--plain')
            result = execute(argv, PROVIDER, folder=lane/'prepare')
            assert result.returncode==0, result.stderr
            launch = capture.strict_json(result.stdout)
            write(lane/'launch.json',launch)
            assert launch['plain'] is plain and launch['main_class']=='OteleqDriver'
            assert launch['jvm_profile']=='diagnostic-no-cds' and '-Xshare:off' in launch['argv']
            assert launch['control_socket'] is None if plain else launch['control_socket']==str(runtime/'control.sock')
            env = {**environment,'OTELEQ_OBSERVATION':str(lane/'observation')}
            output = lane/'application'
            output.mkdir()
            with (output/'stdout').open('wb') as out, (output/'stderr').open('wb') as err:
                process = subprocess.Popen(launch['argv'],cwd=project,env=env,stdout=out,stderr=err,start_new_session=True)
                write(output/'process.json', {'pid':process.pid,'argv':launch['argv']})
                try:
                    process.wait(timeout=45)
                finally:
                    generation.finish_process(process)
            result = subprocess.CompletedProcess(launch['argv'],process.returncode,
                (output/'stdout').read_bytes(),(output/'stderr').read_bytes())
            java_build.verify(project,classes,folder)
            if plain:
                assert launch['health_report'] is None and launch['selection_sha256'] is None
            else:
                health = capture.strict_json(Path(launch['health_report']).read_bytes())
                assert health['pid']==process.pid and health['policy_sha256']==launch['policy_sha256']
                assert health['selection_sha256']==launch['selection_sha256']
                assert health['phase']=='final' and health['sdk_attached'] is True
                assert health['lifecycle']=={'flush':'succeeded','shutdown':'succeeded'}
                assert health['span_accounting']['sampled_started']==health['span_accounting']['sampled_ended']=='1'
                assert health['span_accounting']['sampled_active']==health['span_accounting']['queue_pending']==health['span_accounting']['queue_dropped']=='0'
                assert health['span_accounting']['queue_evidence']=='derived_after_shutdown'
                assert health['trace_exports']['units_started']==health['trace_exports']['units_succeeded']=='1'
                assert health['trace_exports']['units_failed']==health['trace_exports']['batches_failed']==health['trace_exports']['batches_pending']=='0'
                assert health['downstream_receipt']==health['otlp_partial_rejection']=='unavailable'
                write(lane/'checked-health.json',health)
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
