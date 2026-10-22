"""Explicit emitters and public collection capability before application execution."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/generation"), str(ROOT / "examples")]
import generation
import policy
import typescript_provider as provider


def entry(backend="source", collect=True):
    value = {"id": "fixture", "status": "ready", "reason": "", "language": "typescript",
             "otelc_function": "sample.Counter.add", "name": "Counter.add", "path": "sample.mts",
             "typescript_backend": backend, "node_class_label": "sample.Counter",
             "receiver_fixture": {"kind": "constructor"}}
    if collect:
        value["sequence_configuration"] = [{"action": "call", "arguments": "case"}, {"action": "release"},
                                            {"action": "collect", "gc_rounds": 16, "settle_turns": 4}]
    return value


def resolved(value):
    lifetime = {"enabled": True, "boundary": "collection", "include": ["sample.Counter"], "exclude": [], "resources": []}
    if "sequence_configuration" not in value:
        lifetime["enabled"] = False
    return {"schema_version": 2, "language": "typescript", "backend": value["typescript_backend"],
            "execution_available": True, "functions": {"include": [value["otelc_function"]], "exclude": []},
            "traces": {"enabled": True}, "lifetimes": lifetime}


class TypeScriptProviderTests(unittest.TestCase):
    def bind(self, value, response=None, status=0):
        response = resolved(value) if response is None else response
        raw = response if isinstance(response, bytes) else json.dumps(response).encode()
        execute = Mock(return_value=subprocess.CompletedProcess([], status, raw, b""))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with patch.object(provider.capture, "typescript_backend", return_value=value["typescript_backend"]):
                provider.bind(value, folder, folder, {}, execute, generation.policy)
            if execute.called:
                command = execute.call_args.args[0]
                self.assertEqual(command[-5:], ["--language", "typescript", "config", "--json", "--require-supported"])
                self.assertEqual((folder / "typescript-provider/fixture/policy.toml").read_text(), value["typescript_provider"]["request"])
        return execute

    def test_backend_selection_is_explicit_frozen_and_never_guessed(self):
        self.assertEqual(policy.validate({})["adapters"]["typescript"], {"backend": "source"})
        for backend in ("source", "native"):
            config = policy.validate({"adapters": {"typescript": {"backend": backend}}})
            self.assertEqual(config["adapters"]["typescript"]["backend"], backend)
            self.assertIn('backend = "' + backend + '"', generation.policy(entry(backend), "http://127.0.0.1:4318"))
        for value in (True, None, [], "", "compiler", "Native"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy.validate({"adapters": {"typescript": {"backend": value}}})
        with self.assertRaises(ValueError):policy.validate({"adapters": {"typescript": {"unknown": True}}})

    def test_both_emitters_preserve_actual_config_request_response_and_native_call_only(self):
        for backend, collect in (("source", True), ("native", True), ("native", False)):
            with self.subTest(backend=backend, collect=collect):
                value = entry(backend, collect)
                execute = self.bind(value)
                self.assertEqual(execute.call_count, 1)
                self.assertEqual(value["status"], "ready")
                self.assertEqual(value["typescript_provider"]["resolved"], resolved(value))
                self.assertEqual(json.loads(value["typescript_provider"]["stdout"]), resolved(value))

    def test_old_unavailable_or_malformed_capability_is_a_named_prelaunch_blocker(self):
        variants = [b'not-json', b'{"schema_version":2,"schema_version":2}']
        for key, values in {"schema_version": [True, 1, 3], "language": ["javascript"], "backend": ["native"],
                            "execution_available": [False, 1], "functions": [{"include": [], "exclude": []}],
                            "traces": [{}, []], "lifetimes": [{}, {**resolved(entry())["lifetimes"], "include": ["other.Counter"]}]}.items():
            for candidate in values:
                variant = resolved(entry()); variant[key] = candidate; variants.append(variant)
        for response in variants:
            value = entry()
            with self.subTest(response=response):
                self.bind(value, response)
                self.assertEqual(value["status"], "blocked")
                self.assertTrue(value["reason"])
                self.assertNotIn("resolved", value["typescript_provider"])
        value = entry(); self.bind(value, status=1)
        self.assertEqual(value["status"], "blocked")
        self.assertEqual(value["typescript_provider"]["status"], 1)

    def test_unrequested_and_already_blocked_profiles_do_not_query_the_provider(self):
        for change in ({"language": "javascript"}, {"status": "blocked"}, {"status": "excluded"}):
            value = {**entry(), **change}
            self.assertFalse(self.bind(value).called)
        self.assertFalse(self.bind(entry(collect=False)).called)

    def test_missing_native_host_compiler_refuses_before_provider_or_application_launch(self):
        value = entry("native")
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); execute = Mock()
            with patch.object(provider.capture, "typescript_backend", side_effect=ValueError("native compiler unavailable")):
                provider.bind(value, folder, folder, {}, execute, generation.policy)
        self.assertFalse(execute.called)
        self.assertEqual(value["status"], "blocked")
        self.assertIn("compiler unavailable", value["reason"])

    def test_real_inventory_flow_freezes_native_backend_and_its_public_resolver_evidence(self):
        parsed = {"functions": [{"name": "selected", "line": 1, "column": 1, "parameters": ["number"],
                                  "output": "number", "reason": ""}], "globals": [], "parser": "fixture AST"}
        config = policy.validate({"languages": ["typescript"], "adapters": {"typescript": {"backend": "native"}}})
        args = argparse.Namespace(configuration=config, language=["typescript"], cases=1)
        response = resolved({**entry("native", collect=False), "otelc_function": "sample.selected"})
        execute = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(response).encode(), b""))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); (folder / "sample.mts").write_text("function selected(value:number){return value;}")
            with (patch.object(generation.capture, "selected_tools", return_value={"typescript": Path("/fixed/node")}),
                  patch.object(generation.capture, "artefacts", return_value={}),
                  patch.object(generation.discovery, "discover", return_value=copy.deepcopy(parsed)),
                  patch.object(generation.node_project, "inventory_context", return_value={}),
                  patch.object(generation, "execute", execute),
                  patch.object(provider.capture, "typescript_backend", return_value="native")):
                _, _, inventory = generation.inventory_tree({"sample.mts": "a" * 64}, folder, folder, folder, args)
        self.assertEqual(inventory[0]["status"], "ready", inventory[0])
        self.assertEqual(inventory[0]["typescript_backend"], "native")
        self.assertEqual(inventory[0]["typescript_provider"]["resolved"], response)


if __name__ == "__main__":
    unittest.main()
