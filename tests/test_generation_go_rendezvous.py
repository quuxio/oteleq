"""The actual compiled Go gate, including refusals, has its own coverage floor."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_rendezvous as gate


class GoRendezvousTests(unittest.TestCase):
    def test_explicit_source_worker_only_and_no_source_replacement(self):
        self.assertEqual(gate.statement({}), "")
        self.assertEqual(gate.statement({"go_backend": "source-v1"}), "__oteleqAwaitGoHost();")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for invalid in ("main;panic()", "_", None):
                with self.assertRaises(ValueError): gate.materialise(root, invalid)
            path = gate.materialise(root, "main")
            before = path.read_bytes()
            with self.assertRaises(FileExistsError): gate.materialise(root, "main")
            self.assertEqual(path.read_bytes(), before)

    def test_native_gate_race_checks_and_compiled_statement_floor(self):
        go = shutil.which(os.environ.get("OTELC_GO", "go"))
        self.assertIsNotNone(go, "Go rendezvous regression needs the selected native Go tool")
        with tempfile.TemporaryDirectory(prefix="oteleq-go-gate-") as temporary:
            root = Path(temporary).resolve()
            gate.materialise(root, "main")
            (root / "go.mod").write_text("module example.test/oteleqgate\n\ngo 1.26.0\n")
            shutil.copyfile(REPO / "tests/fixtures/go-rendezvous-test.go", root / "rendezvous_test.go")
            env = {key: value for key, value in os.environ.items() if not key.startswith(("OTEL", "GH_", "GITHUB_", "AWS_", "SONAR_"))}
            env.update(GOWORK="off", GOFLAGS="", GOENV="off", GOTOOLCHAIN="local", GOPROXY="off",
                       GOCACHE=str(REPO / "build/go-rendezvous-cache"))
            result = subprocess.run([go, "test", "-race", "-coverprofile=coverage.out", "./..."], cwd=root,
                                    env=env, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode(errors="replace"))
            summary = subprocess.run([go, "tool", "cover", "-func=coverage.out"], cwd=root, env=env,
                                     capture_output=True, timeout=30)
            self.assertEqual(summary.returncode, 0, summary.stderr.decode(errors="replace"))
            output = summary.stdout.decode()
            self.assertIn("__oteleqAwaitGoHost", output)
            total = re.search(r"total:\s+\(statements\)\s+([0-9.]+)%", output)
            self.assertIsNotNone(total, output)
            self.assertGreaterEqual(float(total[1]), 80., output)


if __name__ == "__main__":
    unittest.main()
