"""Fail closed on missing resource events, counters, metrics or creation links."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from test_capture_languages import capture, decoder, report, span


def attribute(key, value):
    return NS(key=key, value=NS(string_value=value))


class ResourceWitnessTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads(Path(capture.__file__).with_name("otelc-resource-workloads.json").read_text())["python"]
        spec = self.spec["resource"]
        self.nodes = [span(spec["creator"])]
        for index in (1, 2):
            node = span(spec["span"], identity=index.to_bytes(8, "big"))
            node.trace_id = index.to_bytes(16, "big")
            node.kind, node.dropped_links_count, node.dropped_attributes_count = 1, 0, 0
            node.links = [NS(trace_id=self.nodes[0].trace_id, span_id=self.nodes[0].span_id, dropped_attributes_count=0)]
            node.attributes = [attribute("code.type.name", spec["type"]), attribute("otelc.lifetime.boundary", "resource"),
                               attribute("otelc.lifetime.instance", str(index))]
            self.nodes.append(node)
        self.status = report()
        self.status["traces"]["completed_trees"] = 3
        self.status["functions"] = {spec["creator"]: {"count": 1, "unwinds": 0}}
        self.status["lifetimes"] = {"admitted": 2, "completed": 2, "current_live": 0, "censored": 0,
                                    "tracked_instances": 0, "active_constructors": 0, "failed_initialisations": 0,
                                    "active_releases": 0, "failed_releases": 1, "losses": {}}
        self.points = []
        self.metric_nodes = []
        for suffix, value, kind in (("admitted", 2, "sum"), ("completed", 2, "sum"),
                                    ("live", 0, "gauge"), ("failed_releases", 1, "sum")):
            fields = [] if suffix == "failed_releases" else [attribute("code.type.name", spec["type"]),
                                                              attribute("otelc.lifetime.boundary", "resource")]
            point = NS(attributes=fields, as_int=value, flags=0, WhichOneof=lambda _: "as_int")
            self.points.append(point)
            data = NS(data_points=[point], aggregation_temporality=2, is_monotonic=True)
            metric = NS(name="otelc.lifetime." + suffix, WhichOneof=lambda _, kind=kind: kind)
            setattr(metric, kind, data)
            self.metric_nodes.append(metric)
        self.scope = NS(scope=NS(name="quux.otelc"), metrics=self.metric_nodes)
        self.resource = NS(resource=NS(attributes=[attribute("service.name", "expected")]), scope_metrics=[self.scope])
        self.metric_decoder = NS(FromString=lambda _: NS(resource_metrics=[self.resource]))
        self.bodies = [("/v1/traces", b"traces"), ("/v1/metrics", b"metrics")]

    def check(self):
        with patch.object(capture.otelc_resource, "metric_decoder", return_value=self.metric_decoder):
            return capture.witness(self.bodies, self.status, self.spec, "expected", decoder(self.nodes), "python")

    def test_failed_close_is_an_expected_event_and_completion_is_exactly_once(self):
        witness = self.check()
        self.assertEqual(witness["spans"], 3)
        self.assertTrue(all(value == 0 for value in witness["losses"].values()))
        self.status["lifetimes"]["completed"] = 3
        with self.assertRaises(ValueError):
            self.check()

    def test_missing_pending_failed_or_lossy_release_observations_are_rejected(self):
        for key in ("active_releases", "failed_releases"):
            for value in (None, True, 1.0, -1, 2):
                original = copy.deepcopy(self.status)
                if value is None:
                    self.status["lifetimes"].pop(key)
                else:
                    self.status["lifetimes"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.check()
                self.status = original
        self.status["lifetimes"]["losses"] = {"export": 1}
        with self.assertRaises(ValueError):
            self.check()

    def test_creation_links_boundary_and_duplicate_instance_events_are_checked(self):
        for change in (lambda n: n[1].links.clear(), lambda n: setattr(n[2].attributes[2].value, "string_value", "1"),
                       lambda n: setattr(n[1].attributes[1].value, "string_value", "collection")):
            original = copy.deepcopy(self.nodes)
            change(self.nodes)
            with self.assertRaises(ValueError):
                self.check()
            self.nodes = original

    def test_metrics_require_actual_service_scope_counts_and_complete_point_contracts(self):
        for change in (
            lambda: setattr(self.resource.resource.attributes[0].value, "string_value", "wrong"),
            lambda: setattr(self.scope.scope, "name", "wrong"),
            lambda: setattr(self.metric_nodes[0], "WhichOneof", lambda _: "gauge"),
            lambda: setattr(self.metric_nodes[0].sum, "aggregation_temporality", 1),
            lambda: setattr(self.metric_nodes[0].sum, "is_monotonic", False),
            lambda: self.metric_nodes[0].sum.data_points.clear(),
            lambda: setattr(self.points[0], "flags", 1),
            lambda: self.points[0].attributes.clear(),
            lambda: setattr(self.points[0], "WhichOneof", lambda _: "as_double"),
            lambda: setattr(self.points[0], "as_int", 3),
            lambda: self.metric_nodes.clear(),
        ):
            self.setUp()
            change()
            with self.assertRaises(ValueError):
                self.check()
        self.setUp()
        self.bodies = self.bodies[:1]
        with self.assertRaisesRegex(ValueError, "missing resource metric"):
            self.check()

    def test_resource_contract_cannot_be_substituted_for_other_workload_or_language(self):
        self.spec["collection"] = self.spec["resource"]
        with self.assertRaises(ValueError):
            self.check()
        self.spec.pop("collection")
        self.status["language"] = "java"
        message_decoder = decoder(self.nodes)
        with self.assertRaises(ValueError):
            capture.witness(self.bodies, self.status, self.spec, "expected", message_decoder, "java")


if __name__ == "__main__":
    unittest.main()
