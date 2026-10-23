"""Literal source and independent complete graph oracles for Python sequences."""

ACTIVE = '"quux.otelc" in tuple(sys.monitoring.get_tool(index) for index in range(6))'
METHODS = ('identity', 'secret', 'transient', 'fail', 'recursive', 'touch')
SOURCE = '''import sys
created=0
class Counter:
 total=0
 instances=0
 shared=[]
 def __init__(self,start:int):
  global created
  created+=1
  Counter.instances+=1
  self.value=start
  self.alias=self
  self.shared=Counter.shared
  self.calls=0
  self._token=99
 def _change(self,amount:int):
  self.value+=amount
  self.calls+=1
  Counter.total+=amount
  Counter.shared.append(amount)
 def identity(self,amount:int):
  self._change(amount)
  return self
 def secret(self,amount:int)->int:
  self._change(amount)
  return self.value
 def transient(self,amount:int)->int:
  self._change(amount)
  if amount==2:
   self.value=19
   Counter.total=9
  else:self.value+=int(ACTIVE)
  return 7
 def fail(self,amount:int)->int:
  self._change(amount)
  if amount!=2:raise ValueError("expected")
  return 7
 def recursive(self,amount:int)->int:
  if amount>0:self.recursive(0)
  self._change(amount)
  return 7
 def touch(self,amount:int):
  self._change(amount)
def make_counter(start:int)->Counter:
 return Counter(start)
'''.replace('ACTIVE', ACTIVE)
COMPACT_SOURCE = '''class Counter:
 total=0
 def __init__(self,start:int):
  self.value=start
  self.alias=self
  self.calls=0
 def identity(self,amount:int)->int:
  self.value+=amount
  self.calls+=1
  Counter.total+=amount
  return self.value
'''
BUDGET_SOURCE = SOURCE.replace('  self._token=99', '  self._token=99\n  self.padding=[0]*128')


def function(method: str) -> str:
    return 'src.pkg.state.Counter.' + method


FUNCTIONS = {function(method): method for method in METHODS}


def integer(value: int) -> dict:
    return {'type': 'int', 'value': str(value)}


def graph(state: dict, argument: int, *, outcome: str | None = None,
          result: int | None = None, compact: bool = False, padding: bool = False) -> dict:
    """Allocate only the declared fixture's literal nodes, independently of codecs."""
    nodes = [{'type': 'builtins.list', 'items': [integer(argument)]}]
    roots = {'arguments': {'ref': 0}}
    if outcome == 'error':
        roots['error'] = {'ref': len(nodes)}
        nodes.extend([
            {'type': 'builtins.ValueError', 'args': {'ref': len(nodes) + 1},
             'fields': [], 'cause': {'type': 'null'}, 'context': {'type': 'null'},
             'suppress_context': False},
            {'type': 'builtins.tuple', 'items': [{'type': 'str', 'value': 'expected'}]},
        ])
    if not compact:
        roots['global:created'] = integer(1)
    receiver = {'ref': len(nodes)}
    fields = [['value', integer(state['value'])], ['alias', receiver]]
    nodes.append({'type': 'pkg.state.Counter', 'fields': fields})
    roots['receiver'] = receiver
    if not compact:
        shared = {'ref': len(nodes)}
        nodes.append({'type': 'builtins.list', 'items': [integer(value) for value in state['history']]})
        fields.append(['shared', shared])
    fields.append(['calls', integer(state['calls'])])
    if not compact:
        fields.append(['_token', integer(99)])
    if padding:
        fields.append(['padding', {'ref': len(nodes)}])
        nodes.append({'type': 'builtins.list', 'items': [integer(0) for _ in range(128)]})
    if outcome == 'identity':
        roots['result'] = receiver
    elif outcome == 'return':
        roots['result'] = {'type': 'null'} if result is None else integer(result)
    if not compact:
        roots['static:Counter.instances'] = integer(1)
        roots['static:Counter.shared'] = shared
    roots['static:Counter.total'] = integer(state['total'])
    return {'roots': roots, 'nodes': nodes}


def raw_observation(method: str, amount: int, active: bool, *, steps: int = 2,
                    compact: bool = False, padding: bool = False) -> dict:
    """Specify every expected field, alias and intermediate application result."""
    assert method in METHODS and type(amount) is int and 0 <= amount <= 7
    assert steps in (1, 2, 32) and (not compact or method == 'identity')
    state = {'value': 10, 'total': 0, 'calls': 0, 'history': []}
    observations = []
    for index, argument in enumerate([amount] + [2 if steps == 2 else 0] * (steps - 1)):
        before = graph(state, argument, compact=compact, padding=padding)
        changes = [0, argument] if method == 'recursive' and argument > 0 else [argument]
        for value in changes:
            state['value'] += value
            state['total'] += value
            state['calls'] += 1
            state['history'].append(value)
        if method == 'transient':
            if argument == 2:
                state['value'], state['total'] = 19, 9
            else:
                state['value'] += int(active)
        error = method == 'fail' and argument != 2
        outcome = 'error' if error else 'identity' if method == 'identity' and not compact else 'return'
        result = state['value'] if method == 'secret' or compact else None if method == 'touch' else 7
        observations.append({
            'id': 'step-' + str(index), 'action': 'call', 'gaps': [], 'before': before,
            'outcome': {'kind': 'error' if error else 'return',
                        'value': graph(state, argument, outcome=outcome, result=result,
                                       compact=compact, padding=padding)},
            'after': graph(state, argument, compact=compact, padding=padding),
        })
    return {'before': observations[0]['before'], 'outcome': observations[-1]['outcome'],
            'after': observations[-1]['after'], 'steps': observations}


def typed_value(value: dict) -> dict:
    """Encode the fixed fixture's expected values without a product encoder."""
    if set(value) == {'ref'}:
        return {'kind': 'reference', 'node_id': 'n' + str(value['ref'])}
    if value['type'] == 'int':
        return {'kind': 'integer', 'type': 'python.int', 'value': value['value'],
                'bits': None, 'signed': True}
    if value['type'] == 'str':
        return {'kind': 'string', 'type': 'python.string', 'encoding': 'codepoints32_be',
                'value': ''.join(format(ord(char), '08x') for char in value['value'])}
    assert value == {'type': 'null'}
    return {'kind': 'null'}


def typed_graph(raw: dict) -> dict:
    nodes = []
    for index, node in enumerate(raw['nodes']):
        fields = {}
        for item, value in enumerate(node.get('items', [])):
            fields['item:' + str(item)] = typed_value(value)
        for item, (name, value) in enumerate(node.get('fields', [])):
            fields['order:' + str(item)] = typed_value({'type': 'str', 'value': name})
            fields['property:' + name] = typed_value(value)
        if node['type'] == 'builtins.ValueError':
            fields.update({'exception:' + name: typed_value(node[name])
                           for name in ('args', 'cause', 'context')})
            fields['exception:suppress_context'] = {'kind': 'boolean', 'value': False}
        nodes.append({'id': 'n' + str(index), 'type': 'python.' + node['type'], 'fields': fields})
    return {'roots': {name: typed_value(value) for name, value in raw['roots'].items()}, 'nodes': nodes}


def boundaries(raw: dict) -> dict:
    outcome = {'kind': raw['outcome']['kind'], 'graph': typed_graph(raw['outcome']['value'])}
    if outcome['kind'] == 'error':
        outcome['category'] = 'exception'
    return {'before': typed_graph(raw['before']), 'outcome': outcome, 'after': typed_graph(raw['after'])}


def check_observation(observed: dict, method: str, amount: int, active: bool,
                      *, steps: int = 2, compact: bool = False) -> None:
    raw = raw_observation(method, amount, active, steps=steps, compact=compact)
    expected = boundaries(raw)
    expected['steps'] = [{'id': step['id'], 'action': 'call', 'gaps': [], **boundaries(step)}
                         for step in raw['steps']]
    assert not observed['gaps']
    for name, value in expected.items():
        assert observed[name] == value, (method, amount, active, name)


def node(graph: dict, reference: dict) -> dict:
    return next(value for value in graph['nodes'] if value['id'] == reference['node_id'])
