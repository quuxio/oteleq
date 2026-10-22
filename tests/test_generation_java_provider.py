"""Explicit Java API selection, complete policy and frozen public provider probe."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import java_provider as provider
import policy


def entry() -> dict:
    return {"language": "java", "java_backend": "prepared", "path": "sample/App.java", "id": "chosen",
            "otelc_function": "sample.App.add(int)", "status": "ready", "reason": ""}


def response(value: dict) -> dict:
    return {"policy": provider.configuration(value, "http://127.0.0.1:4318", "oteleq-java-provider"),
            "implemented": ["java"], "remaining": sorted(provider.SDK_LANGUAGES - {"java"})}


class JavaProviderTests(unittest.TestCase):
    def test_explicit_backend_and_complete_schema_three_policy(self):
        self.assertEqual(policy.validate({})["adapters"]["java"], {"backend": "legacy"})
        for backend in ("legacy", "prepared"):
            self.assertEqual(policy.validate({"adapters": {"java": {"backend": backend}}})["adapters"]["java"]["backend"], backend)
        for backend in (None, True, "", "Legacy", "unknown"):
            with self.subTest(backend=backend), self.assertRaises(ValueError): provider.backend(backend)
        with self.assertRaises(ValueError): policy.validate({"adapters": {"java": {"other": True}}})
        value = entry();value["path"] = "sample/\U0001f680.java"
        text = provider.policy(value, "http://127.0.0.1:4321", "case")
        data = provider.configuration(value, "http://127.0.0.1:4321", "case")
        self.assertEqual(tomllib.loads(text), data)
        self.assertEqual(provider.digest(data), hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest())
        self.assertTrue(provider.prepared(value))
        self.assertFalse(provider.prepared({**value, "language": "python"}))

    def bind(self, value, result=None, status=0):
        data = response(value) if result is None else result
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        execute = Mock(return_value=subprocess.CompletedProcess([], status, raw, b""))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            java = root / "jdk/bin/java";java.parent.mkdir(parents=True);java.write_bytes(b"java")
            provider.bind(value, root, root, {"java": java}, execute)
            if execute.called:
                args, options = execute.call_args
                self.assertEqual(args[0][-1], "plan")
                self.assertEqual(args[2]["JAVA_HOME"], str(java.parent.parent))
                self.assertEqual(args[2]["PYTHONPATH"], str(root))
                self.assertEqual(args[2]["PYTHONDONTWRITEBYTECODE"], "1")
                self.assertTrue(Path(args[2]["PYTHONPYCACHEPREFIX"]).is_dir())
                self.assertEqual(options["max_output_bytes"], provider.MAX_METADATA)
        return execute

    def test_public_probe_retains_full_request_response_and_selected_jdk(self):
        value = entry()
        self.bind(value)
        self.assertEqual(value["status"], "ready")
        self.assertEqual(value["java_provider"]["resolved"], response(value))
        self.assertEqual(tomllib.loads(value["java_provider"]["request"]), response(value)["policy"])

    def test_candidate_languages_are_retained_without_becoming_implemented_capabilities(self):
        for candidates in ([], ["javascript", "typescript"]):
            value = entry()
            data = {**response(value), "candidates": candidates}
            with self.subTest(candidates=candidates):
                self.bind(value, data)
                self.assertEqual(value["status"], "ready", value["reason"])
                self.assertEqual(value["java_provider"]["resolved"], data)
                self.assertEqual(value["java_provider"]["resolved"]["implemented"], ["java"])

    def test_malformed_or_implemented_candidate_claims_remain_blocked(self):
        for candidates in (None, True, "javascript", [True], ["unknown"], ["java"],
                           ["javascript", "javascript"]):
            value = entry()
            with self.subTest(candidates=candidates):
                self.bind(value, {**response(value), "candidates": candidates})
                self.assertEqual(value["status"], "blocked")
                self.assertNotIn("resolved", value["java_provider"])

    def test_java_candidate_does_not_replace_required_implemented_java(self):
        value = entry()
        data = {**response(value), "implemented": [], "remaining": sorted(provider.SDK_LANGUAGES),
                "candidates": ["java"]}
        self.bind(value, data)
        self.assertEqual(value["status"], "blocked")
        self.assertNotIn("resolved", value["java_provider"])

    def test_unavailable_changed_duplicate_or_incomplete_capability_is_blocked(self):
        variants = [b"not json", b'{"policy":{},"policy":{}}']
        for group, values in (("implemented", [[], ["java", "java"], [True]]),
                              ("remaining", [[], ["java"], "other"]), ("policy", [{}])):
            for value in values:
                changed = response(entry());changed[group] = value;variants.append(changed)
        extra = response(entry());extra["unknown"] = True;variants.append(extra)
        for data in variants:
            value = entry()
            with self.subTest(data=data):
                self.bind(value, data)
                self.assertEqual(value["status"], "blocked")
                self.assertIn("provider unavailable", value["reason"])
                self.assertNotIn("resolved", value["java_provider"])
        value = entry();self.bind(value, status=1)
        self.assertEqual(value["status"], "blocked")

    def test_unrequested_excluded_and_blocked_entries_do_not_query(self):
        for change in ({"status": "blocked"}, {"status": "excluded"}, {"java_backend": "legacy"}, {"language": "go"}):
            self.assertFalse(self.bind({**entry(), **change}).called)

    def test_prebuilt_products_sources_and_tools_are_frozen_and_links_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in provider.SDK_MODULES:
                path = root / "otelc" / name;path.parent.mkdir(exist_ok=True);path.write_bytes(b"# source\n")
            for name in (provider.AGENT, provider.EXTENSION, "adapters/java/pom.xml", "adapters/java/src/main/App.java"):
                path = root / name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(b"product")
            java = root / "java";java.write_bytes(b"selected")
            agent_sha = hashlib.sha256(b"product").hexdigest()
            with patch.object(provider, "AGENT_SHA256", agent_sha):
                before = provider.artefacts(root, {"java": java})
                self.assertIn("tool:java", before)
                (root / "otelc/new.py").write_text("# added")
                self.assertNotEqual(provider.artefacts(root, {"java": java}), before)
                (root / "otelc/link.py").symlink_to(root / "otelc/java.py")
                with self.assertRaisesRegex(ValueError, "symlink"): provider.artefacts(root, {"java": java})
                (root / "otelc/link.py").unlink()
                (root / provider.AGENT).write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "agent digest"): provider.artefacts(root, {"java": java})
                (root / provider.AGENT).unlink()
                with self.assertRaisesRegex(ValueError, "missing"): provider.artefacts(root, {"java": java})


if __name__ == "__main__":
    unittest.main()
