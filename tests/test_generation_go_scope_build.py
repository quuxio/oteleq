"""Build6/7 require independently queried tooling2 and literal private helpers."""

import copy
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_build as build
import go_files as files
import go_tooling
from go_provider import SCOPE_HELPER_PROFILE
from test_generation_go_source_build import fixture, write
from test_generation_go_tooling import fixture as tooling_fixture, query


class GoScopeBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.intent, self.receipt, self.inventory = fixture(self.base)
        directory, compiler, tools, _ = tooling_fixture(self, self.base)
        binding = go_tooling.prepare(directory, compiler,
            lambda *args, **options: query(tools, *args, **options))
        self.intent = replace(self.intent, toolchain=tools, helper_profile=SCOPE_HELPER_PROFILE, tooling=binding)
        golden = json.loads((REPO / "tests/fixtures/go-scope-hooks.json").read_text())
        self.assertEqual(golden["selection_sha256"], self.receipt["selection"]["sha256"])
        for name, text in golden["files"].items():
            path = self.intent.directory / "private" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.receipt.update(schema_version=6, helper_profile=SCOPE_HELPER_PROFILE, toolchain=copy.deepcopy(tools))
        self.publish()

    def publish(self):
        directory = self.intent.directory
        self.receipt["private_inputs"] = files.freeze(directory / "private").identities
        self.receipt["commands"] = build.commands(self.intent)
        write(directory / "commands.json", self.receipt["commands"])
        write(directory / "inspection/inventory.json", self.inventory)
        self.receipt["inventory"] = files.identity(directory / "inspection/inventory.json")
        names = ["commands.json", *[f"command-{index}.{suffix}" for index in range(len(self.receipt["commands"]))
                                   for suffix in ("stdout", "stderr")]]
        self.receipt["command_evidence"] = {name: files.identity(directory / name) for name in names}
        write(directory / "build.json", self.receipt)

    def tagged(self):
        self.intent = replace(self.intent, build_tags=("feature", "tools", "\u03c0"))
        self.inventory.update(schema_version=2, build_tags=list(self.intent.build_tags))
        self.receipt.update(schema_version=7, build_tags=list(self.intent.build_tags))
        pin = self.intent.directory / "private/otel.instrumentation.go"
        pin.write_bytes(pin.read_bytes().replace(b"//go:build tools\n", b"//go:build !feature\n", 1))
        self.publish()

    def test_both_scope_profiles_bind_literals_without_executing_metadata(self):
        with patch("subprocess.run", side_effect=AssertionError("reader executed metadata")):
            build.read(self.intent).verify()
            self.tagged()
            actual = build.read(self.intent)
            actual.verify()
        self.assertEqual(actual.receipt["schema_version"], 7)
        self.assertEqual(actual.intent.tooling.seal, self.intent.tooling.seal)
        self.assertEqual(len(actual.receipt["commands"]), 15)

    def test_scope_build_requires_queried_binding_and_cannot_use_old_formats(self):
        for intent in (replace(self.intent, tooling=None), replace(self.intent, helper_profile=None),
                       replace(self.intent, helper_profile="unknown"),
                       replace(self.intent, tooling=go_tooling.read(self.intent.tooling.directory,
                               Path(self.intent.toolchain["go"])))):
            with self.subTest(intent=intent.helper_profile), self.assertRaises(ValueError):
                build.read(intent)
        for profile in (None, SCOPE_HELPER_PROFILE):
            changed = replace(self.intent, helper_profile=profile, tooling=None)
            with self.assertRaises(ValueError):
                build.validate_intent(changed)

    def test_old_or_missing_receipt_fields_and_helper_substitutions_refuse(self):
        original = copy.deepcopy(self.receipt)
        for key, value in (("schema_version", 4), ("schema_version", 6.0), ("schema_version", True),
                           ("helper_profile", "legacy"), ("command_evidence", {})):
            write(self.intent.directory / "build.json", {**original, key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                build.read(self.intent)
        for name in ("helper_profile", "command_evidence"):
            write(self.intent.directory / "build.json", {key: value for key, value in original.items() if key != name})
            with self.subTest(missing=name), self.assertRaises(ValueError):
                build.read(self.intent)
        self.publish()
        helper = self.intent.directory / ("private/zz_otelc_" + self.receipt["selection"]["sha256"][:12] + ".go")
        helper.write_bytes(helper.read_bytes() + b"// altered and rehashed\n")
        self.publish()
        with self.assertRaisesRegex(ValueError, "helper differs"):
            build.read(self.intent)

    def test_untagged_channels_and_reused_tooling_facts_cannot_be_repaired(self):
        checked = build.read(self.intent)
        log = self.intent.directory / "command-0.stderr"
        log.write_bytes(b"changed compiler diagnostic")
        with self.assertRaisesRegex(ValueError, "compiler evidence differs"):
            build.read(self.intent)
        with self.assertRaisesRegex(ValueError, "compiler evidence changed"):
            checked.verify()
        log.write_bytes(b"")
        self.publish()
        checked = build.read(self.intent)
        source = self.intent.tooling.source.root / "go.mod"
        source.write_bytes(source.read_bytes())
        with self.assertRaisesRegex(ValueError, "source changed"):
            checked.verify()

    def test_tagged_scope_cannot_omit_tags_or_use_build5(self):
        self.tagged()
        original = copy.deepcopy(self.receipt)
        for key, value in (("schema_version", 5), ("schema_version", 6), ("build_tags", []),
                           ("build_tags", ["tools", "feature", "\u03c0"])):
            write(self.intent.directory / "build.json", {**original, key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                build.read(self.intent)


if __name__ == "__main__":
    unittest.main()
