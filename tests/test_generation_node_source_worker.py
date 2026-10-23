"""The fixed Node supervisor preserves channels, process ownership and failures."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import node_source_worker as worker


class NodeSourceWorkerTests(unittest.TestCase):
    def test_receipts_publish_complete_private_bytes_and_preserve_existing_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();filename = root / 'receipt.json'
            value = {"pid": 101, "data": "x" * 100000}
            real_link = os.link
            def publish(staged, destination, **options):
                self.assertFalse(filename.exists())
                self.assertEqual(json.loads(Path(staged).read_bytes()), value)
                self.assertEqual(Path(staged).stat().st_mode & 0o777, 0o600)
                return real_link(staged, destination, **options)
            with patch.object(worker.os, 'link', side_effect=publish):
                worker.write(filename, value)
            self.assertEqual(json.loads(filename.read_bytes()), value)
            self.assertEqual(filename.stat().st_mode & 0o777, 0o600)
            self.assertFalse(list(root.glob('*.staging')))
            with self.assertRaises(FileExistsError):
                worker.write(filename, {"changed": True})
            self.assertEqual(json.loads(filename.read_bytes()), value)
            self.assertFalse(list(root.glob('*.staging')))
            staged = root / 'other.json.staging';staged.write_text('preserve unknown data')
            with self.assertRaises(FileExistsError):
                worker.write(root / 'other.json', {})
            self.assertEqual(staged.read_text(), 'preserve unknown data')
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        original_path = sys.path.copy()
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), original_path))
        self.counter = 0

    def fixture(self, plain=False):
        self.counter += 1
        folder = self.root / str(self.counter)
        folder.mkdir()
        project = folder / "project"
        project.mkdir()
        entry = project / "app.cjs"
        entry.write_text("function add(value){return value+1;}\n")
        provider = self.root / "provider"
        provider.mkdir(exist_ok=True)
        value = {"schema_version": 1, "provider": str(provider), "project": str(project),
                 "entry": str(entry), "runtime": str(folder / "node-runtime"),
                 "policy": str(folder / "policy.toml"), "node": str(self.root / "node"),
                 "language": "javascript", "compiler": "native", "plain": plain,
                 "gc_fixture": False, "timeout_ms": 60000}
        path = folder / "node-source-request.json"
        path.write_text(json.dumps(value))
        return folder, path, value

    def test_request_requires_exact_types_paths_and_new_external_runtime(self):
        folder, path, value = self.fixture()
        with patch.object(worker.Path, "cwd", return_value=Path(value["project"])):
            self.assertEqual(worker.request(path), value)
            variants = [{**value, "extra": True}, {**value, "schema_version": True},
                        {**value, "node": "node"}, {**value, "node": None},
                        {**value, "language": []}, {**value, "compiler": []},
                        {**value, "plain": 1}, {**value, "gc_fixture": 0},
                        {**value, "timeout_ms": False}, {**value, "timeout_ms": 0},
                        {**value, "entry": str(path)}, {**value, "project": str(folder)},
                        {**value, "policy": str(self.root / "policy.toml")},
                        {**value, "runtime": str(folder / "another-runtime")},
                        {**value, "provider": str(folder)}]
            for changed in variants:
                path.write_text(json.dumps(changed))
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    worker.request(path)
            path.write_text(json.dumps(value))
            Path(value["runtime"]).symlink_to(folder / "absent")
            with self.assertRaises(ValueError):
                worker.request(path)
            Path(value["runtime"]).unlink()
            with self.assertRaisesRegex(ValueError, "fixed run filename"):
                worker.request(folder / "another-request.json")
            entry = Path(value["entry"])
            entry.unlink()
            entry.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "regular canonical"):
                worker.request(path)
            entry.unlink()
            entry.write_text("function add(value){return value+1;}\n")
            path.write_text('{"schema_version":1,"schema_version":1}')
            with self.assertRaises(ValueError):
                worker.request(path)
            path.write_bytes(b" " * (1024 * 1024 + 1))
            with self.assertRaises(ValueError):
                worker.request(path)

    def test_fixed_argv_distinguishes_plain_js_compiled_ts_and_explicit_gc(self):
        _, _, value = self.fixture(plain=True)
        self.assertEqual(worker.expected_argv(value), [value["node"], "--enable-source-maps", value["entry"]])
        for language, plain, prefix in (("typescript", True, "node-plain"), ("javascript", False, "node")):
            requested = {**value, "language": language, "plain": plain, "gc_fixture": True}
            self.assertEqual(worker.expected_argv(requested), [value["node"], "--enable-source-maps", "--expose-gc",
                "--require", str(Path(value["runtime"]) / (prefix + "-bootstrap.cjs")), value["entry"]])

    def test_loaded_provider_location_rejects_an_alias_into_the_runtime_parent(self):
        folder, _, value = self.fixture()
        physical = folder / "otelc/node.py"
        physical.parent.mkdir()
        physical.write_text("# Isolated provider-origin fixture.\n")
        alias = self.root / "sdk-alias"
        alias.symlink_to(folder, target_is_directory=True)
        module = types.SimpleNamespace(__file__=str(alias / "otelc/node.py"))
        with self.assertRaisesRegex(ValueError, "loaded provider"):
            worker.provider_boundary(Path(value["runtime"]), module)

    def test_cli_accepts_only_the_fixed_run_request_and_no_argument_override(self):
        folder, path, value = self.fixture()
        path.write_text('{}')
        script = ("import runpy,sys;sys.path[:0]=" + repr([str(REPO / "adapters/generation"), str(REPO / "examples")])
                  + ";runpy.run_module('node_source_worker',run_name='__main__')")
        for args, message in (([], b"invalid supervisor request fields"), (["override.json"], b"no command-line request override")):
            result = subprocess.run([sys.executable, "-I", "-B", "-c", script, *args],
                                    cwd=value["project"], capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)
            self.assertFalse((folder / "node-source-application.json").exists())

    def test_sdk_exit_requires_actual_termination_and_owned_process_group(self):
        for sdk in (None, True, 1, 100):
            with self.subTest(sdk=sdk), self.assertRaises(ValueError):
                worker.wait_sdk_exit({"sdk_pid": sdk}, 100, 10)
        with patch.object(worker.os, "getpgid", side_effect=ProcessLookupError):
            worker.wait_sdk_exit({"sdk_pid": 101}, 100, 10)
        with patch.object(worker.os, "getpgid", return_value=2), patch.object(worker.os, "getpgrp", return_value=1):
            with self.assertRaisesRegex(ValueError, "escaped"):
                worker.wait_sdk_exit({"sdk_pid": 101}, 100, 10)
        with patch.object(worker.os, "getpgid", return_value=1), patch.object(worker.os, "getpgrp", return_value=1), \
                patch.object(worker.time, "monotonic", return_value=11):
            with self.assertRaises(TimeoutError):
                worker.wait_sdk_exit({"sdk_pid": 101}, 100, 10)
        with patch.object(worker.os, "getpgid", side_effect=[1, ProcessLookupError]), \
                patch.object(worker.os, "getpgrp", return_value=1), \
                patch.object(worker.time, "monotonic", return_value=0), patch.object(worker.time, "sleep") as sleep:
            worker.wait_sdk_exit({"sdk_pid": 101}, 100, 10)
            sleep.assert_called_once_with(.01)

    def test_receipts_are_private_and_existing_evidence_is_never_replaced(self):
        path = self.root / "receipt.json"
        worker.write(path, {"actual": 7})
        self.assertEqual(json.loads(path.read_text()), {"actual": 7})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            worker.write(path, {"actual": 8})
        self.assertEqual(json.loads(path.read_text()), {"actual": 7})
        with patch.object(worker.time, "monotonic", return_value=5):
            self.assertEqual(worker.remaining(10), 5)
            with self.assertRaises(TimeoutError):
                worker.remaining(5)

    def exercise(self, *, plain=False, changed_argv=False, phase="closed", verified=True, app_pid=101,
                 timeout=False, result=0, source_version=5, protocol_source=5):
        folder, _, value = self.fixture(plain)
        package = types.ModuleType("otelc")
        config, node, provenance = (types.ModuleType("otelc." + name) for name in ("config", "node", "node_provenance"))
        module_path = Path(value["provider"]) / "otelc/node.py"
        module_path.parent.mkdir(exist_ok=True)
        module_path.write_text("# Fixed module origin for this protocol fixture.\n")
        node.__file__ = str(module_path)
        config.Policy = Mock()
        report = {"pid": app_pid, "sdk_pid": 102, "phase": phase}
        node.wait_report = Mock(return_value=report)
        node.protocols = Mock(return_value={**worker.node_source.PROTOCOLS, "source": protocol_source})

        def verify_inputs(runtime, manifest):
            if not plain:
                self.assertTrue((runtime / "node-events.fifo").is_fifo())
            return verified

        def exited_sdk(process_id):
            self.assertEqual(process_id, 102)
            self.assertTrue((Path(value["runtime"]) / "node-events.fifo").is_fifo())
            raise ProcessLookupError

        provenance.finish = Mock(side_effect=verify_inputs)

        def prepare(*args, **kwargs):
            runtime = Path(value["runtime"])
            runtime.mkdir()
            prefix = "node-plain" if plain else "node"
            (runtime / (prefix + "-launch.json")).write_text(json.dumps({"schema_version": source_version, "launch_id": "case"}))
            if not plain:
                os.mkfifo(runtime / "node-events.fifo", 0o600)
            return worker.expected_argv(value) + (["changed"] if changed_argv else [])

        node.command = Mock(side_effect=prepare)
        package.config, package.node, package.node_provenance = config, node, provenance
        modules = {"otelc": package, "otelc.config": config, "otelc.node": node, "otelc.node_provenance": provenance}
        application = Mock(pid=101)
        application.wait.return_value = result
        application.poll.return_value = result
        if timeout:
            application.wait.side_effect = [subprocess.TimeoutExpired([], 1), 0]
            application.poll.return_value = None
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {}, clear=False), \
                patch.object(worker.subprocess, "Popen", return_value=application) as launch, \
                patch.object(worker.os, "getpgid", side_effect=exited_sdk):
            if protocol_source != 5:
                with self.assertRaisesRegex(ValueError, "protocols are unavailable"):
                    worker.run(value, folder)
                node.command.assert_not_called()
                launch.assert_not_called()
            elif source_version != 5:
                with self.assertRaisesRegex(ValueError, "evidence version differs"):
                    worker.run(value, folder)
                launch.assert_not_called()
            elif changed_argv:
                with self.assertRaisesRegex(ValueError, "fixed Node recipe"):
                    worker.run(value, folder)
                launch.assert_not_called()
            elif timeout:
                with self.assertRaises(subprocess.TimeoutExpired):
                    worker.run(value, folder)
                application.kill.assert_called_once()
            elif app_pid != 101 or not verified or phase != "closed":
                with self.assertRaises(ValueError):
                    worker.run(value, folder)
            else:
                self.assertEqual(worker.run(value, folder), result)
                launch.assert_called_once_with(worker.expected_argv(value))
                receipt = json.loads((folder / "node-source-completion.json").read_text())
                self.assertEqual(receipt["application_pid"], 101)
                self.assertEqual(receipt["application_returncode"], result)
                self.assertEqual(receipt["sdk_pid"], None if plain else 102)
                self.assertIs(receipt["sdk_exited"], None if plain else True)
                self.assertEqual(json.loads((folder / "node-source-application-exit.json").read_text()),
                                 {"pid": 101, "returncode": result})
                provenance.finish.assert_called_once()
                if plain:
                    node.wait_report.assert_not_called()
                else:
                    node.wait_report.assert_called_once()
                    self.assertFalse((Path(value["runtime"]) / "node-events.fifo").exists())
                    transport = json.loads((folder / "node-source-transport.json").read_text())
                    self.assertEqual(transport["sdk_pid"], 102)
                    self.assertTrue(transport["removed_after_sdk_exit"])

    def test_transport_cleanup_requires_a_private_fifo_and_preserves_other_files(self):
        folder, _, value = self.fixture()
        runtime = Path(value["runtime"])
        runtime.mkdir()
        endpoint = runtime / "node-events.fifo"
        endpoint.write_text("retained regular evidence")
        with self.assertRaisesRegex(ValueError, "private FIFO"):
            worker.close_transport(runtime, folder, 102)
        self.assertEqual(endpoint.read_text(), "retained regular evidence")
        endpoint.unlink()
        endpoint.symlink_to(folder / "absent")
        with self.assertRaisesRegex(ValueError, "private FIFO"):
            worker.close_transport(runtime, folder, 102)
        self.assertTrue(endpoint.is_symlink())

    def test_plain_and_instrumented_launches_keep_real_process_receipts(self):
        self.exercise(plain=True)
        self.exercise(result=42)

    def test_changed_public_recipe_cannot_launch_an_application(self):
        self.exercise(changed_argv=True)

    def test_old_protocol_or_mismatched_prepared_version_cannot_launch_an_application(self):
        self.exercise(protocol_source=4)
        self.exercise(source_version=4)

    def test_sdk_and_source_failures_do_not_turn_into_success(self):
        self.exercise(phase="failed")
        self.exercise(verified=False)
        self.exercise(app_pid=999)

    def test_application_timeout_still_reaps_the_application(self):
        self.exercise(timeout=True)
