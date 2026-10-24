"""Scope-safe helpers have literal bytes and preserve static result predicates."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_files as files
import go_hooks as hooks
from go_provider import SCOPE_HELPER_PROFILE
from test_generation_go_source_build import fixture


class GoScopeHookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.intent, self.receipt, self.inventory = fixture(Path(temporary.name).resolve())
        self.selection = self.receipt["selection"]
        self.golden = json.loads((REPO / "tests/fixtures/go-scope-hooks.json").read_text())

    def render(self, **options):
        return hooks.generated(self.selection, self.inventory, "example.test/app",
                               helper_profile=SCOPE_HELPER_PROFILE, **options)

    def private(self):
        root = self.intent.directory / "private"
        for name, data in self.golden["files"].items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data)
        return files.freeze(root)

    def test_complete_literal_helpers_require_no_sdk_import_or_execution(self):
        with patch("subprocess.run", side_effect=AssertionError("renderer executed a tool")):
            expected = {name: value.encode() for name, value in self.golden["files"].items()}
            self.assertEqual(self.render(), expected)
            hooks.verify(self.intent.original, self.private(), self.selection, self.inventory,
                         "example.test/app", helper_profile=SCOPE_HELPER_PROFILE)
        tagged = self.render(build_tags=("feature", "tools", "\u03c0"))
        self.assertEqual(tagged["otel.instrumentation.go"], expected["otel.instrumentation.go"].replace(b"//go:build tools", b"//go:build !feature"))
        self.assertEqual({key: value for key, value in tagged.items() if key != "otel.instrumentation.go"},
                         {key: value for key, value in expected.items() if key != "otel.instrumentation.go"})

    def test_closed_error_predicates_use_private_constants_and_static_generic_nil_checks(self):
        rows = [{"expression": "nil", "error": True, "failure": "nil != nil", "pointer": ""},
                {"expression": "other", "error": True, "failure": "true", "pointer": ""}]
        prefix = "__otelc_unit_"
        self.assertEqual(hooks.failure(rows, prefix=prefix), prefix + "NotNil(nil) || " + prefix + "True")
        self.assertEqual(hooks.failure([], prefix=prefix), prefix + "False")
        self.inventory["functions"][0]["results"] = rows
        self.assertIn(("Invocation.End(" + hooks.failure(rows, prefix="__otelc_02c685ccb4cb_") + ")").encode(),
                      self.render()["otelc_rules/otelc.yaml"])
        for predicate in ("false", "other != nil", "nil == nil", "reflect.ValueOf(nil)"):
            with self.subTest(predicate=predicate), self.assertRaises(ValueError):
                hooks.failure([{**rows[0], "failure": predicate}], prefix=prefix)

    def test_every_rehashed_helper_or_added_private_source_still_refuses(self):
        private = self.private()
        for name in self.golden["files"]:
            path = private.root / name
            original = path.read_bytes()
            path.write_bytes(original + b"altered\n")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "independent recipe"):
                hooks.verify(self.intent.original, files.freeze(private.root), self.selection, self.inventory,
                             "example.test/app", helper_profile=SCOPE_HELPER_PROFILE)
            path.write_bytes(original)
        extra = private.root / "unrequested.go"
        extra.write_text("package main\n")
        with self.assertRaisesRegex(ValueError, "file denominator"):
            hooks.verify(self.intent.original, files.freeze(private.root), self.selection, self.inventory,
                         "example.test/app", helper_profile=SCOPE_HELPER_PROFILE)

    def test_reserved_bootstrap_directory_and_unknown_profile_refuse(self):
        private = self.private()
        directory = self.intent.original.root / ("otelc_bootstrap_" + self.selection["sha256"][:12])
        directory.mkdir()
        with self.assertRaisesRegex(ValueError, "collide"):
            hooks.verify(files.freeze(self.intent.original.root), private, self.selection, self.inventory,
                         "example.test/app", helper_profile=SCOPE_HELPER_PROFILE)
        for value in ("unknown", True, 6):
            with self.subTest(profile=value), self.assertRaisesRegex(ValueError, "helper profile"):
                hooks.generated(self.selection, self.inventory, "example.test/app", helper_profile=value)

    def test_receiver_packages_share_one_private_bootstrap_and_keep_accessor_calls(self):
        row = copy.deepcopy(self.inventory["functions"][0])
        row.update(name="example.test/app/worker.Counter.Step", package="example.test/app/worker",
                   file="worker/call.go", symbol="Step", receiver_id="*Counter")
        self.inventory["functions"][0] = row
        self.inventory["packages"]["example.test/app/worker"] = {"name": "worker", "directory": "worker"}
        self.selection["functions"] = [row]
        result = self.render()
        self.assertEqual(len([name for name in result if name.endswith("/bootstrap.go")]), 1)
        self.assertEqual(len(result), 6)
        self.assertIn(b"Runtime().Probes.Start(0)", result["otelc_rules/otelc.yaml"])
        self.assertIn(b"Runtime().Close()", result["otelc_rules/otelc.yaml"])
