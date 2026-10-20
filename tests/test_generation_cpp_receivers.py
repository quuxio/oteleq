"""Compiler-bound C++ fixtures and legal private-copy access without layout edits."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "adapters/generation"),
                str(Path(__file__).resolve().parents[1] / "examples")]
import cpp_receivers
import discovery
import harness
from test_generation_cpp_models import SOURCE


class CppReceiverBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.path = self.base / "app.cpp"
        self.path.write_text(SOURCE)
        self.compiler = os.environ.get("OTELC_CLANGXX") or shutil.which("clang++")

    def discover(self):
        def execute(command, cwd, **kwargs):
            return subprocess.run(command, cwd=cwd, capture_output=True, check=False, timeout=30)
        return discovery.discover(self.path, "cpp", self.base, {"clang++": self.compiler}, execute)

    def contract(self, factory="sample::Counter", source=None):
        if source is not None:
            self.path.write_text(source)
        data = self.discover()
        method = next(item for item in data["functions"] if item["name"] == "sample::Counter::add")
        entry = {**method, "globals": data["globals"]}
        contract = cpp_receivers.bind(entry, data, {"factory": factory, "arguments": [10]}, harness.concrete_arguments)
        return contract, data

    def test_existing_constructor_and_factory_bind_exact_storage_and_fixed_arguments(self):
        for factory, kind in (("sample::Counter", "constructor"), ("sample::make", "function")):
            contract, _ = self.contract(factory)
            self.assertEqual(contract["factory"]["arguments"], [10])
            self.assertEqual(contract["factory"]["parameters"], ["short"])
            self.assertEqual(contract["factory"]["kind"], kind)
            self.assertEqual(contract["method"]["parameters"], ["short"])
            self.assertEqual(contract["method"]["output"], "sample::Counter &")
            self.assertEqual(contract["globals"], [{"name": "sample::Counter::total_", "owner": "sample::Counter", "type": "short"}])
            self.assertEqual(contract["types"]["sample::Counter *"], {"kind": "pointer", "element": "sample::Counter"})
            self.assertEqual(contract["types"]["int[2]"], {"kind": "array", "element": "int", "length": 2})

    def test_missing_ambiguous_and_uninitialised_factories_do_not_bind(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            self.contract("missing")
        uninitialised = SOURCE.replace("value_(seed), ", "")
        with self.assertRaisesRegex(ValueError, "initialisation"):
            self.contract(source=uninitialised)
        overload = SOURCE.replace("public:", "public:\nCounter():Counter(1){}")
        with self.assertRaisesRegex(ValueError, "unique"):
            self.contract(source=overload)
        source = SOURCE.replace("Counter make(Count seed) { return Counter(seed); }", "int make(Count seed){return seed;}")
        with self.assertRaisesRegex(ValueError, "exact source class"):
            self.contract("sample::make", source)

    def test_private_copy_friend_access_compiles_without_source_mutation(self):
        contract, _ = self.contract()
        original = self.path.read_bytes()
        prefix = "namespace __oteleq_cpp {template<class> struct access;}\n"
        private = cpp_receivers.private_source(self.path.read_text(), contract["records"])
        # Constructor and field access occur only in the friend; no private/public macro.
        driver = prefix + private + cpp_receivers.sanitise_identifiers(contract) + '''
namespace __oteleq_cpp {
template<> struct access<::sample::Counter> {
static int run(){sample::Counter value(10);value.value_+=3;value.total_+=3;return value.value_+value.total_;}
};
}
int main(){return __oteleq_cpp::access<sample::Counter>::run()==16?0:1;}
'''
        target = self.base / "private.cpp"
        target.write_text(driver)
        binary = self.base / "private"
        compiled = subprocess.run([self.compiler, "-std=c++17", target, "-o", binary], capture_output=True, check=False, timeout=30)
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        result = subprocess.run([binary], capture_output=True, check=False, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertNotIn("#define private", driver)

    def test_opaque_fields_macro_callbacks_and_changed_ranges_are_visible(self):
        for type_ in ("volatile int", "void *", "int (*)(int)", "Foreign", "int[4097]"):
            with self.subTest(type_=type_), self.assertRaises(ValueError):
                cpp_receivers.type_graph([type_], {})
        contract, _ = self.contract()
        changed = copy.deepcopy(contract["records"])
        changed["sample::Counter"]["body_end"] = 0
        source = self.path.read_text()
        with self.assertRaisesRegex(ValueError, "range"):
            cpp_receivers.private_source(source, changed)
        collision = source + "// __oteleq_cpp"
        with self.assertRaisesRegex(ValueError, "collides"):
            cpp_receivers.private_source(collision, contract["records"])
        sanitised = cpp_receivers.sanitise_identifiers(contract)
        self.assertIn("#undef value_\n", sanitised)
        self.assertIn("#undef make\n", cpp_receivers.sanitise_identifiers(self.contract("sample::make")[0]))

    def test_local_static_storage_is_a_visible_gap(self):
        source = SOURCE.replace("value_ += amount;", "static int hidden=0;hidden+=amount;value_+=amount;")
        with self.assertRaisesRegex(ValueError, "function-local static"):
            self.contract(source=source)

    def test_thread_local_storage_is_a_visible_gap_before_factory_execution(self):
        source = SOURCE + '\nthread_local int hidden=0;\n'
        with self.assertRaisesRegex(ValueError, "thread-local"):
            self.contract(source=source)
