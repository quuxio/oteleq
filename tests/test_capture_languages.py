"""Fail closed on unwitnessed instrumentation, unstable tools and broken capture."""
from http.client import HTTPConnection
import json
import os
import socket
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import otelc_capture as capture
import capture_otelc_languages as observer


def span(name="selected", parent=b"", identity=b"s" * 8):
    return NS(name=name, trace_id=b"t" * 16, span_id=identity, parent_span_id=parent,
              start_time_unix_nano=10, end_time_unix_nano=20, status=NS(code=0))


def decoder(spans, service="expected", scope="quux.otelc"):
    message = NS(resource_spans=[NS(resource=NS(attributes=[NS(key="service.name", value=NS(string_value=service))]),
                                   scope_spans=[NS(scope=NS(name=scope), spans=spans)])])
    return NS(FromString=lambda _: message)


def report():
    return {"traces": {"losses": {}, "pending_contexts": 0, "active_trees": 0,
                       "queued_trees": 0, "completed_trees": 1},
            "function_calls": 1, "losses": {"function_capacity": 0, "active_call_capacity": 0, "incomplete": 0, "invalid": 0}, "schema_version": 1, "language": "python", "export_loss": 0, "export_finished": True}


class TelemetryWitnessTests(unittest.TestCase):
    def setUp(self):
        self.spec = {"functions": {"selected": 1}, "trees": 1, "errors": 0}
        self.bodies = [("/v1/metrics", b"metrics"), ("/v1/traces", b"trace bytes")]

    def test_valid_witness_has_exact_names_raw_identity_and_no_pending(self):
        witness = capture.witness(self.bodies, report(), self.spec, "expected", decoder([span()]), "python")
        self.assertEqual(witness["functions"], {"selected": 1})
        self.assertEqual(witness["raw_otlp_sha256"], capture.digest(b"trace bytes"))
        self.assertEqual(witness["pending"], 0)

    def test_missing_extra_or_wrong_function_never_qualifies(self):
        for spans in ([], [span("other")], [span(), span(identity=b"x" * 8)]):
            status, decoded = report(), decoder(spans)
            with self.subTest(spans=spans), self.assertRaises(ValueError):
                capture.witness(self.bodies, status, self.spec, "expected", decoded, "python")

    def test_service_and_scope_must_match_the_launched_instance(self):
        for service, scope in (("wrong", "quux.otelc"), ("expected", "wrong")):
            decoded = decoder([span()], service, scope)
            with self.subTest(service=service, scope=scope), self.assertRaises(ValueError):
                capture.decode(self.bodies, "expected", decoded)

    def test_bad_ids_timestamps_duplicate_missing_parent_and_cycle_fail(self):
        cases = []
        for key, value in (("trace_id", b"\0" * 16), ("span_id", b"short"),
                           ("parent_span_id", b"\0" * 8), ("start_time_unix_nano", 0),
                           ("end_time_unix_nano", 1), ("name", "")):
            node = span()
            setattr(node, key, value)
            cases.append([node])
        cases += [[span(), span()], [span(parent=b"x" * 8)],
                  [span(parent=b"x" * 8), span(parent=b"s" * 8, identity=b"x" * 8)],
                  [span(), span(identity=b"x" * 8)]]
        for nodes in cases:
            decoded = decoder(nodes)
            with self.subTest(nodes=nodes), self.assertRaises(ValueError):
                capture.decode(self.bodies, "expected", decoded)

    def test_late_children_are_valid_without_stretching_parent_duration(self):
        parent, child = span(), span("child", b"s" * 8, b"x" * 8)
        child.start_time_unix_nano, child.end_time_unix_nano = 30, 40
        names, _, roots, errors = capture.decode(self.bodies, "expected", decoder([parent, child]))
        self.assertEqual((names, roots, errors), ({"selected": 1, "child": 1}, 1, 0))

    def test_export_runtime_losses_pending_and_missing_status_cannot_pass(self):
        changes = [lambda r: r.update(export_finished=False), lambda r: r.update(drained=False),
                   lambda r: r.update(export_loss=1), lambda r: r.update(losses={"capacity": 1}),
                   lambda r: r.update(function_calls=2), lambda r: r.pop("export_loss"),
                   lambda r: r["traces"].update(losses={"export": 1}),
                   lambda r: r["traces"].update(pending_contexts=1),
                   lambda r: r["traces"].update(active_trees=1),
                   lambda r: r["traces"].update(queued_trees=1),
                   lambda r: r["traces"].update(completed_trees=2)]
        for change in changes:
            status = report()
            change(status)
            decoded = decoder([span()])
            with self.subTest(status=status), self.assertRaises(ValueError):
                capture.witness(self.bodies, status, self.spec, "expected", decoded, "python")

    def test_native_export_counter_and_error_span_are_independently_checked(self):
        status = report()
        status["export_dropped_batches"] = status.pop("export_loss")
        status["losses"] = {key: 0 for key in ("active_call_capacity", "incomplete", "invalid_exit", "object_capacity", "object_incomplete", "queue", "stack", "thread_admission")}
        status.pop("schema_version")
        status.pop("language")
        status["drained"] = True
        node = span()
        node.status.code = 2
        spec = {**self.spec, "errors": 1}
        capture.witness(self.bodies, status, spec, "expected", decoder([node]), "c")
        decoded = decoder([node])
        with self.assertRaises(ValueError):
            capture.witness(self.bodies, status, self.spec, "expected", decoded, "c")

    def test_malformed_or_missing_diagnostics_never_pass_as_zero(self):
        changes = [lambda r: r.update(losses={}), lambda r: r["traces"].pop("queued_trees"),
                   lambda r: r["traces"].pop("pending_contexts"),
                   lambda r: r.update(export_loss=-1, export_dropped_batches=1),
                   lambda r: r["traces"].update(active_trees=-1, queued_trees=1),
                   lambda r: r.update(export_loss=False), lambda r: r.update(export_loss=-1),
                   lambda r: r["traces"].update(pending_contexts=0.0),
                   lambda r: r["traces"].update(losses={"capacity": False}),
                   lambda r: r.update(function_calls=True),
                   lambda r: r["traces"].update(losses={" ": 0})]
        for change in changes:
            status = report()
            change(status)
            decoded = decoder([span()])
            with self.subTest(status=status), self.assertRaises((ValueError, KeyError)):
                capture.witness(self.bodies, status, self.spec, "expected", decoded, "python")

    def test_duplicate_report_keys_cannot_hide_a_loss(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            capture.strict_json('{"export_loss":1,"export_loss":0}')

    def test_runtime_language_schema_and_native_drain_status_are_required(self):
        changes = [lambda r: r.pop("schema_version"), lambda r: r.update(schema_version=True),
                   lambda r: r.update(schema_version=2), lambda r: r.update(language="java"),
                   lambda r: (r.pop("language"), r["traces"].pop("pending_contexts"))]
        for change in changes:
            status = report()
            change(status)
            decoded = decoder([span()])
            with self.subTest(status=status), self.assertRaises(ValueError):
                capture.witness(self.bodies, status, self.spec, "expected", decoded, "python")
        status, decoded = report(), decoder([span()])
        with self.assertRaisesRegex(ValueError, "native drain status"):
            capture.witness(self.bodies, status, self.spec, "expected", decoded, "c")

    def test_long_parent_chain_remains_valid(self):
        nodes = [span(identity=index.to_bytes(8, "big"),
                      parent=(index - 1).to_bytes(8, "big") if index > 1 else b"") for index in range(1, 513)]
        names, _, roots, _ = capture.decode(self.bodies, "expected", decoder(nodes))
        self.assertEqual(names, {"selected": 512})
        self.assertEqual(roots, 1)


class CaptureBoundaryTests(unittest.TestCase):
    def test_receiver_retains_exact_bytes_and_rejects_unknown_oversized_or_truncated(self):
        with capture.receiver() as (endpoint, bodies, errors):
            connection = HTTPConnection(endpoint.removeprefix("http://"), timeout=5)
            connection.request("POST", "/v1/traces", b"\xff\0\n")
            self.assertEqual(connection.getresponse().status, 200)
            connection.close()
            for path, headers, body in (("/other", {}, b""),
                                        ("/v1/traces", {"Content-Length": "1048577"}, b""),
                                        ("/v1/traces", {"Content-Length": "oops"}, b""),
                                        ("/v1/traces", {"Content-Length": "2"}, b"x")):
                expected = 413 if headers.get("Content-Length") == "1048577" else 408 if headers.get("Content-Length") == "2" else 400
                connection = HTTPConnection(endpoint.removeprefix("http://"), timeout=5)
                connection.request("POST", path, body, headers)
                self.assertEqual(connection.getresponse().status, expected)
                connection.close()
            self.assertEqual(bodies, [("/v1/traces", b"\xff\0\n")])
            self.assertEqual(len(errors), 4)

    def test_receiver_request_budget_fails_visibly(self):
        with capture.receiver() as (endpoint, bodies, errors):
            for index in range(33):
                connection = HTTPConnection(endpoint.removeprefix("http://"), timeout=5)
                connection.request("POST", "/v1/metrics", b"x")
                self.assertEqual(connection.getresponse().status, 200 if index < 32 else 413)
                connection.close()
            self.assertEqual((len(bodies), len(errors)), (32, 1))

    def test_shared_receiver_rejects_duplicate_framing_compression_and_unknown_methods(self):
        with capture.receiver() as (endpoint, bodies, errors):
            host, port = endpoint.removeprefix("http://").split(":")
            for request in (b"POST /v1/traces HTTP/1.0\r\nContent-Length: 1\r\nContent-Length: 1\r\n\r\nx",
                            b"POST /v1/traces HTTP/1.0\r\nContent-Length: 1\r\nContent-Encoding: gzip\r\n\r\nx",
                            b"GET /v1/traces HTTP/1.0\r\n\r\n"):
                with socket.create_connection((host, int(port)), timeout=5) as connection:
                    connection.sendall(request)
                    connection.shutdown(socket.SHUT_WR)
                    self.assertNotIn(b"200", connection.recv(4096).split(b"\r\n")[0])
            self.assertEqual((len(bodies), len(errors)), (0, 3))

    def test_source_contained_temporary_parent_is_rejected_before_probing_or_copying(self):
        with patch.dict(os.environ, {"TMPDIR": "/source/tmp"}), patch.object(capture.tempfile, "gettempdir") as lookup:
            with self.assertRaisesRegex(ValueError, "outside both repositories"):
                capture.temporary_parent(Path("/source"), Path("/checker"))
            lookup.assert_not_called()
        with patch.dict(os.environ, {}, clear=True), patch.object(capture.tempfile, "gettempdir", return_value="/checker/tmp"):
            with self.assertRaises(ValueError):
                capture.temporary_parent(Path("/source"), Path("/checker"))

    def test_environment_isolated_from_ambient_agents_headers_and_wrappers(self):
        with patch.dict(os.environ, {"NODE_OPTIONS": "injected", "OTEL_EXPORTER_OTLP_HEADERS": "secret",
                                     "JAVA_TOOL_OPTIONS": "injected", "RUSTC_WRAPPER": "injected"}):
            env = capture.environment(Path("/tmp/run/project"), {}, "service", Path("/tmp/otelc"))
        self.assertFalse(any(key in env for key in ("NODE_OPTIONS", "OTEL_EXPORTER_OTLP_HEADERS", "JAVA_TOOL_OPTIONS", "RUSTC_WRAPPER")))
        self.assertEqual(env["TMPDIR"], "/tmp/run")
        self.assertEqual(env["HOME"], "/tmp/run")

    def test_endpoint_is_only_changed_in_private_policy_and_ambiguous_policy_fails(self):
        policy = b'[export]\nendpoint = "old"\ninterval_ms = 500\n'
        actual = capture.configure(policy, "http://127.0.0.1:123")
        self.assertIn(b'endpoint = "http://127.0.0.1:123"', actual)
        self.assertIn(b"interval_ms = 500", actual)
        for invalid in (b"[export]\n", policy + b'endpoint = "second"\n'):
            with self.assertRaises(ValueError):
                capture.configure(invalid, "new")

    def test_subprocess_preserves_non_utf8_exit_and_closed_stdin(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = capture.execute([sys.executable, "-c", "import sys; assert sys.stdin.read()==''; sys.stdout.buffer.write(b'\\xff'); sys.exit(2)"], Path(temporary), os.environ)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (2, b"\xff", b""))

    def test_failed_build_is_not_confused_with_application_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with self.assertRaisesRegex(ValueError, "build failed"):
                capture.build([sys.executable, "-c", "import sys; print('build failure'); sys.exit(3)"], folder, os.environ, folder / "build.log")
            self.assertIn(b"build failure", (folder / "build.log").read_bytes())

    def test_missing_tool_fails_before_capture(self):
        with self.assertRaisesRegex(ValueError, "required tool"):
            capture.tool_path("oteleq-deliberately-missing-tool")

    def test_every_language_uses_the_requested_compiler_or_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata = root / "target/debug/otelc-llvm-toolchain.json"
            metadata.parent.mkdir(parents=True)
            metadata.write_text(json.dumps({"bindir": "/qualified/llvm"}))
            with patch.object(capture, "tool_path", side_effect=lambda name: Path(name)), \
                 patch.dict(os.environ, {"OTELC_NODE": "/qualified/node", "OTELC_JAVA": "/qualified/java", "OTELC_RUSTC": "/qualified/rustc", "OTELC_GO": "/qualified/go", "OTELC_CLANG": "/qualified/llvm/clang", "OTELC_CLANGXX": "/qualified/llvm/clang++"}):
                self.assertEqual(capture.selected_tools(root, "c"), {"clang": Path("/qualified/llvm/clang")})
                self.assertEqual(capture.selected_tools(root, "cpp"), {"clang++": Path("/qualified/llvm/clang++")})
                self.assertEqual(capture.selected_tools(root, "rust"), {"rustc": Path("/qualified/rustc")})
                for language in ("python", "java", "go", "javascript", "typescript"):
                    tools = capture.selected_tools(root, language)
                    self.assertIn(language, tools)
                self.assertEqual(capture.selected_tools(root, "typescript")["javascript"], Path("/qualified/node"))

    def test_native_metadata_cannot_redirect_execution_to_an_unselected_tool(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata = root / "target/debug/otelc-llvm-toolchain.json"
            metadata.parent.mkdir(parents=True)
            metadata.write_text(json.dumps({"bindir": "/untrusted/toolchain"}))
            with patch.object(capture, "tool_path", return_value=Path("/qualified/llvm/clang")) as selected:
                with self.assertRaisesRegex(ValueError, "does not match"):
                    capture.selected_tools(root, "c")
                self.assertNotIn("untrusted", str(selected.call_args.args))
            metadata.write_text('{"bindir":"/qualified/llvm","bindir":"/untrusted/toolchain"}')
            with self.assertRaisesRegex(ValueError, "duplicate"):
                capture.selected_tools(root, "c")

    def test_native_plain_and_instrumented_builds_keep_exceptions_and_same_flags(self):
        workspace, root, policy, source = map(Path, ("/tmp/work", "/tmp/otelc", "/tmp/policy", "/tmp/source"))
        for language, tool in (("c", "clang"), ("cpp", "clang++")):
            with self.subTest(language=language), patch.object(capture, "build") as build:
                plain, on = capture.commands(root, workspace, language, source, policy, {tool: Path("/qualified/" + tool)}, {}, workspace)
                self.assertEqual(len(build.call_args_list), 2)
                self.assertNotIn("-fno-exceptions", build.call_args_list[0].args[0])
                self.assertEqual(on[-2:], ["run", workspace / "instrumented"])
                self.assertEqual(plain, [workspace / "plain"])

    def test_managed_and_rust_execution_recipes_keep_the_original_source(self):
        workspace, root, policy, source = map(Path, ("/tmp/work", "/tmp/otelc", "/tmp/policy", "/tmp/source"))
        for language in ("python", "java", "go", "javascript", "typescript", "rust"):
            with self.subTest(language=language), patch.object(capture, "build"):
                tools = {language: Path("/qualified/tool"), "rustc": Path("/qualified/rustc")}
                plain, on = capture.commands(root, workspace, language, source, policy, tools, {}, workspace)
                self.assertEqual(on[-1], source)
                self.assertIn(str(source), [str(p) for p in plain] if language != "rust" else [str(source)])

    def test_rustup_locations_are_preserved_without_a_compiler_wrapper(self):
        with patch.dict(os.environ, {"RUSTUP_HOME": "/qualified/rustup", "CARGO_HOME": "/qualified/cargo"}):
            env = capture.environment(Path("/tmp/run/project"), {"rustc": Path("/qualified/rustc")}, "service", Path("/tmp/otelc"))
        self.assertEqual(env["RUSTUP_HOME"], "/qualified/rustup")
        self.assertEqual(env["CARGO_HOME"], "/qualified/cargo")
        self.assertEqual(env["OTELC_RUSTC"], "/qualified/rustc")

    def test_manifest_covers_all_languages_and_has_independent_nonzero_expectations(self):
        manifest = json.loads(Path(observer.__file__).with_name("otelc-workloads.json").read_text())
        self.assertEqual(set(manifest), {"c", "cpp", "rust", "python", "java", "javascript", "typescript", "go"})
        self.assertEqual([sum(spec["functions"].values()) for spec in manifest.values()], [7, 31, 8, 9, 10, 11, 11, 10])


class LanguageArtefactTests(unittest.TestCase):
    def test_all_languages_detect_changed_added_or_deleted_adapter_inputs(self):
        configurations = {
            "c": ("target/debug/libquux_otelc_runtime.a", "target/debug/otelc-llvm-toolchain.json", "target/debug/libotelc_pass.dylib"),
            "cpp": ("target/debug/libquux_otelc_runtime.a", "target/debug/otelc-llvm-toolchain.json", "target/debug/libotelc_pass.dylib"),
            "rust": ("target/debug/otelc-rust-adapter", "target/debug/libquux_otelc_rust.rlib", "Cargo.lock", "target/debug/deps/original.rlib"),
            "java": ("adapters/java/target/java-agent-0.1.0-agent.jar",),
            "go": ("adapters/go/build/otelc-go", "adapters/go/go.sum", "adapters/go/runtime/runtime.go"),
            "javascript": ("target/debug/otelc_node_observer.node", "adapters/node/package-lock.json", "adapters/node/runtime.mjs"),
            "typescript": ("target/debug/otelc_node_observer.node", "adapters/node/package-lock.json", "adapters/node/runtime.mjs"),
            "python": ("adapters/python/requirements.txt", "adapters/python/monitor.py", ".venv/lib/python3.12/site-packages/sdk.py")}
        for language, files in configurations.items():
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                for relative in ("target/debug/quux-otelc", "tool", *files):
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"original")
                tools = {"tool": root / "tool"}
                identities = capture.artefacts(root, language, tools)
                for filename in ("otelc-workloads.json", "otelc-worker-workloads.json"):
                    self.assertEqual(identities["observer:" + filename],
                                     capture.file_digest(Path(observer.__file__).with_name(filename)))
                capture.stable(root, language, tools, identities)
                changed = root / files[-1]
                changed.write_bytes(b"rebuilt")
                with self.assertRaises(ValueError):
                    capture.stable(root, language, tools, identities)
                changed.write_bytes(b"original")
                if language in ("rust", "go", "python", "javascript", "typescript"):
                    extra = changed.with_name("additional" + changed.suffix)
                    extra.write_bytes(b"new adapter code")
                    with self.assertRaises(ValueError):
                        capture.stable(root, language, tools, identities)
                    extra.unlink()
                (root / "tool").unlink()
                with self.assertRaises(FileNotFoundError):
                    capture.stable(root, language, tools, identities)

    def test_missing_adapter_tree_and_unknown_language_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            for language in ("go", "python", "javascript", "swift"):
                with self.subTest(language=language), self.assertRaises(ValueError):
                    capture.artefacts(Path(temporary), language, {})


class PrivateExecutionTests(unittest.TestCase):
    def test_worker_workload_selects_only_python_and_rejects_unavailable_languages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "otelc"
            root.mkdir()
            comparator = Path(temporary) / "comparator"
            comparator.write_bytes(b"fake comparator")
            def run(_root, destination, _language, _spec, _decoder):
                destination.mkdir()
            module_name = "opentelemetry.proto.collector.trace.v1.trace_service_pb2"
            module = NS(ExportTraceServiceRequest=object())
            argv = ["capture", "--otelc-root", str(root), "--report-dir", str(Path(temporary) / "workers"),
                    "--comparator", str(comparator), "--workload", "python-workers"]
            with patch.dict(sys.modules, {module_name: module}), patch.object(observer, "run", side_effect=run) as runner, \
                 patch.object(observer.subprocess, "run", return_value=NS(returncode=0, stdout=b'equivalent_observed')):
                with patch.object(sys, "argv", argv):
                    observer.main()
                self.assertEqual(runner.call_count, 1)
                _, _, language, spec, _ = runner.call_args.args
                self.assertEqual(language, "python")
                self.assertEqual((spec["case_id"], sum(spec["functions"].values()), spec["trees"], spec["errors"]),
                                 ("python-executor-context-example", 10, 5, 1))
            argv[4] = str(Path(temporary) / "unsupported")
            with patch.object(sys, "argv", argv + ["--language", "java"]), self.assertRaises(SystemExit):
                observer.main()
            self.assertFalse((Path(temporary) / "unsupported").exists())

    def test_selected_worker_manifest_rejects_duplicate_json_keys_before_capture(self):
        argv = ["capture", "--otelc-root", "/unused", "--report-dir", "/unused-report", "--workload", "python-workers"]
        with patch.object(sys, "argv", argv), patch.object(Path, "read_text", return_value='{"python":{},"python":{}}'), \
             patch.object(observer, "run") as runner:
            with self.assertRaisesRegex(ValueError, "duplicate"):
                observer.main()
            runner.assert_not_called()

    def test_cli_dispatches_all_languages_and_requires_comparison_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "otelc"
            root.mkdir()
            comparator = Path(temporary) / "comparator"
            comparator.write_bytes(b"fake comparator")
            def run(_root, destination, _language, _spec, _decoder):
                destination.mkdir()
            module_name = "opentelemetry.proto.collector.trace.v1.trace_service_pb2"
            module = NS(ExportTraceServiceRequest=object())
            with patch.dict(sys.modules, {module_name: module}), patch.object(observer, "run", side_effect=run) as runner, \
                 patch.object(observer.subprocess, "run", return_value=NS(returncode=0, stdout=b'{"verdict":"equivalent_observed"}')):
                argv = ["capture", "--otelc-root", str(root), "--report-dir", str(Path(temporary) / "all"), "--comparator", str(comparator)]
                with patch.object(sys, "argv", argv):
                    observer.main()
                self.assertEqual(runner.call_count, 8)
                with patch.object(sys, "argv", argv + ["--language", "python", "--language", "python"]):
                    with self.assertRaises(FileExistsError):
                        observer.main()
            with patch.dict(sys.modules, {module_name: module}), patch.object(observer, "run", side_effect=run), \
                 patch.object(observer.subprocess, "run", return_value=NS(returncode=3, stdout=b'inconclusive')):
                argv[4] = str(Path(temporary) / "failed")
                with patch.object(sys, "argv", argv + ["--language", "python"]), self.assertRaisesRegex(ValueError, "comparison failed"):
                    observer.main()
                self.assertEqual((Path(temporary) / "failed/python/comparison.json").read_bytes(), b'inconclusive')
            argv[4] = str(root / "forbidden")
            with patch.object(sys, "argv", argv), self.assertRaises(SystemExit):
                observer.main()

    def test_source_contained_tmpdir_is_rejected_before_any_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "otelc"
            root.mkdir()
            destination = Path(temporary) / "report"
            for unsafe in (root, Path(observer.__file__).resolve().parents[1]):
                argv = ["capture", "--otelc-root", str(root), "--report-dir", str(destination)]
                with patch.object(sys, "argv", argv), patch.object(observer.tempfile, "gettempdir", return_value=str(unsafe)), self.assertRaises(SystemExit):
                    observer.main()
                self.assertFalse(destination.exists())

    def test_repeated_real_process_capture_preserves_source_and_requires_witness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "otelc"
            source = root / "examples/apps/test.py"
            source.parent.mkdir(parents=True)
            source.write_text("print('result=42')\n")
            policy = root / "examples/python-traces.toml"
            policy.write_text('[export]\nendpoint = "http://localhost:4318"\n')
            probe = Path(temporary) / "probe.py"
            probe.write_text("import json, os, runpy, sys, urllib.request\n"
                             "from pathlib import Path\n"
                             "runpy.run_path(sys.argv[1], run_name='__main__')\n"
                             "text = Path('policy.toml').read_text()\n"
                             "endpoint = text.split('endpoint = ')[1].strip().strip(chr(34))\n"
                             "request = urllib.request.Request(endpoint+'/v1/traces', data=b'spans', method='POST')\n"
                             "urllib.request.urlopen(request).close()\n"
                             "Path(os.environ['OTELC_REPORT_PATH']).write_text(" + repr(json.dumps(report())) + ")\n")
            spec = {"case_id": "independent-case", "source": "examples/apps/test.py", "policy": "examples/python-traces.toml",
                    "functions": {"selected": 1}, "trees": 1, "errors": 0}
            def commands(_root, _workspace, _language, app, _policy, _tools, _environment, _evidence):
                return [sys.executable, app], [sys.executable, probe, app]
            # Unit fake emits one declared span; real otelc qualification is separate.
            dynamic_decoder = NS(FromString=lambda body: NS(resource_spans=[NS(
                resource=NS(attributes=[NS(key="service.name", value=NS(string_value=current_service[0]))]),
                scope_spans=[NS(scope=NS(name="quux.otelc"), spans=[span()])])]))
            current_service = [""]
            actual_environment = capture.environment
            def environment(workspace, tools, service, target):
                current_service[0] = service
                return actual_environment(workspace, tools, service, target)
            destination = Path(temporary) / "evidence"
            with patch.object(capture, "selected_tools", return_value={}), \
                 patch.object(capture, "artefacts", return_value={"tool": "unchanged"}), \
                 patch.object(capture, "commands", side_effect=commands), \
                 patch.object(capture, "environment", side_effect=environment):
                observer.run(root, destination, "python", spec, dynamic_decoder)
                bundle = json.loads((destination / "bundle.json").read_text())
                self.assertEqual(bundle["cases"][0]["case_id"], spec["case_id"])
                self.assertEqual([len(bundle["cases"][0][lane]) for lane in ("baseline", "instrumented_on")], [2, 2])
                self.assertEqual(bundle["cases"][0]["baseline"][0]["channels"], bundle["cases"][0]["instrumented_on"][0]["channels"])
                self.assertEqual(source.read_text(), "print('result=42')\n")
                self.assertEqual(len(list(destination.glob("*/otlp-*.protobuf"))), 2)
                probe.write_text("import runpy, sys\nrunpy.run_path(sys.argv[1])\n")
                with self.assertRaisesRegex(ValueError, "runtime report missing"):
                    observer.run(root, Path(temporary) / "missing", "python", spec, dynamic_decoder)
                self.assertFalse((Path(temporary) / "missing/bundle.json").exists())
