"""Validate complete C++ slot graphs against their frozen compiler declarations."""
from collections import deque

from otelc_capture import strict_json

PREFIX = "cpp.storage:"
LOCATION = "cpp.location"
ERROR_TYPES = {"std::exception", "std::runtime_error", "std::logic_error", "std::invalid_argument",
               "std::domain_error", "std::length_error", "std::out_of_range", "std::range_error",
               "std::overflow_error", "std::underflow_error"}


def require(condition: bool, reason: str) -> None:
    """An incomplete observation never establishes equivalence."""
    if not condition:
        raise ValueError("typed capture: C++ " + reason)


def root_types(entry: dict) -> dict[str, str]:
    """All receiver, scalar input and source namespace/static slots are required."""
    contract = entry["cpp_receiver"]
    return {"receiver": contract["owner"],
            **{"argument:" + str(i): name for i, name in enumerate(contract["method"]["parameters"])},
            **{"global:" + item["name"]: item["type"] for item in contract["globals"]}}


class Schema:
    """Native bytes enter shared scalars only after exact type/ABI validation."""

    def __init__(self, entry: dict, abi: dict, scalar) -> None:
        self.models, self.abi, self.scalar = entry["cpp_receiver"]["types"], abi, scalar

    @staticmethod
    def reference(value: dict, label: str, nodes: dict) -> None:
        """Location equality is retained independently of a pointer's typed view."""
        require(type(value) is dict and set(value) == {"kind", "node_id"} and value["kind"] == "reference"
                and type(value["node_id"]) is str and value["node_id"] in nodes, "missing slot reference")
        require(nodes[value["node_id"]]["type"] == label, "slot source type differs")

    def value(self, value: dict, expected: str, nodes: dict, *, nullable: bool = False) -> None:
        """Only pointer targets admit null; primitive storage remains addressable."""
        if expected == "void":
            require(value == {"kind": "unit", "type": "cpp.unit"}, "invalid void result")
        elif value == {"kind": "null"}:
            require(nullable, "null non-pointer storage")
        else:
            self.reference(value, LOCATION if expected == LOCATION else PREFIX + expected, nodes)

    def fields(self, node: dict, nodes: dict) -> None:
        """Exact field coverage rejects dropped fields, injected values and opaque data."""
        label, fields = node["type"], node["fields"]
        if label == LOCATION:
            require(not fields, "location exposes raw address or fields")
            return
        require(type(label) is str and label.startswith(PREFIX) and label[len(PREFIX):] in self.models,
                "unbound storage node")
        name = label[len(PREFIX):]
        model, kind = self.models[name], self.models[name]["kind"]
        expected = {"location": LOCATION}
        if kind == "record":
            expected.update({"field:" + item["name"]: item["canonical"] for item in model["fields"]})
        elif kind == "array":
            expected.update({"item:" + str(i): model["element"] for i in range(model["length"])})
        else:
            expected["value"] = model.get("element", "@scalar")
        require(set(fields) == set(expected), "source fields are missing or added")
        for field, type_ in expected.items():
            if type_ == "@scalar":
                value = fields[field]
                require(type(value) is dict and set(value) == {"native_type", "bytes"}
                        and value["native_type"] == name and type(value["bytes"]) is str
                        and len(value["bytes"]) <= 16, "primitive source storage differs")
                fields[field] = self.scalar(value["bytes"].encode("ascii"), name, self.abi, "cpp")
            else:
                self.value(fields[field], type_, nodes, nullable=kind == "pointer" and field == "value")

    def graph(self, graph: dict, roots: dict, *, error: bool = False) -> dict:
        """Require canonical nodes, reachable storage and bounded complete roots."""
        require(type(graph) is dict and set(graph) == {"roots", "nodes"}
                and type(graph["roots"]) is dict and set(graph["roots"]) == set(roots)
                and type(graph["nodes"]) is list and len(graph["nodes"]) <= 512, "invalid graph or root set")
        nodes, total = {}, 0
        for index, node in enumerate(graph["nodes"]):
            require(type(node) is dict and set(node) == {"id", "type", "fields"}
                    and node["id"] == "n" + str(index) and type(node["fields"]) is dict, "invalid storage node")
            nodes[node["id"]] = node
        for node in nodes.values():
            total += len(node["fields"])
            require(total <= 8192, "field budget exceeded")
            self.fields(node, nodes)
        for name, type_ in roots.items():
            if error and name == "error":
                value = graph["roots"][name]
                require(type(value) is dict and set(value) == {"error_type", "message"}
                        and type(value["error_type"]) is str and value["error_type"] in ERROR_TYPES
                        and type(value["message"]) is str and len(value["message"]) <= 131072
                        and len(value["message"]) % 2 == 0
                        and all(char in "0123456789abcdef" for char in value["message"]), "unsupported exception payload")
                graph["roots"][name] = {"kind": "bytes", "type": "cpp.exception." + value["error_type"], "hex": value["message"]}
            else:
                self.value(graph["roots"][name], type_, nodes)
        seen, pending = set(), deque((value, 0) for value in graph["roots"].values())
        while pending:
            value, depth = pending.popleft()
            if value.get("kind") == "reference" and value["node_id"] not in seen:
                require(depth <= 32, "graph depth budget exceeded")
                seen.add(value["node_id"])
                pending.extend((field, depth + 1) for field in nodes[value["node_id"]]["fields"].values())
        require(seen == set(nodes), "unreachable storage nodes")
        return graph


def boundaries(raw: bytes, entry: dict, scalar) -> dict:
    """Decode actual compiler ABI metadata and the private receiver envelope."""
    require(len(raw) <= 3*262144+4096, "capture budget exceeded")
    metadata, separator, payload = raw.partition(b"\n")
    require(bool(separator) and metadata.startswith(b"abi:"), "missing actual compiler ABI")
    abi, capture = strict_json(metadata[4:]), strict_json(payload)
    ordered = "sequence_configuration" in entry
    fields = {"cpp_receiver_schema_version", "before", "outcome", "after"} | ({"steps"} if ordered else set())
    require(type(abi) is dict and type(capture) is dict and set(capture) == fields
            and type(capture["cpp_receiver_schema_version"]) is int
            and capture["cpp_receiver_schema_version"] == (2 if ordered else 1),
            "unsupported receiver envelope")
    if ordered:
        observed, declared = capture['steps'], entry['sequence_configuration']
        require(type(observed) is list and 1 <= len(observed) == len(declared) <= 32, "incomplete receiver sequence")
        for index, (step, action) in enumerate(zip(observed, declared)):
            require(type(step) is dict and set(step) == {'id', 'action', 'before', 'outcome', 'after'}
                    and step['id'] == 'step-' + str(index) and step['action'] == action['action'] == 'call',
                    "invalid receiver action")
        require(capture['before'] == observed[0]['before']
                and all(capture[name] == observed[-1][name] for name in ('outcome', 'after')),
                "receiver sequence contradicts its outer boundaries")
    result = boundary(capture, entry, abi, scalar)
    if ordered:
        result['steps'] = [{'id': step['id'], 'action': 'call', 'gaps': [],
            **boundary(step, entry, abi, scalar)} for step in observed]
    return result


def boundary(capture: dict, entry: dict, abi: dict, scalar) -> dict:
    """Decode each complete source-bound snapshot through the same closed codec."""
    outcome = capture["outcome"]
    require(type(outcome) is dict and set(outcome) == {"kind", "value"}
            and outcome["kind"] in ("return", "error"), "invalid outcome")
    schema, roots = Schema(entry, abi, scalar), root_types(entry)
    error = outcome["kind"] == "error"
    returned = {**roots, "error" if error else "result": "void" if error else entry["cpp_receiver"]["method"]["output"]}
    result = {"kind": outcome["kind"], "graph": schema.graph(outcome["value"], returned, error=error)}
    if error:
        result["category"] = "exception"
    return {"before": schema.graph(capture["before"], roots), "outcome": result,
            "after": schema.graph(capture["after"], roots)}
