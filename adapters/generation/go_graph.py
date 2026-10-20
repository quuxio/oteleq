"""Validate complete source-bound Go storage graphs before comparison."""
from collections import deque

from otelc_capture import strict_json

STORAGE_PREFIX = "go.storage:"

def require(condition: bool, reason: str) -> None:
    """A missing or unsupported observation cannot become an equivalence verdict."""
    if not condition:
        raise ValueError("typed capture: Go " + reason)


def hex_value(text: object, maximum: int) -> bool:
    """Only complete canonical lowercase byte encodings are admitted."""
    return (isinstance(text, str) and len(text) <= maximum and len(text) % 2 == 0
            and all(char in "0123456789abcdef" for char in text))


def integer(value: dict, model: dict) -> None:
    """Require a complete canonical decimal within its nominal storage width."""
    require(set(value) == {"kind", "type", "value", "bits", "signed"}
            and type(value["bits"]) is int and value["bits"] == model["bits"]
            and type(value["signed"]) is bool and value["signed"] == model["signed"], "integer storage differs")
    text, bits, signed = value["value"], model["bits"], model["signed"]
    require(type(text) is str and 0 < len(text) <= 20, "invalid integer value")
    number = int(text)
    low, high = (-2**(bits-1), 2**(bits-1)-1) if signed else (0, 2**bits-1)
    require(text == str(number) and low <= number <= high, "integer exceeds its declaration")


def primitive(value: dict, name: str, model: dict) -> None:
    """Retain declared integer widths, float bits and arbitrary string bytes."""
    require(type(value) is dict and value.get("type") == "go." + name, "primitive source type differs")
    kind = model["kind"]
    require(value.get("kind") == kind, "primitive kind differs")
    if kind == "integer":
        integer(value, model)
    elif kind == "boolean":
        require(set(value) == {"kind", "type", "value"} and type(value["value"]) is bool, "invalid boolean")
    elif kind == "float":
        width = model["bits"] // 4
        require(set(value) == {"kind", "type", "bits"} and hex_value(value["bits"], width)
                and len(value["bits"]) == width, "float bits differ")
        if model["bits"] == 32:
            bits = int(value["bits"], 16)
            require(bits & 0x7F800000 != 0x7F800000 or bits & 0x007FFFFF == 0,
                    "float32 NaN payload is outside this reflection profile")
    else:
        require(kind == "string" and set(value) == {"kind", "type", "encoding", "value"}
                and value["encoding"] == "raw_bytes" and hex_value(value["value"], 131072), "invalid string bytes")


def panic_value(value: dict) -> None:
    """Panic primitives keep type/value without invoking Error or String."""
    require(type(value) is dict and type(value.get("type")) is str
            and value["type"].startswith("go.") and 3 < len(value["type"]) <= 1027,
            "unsupported panic payload")
    kind = value.get("kind")
    model = {"kind": kind}
    if kind in ("integer", "float"):
        bits = value.get("bits")
        if kind == "float":
            require(type(bits) is str and len(bits) in (8, 16), "invalid panic float")
            model["bits"] = len(bits) * 4
        else:
            require(type(bits) is int and bits in (8, 16, 32, 64)
                    and type(value.get("signed")) is bool, "invalid panic integer")
            model.update(bits=bits, signed=value["signed"])
    require(kind in ("integer", "float", "boolean", "string"), "panic storage requires another codec")
    primitive(value, value["type"].removeprefix("go."), model)


class Schema:
    """Validate each memory slot and value against the frozen type registry."""

    def __init__(self, entry: dict) -> None:
        self.models = entry["go_models"]

    def value(self, value: dict, expected: str, nodes: dict) -> None:
        """Go has exact nominal storage types; pointer absence is explicit."""
        require(type(value) is dict, "value must be tagged")
        if expected == "void":
            require(value == {"kind": "undefined"}, "invalid void result")
            return
        require(expected in self.models, "storage type is unbound")
        model = self.models[expected]
        if model["kind"] in ("pointer", "array", "struct"):
            if value == {"kind": "null"}:
                require(model["kind"] == "pointer", "absent non-pointer storage")
                return
            require(set(value) == {"kind", "node_id"} and value["kind"] == "reference"
                    and type(value["node_id"]) is str and value["node_id"] in nodes,
                    "missing storage reference")
            require(nodes[value["node_id"]]["type"] == STORAGE_PREFIX + expected, "reference type differs")
        else:
            primitive(value, expected, model)

    def fields(self, node: dict) -> dict[str, str]:
        """Struct/array members are addressable slots, preserving interior aliases."""
        label = node["type"]
        require(type(label) is str and label.startswith(STORAGE_PREFIX), "unbound storage node")
        name = label.removeprefix(STORAGE_PREFIX)
        require(name in self.models, "node lacks a source storage declaration")
        model = self.models[name]
        if model["kind"] == "pointer":
            return {"value": model["element"]}
        if model["kind"] == "struct":
            return {field["name"]: "*" + field["type"] for field in model["fields"]}
        require(model["kind"] == "array", "primitive cannot substitute a storage node")
        return {"item:" + str(i): "*" + model["element"] for i in range(model["length"])}

    def graph(self, graph: dict, roots: dict[str, str], *, panic: bool = False) -> dict:
        """Require exact roots, field coverage and reachable bounded node storage."""
        require(type(graph) is dict and set(graph) == {"roots", "nodes"}
                and type(graph["roots"]) is dict and set(graph["roots"]) == set(roots)
                and type(graph["nodes"]) is list and len(graph["nodes"]) <= 512, "invalid graph or root set")
        nodes, total_fields = {}, 0
        for index, node in enumerate(graph["nodes"]):
            require(type(node) is dict and set(node) == {"id", "type", "fields"}
                    and node["id"] == "n" + str(index) and type(node["fields"]) is dict, "invalid node storage")
            nodes[node["id"]] = node
        for node in nodes.values():
            expected = self.fields(node)
            require(set(node["fields"]) == set(expected), "source fields are missing or added")
            total_fields += len(expected)
            require(total_fields <= 8192, "field observation budget exceeded")
            for name, type_ in expected.items():
                self.value(node["fields"][name], type_, nodes)
        for name, type_ in roots.items():
            if panic and name == "error":
                panic_value(graph["roots"][name])
            else:
                self.value(graph["roots"][name], type_, nodes)
        pending, seen = deque((value, 0) for value in graph["roots"].values()), set()
        while pending:
            value, depth = pending.popleft()
            if value.get("kind") == "reference" and value["node_id"] not in seen:
                require(depth <= 32, "graph depth budget exceeded")
                seen.add(value["node_id"])
                pending.extend((child, depth + 1) for child in nodes[value["node_id"]]["fields"].values())
        require(seen == set(nodes), "unreachable storage nodes")
        return graph


def boundaries(raw: bytes, entry: dict) -> dict:
    """Decode a complete private observer envelope into shared boundary graphs."""
    require(len(raw) <= 3*262144+1024, "capture budget exceeded")
    capture = strict_json(raw)
    require(type(capture) is dict and set(capture) == {"go_receiver_schema_version", "before", "outcome", "after"}
            and type(capture["go_receiver_schema_version"]) is int and capture["go_receiver_schema_version"] == 1,
            "unsupported receiver envelope")
    outcome = capture["outcome"]
    require(type(outcome) is dict and set(outcome) == {"kind", "value"}
            and outcome["kind"] in ("return", "error"), "invalid outcome")
    schema, roots = Schema(entry), entry["go_root_types"]
    error = outcome["kind"] == "error"
    types = {**roots, "error" if error else "result": "void" if error else entry["go_result"]}
    result = {"kind": outcome["kind"], "graph": schema.graph(outcome["value"], types, panic=error)}
    if error:
        result["category"] = "panic"
    return {"before": schema.graph(capture["before"], roots), "outcome": result,
            "after": schema.graph(capture["after"], roots)}
