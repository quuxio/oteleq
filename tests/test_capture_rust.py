"""Qualified standalone Rust build/run boundary, provenance and channel tests."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import otelc_capture as capture


class RustBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "otelc"
        (self.root / "target/debug").mkdir(parents=True)
        for name in ("libquux_otelc_rust.rlib", "otelc-rust-adapter"):
            (self.root / "target/debug" / name).write_bytes(name.encode())
        self.project = self.base / "project with spaces"
        self.project.mkdir()
        self.source = self.project / "source.rs"
        self.source.write_text("fn unused(){}\nfn main(){}\n")
        self.evidence = self.base / "evidence"
        self.evidence.mkdir()
        self.output = self.base / "output"
        self.output.mkdir()
        self.tools = {"rustc": Path("/selected compiler/bin/rustc")}
        self.bundle = self.output / "rust-bundle"

    def create_bundle(self):
        self.bundle.mkdir()
        (self.bundle / "application").write_bytes(b"instrumented executable")
        (self.bundle / "plan.json").write_text('{"resolved":"policy"}')
        self.metadata = {
            "schema_version": 1, "language": "rust",
            "baseline_flags": list(capture.RUST_BASELINE_FLAGS),
            "source": str(self.source.resolve()), "source_root": str(self.project.resolve()),
            "source_sha256": capture.file_digest(self.source),
            "executable_sha256": capture.file_digest(self.bundle / "application"),
            "plan_sha256": capture.file_digest(self.bundle / "plan.json"),
            "sdk_sha256": capture.file_digest(self.root / "target/debug/libquux_otelc_rust.rlib"),
            "adapter_sha256": capture.file_digest(self.root / "target/debug/otelc-rust-adapter"),
            "compiler": {"program": str(self.tools["rustc"]), "argv": ["generated.rs", *capture.RUST_BASELINE_FLAGS], "version": "qualified rustc"},
        }
        self.write_metadata(self.metadata)

    def write_metadata(self, metadata):
        (self.bundle / "build.json").write_text(json.dumps(metadata))

    def test_matched_flags_and_build_warnings_stay_out_of_launch_commands(self):
        def build(command, cwd, env, log):
            log.write_bytes(b"warning: unused function; retained compiler bytes\n")
            if "--build" in command:
                self.create_bundle()
            else:
                (self.output / "plain").write_bytes(b"plain executable")
        commands = []
        with patch.object(capture, "build", side_effect=build) as builder:
            for lane in ("baseline", "instrumented_on"):
                commands.append(capture.rust_command(self.root, self.project, self.source, self.base / "policy.toml", self.tools, {}, self.evidence, self.output, lane))
        self.assertEqual(commands[0], [self.output / "plain"])
        self.assertEqual(commands[1][-3:], ["rust", "--run", self.bundle])
        self.assertNotIn(self.tools["rustc"], commands[1])
        self.assertEqual(builder.call_count, 2)
        self.assertIn(Path("source.rs"), builder.call_args_list[0].args[0])
        self.assertIn(Path("source.rs"), builder.call_args_list[1].args[0])
        for flag in capture.RUST_BASELINE_FLAGS:
            self.assertIn(flag, builder.call_args_list[0].args[0])
        for name in ("plain-build.log", "instrumented-build.log"):
            self.assertIn(b"warning:", (self.evidence / name).read_bytes())
        on = json.loads((self.evidence / "instrumented_on-build-identities.json").read_text())
        self.assertEqual(on["baseline_flags"], list(capture.RUST_BASELINE_FLAGS))
        self.assertEqual(on["manifest_sha256"], capture.file_digest(self.bundle / "build.json"))
        self.assertEqual(self.source.read_text(), "fn unused(){}\nfn main(){}\n")

    def test_malformed_changed_or_unqualified_build_metadata_is_refused(self):
        self.create_bundle()
        candidates = [[], {**self.metadata, "schema_version": True}, {**self.metadata, "baseline_flags": ["-O0"]},
                      {**self.metadata, "compiler": []}, {**self.metadata, "compiler": {"program": "untrusted"}},
                      {**self.metadata, "source": "/untrusted/source.rs"}, {**self.metadata, "source_root": "/untrusted/root"}]
        for key in ("source_sha256", "executable_sha256", "plan_sha256", "sdk_sha256", "adapter_sha256"):
            candidates.append({**self.metadata, key: "0" * 64})
        for metadata in candidates:
            self.write_metadata(metadata)
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                capture.rust_manifest(self.root, self.project, self.source, self.bundle, self.tools)
        self.write_metadata(self.metadata)
        binary = self.bundle / "application"
        binary.unlink()
        binary.symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, "regular"):
            capture.rust_manifest(self.root, self.project, self.source, self.bundle, self.tools)
        binary.unlink()
        binary.write_bytes(b"instrumented executable")
        (self.bundle / "build.json").write_bytes(b" " * (4 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "size limit"):
            capture.rust_manifest(self.root, self.project, self.source, self.bundle, self.tools)

    def test_fixed_capture_uses_the_same_two_separate_build_recipes(self):
        with patch.object(capture, "rust_command", side_effect=(["plain"], ["on"])) as recipe:
            result = capture.commands(self.root, self.project, "rust", self.source, self.base / "policy", self.tools, {}, self.evidence)
        self.assertEqual(result, (["plain"], ["on"]))
        self.assertEqual([call.args[-1] for call in recipe.call_args_list], ["baseline", "instrumented_on"])
