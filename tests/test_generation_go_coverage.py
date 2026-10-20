"""The Go observer gate must measure only the compiled product statements."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
import go_coverage


class GoCoverageTests(unittest.TestCase):
    def test_product_floor_and_missing_or_foreign_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "coverage.out"
            prefix = "mode: count\n" + go_coverage.PRODUCT
            path.write_text(prefix + ":1.1,2.1 8 1\n" + go_coverage.PRODUCT + ":3.1,4.1 2 0\n")
            self.assertEqual(go_coverage.coverage(path), 80)
            for text in ("", "mode: set\n", "mode: count\n", prefix + ":1.1,2.1 1 0\n",
                         "mode: count\nother.go:1.1,2.1 100 1\n", prefix + ":1.1,2.1 -1 1\n",
                         prefix + ":1.1,2.1 1 1\n" + go_coverage.PRODUCT + ":1.1,2.1 1 1\n"):
                with self.subTest(text=text), self.assertRaises(ValueError):
                    path.write_text(text)
                    go_coverage.coverage(path)

    def test_gate_copies_real_sources_and_runs_test_and_vet(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            for name in ("adapters/generation/go_observe.go", "tests/go_observer_test.go"):
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("package oteleqobserver\n")

            def run(command, **kwargs):
                folder = kwargs["cwd"]
                self.assertEqual((folder / "observer.go").read_text(), "package oteleqobserver\n")
                self.assertTrue((folder / "observer_test.go").is_file())
                self.assertEqual(kwargs["env"]["GOWORK"], "off")
                if "-coverprofile" in command:
                    Path(command[command.index("-coverprofile") + 1]).write_text(
                        "mode: count\n" + go_coverage.PRODUCT + ":1.1,2.1 10 1\n")

            with patch.object(go_coverage.subprocess, "run", side_effect=run) as executed:
                go_coverage.check(repo)
            self.assertEqual(executed.call_count, 2)
            self.assertEqual(executed.call_args.args[0][1:], ["vet", "."])
