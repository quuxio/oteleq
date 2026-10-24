"""Prepared Go metadata cannot replace caller intent, source or fixed launch tools."""

import copy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_build
import go_files as files
import go_prepared as prepared
import python_prepared
from test_generation_go_source_build import fixture


def digest(value) -> str:
    return hashlib.sha256((json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()).hexdigest()


def private(path: Path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    path.chmod(0o600)


class GoPreparedTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        intent, _, _ = fixture(self.base)
        built = go_build.read(intent)
        producer, runtime = self.base / "producer", self.base / "runtime"
        producer.mkdir(); runtime.mkdir(mode=0o700)
        for name in ("go_supervisor.py", "prepared_go.py"):
            (producer / name).write_text('"""Frozen producer source, never executed by this test."""\n')
        python = Path(sys.executable).absolute()
        policy = {"schema_version": 3, "languages": ["go"],
            "resource": {"service_name": "literal-go-fixture"},
            "sources": {"include": ["**/*.go"], "exclude": []},
            "functions": {"include": ["example.test/app.Add"], "exclude": []},
            "export": {"endpoint": "http://127.0.0.1:12345", "interval_ms": 1000,
                       "timeout_ms": 1000, "shutdown_timeout_ms": 10000},
            "metrics": {"collection": True, "emission": True, "histogram_boundaries_seconds": [0.01, 0.1]},
            "traces": {"enabled": True, "sample_ratio": 1.0},
            "context": {"tasks": False, "http": False},
            "lifetimes": {"enabled": False, "max_live": 100, "include": [], "exclude": [], "release_methods": []},
            "benchmark": {"iterations": 1, "samples": 1, "warmup": 1}}
        self.intent = prepared.Intent(built, runtime, files.freeze(producer), python,
                                     python_prepared.file_identity(python), policy, False, ("literal argument", "--flag"))
        selection = built.receipt["selection"]["sha256"]
        self.config = {"schema_version": 2, "service_name": "literal-go-fixture", "endpoint": "http://127.0.0.1:12345",
            "interval_ms": 1000, "timeout_ms": 1000, "shutdown_timeout_ms": 10000,
            "collection": True, "emission": True, "traces_enabled": True, "sample_ratio": 1.0, "http_context": False,
            "functions": ["example.test/app.Add"], "lifetimes": [], "max_live": 100, "boundaries": [0.01, 0.1],
            "policy_sha256": hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest(),
            "selection_sha256": selection}
        private(runtime / "config.json", self.config)
        config_identity = files.identity(runtime / "config.json")
        request = {"schema_version": 1, "kind": "otelc.go.request", "profile": "go-source-v1",
            "build": built.identity, "runtime": str(runtime), "policy": policy,
            "arguments": ["literal argument", "--flag"], "plain": False, "launch_id": "a" * 32}
        plan = {"schema_version": 1, "kind": "otelc.go.plan", "profile": "go-source-v1",
            "request_sha256": digest(request), "cwd": str(intent.original.root),
            "argv": [str(intent.directory / "instrumented"), "literal argument", "--flag"],
            "binary": built.receipt["instrumented"], "selection_sha256": selection, "source_complete": False}
        manifest = {"schema_version": 1, "kind": "otelc.go.prepared", "profile": "go-source-v1",
            "request_sha256": digest(request), "plan_sha256": digest(plan),
            "config": {"schema_version": 1, "kind": "otelc.go-runtime-config", "directory": str(runtime),
                "config": config_identity, "health_version": 4,
                "environment": {"OTELC_GO_RUNTIME": str(runtime), "OTELC_GO_CONFIG_SHA256": config_identity["sha256"]}},
            "interpreter": self.intent.interpreter,
            "producer": [files.identity(producer / name) for name in ("go_supervisor.py", "prepared_go.py")],
            "source_complete": False}
        self.response = copy.deepcopy({"schema_version": 1, "kind": "otelc.go.command", "profile": "go-source-v1",
            "request": request, "plan": plan, "prepared": manifest,
            "command": [str(python), "-I", "-S", "-B", str(producer / "go_supervisor.py"), "--runtime", str(runtime)],
            "source_complete": False})
        self.publish()

    def publish(self):
        original, plan, manifest = (self.response[key] for key in ("request", "plan", "prepared"))
        plan["request_sha256"] = digest(original)
        manifest["request_sha256"] = digest(original)
        manifest["plan_sha256"] = digest(plan)
        if manifest["config"] is not None:
            identity = files.identity(self.intent.runtime / "config.json")
            manifest["config"]["config"] = identity
            manifest["config"]["environment"]["OTELC_GO_CONFIG_SHA256"] = identity["sha256"]
        for name, value in zip(prepared.DOCUMENTS, (original, plan, manifest), strict=True):
            private(self.intent.runtime / name, value)

    def test_instrumented_recipe_is_independent_and_never_starts_a_program(self):
        with patch("subprocess.run", side_effect=AssertionError("reader executed producer code")), \
                patch("subprocess.Popen", side_effect=AssertionError("reader started an application")):
            result = prepared.verify(self.response, self.intent)
            result.verify()
        self.assertEqual(len(result.evidence), 4)
        self.assertEqual(result.response["command"], self.response["command"])

    def test_plain_recipe_has_the_stock_binary_and_no_sdk_configuration(self):
        self.intent = replace(self.intent, plain=True)
        (self.intent.runtime / "config.json").unlink()
        self.response["request"]["plain"] = True
        self.response["plan"]["argv"][0] = str(self.intent.build.intent.directory / "plain")
        self.response["plan"]["binary"] = self.intent.build.receipt["plain"]
        self.response["prepared"]["config"] = None
        self.publish()
        self.assertEqual(len(prepared.verify(self.response, self.intent).evidence), 3)
        private(self.intent.runtime / "config.json", self.config)
        with self.assertRaisesRegex(ValueError, "plain Go lane"):
            prepared.verify(self.response, self.intent)

    def test_rehashed_requests_cannot_change_lane_policy_build_arguments_or_identity(self):
        original = copy.deepcopy(self.response)
        values = (("plain", 0), ("schema_version", True), ("runtime", "/another/runtime"),
            ("build", {**original["request"]["build"], "size": True}), ("arguments", ["changed"]),
            ("launch_id", "f" * 31), ("policy", {**self.intent.policy, "languages": ["python"]}), ("unknown", 0))
        for key, value in values:
            self.response = copy.deepcopy(original)
            self.response["request"][key] = value; self.publish()
            with self.subTest(key=key), self.assertRaises(ValueError):
                prepared.verify(self.response, self.intent)
        self.response = original; self.publish()
        prepared.verify(self.response, self.intent)

    def test_rehashed_plans_and_manifests_cannot_replace_the_recipe(self):
        original = copy.deepcopy(self.response)
        values = (("plan", "argv", ["/never-read-or-executed"]), ("plan", "cwd", "/another"),
            ("plan", "source_complete", 0), ("prepared", "producer", []),
            ("prepared", "interpreter", {"path": "/never-read-or-executed"}), ("prepared", "unknown", 0))
        for section, key, value in values:
            self.response = copy.deepcopy(original)
            self.response[section][key] = value; self.publish()
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                prepared.verify(self.response, self.intent)
        self.response = copy.deepcopy(original); self.publish()
        self.response["command"][0] = "/never-read-or-executed"
        with self.assertRaisesRegex(ValueError, "prepare response"):
            prepared.verify(self.response, self.intent)

    def test_rehashed_private_configuration_must_match_each_original_policy_dimension(self):
        original = copy.deepcopy(self.config)
        for key, value in (("collection", 1), ("schema_version", 1), ("http_context", 0), ("functions", []),
                           ("lifetimes", [{"name": "injected", "resource": True}]),
                           ("endpoint", "http://127.0.0.1:1"), ("policy_sha256", "b" * 64), ("unknown", True)):
            self.config = {**original, key: value}
            private(self.intent.runtime / "config.json", self.config); self.publish()
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "configuration differs"):
                prepared.verify(self.response, self.intent)
        private(self.intent.runtime / "config.json", original); self.publish()
        prepared.verify(self.response, self.intent)

    def test_changed_producer_or_retained_metadata_cannot_reuse_acceptance(self):
        result = prepared.verify(self.response, self.intent)
        path = self.intent.runtime / "go-request.json"
        info = path.stat(); os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        with self.assertRaisesRegex(ValueError, "prepared record changed"):
            result.verify()
        result = prepared.verify(self.response, self.intent)
        (self.intent.producer.root / "go_supervisor.py").write_text("changed source\n")
        with self.assertRaisesRegex(ValueError, "frozen Go inputs"):
            result.verify()

    def test_previously_used_runtime_is_only_available_to_explicit_retained_checks(self):
        private(self.intent.runtime / "go-supervisor-start.json", {})
        with self.assertRaisesRegex(ValueError, "already used"):
            prepared.verify(self.response, self.intent)
        prepared.verify(self.response, self.intent, fresh=False)

    def test_metadata_changes_between_decode_and_sealing_are_refused(self):
        original = files.file
        path = self.intent.runtime / "go-prepared.json"
        reads = 0
        def changed(name, *args, **kwargs):
            nonlocal reads
            if name == path:
                reads += 1
                if reads == 2:
                    path.write_bytes(path.read_bytes() + b" ")
            return original(name, *args, **kwargs)
        with patch.object(files, "file", side_effect=changed), self.assertRaisesRegex(ValueError, "changed during independent"):
            prepared.verify(self.response, self.intent)

    def test_malformed_caller_intent_and_nonprivate_runtime_refuse(self):
        values = (replace(self.intent, plain=0), replace(self.intent, arguments=["x"]),
            replace(self.intent, arguments=("bad\0argument",)), replace(self.intent, arguments=("x" * (1024 * 1024 + 1),)),
            replace(self.intent, runtime=self.intent.build.intent.directory),
            replace(self.intent, interpreter={"path": "/another/python"}),
            replace(self.intent, policy={**self.intent.policy, "context": {"tasks": True, "http": False}}))
        for intent in values:
            with self.subTest(intent=intent.arguments), self.assertRaises(ValueError):
                prepared.verify(self.response, intent)
        self.intent.runtime.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "mode0700"):
            prepared.verify(self.response, self.intent)

    def test_common_name_globs_keep_punctuation_literal_and_exclusion_precedence(self):
        name = "example.test/pkg.Box[int].Method"
        self.assertTrue(prepared.name_selected(name, {"include": [name], "exclude": []}))
        self.assertFalse(prepared.name_selected("example.test/pkg.Boxi.Method", {"include": [name], "exclude": []}))
        self.assertTrue(prepared.name_selected(name, {"include": ["*.Box[?nt].*"], "exclude": []}))
        self.assertFalse(prepared.name_selected(name, {"include": ["*"], "exclude": ["*.Method"]}))
        intent = replace(self.intent, policy={**self.intent.policy, "functions": {"include": ["*"], "exclude": ["*.Add"]}})
        with self.assertRaisesRegex(ValueError, "excluded by caller policy"):
            prepared.verify(self.response, intent)


if __name__ == "__main__":
    unittest.main()
