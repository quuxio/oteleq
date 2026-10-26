"""Exhaustive small-graph oracle independent of the implementation matcher."""
import copy
from itertools import combinations, permutations, product
import json
from pathlib import Path
import random
import sys
from unittest import mock

source = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-source-attribution/source-ecf80a9')
sys.path[:0] = [str(source), str(source/'tests')]
from otelc.python_code_comparison import compare
from otelc.python_code_index import decode
from test_python_code_index import graph, record


def label(node):
    return (node.kind, node.metadata, tuple(name for name, _ in node.fields),
            None if node.kind in ('code','tuple','frozenset','slice') else node.value,
            len(node.references))


def oracle(a, b):
    if len(a.nodes) != len(b.nodes):
        return False
    groups = {}
    for i,n in enumerate(a.nodes,1):
        groups.setdefault(label(n), [[],[]])[0].append(i)
    for i,n in enumerate(b.nodes,1):
        groups.setdefault(label(n), [[],[]])[1].append(i)
    if any(len(x)!=len(y) for x,y in groups.values()):
        return False
    for alternatives in product(*(list(permutations(y)) for x,y in groups.values())):
        mapping = {}
        for (left,_),right in zip(groups.values(),alternatives):
            mapping.update(zip(left,right))
        if mapping[a.root] != b.root:
            continue
        for i,node in enumerate(a.nodes,1):
            mapped = tuple(mapping[child] for child in node.references)
            actual = b.nodes[mapping[i]-1].references
            if (set(mapped) != set(actual) if node.kind=='frozenset' else mapped != actual):
                break
        else:
            return True
    return False


def fixture(subset, order, set_order, seed):
    data=graph()
    data['nodes'][1]['items']=[3,9,*order]
    data['nodes'].append({'id':9,'type':'frozenset','items':list(subset)[::set_order]})
    data['nodes'].extend({'id':i,'type':'float','data':'7ff8000000000001'} for i in (10,11,12))
    identities=list(range(1,13)); random.Random(seed).shuffle(identities)
    mapping=dict(zip(range(1,13),identities)); result=[None]*12
    for node in data['nodes']:
        node=copy.deepcopy(node); node['id']=mapping[node['id']]
        if 'items' in node: node['items']=[mapping[i] for i in node['items']]
        if 'fields' in node: node['fields']={k:mapping[v] for k,v in node['fields'].items()}
        result[node['id']-1]=node
    data['nodes']=result;data['root']=mapping[1]
    return decode(record(data))

values=[fixture(subset, order, direction, i) for i,(subset,order,direction) in enumerate(
    product(combinations((10,11,12),2),permutations((10,11,12)),(1,-1)))]
counts={'pairs':0,'match':0,'different':0}
for a,b in product(values,repeat=2):
    expected='match' if oracle(a,b) else 'different'
    result=compare(a,b)
    if result.status != expected:
        raise AssertionError((expected,result,a,b))
    counts['pairs']+=1;counts[expected]+=1
# Force every structural hash to collide; the exact matcher must still agree.
class Digest:
    def digest(self): return b'collision'
with mock.patch('otelc.python_code_comparison.hashlib.sha256',return_value=Digest()):
    for a,b in product(values[:12],repeat=2):
        if compare(a,b).status != ('match' if oracle(a,b) else 'different'):
            raise AssertionError('collision changed verdict')
counts['forced_collision_pairs']=144
Path(__file__).with_suffix('.json').write_text(json.dumps(counts,indent=2)+'\n')
print(json.dumps(counts))
