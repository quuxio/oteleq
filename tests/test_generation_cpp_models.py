"""Actual Clang source models preserve private storage, owners and initialisation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters/generation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import cpp_models
import discovery


SOURCE = '''#include <cstdint>
namespace sample {
using Count = std::int16_t;
struct Child { int value = 1; };
class Counter {
    Count value_;
    Counter* self_;
    Count* pointer_;
    Child child_;
    int array_[2];
    inline static Count total_ = 0;
public:
    explicit Counter(Count seed) : value_(seed), self_(this), pointer_(&value_), child_{}, array_{} {}
    Counter& add(Count amount) noexcept { value_ += amount; total_ += amount; return *this; }
    int read() const;
};
int Counter::read() const { return value_; }
Counter make(Count seed) { return Counter(seed); }
}
'''


class CppModelTests(unittest.TestCase):
    def test_demangler_retains_actual_alias_domains_and_const_method_identity(self):
        data, path = self.model()
        demangler = Path(os.environ.get("OTELC_CLANGXX", "/opt/homebrew/opt/llvm@22/bin/clang++")).with_name("llvm-cxxfilt")
        if not demangler.is_file():
            demangler = Path(shutil.which("llvm-cxxfilt") or shutil.which("c++filt"))
        def execute(command, cwd, input_data):
            return subprocess.run(command, cwd=cwd, input=input_data, capture_output=True, check=False, timeout=30)
        cpp_models.bind_symbols(data, demangler, path.parent, execute)
        read = next(item for item in data["cpp_functions"] if item["name"] == "sample::Counter::read")
        add = next(item for item in data["cpp_functions"] if item["name"] == "sample::Counter::add")
        self.assertEqual(read["compiler_identity"], "sample::Counter::read() const")
        self.assertEqual(add["compiler_identity"], "sample::Counter::add(short)")
        result = subprocess.CompletedProcess([], 1, b"", b"bad")
        with self.assertRaisesRegex(ValueError, "resolution"):
            cpp_models.bind_symbols(data, demangler, path.parent, Mock(return_value=result))
        data["cpp_functions"][0]["symbol"] = "bad\nsymbol"
        with self.assertRaisesRegex(ValueError, "framing"):
            cpp_models.bind_symbols(data, demangler, path.parent, Mock())

    def model(self, source=SOURCE):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "app.cpp"
        path.write_text(source)
        compiler = os.environ.get("OTELC_CLANGXX") or shutil.which("clang++")
        self.assertIsNotNone(compiler)
        result = subprocess.run([compiler, "-O2", "-pthread", "-std=c++17", "-Xclang", "-ast-dump=json", "-fsyntax-only", path],
                                capture_output=True, check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_text(), source)
        return cpp_models.Inventory(json.loads(result.stdout), path).export(), path

    def test_private_fields_aliases_source_ranges_and_out_of_line_owner(self):
        data, path = self.model()
        self.assertEqual(set(data["cpp_records"]), {"sample::Counter", "sample::Child"})
        record = data["cpp_records"]["sample::Counter"]
        self.assertEqual([field["name"] for field in record["fields"]], ["value_", "self_", "pointer_", "child_", "array_"])
        self.assertTrue(all(field["access"] == "private" and field["physical"] for field in record["fields"]))
        self.assertEqual([field["canonical"] for field in record["fields"]],
                         ["short", "sample::Counter *", "short *", "sample::Child", "int[2]"])
        self.assertEqual(record["statics"][0]["canonical"], "short")
        self.assertEqual(record["statics"][0]["access"], "private")
        self.assertEqual(path.read_bytes()[record["body_end"]:record["body_end"]+1], b"}")
        add = next(item for item in data["cpp_functions"] if item["name"] == "sample::Counter::add")
        self.assertEqual(add["parameters"], ["short"])
        self.assertEqual(add["parameter_spellings"], ["Count"])
        self.assertEqual(add["output"], "sample::Counter &")
        self.assertEqual(add["qualifiers"], "noexcept")
        reads = [item for item in data["cpp_functions"] if item["name"] == "sample::Counter::read"]
        self.assertEqual(len(reads), 2)
        self.assertTrue(all(item["owner"] == "sample::Counter" and item["qualifiers"] == "const" for item in reads))
        self.assertEqual(sum(item["has_body"] for item in reads), 1)

    def test_constructor_initialisers_and_implicit_overloads_stay_distinct(self):
        data, _ = self.model()
        record = data["cpp_records"]["sample::Counter"]
        constructor = next(item for item in record["constructors"] if not item["implicit"])
        self.assertEqual(constructor["parameters"], ["short"])
        self.assertEqual(constructor["initialised_fields"], ["value_", "self_", "pointer_", "child_", "array_"])
        self.assertFalse(constructor["delegated"])
        implicit = [item for item in data["cpp_functions"] if item["kind"] == "CXXConstructorDecl" and item["implicit"]]
        self.assertGreaterEqual(len(implicit), 4)
        self.assertEqual(len({item["symbol"] for item in implicit}), len(implicit))
        child = data["cpp_records"]["sample::Child"]
        self.assertTrue(child["fields"][0]["in_class_initialiser"])
        uninitialised, _ = self.model(SOURCE.replace("value_(seed), ", ""))
        constructor = next(item for item in uninitialised["cpp_records"]["sample::Counter"]["constructors"] if not item["implicit"])
        self.assertNotIn("value_", constructor["initialised_fields"])

    def test_inventory_uses_the_actual_native_build_mode_and_owner(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "app.cpp"
        path.write_text('''#if defined(__STRICT_ANSI__) && defined(_REENTRANT)
int matched(){return 1;}
#else
int wrong_mode(){return 0;}
#endif
''')
        compiler = os.environ.get("OTELC_CLANGXX") or shutil.which("clang++")
        def execute(command, cwd, **kwargs):
            return subprocess.run(command, cwd=cwd, capture_output=True, check=False, timeout=30)
        data = discovery.discover(path, "cpp", path.parent, {"clang++": compiler}, execute)
        self.assertEqual([item["name"] for item in data["functions"]], ["matched"])
        path.write_text(SOURCE)
        data = discovery.discover(path, "cpp", path.parent, {"clang++": compiler}, execute)
        reads = [item for item in data["functions"] if item["name"] == "sample::Counter::read"]
        self.assertEqual(len(reads), 2)
        self.assertTrue(all(item["cpp_function"]["owner"] == "sample::Counter" for item in reads))

    def test_unsupported_storage_shapes_remain_declared_and_macro_ranges_refuse(self):
        source = '''struct Base {int base=0;};
struct Derived:Base { volatile int value=1; unsigned flag:2; virtual ~Derived(){} };
union Choice { int value; double other; };
#define RECORD struct Macro {int value=1;};
RECORD
template<class T> struct Generic {T value;};
void selected(){}
'''
        data, _ = self.model(source)
        derived = data["cpp_records"]["Derived"]
        self.assertEqual(derived["bases"], ["Base"])
        self.assertTrue(derived["polymorphic"])
        self.assertEqual(derived["fields"][0]["canonical"], "volatile int")
        self.assertTrue(derived["fields"][1]["bitfield"])
        self.assertEqual(data["cpp_records"]["Choice"]["tag"], "union")
        self.assertNotIn("Macro", data["cpp_records"])
        self.assertNotIn("Generic", data["cpp_records"])


if __name__ == "__main__":
    unittest.main()
