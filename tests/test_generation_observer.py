"""Passive Python observer regressions for application descriptors."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters/generation"))
import observe
import harness


class PassiveObserverTests(unittest.TestCase):
    def test_selected_function_binding_uses_frozen_code_not_a_startup_span(self):
        original = "def selected(value:int)->int:\n    return value+1\n"
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder).resolve() / "target.py"
            source.write_text(original)
            expected = observe.function_code(source, "selected", 1)
            module = ModuleType("target")
            exec(compile(original, str(source), "exec"), vars(module))
            self.assertEqual(observe.bound_function(module, "selected", expected)(7), 8)
            exec(compile("def replacement(value):return 99\n", str(source), "exec"), vars(module))
            vars(module)["selected"] = vars(module)["replacement"]
            with self.assertRaisesRegex(ValueError, "binding differs"):
                observe.bound_function(module, "selected", expected)
            vars(module)["selected"] = lambda value: 99
            with self.assertRaisesRegex(ValueError, "binding differs"):
                observe.bound_function(module, "selected", expected)
            with self.assertRaisesRegex(ValueError, "unique source"):
                observe.function_code(source, "missing", 1)
            with self.assertRaisesRegex(ValueError, "binding fixture"):
                observe.bound_function(object(), "selected", expected)

    def test_dynamic_callable_binding_does_not_invoke_lookup_or_call_hooks(self):
        calls = []

        class Callable:
            def __getattribute__(self, name):
                calls.append(name)
                return super().__getattribute__(name)

            def __call__(self, value):
                calls.append("call")
                return value

        module = ModuleType("target")
        vars(module)["selected"] = Callable()
        expected = compile("def selected(value):return value\n", "target.py", "exec").co_consts[0]
        with self.assertRaisesRegex(ValueError, "binding differs"):
            observe.bound_function(module, "selected", expected)
        self.assertEqual(calls, [])

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


class NodePassiveObserverTests(unittest.TestCase):
    def test_node_driver_rejects_rebinding_and_preserves_hashbang_and_directives(self):
        node = os.environ.get("OTELC_NODE") or shutil.which("node")
        self.assertIsNotNone(node)
        prologue = "#!/usr/bin/env node\n'use strict';"
        source = prologue + "\n// unicode: \U0001f600\nfunction sample(value){return value+1;}\n"
        entry = {"name": "sample", "path": "driver.mjs", "globals": [], "binding_capture_offset": len(prologue.encode())}
        for rebound in (False, True):
            with tempfile.TemporaryDirectory() as folder:
                observation = Path(folder) / "observation.json"
                script = Path(folder) / "driver.mjs"
                body = source + ("sample=(value)=>99;\n" if rebound else "")
                generated = Path(folder) / "_oteleq_generated"
                generated.mkdir()
                (generated / "node_observe.mjs").write_text(harness.JS_OBSERVER)
                script.write_text(harness.js_driver(entry, [7], body))
                result = subprocess.run([node, script], capture_output=True, check=False, timeout=30,
                                        env={**os.environ, "OTELEQ_OBSERVATION": str(observation)})
                if rebound:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(b"selected function binding differs", result.stderr)
                    self.assertFalse(observation.exists())
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(observation.exists())

    def test_node_observer_does_not_evaluate_error_names_accessors_or_proxies(self):
        node = os.environ.get("OTELC_NODE") or shutil.which("node")
        self.assertIsNotNone(node, "Node24+ is required for the shared Node observer regression")
        source = "import {test} from 'node:test';import assert from 'node:assert/strict';\n" + harness.JS_OBSERVER + r"""
test('error identity never evaluates prototype name getters', () => {
  let calls=0;
  const previous=Object.getOwnPropertyDescriptor(Error.prototype,'name');
  try {
    Object.defineProperty(Error.prototype,'name',{get(){calls++;return 'changed'},configurable:true});
    const graph=__oteleqGraph({error:new Error('original')});
    assert.equal(calls,0);
    assert.equal(graph.nodes[0].type,'Error');
  } finally { Object.defineProperty(Error.prototype,'name',previous); }
});
test('application accessors are refused without evaluating them', () => {
  let calls=0;
  const value={get field(){calls++;return 1}};
  assert.throws(()=>__oteleqGraph({value}),/accessor state/);
  assert.equal(calls,0);
});
test('proxy state is refused before evaluating traps', () => {
  let calls=0;
  const value=new Proxy({}, {getPrototypeOf(){calls++;return null},ownKeys(){calls++;return []}});
  assert.throws(()=>__oteleqGraph({value}),/proxy state/);
  assert.equal(calls,0);
});
"""
        result = subprocess.run([node, "--test-reporter=tap", "--input-type=module", "-"], input=source,
                                capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
