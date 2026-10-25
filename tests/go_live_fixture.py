"""Fixed Go live-control workload and complete, independently authored graphs."""

import json

STARTS = ('both-on', 'collection-off', 'emission-off', 'both-off')
STATES = ((True, True), (False, True), (True, False), (False, False))
METHODS = ('identity', 'transient')
NAMES = {'identity': 'Step', 'transient': 'Transient', 'added': 'Added'}
FUNCTIONS = {'counter.api.Counter.' + NAMES[name]: name for name in METHODS}
SHADOWS = ('any', 'bool', 'false', 'int', 'nil', 'panic', 'true')
ROOTS = {'argument:0', 'receiver', 'global:shared', 'global:total',
         *('global:' + name for name in SHADOWS)}

DOMAIN = '''package domain
import "runtime/debug"
type Number = int
func Fail(){panic("known")}
func HasSDK()bool{info,ok:=debug.ReadBuildInfo();if !ok{return false};for _,dep:=range info.Deps{if dep.Path=="io.quux.otelc/go"{return true}};return false}
'''
SOURCE = '''package counter
import "example.test/live/domain"
var nil, any, int, bool, panic, true, false domain.Number
type Counter struct {value domain.Number;calls domain.Number;self *Counter}
var shared *Counter
var total domain.Number
func New(seed domain.Number)*Counter{value:=&Counter{value:seed};value.self=value;shared=value;return value}
func (value *Counter) Step(amount domain.Number)domain.Number{value.calls++;value.value+=amount;total+=amount;if amount<0{domain.Fail()};return value.value}
func (value *Counter) Transient(amount domain.Number)domain.Number{value.calls++;value.value+=amount;total+=amount;if domain.HasSDK(){if value.calls==1{value.value++};if value.calls==2{value.value--}};if amount<0{domain.Fail()};return 42}
'''


def exact(actual: object, expected: object) -> None:
    """JSON booleans, integers and floating-point values remain distinct."""
    encode = lambda value: json.dumps(value, sort_keys=True, allow_nan=False,
                                     separators=(',', ':'))
    if encode(actual) != encode(expected):
        raise ValueError('Go live evidence differs from its independent expectation')


def function(method: str) -> str:
    return 'counter.api.Counter.' + NAMES[method]


def runtime_function(method: str) -> str:
    return 'example.test/live/counter.Counter.' + NAMES[method]


def states(start: str) -> tuple[dict, ...]:
    """Cover every flag pair and finish with collected, temporarily held errors."""
    initial = STATES[STARTS.index(start)]
    return tuple({'collection': a, 'emission': b}
                 for a, b in (initial, STATES[0], STATES[1], STATES[3], STATES[2]))


def sources(*, changed: bool = False) -> dict[str, bytes]:
    text = SOURCE
    if changed:
        text = text.replace('return value.value}', 'return value.value+100}')
        text = text.replace('return 42}', 'return 142}')
        added = SOURCE.split('func (value *Counter) Step', 1)[1].split('\n', 1)[0]
        text += 'func (value *Counter) Added' + added.replace('return value.value}', 'return value.value+100}') + '\n'
    return {'go.mod': b'module example.test/live\n\ngo 1.27.2\n',
            'domain/types.go': DOMAIN.encode(), 'counter/api.go': text.encode()}


def policy(start: str) -> str:
    """One wildcard fixture must also discover the newly promoted method."""
    text = ('schema_version=1\nlanguages=["go"]\n[adapters.go]\n'
            'backend="source-scope-v1"\nmodule_roots=["."]\nbuild_timeout_ms=900000\n'
            '[limits]\ncase_timeout_ms=60000\n[functions]\ninclude='
            + json.dumps([function(name) for name in (*METHODS, 'added')]) + '\n'
            '[[fixtures]]\nfunction="counter.api.Counter.*"\ncases=[[7]]\n'
            'receiver={factory="New",arguments=[10]}\n'
            'domains=[{kind="integer",minimum=0,maximum=7}]\nsequence=[\n')
    for index, (flags, arguments) in enumerate(zip(states(start), ('"case"', '[2]', '[4]', '[1]', '[-2]'))):
        expectation = ('{kind="error",category="panic",type="go.string"}'
                       if index == 4 else '{kind="return"}')
        text += ('{action="call",arguments=' + arguments + ',expected_baseline=' + expectation
                 + ',metrics={collection=' + str(flags['collection']).lower()
                 + ',emission=' + str(flags['emission']).lower() + '}},\n')
    return text + ']\n'


def number(value: int) -> dict:
    return {'kind': 'integer', 'type': 'go.int', 'bits': 64,
            'signed': True, 'value': str(value)}


def reference(index: int) -> dict:
    return {'kind': 'reference', 'node_id': 'n' + str(index)}


def graph(value: int, total: int, calls: int, amount: int, *,
          outcome: str | None = None, result: int | None = None) -> dict:
    """Include all slots, locations, self cycles and first-field address aliases."""
    nodes = {}
    roots = {'argument:0': number(amount), 'receiver': reference(14),
             'global:shared': reference(12)}

    def node(index: int, kind: str, fields: dict) -> None:
        nodes[index] = {'id': 'n' + str(index), 'type': kind, 'fields': fields}

    def location(index: int) -> None:
        node(index, 'go.location', {})

    def scalar(index: int, value: int, address: int) -> None:
        node(index, 'go.storage:*int', {'location': reference(address), 'value': number(value)})
        location(address)

    for name, index in zip(SHADOWS, (0, 2, 4, 6, 8, 10, 24)):
        scalar(index, 0, index + 1)
        roots['global:' + name] = reference(index)
    node(12, 'go.storage:**example.test/live/counter.Counter',
         {'location': reference(13), 'value': reference(14)})
    location(13)
    node(14, 'go.storage:*example.test/live/counter.Counter',
         {'location': reference(15), 'value': reference(16)})
    location(15)
    node(16, 'go.storage:example.test/live/counter.Counter',
         {'value': reference(17), 'calls': reference(18), 'self': reference(20)})
    scalar(17, value, 15)
    scalar(18, calls, 19)
    node(20, 'go.storage:**example.test/live/counter.Counter',
         {'location': reference(21), 'value': reference(14)})
    location(21)
    scalar(22, total, 23)
    roots['global:total'] = reference(22)
    if outcome == 'return':
        roots['result'] = number(value if result is None else result)
    elif outcome == 'error':
        roots['error'] = {'kind': 'string', 'type': 'go.string',
                          'encoding': 'raw_bytes', 'value': '6b6e6f776e'}
    exact(sorted(nodes), list(range(26)))
    return {'nodes': [nodes[index] for index in range(26)], 'roots': roots}


def observation(method: str, amount: int, active: bool, case: str,
                fixture: str, *, changed: bool = False) -> dict:
    """Return the whole expected observation, including every intermediate edge."""
    steps, total = [], 0
    for index, argument in enumerate((amount, 2, 4, 1, -2)):
        before_delta = int(active and method == 'transient' and index == 1)
        before = graph(10 + total + before_delta, total, index, argument)
        total += argument
        after_delta = int(active and method == 'transient' and index == 0)
        value = 10 + total + after_delta
        after = graph(value, total, index + 1, argument)
        kind = 'error' if index == 4 else 'return'
        result = (42 if method == 'transient' else value) + (100 if changed else 0)
        outcome = {'kind': kind, 'graph': graph(value, total, index + 1, argument,
                                               outcome=kind, result=result)}
        if kind == 'error':
            outcome['category'] = 'panic'
        steps.append({'id': 'step-' + str(index), 'action': 'call', 'gaps': [],
                      'before': before, 'after': after, 'outcome': outcome})
    return {'observation_schema_version': 1, 'case_id': case,
            'function_id': runtime_function(method), 'fixture_sha256': fixture,
            'fixture': {'status': 'ready'}, 'gaps': [], 'steps': steps,
            'before': steps[0]['before'], 'after': steps[-1]['after'],
            'outcome': steps[-1]['outcome']}
