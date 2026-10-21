"""Maintainer recipes use the consumer executable that Cargo actually built."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class QualificationRecipeTests(unittest.TestCase):
    def test_all_qualification_recipes_honour_default_relative_and_spaced_target_directories(self):
        targets = {}
        target = None
        for line in (ROOT / "Makefile").read_text().splitlines():
            if line and not line[0].isspace() and line.endswith(":"):
                target = line[:-1]
            for flag in ("--cli", "--comparator"):
                if line.startswith("\t") and flag + " " in line:
                    targets[target] = flag
        self.assertEqual(len(targets), 24)
        self.assertIn("generation-native-project-otelc", targets)
        self.assertIn("generation-http-otelc", targets)
        self.assertIn("generation-java-receiver-otelc", targets)
        self.assertIn("generation-java-sequence-otelc", targets)
        self.assertIn("generation-java-controls-otelc", targets)
        self.assertIn("generation-go-receiver-otelc", targets)
        self.assertIn("rust-semantic-otelc", targets)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            cargo = base / "cargo"
            cargo.write_text("#!/bin/sh\nexit 0\n")
            cargo.chmod(0o700)
            python = base / "record-python"
            python.write_text(f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
                              "Path(os.environ['OTELEQ_RECIPE_RECORD']).write_text(json.dumps(sys.argv[1:]))\n")
            python.chmod(0o700)
            record = base / "arguments.json"
            for directory in (None, "relative target", str(base / "external target")):
                environment = {**os.environ, "PATH": str(base) + os.pathsep + os.environ["PATH"],
                               "OTELEQ_RECIPE_RECORD": str(record)}
                environment.pop("CARGO_TARGET_DIR", None)
                if directory is not None:
                    environment["CARGO_TARGET_DIR"] = directory
                expected = str(Path(directory or ROOT / "target") / "debug/quux-oteleq")
                for name, flag in targets.items():
                    with self.subTest(target=name, directory=directory):
                        result = subprocess.run(["make", "--no-print-directory", "-s", name,
                            "OTELC_ROOT=" + str(base / "provider"), "REPORT_DIR=" + str(base / "evidence"),
                            "UNSUPPORTED_OTELC_ROOT=" + str(base / "old-provider"), "PYTHON=" + str(python),
                            "GENERATION_ARGS=", "CAPTURE_ARGS="], cwd=ROOT, env=environment,
                            capture_output=True, text=True, check=False)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        arguments = json.loads(record.read_text())
                        self.assertEqual(arguments[arguments.index(flag) + 1], expected)

    def test_help_names_the_http_qualification_target(self):
        result = subprocess.run(["make", "help"], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn("generation-http-otelc Qualify scripted HTTP", result.stdout)
        self.assertIn("generation-native-project-otelc Qualify explicit C/C++ targets", result.stdout)


if __name__ == "__main__":
    unittest.main()
