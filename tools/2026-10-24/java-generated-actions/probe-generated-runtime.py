"""Development execution of real generated callers, public preparation and receipt."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-java-generated-actions')
SDK = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-handle-runtime-review-6fb166c/source-6fb166c')
ROOT = Path(sys.argv[1]).resolve();ROOT.mkdir()
sys.path[:0] = [str(REPO / 'adapters/generation'), str(REPO / 'examples')]
import generation
import harness
import java_action_launch
import java_action_run
import java_action_telemetry
import java_build
import java_launch
import java_provider
import otelc_capture as capture
import policy
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

TOOLS = {'java': Path('/opt/homebrew/opt/openjdk@21/bin/java'), 'javac': Path('/opt/homebrew/opt/openjdk@21/bin/javac')}
SOURCE = '''class Counter {
private int value;private static int total;private Counter self=this;
private Counter(int initial){value=initial;}
private static Counter make(int initial){return new Counter(initial);}
private Counter run(int amount){
total++;
if(amount<0)throw new IllegalStateException("negative");
value+=amount;
if(amount>0)run(amount-1);
return this;
}
}'''

def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')

lanes = []
for controlled in (False, True):
    observations = []
    for plain in (True, False):
        folder = ROOT / (('live-' if controlled else 'ordinary-') + ('baseline' if plain else 'on'))
        folder.mkdir();project = folder / 'project';project.mkdir();(folder / 'scratch').mkdir()
        (project / 'Counter.java').write_text(SOURCE)
        discovered = json.loads(subprocess.check_output([str(TOOLS['java']), str(REPO / 'adapters/generation/Discover.java'), str(project / 'Counter.java')]))
        discovered['entrypoints'] = []
        steps = [{'action': 'call', 'arguments': 'case' if index == 0 else [amount]}
                 for index, amount in enumerate((0, 3, -1, 1))]
        if controlled:
            for step, flags in zip(steps, ((True, True), (False, True), (True, False), (False, False))):
                step['metrics'] = dict(zip(('collection', 'emission'), flags))
        config = policy.validate({'languages': ['java'], 'adapters': {'java': {'backend': 'prepared',
            'profile': 'safe-methods-v1', 'witness_profile': 'java-sync-private-handle-v1'}},
            'functions': {'include': ['Counter.run(int)']},
            'fixtures': [{'function': 'Counter.run(int)', 'cases': [[0]],
                          'receiver': {'factory': 'make', 'arguments': [10]}, 'sequence': steps}]})
        function = next(item for item in discovered['functions'] if item['name'] == 'Counter.run')
        entry = generation.inventory_entry(function, discovered, 'Counter.java', 'java', hashlib.sha256(SOURCE.encode()).hexdigest(),
                                           project, argparse.Namespace(configuration=config, cases=1))
        assert entry['status'] == 'ready', entry
        case = generation.generation_case(entry, 0, [0]);driver = harness.materialise(project, entry, [0])
        immutable = generation.manifest(project)
        service = 'oteleq-generated-action-development-' + ('live' if controlled else 'ordinary')
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'JAVA_HOME': '/opt/homebrew/opt/openjdk@21',
               'OTELEQ_OBSERVATION': str(folder / 'observation')}
        with java_launch.runtime(entry, folder, source_roots=(REPO, SDK, ROOT)) as runtime:
            with capture.receiver(max_requests=4096, response_path=folder / 'http-responses.json') as (endpoint, bodies, errors):
                configuration = folder / 'policy.toml';configuration.write_text(java_provider.policy(entry, endpoint, service))
                command = generation.java_command(SDK, project, entry, driver, configuration, TOOLS, env,
                    folder, folder / 'scratch', 'baseline' if plain else 'instrumented_on', prepared_runtime=runtime)
                compiler_seals = java_action_launch.seals(folder)
                options = generation.execution_options(entry, case, 'baseline' if plain else 'instrumented_on',
                                                       folder, runtime, bodies, env, service=service)
                with java_action_run.retained(options):
                    result = generation.execute(command, project, env, folder, timeout=60, **options)
                assert result.returncode == 0 and result.stdout == result.stderr == b'', (result.returncode, result.stdout, result.stderr)
            capture.retain_http(folder, bodies, errors);assert not errors, errors
            raw = capture.strict_json((folder / 'observation').read_bytes())
            assert len(raw['steps']) == 4
            for step, before, after, total in zip(raw['steps'], (10, 10, 16, 16), (10, 16, 16, 17), (1, 5, 6, 8)):
                assert step['before']['nodes'][0]['fields']['value']['value'] == str(before), step
                assert step['after']['nodes'][0]['fields']['value']['value'] == str(after), step
                assert step['after']['roots']['static:Counter.total']['value'] == str(total), step
            assert [step['outcome']['kind'] for step in raw['steps']] == ['return', 'return', 'error', 'return']
            for index in (0, 1, 3):
                assert raw['steps'][index]['outcome']['value']['roots']['result'] == raw['steps'][index]['outcome']['value']['roots']['receiver']
            error_graph = raw['steps'][2]['outcome']['value']
            error_nodes = {node['id']: node for node in error_graph['nodes']}
            original_error = error_nodes[error_graph['roots']['error']['node_id']]
            assert original_error['type'] == 'java.lang.IllegalStateException'
            message = error_nodes[original_error['fields']['message']['node_id']]['fields']['value']
            assert message == {'kind': 'string', 'type': 'java.lang.String', 'encoding': 'utf16_be',
                               'value': 'negative'.encode('utf-16-be').hex()}
            received = java_action_telemetry.qualify(runtime, folder, entry, case, options['interaction'], bodies,
                service=service, trace_decoder=ExportTraceServiceRequest)
            launch = generation.read(folder / java_launch.LAUNCH_FILE)
            java_launch.verify(launch, root=SDK, project=project, folder=folder, tools=TOOLS, runtime=runtime,
                               entry=entry, data=tomllib.loads(configuration.read_text()), plain=plain)
            java_launch.origins(runtime, folder, entry)
            java_build.verify(project, folder / 'scratch/classes', folder)
            assert compiler_seals == java_action_launch.seals(folder)
            assert immutable == generation.manifest(project)
            if plain:
                assert received is None and not bodies
                generation.baseline_receipt(entry, folder, bodies)
            else:
                verified = generation.read(folder / 'verified-actions.json')
                assert [item['target_entries'] for item in verified['actions']] == [1, 4, 1, 2], verified
                assert verified['selected_method_spans'] == 8 and verified['unscoped_spans'] == 0, verified
                assert verified['collected_method_calls'] == (2 if controlled else 8), verified
                assert received['functions'] == {'Counter.run(int)': 8, 'otelc.action.wrapper': 4, 'otelc.action.target': 8}
                assert received['spans'] == 20 and all(value == 0 for value in received['losses'].values())
            observations.append(raw)
            process = generation.read(folder / 'process.json')
            summary = {'plain': plain, 'controlled': controlled, 'pid': process['pid'], 'witness': received,
                       'source_preserved': True, 'application_oracle_checked': True}
            write(folder / 'summary.json', summary);lanes.append(summary)
    assert observations[0] == observations[1]
write(ROOT / 'proof.json', {'kind': 'development_generated_action_runtime', 'lanes': lanes,
                          'scope': 'Real generated caller/compiler/public preparation/execution; private receiver, recursion, original exception, four metric states'})
print(json.dumps({'lanes': len(lanes), 'pids': [row['pid'] for row in lanes], 'oracles': 'passed'}))
