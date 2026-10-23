"""Closed worker codecs for versioned boundary graphs; never evaluate target text."""
import base64
from typing import Any
import node_receivers
import java_graph
import go_graph
import cpp_graph

from otelc_capture import strict_json


def require(condition: bool, reason: str) -> None:
    """Malformed or unsupported capture is incomplete evidence, never equality."""
    if not condition:
        raise ValueError("typed capture: " + reason)


def integer(type_: str, value: str, bits: int | None, signed: bool = True) -> dict:
    require(type(value) is str and value == str(int(value)), "noncanonical integer")
    number = int(value)
    require(signed or number >= 0, "negative unsigned integer")
    if bits is not None:
        require(bits in (8, 16, 32, 64, 128), "unsupported integer width")
        low, high = (-2**(bits-1), 2**(bits-1)-1) if signed else (0, 2**bits-1)
        require(low <= number <= high, "integer exceeds recorded width")
    return {"kind": "integer", "type": type_, "value": value, "bits": bits, "signed": signed}


def floating(type_: str, value: str, width: int) -> dict:
    require(type(value) is str and 0 < len(value) <= width // 4, "invalid float width")
    require(all(char in "0123456789abcdef" for char in value), "invalid float bits")
    return {"kind": "float", "type": type_, "bits": value.zfill(width // 4)}


def string(value: str, language: str, type_: str | None = None) -> dict:
    if language == "python":
        encoding, payload = "codepoints32_be", b"".join(ord(char).to_bytes(4, "big") for char in value)
    elif language in ("javascript", "typescript", "java"):
        encoding, payload = "utf16_be", value.encode("utf-16-be", errors="surrogatepass")
    else:
        encoding, payload = "utf8", value.encode("utf-8", errors="strict")
    return {"kind": "string", "type": type_ or language + ".string", "encoding": encoding, "value": payload.hex()}


def reference(index: int) -> dict:
    require(type(index) is int and index >= 0, "invalid local reference")
    return {"kind": "reference", "node_id": "n" + str(index)}


def property_key(name: str) -> str:
    """Keep ordinary paths legible while preserving arbitrary surrogate keys."""
    try:
        name.encode("utf-8", errors="strict")
    except UnicodeError:
        return "property-units:" + name.encode("utf-32-be", errors="surrogatepass").hex()
    return "property:" + name


def dynamic_value(value: dict, language: str) -> dict:
    require(type(value) is dict, "dynamic value must be tagged")
    if set(value) == {"ref"}:
        return reference(value["ref"])
    kind = value.get("type")
    if kind in ("null", "undefined", "unbound"):
        require(set(value) == {"type"}, "unexpected absence fields")
        return {"kind": kind}
    require(set(value) == {"type", "bits" if kind == "float64" else "value"}, "unexpected scalar fields")
    if kind in ("bool", "boolean"):
        require(type(value.get("value")) is bool, "invalid boolean")
        return {"kind": "boolean", "type": language + "." + kind, "value": value["value"]}
    if kind in ("int", "bigint"):
        return integer(language + "." + kind, value["value"], None)
    if kind == "float64":
        return floating(language + ".float64", value["bits"], 64)
    if kind in ("str", "string"):
        require(type(value.get("value")) is str, "invalid string")
        return string(value["value"], language)
    if kind == "bytes":
        payload = value["value"]
        require(type(payload) is str and bytes.fromhex(payload).hex() == payload, "invalid bytes")
        return {"kind": "bytes", "type": "python.bytes", "hex": payload}
    raise ValueError("typed capture: unsupported dynamic tag " + str(kind))


def own_fields(fields: list, language: str, descriptors: bool) -> dict:
    result, names = {}, set()
    require(type(fields) is list, "object fields must be ordered")
    for index, field in enumerate(fields):
        require(type(field) is list and len(field) == (5 if descriptors else 2), "invalid object field")
        name, value = field[:2]
        require(type(name) is str and name not in names, "duplicate/invalid object field")
        names.add(name)
        result["order:" + str(index)] = string(name, language)
        key = property_key(name)
        result[key] = dynamic_value(value, language)
        if descriptors:
            for label, flag in zip(("writable", "enumerable", "configurable"), field[2:]):
                require(type(flag) is bool, "invalid property descriptor")
                result[label + ":" + key] = {"kind": "boolean", "value": flag}
    return result


def python_exception_fields(node: dict) -> dict:
    """Keep the exception's argument and chaining state without formatting it."""
    fields = {"exception:" + name: dynamic_value(node[name], "python") for name in ("args", "cause", "context")}
    require(type(node["suppress_context"]) is bool, "invalid exception context flag")
    fields["exception:suppress_context"] = {"kind": "boolean", "value": node["suppress_context"]}
    return fields


def python_dictionary_fields(items: list) -> dict:
    """Retain insertion order and typed keys separately from dictionary values."""
    fields = {}
    for index, pair in enumerate(items):
        require(type(pair) is list and len(pair) == 2, "invalid dictionary entry")
        for part, value in zip(("key", "value"), pair):
            fields["entry:" + str(index) + ":" + part] = dynamic_value(value, "python")
    return fields


def python_node(node: dict) -> dict:
    """Decode one supported Python container, ordinary object or exception node."""
    label = node["type"]
    require(type(label) is str, "invalid Python type label")
    fields = {}
    if label in ("builtins.list", "builtins.tuple"):
        require(set(node) == {"type", "items"} and type(node["items"]) is list, "invalid sequence node")
        fields = {"item:" + str(index): dynamic_value(value, "python") for index, value in enumerate(node["items"])}
    elif label == "builtins.dict":
        require(set(node) == {"type", "items"} and type(node["items"]) is list, "invalid dictionary node")
        fields = python_dictionary_fields(node["items"])
    else:
        expected = {"type", "fields"} | ({"args", "cause", "context", "suppress_context"} if "args" in node else set())
        require(set(node) == expected, "unsupported Python object fields")
        fields = own_fields(node["fields"], "python", False)
        if "args" in node:
            fields.update(python_exception_fields(node))
    # Type names are labels of observed state, not a proof of class origin.
    try:
        label.encode("utf-8", errors="strict")
        type_ = "python." + label
    except UnicodeError:
        type_ = "python-type-units:" + label.encode("utf-32-be", errors="surrogatepass").hex()
    return {"type": type_, "fields": fields}


def dynamic_graph(graph: dict, language: str, declared_prototypes: tuple[str, ...] = ()) -> dict:
    require(type(graph) is dict and set(graph) == {"roots", "nodes"}, "invalid dynamic graph")
    require(type(graph["roots"]) is dict and type(graph["nodes"]) is list, "invalid dynamic graph records")
    nodes = []
    for index, node in enumerate(graph["nodes"]):
        require(type(node) is dict, "invalid graph node")
        if language == "python":
            converted = python_node(node)
        else:
            require(set(node) == {"type", "fields", "prototype", "extensible"}, "unexpected Node fields")
            require(type(node.get("extensible")) is bool, "missing object extensibility capture")
            prototype = node.get("prototype")
            require(prototype in ("null", "Object", "Array", "Error", "TypeError", "RangeError", "SyntaxError", "ReferenceError", "URIError", "EvalError", "AggregateError") or prototype in declared_prototypes, "unsupported prototype")
            fields = own_fields(node["fields"], language, True)
            fields["meta:extensible"] = {"kind": "boolean", "value": node["extensible"]}
            converted = {"type": "ecmascript." + node["type"] + ".prototype:" + prototype, "fields": fields}
        nodes.append({"id": "n" + str(index), **converted})
    return {"roots": {name: dynamic_value(value, language) for name, value in graph["roots"].items()}, "nodes": nodes}


def hexadecimal(raw: str, index: int, width: int) -> int:
    """Consume one complete hexadecimal escape payload."""
    digits = raw[index:index + width]
    require(len(digits) == width and all(unit in "0123456789abcdefABCDEF" for unit in digits), "invalid hexadecimal escape")
    return int(digits, 16)


def escaped(raw: str, index: int, language: str) -> tuple[bytes, int]:
    """Read a single source-independent formatter escape."""
    end = len(raw) - 1
    require(index < end, "incomplete escape")
    char = raw[index]
    index += 1
    escapes = {'n': b'\n', 'r': b'\r', 't': b'\t', '0': b'\0', 'a': b'\a', 'b': b'\b', 'f': b'\f', 'v': b'\v', '\\': b'\\', '"': b'"', "'": b"'"}
    if char in escapes and (char != "0" or language == "rust"):
        return escapes[char], index
    if char == "x":
        return bytes([hexadecimal(raw, index, 2)]), index + 2
    if language == "rust" and char == "u" and raw[index:index + 1] == "{":
        close = raw.find("}", index + 1, end)
        require(close > index + 1, "unfinished Rust code point")
        return chr(hexadecimal(raw, index + 1, close - index - 1)).encode("utf-8"), close + 1
    if char in ("u", "U"):
        width = 4 if char == "u" else 8
        return chr(hexadecimal(raw, index, width)).encode("utf-8"), index + width
    require(language == "go" and char in "01234567", "unsupported string escape")
    digits = char + raw[index:index + 2]
    require(len(digits) == 3 and all(unit in "01234567" for unit in digits), "invalid octal escape")
    return bytes([int(digits, 8)]), index + 2


def quoted(raw: str, language: str) -> bytes:
    """Decode the closed Rust Debug / Go quoted-string grammar without eval."""
    require(len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"), "invalid quoted scalar")
    output, index = bytearray(), 1
    end = len(raw) - 1
    while index < end:
        char = raw[index]; index += 1
        if char != "\\":
            require(char != raw[0] and ord(char) >= 32, "unescaped string delimiter/control")
            output.extend(char.encode("utf-8"))
        else:
            payload, index = escaped(raw, index, language)
            output.extend(payload)
    return bytes(output)


def native_scalar(payload: bytes, type_: str, abi: dict, language: str) -> dict:
    type_ = type_.replace("const ", "").strip()
    data = bytes.fromhex(payload.decode("ascii"))
    require(payload.decode("ascii") == data.hex(), "noncanonical native bytes")
    require(abi.get("byte_order") in ("little", "big") and abi.get("char_bits") == 8, "unsupported native byte representation")
    label = language + "." + type_
    if type_ in ("bool", "_Bool"):
        require(len(data) == 1 and data[0] in (0, 1), "unsupported native boolean representation")
        return {"kind": "boolean", "type": label, "value": bool(data[0])}
    require(type(abi.get("bits")) is dict, "missing native type widths")
    width = abi["bits"].get(type_)
    require(type(width) is int and len(data) * 8 == width, "native width differs from actual compiler ABI")
    if type_ in ("float", "double"):
        require(abi.get("ieee754") is True and width == (32 if type_ == "float" else 64), "unsupported native float format")
        return floating(label, (data[::-1] if abi["byte_order"] == "little" else data).hex(), width)
    signed = not type_.startswith("unsigned")
    if type_ == "char":
        require(type(abi.get("char_signed")) is bool, "missing native char sign")
        signed = abi["char_signed"]
    return integer(label, str(int.from_bytes(data, abi["byte_order"], signed=signed)), width, signed)


def boolean(payload: str, type_: str) -> dict:
    """Only actual boolean literals can enter the shared boolean domain."""
    require(payload in ("true", "false"), "invalid boolean")
    return {"kind": "boolean", "type": type_, "value": payload == "true"}


def java_scalar(tag: str, payload: str) -> dict:
    """Decode final bootstrap wrappers and exact UTF-16 code units."""
    if tag in ("float", "double"):
        return floating("java." + tag, payload, 32 if tag == "float" else 64)
    if tag == "string":
        require(payload.startswith("utf16:"), "unsupported Java string encoding")
        encoded = payload[len("utf16:"):]
        require(len(encoded) % 4 == 0 and bytes.fromhex(encoded).hex() == encoded, "invalid UTF-16 units")
        return {"kind": "string", "type": "java.lang.String", "encoding": "utf16_be", "value": encoded}
    if tag == "char":
        require(0 <= int(payload, 16) <= 65535, "invalid Java char")
        return {"kind": "string", "type": "java.char", "encoding": "utf16_be", "value": f"{int(payload, 16):04x}"}
    payload = base64.b64decode(payload, validate=True).decode("ascii")
    if tag == "java.lang.Boolean":
        return boolean(payload, tag)
    widths = {"java.lang.Byte": 8, "java.lang.Short": 16, "java.lang.Integer": 32, "java.lang.Long": 64}
    require(tag in widths, "unsupported Java primitive wrapper")
    return integer(tag, payload, widths[tag])


def rust_scalar(tag: str, payload: str, abi: dict) -> dict:
    """The worker's closed trait reports the actual primitive type."""
    label = "rust." + tag
    if tag in ("f32", "f64"):
        return floating(label, payload, 32 if tag == "f32" else 64)
    if tag == "bool":
        return boolean(payload, label)
    if tag in ("String", "str", "char"):
        value = quoted(payload, "rust")
        decoded = value.decode("utf-8")
        require(tag != "char" or len(decoded) == 1, "invalid Rust char")
        return {"kind": "string", "type": label, "encoding": "utf8", "value": value.hex()}
    widths = {prefix + str(bits): bits for prefix in ("i", "u") for bits in (8, 16, 32, 64, 128)}
    widths.update({"isize": abi.get("pointer_bits"), "usize": abi.get("pointer_bits")})
    require(tag in widths and type(widths[tag]) is int, "unsupported/missing primitive ABI")
    return integer(label, payload, widths[tag], tag.startswith("i"))


def go_scalar(tag: str, payload: str, abi: dict) -> dict:
    """Named primitive types keep both their reflection kind and type label."""
    actual = tag
    if tag.startswith("@"):
        tag, separator, actual = tag[1:].partition("|")
        require(bool(separator) and bool(actual), "invalid named Go scalar")
    label = "go." + actual
    if tag in ("float32", "float64"):
        return floating(label, payload, 32 if tag == "float32" else 64)
    if tag == "bool":
        return boolean(payload, label)
    if tag == "string":
        return {"kind": "string", "type": label, "encoding": "raw_bytes", "value": quoted(payload, "go").hex()}
    widths = {prefix + str(bits): bits for prefix in ("int", "uint") for bits in (8, 16, 32, 64)}
    widths.update({"int": abi.get("pointer_bits"), "uint": abi.get("pointer_bits")})
    require(tag in widths and type(widths[tag]) is int, "unsupported/missing primitive ABI")
    if payload.startswith("0x"):
        payload = str(int(payload[2:], 16))
    return integer(label, payload, widths[tag], tag.startswith("int"))


def managed_scalar(raw: bytes, language: str, abi: dict) -> dict:
    """Dispatch only a supported, explicit worker type tag."""
    text = raw.decode("utf-8")
    if text in ("void", "unit:()"):
        return {"kind": "unit", "type": language + ".unit"}
    if language == "java" and text == "null":
        return {"kind": "null"}
    tag, separator, payload = text.partition(":")
    require(bool(separator), "missing scalar type")
    readers = {"java": java_scalar, "rust": rust_scalar, "go": go_scalar}
    require(language in readers, "unsupported scalar worker language")
    return java_scalar(tag, payload) if language == "java" else readers[language](tag, payload, abi)


def scalar_value(payload: bytes, type_: str, abi: dict, language: str) -> dict:
    """Select the closed codec for the actual worker language."""
    if language in ("c", "cpp"):
        return native_scalar(payload, type_, abi, language)
    return managed_scalar(payload, language, abi)


def scalar_state(records: list[bytes], entry: dict, abi: dict) -> dict:
    """Require the plan's complete ordered global list at each boundary."""
    language = entry["language"]
    roots = {}
    for item, record in zip(entry["globals"], records):
        prefix = item["name"].encode() + b":"
        if language in ("c", "cpp"):
            prefix += item["type"].encode() + b":"
        require(record.startswith(prefix), "missing/misordered declared global")
        roots["global:" + item["name"]] = scalar_value(record[len(prefix):], item["type"], abi, language)
    return {"roots": roots, "nodes": []}


def scalar_return(payload: bytes, entry: dict, abi: dict) -> dict:
    """Read a successful result only after checking its native type framing."""
    language = entry["language"]
    if payload == b"void":
        return {"kind": "unit", "type": language + ".unit"}
    if language in ("c", "cpp"):
        prefix = entry["output"].replace("const ", "").strip().encode() + b":"
        require(payload.startswith(prefix), "unexpected native return type")
        payload = payload[len(prefix):]
    return scalar_value(payload, entry["output"], abi, language)


def scalar_error(payload: bytes, language: str, abi: dict, graph: dict) -> dict:
    """Decode only qualified error/panic payloads, never application formatters."""
    category = "exception"
    if language == "cpp":
        tag, delimiter, message = payload.partition(b"\t")
        require(bool(delimiter), "unsupported C++ error codec")
        type_, message_value = "cpp." + tag.decode("ascii"), {"kind": "bytes", "type": "cpp.what", "hex": message.hex()}
    elif language == "java":
        tag, delimiter, message = payload.partition(b":")
        require(bool(delimiter), "invalid Java error codec")
        type_, message_value = tag.decode("ascii"), managed_scalar(message, language, abi)
    elif language == "rust":
        tag, delimiter, message = payload.partition(b":")
        require(tag in (b"string", b"str") and bool(delimiter), "unsupported Rust panic payload")
        type_ = "rust.panic." + tag.decode()
        category = "panic"
        message_value = {"kind": "string", "type": "rust.str", "encoding": "utf8", "value": quoted(message.decode(), "rust").hex()}
    else:
        require(language == "go", "C error observation requires a fixture")
        graph["roots"]["error"] = managed_scalar(payload, language, abi)
        return {"kind": "error", "category": "panic", "graph": graph}
    graph["roots"]["error"] = reference(0)
    graph["nodes"].append({"id": "n0", "type": type_, "fields": {"message": message_value}})
    return {"kind": "error", "category": category, "graph": graph}


def scalar_capture(raw: bytes, entry: dict) -> tuple[dict, dict, dict]:
    """Frame complete boundaries from the frozen global count, not delimiters in values."""
    language = entry["language"]
    lines = raw.split(b"\n")
    require(len(lines) >= 4, "missing observation boundaries")
    require(lines[-1] == b"", "unterminated observation")
    lines.pop()
    abi = {}
    if language != "java":
        require(lines[0].startswith(b"abi:"), "missing actual ABI metadata")
        abi = strict_json(lines.pop(0)[4:])
        require(type(abi) is dict, "invalid ABI record")
    count = len(entry["globals"])
    after_index = len(lines) - count - 1
    require(lines[0] == b"before" and after_index > count and lines[after_index] == b"after", "invalid state boundary framing")
    before = scalar_state(lines[1:1 + count], entry, abi)
    after = scalar_state(lines[after_index + 1:], entry, abi)
    kind, separator, payload = b"\n".join(lines[1 + count:after_index]).partition(b":")
    require(kind in (b"return", b"error") and bool(separator), "invalid outcome")
    graph = {"roots": dict(after["roots"]), "nodes": []}
    if kind == b"return":
        graph["roots"]["result"] = scalar_return(payload, entry, abi)
        return before, {"kind": "return", "graph": graph}, after
    return before, scalar_error(payload, language, abi, graph), after


def required_roots(entry: dict) -> list[str]:
    if entry["language"] == "cpp" and "cpp_receiver" in entry:
        return list(cpp_graph.root_types(entry))
    if entry["language"] == "go" and "receiver_fixture" in entry:
        return list(entry["go_root_types"])
    if entry["language"] == "java" and "receiver_fixture" in entry:
        return list(java_graph.root_types(entry))
    roots = ["global:" + item["name"] for item in entry["globals"]]
    if entry["language"] in ("python", "javascript", "typescript"):
        roots.append("arguments")
    if "receiver_fixture" in entry:
        roots.append("receiver")
        owner = entry["receiver_class"]
        fields = entry.get("python_class_roots", []) if entry["language"] == "python" else entry["node_class_roots"]
        roots.extend("static:" + owner + "." + item["name"] for item in fields)
    return roots


def dynamic_boundaries(capture: dict, entry: dict) -> dict:
    """Use one closed codec for whole cases and ordered action boundaries."""
    language = entry["language"]
    require(type(capture["outcome"]) is dict and set(capture["outcome"]) == {"kind", "value"}, "invalid dynamic outcome fields")
    declared = (node_receivers.prototype_label(entry),) if "receiver_fixture" in entry and language != "python" else ()
    kind = capture["outcome"]["kind"]
    require(kind in ("return", "error"), "invalid dynamic outcome")
    outcome = {"kind": kind, "graph": dynamic_graph(capture["outcome"]["value"], language, declared)}
    if kind == "error":
        outcome["category"] = "exception"
    return {"before": dynamic_graph(capture["before"], language, declared),
            "outcome": outcome, "after": dynamic_graph(capture["after"], language, declared)}


def dynamic_steps(capture: dict, entry: dict) -> list[dict]:
    """Collection retry counts remain raw evidence outside typed equality."""
    require(type(capture) is dict and type(capture.get("steps")) is list and len(capture["steps"]) <= 32, "invalid dynamic sequence")
    if entry["language"] == "python":
        expected = entry["sequence_configuration"]
        require(len(capture["steps"]) == len(expected), "Python sequence call count differs")
        require(all(type(step) is dict and step.get("id") == "step-" + str(index)
                    and step.get("action") == expected[index]["action"]
                    for index, step in enumerate(capture["steps"])), "Python sequence identities differ")
        require(bool(capture["steps"])
                and capture["before"] == capture["steps"][0].get("before")
                and capture["outcome"] == capture["steps"][-1].get("outcome")
                and capture["after"] == capture["steps"][-1].get("after"),
                "Python sequence outer boundaries differ")
    result = []
    for step in capture["steps"]:
        require(type(step) is dict, "dynamic action must be an object")
        required = {"id", "action", "gaps", "before", "outcome", "after"}
        allowed = required | ({"collection"} if step.get("action") == "collect" else set())
        require(required <= set(step) <= allowed and type(step["gaps"]) is list, "invalid dynamic action fields")
        boundaries = dynamic_boundaries(step, entry)
        if step.get("action") == "collect":
            metadata = step.get("collection")
            require(type(metadata) is dict and set(metadata) == {"completed", "rounds"}
                    and type(metadata["completed"]) is bool and type(metadata["rounds"]) is int
                    and 1 <= metadata["rounds"] <= 256, "invalid collection scheduling evidence")
            bound = next((item["gc_rounds"] for item in entry["sequence_configuration"] if item["action"] == "collect"), 0)
            require(metadata["rounds"] <= bound and boundaries["outcome"]["kind"] == "return"
                    and boundaries["outcome"]["graph"]["roots"].get("result") == dynamic_value({"type": "boolean", "value": metadata["completed"]}, entry["language"])
                    and (metadata["completed"] or bool(step["gaps"])), "collection evidence contradicts its outcome, gap or declared bound")
        result.append({"id": step["id"], "action": step["action"], "gaps": step["gaps"], **boundaries})
    return result


def observation(raw: bytes, entry: dict, contract: dict) -> dict[str, Any]:
    language = entry["language"]
    if language == "cpp" and "cpp_receiver" in entry:
        boundaries = cpp_graph.boundaries(raw, entry, native_scalar)
    elif language == "go" and "receiver_fixture" in entry:
        boundaries = go_graph.boundaries(raw, entry)
    elif language == "java" and "receiver_fixture" in entry:
        boundaries = java_graph.boundaries(raw, entry)
    elif language in ("python", "javascript", "typescript"):
        capture = strict_json(raw)
        allowed = {"before", "outcome", "after"} | ({"steps"} if "sequence_configuration" in entry else set())
        require(type(capture) is dict and set(capture) <= allowed and {"before", "outcome", "after"} <= set(capture), "invalid dynamic boundaries")
        boundaries = dynamic_boundaries(capture, entry)
    else:
        before, outcome, after = scalar_capture(raw, entry)
        boundaries = {"before": before, "outcome": outcome, "after": after}
    result = {"observation_schema_version": 1, "case_id": contract["case_id"], "function_id": contract["function_id"],
            "fixture_sha256": contract["fixture_sha256"], "fixture": {"status": "ready"}, "gaps": [],
            **boundaries}
    if "sequence_configuration" in entry and language in ("python", "javascript", "typescript"):
        result["steps"] = dynamic_steps(capture, entry) if "steps" in capture else []
        require(language != "python" or bool(result["steps"]), "missing Python sequence steps")
    return result
