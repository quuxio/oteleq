"""Rebuilt Node selection, common policy and installed closure refuse drift."""

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import node_source as provider
import generation
import policy


def entry(language: str = "typescript") -> dict:
    return {"language": language, "node_backend": provider.SOURCE,
            "path": "src/rocket\U0001f680\x7f/App.mts", "otelc_function": "src.App.add"}


def response(requested: dict) -> dict:
    return {"policy": copy.deepcopy(requested), "implemented": ["java"],
            "candidates": ["javascript", "typescript"],
            "remaining": sorted(provider.SDK_LANGUAGES - {"java"})}


def fake_provider(root: Path) -> dict[str, Path]:
    names = ["package.json", "package-lock.json", "otelc/config.py", "otelc/node.py",
             "otelc/node_recipe.py", "otelc/node_provenance.py", "otelc/node_preloads.py",
             "adapters/node/src/source-bootstrap.ts", "adapters/node/src/plain-source-loader.ts",
             "node_modules/typescript-api/typescript.js", "build/tools/otelc_node_observer-24.0.0.node",
             "node"]
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    return {"javascript": root / "node"}


class NodeSourceTests(unittest.TestCase):
    def test_protocol_descriptor_is_closed_typed_and_required_before_any_application(self) -> None:
        provider.verify_protocols(provider.PROTOCOLS.copy())
        for value in (None, {}, {**provider.PROTOCOLS, "extra": 1}, {**provider.PROTOCOLS, "source": 4},
                      {**provider.PROTOCOLS, "execution": True}, {**provider.PROTOCOLS, "kind": "other"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                provider.verify_protocols(value)
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            tools = {"python-host": Path(sys.executable)}
            execute = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(provider.PROTOCOLS).encode(), stderr=b""))
            self.assertEqual(provider.probe_protocols(workspace, workspace, tools, execute), provider.PROTOCOLS)
            self.assertEqual(provider.probe_protocols(workspace, workspace, tools, execute), provider.PROTOCOLS)
            execute.assert_called_once()
            self.assertEqual(execute.call_args.args[0][:3], [Path(sys.executable), "-I", "-B"])
            path = workspace / provider.DIRECTORY / "protocol/response.json"
            document = json.loads(path.read_bytes())
            document["command"] = ["unrelated provider"]
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "protocol probe failed"):
                provider.probe_protocols(workspace, workspace, tools, execute)

    def test_project_policy_freezes_new_provider_and_refuses_conflicting_emitter(self) -> None:
        configured = policy.validate({"adapters": {"node": {"backend": "source-v1", "typescript_compiler": "api"}}})
        self.assertEqual(configured["adapters"]["node"], {"backend": "source-v1", "typescript_compiler": "api"})
        self.assertNotIn("node", policy.validate({})["adapters"])
        with self.assertRaisesRegex(ValueError, "legacy TypeScript backend"):
            policy.validate({"adapters": {"node": {"backend": "source-v1"}, "typescript": {"backend": "native"}}})

    def test_public_probe_is_config_only_and_failed_candidates_remain_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            tools = {"javascript": Path(sys.executable), "python-host": Path(sys.executable)}
            value = {**entry("javascript"), "id": "selected", "status": "ready"}
            requested = provider.configuration(value, "http://127.0.0.1:4318", "oteleq-node-provider")
            execute = Mock(side_effect=[SimpleNamespace(returncode=0, stdout=provider.json.dumps(provider.PROTOCOLS).encode(), stderr=b""),
                                       SimpleNamespace(returncode=0, stdout=provider.json.dumps(response(requested)).encode(), stderr=b""),
                                       SimpleNamespace(returncode=1, stdout=b"", stderr=b"unavailable")])
            provider.bind(value, root, root, tools, execute)
            self.assertEqual(value["node_provider"]["resolved"], response(requested))
            self.assertEqual(value["status"], "ready")
            self.assertEqual(value["node_provider"]["protocols"], provider.PROTOCOLS)
            self.assertEqual(execute.call_count, 2)
            self.assertEqual(execute.call_args.args[0][-1], "plan")
            self.assertEqual(execute.call_args.args[0][:3], [Path(sys.executable), "-B", "-m"])
            blocked = {**entry("javascript"), "id": "blocked", "status": "ready"}
            provider.bind(blocked, root, root, tools, execute)
            self.assertEqual(blocked["status"], "blocked")
            self.assertIn("public configuration probe failed", blocked["reason"])
            execute.reset_mock()
            provider.bind(blocked, root, root, tools, execute)
            execute.assert_not_called()

    def test_provider_context_seal_refuses_missing_edited_and_unowned_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            provider.verify_probes(generation, workspace, {})
            folder = workspace / provider.DIRECTORY
            folder.mkdir()
            with self.assertRaisesRegex(ValueError, "unowned"):
                provider.verify_probes(generation, workspace, {})
            record = folder / "probe.json"
            record.write_text("fixed evidence")
            data = {"node_provider_manifest": generation.manifest(folder)}
            provider.verify_probes(generation, workspace, data)
            record.write_text("edited")
            with self.assertRaisesRegex(ValueError, "changed"):
                provider.verify_probes(generation, workspace, data)
            record.unlink()
            folder.rmdir()
            with self.assertRaisesRegex(ValueError, "changed"):
                provider.verify_probes(generation, workspace, data)

    def test_resealed_entry_cannot_switch_compiler_provider_or_case_budget(self) -> None:
        configuration = policy.validate({"adapters": {"node": {"backend": "source-v1"}}})
        selected = {**entry(), "node_compiler": "native", "node_timeout_ms": 60000}
        data = {"configuration": configuration, "inventory": [selected]}
        provider.verify_entry_settings(data)
        for key, value in (("node_compiler", "api"), ("node_backend", "legacy"), ("node_timeout_ms", 120000), ("node_timeout_ms", True)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                provider.verify_entry_settings({**data, "inventory": [{**selected, key: value}]})
        empty = policy.validate({})
        with self.assertRaisesRegex(ValueError, "entry provider"):
            provider.verify_entry_settings({"configuration": empty, "inventory": [selected]})

    def test_provider_and_compiler_choices_are_explicit(self) -> None:
        self.assertEqual(provider.settings({}), {"backend": "legacy"})
        self.assertEqual(provider.settings({"backend": provider.SOURCE}),
                         {"backend": provider.SOURCE, "typescript_compiler": "native"})
        self.assertEqual(provider.settings({"backend": provider.SOURCE, "typescript_compiler": "api"}),
                         {"backend": provider.SOURCE, "typescript_compiler": "api"})
        for value in (None, [], True, {"unknown": 1}, {"backend": True}, {"backend": "source"},
                      {"typescript_compiler": "native"}, {"backend": provider.SOURCE, "typescript_compiler": False}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                provider.settings(value)
        self.assertTrue(provider.enabled(entry()))
        self.assertTrue(provider.enabled(entry("javascript")))
        self.assertFalse(provider.enabled(entry("java")))
        self.assertFalse(provider.enabled({**entry(), "node_backend": "legacy"}))

    def test_complete_common_policy_preserves_unicode_and_control_paths(self) -> None:
        for language in ("javascript", "typescript"):
            value = entry(language)
            requested = provider.configuration(value, "http://127.0.0.1:4321", "case")
            text = provider.policy(value, "http://127.0.0.1:4321", "case")
            self.assertEqual(tomllib.loads(text), requested)
            self.assertIn("\\u007f", text)
            self.assertNotIn("\x7f", text)
            self.assertEqual(requested["context"], {"tasks": False, "http": False})
            self.assertEqual(requested["functions"], {"include": [value["otelc_function"]], "exclude": []})
            self.assertEqual(requested["languages"], [language])
        legacy = {**entry(), "node_backend": "legacy"}
        with self.assertRaises(ValueError):
            provider.configuration(legacy, "endpoint", "service")

    def test_live_schedule_freezes_requested_startup_flags_in_the_common_policy(self) -> None:
        for language in ("javascript", "typescript"):
            for collection in (False, True):
                for emission in (False, True):
                    with self.subTest(language=language, collection=collection, emission=emission):
                        initial = {"collection": collection, "emission": emission}
                        value = {**entry(language), "sequence_configuration": [
                            {"action": "call", "metrics": initial.copy()},
                            {"action": "call", "metrics": {"collection": True, "emission": True}},
                        ]}
                        requested = provider.configuration(value, "endpoint", "service")
                        self.assertEqual({key: requested["metrics"][key] for key in initial}, initial)
                        self.assertEqual(tomllib.loads(provider.policy(value, "endpoint", "service")), requested)
                        requested["metrics"]["collection"] = not collection
                        self.assertEqual(value["sequence_configuration"][0]["metrics"], initial)
            ordinary = provider.configuration(entry(language), "endpoint", "service")
            self.assertTrue(ordinary["metrics"]["collection"])
            self.assertTrue(ordinary["metrics"]["emission"])

    def test_candidate_response_is_preserved_without_promoting_other_languages(self) -> None:
        requested = provider.configuration(entry(), "endpoint", "service")
        value = response(requested)
        original = copy.deepcopy(value)
        provider.verify_capabilities(value, requested, "typescript")
        self.assertEqual(value, original)
        value["implemented"].append("typescript")
        value["remaining"].remove("typescript")
        value["candidates"].remove("typescript")
        provider.verify_capabilities(value, requested, "typescript")

    def test_public_response_refuses_missing_unknown_and_overlapping_claims(self) -> None:
        requested = provider.configuration(entry(), "endpoint", "service")
        variants = [None, {}, {**response(requested), "extra": True}]
        for key in ("policy", "implemented", "candidates", "remaining"):
            value = response(requested)
            del value[key]
            variants.append(value)
        for key in ("implemented", "candidates", "remaining"):
            for items in (None, "typescript", [False], ["unknown"], ["java", "java"]):
                variants.append({**response(requested), key: items})
        variants += [{**response(requested), "remaining": sorted(provider.SDK_LANGUAGES)},
                     {**response(requested), "candidates": ["java"]},
                     {**response(requested), "candidates": []}]
        changed = response(requested)
        changed["policy"]["context"]["tasks"] = 0
        variants.append(changed)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                provider.verify_capabilities(value, requested, "typescript")
        unsupported = response(requested)
        with self.assertRaises(ValueError):
            provider.verify_capabilities(unsupported, requested, "go")

    def test_closure_records_source_dependencies_products_and_file_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = fake_provider(root)
            link = root / "node_modules/alias.js"
            link.symlink_to("typescript-api/typescript.js")
            expected = provider.artefacts(root, tools)
            self.assertIn("link-target:node_modules/alias.js", expected)
            self.assertIn("tool:javascript", expected)
            duplicate = root / "node_modules/typescript-api/copy.js"
            duplicate.write_bytes(link.read_bytes())
            before = provider.artefacts(root, tools)
            link.unlink()
            link.symlink_to("typescript-api/copy.js")
            after = provider.artefacts(root, tools)
            self.assertEqual(before["node_modules/alias.js"], after["node_modules/alias.js"])
            self.assertNotEqual(before["link-target:node_modules/alias.js"],
                                after["link-target:node_modules/alias.js"])
            duplicate.write_text("changed dependency")
            self.assertNotEqual(after, provider.artefacts(root, tools))

    def test_missing_sources_observers_and_nonregular_inputs_refuse(self) -> None:
        for relative in ("package.json", "otelc/node.py", "build/tools/otelc_node_observer-24.0.0.node"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                tools = fake_provider(root)
                (root / relative).unlink()
                with self.assertRaises((ValueError, OSError)):
                    provider.artefacts(root, tools)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = fake_provider(root)
            os.mkfifo(root / "node_modules/pipe")
            with self.assertRaisesRegex(ValueError, "non-regular"):
                provider.artefacts(root, tools)

    def test_linked_directories_and_escaped_file_links_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "provider"
            root.mkdir()
            tools = fake_provider(root)
            outside = root.parent / "outside.js"
            outside.write_text("dependency")
            link = root / "node_modules/alias.js"
            link.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "escapes"):
                provider.artefacts(root, tools)
            link.unlink()
            link.symlink_to(root / "otelc", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "linked provider directory"):
                provider.artefacts(root, tools)
            with self.assertRaisesRegex(ValueError, "missing or linked"):
                provider.provider_files(root / "absent")

    def test_directory_inspection_errors_are_not_empty_success(self) -> None:
        def unreadable(directory, onerror):
            onerror(PermissionError("denied"))
        with tempfile.TemporaryDirectory() as temporary, patch.object(provider.os, "walk", unreadable):
            with self.assertRaisesRegex(PermissionError, "denied"):
                provider.provider_files(Path(temporary))
