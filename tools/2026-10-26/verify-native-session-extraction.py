"""Prove the native session operations are preserved by shared helper extraction."""

import ast
import copy
from pathlib import Path
import subprocess


def shape(value) -> str:
    return ast.dump(value, include_attributes=False)


def verify(root: Path) -> dict:
    previous = subprocess.check_output(['git', 'show',
        'b9f7c6c7fad6db6d48c24af1f7a75d1557615de7:adapters/generation/native_session.py'], cwd=root, text=True)
    old = ast.parse(previous)
    new = ast.parse((root / 'adapters/generation/native_session.py').read_text())
    old_functions = {node.name: node for node in old.body if isinstance(node, ast.FunctionDef)}
    new_functions = {node.name: node for node in new.body if isinstance(node, ast.FunctionDef)}
    for name in ('kernel', 'publish'):
        assert shape(old_functions[name]) == shape(new_functions[name]), name
    original = next(node for node in old.body if isinstance(node, ast.ClassDef) and node.name == 'Session')
    current = next(node for node in new.body if isinstance(node, ast.ClassDef) and node.name == 'Session')
    methods = {node.name: node for node in original.body if isinstance(node, ast.FunctionDef)}
    body = methods['poll'].body
    first = next(i for i, node in enumerate(body) if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'supervisor')
    extracted = copy.deepcopy(new_functions['observed_owner'].body[1:-1])

    class Reason(ast.NodeTransformer):
        def visit_Name(self, node):
            return ast.Constant('native application is not the live owned waiting child') if node.id == 'reason' else node

    extracted = [Reason().visit(node) for node in extracted]
    assert [shape(node) for node in body[first:first + 3]] == [shape(node) for node in extracted]
    methods['poll'].body = body[:first] + ast.parse('supervisor, application = observed_owner(process, pid, deadline)').body + body[first + 3:]

    class Child(ast.NodeTransformer):
        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == 'self' and node.attr == 'child':
                return ast.Name(id='child', ctx=node.ctx)
            return self.generic_visit(node)

    extracted = [Child().visit(copy.deepcopy(node)) for node in methods['close'].body[1:]]
    assert [shape(node) for node in extracted] == [shape(node) for node in new_functions['close_child'].body[1:]]
    methods['close'].body = methods['close'].body[:1] + ast.parse('close_child(self.child)').body
    assert shape(original) == shape(current), 'native Session has another code change'

    class Close(ast.NodeTransformer):
        def visit_Call(self, node):
            if (isinstance(node.func, ast.Attribute) and node.func.attr == 'close'
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == 'session'):
                return ast.Call(func=ast.Name(id='close', ctx=ast.Load()), args=[], keywords=[])
            return self.generic_visit(node)

    prior_retained = old_functions['retained']
    cleanup = [Close().visit(copy.deepcopy(node)) for node in prior_retained.body[2:]]
    assert [shape(node) for node in cleanup] == [shape(node) for node in new_functions['cleanup'].body[1:]]
    replacement = ast.parse('with cleanup(lambda: session.close()):\n    yield').body
    prior_retained.body = prior_retained.body[:2] + replacement
    assert shape(prior_retained) == shape(new_functions['retained'])
    return {'status': 'pass', 'kernel_and_publisher': 'identical AST',
            'ownership_barrier': 'identical operations and original deadline/condition order',
            'child_group_cleanup': 'identical operations after self.child parameter substitution',
            'exception_cleanup': 'identical primary-error preservation; late method lookup retained',
            'native_session': 'no other class or retained-wrapper operation change'}
