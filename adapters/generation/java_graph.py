"""Validate source-bound Java graphs without executing application codecs."""
from collections import deque
from typing import cast

from otelc_capture import strict_json


JAVA_PACKAGE = "java.lang."
OBJECT_TYPE = JAVA_PACKAGE + "Object"
OBJECT_PREFIX = "java.object:"
INTEGERS = {"byte": (8, True), "short": (16, True), "int": (32, True),
            "long": (64, True), "char": (16, False)}
BOXES = {"Boolean": "boolean", "Byte": "byte", "Short": "short", "Integer": "int",
         "Long": "long", "Character": "char", "Float": "float", "Double": "double", "String": "string"}
ERRORS = {"Exception", "RuntimeException", "IllegalArgumentException", "IllegalStateException",
          "NullPointerException", "ArithmeticException", "IndexOutOfBoundsException",
          "ArrayIndexOutOfBoundsException", "StringIndexOutOfBoundsException",
          "UnsupportedOperationException", "ClassCastException", "NumberFormatException"}
ERROR_TYPES = {JAVA_PACKAGE + name for name in ERRORS}
ARRAY_CODES = dict(zip("ZBSCIJFD", ("boolean", "byte", "short", "char", "int", "long", "float", "double")))


def require(condition: bool, reason: str) -> None:
    """Reject incomplete Java observations before shared graph comparison."""
    if not condition:
        raise ValueError("typed capture: Java " + reason)


def hex_units(value: object, multiple: int, maximum: int) -> bool:
    """Only complete, canonical lowercase units are accepted."""
    if type(value) is not str:
        return False
    text = cast(str, value)
    return (len(text) <= maximum and len(text) % multiple == 0
            and all(char in "0123456789abcdef" for char in text))


def primitive(value: dict, expected: str) -> None:
    """Check exact Java primitive widths, signs, float bits and UTF-16 units."""
    require(type(value) is dict, "primitive must be tagged")
    label = "java.lang.String" if expected == "string" else "java." + expected
    require(value.get("type") == label, "primitive type differs from its storage")
    if expected in INTEGERS:
        bits, signed = INTEGERS[expected]
        require(set(value) == {"kind", "type", "value", "bits", "signed"}
                and value["kind"] == "integer" and type(value["bits"]) is int and value["bits"] == bits
                and type(value["signed"]) is bool and value["signed"] == signed, "integer storage differs")
        text = value["value"]
        require(type(text) is str and 0 < len(text) <= 20, "invalid integer")
        number = int(text)
        low, high = (-2**(bits-1), 2**(bits-1)-1) if signed else (0, 2**bits-1)
        require(text == str(number) and low <= number <= high, "noncanonical or out-of-range integer")
    elif expected == "boolean":
        require(set(value) == {"kind", "type", "value"} and value["kind"] == "boolean"
                and type(value["value"]) is bool, "invalid boolean")
    elif expected in ("float", "double"):
        width = 8 if expected == "float" else 16
        require(set(value) == {"kind", "type", "bits"} and value["kind"] == "float"
                and hex_units(value["bits"], width, width) and len(value["bits"]) == width, "invalid float bits")
    else:
        require(expected == "string" and set(value) == {"kind", "type", "encoding", "value"}
                and value["kind"] == "string" and value["encoding"] == "utf16_be"
                and hex_units(value["value"], 4, 262144), "invalid string units")


class Schema:
    """Bind each node, field and root to frozen source storage declarations."""

    def __init__(self, entry: dict) -> None:
        self.entry = entry
        package = entry["package"]
        self.names = {item["name"]: (package + "." if package else "") + item["name"]
                      for item in entry["java_models"]}
        self.models = {self.names[item["name"]]: item for item in entry["java_models"]}
        self.references = set(self.models) | {JAVA_PACKAGE + name for name in BOXES} | {OBJECT_TYPE} | ERROR_TYPES

    def resolve(self, spelling: str) -> str:
        """Resolve the closed standalone source profile; javac checks binding too."""
        if spelling.endswith("[]"):
            component = self.resolve(spelling[:-2])
            code = next((code for code, name in ARRAY_CODES.items() if name == component), None)
            if code:
                return "[" + code
            if component.startswith("["):
                return "[" + component
            return "[L" + component + ";"
        if spelling in self.names:
            return self.names[spelling]
        if spelling in BOXES or spelling == "Object":
            return JAVA_PACKAGE + spelling
        require(spelling in self.references | set(ARRAY_CODES.values()) | {"void"}, "unsupported declared type")
        return spelling

    def component(self, name: str) -> str:
        """Validate a JVM array descriptor and return its immediate component."""
        require(name.startswith("[") and len(name) - len(name.lstrip("[")) <= 32, "invalid array type")
        component = name[1:]
        if component.startswith("["):
            self.component(component)
            return component
        if component in ARRAY_CODES:
            return ARRAY_CODES[component]
        require(component.startswith("L") and component.endswith(";") and component[1:-1] in self.references,
                "unbound array component")
        return component[1:-1]

    def assignable(self, actual: str, expected: str) -> bool:
        """The supported source classes extend Object; arrays retain covariance."""
        if actual == expected:
            return True
        if expected == OBJECT_TYPE:
            return actual in self.references or actual.startswith("[")
        if actual in ERROR_TYPES and expected == "java.lang.Exception":
            return True
        if actual.startswith("[") and expected.startswith("["):
            left, right = self.component(actual), self.component(expected)
            return left not in ARRAY_CODES.values() and right not in ARRAY_CODES.values() and self.assignable(left, right)
        return False

    def value(self, value: dict, expected: str, nodes: dict) -> None:
        """Primitive values never collapse boxed/string reference identities."""
        require(type(value) is dict, "value must be tagged")
        if expected == "void":
            require(value == {"kind": "undefined"}, "invalid void result")
        elif expected in ARRAY_CODES.values():
            primitive(value, expected)
        elif value == {"kind": "null"}:
            return
        else:
            require(set(value) == {"kind", "node_id"} and value["kind"] == "reference"
                    and type(value["node_id"]) is str and value["node_id"] in nodes, "invalid reference")
            label = nodes[value["node_id"]]["type"]
            actual = label.removeprefix(OBJECT_PREFIX)
            require(self.assignable(actual, expected), "reference type differs from its storage")

    def fields(self, node: dict) -> dict[str, str] | None:
        """Require every observed instance slot and every supported array element."""
        label, fields = node["type"], node["fields"]
        require(type(label) is str and type(fields) is dict, "invalid node storage")
        if label in ERROR_TYPES:
            return {"message": "java.lang.String"}
        require(label.startswith(OBJECT_PREFIX), "unknown node kind")
        name = label.removeprefix(OBJECT_PREFIX)
        if name in self.models:
            return {field["name"]: self.resolve(field["type"]) for field in self.models[name]["fields"] if not field["modifiers"] & 8}
        if name == OBJECT_TYPE:
            return {}
        if name.startswith(JAVA_PACKAGE) and name.removeprefix(JAVA_PACKAGE) in BOXES:
            primitive(fields.get("value"), BOXES[name.removeprefix(JAVA_PACKAGE)])
            require(set(fields) == {"value"}, "unexpected wrapper storage")
            return None
        require(name.startswith("["), "unbound node class")
        component = self.component(name)
        primitive(fields.get("length"), "int")
        length = int(fields["length"]["value"])
        require(0 <= length <= 4096, "array budget exceeded")
        return {"length": "int", **{"item:" + str(i): component for i in range(length)}}

    def graph(self, graph: dict, roots: dict[str, str]) -> dict:
        """Validate a complete boundary graph, including reference reachability."""
        require(type(graph) is dict and set(graph) == {"roots", "nodes"}, "invalid graph fields")
        require(type(graph["roots"]) is dict and set(graph["roots"]) == set(roots)
                and type(graph["nodes"]) is list and len(graph["nodes"]) <= 512, "missing roots or graph budget exceeded")
        nodes = {}
        for index, node in enumerate(graph["nodes"]):
            require(type(node) is dict and set(node) == {"id", "type", "fields"} and node["id"] == "n" + str(index), "invalid node identity")
            nodes[node["id"]] = node
        for node in nodes.values():
            fields = self.fields(node)
            # Bootstrap boxes were checked as scalar storage rather than graph edges.
            if fields is not None:
                require(set(node["fields"]) == set(fields), "missing or extra source storage")
                for name, expected in fields.items():
                    self.value(node["fields"][name], expected, nodes)
        for name, expected in roots.items():
            self.value(graph["roots"][name], self.resolve(expected), nodes)
        receiver = graph["roots"]["receiver"]
        require(receiver.get("kind") == "reference", "receiver is absent")
        pending, seen = deque((value, 0) for value in graph["roots"].values()), set()
        while pending:
            value, depth = pending.popleft()
            if value.get("kind") == "reference" and value["node_id"] not in seen:
                require(depth <= 32, "graph depth budget exceeded")
                seen.add(value["node_id"])
                pending.extend((item, depth + 1) for item in nodes[value["node_id"]]["fields"].values())
        require(seen == set(nodes), "unreachable node storage")
        return graph


def root_types(entry: dict) -> dict[str, str]:
    """Return the exact context roots shared by all three boundaries."""
    owner = entry["receiver_class"]
    return {"receiver": owner, **{"argument:" + str(i): name for i, name in enumerate(entry["parameters"])},
            **{"static:" + owner + "." + field["name"]: field["type"] for field in entry["java_class_roots"]}}


def boundaries(raw: bytes, entry: dict) -> dict:
    """Decode the closed Java receiver envelope into the shared typed contract."""
    require(len(raw) <= 3 * 262144 + 1024, "capture budget exceeded")
    capture = strict_json(raw)
    require(type(capture) is dict and set(capture) == {"java_receiver_schema_version", "before", "outcome", "after"}
            and type(capture["java_receiver_schema_version"]) is int and capture["java_receiver_schema_version"] == 1,
            "invalid receiver envelope")
    outcome = capture["outcome"]
    require(type(outcome) is dict and set(outcome) == {"kind", "value"} and outcome["kind"] in ("return", "error"), "invalid outcome")
    schema, roots = Schema(entry), root_types(entry)
    kind = outcome["kind"]
    outcome_graph = schema.graph(outcome["value"], {**roots, "result" if kind == "return" else "error": entry["output"] if kind == "return" else "java.lang.Exception"})
    if kind == "error":
        require(outcome_graph["roots"]["error"].get("kind") == "reference", "exception is absent")
    result = {"kind": kind, "graph": outcome_graph}
    if kind == "error":
        result["category"] = "exception"
    return {"before": schema.graph(capture["before"], roots), "outcome": result,
            "after": schema.graph(capture["after"], roots)}
