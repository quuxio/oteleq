"""Fixed generated-Java action fixtures and independent complete value oracles."""

import json
from pathlib import Path
import zipfile

from qualify_generation import command

COUNTER = 'Counter.run(int)'
STATIC = 'Work.target(int)'
PROFILE = 'java-sync-private-handle-v1'
STATES = ((True, True), (False, True), (True, False), (False, False))
SIZES = (1, 4, 1, 2)
SOURCE = '''class Counter {
private int value;private static int total;private Counter self=this;
private Counter(int initial){value=initial;}
private static Counter make(int initial){return new Counter(initial);}
private Counter run(int amount){
ARCHIVE_CHECK
total++;
if(amount<0)throw new IllegalStateException("negative");
value+=amount;
if(amount>0)run(amount-1);
return this;
}
}
'''
STATIC_SOURCE = '''class Work {
static int total=10;
private static int target(int amount){
ARCHIVE_CHECK
boolean on=java.lang.management.ManagementFactory.getRuntimeMXBean().getInputArguments().stream().anyMatch(v->v.contains("opentelemetry-javaagent-2.32.0.jar"));
total+=amount+(on?1:0);return 7;
}
}
'''
COLLISION = 'package io.quux.otelc.methods;public class MethodMetrics {public static int value(){return 3;}}\n'


def states(start: int) -> list[dict]:
    """Each schedule includes both-on and all independent flag combinations."""
    assert type(start) is int and 0 <= start < 4
    order = [STATES[start], *(state for state in STATES if state != STATES[start])]
    return [dict(zip(('collection', 'emission'), state)) for state in order]


def fixture(folder: Path, java: Path, profile: str) -> Path:
    """An archive fixture forces real MR selection and SDK helper relocation."""
    source = folder / 'application';source.mkdir()
    check = ''
    if profile == 'archive-methods-v1':
        products = []
        for label, value in (('base', 1), ('version21', 3)):
            build = folder / label;build.mkdir()
            unit = build / 'Library.java'
            unit.write_text('package dep;public class Library {public static int value(){return ' + str(value) + ';}}')
            command([java.with_name('javac'), '-encoding', 'UTF-8', '-proc:none', '-d', build, unit], folder, 'compile-' + label)
            products.append((build / 'dep/Library.class').read_bytes())
        jar = source / 'lib/library.jar';jar.parent.mkdir()
        with zipfile.ZipFile(jar, 'x') as archive:
            archive.writestr('META-INF/MANIFEST.MF', b'Manifest-Version: 1.0\r\nMulti-Release: true\r\n\r\n')
            archive.writestr('dep/Library.class', products[0])
            archive.writestr('META-INF/versions/21/dep/Library.class', products[1])
            archive.writestr('resource.bin', b'unchanged\x00resource')
        unit = source / 'io/quux/otelc/methods/MethodMetrics.java';unit.parent.mkdir(parents=True)
        unit.write_text(COLLISION)
        check = ('if(dep.Library.value()!=3 || io.quux.otelc.methods.MethodMetrics.value()!=3)'
                 'throw new AssertionError("wrong archive or helper body");')
    (source / 'Counter.java').write_text(SOURCE.replace('ARCHIVE_CHECK', check))
    (source / 'Work.java').write_text(STATIC_SOURCE.replace('ARCHIVE_CHECK', check))
    (source / 'pom.xml').write_text('<project><!-- Preserved; not executed. --></project>\n')
    (source / 'gradle.lockfile').write_text('existing-lock=1\n')
    return source


def configuration(folder: Path, profile: str, *, start: int = 0, counter_only: bool = False) -> Path:
    """Freeze original inputs and the independently requested intermediate error."""
    text = 'schema_version=1\nlanguages=["java"]\n[adapters.java]\nbackend="prepared"\n'
    text += 'profile=' + json.dumps(profile) + '\nwitness_profile=' + json.dumps(PROFILE) + '\n'
    if profile == 'archive-methods-v1':
        text += 'source_roots=["."]\nclasspath=["lib/library.jar"]\n'
    text += '[functions]\ninclude=' + json.dumps([COUNTER] if counter_only else [COUNTER, STATIC]) + '\n'
    text += '[limits]\ncase_timeout_ms=60000\n'
    text += '[[fixtures]]\nfunction=' + json.dumps(COUNTER) + '\ncases=[[0]]\nreceiver={factory="make",arguments=[10]}\nsequence=[\n'
    for index, (amount, flags) in enumerate(zip((0, 3, -1, 1), states(start))):
        step = '{action="call",arguments=' + ('"case"' if index == 0 else '[' + str(amount) + ']')
        if index == 2:
            step += ',expected_baseline={kind="error",category="exception",type="java.lang.IllegalStateException"}'
        step += ',metrics={collection=' + str(flags['collection']).lower() + ',emission=' + str(flags['emission']).lower() + '}}'
        text += step + ',\n'
    text += ']\n'
    if not counter_only:
        text += '[[fixtures]]\nfunction=' + json.dumps(STATIC) + '\ncases=[[7]]\ndomains=[{kind="integer",minimum=0,maximum=7}]\n'
    path = folder / 'equivalence.toml';path.write_text(text)
    return path


def integer(value: int, *, scalar: bool = False) -> dict:
    return {'kind': 'integer', 'type': 'java.lang.Integer' if scalar else 'java.int',
            'value': str(value), 'bits': 32, 'signed': True}


def receiver_graph(actual: dict, value: int, total: int, amount: int, *, result: bool = False, error: bool = False) -> None:
    """Only local node labels come from observations; all values/aliases are fixed."""
    receiver = actual['roots']['receiver']
    reference = {'kind': 'reference', 'node_id': receiver['node_id']}
    roots = {'receiver': reference, 'argument:0': integer(amount), 'static:Counter.total': integer(total)}
    nodes = [{'id': reference['node_id'], 'type': 'java.object:Counter',
              'fields': {'value': integer(value), 'self': reference}}]
    if result:
        roots['result'] = reference
    if error:
        error_id = actual['roots']['error']['node_id']
        error_node = next(node for node in actual['nodes'] if node['id'] == error_id)
        message_id = error_node['fields']['message']['node_id']
        roots['error'] = {'kind': 'reference', 'node_id': error_id}
        nodes += [{'id': error_id, 'type': 'java.lang.IllegalStateException',
                   'fields': {'message': {'kind': 'reference', 'node_id': message_id}}},
                  {'id': message_id, 'type': 'java.object:java.lang.String',
                   'fields': {'value': {'kind': 'string', 'type': 'java.lang.String', 'encoding': 'utf16_be',
                                        'value': 'negative'.encode('utf-16-be').hex()}}}]
    assert actual == {'roots': roots, 'nodes': nodes}


def observation(observed: dict, function: str, amount: int, *, instrumented: bool,
                static_base: int = 10, static_return: int = 7) -> int:
    """Check complete literal graphs, not merely matching cross-lane values."""
    assert observed['function_id'] == function and observed['gaps'] == [] and observed['fixture'] == {'status': 'ready'}
    if function == COUNTER:
        assert amount == 0 and len(observed['steps']) == 4
        for index, step in enumerate(observed['steps']):
            before, after = (10, 10, 16, 16)[index], (10, 16, 16, 17)[index]
            total_before, total_after = (0, 1, 5, 6)[index], (1, 5, 6, 8)[index]
            argument, failed = (0, 3, -1, 1)[index], index == 2
            assert step['id'] == 'step-' + str(index) and step['action'] == 'call' and step['gaps'] == []
            receiver_graph(step['before'], before, total_before, argument)
            receiver_graph(step['after'], after, total_after, argument)
            receiver_graph(step['outcome']['graph'], after, total_after, argument, result=not failed, error=failed)
            assert set(step['outcome']) == ({'kind', 'graph', 'category'} if failed else {'kind', 'graph'})
            assert step['outcome']['kind'] == ('error' if failed else 'return')
            if failed:
                assert step['outcome']['category'] == 'exception'
        assert observed['before'] == observed['steps'][0]['before']
        assert observed['after'] == observed['steps'][-1]['after'] and observed['outcome'] == observed['steps'][-1]['outcome']
        return 12
    assert function == STATIC and type(amount) is int and 0 <= amount <= 7
    before = {'roots': {'global:Work.total': integer(static_base, scalar=True)}, 'nodes': []}
    after = {'roots': {'global:Work.total': integer(static_base + amount + instrumented, scalar=True)}, 'nodes': []}
    outcome = {'kind': 'return', 'graph': {'roots': {**after['roots'], 'result': integer(static_return, scalar=True)}, 'nodes': []}}
    assert observed['before'] == before and observed['after'] == after and observed['outcome'] == outcome
    return 3
