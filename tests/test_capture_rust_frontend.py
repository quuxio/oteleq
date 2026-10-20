"""Compiler frontend provenance extends, rather than replaces, the legacy contract."""
import copy

import test_capture_rust_llvm as llvm_tests

capture = llvm_tests.capture


class RustFrontendTests(llvm_tests.RustLlvmTests):
    """Run the legacy refusal corpus again with profile2/inventory3 fixtures."""

    def setUp(self):
        super().setUp()
        self.frontend = self.root / "target/debug/otelc-rust-frontend"
        self.frontend.write_bytes(b"qualified pinned compiler frontend")
        self.profile.update(schema_version=2, frontend=str(self.frontend),
                            frontend_sha256=capture.file_digest(self.frontend))
        self.write(self.profile_path, self.profile)
        self.inventory["schema_version"] = 3
        for index, row in enumerate(self.inventory["functions"]):
            row.update(compiler_name="selected" if row["selected"] else "main", compiler_expansion=False,
                       compiled_symbol="symbol-" + str(index), emitted=True)
        argv = self.metadata["compiler"]["argv"]
        index = 1 + len(capture.RUST_LLVM_BASELINE_FLAGS)
        argv[index:index] = ["--sysroot", str(self.tools["rustc"].parent.parent)]
        self.seal_records()

    def test_exact_profile_recipe_selection_and_compiled_symbol_qualify(self):
        assets = {"sdk": self.sdk, "plugin": self.plugin, "frontend": self.frontend}
        self.assertEqual(capture.rust_profile(self.root, self.tools), assets)
        result = self.verify()
        self.assertEqual(result["selected_compiler_name"], "selected")
        self.assertIs(result["compiler_expansion"], False)
        self.assertEqual(result["selected_symbol"], "symbol-0")
        self.assertEqual(result["frontend_sha256"], capture.file_digest(self.frontend))
        self.assertEqual(result["baseline_flags"], list(capture.RUST_LLVM_BASELINE_FLAGS))

    def test_frontend_path_hash_fields_and_schema_are_strict(self):
        original = copy.deepcopy(self.profile)
        mutations = [("schema_version", 1), ("schema_version", 3), ("frontend", "/untrusted/frontend"),
                     ("frontend", "relative/frontend"), ("frontend", str(self.sdk)),
                     ("frontend_sha256", "0" * 64), ("frontend_sha256", None)]
        for key, value in mutations:
            self.write(self.profile_path, {**original, key: value})
            self.seal_records()
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.verify()
        for key in ("frontend", "frontend_sha256"):
            missing = copy.deepcopy(original)
            del missing[key]
            self.write(self.profile_path, missing)
            self.seal_records()
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.verify()

    def test_frontend_is_a_fixed_regular_frozen_input(self):
        frozen = capture.artefacts(self.root, "rust", self.tools, rust_backend="llvm")
        self.assertIn(str(self.frontend.relative_to(self.root)), frozen)
        self.frontend.write_bytes(b"changed frontend")
        self.profile["frontend_sha256"] = capture.file_digest(self.frontend)
        self.write(self.profile_path, self.profile)
        with self.assertRaises(ValueError):
            capture.stable(self.root, "rust", self.tools, frozen, rust_backend="llvm")
        self.frontend.unlink()
        self.frontend.symlink_to(self.sdk)
        self.profile["frontend_sha256"] = capture.file_digest(self.sdk)
        self.write(self.profile_path, self.profile)
        with self.assertRaises(ValueError):
            capture.rust_llvm_inputs(self.root, self.tools)

    def test_frontend_recipe_requires_the_exact_selected_sysroot(self):
        original = copy.deepcopy(self.metadata["compiler"])
        index = original["argv"].index("--sysroot")
        variants = [original["argv"][:index] + original["argv"][index + 2:],
                    original["argv"][:index + 1] + ["/different/sysroot"] + original["argv"][index + 2:]]
        for argv in variants:
            self.metadata["compiler"] = {**original, "argv": argv}
            self.seal_records()
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                self.verify()
        self.metadata["compiler"] = {**original, "program": str(self.frontend)}
        self.seal_records()
        with self.assertRaises(ValueError):
            self.verify()

    def test_rehashed_frontend_inventory_fields_cannot_change_the_selected_instance(self):
        original = copy.deepcopy(self.inventory)
        mutations = [("compiler_name", "unrelated"), ("compiler_name", ""), ("compiler_name", 1),
                     ("compiler_expansion", True), ("compiler_expansion", 0), ("emitted", False),
                     ("emitted", 1), ("compiled_symbol", "other-instance"), ("compiled_symbol", ""),
                     ("compiled_symbol", " "), ("compiled_symbol", None)]
        for key, value in mutations:
            self.inventory = copy.deepcopy(original)
            self.inventory["functions"][0][key] = value
            self.seal_records()
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.verify()
        for key in ("compiler_name", "compiler_expansion", "emitted", "compiled_symbol"):
            self.inventory = copy.deepcopy(original)
            del self.inventory["functions"][0][key]
            self.seal_records()
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.verify()

    def test_uninstantiated_declarations_are_retained_but_cannot_witness_the_target(self):
        unused = {**self.inventory["functions"][0], "name": "app.unused", "compiler_name": "unused",
                  "selected": False, "emitted": False, "compiled_symbol": ""}
        self.inventory["functions"].append(unused)
        self.seal_records()
        self.verify()
        unused["compiled_symbol"] = " "
        self.seal_records()
        with self.assertRaises(ValueError):
            self.verify()
        unused["compiled_symbol"] = ""
        self.inventory["functions"][0].update(emitted=False, compiled_symbol="")
        self.seal_records()
        with self.assertRaises(ValueError):
            self.verify()

    def test_duplicate_symbols_and_rehashed_resolution_rebinding_are_refused(self):
        original = copy.deepcopy(self.inventory)
        actual = copy.deepcopy(self.resolved)
        self.inventory["functions"][1]["compiled_symbol"] = "symbol-0"
        self.seal_records()
        with self.assertRaises(ValueError):
            self.verify()
        self.inventory = original
        self.resolved["functions"][0]["compiled_symbol"] = "another-symbol"
        self.seal_records()
        with self.assertRaises(ValueError):
            self.verify()
        self.resolved = actual
        self.resolved["functions"].append({**actual["functions"][0], "selected": False, "startup": False})
        self.seal_records()
        with self.assertRaises(ValueError):
            self.verify()

    def test_profile_and_inventory_versions_must_be_paired(self):
        self.inventory["schema_version"] = 2
        self.seal_records()
        with self.assertRaises(ValueError):
            self.verify()
        self.inventory["schema_version"] = 3
        self.profile["schema_version"] = 1
        del self.profile["frontend"]
        del self.profile["frontend_sha256"]
        self.write(self.profile_path, self.profile)
        self.seal_records()
        with self.assertRaises(ValueError):
            self.verify()
        self.inventory["schema_version"] = 2
        index = self.metadata["compiler"]["argv"].index("--sysroot")
        del self.metadata["compiler"]["argv"][index:index + 2]
        self.seal_records()
        with self.assertRaisesRegex(ValueError, "legacy inventory"):
            self.verify()
