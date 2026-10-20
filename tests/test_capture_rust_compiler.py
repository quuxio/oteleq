"""Original-source compiler records must bind the actual caller and provider."""
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
import otelc_rust_build as compiler_build


class RustCompilerBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "provider"
        self.workspace = self.base / "project with spaces"
        self.scratch = self.base / "scratch"
        self.bundle = self.base / "bundle"
        for path in (self.root / "target/debug/deps", self.workspace,
                     self.scratch, self.bundle, self.base / "tool/bin"):
            path.mkdir(parents=True)
        self.tools = {"rustc": self.base / "tool/bin/rustc"}
        self.assets = {"rustc": self.tools["rustc"],
                       "sdk": self.root / "target/debug/libquux_otelc_rust.rlib",
                       "driver": self.root / "target/debug/otelc-rust-mir"}
        for path in (*self.assets.values(), self.root / "target/debug/quux-otelc",
                     self.root / "target/debug/otelc-rust-adapter", self.root / "Cargo.lock",
                     self.root / "target/debug/deps/dependency.rmeta"):
            path.write_bytes(path.name.encode())
        self.source = self.workspace / "app.rs"
        self.source.write_text("fn selected(value:i32)->i32{value}\nfn main(){}\n")
        self.version = ("rustc 1.98.1 (48a229cea 2026-09-17)\ncommit-hash: "
                        + compiler_build.COMPILER_COMMIT
                        + "\nhost: aarch64-apple-darwin\nLLVM version: 22.1.8")
        self.profile = {"schema_version": 1, "backend": "compiler",
                        "commit_hash": compiler_build.COMPILER_COMMIT,
                        "protected_source_roots": [str(self.root / "crates" / name)
                                                   for name in ("config", "export", "rust-probes")]}
        for key, path in self.assets.items():
            self.profile[key] = str(path)
            self.profile[key + "_sha256"] = capture.file_digest(path)
        self.plan = {"schema_version": 2, "language": "rust", "backend": "compiler",
                     "execution_available": True, "unavailable": [],
                     "sources": {"include": ["**"], "exclude": []},
                     "functions": {"include": ["app.selected"], "exclude": []},
                     **{key: {} for key in compiler_build.POLICY_FIELDS
                        - {"language", "backend", "execution_available", "sources", "functions"}}}
        self.declarations = []
        offset = 0
        for index, line in enumerate(self.source.read_text().splitlines(), 1):
            name = "selected" if index == 1 else "main"
            self.declarations.append({"file": str(self.source), "name": "app." + name,
                                      "suffix": name, "leaf": name, "unsupported": "",
                                      "selected": index == 1, "startup": index == 2,
                                      "header_start": offset, "header_end": offset + line.index("{"),
                                      "body_start_line": index, "body_start_column": line.index("{") + 1,
                                      "body_end_line": index, "body_end_column": len(line),
                                      "declaration_start_line": index, "declaration_start_column": 1,
                                      "declaration_end_line": index, "declaration_end_column": len(line) + 1})
            offset += len(line) + 1
        output = self.scratch / "compiler-build/application"
        dependency = "dependency=" + str(self.root / "target/debug/deps")
        self.discovery = ["app.rs", *capture.RUST_BASELINE_FLAGS, "-L", dependency,
                          "--emit=dep-info=" + str(output.parent / "original.d")]
        sources = {str(self.source): capture.file_digest(self.source)}
        self.request = {"schema_version": 1, "root": str(self.workspace), "entry": str(self.source),
                        "policy": {key: self.plan[key] for key in compiler_build.POLICY_FIELDS},
                        "sources": sources, "declarations": self.declarations,
                        "protected_source_roots": self.profile["protected_source_roots"],
                        "discovery_argv": self.discovery}
        self.inventory = {"schema_version": 3, "sources": sources, "discovery_argv": self.discovery,
                          "functions": [{**row, "compiler_name": row["leaf"], "compiler_expansion": False,
                                         "compiled_symbol": "symbol-" + str(index), "emitted": True}
                                        for index, row in enumerate(self.declarations)]}
        (self.bundle / "application").write_bytes(b"instrumented application")
        argv = ["app.rs", *capture.RUST_BASELINE_FLAGS, "-o", str(output), "-L", dependency,
                "--sysroot", str(self.tools["rustc"].parent.parent), "--extern",
                "quux_otelc_rust=" + str(self.assets["sdk"]), "-L", dependency]
        self.metadata = {"schema_version": 3, "language": "rust", "backend": "compiler",
                         "baseline_flags": list(capture.RUST_BASELINE_FLAGS), "source": str(self.source),
                         "source_root": str(self.workspace), "source_sha256": capture.file_digest(self.source),
                         "executable_sha256": capture.file_digest(self.bundle / "application"),
                         "sdk_sha256": capture.file_digest(self.assets["sdk"]),
                         "adapter_sha256": capture.file_digest(self.root / "target/debug/otelc-rust-adapter"),
                         "compiler": {"program": str(self.tools["rustc"]), "argv": argv, "version": self.version}}
        self.environment = {"TMPDIR": str(self.scratch)}
        self.seal()

    def write(self, path: Path, document: dict) -> None:
        path.write_text(json.dumps(document))

    def seal(self) -> None:
        self.write(self.root / compiler_build.PROFILE_FILENAME, self.profile)
        for name, document in (("profile.json", self.profile), ("plan.json", self.plan),
                               ("compiler-request.json", self.request), ("inventory.json", self.inventory)):
            self.write(self.bundle / name, document)
        self.metadata["plan_sha256"] = capture.file_digest(self.bundle / "plan.json")
        self.metadata["compiler_driver"] = {
            "profile_sha256": capture.file_digest(self.root / compiler_build.PROFILE_FILENAME),
            "driver_sha256": capture.file_digest(self.assets["driver"]),
            "request_sha256": capture.file_digest(self.bundle / "compiler-request.json"),
            "inventory_sha256": capture.file_digest(self.bundle / "inventory.json")}
        self.write(self.bundle / "build.json", self.metadata)

    def verify(self, *, function: str | None = "app.selected", environment: dict | None = None) -> dict:
        result = subprocess.CompletedProcess([], 0, (self.version + "\n").encode(), b"")
        with patch.object(compiler_build, "execute", return_value=result):
            return capture.rust_manifest(self.root, self.workspace, self.source, self.bundle, self.tools,
                                         expected_function=function,
                                         environment=self.environment if environment is None else environment)

    def test_exact_compiler_profile_recipe_and_emitted_roles_qualify(self) -> None:
        result = self.verify()
        self.assertEqual(result["backend"], "compiler")
        self.assertEqual(result["selected_function"], "app.selected")
        self.assertEqual(result["selected_symbol"], "symbol-0")
        self.assertEqual(result["resolution_phase"], "mir")
        self.assertEqual(result["loaded_sources"], self.request["sources"])
        self.plan["sources"]["include"] = ["app.rs"]
        self.request["policy"]["sources"]["include"] = ["app.rs"]
        self.seal()
        self.verify()

    def test_profile_fields_assets_and_protected_roots_are_strict(self) -> None:
        original = copy.deepcopy(self.profile)
        changes = [("schema_version", True), ("schema_version", 2), ("backend", "llvm"),
                   ("commit_hash", "other"), ("protected_source_roots", []),
                   ("protected_source_roots", ["/untrusted"]), ("unknown", True)]
        for key in self.assets:
            changes += [(key, "relative"), (key, "/untrusted"), (key + "_sha256", "0" * 64)]
        for key, value in changes:
            self.profile = {**original, key: value}
            self.seal()
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.verify()

    def test_fixed_inputs_and_additions_are_bound_to_the_frozen_manifest(self) -> None:
        initial = capture.artefacts(self.root, "rust", self.tools)
        for path in (self.assets["driver"], self.root / "target/debug/deps/dependency.rmeta"):
            self.assertIn(str(path.relative_to(self.root)), initial)
        extra = self.root / "target/debug/deps/added.rlib"
        extra.write_bytes(b"added dependency")
        with self.assertRaisesRegex(ValueError, "artefacts changed"):
            capture.stable(self.root, "rust", self.tools, initial)
        extra.unlink()
        self.assets["driver"].write_bytes(b"changed compiler driver")
        with self.assertRaises(ValueError):
            capture.stable(self.root, "rust", self.tools, initial)

    def test_profile_assets_dependencies_and_retained_records_cannot_be_links(self) -> None:
        paths = [*self.assets.values(), self.root / compiler_build.PROFILE_FILENAME,
                 *(self.bundle / name for name in ("profile.json", "compiler-request.json", "inventory.json")),
                 self.root / "target/debug/deps/dependency.rmeta"]
        for path in paths:
            saved = path.read_bytes()
            original = path.with_name(path.name + ".original")
            path.rename(original)
            path.symlink_to(original)
            with self.subTest(path=path), self.assertRaises(ValueError):
                if path.suffix == ".rmeta":
                    compiler_build.inputs(self.root, self.tools)
                else:
                    self.verify()
            path.unlink()
            original.rename(path)
            self.assertEqual(path.read_bytes(), saved)
        dependencies = self.root / "target/debug/deps"
        moved = dependencies.with_name("deps-original")
        dependencies.rename(moved)
        dependencies.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError):
            compiler_build.inputs(self.root, self.tools)

    def test_manifest_versions_fields_backend_and_hashes_cannot_be_rebound(self) -> None:
        original = copy.deepcopy(self.metadata)
        changes = [("schema_version", 1), ("schema_version", 2), ("schema_version", True),
                   ("backend", "llvm"), ("unknown", 1), ("compiler_driver", {}),
                   ("compiler_driver", {**original["compiler_driver"], "driver_sha256": "0" * 64})]
        for key, value in changes:
            self.write(self.bundle / "build.json", {**original, key: value})
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.verify()
        self.write(self.bundle / "build.json", original)
        (self.bundle / "profile.json").write_text(json.dumps(self.profile, indent=2))
        with self.assertRaisesRegex(ValueError, "identity differs"):
            self.verify()

    def test_new_profile_cannot_silently_substitute_a_legacy_source_build(self) -> None:
        legacy = {key: value for key, value in self.metadata.items()
                  if key not in ("backend", "compiler_driver")}
        legacy["schema_version"] = 1
        self.write(self.bundle / "build.json", legacy)
        with self.assertRaisesRegex(ValueError, "profile and manifest versions"):
            self.verify()
        self.write(self.bundle / "build.json", self.metadata)
        profile = self.root / compiler_build.PROFILE_FILENAME
        profile.unlink()
        with self.assertRaisesRegex(ValueError, "profile and manifest versions"):
            self.verify()
        profile.symlink_to(profile.with_name("missing-profile"))
        self.write(self.bundle / "build.json", legacy)
        with self.assertRaises(ValueError):
            self.verify()
        with self.assertRaises(ValueError):
            capture.artefacts(self.root, "rust", self.tools)

    def test_compiler_recipe_requires_selected_sysroot_flags_outputs_and_version(self) -> None:
        original = copy.deepcopy(self.metadata["compiler"])
        for index, value in ((0, "rewritten.rs"), (1, "--edition=2021"),
                             (len(original["argv"]) - 1, "dependency=/untrusted"),
                             (original["argv"].index("--sysroot") + 1, "/other/sysroot"),
                             (original["argv"].index("-o") + 1, "/untrusted/application")):
            changed = copy.deepcopy(original)
            changed["argv"][index] = value
            self.metadata["compiler"] = changed
            self.seal()
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.verify()
        for key, value in (("version", "other"), ("program", str(self.assets["driver"])), ("extra", True)):
            self.metadata["compiler"] = {**original, key: value}
            self.seal()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()
        self.metadata["compiler"] = original
        self.seal()
        with self.assertRaises(ValueError):
            self.verify(environment={})
        with self.assertRaises(ValueError):
            self.verify(function=None)

    def test_actual_compiler_failure_wrong_version_stderr_and_oversized_output_refuse(self) -> None:
        for code, stdout, stderr in ((1, b"", b""), (0, b"other compiler", b""),
                                      (0, self.version.encode(), b"unexpected diagnostic"),
                                      (0, b"x" * 32769, b"")):
            result = subprocess.CompletedProcess([], code, stdout, stderr)
            with patch.object(compiler_build, "execute", return_value=result), self.assertRaises(ValueError):
                capture.rust_manifest(self.root, self.workspace, self.source, self.bundle, self.tools,
                                      expected_function="app.selected", environment=self.environment)

    def test_rehashed_request_cannot_change_sources_selection_or_discovery(self) -> None:
        original = copy.deepcopy(self.request)
        changes = [("schema_version", True), ("schema_version", 2), ("root", "/untrusted"),
                   ("entry", "/untrusted/app.rs"), ("sources", {}), ("policy", {}),
                   ("protected_source_roots", []), ("discovery_argv", []),
                   ("declarations", []), ("declarations", [None]), ("unknown", 1)]
        for key, value in changes:
            self.request = {**original, key: value}
            self.seal()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()

    def test_rehashed_plan_cannot_change_the_requested_target_or_build_scope(self) -> None:
        original = copy.deepcopy(self.plan)
        for key, value in (("schema_version", True), ("backend", "llvm"), ("language", "go"),
                           ("execution_available", 1), ("unavailable", ["gap"]),
                           ("functions", {"include": ["app.main"], "exclude": []}),
                           ("sources", {"include": ["other.rs"], "exclude": []})):
            self.plan = {**original, key: value}
            self.request["policy"] = {key: self.plan[key] for key in compiler_build.POLICY_FIELDS}
            self.seal()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()

    def test_rehashed_inventory_cannot_lose_or_rebind_the_emitted_target(self) -> None:
        original = copy.deepcopy(self.inventory)
        for key, value in (("schema_version", 2), ("sources", {}), ("discovery_argv", []), ("unknown", 1)):
            self.inventory = {**original, key: value}
            self.seal()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()
        for key, value in (("compiler_name", "other"), ("compiler_expansion", True), ("emitted", False),
                           ("compiled_symbol", ""), ("selected", False), ("body_start_column", 9999)):
            self.inventory = copy.deepcopy(original)
            self.inventory["functions"][0][key] = value
            self.seal()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()
        self.inventory = copy.deepcopy(original)
        self.inventory["functions"][1]["compiled_symbol"] = self.inventory["functions"][0]["compiled_symbol"]
        self.seal()
        with self.assertRaises(ValueError):
            self.verify()

    def test_bound_requests_enforce_their_own_regular_file_size_limit(self) -> None:
        request = self.bundle / "compiler-request.json"
        request.write_bytes(b" " * (8 * 1024 * 1024 + 1))
        self.metadata["compiler_driver"]["request_sha256"] = capture.file_digest(request)
        self.write(self.bundle / "build.json", self.metadata)
        with self.assertRaisesRegex(ValueError, "size limit"):
            self.verify()
