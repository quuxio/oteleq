"""Java fixture declarations refuse unavailable source and storage contracts."""
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "adapters/generation"),
                str(Path(__file__).resolve().parents[1] / "examples")]
import harness
import java_receivers


def metadata() -> tuple[dict, dict, dict]:
    entry = {"language": "java", "name": "Counter.run", "parameters": ["int"], "package": "sample", "globals": [],
             "reason": "instance method needs an object fixture", "java_receiver_class": "Counter",
             "java_receiver_reason": "", "java_static": False, "java_constructor": False}
    discovered = {"classes": [{"name": "Counter", "reason": "", "fields": [{"name": "value", "type": "int", "modifiers": 2}]}],
                  "functions": [{"name": "Counter.<init>", "line": 2, "parameters": ["int"],
                                 "reason": "constructor needs an object fixture", "java_receiver_reason": ""}]}
    return entry, discovered, {"factory": "Counter", "arguments": [10]}


class JavaReceiverBindingTests(unittest.TestCase):
    def test_source_constructor_implicit_constructor_and_static_factory_are_bound(self):
        entry, discovered, declaration = metadata()
        java_receivers.bind(entry, discovered, declaration, harness.concrete_arguments)
        fixture = entry["receiver_fixture"]
        self.assertEqual(fixture["kind"], "constructor")
        self.assertEqual(fixture["source_function"], "Counter.<init>")
        self.assertEqual(fixture["factory"], "Counter")
        self.assertEqual(fixture["arguments"], [10])
        self.assertEqual(entry["globals"], [])
        entry, discovered, declaration = metadata()
        discovered["functions"] = []
        declaration["arguments"] = []
        java_receivers.bind(entry, discovered, declaration, harness.concrete_arguments)
        self.assertIsNone(entry["receiver_fixture"]["source_function"])
        entry, discovered, declaration = metadata()
        discovered["functions"][0].update(name="Counter.make", java_static=True, java_private=True, reason="private method needs an access fixture")
        declaration["factory"] = "make"
        java_receivers.bind(entry, discovered, declaration, harness.concrete_arguments)
        self.assertEqual(entry["receiver_fixture"]["kind"], "function")
        self.assertTrue(entry["receiver_fixture"]["private"])

    def test_unsupported_receiver_shapes_and_unbound_storage_are_blockers(self):
        controls = [{"java_static": True}, {"java_constructor": True},
                    {"java_receiver_class": None}, {"reason": "generic or abstract method needs a fixture"},
                    {"java_receiver_reason": "inherited storage"},
                    {"globals": [{"name": "Other.value", "type": "int"}]}]
        for changes in controls:
            entry, discovered, declaration = metadata()
            entry.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                java_receivers.bind(entry, discovered, declaration, harness.concrete_arguments)
        for kind in ("missing", "reserved", "many-classes", "many-fields", "field-type"):
            entry, discovered, declaration = metadata()
            if kind == "missing":
                discovered["classes"] = []
            elif kind == "reserved":
                discovered["classes"].append({"name": "OteleqGraph", "reason": "", "fields": []})
            elif kind == "many-classes":
                discovered["classes"] += [{"name": "Extra" + str(i), "reason": "", "fields": []} for i in range(64)]
            elif kind == "many-fields":
                discovered["classes"][0]["fields"] *= 257
            else:
                discovered["classes"][0]["fields"][0]["type"] = "java.util.List"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                java_receivers.bind(entry, discovered, declaration, harness.concrete_arguments)

    def test_ambiguous_missing_unsupported_and_nonstatic_factories_refuse(self):
        for kind in ("ambiguous", "unsupported", "receiver", "missing", "nonstatic", "arguments"):
            entry, discovered, declaration = metadata()
            if kind == "ambiguous":
                discovered["functions"] *= 2
            elif kind == "unsupported":
                discovered["functions"][0]["reason"] = "generic or abstract method needs a fixture"
            elif kind == "receiver":
                discovered["functions"][0]["java_receiver_reason"] = "inherited storage"
            elif kind == "missing":
                declaration["factory"] = "missing"
            elif kind == "nonstatic":
                declaration["factory"] = "make"
                discovered["functions"][0].update(name="Counter.make", java_static=False, reason="")
            else:
                declaration["arguments"] = ["not an integer"]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                java_receivers.bind(entry, discovered, declaration, harness.concrete_arguments)

    def test_supported_closed_storage_types_and_array_bounds(self):
        models = [{"name": "Counter"}]
        for name in ("Counter", "sample.Counter", "Object", "java.lang.String", "int[][]", "String[]", "int" + "[]" * 32):
            self.assertTrue(java_receivers.supported_type(name, models, "sample"), name)
        for name in ("void", "void[]", "java.util.List", "int" + "[]" * 33):
            self.assertFalse(java_receivers.supported_type(name, models, "sample"), name)
        self.assertTrue(java_receivers.supported_type("void", models, "sample", void=True))


if __name__ == "__main__":
    unittest.main()
