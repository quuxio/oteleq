"""Closed Java receiver codecs preserve types, identity and incomplete evidence."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters/generation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import java_graph
import typed_capture as typed


def integer(value: int, name: str = "int") -> dict:
    bits, signed = java_graph.INTEGERS[name]
    return {"kind": "integer", "type": "java." + name, "value": str(value), "bits": bits, "signed": signed}


def reference(index: int) -> dict:
    return {"kind": "reference", "node_id": "n" + str(index)}


def entry() -> dict:
    return {"language": "java", "package": "sample", "receiver_class": "Counter", "receiver_fixture": {},
            "parameters": ["int"], "output": "Counter", "globals": [],
            "java_models": [{"name": "Counter", "reason": "", "fields": [
                {"name": "value", "type": "int", "modifiers": 2},
                {"name": "self", "type": "Counter", "modifiers": 0},
                {"name": "total", "type": "int", "modifiers": 10}]}],
            "java_class_roots": [{"name": "total", "type": "int", "modifiers": 10}]}


def graph() -> dict:
    return {"roots": {"receiver": reference(0), "argument:0": integer(7), "static:Counter.total": integer(0)},
            "nodes": [{"id": "n0", "type": "java.object:sample.Counter", "fields": {"value": integer(10), "self": reference(0)}}]}


def capture() -> dict:
    before, after = graph(), graph()
    after["nodes"][0]["fields"]["value"] = integer(17)
    after["roots"]["static:Counter.total"] = integer(7)
    outcome = copy.deepcopy(after)
    outcome["roots"]["result"] = reference(0)
    return {"java_receiver_schema_version": 1, "before": before,
            "outcome": {"kind": "return", "value": outcome}, "after": after}


class JavaGraphTests(unittest.TestCase):
    def decode(self, payload: dict, candidate: dict | None = None) -> dict:
        candidate = candidate or entry()
        return typed.observation(json.dumps(payload).encode(), candidate,
                                 {"case_id": "case", "function_id": "function", "fixture_sha256": "f" * 64})

    def test_receiver_private_static_mutation_and_aliases_enter_shared_observations(self):
        raw = capture()
        result = self.decode(raw)
        self.assertEqual(result["before"], raw["before"])
        self.assertEqual(result["after"], raw["after"])
        self.assertEqual(result["outcome"]["graph"]["roots"]["result"], reference(0))
        self.assertEqual(set(typed.required_roots(entry())), set(raw["before"]["roots"]))

    def test_exact_primitive_widths_signs_float_bits_and_string_units(self):
        for name, (bits, signed) in java_graph.INTEGERS.items():
            for number in ((-2**(bits-1), 2**(bits-1)-1) if signed else (0, 2**bits-1)):
                with self.subTest(name=name, number=number):
                    java_graph.primitive(integer(number, name), name)
        valid = [({"kind": "boolean", "type": "java.boolean", "value": True}, "boolean"),
                 ({"kind": "float", "type": "java.float", "bits": "80000000"}, "float"),
                 ({"kind": "float", "type": "java.double", "bits": "7ff8000000000001"}, "double"),
                 ({"kind": "string", "type": "java.lang.String", "encoding": "utf16_be", "value": "0000d800dfff"}, "string")]
        for value, name in valid:
            java_graph.primitive(value, name)
        invalid = [(integer(128, "byte"), "byte"), (integer(-1, "char"), "char"),
                   ({**integer(1), "value": "01"}, "int"), ({**integer(1), "value": 1}, "int"),
                   ({**integer(1), "bits": True}, "int"), ({**integer(1), "signed": 1}, "int"),
                   ({**valid[0][0], "value": 1}, "boolean"), ({**valid[1][0], "bits": "000"}, "float"),
                   ({**valid[2][0], "bits": "7FF8000000000001"}, "double"),
                   ({**valid[3][0], "value": "d80"}, "string"), ({**valid[3][0], "encoding": "utf8"}, "string"),
                   ({**integer(1), "type": "java.long"}, "int"), ({**integer(1), "extra": 1}, "int"),
                   ({}, "opaque"), (None, "int")]
        for value, name in invalid:
            with self.subTest(value=value, name=name), self.assertRaises(ValueError):
                java_graph.primitive(value, name)

    def test_source_names_boxes_arrays_null_and_void_keep_distinct_representations(self):
        candidate = entry()
        candidate["java_models"][0]["fields"] += [
            {"name": "items", "type": "Object[]", "modifiers": 0},
            {"name": "custom", "type": "String", "modifiers": 0}]
        candidate["java_models"].append({"name": "String", "reason": "", "fields": []})
        schema = java_graph.Schema(candidate)
        self.assertEqual(schema.resolve("String"), "sample.String")
        self.assertEqual(schema.resolve("java.lang.String"), "java.lang.String")
        self.assertEqual(schema.resolve("int[][]"), "[[I")
        value = graph()
        value["nodes"][0]["fields"].update(items=reference(1), custom=reference(5))
        value["nodes"] += [
            {"id": "n1", "type": "java.object:[Ljava.lang.Object;", "fields": {"length": integer(4), "item:0": reference(0), "item:1": reference(2), "item:2": reference(3), "item:3": reference(4)}},
            {"id": "n2", "type": "java.object:java.lang.String", "fields": {"value": {"kind": "string", "type": "java.lang.String", "encoding": "utf16_be", "value": "d800"}}},
            {"id": "n3", "type": "java.object:java.lang.Integer", "fields": {"value": integer(1000)}},
            {"id": "n4", "type": "java.object:java.lang.Object", "fields": {}},
            {"id": "n5", "type": "java.object:sample.String", "fields": {}}]
        self.assertEqual(schema.graph(value, java_graph.root_types(candidate)), value)
        schema.value({"kind": "null"}, "java.lang.Object", {})
        schema.value({"kind": "undefined"}, "void", {})
        self.assertTrue(schema.assignable("[[I", "[Ljava.lang.Object;"))
        self.assertTrue(schema.assignable("[Lsample.Counter;", "[Ljava.lang.Object;"))
        self.assertFalse(schema.assignable("[I", "[J"))
        for actual in ("[Lunknown;", "[Q", "[I;", "[" * 33 + "I"):
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                schema.component(actual)
        for declared in ("opaque", "java.util.List"):
            with self.assertRaises(ValueError):
                schema.resolve(declared)
        with self.assertRaises(ValueError):
            schema.value({"kind": "null"}, "void", {})
        with self.assertRaisesRegex(ValueError, "reference type differs"):
            schema.value(reference(0), "sample.Counter", {"n0": {"type": "java.object:java.lang.Object"}})

    def test_standard_exception_keeps_message_identity_without_formatting(self):
        raw = capture()
        outcome = raw["outcome"]
        outcome["kind"] = "error"
        outcome["value"]["roots"].pop("result")
        outcome["value"]["roots"]["error"] = reference(1)
        outcome["value"]["nodes"] += [
            {"id": "n1", "type": "java.lang.IllegalArgumentException", "fields": {"message": reference(2)}},
            {"id": "n2", "type": "java.object:java.lang.String", "fields": {"value": {"kind": "string", "type": "java.lang.String", "encoding": "utf16_be", "value": "0000d800"}}}]
        self.assertEqual(self.decode(raw)["outcome"]["category"], "exception")
        outcome["value"]["nodes"][1]["fields"]["message"] = {"kind": "null"}
        outcome["value"]["nodes"].pop()
        self.decode(raw)
        outcome["value"]["roots"]["error"] = {"kind": "null"}
        outcome["value"]["nodes"].pop()
        with self.assertRaisesRegex(ValueError, "exception is absent"):
            self.decode(raw)

    def test_altered_missing_extra_storage_and_wrong_types_refuse(self):
        def mutate(path: tuple, replacement: object) -> dict:
            raw = capture()
            value = raw
            for part in path[:-1]:
                value = value[part]
            if replacement is None:
                del value[path[-1]]
            else:
                value[path[-1]] = replacement
            return raw
        controls = [(('java_receiver_schema_version',), True), (('java_receiver_schema_version',), 2),
                    (('before', 'roots', 'receiver'), {"kind": "null"}),
                    (('before', 'roots', 'argument:0'), None),
                    (('before', 'roots', 'extra'), integer(1)),
                    (('before', 'nodes', 0, 'fields', 'value'), None),
                    (('before', 'nodes', 0, 'fields', 'extra'), integer(1)),
                    (('before', 'nodes', 0, 'fields', 'self'), reference(99)),
                    (('before', 'nodes', 0, 'fields', 'self'), {"kind": "reference", "node_id": 0}),
                    (('before', 'nodes', 0, 'type'), 'java.object:java.lang.Object'),
                    (('before', 'nodes', 0, 'type'), 'java.object:unknown'),
                    (('before', 'nodes', 0, 'type'), 'unbound'),
                    (('before', 'nodes', 0, 'id'), 'n1'),
                    (('before', 'nodes', 0, 'fields'), []),
                    (('outcome', 'kind'), 'skipped'),
                    (('outcome', 'extra'), 1), (('extra',), 1)]
        for path, replacement in controls:
            with self.subTest(path=path, replacement=replacement), self.assertRaises(ValueError):
                self.decode(mutate(path, replacement))
        raw = capture()
        raw["before"]["nodes"].append({"id": "n1", "type": "java.object:java.lang.Object", "fields": {}})
        with self.assertRaisesRegex(ValueError, "unreachable"):
            self.decode(raw)
        with self.assertRaises(ValueError):
            java_graph.boundaries(b'{"java_receiver_schema_version":1,"java_receiver_schema_version":1}', entry())

    def test_graph_array_and_encoded_byte_budgets_refuse(self):
        raw = capture()
        raw["before"]["nodes"] *= 513
        with self.assertRaisesRegex(ValueError, "budget"):
            self.decode(raw)
        raw = capture()
        for index in range(1, 34):
            raw["before"]["nodes"][-1]["fields"]["self"] = reference(index)
            raw["before"]["nodes"].append({"id": "n" + str(index), "type": "java.object:sample.Counter", "fields": {"value": integer(1), "self": reference(index)}})
        with self.assertRaisesRegex(ValueError, "depth"):
            self.decode(raw)
        schema = java_graph.Schema(entry())
        with self.assertRaisesRegex(ValueError, "array budget"):
            schema.fields({"type": "java.object:[I", "fields": {"length": integer(4097)}})
        with self.assertRaisesRegex(ValueError, "capture budget"):
            java_graph.boundaries(b' ' * (3 * 262144 + 1025), entry())


if __name__ == "__main__":
    unittest.main()
