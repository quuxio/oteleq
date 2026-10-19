"""Passive Python observer regressions for application descriptors."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters/generation"))
import observe


class PassiveObserverTests(unittest.TestCase):
    def test_dictionary_properties_are_refused_without_running_getters(self):
        calls = []

        class WithProperty:
            @property
            def __dict__(self):
                calls.append("getter")
                return {"value": 1}

        item = WithProperty()
        with self.assertRaisesRegex(ValueError, "descriptor"):
            observe.graph({"root": item})
        self.assertEqual(calls, [])

    def test_instance_lookup_overrides_are_not_invoked(self):
        calls = []

        class WithLookup:
            def __getattribute__(self, name):
                calls.append(name)
                return super().__getattribute__(name)

        item = WithLookup()
        item.value = 2
        result = observe.graph({"root": item})
        self.assertEqual(calls, [])
        self.assertEqual(result["nodes"][0]["fields"], [["value", {"type": "int", "value": "2"}]])

    def test_custom_metaclasses_are_refused_without_metadata_lookup(self):
        calls = []

        class Meta(type):
            def __getattribute__(cls, name):
                calls.append(name)
                return super().__getattribute__(name)

        class WithMeta(metaclass=Meta):
            pass

        item = WithMeta()
        calls.clear()
        with self.assertRaisesRegex(ValueError, "metaclass"):
            observe.graph({"root": item})
        self.assertEqual(calls, [])

    def test_nonstring_object_fields_do_not_run_comparison_callbacks(self):
        calls = []

        class Key:
            def __lt__(self, other):
                calls.append("compare")
                return False

        class Container:
            pass

        item = Container()
        item.__dict__[Key()] = 1
        item.__dict__[Key()] = 2
        with self.assertRaisesRegex(ValueError, "non-string"):
            observe.graph({"root": item})
        self.assertEqual(calls, [])

    def test_exception_fields_use_only_qualified_builtin_descriptors(self):
        calls = []

        class WithArgsProperty(Exception):
            @property
            def args(self):
                calls.append("args getter")
                return ("changed",)

        error = WithArgsProperty("original")
        with self.assertRaisesRegex(ValueError, "exception field descriptor"):
            observe.graph({"error": error})
        self.assertEqual(calls, [])

        class WithLookup(Exception):
            def __getattribute__(self, name):
                calls.append(name)
                return super().__getattribute__(name)

        item = WithLookup("original")
        item.extra = [1, 2]
        result = observe.graph({"error": item})
        self.assertEqual(calls, [])
        self.assertIn("original", str(result))

    def test_invalid_class_identities_and_root_contracts_fail_explicitly(self):
        class InvalidIdentity:
            pass

        InvalidIdentity.__module__ = 12
        item = InvalidIdentity()
        with self.assertRaisesRegex(ValueError, "class identity"):
            observe.graph({"root": item})
        calls = []

        class IdentityDescriptor:
            def __get__(self, instance, owner):
                calls.append("identity getter")
                return "changed"

        class WithIdentityDescriptor:
            __module__ = IdentityDescriptor()

        item = WithIdentityDescriptor()
        with self.assertRaisesRegex(ValueError, "class identity"):
            observe.graph({"root": item})
        self.assertEqual(calls, [])
        for roots in ([], {1: 2}):
            with self.assertRaisesRegex(ValueError, "string-keyed"):
                observe.graph(roots)
