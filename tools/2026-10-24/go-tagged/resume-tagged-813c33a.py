"""Retain the initial36 applications and run only the remaining tagged routes."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

BASE = Path(__file__).resolve().parent
ROOT = BASE / 'maintained-b6d4369'
DESTINATION = ROOT / 'resume-813c33a'
DESTINATION.mkdir()
INDEX = json.loads((BASE / 'source-813c33a.json').read_text())
SOURCE = Path(INDEX['source'])
sys.path.insert(0, str(SOURCE / 'tests'))
import qualify_go_receivers as qualifier

SDK = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-reuse-review-d2ec6bf/source')
SDK_INDEX = json.loads((SDK.parent / 'inputs-before.json').read_text())
OLD_INDEX = json.loads((ROOT / 'source.json').read_text())
OLD_SOURCE = Path(OLD_INDEX['source'])
OLD_INPUTS = json.loads((ROOT / 'inputs-before.json').read_text())
CLI = BASE / 'target/debug/quux-oteleq'
FOLDER = ROOT / 'evidence'
WORK = FOLDER / 'receivers'
WORKSPACE = next(WORK.glob('oteleq-run-*'))
TAGS = ('feature', 'tools', '\u03c0')
assert not (WORK / 'framework.stdout').exists() and not (WORK / 'exported').exists() and not (WORK / 'shrink').exists()
os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(CLI), OTELC_PYTHON=sys.executable,
                  OTELC_GO='/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go',
                  PYTHONDONTWRITEBYTECODE='1')
os.environ['PATH'] = str(Path(os.environ['OTELC_GO']).parent) + os.pathsep + os.environ['PATH']


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def facts(path):
    value = path.stat()
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'facts': [value.st_dev, value.st_ino,
        value.st_mode, value.st_uid, value.st_gid, value.st_size, value.st_mtime_ns, value.st_ctime_ns]}


def inputs():
    tooling = json.loads((SDK / 'build/go-upstream/toolchain.json').read_text())
    return {'source': {name: facts(OLD_SOURCE / name) for name in OLD_INDEX['files']},
            'qualifier': {name: facts(SOURCE / name) for name in INDEX['files']},
            'sdk': {name: facts(SDK / name) for name in SDK_INDEX['files']},
            'tooling': {str(path): facts(path) for path in [SDK / 'build/go-upstream/toolchain.json',
                         *[Path(tooling[name]) for name in ('go', 'weaver', 'bundle')]]}, 'cli': facts(CLI)}


before = inputs()
assert all(before[name] == value for name, value in OLD_INPUTS.items()), 'original frozen inputs changed'
assert all(before['qualifier'][name]['sha256'] == digest for name, digest in INDEX['files'].items())
write(DESTINATION / 'inputs-before.json', before)
state = {'status': 'running', 'runtime_head': 'c8c1e890b400171043f9dae36e1121bcd847548e',
         'qualifier_head': INDEX['head'], 'original_qualifier_head': OLD_INDEX['head'],
         'started': datetime.now(timezone.utc).isoformat(), 'commands': [],
         'scope': 'Explicit feature/tools/Unicode tagged receiver/retained/reduction corpus. Initial36 applications are audited and reused; no repeated direct run.'}
command = qualifier.command


def execute(arguments, folder, name, expected=0, timeout=900):
    started = time.monotonic()
    state['phase'] = name
    write(DESTINATION / 'status.json', state)
    write(DESTINATION / (str(len(state['commands'])) + '-command.json'), {'argv': list(map(str, arguments)),
        'destination': str(folder), 'name': name, 'expected': expected, 'timeout_seconds': timeout})
    try:
        output = command(arguments, folder, name, expected=expected, timeout=timeout)
    except Exception as error:
        state['commands'].append({'phase': name, 'result': 'failed', 'seconds': round(time.monotonic() - started, 3), 'error': repr(error)})
        write(DESTINATION / 'status.json', state)
        raise
    state['commands'].append({'phase': name, 'result': 'passed', 'seconds': round(time.monotonic() - started, 3)})
    write(DESTINATION / 'status.json', state)
    return output


qualifier.command = execute
try:
    launches = qualifier.check_report(WORK / 'comparison/report.json', backend='source-v1', build_tags=TAGS)
    assert launches == 36
    state['retained_initial_applications'] = launches
    launches += qualifier.framework(WORKSPACE, WORK, 'framework', backend='source-v1', build_tags=TAGS)
    exported = WORK / 'exported'
    execute([CLI, 'export-tests', '--workspace', WORKSPACE, '--destination', exported, '--apply'], WORK, 'export')
    execute([CLI, 'run', '--workspace', exported, '--report-dir', WORK / 'export-comparison'], WORK, 'export-run', expected=1, timeout=3600)
    launches += qualifier.check_report(WORK / 'export-comparison/report.json', backend='source-v1', build_tags=TAGS)
    launches += qualifier.framework(exported, WORK, 'export-framework', backend='source-v1', build_tags=TAGS)
    corpus = json.loads((WORKSPACE / 'tests/corpus.json').read_text())
    plan = json.loads((WORKSPACE / 'plan.json').read_text())
    case = qualifier.selected_case(plan, corpus, 'Counter.InstanceDifference')
    controls = qualifier.source_guards(CLI, WORKSPACE, WORK, case)
    execute([CLI, 'shrink', '--workspace', WORKSPACE, '--case', case['id'], '--trials', '1',
             '--report-dir', WORK / 'shrink'], WORK, 'shrink', expected=1)
    shrink = json.loads((WORK / 'shrink/shrink.json').read_text())
    assert shrink['reduced_arguments'] == [0] and shrink['status'] == 'candidate_rule_minimal'
    reports = [WORK / 'shrink/original/report.json', WORK / 'shrink/confirmation/report.json',
               *[Path(item['report']) for item in shrink['trials']]]
    launches += sum(qualifier.check_report(path, 1, backend='source-v1', build_tags=TAGS) for path in reports)
    replay = json.loads(execute([CLI, 'replay', '--workspace', shrink['workspace'], '--case', case['id']], WORK, 'replay', expected=1))
    launches += qualifier.check_report(Path(replay['report']), 1, backend='source-v1', build_tags=TAGS)
    refused = qualifier.source_probe_guards(CLI, WORKSPACE, WORK, case)
    assert refused['actual_application_launches'] == 0
    for workspace in (WORKSPACE, exported, Path(shrink['workspace'])):
        frozen = json.loads((workspace / 'plan.json').read_text())
        assert all(hashlib.sha256((Path(frozen['source']) / name).read_bytes()).hexdigest() == digest
                   for name, digest in frozen['source_manifest'].items())
    paths = [path for path in FOLDER.rglob('command.json') if path.parent.name.startswith(('baseline-', 'instrumented_on-'))]
    unique = {hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert launches == len(unique) == 160
    state.update(status='passed', actual_application_launches=launches, new_application_launches=launches-36,
                 retained_attempt_folders=len(paths), unique_command_identities=len(unique), prelaunch_source_refusals=controls,
                 fixture_refusals=refused)
except Exception as error:
    state.update(status='failed', error=repr(error))
finally:
    after = inputs()
    write(DESTINATION / 'inputs-after.json', after)
    state['preservation'] = {name: before[name] == after[name] for name in before}
    if not all(state['preservation'].values()): state['status'] = 'failed'
    state['finished'] = datetime.now(timezone.utc).isoformat()
    write(DESTINATION / 'status.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
