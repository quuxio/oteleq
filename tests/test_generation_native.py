"""Native scalar names are language scoped and checked by the real compiler."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters/generation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import generation as gen
import harness


def entry(language, parameters=None, output="int", globals_=None):
    return {"language": language, "name": "selected", "path": "source." + ("c" if language == "c" else "cpp"),
            "parameters": parameters or [], "output": output, "globals": globals_ or [], "reason": ""}


class NativeScalarTests(unittest.TestCase):
    def compiler(self, language):
        variable, executable = ("OTELC_CLANG", "clang") if language == "c" else ("OTELC_CLANGXX", "clang++")
        compiler = os.environ.get(variable) or shutil.which(executable)
        self.assertIsNotNone(compiler, "Clang C11/C++17 is required for native generator regressions")
        return compiler

    def compile(self, folder, candidate, source, arguments):
        application = folder / candidate["path"]
        application.write_text(source)
        driver = folder / ("driver.c" if candidate["language"] == "c" else "driver.cpp")
        driver.write_text(harness.native_driver(candidate, arguments))
        binary = folder / "application"
        result = subprocess.run([self.compiler(candidate["language"]),
                                 "-std=c11" if candidate["language"] == "c" else "-std=c++17",
                                 str(driver), "-o", str(binary)], capture_output=True, check=False, timeout=30)
        return result, binary

    def test_source_language_not_a_shared_name_catalog_defines_supported_scalars(self):
        for language in ("c", "cpp"):
            for name in ("i32", "int8", "f32", "float64", "number", "String", "string", "boolean"):
                self.assertIsNone(harness.values(name, language), (language, name))
            for name in ("int", "unsigned long long", "float", "double", "_Bool" if language == "c" else "bool"):
                self.assertIsNotNone(harness.values(name, language))
            with tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                (folder / "source.c").write_text("/* application */\n")
                for candidate in (entry(language, output="i32"), entry(language, parameters=["i32"]),
                                  entry(language, globals_=[{"name": "state", "type": "i32"}])):
                    self.assertEqual(gen.qualify_entry(candidate, folder, 1), "blocked")
                    self.assertIn("fixture", candidate["reason"])
        self.assertIsNotNone(harness.values("i32", "rust"))
        self.assertIsNotNone(harness.values("int8", "go"))
        self.assertIsNotNone(harness.values("String", "java"))

    def test_actual_native_primitives_and_booleans_still_compile_and_execute(self):
        for language in ("c", "cpp"):
            for boolean in (False, True):
                with tempfile.TemporaryDirectory() as temporary:
                    folder = Path(temporary)
                    type_ = ("_Bool" if language == "c" else "bool") if boolean else "int"
                    source = f"int state=0;\nint selected({type_} value){{state=value?7:0;return state+1;}}\n"
                    candidate = entry(language, [type_], globals_=[{"name": "state", "type": "int"}])
                    result, binary = self.compile(folder, candidate, source, [True if boolean else 7])
                    self.assertEqual(result.returncode, 0, result.stderr)
                    observation = folder / "observation"
                    result = subprocess.run([str(binary)], env={**os.environ, "OTELEQ_OBSERVATION": str(observation)},
                                            capture_output=True, check=False, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    expected = (8).to_bytes(ctypes.sizeof(ctypes.c_int), sys.byteorder).hex()
                    self.assertIn(("return:int:" + expected).encode(), observation.read_bytes())

    def test_compiler_rejects_objects_in_results_globals_or_implicit_arguments(self):
        for language in ("c", "cpp"):
            record = "typedef struct {char kind;int value;} i32;\n"
            cases = [
                (entry(language, output="i32"), record + "i32 selected(void){i32 value={1,7};return value;}\n", []),
                (entry(language, globals_=[{"name": "state", "type": "i32"}]),
                 record + "i32 state={1,7};\nint selected(void){return 7;}\n", []),
                (entry(language, ["i32"]), record + "int selected(i32 value){return value.value;}\n", [7]),
            ]
            if language == "cpp":
                cases[-1] = (entry(language, ["i32"]),
                             "struct i32 {int value;i32(int x):value(x){}};\nint selected(i32 value){return value.value;}\n", [7])
            for candidate, source, arguments in cases:
                with tempfile.TemporaryDirectory() as temporary:
                    result, _ = self.compile(Path(temporary), candidate, source, arguments)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(b"native type requires a scalar fixture", result.stderr)

    def test_unknown_cpp_exception_accessors_are_not_called(self):
        sources = [
            ("#include <stdexcept>\nint selected(void){throw std::runtime_error(\"known\");}\n", 0),
            ("#include <exception>\n#include <cstdio>\nstruct Error:std::exception {const char* what()const noexcept override{std::fputs(\"CALLBACK\\n\",stdout);return \"unknown\";}};\n"
             "int selected(void){throw Error{};}\n", 91),
        ]
        for source, expected in sources:
            with tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                result, binary = self.compile(folder, entry("cpp"), source, [])
                self.assertEqual(result.returncode, 0, result.stderr)
                observation = folder / "observation"
                result = subprocess.run([str(binary)], env={**os.environ, "OTELEQ_OBSERVATION": str(observation)},
                                        capture_output=True, check=False, timeout=10)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(result.stdout, b"")
                if expected == 0:
                    self.assertIn(b"known", observation.read_bytes())


if __name__ == "__main__":
    unittest.main()
