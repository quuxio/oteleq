"""Real static-language observers must not invoke application formatters."""
import argparse
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
import policy


class StaticObserverTests(unittest.TestCase):
    def execute(self, language, source, output="int", arguments=None, parameters=None):
        """Compile a real generated worker, then retain only its bounded results."""
        candidate = {"language": language, "name": "App.selected" if language == "java" else "selected",
                     "path": {"java": "App.java", "rust": "app.rs", "go": "app.go"}[language],
                     "parameters": parameters or [], "output": output, "globals": [],
                     "file_functions": [], "package": "", "package_end": len("package main")}
        tool = {"java": "javac", "go": "go", "rust": "rustc"}[language]
        compiler = os.environ.get("OTELC_" + tool.upper()) or shutil.which(tool)
        self.assertIsNotNone(compiler, tool + " is required for static observer regressions")
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            original = folder / candidate["path"]
            original.write_text(source)
            driver = harness.materialise(folder, candidate, arguments or [])
            binary = folder / "application"
            if language == "java":
                build = [compiler, "-d", folder, original, driver]
                java = os.environ.get("OTELC_JAVA") or shutil.which("java")
                self.assertIsNotNone(java)
                command = [java, "-cp", folder, "OteleqDriver"]
            elif language == "rust":
                build = [compiler, "--edition=2024", driver, "-o", binary]
                command = [binary]
            else:
                build = [compiler, "build", "-o", binary, driver]
                command = [binary]
            environment = {**os.environ, "OTELEQ_OBSERVATION": str(folder / "observation"), "GOTOOLCHAIN": "local"}
            compiled = subprocess.run(build, capture_output=True, env=environment, timeout=60, check=False)
            if compiled.returncode:
                return compiled, None, b""
            executed = subprocess.run(command, capture_output=True, env=environment, timeout=15, check=False)
            observation = folder / "observation"
            return compiled, executed, observation.read_bytes() if observation.is_file() else b""

    def test_java_unknown_messages_and_string_objects_do_not_call_application_methods(self):
        sources = [
            ("class App {static class E extends RuntimeException {public String getMessage(){System.out.println(\"CALLBACK\");return \"x\";}} static int selected(){throw new E();}}", "int"),
            ("class String {public java.lang.String toString(){java.lang.System.out.println(\"CALLBACK\");return \"x\";}} class App {static String selected(){return new String();}}", "String"),
        ]
        for source, output in sources:
            with self.subTest(output=output):
                compiled, result, observation = self.execute("java", source, output)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(observation, b"")

    def test_java_bootstrap_helpers_and_known_errors_are_qualified(self):
        sources = [
            ("class Long {static java.lang.String toHexString(long v){System.out.println(\"CALLBACK\");return \"masked\";}} class App {static double selected(){return 1.5;}}", "double", b"double:3ff8000000000000"),
            ("class App {static int selected(){throw new IllegalArgumentException(\"known\");}}", "int", b"error:java.lang.IllegalArgumentException:string:utf16:006b006e006f0077006e"),
            ("class App {static String selected(){return \"\\u0000\\ud800\\udfff\";}}", "String", b"string:utf16:0000d800dfff"),
        ]
        for source, output, expected in sources:
            with self.subTest(output=output):
                compiled, result, observation = self.execute("java", source, output)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, b"")
                self.assertIn(expected, observation)

    def test_rust_custom_debug_and_to_bits_require_a_fixture(self):
        sources = [
            ("#[allow(non_camel_case_types)] struct i32; impl std::fmt::Debug for i32 {fn fmt(&self,f:&mut std::fmt::Formatter)->std::fmt::Result {println!(\"CALLBACK\");write!(f,\"masked\")}} fn selected()->i32{i32}", "i32"),
            ("#[allow(non_camel_case_types)] struct f32; impl f32 {fn to_bits(&self)->u32{println!(\"CALLBACK\");7}} fn selected()->f32{f32}", "f32"),
        ]
        for source, output in sources:
            compiled, result, _ = self.execute("rust", source, output)
            self.assertNotEqual(compiled.returncode, 0)
            self.assertIn(b"__oteleq_Value", compiled.stderr)
            self.assertIsNone(result)

    def test_rust_primitives_and_reserved_standard_macros_preserve_values(self):
        sources = [
            ("macro_rules! format {($($v:tt)*)=>{{println!(\"CALLBACK\");std::string::String::new()}}} fn selected()->i32{7}", "i32", b"return:i32:7"),
            ("fn selected()->u128{u128::MAX}", "u128", b"340282366920938463463374607431768211455"),
            ("fn selected()->f32{f32::from_bits(0x80000000)}", "f32", b"return:f32:80000000"),
            ("fn selected()->f64{f64::from_bits(0x7ff8000000000001)}", "f64", b"return:f64:7ff8000000000001"),
            ('fn selected()->String{String::from("known")}', "String", b'return:String:"known"'),
            ("fn selected(){}", "()", b"return:():()"),
            ("fn selected()->i32{panic!(\"known\")}", "i32", b'error:str:"known"'),
        ]
        for source, output, expected in sources:
            with self.subTest(output=output):
                compiled, result, observation = self.execute("rust", source, output)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, b"")
                self.assertIn(expected, observation)

    def test_go_custom_formatters_and_recovered_opaque_values_cannot_pass(self):
        sources = [
            "package main\nimport \"fmt\"\ntype int struct{}\nfunc (int) GoString() string{fmt.Println(\"CALLBACK\");return \"masked\"}\nfunc selected() int{return int{}}\n",
            "package main\nimport \"fmt\"\ntype custom struct{}\nfunc (custom) GoString() string{fmt.Println(\"CALLBACK\");return \"masked\"}\nfunc selected() int{panic(custom{})}\n",
        ]
        for source in sources:
            compiled, result, observation = self.execute("go", source)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            self.assertEqual(result.returncode, 91, result.stderr)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(observation, b"")

    def test_go_primitives_preserve_bits_and_shadowed_literals_do_not_change_inputs(self):
        sources = [
            ("package main\nimport \"math\"\nfunc selected() float32{return math.Float32frombits(0x7fc00001)}\n", "float32", [], [], b"return:float32:7fc00001"),
            ("package main\nimport \"math\"\nfunc selected() float32{return math.Float32frombits(0x7f800001)}\n", "float32", [], [], b"return:float32:7f800001"),
            ("package main\nimport \"math\"\nfunc selected() float64{return math.Float64frombits(0x8000000000000000)}\n", "float64", [], [], b"return:float64:8000000000000000"),
            ("package main\nconst true=false\nfunc selected(v bool) bool{return v}\n", "bool", [True], ["bool"], b"return:bool:true"),
            ("package main\nfunc selected() int{panic(\"known\")}\n", "int", [], [], b'error:string:"known"'),
            ("package main\nimport \"fmt\"\ntype int int64\nfunc (int) GoString() string{fmt.Println(\"CALLBACK\");return \"masked\"}\nfunc selected() int{return int(7)}\n", "int", [], [], b"return:main.int:7"),
        ]
        for source, output, arguments, parameters, expected in sources:
            compiled, result, observation = self.execute("go", source, output, arguments, parameters)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, b"")
            self.assertIn(expected, observation)

    def test_go_shadowed_recovery_is_a_visible_inventory_blocker(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "app.go").write_text("package main\n")
            for name in ("panic", "recover"):
                function = {"name": "selected", "line": 1, "reason": "", "parameters": [], "output": "int"}
                discovered = {"globals": [], "entrypoints": [], "functions": [function, {"name": name}]}
                args = argparse.Namespace(configuration=policy.load(None), cases=1)
                candidate = gen.inventory_entry(function, discovered, "app.go", "go", "a" * 64, folder, args)
                self.assertEqual(candidate["status"], "blocked")
                self.assertIn("shadowed Go", candidate["reason"])


if __name__ == "__main__":
    unittest.main()
