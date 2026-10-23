"""Validate native descriptor-2 graphs as data, without compiling or loading code."""

from codecs import lookup_error
from dataclasses import dataclass
import json
import re

from python_journal import CodeRecord, MAX_PATH, MAX_PAYLOAD, MAX_RECORDS
from python_provider import require

MAX_NODES = 65536
MAX_EDGES = 262144
MAX_DEPTH = 128
METADATA = ("co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals",
            "co_stacksize", "co_flags", "co_firstlineno")
NAMES = ("co_names", "co_varnames", "co_cellvars", "co_freevars")
TEXT = ("co_filename", "co_name", "co_qualname")
BINARY = ("co_linetable", "co_exceptiontable", "co_code")
FIELDS = ("co_consts", *NAMES, *TEXT, *BINARY)


@dataclass(frozen=True)
class Node:
    """Immutable data nodes preserve snapshot-local aliases and float bits."""

    kind: str
    value: None | bool | str | bytes | tuple[int, ...] = None
    fields: tuple[tuple[str, int], ...] = ()
    metadata: tuple[tuple[str, int], ...] = ()

    @property
    def references(self) -> tuple[int, ...]:
        """Return only graph edges, never binary or string contents."""
        if self.kind == "code":
            return tuple(value for _, value in self.fields)
        return self.value if type(self.value) is tuple else ()


@dataclass(frozen=True)
class Descriptor:
    """Well-formed code data does not establish source or compiler origin."""

    record: CodeRecord
    root: int
    nodes: tuple[Node, ...]
    filesystem: tuple[str, str]


def unique(pairs: list[tuple[str, object]]) -> dict:
    """Refuse duplicate fields before a JSON object can overwrite them."""
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate descriptor JSON field")
        result[key] = value
    return result


def integer(text: str) -> int:
    """JSON numbers carry bounded metadata; arbitrary integers use hex bytes."""
    require(len(text) <= 11, "descriptor JSON integer exceeds metadata bounds")
    return int(text)


def not_integer(_text: str) -> None:
    """Float constants are bit strings, including NaNs and signed zero."""
    raise ValueError("Python prepared provider: non-integer JSON number in code descriptor")


def reference(value: object) -> int:
    """Boolean and missing/zero/oversized IDs cannot name graph nodes."""
    require(type(value) is int and 1 <= value <= MAX_NODES, "invalid code graph reference")
    return value


def binary(value: object, size: int | None = None) -> bytes:
    """Only canonical lowercase even hex carries primitive bytes."""
    require(type(value) is str and len(value) % 2 == 0 and re.fullmatch("[0-9a-f]*", value) is not None,
            "invalid code graph hex bytes")
    result = bytes.fromhex(value)
    require(size is None or len(result) == size, "invalid code graph primitive width")
    return result


def node(value: object, identity: int) -> Node:
    """Decode exact closed node shapes; unknown types remain unsupported."""
    require(type(value) is dict and type(value.get("id")) is int and value["id"] == identity
            and type(value.get("type")) is str, "invalid code graph node identity")
    kind = value["type"]
    if kind == "code":
        require(set(value) == {"id", "type", "fields", "metadata"}
                and type(value["metadata"]) is dict and set(value["metadata"]) == set(METADATA)
                and all(type(item) is int and 0 <= item <= 0x7fffffff for item in value["metadata"].values())
                and type(value["fields"]) is dict and set(value["fields"]) == set(FIELDS), "invalid code graph code node")
        return Node(kind, fields=tuple((name, reference(value["fields"][name])) for name in FIELDS),
                    metadata=tuple((name, value["metadata"][name]) for name in METADATA))
    if kind in ("literal", "unicode"):
        require(set(value) == {"id", "type", "value"}, "invalid code graph literal fields")
        data = value["value"]
        valid = (data is None or type(data) is bool) if kind == "literal" else type(data) is str
        require(valid, "invalid code graph literal value")
        return Node(kind, data)
    if kind == "ellipsis":
        require(set(value) == {"id", "type"}, "invalid code graph ellipsis fields")
        return Node(kind)
    if kind in ("integer", "float", "complex", "bytes"):
        require(set(value) == {"id", "type", "data"}, "invalid code graph binary fields")
        data = binary(value["data"], {"float": 8, "complex": 16}.get(kind))
        if kind == "integer":
            require(bool(data) and len(data) == int.from_bytes(data, "big", signed=True).bit_length() // 8 + 1,
                    "invalid code graph integer encoding")
        return Node(kind, data)
    require(kind in ("tuple", "frozenset", "slice") and set(value) == {"id", "type", "items"}
            and type(value["items"]) is list, "invalid code graph container")
    values = tuple(reference(item) for item in value["items"])
    require(kind != "slice" or len(values) == 3, "invalid code graph slice width")
    require(kind != "frozenset" or len(set(values)) == len(values), "duplicate code graph set reference")
    return Node(kind, values)


def shapes(nodes: tuple[Node, ...]) -> None:
    """Code slots have fixed types; bytecode stays opaque two-byte words."""
    require(sum(len(item.references) for item in nodes) <= MAX_EDGES, "code graph edge budget exceeded")
    require(all(child <= len(nodes) for item in nodes for child in item.references), "code graph reference is missing")
    for item in nodes:
        if item.kind != "code":
            continue
        fields = dict(item.fields)
        for name in ("co_consts", *NAMES):
            value = nodes[fields[name] - 1]
            require(value.kind == "tuple", "code graph tuple slot differs")
            if name != "co_consts":
                require(all(nodes[child - 1].kind == "unicode" for child in value.references), "code graph name slot differs")
        for names, kind in ((TEXT, "unicode"), (BINARY, "bytes")):
            require(all(nodes[fields[name] - 1].kind == kind for name in names), "code graph slot type differs")
        require(dict(item.metadata)["co_nlocals"] == len(nodes[fields["co_varnames"] - 1].references)
                and len(nodes[fields["co_code"] - 1].value) % 2 == 0, "code graph locals or bytecode width differs")


def graph(nodes: tuple[Node, ...], root: int) -> None:
    """An iterative walk checks cycles, reachability and depth across aliases."""
    colours, heights = {}, {}
    pending = [(root, 0, False)]
    while pending:
        identity, depth, closing = pending.pop()
        require(depth <= MAX_DEPTH, "code graph depth budget exceeded")
        if closing:
            height = max((1 + heights[child] for child in nodes[identity - 1].references), default=0)
            require(depth + height <= MAX_DEPTH, "code graph depth budget exceeded")
            heights[identity], colours[identity] = height, 2
            continue
        require(colours.get(identity) != 1, "code graph cycle")
        if colours.get(identity) == 2:
            require(depth + heights[identity] <= MAX_DEPTH, "code graph depth budget exceeded")
            continue
        colours[identity] = 1
        pending.append((identity, depth, True))
        pending.extend((child, depth + 1, False) for child in reversed(nodes[identity - 1].references))
    require(len(colours) == len(nodes), "code graph has unreachable nodes")


def decode(record: CodeRecord) -> Descriptor:
    """Validate descriptor-2 data, including filename bytes and the entry offset."""
    require(type(record) is CodeRecord and type(record.descriptor_version) is int and record.descriptor_version == 2
            and type(record.content) is bytes and 0 < len(record.content) <= MAX_PAYLOAD,
            "invalid code descriptor record")
    require(type(record.sequence) is int and 1 <= record.sequence <= MAX_RECORDS
            and type(record.identity) is int and 0 < record.identity < 2 ** 64
            and type(record.path) is bytes and 0 < len(record.path) <= MAX_PATH and b"\0" not in record.path
            and type(record.python_version) is int and 0 <= record.python_version <= 0xffffffff
            and record.python_version >> 24 == 3 and (record.python_version >> 16 & 255) >= 12,
            "invalid code descriptor identity or interpreter version")
    try:
        value = json.loads(record.content.decode("ascii"), object_pairs_hook=unique, parse_int=integer,
                           parse_float=not_integer, parse_constant=not_integer)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Python prepared provider: invalid descriptor encoding or JSON depth") from error
    require(type(value) is dict and set(value) == {"schema_version", "filesystem", "root", "nodes"}
            and type(value["schema_version"]) is int and value["schema_version"] == 2
            and type(value["nodes"]) is list and 0 < len(value["nodes"]) <= MAX_NODES, "invalid code descriptor schema")
    filesystem = value["filesystem"]
    require(type(filesystem) is dict and set(filesystem) == {"encoding", "errors"}
            and all(type(item) is str and re.fullmatch("[A-Za-z0-9_.-]{1,128}", item) is not None
                    for item in filesystem.values()), "invalid code descriptor filesystem codec")
    nodes = tuple(node(item, index) for index, item in enumerate(value["nodes"], 1))
    root = reference(value["root"])
    require(root <= len(nodes) and nodes[root - 1].kind == "code", "invalid code graph root")
    shapes(nodes)
    graph(nodes, root)
    fields = dict(nodes[root - 1].fields)
    try:
        lookup_error(filesystem["errors"])
        filename = nodes[fields["co_filename"] - 1].value.encode(filesystem["encoding"], filesystem["errors"])
    except (UnicodeError, LookupError) as error:
        raise ValueError("Python prepared provider: unsupported code descriptor filename codec") from error
    require(filename == record.path, "code descriptor filename bytes differ")
    require(type(record.offset) is int and 0 <= record.offset < len(nodes[fields["co_code"] - 1].value)
            and record.offset % 2 == 0, "code descriptor entry offset is outside bytecode")
    return Descriptor(record, root, nodes, (filesystem["encoding"], filesystem["errors"]))
