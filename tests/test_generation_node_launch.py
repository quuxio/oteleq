"""Consumer-owned intent and real-receipt validation refuse protocol substitution."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import node_launch as launch
import node_source as provider
import node_source_worker as worker
from test_generation_node_source import fake_provider


class NodeLaunchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "provider"
        self.root.mkdir()
        self.tools = fake_provider(self.root)
        self.tools["python-host"] = Path(sys.executable)
        self.folder = self.base / "attempt"
        self.folder.mkdir()
        self.project = self.folder / "project"
        self.project.mkdir()
        self.source = self.project / "app.cjs"
        self.source.write_text("function add(value){return value+1;}\n")
        self.entry = {"language": "javascript", "node_backend": provider.SOURCE, "node_compiler": "native",
                      "node_timeout_ms": 60000, "path": "app.cjs", "otelc_function": "app.add",
                      "node_context": {"format": "commonjs", "node_version": "v24.0.0"}}
        self.config = self.folder / "policy.toml"
        self.config.write_text(provider.policy(self.entry, "http://127.0.0.1:4318", "case"))
        self.environment = {"TMPDIR": str(self.folder), "LANG": "C.UTF-8"}

    def fixture(self, plain=False):
        """Construct protocol unit fixtures without claiming actual SDK execution."""
        lane = "baseline" if plain else "instrumented_on"
        command = launch.command(self.root, self.project, self.entry, self.tools, self.folder, lane, self.environment)
        value = launch.read(self.folder / launch.REQUEST_FILE)
        runtime = Path(value["runtime"])
        runtime.mkdir(mode=0o700)
        prefix = "node-plain" if plain else "node"
        original = launch.expected_original(value, provider.configuration(self.entry, "http://127.0.0.1:4318", "case"),
                                            launch.environment_records(self.environment))
        plan = launch.expected_plan(original, "a" * 32)
        worker.write(runtime / (prefix + "-request.json"), original)
        if not plain:
            worker.write(runtime / "node-plan.json", plan)
            bootstrap = ('process.env.OTELC_NODE_PLAN = ' + json.dumps(str(runtime / 'node-plan.json')) + ';\nrequire('
                         + json.dumps(str(self.root / 'adapters/node/src/source-bootstrap.ts')) + ');\n')
            (runtime / "node-bootstrap.cjs").write_text(bootstrap)
        generated = launch.generated_files(self.root, runtime, value, original, plan)
        groups = {"launcher": provider.provider_files(self.root / "otelc", suffix=".py")}
        if not plain:
            groups.update(adapter=provider.provider_files(self.root / "adapters/node/src"),
                          packages=provider.provider_files(self.root / "node_modules"),
                          package_metadata=[self.root / "package.json", self.root / "package-lock.json"],
                          observer=[self.root / "build/tools/otelc_node_observer-24.0.0.node"])
        tooling = {key: [launch.file_identity(p) for p in (sorted(paths, key=str) if key in ("launcher", "adapter", "packages") else paths)]
                   for key, paths in groups.items()}
        manifest = {"schema_version": 5, "request": original, "preloads": {"schema_version": 1,
                    "argv": None, "entries": [], "gaps": [], "requests": [], "resolution_flags": [],
                    "coverage": "resolved_entries_and_nearest_package_context", "cwd": str(self.project)},
                    "launch_id": "a" * 32, "language": "javascript", "backend": "native", "plain": plain,
                    "root": str(self.project), "argv": worker.expected_argv(value), "cwd": str(self.project),
                    "launcher_pid": 100, "node": launch.file_identity(self.tools["javascript"]),
                    "runtime": {"version": "24.0.0", "abi": "137", "architecture": "arm64", "platform": "darwin"},
                    "entry": launch.file_identity(self.source), "plan_sha256": launch.capture.digest(json.dumps(plan, sort_keys=True).encode()),
                    "resolved_plan": plan, "tooling_environment": original["environment"], "ambient_sha256": {},
                    "tooling": tooling, "generated": generated, "entry_context": []}
        manifest_path = runtime / (prefix + "-launch.json")
        worker.write(manifest_path, manifest)
        worker.write(self.folder / "process.json", {"pid": 100, "argv": list(map(str, command))})
        worker.write(self.folder / "node-source-application.json", {"pid": 101, "supervisor_pid": 100, "group": 100})
        worker.write(self.folder / "node-source-application-exit.json", {"pid": 101, "returncode": 0})
        worker.write(self.folder / "node-source-command.json", worker.expected_argv(value))
        completion = {"application_pid": 101, "application_returncode": 0, "sdk_pid": None if plain else 102,
                      "sdk_exited": None if plain else True, "phase": None if plain else "closed", "inputs_verified": True}
        worker.write(self.folder / "node-source-completion.json", completion)
        records = []
        if not plain:
            argv = worker.expected_argv(value)
            records = [{"kind": "startup", "path": str(self.source), "startup": {"pid": 101, "node": value["node"],
                        "cwd": str(self.project), "argv": [argv[0], argv[-1]], "exec_argv": argv[1:-1], "environment": original["environment"]}},
                       {"kind": "module_requested", "path": str(self.source), "load_id": 1,
                        "url": self.source.as_uri(), "logical_source": "app.cjs", "module_type": "javascript"},
                       {"kind": "source", "path": str(self.source), "requested_path": str(self.source),
                        "sha256": launch.capture.file_digest(self.source), "text_sha256": launch.capture.file_digest(self.source), "size": self.source.stat().st_size},
                       {"kind": "instrumented", "path": str(self.source), "format": "commonjs", "load_id": 1,
                        "url": self.source.as_uri(), "logical_source": "app.cjs"}]
            content = b"fixed transformed source"
            digest = launch.capture.digest(content)
            output = runtime / ("node-module-" + digest + ".txt")
            output.write_bytes(content)
            records[-1].update(output_file=str(output), sha256=digest, size=len(content),
                               source_sha256=launch.capture.file_digest(self.source),
                               body_entry={"schema_version": 1, "goal": "commonjs",
                                           "helper": str(self.root / "adapters/node/src/source-inputs.ts")})
            records.append({"kind": "execution_started", "load_id": 1, "pid": 101, "execution_protocol": 1,
                            "path": str(self.source), "url": self.source.as_uri(), "logical_source": "app.cjs",
                            "source_sha256": launch.capture.file_digest(self.source), "format": "commonjs",
                            "emission_kind": "instrumented", "emission_sha256": digest})
            (runtime / "node-sources.jsonl").write_text("".join(json.dumps(record) + "\n" for record in records))
            worker.write(runtime / "node-status.json", {"launch_id": "a" * 32, "pid": 101, "sdk_pid": 102})
            worker.write(runtime / "node-sdk-ready.json", {"schema_version": 1, "launch_id": "a" * 32, "pid": 102})
            worker.write(self.folder / "node-source-transport.json", {"path": str(runtime / "node-events.fifo"),
                         "kind": "fifo", "mode": 0o600, "sdk_pid": 102, "removed_after_sdk_exit": True})
        inputs = {"schema_version": 5, "launch_id": "a" * 32, "phase": "verified", "action_delivery_verified": False,
                  "loaded_inputs": records, "launch_manifest": launch.file_identity(manifest_path),
                  "module_execution_protocol": 1, "module_outcomes": [] if plain else [{"load_id": 1,
                    "path": str(self.source), "url": self.source.as_uri(), "logical_source": "app.cjs",
                    "returned_format": "commonjs", "resolved_format": "commonjs", "outcome": "body_entered"}],
                  "module_execution_observation": "native_plain_unavailable" if plain else "injected_body_entry"}
        if not plain:
            inputs.update(application_pid=101, sdk_pid=102, sdk_report=launch.file_identity(runtime / "node-status.json"))
        worker.write(runtime / (prefix + "-inputs.json"), inputs)
        return value, manifest, original, completion, lane

    def test_plain_javascript_has_no_fabricated_loader_or_sdk_report(self):
        _, _, _, _, lane = self.fixture(plain=True)
        launch.verify(self.root, self.project, self.entry, self.tools, self.folder, lane)

    def test_source_launch_binds_all_consumer_and_actual_process_receipts(self):
        _, _, _, _, lane = self.fixture()
        launch.verify(self.root, self.project, self.entry, self.tools, self.folder, lane)
        for filename, key, changed in [("process.json", "argv", ["arbitrary"]),
                                       ("node-source-application.json", "group", 999),
                                       ("node-source-application-exit.json", "returncode", 1),
                                       ("node-source-completion.json", "sdk_exited", False),
                                       (launch.REQUEST_FILE, "plain", 0)]:
            path = self.folder / filename
            original = path.read_bytes()
            document = launch.read(path)
            document[key] = changed
            path.write_text(json.dumps(document))
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                launch.verify(self.root, self.project, self.entry, self.tools, self.folder, lane)
            path.write_bytes(original)

    def test_launch_protocol_and_generated_code_refuse_substitution(self):
        value, manifest, original, _, _ = self.fixture()
        variants = [{**manifest, "schema_version": True}, {**manifest, "launch_id": "foreign"},
                    {**manifest, "plain": 0}, {**manifest, "argv": ["arbitrary"]},
                    {**manifest, "ambient_sha256": {"NODE_OPTIONS": "foreign"}},
                    {**manifest, "runtime": {**manifest["runtime"], "version": "26.0.0"}},
                    {**manifest, "preloads": {**manifest["preloads"], "entries": ["foreign"]}},
                    {**manifest, "plan_sha256": "0" * 64}]
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                launch.launch_manifest(changed, value, original, self.root, self.entry)
        bootstrap = Path(value["runtime"]) / "node-bootstrap.cjs"
        bootstrap.write_text("arbitrary code")
        with self.assertRaisesRegex(ValueError, "generated source"):
            launch.generated_files(self.root, Path(value["runtime"]), value, original, manifest["resolved_plan"])

    def test_dependency_inventory_uses_string_order_and_rejects_added_inputs(self):
        for relative in ("node_modules/a/b.js", "node_modules/a-b.js"):
            path = self.root / relative
            path.parent.mkdir(exist_ok=True)
            path.write_text(relative)
        value, manifest, _, _, _ = self.fixture()
        paths = manifest["tooling"]["packages"]
        self.assertEqual([row["path"] for row in paths], sorted(row["path"] for row in paths))
        launch.tooling(manifest, self.root, value)
        changed = copy.deepcopy(manifest)
        changed["tooling"]["packages"].reverse()
        with self.assertRaises(ValueError):
            launch.tooling(changed, self.root, value)
        (self.root / "node_modules/new.js").write_text("new dependency")
        with self.assertRaises(ValueError):
            launch.tooling(manifest, self.root, value)

    def test_retained_emission_bytes_are_rechecked_after_sdk_verification(self):
        value, _, _, _, lane = self.fixture()
        launch.verify(self.root, self.project, self.entry, self.tools, self.folder, lane)
        output = next(Path(value["runtime"]).glob("node-module-*.txt"))
        output.write_bytes(b"altered retained source")
        with self.assertRaisesRegex(ValueError, "artifact"):
            launch.verify(self.root, self.project, self.entry, self.tools, self.folder, lane)

    def test_sdk_execution_summary_must_match_the_raw_witness_and_context(self):
        value, _, _, _, lane = self.fixture()
        filename = Path(value["runtime"]) / "node-inputs.json"
        original = filename.read_bytes()
        changes = (("module_execution_protocol", True), ("module_execution_protocol", 2),
                   ("module_execution_observation", "native_plain_unavailable"), ("module_outcomes", []))
        for key, changed in changes:
            document = launch.read(filename)
            document[key] = changed
            filename.write_text(json.dumps(document))
            with self.subTest(field=key), self.assertRaises(ValueError):
                launch.verify(self.root, self.project, self.entry, self.tools, self.folder, lane)
            filename.write_bytes(original)
        entry = copy.deepcopy(self.entry)
        entry["node_context"]["format"] = "module"
        with self.assertRaisesRegex(ValueError, "format differs"):
            launch.verify(self.root, self.project, entry, self.tools, self.folder, lane)

    def test_type_environment_and_file_guards_preserve_absence_and_identity(self):
        with self.assertRaises(ValueError):
            launch.same({"value": 0}, {"value": False}, "types differ")
        absent = launch.environment_records({})
        empty = launch.environment_records({"NODE_OPTIONS": ""})
        self.assertNotEqual(absent, empty)
        with self.assertRaises(ValueError):
            launch.read(self.folder / "absent.json")
        linked = self.folder / "linked.json"
        linked.symlink_to(self.config)
        with self.assertRaises(ValueError):
            launch.read(linked)
        self.assertIn("symlink", launch.file_identity(linked))


if __name__ == "__main__":
    unittest.main()
