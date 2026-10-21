"""Corrected prepared recipes require explicit selection and pinned bootstrap bytes."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples"), str(REPO / "tests")]
import generation
import java_launch
import java_profiles as profiles
import java_provider as provider
import policy
import test_generation_java_launch as launch_fixture


def patch_jar(root: Path, *, parser: bytes = b"parser", extra: str | None = None) -> Path:
    path = root / profiles.PATCH
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(profiles.PARSER, parser)
        for entry, source in profiles.LICENCES.items():
            original = root / source
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_bytes(source.encode())
            archive.writestr(entry, original.read_bytes())
        if extra:
            archive.writestr(extra, b"unexpected")
    return path


class JavaProfileTests(unittest.TestCase):
    def test_explicit_profile_is_frozen_and_never_inferred_from_provider_files(self):
        self.assertEqual(policy.validate({})["adapters"]["java"], {"backend": "legacy"})
        self.assertEqual(profiles.settings({"backend": "prepared"}), {"backend": "prepared"})
        for profile in (profiles.STOCK, profiles.SAFE):
            config = {"backend": "prepared", "profile": profile}
            self.assertEqual(policy.validate({"adapters": {"java": config}})["adapters"]["java"], config)
        for value in (True, None, "", "latest", "safe"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                profiles.name(value)
        with self.assertRaises(ValueError):
            policy.validate({"adapters": {"java": {"profile": profiles.SAFE}}})

    def test_only_pinned_parser_and_matching_licence_notice_can_be_bootstrapped(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(profiles, "PARSER_SHA256", hashlib.sha256(b"parser").hexdigest()):
            root = Path(temporary)
            path = patch_jar(root)
            self.assertEqual(set(profiles.patch_inputs(root)), {path, *(root / source for source in profiles.LICENCES.values())})
            for extra in ("Extra.class", "foreign/", profiles.PARSER):
                patch_jar(root, extra=extra)
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    profiles.patch_inputs(root)
            patch_jar(root, parser=b"changed")
            with self.assertRaisesRegex(ValueError, "digest"):
                profiles.patch_inputs(root)
            patch_jar(root)
            original = root / next(iter(profiles.LICENCES.values()))
            original.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "licence/notice"):
                profiles.patch_inputs(root)
            for payload in (b"invalid", b"x" * 262145):
                path.write_bytes(payload)
                with self.assertRaises(ValueError):
                    profiles.patch_inputs(root)
            patch_jar(root, parser=b"x" * 16385)
            with self.assertRaisesRegex(ValueError, "oversized"):
                profiles.patch_inputs(root)

    def test_full_fixed_recipe_refuses_stock_substitution_and_missing_patch_tooling(self):
        fixture = launch_fixture.JavaLaunchTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        stock, plain = fixture.value(), fixture.value(True)
        fixture.entry["java_profile"] = profiles.SAFE
        config = java_launch.agent_values(fixture.data, "App", "selected", profiles.SAFE)
        (fixture.runtime / "agent.properties").write_text(java_launch.properties(config))
        patch_path = patch_jar(fixture.root)
        corrected = copy.deepcopy(stock)
        corrected["tooling"] = [java_launch.identity(Path(row["path"])) for row in stock["tooling"]]
        corrected["argv"] = java_launch.expected_argv(fixture.root, fixture.java, fixture.classes, "OteleqDriver",
                fixture.runtime, fixture.data, "App", "selected", False, profiles.SAFE)
        corrected["tooling"].append(java_launch.identity(patch_path))
        fixture.verify(corrected);fixture.verify(plain, True)
        self.assertIn("-Xbootclasspath/a:" + str(patch_path), corrected["argv"])
        self.assertIn("-Dotel.instrumentation.methods.enabled=false", corrected["argv"])
        self.assertIn("-Dotel.instrumentation.otelc-methods.enabled=true", corrected["argv"])
        with self.assertRaisesRegex(ValueError, "launch recipe"):
            fixture.verify(stock)
        missing = copy.deepcopy(corrected);missing["tooling"].pop()
        with self.assertRaisesRegex(ValueError, "prepared input"):
            fixture.verify(missing)
        fixture.entry.pop("java_profile")
        with self.assertRaisesRegex(ValueError, "launch recipe"):
            fixture.verify(corrected)

    def test_safe_profile_freezes_patch_sources_and_rechecks_them_before_replay(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(profiles, "PARSER_SHA256", hashlib.sha256(b"parser").hexdigest()), \
                patch.object(provider, "AGENT_SHA256", hashlib.sha256(b"agent").hexdigest()):
            root = Path(temporary)
            for name in provider.SDK_MODULES:
                path = root / "otelc" / name;path.parent.mkdir(exist_ok=True);path.write_bytes(b"# source")
            for name in (provider.AGENT, provider.EXTENSION, "adapters/java/pom.xml", "adapters/java/src/main/App.java"):
                path = root / name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(b"agent")
            java = root / "java";java.write_bytes(b"selected")
            patch_jar(root)
            frozen = provider.artefacts(root, {"java": java}, profiles.SAFE)
            self.assertIn(profiles.PATCH, frozen)
            self.assertLessEqual(set(profiles.LICENCES.values()), set(frozen))
            entry = {"language": "java", "java_backend": "prepared", "java_profile": profiles.SAFE}
            generation.provider_stable(root, "java", {"java": java}, frozen, entry)
            patch_path = root / profiles.PATCH
            with zipfile.ZipFile(patch_path, "a") as archive:
                archive.comment = b"changed packaging"
            with self.assertRaisesRegex(ValueError, "SDK or selected tools changed"):
                generation.provider_stable(root, "java", {"java": java}, frozen, entry)


if __name__ == "__main__":
    unittest.main()
