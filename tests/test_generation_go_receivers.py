"""Actual Go workers observe private storage without application callbacks."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation
import go_graph
import go_project
import go_receivers
import harness
import policy
import sequences
import typed_capture

SOURCE = r'''package counter
import "math"
type Number int16
type Counter struct {
 value Number
 self *Counter
 pointer *Number
 array [2]uint64
 label string
 ratio float32
 wide float64
}
var shared *Counter
var total Number
func New(seed Number)*Counter {
 value:=&Counter{value:seed,label:"\xff\x00é😀",ratio:math.Float32frombits(0x80000000),wide:math.Float64frombits(0x7ff0000000000001)}
 value.self=value;value.pointer=&value.value;shared=value;return value
}
func (value *Counter) Add(amount Number)*Counter {
 value.value+=amount;value.array[1]++;total+=amount;value.pointer=&total;return value
}
func (value *Counter) String()string{panic("APP_CALLBACK")}
func (value *Counter) MarshalJSON()([]byte,error){panic("APP_CALLBACK")}
'''


class GoReceiverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.cache.cleanup)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.snapshot = self.base / "source"
        (self.snapshot / "counter").mkdir(parents=True)
        (self.snapshot / "go.mod").write_text("module example.test/receiver\n\ngo 1.20\n")
        self.source = self.snapshot / "counter/counter.go"
        self.source.write_text(SOURCE)
        self.go = Path(os.environ.get("OTELC_GO") or shutil.which("go"))
        self.options = go_project.settings({"module_roots": ["."]})
        self.environment = {**os.environ, **go_project.environment(self.options), "GOTOOLCHAIN": "local",
                            "GOCACHE": str(Path(self.cache.name) / "build"),
                            "GOMODCACHE": str(self.base / "modules"), "PYTHONDONTWRITEBYTECODE": "1"}

    def execute(self, command, cwd, input_data=None):
        return subprocess.run(command, cwd=cwd, input=input_data, env=self.environment,
                              capture_output=True, check=False, timeout=90)

    def entry(self, method="Counter.Add", factory="New", construction=None):
        found = go_project.discover(self.source, self.snapshot, self.options, self.go, self.execute, {})
        found["entrypoints"] = [item for item in found["functions"] if item.get("entrypoint")]
        function = next(item for item in found["functions"] if item["name"] == method)
        configuration = policy.validate({"adapters": {"go": self.options}, "functions": {"include": ["*"+method]},
                                         "fixtures": [{"function": "*"+method, "cases": [[3]],
                                                       "receiver": {"factory": factory, "arguments": [10] if construction is None else construction}}]})
        args = argparse.Namespace(configuration=configuration, cases=1)
        entry = generation.inventory_entry(function, found, "counter/counter.go", "go", "a"*64, self.snapshot, args)
        self.assertEqual(entry["status"], "ready", entry["reason"])
        return entry

    def worker(self, entry, arguments=None, extra_env=None):
        private = self.base / "private"
        shutil.copytree(self.snapshot, private)
        driver = harness.materialise(private, entry, [3] if arguments is None else arguments)
        observation = self.base / "observation.json"
        env = {**self.environment, "OTELEQ_OBSERVATION": str(observation), **(extra_env or {})}
        process = subprocess.run([self.go, "run", driver], cwd=private, env=env,
                                 capture_output=True, check=False, timeout=90)
        return process, observation

    def node(self, graph, reference):
        return graph["nodes"][int(reference["node_id"][1:])]["fields"]

    def test_private_fields_cycles_interior_aliases_and_exact_scalar_bits(self):
        before = generation.manifest(self.snapshot)
        entry = self.entry()
        result, path = self.worker(entry)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"")
        data = go_graph.boundaries(path.read_bytes(), entry)
        for boundary, number in ((data["before"], "10"), (data["after"], "13")):
            receiver = boundary["roots"]["receiver"]
            fields = self.node(boundary, self.node(boundary, receiver)["value"])
            self.assertEqual(self.node(boundary, fields["value"])["value"]["value"], number)
            self.assertEqual(self.node(boundary, fields["self"])["value"], receiver)
            self.assertEqual(self.node(boundary, boundary["roots"]["global:shared"])["value"], receiver)
            self.assertEqual(self.node(boundary, fields["label"])["value"]["value"], "ff00c3a9f09f9880")
            self.assertEqual(self.node(boundary, fields["ratio"])["value"]["bits"], "80000000")
            self.assertEqual(self.node(boundary, fields["wide"])["value"]["bits"], "7ff0000000000001")
            pointer = self.node(boundary, fields["pointer"])["value"]
            self.assertEqual(pointer, fields["value"] if number == "10" else boundary["roots"]["global:total"])
        self.assertEqual(data["outcome"]["graph"]["roots"]["result"], data["outcome"]["graph"]["roots"]["receiver"])
        contract = {"case_id": "case", "function_id": "function", "fixture_sha256": "b"*64}
        typed = typed_capture.observation(path.read_bytes(), entry, contract)
        self.assertEqual(typed["gaps"], [])
        self.assertEqual(set(typed_capture.required_roots(entry)), set(data["before"]["roots"]))
        self.assertEqual(generation.manifest(self.snapshot), before)

    def test_value_receiver_uses_a_copy_and_primitive_panic_keeps_state(self):
        for mode in ("value", "panic"):
            with self.subTest(mode=mode):
                if mode == "value":
                    self.source.write_text(SOURCE.replace("func (value *Counter) Add(amount Number)*Counter {\n value.value+=amount;value.array[1]++;total+=amount;value.pointer=&total;return value\n}",
                                                         "func (value Counter) Add(amount Number)Number{value.value+=amount;return value.value}"))
                else:
                    self.source.write_text(SOURCE.replace("value.value+=amount;value.array[1]++;total+=amount;value.pointer=&total;return value",
                                                         'value.value+=amount;panic("expected")'))
                entry = self.entry()
                result, path = self.worker(entry)
                self.assertEqual(result.returncode, 0, result.stderr)
                data = go_graph.boundaries(path.read_bytes(), entry)
                fields = self.node(data["after"], self.node(data["after"], data["after"]["roots"]["receiver"])["value"])
                self.assertEqual(self.node(data["after"], fields["value"])["value"]["value"], "10" if mode == "value" else "13")
                if mode == "value":
                    self.assertEqual(data["outcome"]["graph"]["roots"]["result"]["value"], "13")
                else:
                    self.assertEqual(data["outcome"]["category"], "panic")
                    self.assertEqual(data["outcome"]["graph"]["roots"]["error"]["value"], b"expected".hex())
                shutil.rmtree(self.base / "private")
                path.unlink()

    def test_nil_pointer_receiver_and_shadowed_application_builtins(self):
        self.source.write_text('''package counter
type Counter struct { value int64 }
type string int
type bool int
func len(){}
func append(){}
func New()*Counter{return nil}
func (value *Counter) Read(amount int64)int64{if value==nil{return amount};return value.value}
''')
        entry = self.entry(method="Counter.Read", construction=[])
        result, path = self.worker(entry)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = go_graph.boundaries(path.read_bytes(), entry)
        self.assertEqual(data["before"]["roots"]["receiver"], {"kind": "null"})
        self.assertEqual(data["outcome"]["graph"]["roots"]["result"]["value"], "3")

    def test_main_package_receiver_retains_source_binding_and_runtime_type(self):
        self.source.write_text(SOURCE.replace("package counter", "package main") + "\nfunc main(){}\n")
        entry = self.entry()
        result, path = self.worker(entry)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = go_graph.boundaries(path.read_bytes(), entry)
        self.assertEqual(data["outcome"]["graph"]["roots"]["receiver"], data["outcome"]["graph"]["roots"]["result"])
        self.assertEqual(entry["go_context"]["import_path"], "example.test/receiver/counter")
        self.assertEqual(entry["go_receiver_type"], "*main.Counter")

    def test_pointer_conversion_retains_aliases_across_nominal_types(self):
        source = SOURCE.replace('import "math"', 'import "math"\nimport "os"')
        source = source.replace("pointer *Number", "pointer *int16").replace("value.pointer=&value.value", "value.pointer=(*int16)(&value.value)")
        source = source.replace("value.value+=amount;value.array[1]++;total+=amount;value.pointer=&total;return value",
                                'if os.Getenv("CHANGE_ALIAS")=="yes"{other:=int16(value.value);value.pointer=&other};return value')
        self.source.write_text(source)
        entry = self.entry()
        for flag in ("no", "yes"):
            result, path = self.worker(entry, extra_env={"CHANGE_ALIAS": flag})
            self.assertEqual(result.returncode, 0, result.stderr)
            data = go_graph.boundaries(path.read_bytes(), entry)
            for boundary in ("before", "after"):
                graph = data[boundary]
                fields = self.node(graph, self.node(graph, graph["roots"]["receiver"])["value"])
                value = self.node(graph, fields["value"])
                pointer = self.node(graph, self.node(graph, fields["pointer"])["value"])
                self.assertEqual(value["value"]["value"], pointer["value"]["value"])
                self.assertIn("location", value)
                self.assertEqual(value["location"] == pointer["location"], boundary == "before" or flag == "no")
            shutil.rmtree(self.base / "private")
            path.unlink()

    def test_observer_failures_do_not_produce_complete_capture(self):
        changes = [SOURCE.replace('value:=&Counter{', 'panic("bad factory");value:=&Counter{'),
                   SOURCE.replace("math.Float32frombits(0x80000000)", "math.Float32frombits(0x7f800001)"),
                   SOURCE.replace('import "math"', 'import "math"\nimport "strings"').replace('label:"\\xff\\x00é😀"', 'label:strings.Repeat("x",65537)')]
        for source in changes:
            self.source.write_text(source)
            entry = self.entry()
            result, path = self.worker(entry)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"Go receiver fixture or observation is unavailable", result.stderr)
            self.assertNotIn(b"APP_CALLBACK", result.stderr)
            self.assertFalse(path.exists())
            shutil.rmtree(self.base / "private")

    def test_ordered_worker_retains_one_receiver_and_every_intermediate_panic_boundary(self):
        self.source.write_text(SOURCE.replace("value.pointer=&total;return value",
                                              'value.pointer=&total;if amount<0{panic("known")};return value'))
        entry = self.entry()
        # This directly exercises the plain observer component. Public source
        # provider negotiation and native ownership have separate qualification.
        entry["sequence_configuration"] = sequences.validate([
            {"action": "call", "arguments": "case"},
            {"action": "call", "arguments": [-2], "expected_baseline": {"kind": "error", "category": "panic", "type": "go.string"}},
            {"action": "call", "arguments": [4]}], policy.expected_baseline)
        original = generation.manifest(self.snapshot)
        result, path = self.worker(entry)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        data = go_graph.boundaries(path.read_bytes(), entry)
        self.assertEqual(len(data["steps"]), 3)
        for index, (before, after, total) in enumerate(((10, 13, 3), (13, 11, 1), (11, 15, 5))):
            step = data["steps"][index]
            self.assertEqual((step["id"], step["action"], step["gaps"]), ("step-" + str(index), "call", []))
            for boundary, expected in (("before", before), ("after", after)):
                graph = step[boundary]
                fields = self.node(graph, self.node(graph, graph["roots"]["receiver"])["value"])
                self.assertEqual(self.node(graph, fields["value"])["value"]["value"], str(expected))
            graph = step["after"]
            global_value = self.node(graph, graph["roots"]["global:total"])["value"]
            self.assertEqual(global_value["value"], str(total))
            if index == 1:
                self.assertEqual(step["outcome"]["category"], "panic")
                self.assertEqual(step["outcome"]["graph"]["roots"]["error"]["value"], "6b6e6f776e")
            else:
                self.assertEqual(step["outcome"]["kind"], "return")
                roots = step["outcome"]["graph"]["roots"]
                self.assertEqual(roots["result"], roots["receiver"])
        self.assertEqual(data["before"], data["steps"][0]["before"])
        self.assertEqual(data["after"], data["steps"][-1]["after"])
        self.assertEqual(generation.manifest(self.snapshot), original)
        raw = json.loads(path.read_text())
        for change in ("count", "id", "action", "step-fields", "schema", "before", "outcome", "field"):
            changed = copy.deepcopy(raw)
            if change == "count": changed["steps"].pop()
            elif change == "id": changed["steps"][1]["id"] = "step-0"
            elif change == "action": changed["steps"][1]["action"] = "release"
            elif change == "step-fields": changed["steps"][1]["extra"] = True
            elif change == "schema": changed["go_receiver_schema_version"] = 2
            elif change == "before": changed["before"] = changed["steps"][1]["before"]
            elif change == "outcome": changed["outcome"] = changed["steps"][1]["outcome"]
            else: changed["steps"][1]["after"]["roots"].pop("receiver")
            with self.subTest(change=change), self.assertRaises(ValueError):
                go_graph.boundaries(json.dumps(changed).encode(), entry)
        with self.assertRaises(ValueError):
            go_graph.boundaries(path.read_bytes(), {key: value for key, value in entry.items() if key != "sequence_configuration"})

    def test_sequence_capture_budget_failure_cannot_return_a_complete_observation(self):
        source = SOURCE.replace('import "math"', 'import "math"\nimport "strings"')
        source = source.replace('label:"\\xff\\x00é😀"', 'label:strings.Repeat("x",8192)')
        self.source.write_text(source)
        entry = self.entry()
        entry["sequence_configuration"] = [{"action": "call", "arguments": "case"}] * 32
        original = generation.manifest(self.snapshot)
        result, path = self.worker(entry)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"Go receiver fixture or observation is unavailable", result.stderr)
        self.assertNotIn(b"APP_CALLBACK", result.stderr)
        self.assertLessEqual(path.stat().st_size, 3 * 262144 + 1024)
        with self.assertRaises(ValueError):
            go_graph.boundaries(path.read_bytes(), entry)
        self.assertEqual(generation.manifest(self.snapshot), original)

    def test_missing_rebound_or_unreachable_storage_cannot_qualify(self):
        entry = self.entry()
        result, path = self.worker(entry)
        self.assertEqual(result.returncode, 0, result.stderr)
        original = json.loads(path.read_text())
        for change in ("root", "field", "type", "location", "location-fields", "unreachable", "version", "outcome"):
            data = copy.deepcopy(original)
            graph = data["before"]
            if change == "root":
                graph["roots"].pop("receiver")
            elif change == "field":
                next(node for node in graph["nodes"] if node["type"] == "go.storage:example.test/receiver/counter.Counter")["fields"].pop("value")
            elif change == "type":
                graph["nodes"][0]["type"] = "go.storage:unbound"
            elif change == "location":
                next(node for node in graph["nodes"] if "location" in node["fields"])["fields"]["location"] = {"kind": "null"}
            elif change == "location-fields":
                next(node for node in graph["nodes"] if node["type"] == "go.location")["fields"]["unexpected"] = {"kind": "null"}
            elif change == "unreachable":
                node = copy.deepcopy(graph["nodes"][0]);node["id"] = "n" + str(len(graph["nodes"]));graph["nodes"].append(node)
            elif change == "version":
                data["go_receiver_schema_version"] = True
            else:
                data["outcome"]["kind"] = "unknown"
            encoded = json.dumps(data).encode()
            with self.subTest(change=change), self.assertRaises(ValueError):
                go_graph.boundaries(encoded, entry)

    def test_scalar_constants_and_panic_payloads_are_strict(self):
        self.assertEqual(go_receivers.scalar_input(True), {"kind": "boolean", "value": "true"})
        self.assertEqual(go_receivers.scalar_input(-0.0), {"kind": "float", "value": "8000000000000000"})
        self.assertEqual(go_receivers.scalar_input("\x00é"), {"kind": "string", "value": "00c3a9"})
        with self.assertRaises(ValueError):
            go_receivers.scalar_input([])
        values = [{"kind": "integer", "type": "go.int16", "bits": 16, "signed": True, "value": "-3"},
                  {"kind": "boolean", "type": "go.bool", "value": False},
                  {"kind": "float", "type": "go.float64", "bits": "7ff0000000000001"},
                  {"kind": "float", "type": "go.float32", "bits": "80000000"},
                  {"kind": "string", "type": "go.string", "encoding": "raw_bytes", "value": "ff"}]
        for value in values:
            go_graph.panic_value(value)
        for value in ({"kind": "null"}, {"kind": "object", "type": "go.Counter"},
                      {"kind": "float", "type": "go.float32", "bits": "7fc00000"},
                      {"kind": "integer", "type": "go.int16", "bits": 16, "signed": True, "value": "32768"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                go_graph.panic_value(value)
