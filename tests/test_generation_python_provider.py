"""Rebuilt Python metadata cannot substitute for selected-source evidence."""

import copy
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
import generation
import policy
import python_provider as provider


def entry() -> dict:
    return {"language": "python", "python_backend": "prepared", "path": "src/rocket\U0001f680\x7f.py",
            "otelc_function": "src.rocket.add", "name": "add", "id": "selected", "status": "ready"}


def response(value: dict) -> dict:
    return {"policy": value, "implemented": ["java"], "candidates": ["python"],
            "remaining": sorted(provider.SDK_LANGUAGES - {"java"})}


def completed(value, status: int = 0):
    raw = value if type(value) is bytes else json.dumps(value).encode()
    return subprocess.CompletedProcess([], status, raw, b"")


class PythonProviderTests(unittest.TestCase):
    def test_origin_profile_policy_is_explicit_and_never_changes_legacy_defaults(self):
        original = copy.deepcopy(policy.DEFAULTS)
        for profile in (provider.INPUT_PROFILE, provider.ORIGIN_PROFILE):
            configured = policy.validate({'adapters': {'python': {'backend': 'prepared', 'profile': profile}}})
            self.assertEqual(configured['adapters']['python']['profile'], profile)
            self.assertEqual(policy.validate(configured), configured)
        self.assertEqual(policy.validate({}), original)
        for value in ({'profile': provider.ORIGIN_PROFILE}, {'backend': 'legacy', 'profile': provider.INPUT_PROFILE},
                      *({'backend': 'prepared', 'profile': value} for value in (True, None, 'unknown'))):
            with self.subTest(value=value), self.assertRaises(ValueError):
                provider.settings(value)

    def test_origin_protocol_descriptor_cannot_be_selected_by_returned_fields(self):
        provider.verify_protocols(copy.deepcopy(provider.ORIGIN_PROTOCOLS), provider.ORIGIN_PROFILE)
        for value, profile in ((provider.ORIGIN_PROTOCOLS, provider.INPUT_PROFILE),
                               (provider.PROTOCOLS, provider.ORIGIN_PROFILE), (provider.PROTOCOLS, 'unknown')):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                provider.verify_protocols(value, profile)
        for key, values in {'schema_version': [1, True], 'profile': [provider.INPUT_PROFILE, None],
                            'code_comparisons': [1, False], 'source_complete': [True, 0],
                            'origin_scope': ['whole-program', None],
                            'journal': [{'schema_version': 1, 'record_kinds': [1, 2, 3, 4]}]}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    provider.verify_protocols({**provider.ORIGIN_PROTOCOLS, key: value}, provider.ORIGIN_PROFILE)

    def test_origin_probe_has_a_separate_cache_and_literal_explicit_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary); tools = {'python': Path(sys.executable)}
            execute = Mock(side_effect=[completed(provider.PROTOCOLS), completed(provider.ORIGIN_PROTOCOLS)])
            provider.probe_protocols(workspace, workspace, tools, execute)
            for _ in range(2):
                self.assertEqual(provider.probe_protocols(workspace, workspace, tools, execute, provider.ORIGIN_PROFILE),
                                 provider.ORIGIN_PROTOCOLS)
            self.assertEqual(execute.call_count, 2)
            self.assertIn("protocols(profile='python-native-origins-v2')", execute.call_args.args[0][5])
            folder = workspace / provider.DIRECTORY
            original = json.loads((folder / 'protocol/response.json').read_bytes())
            target = folder / 'protocol-origins-v2/response.json'
            target.write_text(json.dumps(original))
            with self.assertRaisesRegex(ValueError, 'protocol probe failed'):
                provider.probe_protocols(workspace, workspace, tools, execute, provider.ORIGIN_PROFILE)

    def test_only_explicit_origin_negotiation_admits_the_frozen_generated_route(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configured = policy.validate({'adapters': {'python': {'backend': 'prepared', 'profile': provider.ORIGIN_PROFILE}}})
            selected = entry()
            generation.configure_entry_context(selected, {}, configured, root, False)
            self.assertEqual(selected['python_profile'], provider.ORIGIN_PROFILE)
            requested = provider.configuration(selected, 'http://127.0.0.1:4318', 'oteleq-python-provider')
            execute = Mock(side_effect=[completed(provider.ORIGIN_PROTOCOLS), completed(response(requested))])
            provider.bind(selected, root, root, {'python': Path(sys.executable)}, execute)
            self.assertEqual(selected['status'], 'ready')
            self.assertEqual(selected['python_provider']['protocols'], provider.ORIGIN_PROTOCOLS)
            provider.refuse_unbound(selected)
            data = {'configuration': configured, 'inventory': [selected],
                    'python_provider_manifest': generation.manifest(root / provider.DIRECTORY)}
            provider.verify_probes(generation, root, data)
            selected['python_profile'] = provider.INPUT_PROFILE
            with self.assertRaisesRegex(ValueError, 'profile differs'):
                provider.verify_probes(generation, root, data)

    def test_origin_requires_frozen_successful_complete_negotiation(self):
        selected = {**entry(), 'python_profile': provider.ORIGIN_PROFILE}
        requested = provider.configuration(selected, 'http://127.0.0.1:4318', 'oteleq-python-provider')
        original = {'status': 0, 'request': provider.policy(selected, 'http://127.0.0.1:4318', 'oteleq-python-provider'),
                    'protocols': copy.deepcopy(provider.ORIGIN_PROTOCOLS),
                    'stdout': json.dumps(response(requested)), 'resolved': response(requested)}
        provider.refuse_unbound({**selected, 'python_provider': original})
        for probe in (None, {}, *({**original, key: value} for key, value in (
                ('status', True), ('status', 1), ('request', 'edited'), ('protocols', provider.PROTOCOLS),
                ('stdout', '{}'), ('stdout', None), ('resolved', {})))):
            with self.subTest(probe=probe), self.assertRaises(ValueError):
                provider.refuse_unbound({**selected, 'python_provider': probe})

    def test_origin_policy_includes_declared_source_factories_and_constructors(self):
        selected = {**entry(), 'python_profile': provider.ORIGIN_PROFILE,
                    'name': 'Counter.add', 'otelc_function': 'app.Counter.add'}
        self.assertIsNone(provider.creator(selected))
        for name in ('Counter.__init__', 'make_counter'):
            chosen = {**selected, 'receiver_fixture': {'source_function': name}}
            self.assertEqual(provider.creator(chosen), 'app.' + name)
            self.assertEqual(provider.configuration(chosen, 'endpoint', 'service')['functions']['include'],
                             ['app.Counter.add', 'app.' + name])
        self.assertIsNone(provider.creator({**selected, 'receiver_fixture': {'source_function': None}}))

    def test_legacy_default_and_explicit_choices_roundtrip_without_shared_values(self):
        self.assertEqual(policy.validate({}), policy.DEFAULTS)
        for backend in ("legacy", "prepared"):
            configured = policy.validate({"adapters": {"python": {"backend": backend, "import_roots": ["src"]}}})
            self.assertEqual(configured["adapters"]["python"], {"backend": backend, "import_roots": ["src"]})
            self.assertEqual(policy.validate(configured), configured)
        for value in (None, [], True, {"unknown": 1}, {"backend": True}, {"backend": "source"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                provider.settings(value)
        self.assertTrue(provider.enabled(entry()))
        self.assertFalse(provider.enabled({**entry(), "language": "java"}))
        self.assertFalse(provider.enabled({**entry(), "python_backend": "legacy"}))

    def test_complete_common_policy_and_literal_unicode_paths(self):
        selected = entry()
        requested = provider.configuration(selected, "http://127.0.0.1:4321", "case")
        self.assertEqual(tomllib.loads(provider.policy(selected, "http://127.0.0.1:4321", "case")), requested)
        self.assertEqual(generation.policy(selected, "http://127.0.0.1:4321", service="case"),
                         provider.policy(selected, "http://127.0.0.1:4321", "case"))
        self.assertEqual(requested["sources"]["include"], [selected["path"]])
        self.assertEqual(requested["context"], {"tasks": False, "http": False})
        with patch.object(provider.sequences, "creator", return_value="src.rocket.Factory.create"):
            self.assertEqual(provider.configuration(selected, "endpoint", "case")["functions"]["include"],
                             [selected["otelc_function"], "src.rocket.Factory.create"])
        with self.assertRaises(ValueError):
            provider.configuration({**selected, "python_backend": "legacy"}, "endpoint", "case")

    def test_protocol_descriptor_has_exact_closed_types_and_current_formats(self):
        provider.verify_protocols(copy.deepcopy(provider.PROTOCOLS))
        values = [None, [], {}, {**provider.PROTOCOLS, "extra": 1}, {**provider.PROTOCOLS, "health": True},
                  {**provider.PROTOCOLS, "source_complete": 0}, {**provider.PROTOCOLS, "code": {"written": 2, "readable": [1, 2]}},
                  {**provider.PROTOCOLS, "journal": {"schema_version": 1, "record_kinds": [1, 2, 3]}}]
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                provider.verify_protocols(value)

    def test_protocol_probe_is_isolated_cached_once_and_bound_to_exact_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            tools = {"python": Path(sys.executable)}
            execute = Mock(return_value=completed(provider.PROTOCOLS))
            for _ in range(2):
                self.assertEqual(provider.probe_protocols(workspace, workspace, tools, execute), provider.PROTOCOLS)
            execute.assert_called_once()
            self.assertEqual(execute.call_args.args[0][:4], [Path(sys.executable), "-I", "-S", "-B"])
            path = workspace / provider.DIRECTORY / "protocol/response.json"
            record = json.loads(path.read_bytes())
            for key, value in (("command", ["foreign"]), ("status", True), ("stdout", []), ("extra", 1)):
                path.write_text(json.dumps({**record, key: value}))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    provider.probe_protocols(workspace, workspace, tools, execute)

    def test_protocol_probe_refuses_invalid_duplicate_nonfinite_and_oversized_metadata(self):
        for value, status in ((b'{"schema_version":1,"schema_version":1}', 0), (b'NaN', 0),
                              (b'invalid', 0), (provider.PROTOCOLS, 1), (b' ' * provider.MAX_METADATA, 0)):
            with tempfile.TemporaryDirectory() as temporary, self.subTest(value=str(value)[:60]):
                folder = Path(temporary)
                with self.assertRaises(ValueError):
                    provider.probe_protocols(folder, folder, {"python": Path(sys.executable)}, Mock(return_value=completed(value, status)))

    def test_cached_protocol_refuses_file_and_parent_symlinks_and_oversized_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace, outside = root / "workspace", root / "outside"
            workspace.mkdir(); outside.mkdir()
            tools, execute = {"python": Path(sys.executable)}, Mock()
            linked = workspace / provider.DIRECTORY
            linked.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "linked protocol"):
                provider.probe_protocols(root, workspace, tools, execute)
            linked.unlink(); linked.mkdir()
            folder = linked / "protocol"
            folder.mkdir()
            receipt = folder / "response.json"
            receipt.symlink_to(outside / "absent")
            with self.assertRaisesRegex(ValueError, "invalid cached"):
                provider.probe_protocols(root, workspace, tools, execute)
            receipt.unlink(); receipt.write_bytes(b" " * (provider.MAX_METADATA + 1))
            with self.assertRaisesRegex(ValueError, "invalid cached"):
                provider.probe_protocols(root, workspace, tools, execute)
            execute.assert_not_called()

    def test_complete_capabilities_preserve_candidate_and_refuse_partial_or_edited_policy(self):
        requested = provider.configuration(entry(), "endpoint", "service")
        valid = response(requested)
        provider.verify_capabilities(valid, requested)
        invalid = [None, [], {}, {**valid, "extra": 1}, {**valid, "implemented": ["java", "java"]},
                   {**valid, "remaining": ["java"]}, {**valid, "candidates": ["java"]},
                   {**valid, "candidates": []}, {**valid, "candidates": [True]}, {**valid, "remaining": "python"}]
        changed = copy.deepcopy(valid)
        changed["policy"]["metrics"]["collection"] = 1
        invalid.append(changed)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                provider.verify_capabilities(value, requested)

    def test_actual_selection_and_metadata_cannot_admit_an_unbound_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = entry()
            requested = provider.configuration(selected, "http://127.0.0.1:4318", "oteleq-python-provider")
            execute = Mock(side_effect=[completed(provider.PROTOCOLS), completed(response(requested))])
            provider.bind(selected, root, root, {"python": Path(sys.executable)}, execute)
            self.assertEqual(selected["status"], "blocked")
            self.assertIn(provider.ORIGIN_UNAVAILABLE, selected["reason"])
            self.assertEqual(selected["python_provider"]["resolved"], response(requested))
            self.assertEqual(execute.call_count, 2)
            command = execute.call_args.args[0]
            self.assertEqual(command[:4], [Path(sys.executable), "-I", "-S", "-B"])
            self.assertEqual(command[4], root / "otelc/cli_bootstrap.py")
            self.assertEqual(command[-1], "plan")
            execute.reset_mock()
            provider.bind(selected, root, root, {}, execute)
            execute.assert_not_called()

    def test_failed_public_probes_remain_visible_and_never_fall_back(self):
        for value, status in (({}, 0), (b'bad json', 0), ({}, 1)):
            with tempfile.TemporaryDirectory() as temporary:
                root, selected = Path(temporary), entry()
                execute = Mock(side_effect=[completed(provider.PROTOCOLS), completed(value, status)])
                provider.bind(selected, root, root, {"python": Path(sys.executable)}, execute)
                self.assertEqual(selected["status"], "blocked")
                self.assertNotIn("resolved", selected["python_provider"])
        execute = Mock()
        provider.bind({**entry(), "python_backend": "legacy"}, Path("."), Path("."), {}, execute)
        execute.assert_not_called()

    def test_context_seal_ownership_and_frozen_backend_are_rechecked(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            provider.verify_probes(generation, workspace, {})
            root = workspace / provider.DIRECTORY
            root.mkdir(); (root / "probe").write_text("sealed")
            with self.assertRaisesRegex(ValueError, "unowned"):
                provider.verify_probes(generation, workspace, {})
            data = {"python_provider_manifest": generation.manifest(root)}
            provider.verify_probes(generation, workspace, data)
            (root / "probe").write_text("changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                provider.verify_probes(generation, workspace, data)
            configuration = policy.validate({"adapters": {"python": {"backend": "prepared"}}})
            for selected in (entry(), {**entry(), "python_backend": "legacy", "status": "blocked"}):
                with self.assertRaises(ValueError):
                    provider.verify_probes(generation, workspace, {"configuration": configuration, "inventory": [selected]})

    def test_attempt_barrier_prevents_direct_legacy_launch_and_export_retains_probes(self):
        provider.refuse_unbound({"language": "python"})
        with tempfile.TemporaryDirectory() as temporary, patch.object(generation.java_launch, "runtime") as launch:
            folder = Path(temporary) / "attempt"
            with self.assertRaisesRegex(ValueError, "origin bindings"):
                generation.attempt(Path(temporary), {"configuration": policy.validate({})}, entry(), {}, "baseline", folder, None)
            launch.assert_not_called()
            self.assertFalse(folder.exists())
        self.assertEqual(generation.retained_provider_directories({"python_provider_manifest": {}}), [provider.DIRECTORY])

    def test_entry_context_and_tool_selection_remain_explicit(self):
        configured = policy.validate({"adapters": {"python": {"backend": "prepared"}}})
        selected = {"language": "python", "path": "sample.py"}
        generation.configure_entry_context(selected, {}, configured, Path("."), False)
        self.assertTrue(provider.enabled(selected))
        with patch.object(generation.capture, "selected_tools", return_value={"python": Path(sys.executable)}), \
             patch.object(generation.python_inputs, "artefacts", return_value={"input": "digest"}) as inputs:
            self.assertEqual(generation.discovery_tools(Path("."), "python", configured["adapters"])[1], {"input": "digest"})
            generation.provider_stable(Path("."), "python", {"python": Path(sys.executable)}, {"input": "digest"}, selected)
            with self.assertRaisesRegex(ValueError, "inputs changed"):
                generation.provider_stable(Path("."), "python", {}, {}, selected)
            self.assertEqual(inputs.call_count, 3)
