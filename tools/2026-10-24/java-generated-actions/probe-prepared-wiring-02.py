"""Exercise real generated-source/JDK/SDK binding, stopping before launch."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-java-generated-actions')
SDK = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-handle-runtime-review-6fb166c/source-6fb166c')
ROOT = Path(__file__).resolve().parent / 'prepared-wiring-development-02'
ROOT.mkdir()
PROJECT = ROOT / 'project';PROJECT.mkdir()
FOLDER = ROOT / 'attempt';FOLDER.mkdir();(FOLDER / 'scratch').mkdir()

sys.path[:0] = [str(REPO / 'adapters/generation'), str(REPO / 'examples')]
import generation
import harness
import java_actions
import java_launch
import java_provider
import policy

tools = {'java': Path('/opt/homebrew/opt/openjdk@21/bin/java'), 'javac': Path('/opt/homebrew/opt/openjdk@21/bin/javac')}
source = '''class Counter {
private int value;private Counter(int initial){value=initial;}
private static Counter make(int initial){return new Counter(initial);}
private Counter run(int amount){value+=amount;return this;}
}'''
(PROJECT / 'Counter.java').write_text(source)
discovered = json.loads(subprocess.check_output([str(tools['java']), str(REPO / 'adapters/generation/Discover.java'), str(PROJECT / 'Counter.java')]))
discovered['entrypoints'] = []
config = policy.validate({'languages': ['java'],
    'adapters': {'java': {'backend': 'prepared', 'profile': 'safe-methods-v1', 'witness_profile': 'java-sync-private-handle-v1'}},
    'functions': {'include': ['Counter.run(int)']},
    'fixtures': [{'function': 'Counter.run(int)', 'cases': [[7]], 'receiver': {'factory': 'make', 'arguments': [10]}}]})
function = next(item for item in discovered['functions'] if item['name'] == 'Counter.run')
entry = generation.inventory_entry(function, discovered, 'Counter.java', 'java', hashlib.sha256(source.encode()).hexdigest(),
                                   PROJECT, argparse.Namespace(configuration=config, cases=1))
assert entry['status'] == 'ready', entry
driver = harness.materialise(PROJECT, entry, [7])
configuration = FOLDER / 'policy.toml';configuration.write_text(java_provider.policy(entry, 'http://127.0.0.1:4318', 'compiler-wiring-only'))
environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'JAVA_HOME': '/opt/homebrew/opt/openjdk@21'}
with java_launch.runtime(entry, FOLDER, source_roots=(REPO, SDK, ROOT)) as runtime:
    command = generation.java_command(SDK, PROJECT, entry, driver, configuration, tools, environment,
        FOLDER, FOLDER / 'scratch', 'instrumented', prepared_runtime=runtime)
    value = generation.read(FOLDER / java_launch.LAUNCH_FILE)
    assert command == value['argv']
    assert command[1] == '-Dotelc.witness.plan=' + str(runtime / 'witness.properties')
    metadata = generation.read(runtime / 'witness.json')
    assert metadata['schema_version'] == 3 and metadata['profile'] == entry[java_actions.FIELD]
    record = {'kind':'development_generated_prepared_wiring','application_started':False,
        'profile':metadata['profile'],'route_sha256':metadata['route']['sha256'],
        'tooling_inputs':len(value['tooling']),'source_preserved':(PROJECT/'Counter.java').read_text()==source,
        'scope':'Real JDK/compiler/public SDK prepare-only API; no application execution'}
    (ROOT/'proof.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record))
