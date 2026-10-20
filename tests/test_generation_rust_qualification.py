"""Qualification fixtures keep valid panic expectations and instability separate."""
from pathlib import Path
import json
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import qualify_rust_build as qualifier


class RustQualificationFixtureTests(unittest.TestCase):
    def test_default_compiler_routes_check_all_framework_and_exported_cases(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            replay = folder / "replay/report.json"
            replay.parent.mkdir()
            replay.write_text(json.dumps({"source_preserved": True, "cases": [{"case": "one"}]}))
            exported = folder / "export-comparison/report.json"
            exported.parent.mkdir()
            exported.write_text(json.dumps({"source_preserved": True, "cases": [{"case": str(index)} for index in range(4)]}))
            framework = '\n'.join(json.dumps({"report": str(replay)}) for _ in range(4))
            with patch.object(qualifier, "command", return_value=framework) as command, patch.object(qualifier, "check_case") as checked:
                count = qualifier.compiler_retained_routes(folder / "cli", folder / "workspace", folder)
            self.assertEqual(count, 72)
            self.assertEqual(checked.call_count, 12)
            self.assertEqual([call.args[2] for call in command.call_args_list],
                             ["framework", "export", "export-run", "export-framework"])
            self.assertTrue(all(call.args[2:] == ("compiler", None) for call in checked.call_args_list))

    def test_frontend_provenance_controls_are_scoped_to_schema3(self):
        legacy = {"schema_version": 2, "functions": [{"selected": True}]}
        self.assertEqual(qualifier.frontend_manifest_controls(legacy), [])
        compiled = {"schema_version": 3, "functions": [{"selected": False}, {"selected": True}]}
        controls = qualifier.frontend_manifest_controls(compiled)
        self.assertEqual(len(controls), 4)
        self.assertEqual({row[2] for row in controls},
                         {("functions", 1, key) for key in ("compiler_name", "compiler_expansion", "emitted", "compiled_symbol")})
        self.assertTrue(all(row[1] == "inventory.json" for row in controls))

    def test_llvm_fixture_keeps_the_unstable_case_and_declares_its_hook_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, policy, column = qualifier.fixture(Path(temporary), "llvm")
            text = (source / "wide.rs").read_text()
            config = tomllib.loads(policy.read_text())
        self.assertEqual(config["adapters"]["rust"]["backend"], "llvm")
        self.assertEqual(config["functions"]["exclude"], ["*<closure>*"])
        fixtures = {row["function"]: row for row in config["fixtures"]}
        for name in ("wide.intentional_error", "wide.unstable_error"):
            self.assertEqual(fixtures[name]["expected_baseline"],
                             {"kind": "error", "category": "panic", "type": "rust.panic.str"})
        self.assertIn('eprintln!("case-pid:{}",std::process::id())', text)
        self.assertIn('eprintln!("app-panic:expected")', text)
        self.assertEqual(column, 35)
        self.assertEqual(qualifier.expected_channels({"function": "wide.intentional_error"}, column),
                         (b'error:str:"expected"', b"app-panic:expected\n"))

    def test_compiler_fixture_retains_the_original_domain_and_no_hook_exclusion(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, policy, column = qualifier.fixture(Path(temporary), "compiler")
            text = (source / "wide.rs").read_text()
            config = tomllib.loads(policy.read_text())
        self.assertNotIn("adapters", config)
        self.assertNotIn("functions", config)
        self.assertNotIn("panic", text)
        self.assertIsNone(column)
        self.assertEqual(len(config["fixtures"]), 2)
        self.assertEqual(qualifier.expected_channels({"function": "wide.logical_source_length"}, None),
                         (b"return:usize:7", b""))
