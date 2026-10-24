"""Shared qualification checks retain strict graph, transport and route boundaries."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from opentelemetry.proto.trace.v1.trace_pb2 import Span
import sequence_qualification as shared


class SequenceQualificationTests(unittest.TestCase):
    def test_source_checks_only_exclude_the_explicit_separately_audited_workflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for name in ("receivers", "effects-promotion"):
                workspace = folder / name
                workspace.mkdir()
                source = workspace / "application"
                source.mkdir()
                (source / "app.py").write_text("original")
                (workspace / "plan.json").write_text(json.dumps({
                    "source": str(source),
                    "source_manifest": {"app.py": hashlib.sha256(b"original").hexdigest()}}))
            shared.verify_sources(folder)
            (folder / "effects-promotion/application/app.py").write_text("changed stage")
            with self.assertRaises(AssertionError):
                shared.verify_sources(folder)
            shared.verify_sources(folder, excluded=("effects-promotion",))
            (folder / "receivers/application/app.py").write_text("unexpected change")
            with self.assertRaises(AssertionError):
                shared.verify_sources(folder, excluded=("effects-promotion",))

    def test_contract_requires_every_root_and_the_exact_call_schedule(self):
        bundle = {"contract": {"required_roots": ["receiver"], "steps": [
            {"id": "step-0", "action": "call", "required_roots": ["receiver"]}]}}
        shared.check_contract(bundle, {"receiver"}, 1)
        for path, value in ((["required_roots"], []), (["steps"], []),
                            (["steps", 0, "id"], "other"),
                            (["steps", 0, "action"], "release"),
                            (["steps", 0, "required_roots"], [])):
            changed = copy.deepcopy(bundle)
            target = changed["contract"]
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(AssertionError):
                shared.check_contract(changed, {"receiver"}, 1)

    def test_execution_requires_empty_channels_complete_counts_and_no_loss(self):
        attempt = {"execution": {"channels": {"stdout": [], "stderr": []},
            "witness": {"functions": {"target": 2}, "spans": 2, "losses": {"dropped": 0}, "pending": 0}}}
        shared.check_execution(attempt, "target", 2, active=True)
        for section, key, value in (("channels", "stderr", [1]),
                ("witness", "functions", {}), ("witness", "spans", 1),
                ("witness", "losses", {"dropped": 1}), ("witness", "pending", 1)):
            changed = copy.deepcopy(attempt)
            changed["execution"][section][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                shared.check_execution(changed, "target", 2, active=True)
        attempt["execution"].pop("witness")
        shared.check_execution(attempt, "target", 2, active=False)

    def test_serial_trees_require_identity_parentage_order_and_complete_members(self):
        def span(trace, identifier, start, end, parent=b""):
            return Span(name="target", trace_id=trace * 16, span_id=identifier * 8,
                        parent_span_id=parent, start_time_unix_nano=start, end_time_unix_nano=end)

        original = [span(b"a", b"1", 10, 30), span(b"a", b"2", 12, 20, b"1" * 8),
                    span(b"b", b"3", 40, 50)]
        shared.check_serial_trees(original, [2, 1], "target")
        for fault in ("name", "overlap", "parent", "duplicate", "zero-id", "missing"):
            changed = copy.deepcopy(original)
            if fault == "name":
                changed[1].name = "foreign"
            elif fault == "overlap":
                changed[2].start_time_unix_nano = 25
            elif fault == "parent":
                changed[1].parent_span_id = b"x" * 8
            elif fault == "duplicate":
                changed[1].span_id = changed[0].span_id
            elif fault == "zero-id":
                changed[0].trace_id = b"\0" * 16
            else:
                changed.pop()
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                shared.check_serial_trees(changed, [2, 1], "target")

    def test_routes_keep_function_mapping_across_all_framework_summaries(self):
        methods = ("identity", "secret", "transient", "fail", "recursive", "touch")
        function = lambda method: "fixture." + method
        functions = {function(method): method for method in methods}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)

            def report(name, selected, amount=7):
                path = folder / name / "report.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"cases": [{"function": function(method), "arguments": [amount]}
                                                       for method in selected]}))
                return {"report": str(path)}

            for name in ("comparison", "export-comparison"):
                report(name, methods)
            for method in methods:
                (folder / ("replay-" + method + ".stdout")).write_text(json.dumps(report("replay/" + method, (method,))))
            for name in ("framework", "export-framework", "reduced-framework"):
                selected = ("transient",) if name == "reduced-framework" else methods
                rows = [report(name + "/" + method, (method,), 0 if name == "reduced-framework" else 7)
                        for method in selected]
                (folder / (name + ".stdout")).write_text("\n".join(map(json.dumps, rows)))
            (folder / "reduced-replay.stdout").write_text(json.dumps(report("reduced-replay", ("transient",), 0)))
            for name in ("edge-one", "edge-thirty-two"):
                report(name + "/comparison", ("identity",))
            shared.verify_routes(folder, methods, functions, function)
            report("framework/identity", ("identity",), 0)
            with self.assertRaises(AssertionError):
                shared.verify_routes(folder, methods, functions, function)

    def test_detached_route_restores_the_original_source_after_execution_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source, workspace = folder / "application", folder / "workspace"
            source.mkdir()
            workspace.mkdir()
            (workspace / "plan.json").write_text(json.dumps({"source": str(source)}))
            (folder / "comparison").mkdir()
            (folder / "comparison/report.json").write_text('{"cases":[]}')

            def command(argv, directory, name, expected=0):
                if name == "export-run":
                    self.assertFalse(source.exists())
                    self.assertTrue(source.with_name("application-detached").is_dir())
                    raise RuntimeError("retained worker failed")
                return ""

            with mock.patch.object(shared, "command", side_effect=command):
                with self.assertRaisesRegex(RuntimeError, "retained worker failed"):
                    shared.exercise_routes(folder / "cli", folder, workspace, (), {},
                                           mock.Mock(), mock.Mock(), mock.Mock())
            self.assertTrue(source.is_dir())
            self.assertFalse(source.with_name("application-detached").exists())


if __name__ == "__main__":
    unittest.main()
