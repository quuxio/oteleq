"""Compiler-profile registry gaps cannot pass an otherwise drained capture."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters/generation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import generation


class RustGeneratedHealthTests(unittest.TestCase):
    def test_original_source_profile_requires_complete_registry_before_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "observation").write_bytes(b"observed state")
            data = {"configuration": {"limits": {"max_capture_bytes": 65536}}, "source_sha256": "a" * 64,
                    "artefacts": {"rust": {generation.capture.RUST_COMPILER_PROFILE_FILENAME: "b" * 64}}}
            result = subprocess.CompletedProcess([], 0, b"", b"")
            for runtime in ({}, {"future_observers": {"pending": 1, "admission_exhausted": False}},
                            {"future_observers": {"pending": 0, "admission_exhausted": True}}):
                (folder / "runtime.json").write_text(json.dumps(runtime))
                with patch.object(generation, "telemetry") as telemetry, self.assertRaises(ValueError):
                    generation.qualify_attempt(data, {"language": "rust"}, "instrumented_on", folder,
                                               result, [], [], "fixture", None)
                telemetry.assert_not_called()

    def test_complete_registry_and_legacy_profile_use_the_expected_telemetry_route(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "observation").write_bytes(b"observed state")
            data = {"configuration": {"limits": {"max_capture_bytes": 65536}}, "source_sha256": "a" * 64,
                    "artefacts": {"rust": {generation.capture.RUST_COMPILER_PROFILE_FILENAME: "b" * 64}}}
            result = subprocess.CompletedProcess([], 0, b"", b"")
            runtime = {"future_observers": {"pending": 0, "admission_exhausted": False}}
            for profile in (True, False):
                if not profile:
                    data["artefacts"]["rust"] = {}
                    runtime = {}
                (folder / "runtime.json").write_text(json.dumps(runtime))
                with patch.object(generation, "telemetry", return_value={"qualified": True}) as telemetry:
                    actual = generation.qualify_attempt(data, {"language": "rust"}, "instrumented_on", folder,
                                                        result, [], [], "fixture", None)
                telemetry.assert_called_once()
                self.assertEqual(actual["witness"], {"qualified": True})


if __name__ == "__main__":
    unittest.main()
