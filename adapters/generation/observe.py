"""MIT-licensed generated Python graph observer. Never compare arbitrary repr output."""
import struct
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import CodeType, FunctionType, GetSetDescriptorType, MemberDescriptorType, MethodType, ModuleType
MISSING = object()


def function_code(source: Path, name: str, line: int, *, cached: bool = False) -> CodeType:
    """Freeze the selected body before import, without executing its module."""
    source = source.resolve(strict=True)
    if cached:
        if not sys.dont_write_bytecode:
            raise ValueError("cache-aware binding requires disabled bytecode writes")
        # Preserve the ordinary loader's cache decision, including unchecked hashes.
        compiled = SourceFileLoader('_oteleq_expected', str(source)).get_code('_oteleq_expected')
    else:
        compiled = compile(source.read_bytes(), str(source), "exec", dont_inherit=True,
                           optimize=sys.flags.optimize)
    pending, matches = [compiled], []
    while pending:
        code = pending.pop()
        if code.co_qualname == name and code.co_firstlineno == line:
            matches.append(code)
        pending.extend(item for item in code.co_consts if type(item) is CodeType)
    if len(matches) != 1:
        raise ValueError("selected function has no unique source code identity")
    return matches[0]


def bound_function(module: ModuleType, name: str, expected: CodeType) -> FunctionType:
    """Refuse replaced callables without invoking application lookup hooks."""
    if type(module) is not ModuleType:
        raise ValueError("selected function module requires a binding fixture")
    namespace = vars(module)
    target = namespace.get(name)
    return checked_function(target, namespace, expected)


def checked_function(target: object, namespace: dict, expected: CodeType) -> FunctionType:
    """The declared source body must still be the directly bound function."""
    if (type(target) is not FunctionType or target.__globals__ is not namespace
            or target.__code__ != expected
            or target.__code__.co_filename != expected.co_filename
            or target.__code__.co_firstlineno != expected.co_firstlineno):
        raise ValueError("selected function binding differs from its frozen source identity")
    return target


def bound_receiver(module: ModuleType, owner: str, name: str, expected: CodeType,
                   fixture: dict, factory_code: CodeType | None) -> tuple[object, MethodType]:
    """Construct independently and bind through class storage without lookup hooks."""
    if type(module) is not ModuleType:
        raise ValueError("receiver requires an ordinary source module")
    namespace = vars(module)
    cls = namespace.get(owner)
    if type(cls) is not type:
        raise ValueError("receiver class requires its ordinary source type")
    if type.__dict__["__mro__"].__get__(cls) != (cls, object):
        raise ValueError("receiver inherited class state requires an observation fixture")
    checked_function(class_members(cls).get(name), namespace, expected)
    instance = construct_receiver(module, cls, fixture, factory_code)
    if type(instance) is not cls or namespace.get(owner) is not cls:
        raise ValueError("receiver factory returned a different source class")
    _, origin, qualified = runtime_type(instance)
    if type(namespace.get("__name__")) is not str or origin != namespace["__name__"] or qualified != owner:
        raise ValueError("receiver class identity differs from its source declaration")
    target = checked_function(class_members(cls).get(name), namespace, expected)
    return instance, MethodType(target, instance)


def construct_receiver(module: ModuleType, cls: type, fixture: dict, expected: CodeType | None) -> object:
    """Only direct plain constructors or frozen ordinary factory functions are called."""
    if fixture["kind"] == "function":
        return bound_function(module, fixture["factory"], expected)(*fixture["arguments"])
    members = class_members(cls)
    if "__new__" in members:
        raise ValueError("receiver constructor needs a plain class without custom allocation")
    if expected is None:
        if "__init__" in members:
            raise ValueError("receiver constructor differs from its implicit source declaration")
    else:
        checked_function(members.get("__init__"), vars(module), expected)
    return cls(*fixture["arguments"])


def bound_method(module: ModuleType, owner: str, name: str, instance: object,
                 expected: CodeType, expected_class: type) -> MethodType:
    """Recheck an existing source receiver without reconstructing or invoking lookup hooks."""
    if type(module) is not ModuleType:
        raise ValueError("receiver requires an ordinary source module")
    namespace = vars(module)
    cls = namespace.get(owner)
    if (cls is not expected_class or type(cls) is not type or type(instance) is not cls
            or type.__dict__["__mro__"].__get__(cls) != (cls, object)):
        raise ValueError("receiver class binding differs from its frozen source identity")
    _, origin, qualified = runtime_type(instance)
    if type(namespace.get("__name__")) is not str or origin != namespace["__name__"] or qualified != owner:
        raise ValueError("receiver class identity differs from its source declaration")
    state = instance_state(instance)
    if any(type(key) is not str for key in state) or name in state:
        raise ValueError("receiver method is shadowed by instance storage")
    target = checked_function(class_members(cls).get(name), namespace, expected)
    return MethodType(target, instance)


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
        members = class_members(base)
        if name in members:
            return members[name]
    return None


def class_members(cls: type):
    """Read normal metadata keys without descriptor or key comparison hooks."""
    members = type.__dict__["__dict__"].__get__(cls)
    if any(type(key) is not str for key in members):
        raise ValueError("class metadata keys require an observation fixture")
    return members


def supported_storage(cls: type, base: type) -> None:
    """Unknown native storage cannot masquerade as a complete dictionary view."""
    members = class_members(base)
    if "__slots__" in members:
        raise ValueError("slotted state requires an observation fixture")
    native_fields = any(type(value) in (GetSetDescriptorType, MemberDescriptorType)
                        and name not in ("__dict__", "__weakref__") for name, value in members.items())
    if base not in (BaseException, object) and native_fields:
        raise ValueError("native instance fields require an observation fixture")
    module = type.__dict__["__module__"].__get__(base)
    if type(module) is not str:
        raise ValueError("base class identity requires an observation fixture")
    if base not in (cls, object) and module in ("builtins", "types") and not issubclass(cls, BaseException):
        raise ValueError("builtin base state requires an observation fixture")


def instance_state(item: object) -> object:
    """Read the builtin instance dictionary; never evaluate an override."""
    cls = type(item)
    for base in type.__dict__["__mro__"].__get__(cls):
        supported_storage(cls, base)
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
        return [[name, self.value(value, depth + 1)] for name, value in state.items()]

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
