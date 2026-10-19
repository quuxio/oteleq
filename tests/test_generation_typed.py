"""Typed codecs consume actual workers and retain exact scalar/graph semantics."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters/generation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import discovery
import harness
import observe
import policy
import typed_capture as typed
import test_generation_native as native_tests
import test_generation_static as static_tests


def entry(language, **changes):
    return {"language": language, "globals": [], "name": "selected", "output": "int", **changes}


def contract(candidate):
    return {"case_id": "case", "function_id": "selected", "fixture_sha256": "a" * 64,
            "required_roots": typed.required_roots(candidate), "expected_baseline": {"kind": "return"}}


class TypedCodecTests(unittest.TestCase):
    def test_exact_integer_float_string_and_byte_domains(self):
        self.assertEqual(typed.managed_scalar(b"u128:340282366920938463463374607431768211455", "rust", {})["bits"], 128)
        self.assertEqual(typed.managed_scalar(b"f32:80000000", "rust", {})["bits"], "80000000")
        self.assertEqual(typed.managed_scalar(b"float32:7f800001", "go", {})["bits"], "7f800001")
        self.assertEqual(typed.managed_scalar(b"@uint8|main.small:0xff", "go", {})["value"], "255")
        self.assertEqual(typed.managed_scalar(b"@bool|main.Flag:true", "go", {}),
                         {"kind": "boolean", "type": "go.main.Flag", "value": True})
        self.assertEqual(typed.managed_scalar(b'string:"\\xff\\000"', "go", {})["value"], "ff00")
        self.assertEqual(typed.managed_scalar(b'String:"\\u{1f600}\\0"', "rust", {})["value"], "f09f988000")
        self.assertEqual(typed.managed_scalar(b"string:utf16:0000d800dfff", "java", {})["value"], "0000d800dfff")
        self.assertEqual(typed.dynamic_value({"type": "str", "value": "\ud800"}, "python")["value"], "0000d800")
        self.assertEqual(typed.dynamic_value({"type": "string", "value": "\ud800"}, "javascript")["value"], "d800")
        for language, raw, label in (("rust", b"bool:true", "rust.bool"),
                                     ("java", b"java.lang.Boolean:dHJ1ZQ==", "java.lang.Boolean")):
            self.assertEqual(typed.managed_scalar(raw, language, {})["type"], label)
        for value in ("-0", "01", "+1", "", "NaN"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                typed.integer("int", value, 32)
        for payload in (b"i8:128", b"u8:-1", b"unknown:7", b"float32:000000000", b"char:10000"):
            language = "java" if payload.startswith(b"char") else "rust"
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                typed.managed_scalar(payload, language, {})

    def test_python_alias_cycles_dictionary_order_and_instance_order_are_explicit(self):
        class Cell:
            pass
        cell = Cell()
        cell.first = 1
        cell.second = 2
        cell.owner = cell
        graph = typed.dynamic_graph(observe.graph({"root": cell, "alias": cell}), "python")
        self.assertEqual(graph["roots"]["root"], graph["roots"]["alias"])
        node = graph["nodes"][0]
        self.assertEqual(node["fields"]["property:owner"], graph["roots"]["root"])
        self.assertEqual(node["fields"]["order:0"]["value"], typed.string("first", "python")["value"])
        del cell.first
        cell.first = 1
        changed = typed.dynamic_graph(observe.graph({"root": cell}), "python")
        self.assertNotEqual(node["fields"]["order:0"], changed["nodes"][0]["fields"]["order:0"])
        mapping = {"b": 1, "a": 2}
        graph = typed.dynamic_graph(observe.graph({"root": mapping}), "python")
        self.assertEqual(graph["nodes"][0]["fields"]["entry:0:key"], typed.string("b", "python"))

    def test_hidden_slots_and_builtin_base_state_are_refused(self):
        class Slotted:
            __slots__ = ("hidden", "__dict__")
        class DerivedList(list):
            pass
        for value in (Slotted(), DerivedList([7]), OSError(2,"missing","hidden-filename"),
                      UnicodeDecodeError("utf8", b"x", 0, 1, "hidden fields")):
            with self.subTest(type=type(value)), self.assertRaises(ValueError):
                observe.graph({"root": value})
        calls = []
        class Identity:
            def __eq__(self, other):
                calls.append("equality")
                return False
        class Base:
            pass
        Base.__module__ = Identity()
        class Derived(Base):
            pass
        derived = Derived()
        with self.assertRaises(ValueError):
            observe.graph({"root": derived})
        self.assertEqual(calls, [])

    def test_outcome_framing_retains_native_newlines_without_delimiter_guessing(self):
        raw = b'before\nerror:std::runtime_error\tfirst\nafter\nlast\nafter\n'
        candidate = entry("cpp")
        abi = b'abi:{"byte_order":"little","char_signed":true,"char_bits":8,"bits":{}}\n'
        _, outcome, _ = typed.scalar_capture(abi + raw, candidate)
        self.assertEqual(outcome["graph"]["nodes"][0]["fields"]["message"]["hex"], b"first\nafter\nlast".hex())
        self.assertEqual(outcome["graph"]["nodes"][0]["type"], "cpp.std::runtime_error")
        candidate = entry("rust")
        for malformed in (b"", b"before\nafter\n", b"abi:[]\nbefore\nreturn:i32:7\nafter\n"):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                typed.scalar_capture(malformed, candidate)

    def test_missing_or_ambiguous_codec_fields_never_disappear(self):
        invalid = [{"type": "null", "value": 7}, {"type": "int", "value": "7", "hidden": 2},
                   {"type": "boolean", "value": 1}, {"ref": -1}, {"type": "opaque"}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises((ValueError, KeyError)):
                typed.dynamic_value(value, "python")
        with self.assertRaises(ValueError):
            typed.own_fields([["key", {"type": "null"}], ["key", {"type": "null"}]], "python", False)
        for escaped in ('"\\q"', '"\\x0"', '"\\u{110000}"'):
            with self.subTest(escaped=escaped), self.assertRaises((ValueError, UnicodeError)):
                typed.quoted(escaped, "rust")
        candidate = entry("python")
        frozen = contract(candidate)
        for capture in (None, [], {"before": {}, "outcome": {"kind": "return", "value": {}, "hidden": 1}, "after": {}}):
            payload = json.dumps(capture).encode()
            with self.subTest(capture=capture), self.assertRaises(ValueError):
                typed.observation(payload, candidate, frozen)

    def test_expected_error_fixtures_are_explicit_and_strict(self):
        fixture = {"function": "*selected*", "cases": [[]],
                   "expected_baseline": {"kind": "error", "category": "panic", "type": "rust.panic.str"}}
        self.assertEqual(policy.fixture(fixture, 0)["expected_baseline"], fixture["expected_baseline"])
        for outcome in ({}, {"kind": "error"}, {"kind": "return", "type": "x"},
                        {"kind": "error", "category": "unknown", "type": "x"}):
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                policy.expected_baseline(outcome)

    def test_real_native_workers_record_actual_abi_before_and_after_values(self):
        helper = native_tests.NativeScalarTests()
        for language in ("c", "cpp"):
            candidate = native_tests.entry(language, ["double"], "double", [{"name": "state", "type": "int"}])
            with tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                compiled, binary = helper.compile(folder, candidate, "int state=0;double selected(double value){state=7;return -0.0;}\n", [1.3])
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                output = folder / "observation"
                result = subprocess.run([binary], env={**os.environ, "OTELEQ_OBSERVATION": str(output)}, capture_output=True, check=False, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                captured = typed.observation(output.read_bytes(), candidate, contract(candidate))
                self.assertEqual(captured["before"]["roots"]["global:state"]["value"], "0")
                self.assertEqual(captured["after"]["roots"]["global:state"]["value"], "7")
                self.assertEqual(captured["outcome"]["graph"]["roots"]["result"]["bits"], "8000000000000000")

    def test_real_rust_go_and_java_workers_emit_lossless_type_tags(self):
        scenarios = [
            ("rust", "static mut STATE:i32=0;fn selected()->f32{unsafe{STATE=7;}f32::from_bits(0x7f800001)}", "f32", "STATE", "i32", "7f800001"),
            ("go", 'package main\nimport "math"\nvar state int=0\nfunc selected() float32{state=7;return math.Float32frombits(0x7f800001)}\n', "float32", "state", "int", "7f800001"),
            ("java", 'class App {static int state=0;static String selected(){state=7;return "\\u0000\\ud800";}}', "String", "App.state", "int", "0000d800"),
            ("go", 'package main\ntype Flag bool\nvar state int=0\nfunc selected() Flag{state=7;return Flag(true)}\n', "Flag", "state", "int", True),
        ]
        for language, source, output, name, type_, expected in scenarios:
            with self.subTest(language=language):
                globals_ = [{"name": name, "type": type_}]
                compiled, result, raw = static_tests.StaticObserverTests().execute(language, source, output, globals_=globals_)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                self.assertEqual(result.returncode, 0, result.stderr)
                candidate = entry(language, globals=globals_, output=output)
                captured = typed.observation(raw, candidate, contract(candidate))
                self.assertEqual(captured["before"]["roots"]["global:" + name]["value"], "0")
                self.assertEqual(captured["after"]["roots"]["global:" + name]["value"], "7")
                value = captured["outcome"]["graph"]["roots"]["result"]
                self.assertEqual(value.get("bits", value.get("value")), expected)
                if output == "Flag":
                    self.assertEqual(value["type"], "go.main.Flag")

    def test_actual_standard_error_and_panic_payloads_are_typed(self):
        scenarios = [
            ("rust", 'fn selected()->i32{panic!("known")}\n', "i32", "rust.panic.str"),
            ("go", 'package main\nfunc selected() int{panic("known")}\n', "int", "go.string"),
            ("java", 'class App {static int selected(){throw new IllegalArgumentException("known");}}', "int", "java.lang.IllegalArgumentException"),
        ]
        for language, source, output, type_ in scenarios:
            compiled, result, raw = static_tests.StaticObserverTests().execute(language, source, output)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            self.assertEqual(result.returncode, 0, result.stderr)
            captured = typed.observation(raw, entry(language, output=output), contract(entry(language)))
            outcome = captured["outcome"]
            self.assertEqual(outcome["kind"], "error")
            self.assertEqual(outcome["category"], "exception" if language == "java" else "panic")
            value = outcome["graph"]["roots"]["error"]
            actual = outcome["graph"]["nodes"][0]["type"] if value["kind"] == "reference" else value["type"]
            self.assertEqual(actual, type_)

    def test_real_python_javascript_and_typescript_graph_workers(self):
        for language, extension in (("python", "py"), ("javascript", "mjs"), ("typescript", "mts")):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                path = "app." + extension
                if language == "python":
                    source = "state={'calls':0}\nalias=state\ndef selected(value:int):\n state['calls']+=value\n return state\n"
                    function = discovery.python_inventory(source)["functions"][0]
                    candidate = {**entry(language), **function, "path": path,
                                 "globals": [{"name": "state"}, {"name": "alias"}]}
                    program = sys.executable
                else:
                    annotation = ":number" if language == "typescript" else ""
                    source = "class Map {constructor(){console.log('CALLBACK')}}\nclass JSON {static stringify(){console.log('CALLBACK')}}\nconst state={calls:0};const alias=state;\n" + f"function selected(value{annotation}){{state.calls+=value;return state;}}\n"
                    candidate = entry(language, path=path, parameters=["number"], binding_capture_offset=0,
                                      globals=[{"name": "state"}, {"name": "alias"}])
                    program = os.environ.get("OTELC_NODE") or shutil.which("node")
                (folder / path).write_text(source)
                driver = harness.materialise(folder, candidate, [7])
                output = folder / "observation"
                result = subprocess.run([program, driver], cwd=folder, env={**os.environ, "OTELEQ_OBSERVATION": str(output)}, capture_output=True, check=False, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, b"")
                captured = typed.observation(output.read_bytes(), candidate, contract(candidate))
                graph = captured["outcome"]["graph"]
                self.assertEqual(graph["roots"]["result"], graph["roots"]["global:state"])
                self.assertEqual(graph["roots"]["global:state"], graph["roots"]["global:alias"])
                self.assertEqual(set(captured["before"]["roots"]), set(typed.required_roots(candidate)))


if __name__ == "__main__":
    unittest.main()
