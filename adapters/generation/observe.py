"""MIT-licensed generated Python graph observer. Never compare arbitrary repr output."""
import struct
MISSING = object()


def graph(roots):
    nodes, seen = [], {}

    def value(item, depth=0):
        if item is MISSING:
            return {"type": "unbound"}
        if depth > 32 or len(nodes) >= 512:
            raise ValueError("observation graph limit exceeded")
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
        key = id(item)
        if key in seen:
            return {"ref": seen[key]}
        index = len(nodes)
        seen[key] = index
        node = {"type": type(item).__module__ + "." + type(item).__qualname__}
        nodes.append(node)
        if isinstance(item, BaseException):
            node["args"] = value(object.__getattribute__(item, "args"), depth + 1)
            state = object.__getattribute__(item, "__dict__")
            node["fields"] = [[name, value(state[name], depth + 1)] for name in sorted(state)]
            node["cause"] = value(object.__getattribute__(item, "__cause__"), depth + 1)
            node["context"] = value(object.__getattribute__(item, "__context__"), depth + 1)
            node["suppress_context"] = object.__getattribute__(item, "__suppress_context__")
        elif type(item) in (list, tuple):
            node["items"] = [value(child, depth + 1) for child in item]
        elif type(item) is dict:
            # Insertion order is observable; keys are values, not lossy JSON object names.
            node["items"] = [[value(k, depth + 1), value(v, depth + 1)] for k, v in item.items()]
        elif hasattr(type(item), "__dict__") and type(item).__module__ not in ("builtins", "types"):
            state = object.__getattribute__(item, "__dict__")
            if type(state) is not dict:
                raise ValueError("opaque object state")
            node["fields"] = [[name, value(state[name], depth + 1)] for name in sorted(state)]
        else:
            raise ValueError("opaque value: " + node["type"])
        return {"ref": index}
    return {"roots": {name: value(item) for name, item in sorted(roots.items())}, "nodes": nodes}
