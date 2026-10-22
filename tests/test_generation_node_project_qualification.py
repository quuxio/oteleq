"""Independent Node qualification rejects equal-but-wrong state and raw telemetry."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import node_project_oracle as oracle
import qualify_node_project as qualifier


def telemetry() -> dict:
    identity = {"scope": ["quux.otelc", "0.1.0"], "resource": {
        "service.name": "oteleq-gen-" + "a" * 32, "service.instance.id": "123"}}
    point = {"attributes": {"code.function.name": "sample.selected"}, "start": 10,
             "end": 20, "flags": 0, "exemplars": 0, "value_type": "as_int", "value": 1}
    metrics = [{**identity, "name": "otelc.function.calls", "kind": "sum",
                "temporality": 2, "monotonic": True, "points": [copy.deepcopy(point)]}]
    histogram = {key: value for key, value in point.items() if key not in ("value_type", "value")}
    histogram.update(count=1, sum=.002, minimum=.002, maximum=.002, has_min=True,
                     has_max=True, bounds=[.001, .01], buckets=[0, 1, 0])
    metrics.append({**identity, "name": "otelc.function.duration", "kind": "histogram",
                    "temporality": 2, "monotonic": None, "points": [histogram]})
    losses = [{**point, "attributes": {"reason": reason}, "value": 0} for reason in oracle.LOSSES]
    metrics.append({**identity, "name": "otelc.runtime.dropped_observations", "kind": "sum",
                    "temporality": 2, "monotonic": True, "points": losses})
    metrics.append({**identity, "name": "otelc.export.dropped_batches", "kind": "sum",
                    "temporality": 2, "monotonic": True, "points": [{**point, "attributes": {}, "value": 0}]})
    span = {**identity, "name": "sample.selected", "attributes": {"code.function.name": "sample.selected"},
            "trace_id": "1" * 32, "span_id": "2" * 16, "parent": "", "start": 10, "end": 20,
            "status": 0, "drops": 0, "events": 0, "links": 0}
    return {"spans": [span], "metrics": metrics}


def observation(spec: dict, lane: str, argument: float = 7.0) -> dict:
    initial = 10.0 if spec["receiver"] else 2.0
    after = initial + argument + int(spec["different"] and lane == "instrumented_on")
    result = 7.0 if spec["different"] else after if spec["receiver"] else after + argument
    return {"gaps": [], "before": oracle.expected_graph(spec, argument, initial),
            "after": oracle.expected_graph(spec, argument, after),
            "outcome": {"kind": "return", "graph": oracle.expected_graph(spec, argument, after, result)}}


class NodeProjectQualificationTests(unittest.TestCase):
    def test_source_profile_keeps_legacy_defaults_and_freezes_each_compiler_choice(self):
        for compiler in ("native", "api"):
            options = {"backend": "source-v1", "typescript_compiler": compiler}
            for context in qualifier.CONTEXTS:
                spec, _, _ = qualifier.fixture(context, node_options=options)
                self.assertEqual(spec["format"], "module" if context[0] == "ts-default" else context[3])
                self.assertEqual(tomllib.loads(qualifier.policy(spec))["adapters"]["node"], options)
            spec, source, _ = qualifier.fixture(qualifier.CONTEXTS[4], different=True, node_options=options)
            self.assertIn("/node-bootstrap.cjs", source)
            self.assertEqual(spec["source_sha256"], hashlib.sha256(source.encode()).hexdigest())
        legacy, source, _ = qualifier.fixture(qualifier.CONTEXTS[8], different=True)
        self.assertEqual(legacy["format"], "commonjs")
        self.assertIn("/node/register.mjs", source)
        self.assertNotIn("adapters", tomllib.loads(qualifier.policy(legacy)))

    def test_all_eleven_formats_have_explicit_source_inputs_and_return_values(self):
        self.assertEqual(len(qualifier.CONTEXTS), 11)
        for context in qualifier.CONTEXTS:
            spec, source, package = qualifier.fixture(context)
            self.assertIn("cases=[[7]]", qualifier.policy(spec))
            self.assertIn('bits="4030000000000000"', qualifier.policy(spec))
            self.assertIn("state+=n;return state+n;", source)
            self.assertEqual(package is not None, context[2] is not None)
            self.assertEqual(spec["format"], context[3])

    def test_complete_graphs_refuse_equal_wrong_results_arguments_and_state(self):
        for receiver, different in ((False, False), (True, False), (False, True)):
            spec, _, _ = qualifier.fixture(qualifier.CONTEXTS[4], receiver=receiver, different=different)
            for lane in ("baseline", "instrumented_on"):
                value = observation(spec, lane)
                oracle.check_observation(value, spec, lane, 7.0)
                for fault in ("argument", "initial", "after", "result", "flags", "order", "alias", "extra", "gap"):
                    changed = copy.deepcopy(value)
                    graph = changed["after"]
                    if fault == "argument": graph["nodes"][0]["fields"]["property:0"]["bits"] = "0000000000000000"
                    elif fault == "initial": changed["before"]["roots"].clear()
                    elif fault == "after": graph["roots"].clear()
                    elif fault == "result": changed["outcome"]["graph"]["roots"]["result"]["bits"] = "0000000000000000"
                    elif fault == "flags": graph["nodes"][0]["fields"]["enumerable:property:length"]["value"] = True
                    elif fault == "order": graph["nodes"][0]["fields"]["order:0"] = oracle.text(spec["language"], "length")
                    elif fault == "alias": graph["nodes"].append({"id": "unrequested"})
                    elif fault == "extra": graph["roots"]["extra"] = oracle.number(spec["language"], 0)
                    else: changed["gaps"] = ["missing"]
                    with self.subTest(receiver=receiver, different=different, lane=lane, fault=fault), self.assertRaises(ValueError):
                        oracle.check_observation(changed, spec, lane, 7.0)

    def test_same_return_difference_and_reduced_zero_have_independent_state(self):
        spec, _, _ = qualifier.fixture(qualifier.CONTEXTS[4], different=True)
        for argument in (7.0, 0.0):
            plain = observation(spec, "baseline", argument)
            active = observation(spec, "instrumented_on", argument)
            oracle.check_observation(plain, spec, "baseline", argument)
            oracle.check_observation(active, spec, "instrumented_on", argument)
            self.assertEqual(plain["outcome"]["graph"]["roots"]["result"], active["outcome"]["graph"]["roots"]["result"])
            with self.assertRaises(ValueError):
                oracle.check_observation(plain, spec, "instrumented_on", argument)

    def test_raw_receipt_requires_complete_span_counters_loss_and_histogram(self):
        oracle.check_telemetry(telemetry(), "sample.selected", 123)
        for fault in ("span-name", "function", "trace-id", "parent", "span-loss", "scope", "pid", "service",
                      "missing", "count", "float-count", "loss", "loss-dimension", "hist-count", "hist-value",
                      "hist-extrema", "hist-bucket", "hist-bounds", "flags", "time", "temporality", "monotonic"):
            value = telemetry()
            span = value["spans"][0]
            metric = value["metrics"][0]
            point = metric["points"][0]
            histogram = value["metrics"][1]["points"][0]
            if fault == "span-name": span["name"] = "wrong"
            elif fault == "function": point["attributes"] = {"code.function.name": "wrong"}
            elif fault == "trace-id": span["trace_id"] = "0" * 32
            elif fault == "parent": span["parent"] = "2" * 16
            elif fault == "span-loss": span["drops"] = 1
            elif fault == "scope": span["scope"] = ["other", "0.1.0"]
            elif fault == "pid": span["resource"] = {**span["resource"], "service.instance.id": "124"}
            elif fault == "service": span["resource"] = {**span["resource"], "service.name": "unbound"}
            elif fault == "missing": value["metrics"].pop()
            elif fault == "count": point["value"] = 0
            elif fault == "float-count": point["value_type"] = "as_double"
            elif fault == "loss": value["metrics"][2]["points"][0]["value"] = 1
            elif fault == "loss-dimension": value["metrics"][2]["points"].pop()
            elif fault == "hist-count": histogram["count"] = 0
            elif fault == "hist-value": histogram["sum"] = float("nan")
            elif fault == "hist-extrema": histogram["has_min"] = False
            elif fault == "hist-bucket": histogram["buckets"] = [1, 0, 0]
            elif fault == "hist-bounds": histogram["bounds"] = [.01, .001]
            elif fault == "flags": point["flags"] = 1
            elif fault == "time": point["end"] = 9
            elif fault == "temporality": metric["temporality"] = 1
            else: metric["monotonic"] = False
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                oracle.check_telemetry(value, "sample.selected", 123)

    def test_source_preservation_checks_added_files_and_complete_package_bytes(self):
        spec, source, package = qualifier.fixture(qualifier.CONTEXTS[4])
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            application = folder / "application"
            application.mkdir()
            (application / spec["filename"]).write_text(source)
            (application / "package.json").write_text(package)
            qualifier.source_preserved(folder, spec, source, package)
            for path, text in ((application / "extra", "untracked"), (application / "package.json", json.dumps({"type": "module"}))):
                original = path.read_bytes() if path.exists() else None
                path.write_text(text)
                with self.assertRaises(ValueError):
                    qualifier.source_preserved(folder, spec, source, package)
                path.unlink() if original is None else path.write_bytes(original)

    def test_module_receipts_refuse_rehashed_caller_and_shared_context_changes(self):
        spec, source, _ = qualifier.fixture(qualifier.CONTEXTS[0])
        spec["node_version"] = "v24.21.0"
        receipt = {"schema_version": 1, "format": "commonjs", "loader_hint": "commonjs",
                   "package": None, "node_version": spec["node_version"], "source_sha256": spec["source_sha256"]}
        entry = {"node_context": receipt, "node_original_context": copy.deepcopy(receipt)}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            caller = folder / "project" / spec["filename"]
            caller.parent.mkdir()
            caller.write_text(source)
            probe = folder / "node-context-probe/stdout"
            probe.parent.mkdir()
            value = {"original": receipt, "caller": copy.deepcopy(receipt)}
            def write(current):
                (folder / "node-context.json").write_text(json.dumps(current))
                probe.write_text(json.dumps(current["caller"]))
            write(value)
            oracle.check_context(folder, spec, entry)
            for field, replacement in (("format", "module"), ("package", {}), ("node_version", "other"),
                                       ("source_sha256", "0" * 64), ("schema_version", True)):
                changed = copy.deepcopy(value)
                changed["original"][field] = replacement
                changed["caller"][field] = replacement
                altered_entry = {"node_context": changed["original"], "node_original_context": changed["original"]}
                write(changed)
                with self.subTest(field=field), self.assertRaises(ValueError):
                    oracle.check_context(folder, spec, altered_entry)
            write(value)
            caller.write_text(source + "\n// altered caller, receipt rehashed\n")
            value["caller"]["source_sha256"] = oracle.digest(caller)
            write(value)
            # A caller's helper delta has a different digest; original source stays bound.
            oracle.check_context(folder, spec, entry)
            value["caller"]["source_sha256"] = "0" * 64
            write(value)
            with self.assertRaises(ValueError):
                oracle.check_context(folder, spec, entry)

    def test_source_compiler_receipt_binds_private_context_without_equating_original_paths(self):
        options = {"backend": "source-v1", "typescript_compiler": "api"}
        spec, source, _ = qualifier.fixture(qualifier.CONTEXTS[7], node_options=options)
        spec["node_version"] = "v24.21.0"
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            caller = folder / "project" / spec["filename"]
            caller.parent.mkdir()
            caller.write_text(source)
            receipt = {"schema_version": 1, "format": "module", "loader_hint": "module", "package": None,
                       "node_version": spec["node_version"], "source_sha256": spec["source_sha256"],
                       "source_compiler": {"profile": "module-format-only-v1", "configuration_reads": [],
                         "compiler": {"backend": "api", "transformer_profile": "none", "cwd": "/snapshot"}}}
            original = copy.deepcopy(receipt)
            original["source_compiler"]["compiler"]["cwd"] = "/original"
            entry = {"node_context": receipt, "node_original_context": original}
            value = {"original": receipt, "caller": copy.deepcopy(receipt)}
            probe = folder / "node-context-probe/stdout"
            probe.parent.mkdir()
            probe.write_text(json.dumps(value["caller"]))
            path = folder / "node-context.json"
            path.write_text(json.dumps(value))
            oracle.check_context(folder, spec, entry)
            value["original"] = original
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "private source compiler"):
                oracle.check_context(folder, spec, entry)


if __name__ == "__main__":
    unittest.main()
