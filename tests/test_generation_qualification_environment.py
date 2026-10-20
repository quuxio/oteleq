"""Qualification cannot run commands with its independent assertions disabled."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class QualificationEnvironmentTests(unittest.TestCase):
    def test_explicit_and_environment_optimisation_refuse_before_the_first_command(self):
        for protocol in ("filesystem", "http"):
            for explicit in (False, True):
                with self.subTest(protocol=protocol, explicit=explicit), tempfile.TemporaryDirectory() as temporary:
                    base = Path(temporary)
                    marker = base / "launched"
                    cli = base / "cli"
                    cli.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n")
                    cli.chmod(0o700)
                    provider = base / "provider"; provider.mkdir()
                    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
                    environment.pop("PYTHONOPTIMIZE", None)
                    if not explicit:
                        environment["PYTHONOPTIMIZE"] = "1"
                    arguments = [sys.executable, *(["-O"] if explicit else []),
                        ROOT / f"tests/qualify_{protocol}.py", "--cli", cli,
                        "--otelc-root", provider, "--report-dir", base / "evidence"]
                    result = subprocess.run(arguments, env=environment, capture_output=True, text=True, check=False)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("requires Python assertion checks", result.stderr)
                    self.assertFalse(marker.exists())
