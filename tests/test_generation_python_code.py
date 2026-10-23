"""Pure descriptor data validation preserves aliases and refuses malformed graphs."""

from dataclasses import replace
import json
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import python_code as code
from python_journal import CodeRecord


def fixture() -> dict:
    fields = {"co_consts": 2, "co_names": 8, "co_varnames": 8, "co_cellvars": 8, "co_freevars": 8,
              "co_filename": 3, "co_name": 4, "co_qualname": 4, "co_linetable": 5,
              "co_exceptiontable": 5, "co_code": 6}
    metadata = {"co_argcount": 0, "co_posonlyargcount": 0, "co_kwonlyargcount": 0,
                "co_nlocals": 0, "co_stacksize": 1, "co_flags": 3, "co_firstlineno": 1}
    return {"schema_version": 2, "filesystem": {"encoding": "utf-8", "errors": "surrogateescape"}, "root": 1,
            "nodes": [{"id": 1, "type": "code", "fields": fields, "metadata": metadata},
                      {"id": 2, "type": "tuple", "items": [7]}, {"id": 3, "type": "unicode", "value": "/tmp/entry.py"},
                      {"id": 4, "type": "unicode", "value": "workload"}, {"id": 5, "type": "bytes", "data": ""},
                      {"id": 6, "type": "bytes", "data": "970064005300"}, {"id": 7, "type": "literal", "value": None},
                      {"id": 8, "type": "tuple", "items": []}]}


def record(value: dict | bytes | None = None) -> CodeRecord:
    value = fixture() if value is None else value
    raw = value if type(value) is bytes else json.dumps(value).encode()
    return CodeRecord(1, b"/tmp/entry.py", raw, 1, 0, 0x030c0ff0, 2)


class PythonCodeTests(unittest.TestCase):
    def test_complete_descriptor_keeps_aliases_and_never_constructs_or_runs_code(self) -> None:
        value = code.decode(record())
        self.assertEqual((value.root, value.filesystem, len(value.nodes)), (1, ("utf-8", "surrogateescape"), 8))
        self.assertEqual(dict(value.nodes[0].fields)["co_name"], dict(value.nodes[0].fields)["co_qualname"])
        self.assertEqual(value.nodes[5].value, b"\x97\0\x64\0\x53\0")
        self.assertEqual(value.nodes[0].references, (2, 8, 8, 8, 8, 3, 4, 4, 5, 5, 6))
        self.assertEqual(value.nodes[2].references, ())

    def test_record_schema_types_versions_paths_offsets_and_budgets_are_closed(self) -> None:
        original = record()
        invalid = [None, replace(original, descriptor_version=2.), replace(original, content=b""),
                   replace(original, content=bytearray(b"{}")), replace(original, sequence=True),
                   replace(original, sequence=4097), replace(original, identity=True), replace(original, identity=2 ** 64),
                   replace(original, path=b""), replace(original, path=b"bad\0path"), replace(original, path=b"x" * 65536),
                   replace(original, python_version=True), replace(original, python_version=0x030b0ff0),
                   replace(original, python_version=2 ** 32), replace(original, offset=True),
                   replace(original, offset=1), replace(original, offset=6)]
        for candidate in invalid:
            with self.subTest(candidate=str(candidate)[:60]), self.assertRaises(ValueError):
                code.decode(candidate)
        with patch.object(code, "MAX_PAYLOAD", 1), self.assertRaises(ValueError):
            code.decode(original)

    def test_duplicate_nonfinite_floating_oversized_and_deep_json_refuse(self) -> None:
        for raw in (b'\xff', b'{"a":1,"a":1}', b'{"a":NaN}', b'{"a":Infinity}',
                    b'{"a":1.5}', b'{"a":123456789012}', b'[' * 2000 + b']' * 2000):
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                code.decode(record(raw))

    def test_top_level_schema_codec_names_roots_and_counts_refuse(self) -> None:
        for key, values in {"schema_version": [True, 1, 3], "root": [0, True, 3, 9],
                            "nodes": [[], None], "filesystem": [{}, {"encoding": "utf 8", "errors": "strict"},
                            {"encoding": "utf-8", "errors": "missing-handler"},
                            {"encoding": "missing-codec", "errors": "strict"}]}.items():
            for value in values:
                changed = fixture(); changed[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    code.decode(record(changed))
        with patch.object(code, "MAX_NODES", 2), self.assertRaises(ValueError):
            code.decode(record())
        changed = fixture(); changed["extra"] = 1
        with self.assertRaises(ValueError):
            code.decode(record(changed))

    def test_all_primitive_and_container_node_shapes_keep_exact_payloads(self) -> None:
        nodes = [{"id": 1, "type": "literal", "value": True}, {"id": 1, "type": "ellipsis"},
                 {"id": 1, "type": "integer", "data": "ff80"}, {"id": 1, "type": "float", "data": "7ff8000000000001"},
                 {"id": 1, "type": "complex", "data": "00" * 16}, {"id": 1, "type": "slice", "items": [2, 3, 4]},
                 {"id": 1, "type": "frozenset", "items": [2, 3]}]
        for value in nodes:
            with self.subTest(kind=value["type"]):
                self.assertEqual(code.node(value, 1).kind, value["type"])
        self.assertEqual(code.node(nodes[3], 1).value, bytes.fromhex("7ff8000000000001"))

    def test_malformed_node_fields_values_binary_widths_and_references_refuse(self) -> None:
        invalid = [None, {}, {"id": True, "type": "ellipsis"}, {"id": 2, "type": "ellipsis"},
                   {"id": 1, "type": "unknown"}, {"id": 1, "type": "literal", "value": 1},
                   {"id": 1, "type": "unicode", "value": False}, {"id": 1, "type": "ellipsis", "extra": 1},
                   {"id": 1, "type": "bytes", "data": "FF"}, {"id": 1, "type": "bytes", "data": "f"},
                   {"id": 1, "type": "integer", "data": ""}, {"id": 1, "type": "integer", "data": "0001"},
                   {"id": 1, "type": "float", "data": "00"}, {"id": 1, "type": "complex", "data": "00"},
                   {"id": 1, "type": "slice", "items": [2]}, {"id": 1, "type": "tuple", "items": [True]},
                   {"id": 1, "type": "tuple", "items": [0]}, {"id": 1, "type": "tuple", "items": [65537]},
                   {"id": 1, "type": "frozenset", "items": [2, 2]}, {"id": 1, "type": "tuple", "items": {}}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                code.node(value, 1)

    def test_code_metadata_field_types_local_counts_and_word_width_refuse(self) -> None:
        variants = []
        for section, key, value in (("metadata", "co_flags", True), ("metadata", "co_nlocals", 1),
                                    ("metadata", "co_firstlineno", -1), ("fields", "co_filename", 5),
                                    ("fields", "co_consts", 3), ("fields", "co_names", 2),
                                    ("fields", "co_name", 99)):
            changed = fixture(); changed["nodes"][0][section][key] = value; variants.append(changed)
        changed = fixture(); changed["nodes"][5]["data"] = "00"; variants.append(changed)
        changed = fixture(); del changed["nodes"][0]["fields"]["co_name"]; variants.append(changed)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                code.decode(record(value))
        with patch.object(code, "MAX_EDGES", 1), self.assertRaises(ValueError):
            code.decode(record())

    def test_graph_cycles_unreachable_nodes_depth_and_filename_bytes_refuse(self) -> None:
        changed = fixture(); changed["nodes"][1]["items"] = [1]
        with self.assertRaisesRegex(ValueError, "cycle"):
            code.decode(record(changed))
        changed = fixture(); changed["nodes"].append({"id": 9, "type": "literal", "value": False})
        with self.assertRaisesRegex(ValueError, "unreachable"):
            code.decode(record(changed))
        with patch.object(code, "MAX_DEPTH", 1), self.assertRaisesRegex(ValueError, "depth"):
            code.decode(record())
        changed = fixture(); changed["nodes"][2]["value"] = "/tmp/other.py"
        with self.assertRaisesRegex(ValueError, "filename bytes"):
            code.decode(record(changed))

    def test_iterative_depth_walk_checks_deeper_paths_through_shared_subgraphs(self) -> None:
        nodes = (code.Node("tuple", (2, 3)), code.Node("tuple", (4,)), code.Node("tuple", (2,)), code.Node("literal"))
        with patch.object(code, "MAX_DEPTH", 2), self.assertRaisesRegex(ValueError, "depth"):
            code.graph(nodes, 1)
        with patch.object(code, "MAX_DEPTH", 3):
            code.graph(nodes, 1)

    def test_iterative_walk_agrees_with_independent_small_dag_depth_oracle(self) -> None:
        rng = random.Random(173)
        for size in range(1, 25):
            for _ in range(8):
                edges = {identity: tuple(child for child in range(identity + 1, size + 1) if rng.randrange(4) == 0)
                         for identity in range(1, size + 1)}
                def visit(identity):
                    reached = {identity}
                    height = 0
                    for child in edges[identity]:
                        child_height, descendants = visit(child)
                        height = max(height, child_height + 1)
                        reached.update(descendants)
                    return height, reached
                height, reached = visit(1)
                limit = rng.randrange(1, 8)
                expected = len(reached) == size and height <= limit
                nodes = tuple(code.Node("tuple", edges[identity]) for identity in range(1, size + 1))
                with patch.object(code, "MAX_DEPTH", limit):
                    try:
                        code.graph(nodes, 1)
                    except ValueError:
                        self.assertFalse(expected)
                    else:
                        self.assertTrue(expected)
