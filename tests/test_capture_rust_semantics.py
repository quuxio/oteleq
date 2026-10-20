"""Independent literal oracles for the Rust producer's semantic qualification."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


FIXTURES = Path(__file__).with_name("fixtures")


def semantic_oracle(source: str) -> dict[str, int]:
    """Source coordinates and fixed pinned-profile observations are independent."""
    lines = source.splitlines()
    column = next(line.index("column!()") + 1 for line in lines if "column!()" in line)
    caller_line, caller_column = next(
        (index, line.index("selected_caller();") + 1)
        for index, line in enumerate(lines, 1) if "let caller = selected_caller();" in line)
    return {"column": column, "caller": (caller_line << 32) | caller_column,
            "closure_layout": (16 << 32) | 8, "future_layout": (40 << 32) | 8,
            "never_polled_drops": 1, "result": 42, "pending_drops": 0,
            "ready_drops": 1, "completed_drops": 1, "cancel_pending_drops": 0,
            "cancelled_drops": 1, "panic_payload": 17, "panic_pending_drops": 0,
            "unwind_drops": 1, "panic_dropped": 1}


def alias_fixture(destination: Path) -> tuple[Path, dict[str, int]]:
    """Two logical module paths share one unchanged read-only physical source."""
    source = destination / "main.rs"
    shutil.copyfile(FIXTURES / "rust_compiler_aliases.rs", source)
    shared = destination / "shared.rs"
    shutil.copyfile(FIXTURES / "rust_compiler_shared.rs", shared)
    for name in ("first", "second"):
        folder = destination / name
        folder.mkdir()
        (folder / "shared.rs").symlink_to("../shared.rs")
    shared.chmod(0o444)
    column = next(line.index("column!()") + 1 for line in shared.read_text().splitlines() if "column!()" in line)
    return source, {"first": column, "second": column}


class RustSemanticFixtureTests(unittest.TestCase):
    def compile_and_run(self, source: Path) -> dict:
        compiler = os.environ.get("OTELC_RUSTC", "rustc")
        binary = source.parent / "plain"
        result = subprocess.run([compiler, "--edition=2024", "-O", "-g", str(source), "-o", str(binary)],
                                capture_output=True, timeout=120, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        result = subprocess.run([str(binary)], capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stderr, b"")
        return json.loads(result.stdout)

    def test_plain_locations_layout_send_completion_drop_cancellation_and_panic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "semantics.rs"
            shutil.copyfile(FIXTURES / "rust_compiler_semantics.rs", source)
            text = source.read_text()
            self.assertEqual(self.compile_and_run(source), semantic_oracle(text))
            self.assertEqual(source.read_text(), text)

    def test_plain_linked_modules_preserve_both_aliases_and_the_read_only_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            source, expected = alias_fixture(destination)
            shared = destination / "shared.rs"
            before = hashlib.sha256(shared.read_bytes()).hexdigest()
            self.assertEqual(self.compile_and_run(source), expected)
            self.assertEqual(hashlib.sha256(shared.read_bytes()).hexdigest(), before)
            self.assertEqual(shared.stat().st_mode & 0o777, 0o444)
            for name in ("first", "second"):
                self.assertEqual(os.readlink(destination / name / "shared.rs"), "../shared.rs")


if __name__ == "__main__":
    unittest.main()
