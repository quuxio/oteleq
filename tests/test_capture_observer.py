"""Artefact stability prevents comparisons spanning a concurrent rebuild."""
import runpy
import copy
from contextlib import closing
import http.client
import os
import socket
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

OBSERVER = runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples/capture_otelc_tasks.py"))


def runtime_report():
    return {"schema_version": 1, "language": "python", "export_finished": True,
            "losses": {name: 0 for name in ("function_capacity", "active_call_capacity", "incomplete", "invalid")},
            "export_loss": 0,
            "traces": {"losses": {}, "pending_contexts": 0, "active_trees": 0, "queued_trees": 0}}


class WitnessTests(unittest.TestCase):
    def test_every_pending_queue_and_unfinished_export_are_retained(self):
        losses, pending = OBSERVER["runtime_witness"](runtime_report())
        self.assertEqual(pending, 0)
        self.assertIn("export", losses)
        for key in ("pending_contexts", "active_trees", "queued_trees"):
            status = runtime_report()
            status["traces"][key] = 2
            self.assertEqual(OBSERVER["runtime_witness"](status)[1], 2)
        status = runtime_report()
        status["export_finished"] = False
        self.assertEqual(OBSERVER["runtime_witness"](status)[1], 1)

    def test_trace_loss_names_cannot_overwrite_export_or_runtime_losses(self):
        status = runtime_report()
        status["traces"]["losses"] = {"export": 7, "runtime.invalid": 8}
        losses, _ = OBSERVER["runtime_witness"](status)
        self.assertEqual(losses["traces.export"], 7)
        self.assertEqual(losses["traces.runtime.invalid"], 8)
        self.assertEqual(losses["export"], 0)
        self.assertEqual(losses["runtime.invalid"], 0)

    def test_missing_unknown_or_malformed_runtime_evidence_aborts(self):
        for mutate in (
                lambda s: s.update(schema_version=2),
                lambda s: s.update(schema_version=True),
                lambda s: s.update(language="java"),
                lambda s: s.update(export_finished="yes"),
                lambda s: s.update(export_loss=-1),
                lambda s: s.update(losses={}),
                lambda s: s["traces"].update(losses=[]),
                lambda s: s["traces"].update(losses={" ": 0}),
                lambda s: s["traces"].update(queued_trees=-1),
                lambda s: s["traces"].update(pending_contexts=True),
                lambda s: s["traces"].pop("queued_trees")):
            status = runtime_report()
            mutate(status)
            with self.subTest(status=status), self.assertRaises((ValueError, KeyError)):
                OBSERVER["runtime_witness"](status)

    def test_duplicate_runtime_json_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate runtime report key"):
            OBSERVER["strict_json"]('{"traces":{"queued_trees":3,"queued_trees":0}}')
        self.assertEqual(OBSERVER["strict_json"]('{"export_loss":0}'), {"export_loss": 0})

    def test_decoder_rejects_invalid_or_retransmitted_span_identities(self):
        span = SimpleNamespace(trace_id=b"t" * 16, span_id=b"s" * 8, parent_span_id=b"",
                               name="work", start_time_unix_nano=1, end_time_unix_nano=2)
        def decode(_):
            return SimpleNamespace(resource_spans=[SimpleNamespace(scope_spans=[SimpleNamespace(spans=[span])])])
        bodies = [("/v1/metrics", b"ignored"), ("/v1/traces", b"trace")]
        raw_hash, names = OBSERVER["decode_traces"](bodies, decode)
        self.assertEqual(raw_hash, OBSERVER["digest"](b"trace"))
        self.assertEqual(names, {"work": 1})
        with self.assertRaisesRegex(ValueError, "invalid or duplicate"):
            OBSERVER["decode_traces"](bodies * 2, decode)
        original = copy.copy(span)
        for key, value in (("trace_id", bytes(16)), ("trace_id", b"t"), ("span_id", bytes(8)),
                           ("span_id", b"s"), ("parent_span_id", b"bad"), ("parent_span_id", bytes(8)),
                           ("name", " "), ("start_time_unix_nano", 0), ("end_time_unix_nano", 0)):
            with self.subTest(key=key, value=value):
                span = copy.copy(original)
                setattr(span, key, value)
                with self.assertRaisesRegex(ValueError, "invalid or duplicate"):
                    OBSERVER["decode_traces"](bodies, decode)
        span = copy.copy(original)
        span.parent_span_id = b"p" * 8
        self.assertEqual(OBSERVER["decode_traces"](bodies, decode)[1], {"work": 1})


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.server = OBSERVER["CaptureServer"]()
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        self.worker.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)
        self.assertFalse(self.worker.is_alive())

    def request(self, body=b"message", headers=None):
        with closing(http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)) as connection:
            connection.request("POST", "/v1/traces", body, headers or {})
            response = connection.getresponse()
            response.read()
            return response.status

    def raw_request(self, request):
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3) as connection:
            connection.sendall(request)
            connection.shutdown(socket.SHUT_WR)
            return connection.recv(4096)

    def test_complete_requests_preserve_exact_bytes(self):
        self.assertEqual(self.request(b"\x00\xff"), 200)
        self.server.require_complete()
        self.assertEqual(self.server.bodies, [("/v1/traces", b"\x00\xff")])

    def test_truncated_body_is_not_acknowledged_or_recorded_as_complete(self):
        response = self.raw_request(b"POST /v1/traces HTTP/1.0\r\nContent-Length: 5\r\n\r\nx")
        self.assertIn(b"400", response.split(b"\r\n")[0])
        self.assertEqual(self.server.bodies, [])
        with self.assertRaisesRegex(ValueError, "incomplete HTTP capture"):
            self.server.require_complete()

    def test_ambiguous_framing_and_unsupported_encodings_fail_capture(self):
        for headers in (b"", b"Content-Length: -1\r\n", b"Content-Length: x\r\n",
                        b"Content-Length: 1\r\nContent-Length: 1\r\n",
                        b"Content-Length: 1\r\nTransfer-Encoding: chunked\r\n",
                        b"Content-Length: 1\r\nContent-Encoding: gzip\r\n"):
            with self.subTest(headers=headers):
                response = self.raw_request(b"POST /v1/traces HTTP/1.0\r\n" + headers + b"\r\nx")
                self.assertIn(b"400", response.split(b"\r\n")[0])
        self.assertEqual(self.server.bodies, [])
        with self.assertRaises(ValueError):
            self.server.require_complete()

    def test_size_and_request_limits_cannot_silently_drop_telemetry(self):
        self.assertEqual(self.request(b"x", {"Content-Length": str(OBSERVER["MAX_REQUEST_BYTES"] + 1)}), 413)
        for _ in range(OBSERVER["MAX_REQUESTS"] - 1):
            self.assertEqual(self.request(), 200)
        self.assertEqual(self.request(), 413)
        with self.assertRaises(ValueError):
            self.server.require_complete()

    def test_body_timeout_is_a_capture_failure(self):
        with patch.dict(OBSERVER["Receiver"].do_POST.__globals__, {"REQUEST_TIMEOUT": 0.05}):
            with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3) as connection:
                connection.sendall(b"POST /v1/traces HTTP/1.0\r\nContent-Length: 3\r\n\r\n")
                self.assertIn(b"408", connection.recv(4096).split(b"\r\n")[0])
        with self.assertRaises(ValueError):
            self.server.require_complete()

    def test_protocol_errors_are_capture_failures(self):
        response = self.raw_request(b"GET /unknown HTTP/1.0\r\n\r\n")
        self.assertIn(b"501", response.split(b"\r\n")[0])
        with self.assertRaises(ValueError):
            self.server.require_complete()

    def test_header_timeout_is_retained_even_when_the_handler_catches_it(self):
        with patch.dict(OBSERVER["CaptureServer"].get_request.__globals__, {"REQUEST_TIMEOUT": 0.05}):
            with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3) as connection:
                connection.sendall(b"POST /v1/traces HTTP/1.0")
                self.assertEqual(connection.recv(4096), b"")
        with self.assertRaises(ValueError):
            self.server.require_complete()


class ArtefactStabilityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for relative in ["adapters/python/quux_otelc_python/monitor.py", "adapters/python/requirements.txt",
                         "target/debug/quux-otelc", "python"]:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"original bytes")
        self.interpreter = self.root / "python"
        self.identities = OBSERVER["artefact_identities"](self.root, self.interpreter)

    def test_unchanged_tools_qualify_without_importing_the_target(self):
        OBSERVER["require_same_artefacts"](self.root, self.interpreter, self.identities)
        self.assertEqual(len(self.identities), 5)

    def test_rebuilt_launcher_changed_adapter_lock_or_interpreter_cannot_qualify(self):
        for relative in ["target/debug/quux-otelc", "adapters/python/quux_otelc_python/monitor.py",
                         "adapters/python/requirements.txt", "python"]:
            with self.subTest(relative=relative):
                path = self.root / relative
                path.write_bytes(b"changed bytes")
                with self.assertRaisesRegex(ValueError, "changed during capture"):
                    OBSERVER["require_same_artefacts"](self.root, self.interpreter, self.identities)
                path.write_bytes(b"original bytes")

    def test_added_or_missing_adapter_files_cannot_hide_behind_prior_manifest(self):
        extra = self.root / "adapters/python/quux_otelc_python/nested/extra.py"
        extra.parent.mkdir()
        extra.write_bytes(b"new code")
        with self.assertRaises(ValueError):
            OBSERVER["require_same_artefacts"](self.root, self.interpreter, self.identities)
        extra.unlink()
        (extra.parent.parent / "monitor.py").unlink()
        with self.assertRaises(ValueError):
            OBSERVER["require_same_artefacts"](self.root, self.interpreter, self.identities)

    def test_missing_required_executable_is_a_capture_failure(self):
        (self.root / "target/debug/quux-otelc").unlink()
        with self.assertRaises(FileNotFoundError):
            OBSERVER["require_same_artefacts"](self.root, self.interpreter, self.identities)

    def test_source_contained_temporary_parent_is_rejected_before_creating_any_workspace(self):
        checker = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as parent:
            for temporary_parent in (self.root, checker):
                with self.subTest(temporary_parent=temporary_parent):
                    reports = Path(parent) / "reports"
                    env = dict(os.environ, TMPDIR=str(temporary_parent), TEMP=str(temporary_parent), TMP=str(temporary_parent))
                    result = subprocess.run([sys.executable, str(checker / "examples/capture_otelc_tasks.py"),
                                             "--otelc-root", str(self.root), "--report-dir", str(reports)],
                                            env=env, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(b"temporary directory must be outside both repositories", result.stderr)
                    self.assertFalse(reports.exists())


    def test_actual_capture_aborts_before_recording_success_when_a_run_rebuilds_the_launcher(self):
        app = self.root / "examples/apps/python_tasks_app.py"
        app.parent.mkdir(parents=True)
        launcher = self.root / "target/debug/quux-otelc"
        app.write_text("from pathlib import Path\nPath(" + repr(str(launcher)) + ").write_bytes(b'rebuilt')\nprint('same result')\n")
        (self.root / "examples/python-task-context.toml").write_text("schema_version=2\n")
        report_parent = tempfile.TemporaryDirectory()
        self.addCleanup(report_parent.cleanup)
        reports = Path(report_parent.name) / "reports"
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "examples/capture_otelc_tasks.py"),
                                 "--otelc-root", str(self.root), "--report-dir", str(reports)],
                                capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"artefacts changed during capture", result.stderr)
        self.assertFalse((reports / "bundle.json").exists())
        self.assertFalse((reports / "baseline-0/attempt.json").exists())
        self.assertFalse((reports / "baseline-1").exists())
