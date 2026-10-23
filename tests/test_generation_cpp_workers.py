"""Real Clang workers preserve private state, cycles, bit patterns and aliases."""
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
import cpp_graph
import discovery
import generation
import harness
import typed_capture
from test_generation_cpp_models import SOURCE


class CppWorkerTests(unittest.TestCase):
    def test_preprocessor_defined_spelling_can_name_a_private_source_field(self):
        _, capture, _, _ = self.captured(SOURCE.replace('value_', 'defined'))
        for graph, expected in ((capture['before'], '10'), (capture['after'], '13')):
            value = self.field(graph, graph['roots']['receiver'], 'defined')
            self.assertEqual(value['fields']['value']['value'], expected)

    def test_unicode_field_macro_cannot_invoke_an_application_getter(self):
        source = '''class Counter {
 int value_;
 int& \u6570\u636e;
 int& read_alias()const{++calls_;return \u6570\u636e;}
public:
 inline static int calls_=0;
 explicit Counter(int seed):value_(seed),\u6570\u636e(value_){}
 int add(int amount){value_+=amount;return value_;}
};
#define \u6570\u636e read_alias()
'''
        _, capture, _, _ = self.captured(source, method='Counter::add', factory='Counter')
        for graph in (capture['before'], capture['outcome']['graph'], capture['after']):
            calls = self.node(graph, graph['roots']['global:Counter::calls_'])
            self.assertEqual(calls['fields']['value']['value'], '0')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.compiler = os.environ.get("OTELC_CLANGXX") or shutil.which("clang++")

    def worker(self, source=SOURCE, method="sample::Counter::add", arguments=None, factory="sample::Counter"):
        project = self.base / str(len(list(self.base.iterdir())))
        project.mkdir()
        path = project / "app.cpp"
        path.write_text(source)
        def execute(command, cwd, **kwargs):
            return subprocess.run(command, cwd=cwd, capture_output=True, check=False, timeout=30,
                                  input=kwargs.get("input_data"))
        data = discovery.discover(path, "cpp", project, {"clang++": self.compiler}, execute)
        function = next(item for item in data["functions"] if item["name"] == method and item.get("cpp_function", {}).get("has_body"))
        entry = {**function, "path": "app.cpp", "language": "cpp", "globals": data["globals"]}
        if factory is not None:
            generation.receiver_fixture(entry, data, {"factory": factory, "arguments": [10]})
        self.assertEqual(entry["reason"], "")
        driver = harness.materialise(project, entry, [3] if arguments is None else arguments)
        binary = project / "application"
        built = subprocess.run([self.compiler, "-std=c++17", "-O2", "-pthread", driver, "-o", binary],
                               capture_output=True, check=False, timeout=30)
        self.assertEqual(built.returncode, 0, built.stderr.decode())
        observation = project / "observation"
        result = subprocess.run([binary], env={**os.environ, "OTELEQ_OBSERVATION": str(observation)},
                                capture_output=True, check=False, timeout=15)
        raw = observation.read_bytes() if observation.exists() else b""
        return entry, result, raw, project

    def captured(self, *args, **kwargs):
        entry, result, raw, project = self.worker(*args, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return entry, cpp_graph.boundaries(raw, entry, typed_capture.native_scalar), raw, project

    @staticmethod
    def node(graph, value):
        return graph["nodes"][int(value["node_id"][1:])]

    def field(self, graph, owner, name):
        return self.node(graph, self.node(graph, owner)["fields"]["field:" + name])

    def test_private_scalar_array_cycle_interior_and_return_aliases(self):
        entry, capture, raw, project = self.captured()
        before, after, outcome = capture["before"], capture["after"], capture["outcome"]["graph"]
        receiver = after["roots"]["receiver"]
        value = self.field(after, receiver, "value_")
        self.assertEqual(value["fields"]["value"]["value"], "13")
        initial = self.field(before, before["roots"]["receiver"], "value_")
        self.assertEqual(initial["fields"]["value"]["value"], "10")
        self.assertEqual(self.node(after, after["roots"]["global:sample::Counter::total_"])["fields"]["value"]["value"], "3")
        self.assertEqual(self.field(after, receiver, "self_")["fields"]["value"], receiver)
        self.assertEqual(self.field(after, receiver, "pointer_")["fields"]["value"]["node_id"], value["id"])
        returned = self.node(outcome, outcome["roots"]["result"])
        self.assertEqual(returned["fields"]["value"], outcome["roots"]["receiver"])
        self.assertNotIn(b"0x", raw)
        self.assertIn("friend struct", (project / "app.cpp").read_text())
        self.assertEqual(set(typed_capture.required_roots(entry)), set(before["roots"]))

    def test_const_out_of_line_method_and_existing_free_factory(self):
        _, capture, _, _ = self.captured(method="sample::Counter::read", arguments=[], factory="sample::make")
        graph = capture["outcome"]["graph"]
        self.assertEqual(self.node(graph, graph["roots"]["result"])["fields"]["value"]["value"], "10")

    def test_crlf_source_keeps_compiler_byte_offsets_for_private_access(self):
        self.captured(SOURCE.replace("\n", "\r\n"))

    def test_global_record_name_does_not_resolve_to_the_generated_helper(self):
        source = '''class Graph {
short value_;
public:explicit Graph(short seed):value_(seed){}
Graph& add(short amount){value_+=amount;return *this;}
};
'''
        _, capture, _, _ = self.captured(source, method="Graph::add", factory="Graph")
        graph = capture["after"]
        self.assertEqual(self.field(graph, graph["roots"]["receiver"], "value_")["fields"]["value"]["value"], "13")

    def test_constructor_fixture_does_not_return_small_self_referential_objects(self):
        source = '''class Small {
short value_;Small* self_;
explicit Small(short seed):value_(seed),self_(this){}
public:int add(short amount){value_+=amount;return value_;}
};
'''
        _, capture, _, _ = self.captured(source, method="Small::add", factory="Small")
        for graph in (capture["before"], capture["outcome"]["graph"], capture["after"]):
            root = graph["roots"]["receiver"]
            self.assertEqual(self.field(graph, root, "self_")["fields"]["value"], root)

    def test_out_of_line_constructor_and_private_static_factory(self):
        source = SOURCE.replace('explicit Counter(Count seed) : value_(seed), self_(this), pointer_(&value_), child_{}, array_{} {}',
                                'explicit Counter(Count seed);\nprivate: static Counter create(Count seed){return Counter(seed);}\npublic:')
        source = source.replace('int Counter::read()', 'Counter::Counter(Count seed):value_(seed),self_(this),pointer_(&value_),child_{},array_{} {}\nint Counter::read()')
        self.captured(source, factory="sample::Counter::create")

    def test_ref_and_noexcept_expression_keep_const_overload_binding(self):
        source = SOURCE.replace("int read() const;", "int read() const & noexcept(true);")
        source = source.replace("int Counter::read() const {", "int Counter::read() const & noexcept(true) {")
        entry, _, _, _ = self.captured(source, method="sample::Counter::read", arguments=[])
        self.assertEqual(entry["cpp_receiver"]["method"]["qualifiers"], "const & noexcept(true)")

    def test_multidimensional_arrays_and_float_payloads_keep_exact_storage(self):
        source = SOURCE.replace("int array_[2];", "int array_[2][3]; float small_; double wide_; short& alias_;")
        source = source.replace("child_{}, array_{} {}", "child_{}, array_{{1,2,3},{4,5,6}}, small_(0.0f), wide_(-0.0), alias_(value_) {unsigned bits=0x7fa00017;__builtin_memcpy(__builtin_addressof(small_),__builtin_addressof(bits),4);}")
        _, capture, _, _ = self.captured(source)
        graph = capture["after"]
        receiver = graph["roots"]["receiver"]
        fields = self.node(graph, receiver)["fields"]
        self.assertEqual(self.field(graph, receiver, "small_")["fields"]["value"]["bits"], "7fa00017")
        self.assertEqual(self.field(graph, receiver, "wide_")["fields"]["value"]["bits"], "8000000000000000")
        self.assertEqual(self.field(graph, receiver, "alias_")["fields"]["value"], fields["field:value_"])
        rows = self.field(graph, receiver, "array_")["fields"]
        self.assertEqual(set(rows), {"location", "item:0", "item:1"})
        for row in range(2):
            columns = self.node(graph, rows["item:" + str(row)])["fields"]
            for column in range(3):
                self.assertEqual(self.node(graph, columns["item:" + str(column)])["fields"]["value"]["value"], str(1 + row*3 + column))

    def test_observation_does_not_invoke_overloaded_address_or_global_allocation(self):
        source = '''#include <cstdlib>
#include <cstddef>
int allocation_count=0;
void* operator new(std::size_t size){++allocation_count;return std::malloc(size);}
void operator delete(void* value) noexcept {std::free(value);}
''' + SOURCE.replace("public:", "public:\nCounter* operator&(){throw 123;}\nconst Counter* operator&()const{throw 123;}")
        _, capture, _, _ = self.captured(source)
        for graph in (capture["before"], capture["outcome"]["graph"], capture["after"]):
            allocation = self.node(graph, graph["roots"]["global:allocation_count"])
            self.assertEqual(allocation["fields"]["value"]["value"], "0")

    def test_void_null_pointer_and_macro_tail_do_not_change_access(self):
        source = SOURCE.replace("Counter& add(Count amount) noexcept", "void add(Count amount) noexcept").replace("return *this;", "pointer_=nullptr;")
        source += '\n#define value_ invalid_callback()\n#define g invalid_callback()\n'
        _, capture, _, _ = self.captured(source)
        self.assertEqual(capture["outcome"]["graph"]["roots"]["result"], {"kind": "unit", "type": "cpp.unit"})
        after = capture["after"]
        pointer = self.field(after, after["roots"]["receiver"], "pointer_")
        self.assertEqual(pointer["fields"]["value"], {"kind": "null"})

    def test_exception_observes_post_throw_private_mutation_without_custom_accessors(self):
        source = '#include <stdexcept>\n' + SOURCE.replace("value_ += amount; total_ += amount; return *this;",
                    'value_ += amount; throw std::runtime_error("bad\\nmessage");').replace(" noexcept", "")
        _, capture, _, _ = self.captured(source)
        self.assertEqual(capture["outcome"]["kind"], "error")
        error = capture["outcome"]["graph"]["roots"]["error"]
        self.assertEqual(error, {"kind": "bytes", "type": "cpp.exception.std::runtime_error", "hex": b"bad\nmessage".hex()})
        after = capture["after"]
        self.assertEqual(self.field(after, after["roots"]["receiver"], "value_")["fields"]["value"]["value"], "13")
        custom = source.replace('throw std::runtime_error("bad\\nmessage");', "throw 7;")
        _, result, raw, _ = self.worker(custom)
        self.assertEqual(result.returncode, 91)
        self.assertEqual(raw, b"")

    def test_malformed_or_incomplete_storage_cannot_pass(self):
        entry, _, raw, _ = self.captured()
        metadata, _, payload = raw.partition(b"\n")
        original = json.loads(payload)
        for alteration in ("root", "field", "type", "raw_address", "unreachable", "primitive"):
            document = copy.deepcopy(original)
            graph = document["after"]
            if alteration == "root":
                del graph["roots"]["receiver"]
            elif alteration == "field":
                del graph["nodes"][0]["fields"]["field:value_"]
            elif alteration == "type":
                graph["nodes"][0]["type"] = "cpp.storage:Other"
            elif alteration == "raw_address":
                location = next(node for node in graph["nodes"] if node["type"] == "cpp.location")
                location["fields"]["address"] = {"kind": "integer", "value": "123"}
            elif alteration == "primitive":
                scalar = next(node for node in graph["nodes"] if node["type"] == "cpp.storage:short")
                scalar["fields"]["value"]["bytes"] = "FF"
            else:
                graph["nodes"].append({"id": "n" + str(len(graph["nodes"])), "type": "cpp.location", "fields": {}})
            altered = metadata + b"\n" + json.dumps(document).encode()
            with self.subTest(alteration=alteration), self.assertRaises(ValueError):
                cpp_graph.boundaries(altered, entry, typed_capture.native_scalar)
