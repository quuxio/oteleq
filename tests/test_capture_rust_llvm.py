"""LLVM manifests must prove the caller's fixed build and original selection."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import otelc_capture as capture


class RustLlvmTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "provider"
        self.project = self.base / "project with spaces"
        self.scratch = self.base / "scratch"
        self.bundle = self.base / "rust-bundle"
        for path in (self.root / "target/debug", self.project, self.scratch, self.bundle):
            path.mkdir(parents=True)
        self.sdk = self.root / "target/rust-llvm-sdk/debug/libquux_otelc_rust.rlib"
        self.dependencies = self.sdk.parent / "deps"
        self.dependencies.mkdir(parents=True)
        self.sdk.write_bytes(b"qualified SDK")
        suffix = {"darwin": ".dylib", "linux": ".so", "win32": ".dll"}[sys.platform]
        self.plugin = self.root / ("target/debug/otelc_rust_pass" + suffix)
        self.plugin.write_bytes(b"qualified compiler plugin")
        self.tools = {"rustc": self.base / "tool/bin/rustc"}
        self.tools["rustc"].parent.mkdir(parents=True)
        self.tools["rustc"].write_bytes(b"selected rustc")
        for path in (self.root / "target/debug/quux-otelc", self.root / "target/debug/otelc-rust-adapter", self.root / "Cargo.lock"):
            path.write_bytes(path.name.encode())
        (self.dependencies / "dependency.rlib").write_bytes(b"dependency")
        self.source = self.project / "app.rs"
        self.source.write_text("fn selected(value:u128)->u128{value}\nfn main(){}\n")
        self.environment = {"TMPDIR": str(self.scratch)}
        self.profile = {"schema_version": 1, "rustc": str(self.tools["rustc"]), "sdk": str(self.sdk),
                        "sdk_sha256": capture.file_digest(self.sdk), "plugin": str(self.plugin),
                        "plugin_sha256": capture.file_digest(self.plugin), "llvm_version": "qualified LLVM",
                        "protected_source_roots": [str(self.root / "crates/sdk")]}
        self.profile_path = self.root / "target/debug/otelc-rust-llvm.json"
        self.write(self.profile_path, self.profile)
        self.plan = {"schema_version": 2, "language": "rust", "backend": "llvm", "execution_available": True,
                     "unavailable": [], "sources": {"include": ["app.rs"], "exclude": []},
                     "functions": {"include": ["app.selected"], "exclude": []}}
        self.declarations = []
        for index, line in enumerate(self.source.read_text().splitlines(), 1):
            selected = index == 1
            self.declarations.append({"file": str(self.source), "name": "app.selected" if selected else "app.main",
                                      "selected": selected, "startup": not selected, "unsupported": "",
                                      "body_start_line": index, "body_end_line": index,
                                      "body_start_column": line.index("{") + 1, "body_end_column": len(line)})
        temporary = self.scratch / ".tmp-build"
        self.inventory = {"schema_version": 2, "functions": self.declarations,
                          "sources": {str(self.source): capture.file_digest(self.source)},
                          "discovery_argv": ["app.rs", *capture.RUST_LLVM_BASELINE_FLAGS,
                                             "--emit=dep-info=" + str(temporary / "original.d")]}
        self.resolved = {"schema_version": 1, "phase": "llvm-pipeline-start", "module": "app.module",
                         "functions": [{**row, "kind": "function", "compiled_symbol": "symbol-" + str(index),
                                        "source_sha256": capture.file_digest(self.source)} for index, row in enumerate(self.declarations)]}
        self.write_records()
        (self.bundle / "application").write_bytes(b"built executable")
        self.version = "rustc qualified\nhost: test\nLLVM version: qualified"
        argv = ["app.rs", *capture.RUST_LLVM_BASELINE_FLAGS, "-o", str(temporary / "application"),
                "-Zllvm-plugins=" + str(self.plugin), "-Zunstable-options", "--extern",
                "noprelude,force,nounused:quux_otelc_rust=" + str(self.sdk), "-L", "dependency=" + str(self.dependencies)]
        self.metadata = {"schema_version": 2, "language": "rust", "backend": "llvm",
                         "executable_sha256": capture.file_digest(self.bundle / "application"),
                         "source_sha256": capture.file_digest(self.source), "source": str(self.source),
                         "source_root": str(self.project), "adapter_sha256": capture.file_digest(self.root / "target/debug/otelc-rust-adapter"),
                         "sdk_sha256": capture.file_digest(self.sdk), "baseline_flags": list(capture.RUST_LLVM_BASELINE_FLAGS),
                         "compiler": {"program": str(self.tools["rustc"]), "argv": argv, "version": self.version}}
        self.seal_records()

    def write(self, path, document):
        path.write_text(json.dumps(document))

    def write_records(self):
        for name, document in (("plan.json", self.plan), ("inventory.json", self.inventory), ("resolved.json", self.resolved)):
            self.write(self.bundle / name, document)

    def seal_records(self):
        self.write_records()
        self.metadata["plan_sha256"] = capture.file_digest(self.bundle / "plan.json")
        self.metadata["compiler_hook"] = {"profile_sha256": capture.file_digest(self.profile_path),
                                         "plugin_sha256": capture.file_digest(self.plugin),
                                         "inventory_sha256": capture.file_digest(self.bundle / "inventory.json"),
                                         "resolved_sha256": capture.file_digest(self.bundle / "resolved.json")}
        self.write(self.bundle / "build.json", self.metadata)

    def verify(self):
        result = subprocess.CompletedProcess([], 0, (self.version + "\n").encode(), b"")
        with patch.object(capture, "execute", return_value=result):
            return capture.rust_manifest(self.root, self.project, self.source, self.bundle, self.tools,
                                         backend="llvm", expected_function="app.selected", environment=self.environment)

    def test_exact_profile_recipe_selection_and_compiled_symbol_qualify(self):
        result = self.verify()
        self.assertEqual(result["backend"], "llvm")
        self.assertEqual(result["selected_function"], "app.selected")
        self.assertEqual(result["selected_symbol"], "symbol-0")
        self.assertEqual(result["baseline_flags"], list(capture.RUST_LLVM_BASELINE_FLAGS))
        with self.assertRaises(ValueError):
            capture.rust_metadata(self.bundle)
        self.assertEqual(capture.rust_flags("compiler"), capture.RUST_BASELINE_FLAGS)
        with self.assertRaises(ValueError):
            capture.rust_flags("automatic")

    def test_both_lanes_use_the_selected_llvm_flags_and_no_build_launch(self):
        evidence = self.base / "evidence"
        evidence.mkdir()
        policy = self.base / "policy.toml"
        policy.write_text('[adapters.rust]\nbackend="llvm"\n')
        def build(command, workspace, environment, log):
            log.write_bytes(b"retained build warning")
            if "--build" not in command:
                (self.base / "plain").write_bytes(b"plain executable")
        version = subprocess.CompletedProcess([], 0, self.version.encode(), b"")
        with patch.object(capture, "build", side_effect=build) as builder, patch.object(capture, "execute", return_value=version):
            commands = [capture.rust_command(self.root, self.project, self.source, policy, self.tools,
                                            self.environment, evidence, self.base, lane,
                                            backend="llvm", expected_function="app.selected")
                        for lane in ("baseline", "instrumented_on")]
        self.assertEqual(commands, [[self.base / "plain"], [self.root / capture.OTELC_CLI_PATH,
                         "--config", policy, "--language", "rust", "rust", "--run", self.bundle]])
        self.assertEqual(builder.call_args_list[0].args[0][1:-2], [*capture.RUST_LLVM_BASELINE_FLAGS, Path("app.rs")])
        self.assertNotIn("--build", commands[1])

    def test_profile_schema_assets_compiler_and_metadata_are_checked(self):
        original = copy.deepcopy(self.profile)
        mutations = [("schema_version", True), ("rustc", "/untrusted/compiler"), ("sdk", "/untrusted/sdk"),
                     ("plugin", "/untrusted/plugin"), ("sdk_sha256", "0" * 64), ("plugin_sha256", "0" * 64),
                     ("protected_source_roots", []), ("protected_source_roots", ["relative"]),
                     ("llvm_version", ""), ("unknown", True)]
        for key, value in mutations:
            self.profile = {**original, key: value}
            self.write(self.profile_path, self.profile)
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.verify()
        self.write(self.profile_path, original)
        for path in (self.sdk, self.plugin):
            saved = path.read_bytes()
            path.write_bytes(b"changed")
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.verify()
            path.write_bytes(saved)

    def test_dependency_additions_changes_and_links_cannot_escape_the_frozen_inputs(self):
        expected = capture.artefacts(self.root, "rust", self.tools, rust_backend="llvm")
        extra = self.dependencies / "extra.rmeta"
        extra.write_bytes(b"new metadata")
        with self.assertRaises(ValueError):
            capture.stable(self.root, "rust", self.tools, expected, rust_backend="llvm")
        extra.unlink()
        dependency = self.dependencies / "dependency.rlib"
        dependency.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            capture.stable(self.root, "rust", self.tools, expected, rust_backend="llvm")
        dependency.unlink()
        dependency.symlink_to(self.sdk)
        with self.assertRaises(ValueError):
            capture.rust_llvm_inputs(self.root, self.tools)
        dependency.unlink()
        self.dependencies.rmdir()
        with self.assertRaises(ValueError):
            capture.rust_llvm_inputs(self.root, self.tools)

    def test_manifest_hashes_schema_and_unknown_fields_cannot_qualify(self):
        original = copy.deepcopy(self.metadata)
        mutations = [("schema_version", 1), ("backend", "compiler"), ("unknown", 1),
                     ("baseline_flags", list(capture.RUST_BASELINE_FLAGS)), ("compiler_hook", {})]
        for key in ("executable_sha256", "plan_sha256", "source_sha256", "sdk_sha256", "adapter_sha256"):
            mutations.append((key, "0" * 64))
        for key, value in mutations:
            self.metadata = {**original, key: value}
            self.write(self.bundle / "build.json", self.metadata)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()

    def test_compiler_arguments_version_and_context_cannot_be_selected_by_metadata(self):
        original = copy.deepcopy(self.metadata["compiler"])
        mutations = [{**original, "program": "/untrusted/compiler"}, {**original, "version": "different"},
                     {**original, "unknown": 1}, {**original, "argv": original["argv"] + ["-Cpanic=abort"]},
                     {**original, "argv": ["different.rs", *original["argv"][1:]]}]
        escaped = copy.deepcopy(original)
        escaped["argv"][len(capture.RUST_LLVM_BASELINE_FLAGS) + 2] = "/outside/application"
        mutations.append(escaped)
        for compiler in mutations:
            self.metadata["compiler"] = compiler
            self.write(self.bundle / "build.json", self.metadata)
            with self.subTest(compiler=compiler), self.assertRaises(ValueError):
                self.verify()
        self.metadata["compiler"] = original
        self.write(self.bundle / "build.json", self.metadata)
        self.environment = {}
        with self.assertRaises(ValueError):
            self.verify()

    def test_resolved_semantics_are_checked_even_with_updated_record_hashes(self):
        original = copy.deepcopy(self.resolved)
        for key, value in (("phase", "after-optimisation"), ("module", ""), ("schema_version", True), ("unknown", 1)):
            self.resolved = {**original, key: value}
            self.seal_records()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()
        for key, value in (("compiled_symbol", ""), ("kind", "closure"), ("source_sha256", "0" * 64),
                           ("name", "app.unrelated"), ("file", "/unrelated/app.rs"),
                           ("body_start_column", 0), ("body_start_line", True), ("selected", False), ("startup", True)):
            self.resolved = copy.deepcopy(original)
            self.resolved["functions"][0][key] = value
            self.seal_records()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()
        self.resolved = copy.deepcopy(original)
        self.resolved["functions"].append(copy.deepcopy(self.resolved["functions"][0]))
        self.seal_records()
        with self.assertRaises(ValueError):
            self.verify()

    def test_inventory_source_set_coordinates_and_discovery_recipe_are_checked(self):
        original = copy.deepcopy(self.inventory)
        original_resolved = copy.deepcopy(self.resolved)
        for key, value in (("sources", {}), ("discovery_argv", []), ("functions", [None]), ("schema_version", 1)):
            self.inventory = {**original, key: value}
            self.seal_records()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()
        for key, value in (("body_end_line", 99), ("body_end_column", 999), ("body_start_line", 3),
                           ("body_start_column", len(self.source.read_text().splitlines()[0]) + 1),
                           ("unsupported", "needs fixture"), ("selected", 1)):
            self.inventory = copy.deepcopy(original)
            self.resolved = copy.deepcopy(original_resolved)
            self.inventory["functions"][0][key] = value
            self.resolved["functions"][0][key] = value
            self.seal_records()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()

    def test_changed_selection_plan_and_record_files_cannot_qualify(self):
        original = copy.deepcopy(self.plan)
        for key, value in (("backend", "compiler"), ("functions", {"include": ["app.other"], "exclude": []}),
                           ("sources", {"include": ["other.rs"], "exclude": []}), ("execution_available", False),
                           ("unavailable", ["unsupported"]), ("language", "go")):
            self.plan = {**original, key: value}
            self.seal_records()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()
        self.plan = original
        self.seal_records()
        for name in ("inventory.json", "resolved.json"):
            path = self.bundle / name
            saved = path.read_bytes()
            path.write_text("{}")
            with self.subTest(file=name), self.assertRaises(ValueError):
                self.verify()
            path.write_bytes(saved)
        self.metadata["compiler_hook"]["plugin_sha256"] = "0" * 64
        self.write(self.bundle / "build.json", self.metadata)
        with self.assertRaises(ValueError):
            self.verify()

    def test_nonregular_oversized_and_nondictionary_evidence_is_refused(self):
        path = self.bundle / "resolved.json"
        for raw in (b"[]", b" " * (4 * 1024 * 1024 + 1)):
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                capture.rust_document(path)
        path.unlink()
        path.symlink_to(self.source)
        with self.assertRaises(ValueError):
            capture.rust_document(path)
