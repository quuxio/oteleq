"""The actual compiled Go gate, including refusals, has its own coverage floor."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_rendezvous as gate


class GoRendezvousTests(unittest.TestCase):
    @staticmethod
    def context():
        return {"module_root": ".", "directory": ".", "import_path": "example.test/oteleqgate"}

    def environment(self):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("OTEL", "GH_", "GITHUB_", "AWS_", "SONAR_"))}
        env.update(GOWORK="off", GOFLAGS="", GOENV="off", GOTOOLCHAIN="local", GOPROXY="off",
                   GOCACHE=str(REPO / "build/go-rendezvous-cache"))
        return env

    def test_explicit_source_worker_only_and_no_source_replacement(self):
        self.assertEqual(gate.statement({}), "")
        self.assertEqual(gate.imports({}), "")
        entry = {"go_backend": "source-v1", "go_context": self.context()}
        self.assertEqual(gate.statement(entry), "__oteleq_gate.AwaitHost();")
        self.assertIn('"example.test/oteleqgate/oteleq_generated_control"', gate.imports(entry))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for invalid in ("../outside", "/outside", "a/../b", "a\\b", "a:b", ""):
                with self.assertRaises(ValueError):
                    gate.materialise(root, {**self.context(), "module_root": invalid})
            path = gate.materialise(root, self.context())
            self.assertEqual(path.relative_to(root).as_posix(), "oteleq_generated_control/rendezvous.go")
            before = path.read_bytes()
            with self.assertRaises(FileExistsError): gate.materialise(root, self.context())
            self.assertEqual(path.read_bytes(), before)

    def test_compiled_private_gate_never_calls_shadowed_application_builtins(self):
        go = shutil.which(os.environ.get("OTELC_GO", "go"))
        self.assertIsNotNone(go)
        declarations = (
            'func len(text string) int { Calls++; count:=0; for range []byte(text){count++}; return count }',
            'var nil=7; var true=8; var false=9; type string struct{}; type byte struct{}; '
            'type uint32 struct{}; type int64 struct{}; func make(){Calls++}',
        )
        for declaration in declarations:
            with self.subTest(declaration=declaration), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                context = self.context()
                gate.materialise(root, context)
                (root / "go.mod").write_text("module example.test/oteleqgate\n\ngo 1.26.0\n")
                source = ('package main\nimport "fmt"\n'
                          + gate.imports({"go_backend": "source-v1", "go_context": context})
                          + '\nvar Calls=0\n' + declaration
                          + '\nfunc main(){__oteleq_gate.AwaitHost();fmt.Println(Calls)}\n')
                (root / "main.go").write_text(source)
                env = self.environment()
                result = subprocess.run([go, "build", "-o", "worker", "."], cwd=root, env=env,
                                        capture_output=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                control = root / "control"
                control.mkdir(mode=0o700)
                token = "a" * 32
                env.update({gate.ROOT_ENV: str(control), gate.TOKEN_ENV: token, gate.WAIT_ENV: "5000"})
                process = subprocess.Popen([str(root / "worker")], cwd=root, env=env,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 5
                    while not (control / "start.ready").exists():
                        self.assertIsNone(process.poll(), "gate exited before readiness")
                        self.assertLess(time.monotonic(), deadline, "gate did not publish readiness")
                        time.sleep(.005)
                    resume = control / "start.resume.tmp"
                    resume.write_text(token + " release\n")
                    resume.chmod(0o600)
                    os.link(resume, control / "start.resume")
                    output, errors = process.communicate(timeout=10)
                    self.assertEqual(process.returncode, 0, errors.decode(errors="replace"))
                    self.assertEqual(output, b"0\n", "gate invoked application code")
                    self.assertEqual(errors, b"")
                    self.assertEqual((root / "main.go").read_text(), source)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.communicate()

    def test_native_gate_race_checks_and_compiled_statement_floor(self):
        go = shutil.which(os.environ.get("OTELC_GO", "go"))
        self.assertIsNotNone(go, "Go rendezvous regression needs the selected native Go tool")
        with tempfile.TemporaryDirectory(prefix="oteleq-go-gate-") as temporary:
            root = Path(temporary).resolve()
            helper = gate.materialise(root, self.context())
            (root / "go.mod").write_text("module example.test/oteleqgate\n\ngo 1.26.0\n")
            shutil.copyfile(REPO / "tests/fixtures/go-rendezvous_test.go", helper.with_name("rendezvous_test.go"))
            env = self.environment()
            result = subprocess.run([go, "test", "-race", "-coverprofile=coverage.out", "./..."], cwd=root,
                                    env=env, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode(errors="replace"))
            summary = subprocess.run([go, "tool", "cover", "-func=coverage.out"], cwd=root, env=env,
                                     capture_output=True, timeout=30)
            self.assertEqual(summary.returncode, 0, summary.stderr.decode(errors="replace"))
            output = summary.stdout.decode()
            self.assertIn("AwaitHost", output)
            total = re.search(r"total:\s+\(statements\)\s+([0-9.]+)%", output)
            self.assertIsNotNone(total, output)
            self.assertGreaterEqual(float(total[1]), 80., output)


if __name__ == "__main__":
    unittest.main()
