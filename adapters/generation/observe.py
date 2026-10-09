"""MIT-licensed generated Python graph observer. Never compare arbitrary repr output."""
import struct
MISSING = object()


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


class GraphEncoder:
    def __init__(self):
        self.nodes = []
        self.seen = {}

    def fields(self, state, depth):
        if type(state) is not dict:
            raise ValueError("opaque object state")
        return [[name, self.value(state[name], depth + 1)] for name in sorted(state)]

    def populate(self, node, item, depth):
        if isinstance(item, BaseException):
            node["args"] = self.value(object.__getattribute__(item, "args"), depth + 1)
            node["fields"] = self.fields(object.__getattribute__(item, "__dict__"), depth)
            node["cause"] = self.value(object.__getattribute__(item, "__cause__"), depth + 1)
            node["context"] = self.value(object.__getattribute__(item, "__context__"), depth + 1)
            node["suppress_context"] = object.__getattribute__(item, "__suppress_context__")
        elif type(item) in (list, tuple):
            node["items"] = [self.value(child, depth + 1) for child in item]
        elif type(item) is dict:
            # Insertion order is observable; keys are values, not lossy JSON object names.
            node["items"] = [[self.value(k, depth + 1), self.value(v, depth + 1)] for k, v in item.items()]
        elif hasattr(type(item), "__dict__") and type(item).__module__ not in ("builtins", "types"):
            node["fields"] = self.fields(object.__getattribute__(item, "__dict__"), depth)
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
        node = {"type": type(item).__module__ + "." + type(item).__qualname__}
        self.nodes.append(node)
        self.populate(node, item, depth)
        return {"ref": index}


def graph(roots):
    encoder = GraphEncoder()
    return {"roots": {name: encoder.value(item) for name, item in sorted(roots.items())}, "nodes": encoder.nodes}
