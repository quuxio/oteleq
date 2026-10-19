"""MIT-licensed generated Python graph observer. Never compare arbitrary repr output."""
import struct
import sys
from pathlib import Path
from types import CodeType, FunctionType, GetSetDescriptorType, ModuleType
MISSING = object()


def function_code(source: Path, name: str, line: int) -> CodeType:
    """Compile without execution before import to freeze the selected body."""
    source = source.resolve(strict=True)
    compiled = compile(source.read_bytes(), str(source), "exec", dont_inherit=True,
                       optimize=sys.flags.optimize)
    matches = [item for item in compiled.co_consts if type(item) is CodeType
               and item.co_name == name and item.co_firstlineno == line]
    if len(matches) != 1:
        raise ValueError("selected function has no unique source code identity")
    return matches[0]


def bound_function(module: ModuleType, name: str, expected: CodeType) -> FunctionType:
    """Refuse replaced callables without invoking application lookup hooks."""
    if type(module) is not ModuleType:
        raise ValueError("selected function module requires a binding fixture")
    namespace = vars(module)
    target = namespace.get(name)
    if (type(target) is not FunctionType or target.__globals__ is not namespace
            or target.__code__ != expected
            or target.__code__.co_filename != expected.co_filename
            or target.__code__.co_firstlineno != expected.co_firstlineno):
        raise ValueError("selected function binding differs from its frozen source identity")
    return target


def scalar(item):
    if item is MISSING:
        return {"type": "unbound"}
    if item is None:
        return {"type": "null"}
    if type(item) is bool:
        return {"type": "bool", "value": item}
    if type(item) is int:
        return {"type": "int", "value": str(item)}
    if type(item) is float:
        return {"type": "float64", "bits": struct.pack(">d", item).hex()}
    if type(item) is str:
        return {"type": "str", "value": item}
    if type(item) is bytes:
        return {"type": "bytes", "value": item.hex()}
    return None


def runtime_type(item: object) -> tuple[type, str, str]:
    """Read class metadata only through the ordinary builtin metaclass."""
    cls = type(item)
    if type(cls) is not type:
        raise ValueError("custom metaclass requires an observation fixture")
    module = type.__dict__["__module__"].__get__(cls)
    name = type.__dict__["__qualname__"].__get__(cls)
    if type(module) is not str or type(name) is not str:
        raise ValueError("non-string class identity requires a fixture")
    return cls, module, name


def class_member(cls: type, name: str) -> object | None:
    """Find a descriptor without invoking properties or dynamic lookup."""
    for base in type.__dict__["__mro__"].__get__(cls):
        members = type.__dict__["__dict__"].__get__(base)
        if name in members:
            return members[name]
    return None


def instance_state(item: object) -> object:
    """Read the builtin instance dictionary; never evaluate an override."""
    cls = type(item)
    descriptor = class_member(cls, "__dict__")
    if type(descriptor) is not GetSetDescriptorType:
        raise ValueError("instance dictionary descriptor requires a fixture")
    return descriptor.__get__(item, cls)


def exception_field(item: object, name: str) -> object:
    """Only builtin exception storage is qualified for these fields."""
    descriptor = BaseException.__dict__[name]
    if class_member(type(item), name) is not descriptor:
        raise ValueError("exception field descriptor requires a fixture: " + name)
    return descriptor.__get__(item, type(item))


class GraphEncoder:
    def __init__(self):
        self.nodes = []
        self.seen = {}

    def fields(self, state, depth):
        if type(state) is not dict:
            raise ValueError("opaque object state")
        if any(type(name) is not str for name in state):
            raise ValueError("non-string object field requires a fixture")
        return [[name, self.value(state[name], depth + 1)] for name in sorted(state)]

    def populate(self, node, item, depth):
        cls, module, _ = runtime_type(item)
        if issubclass(cls, BaseException):
            node["args"] = self.value(exception_field(item, "args"), depth + 1)
            node["fields"] = self.fields(instance_state(item), depth)
            node["cause"] = self.value(exception_field(item, "__cause__"), depth + 1)
            node["context"] = self.value(exception_field(item, "__context__"), depth + 1)
            node["suppress_context"] = exception_field(item, "__suppress_context__")
        elif type(item) in (list, tuple):
            node["items"] = [self.value(child, depth + 1) for child in item]
        elif type(item) is dict:
            # Insertion order is observable; keys are values, not lossy JSON object names.
            node["items"] = [[self.value(k, depth + 1), self.value(v, depth + 1)] for k, v in item.items()]
        elif module not in ("builtins", "types"):
            node["fields"] = self.fields(instance_state(item), depth)
        else:
            raise ValueError("opaque value: " + node["type"])

    def value(self, item, depth=0):
        if depth > 32 or len(self.nodes) >= 512:
            raise ValueError("observation graph limit exceeded")
        primitive = scalar(item)
        if primitive is not None:
            return primitive
        key = id(item)
        if key in self.seen:
            return {"ref": self.seen[key]}
        index = len(self.nodes)
        self.seen[key] = index
        _, module, name = runtime_type(item)
        node = {"type": module + "." + name}
        self.nodes.append(node)
        self.populate(node, item, depth)
        return {"ref": index}


def graph(roots):
    if type(roots) is not dict or any(type(name) is not str for name in roots):
        raise ValueError("observation roots require a string-keyed dictionary")
    encoder = GraphEncoder()
    return {"roots": {name: encoder.value(item) for name, item in sorted(roots.items())}, "nodes": encoder.nodes}
