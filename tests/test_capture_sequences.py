"""Independent JavaScript lifetime roots, creation links and incomplete evidence."""
import copy
from types import SimpleNamespace as NS
import unittest

from test_capture_languages import decoder, report, span
import otelc_capture as capture
import otelc_collection as collection


class SequenceWitnessTests(unittest.TestCase):
    def setUp(self):
        self.target = "sample.Counter.add"
        self.creator = span("sample.make", identity=b"f" * 8)
        self.creator.trace_id = b"f" * 16
        self.method = span(self.target, identity=b"m" * 8)
        self.method.trace_id = b"m" * 16
        self.life = span("sample.Counter lifetime", identity=b"l" * 8)
        self.life.trace_id = b"l" * 16
        self.life.kind, self.life.dropped_links_count, self.life.dropped_attributes_count = 1, 0, 0
        self.life.links = [NS(trace_id=self.creator.trace_id, span_id=self.creator.span_id, dropped_attributes_count=0)]
        self.life.attributes = [NS(key=key, value=NS(string_value=value)) for key, value in
                                (("code.type.name", "sample.Counter"), ("otelc.lifetime.boundary", "collection"), ("otelc.lifetime.instance", "1"))]
        self.nodes = [self.creator, self.method, self.life]
        self.status = report()
        self.status.update(language="javascript", function_calls=2)
        self.status["traces"]["completed_trees"] = 3
        self.status["lifetimes"] = {"admitted": 1, "completed": 1, "current_live": 0, "censored": 0,
                                    "tracked_instances": 0, "tracked_constructors": 0,
                                    "failed_initialisations": 0, "losses": {}}
        self.spec = {"functions": {self.target: 1, self.creator.name: 1, self.life.name: 1}, "trees": 3, "errors": 0,
                     "collection": {"type": "sample.Counter", "span": self.life.name, "creator": self.creator.name, "count": 1}}

    def witness(self, nodes=None, status=None, spec=None, incomplete=False):
        return capture.witness([(capture.TRACE_PATH, b"verified")], self.status if status is None else status,
                               self.spec if spec is None else spec, "expected", decoder(self.nodes if nodes is None else nodes),
                               "javascript", allow_incomplete=incomplete)

    def test_source_factory_and_unlinked_constructor_roots_have_distinct_contracts(self):
        collection.sequence_functions(self.nodes, self.target, 1, self.creator.name)
        self.assertFalse(any(self.witness()["losses"].values()))
        nodes = copy.deepcopy([self.method, self.life])
        nodes[1].links = []
        status = copy.deepcopy(self.status)
        status["function_calls"] = 1; status["traces"]["completed_trees"] = 2
        spec = copy.deepcopy(self.spec)
        del spec["functions"][self.creator.name]
        spec["trees"] = 2; spec["collection"]["creator"] = None
        collection.sequence_functions(nodes, self.target, 1, None)
        self.assertEqual(self.witness(nodes, status, spec)["spans"], 2)
        nodes[1].links = self.life.links
        with self.assertRaises(ValueError):self.witness(nodes, status, spec)

    def test_typescript_collection_preserves_original_class_roots_and_incomplete_accounting(self):
        status = copy.deepcopy(self.status); status["language"] = "typescript"
        actual = capture.witness([(capture.TRACE_PATH, b"verified")], status, self.spec, "expected", decoder(self.nodes), "typescript")
        self.assertEqual(actual["functions"], self.spec["functions"])
        self.assertFalse(any(actual["losses"].values()))
        status["lifetimes"]["censored"] = 1
        actual = capture.witness([(capture.TRACE_PATH, b"verified")], status, self.spec, "expected", decoder(self.nodes), "typescript", allow_incomplete=True)
        self.assertEqual(actual["losses"]["lifetimes.requested.censored"], 1)

    def test_missing_collection_retains_explicit_losses_and_never_qualifies_strictly(self):
        nodes = [self.creator, self.method]
        status = copy.deepcopy(self.status)
        status["traces"]["completed_trees"] = 2
        status["lifetimes"].update(completed=0, current_live=1, censored=1, losses={"incomplete": 1})
        spec = copy.deepcopy(self.spec)
        del spec["functions"][self.life.name]
        spec["trees"] = 2
        observed = self.witness(nodes, status, spec, True)
        self.assertGreater(observed["losses"]["lifetimes.incomplete"], 0)
        self.assertEqual(observed["losses"]["lifetimes.requested.spans"], 1)
        with self.assertRaisesRegex(ValueError, "lossy, incomplete"):
            self.witness(nodes, status, spec)
        for key, value in (("export_finished", False), ("function_calls", 3)):
            altered = {**status, key: value}
            self.assertTrue(any(self.witness(nodes, altered, spec, True)["losses"].values()))
        status["traces"]["completed_trees"] = 1
        self.assertEqual(self.witness(nodes, status, spec, True)["losses"]["runtime.completed_trees"], 1)

    def test_missing_or_malformed_accounting_is_not_a_zero_loss_default(self):
        for key in self.status["lifetimes"]:
            for value in (None, True, -1):
                status = copy.deepcopy(self.status)
                status["lifetimes"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    collection.javascript(self.nodes, status, self.spec["collection"])
        for value in ({"capacity": False}, {" ": 0}, {"capacity": -1}):
            status = copy.deepcopy(self.status); status["lifetimes"]["losses"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                collection.javascript(self.nodes, status, self.spec["collection"])
        status = copy.deepcopy(self.status); status["lifetimes"]["admitted"] = 2
        with self.assertRaises(ValueError):collection.javascript(self.nodes, status, self.spec["collection"])

    def test_bad_creation_links_extra_instances_and_constructor_method_calls_are_visible(self):
        for change in (lambda item: item.links.clear(), lambda item: setattr(item.links[0], "span_id", b"x" * 8),
                       lambda item: setattr(item.links[0], "dropped_attributes_count", 1)):
            nodes = copy.deepcopy(self.nodes);change(nodes[-1])
            with self.subTest(change=change), self.assertRaises(ValueError):
                collection.javascript(nodes, self.status, self.spec["collection"])
        child = span(self.target, parent=self.creator.span_id, identity=b"c" * 8)
        child.trace_id = self.creator.trace_id
        with self.assertRaisesRegex(ValueError, "construction invoked"):
            collection.sequence_functions([*self.nodes, child], self.target, 1, self.creator.name)
        with self.assertRaisesRegex(ValueError, "invocation roots"):
            collection.sequence_functions(self.nodes, self.target, 2, self.creator.name)
        extra = copy.deepcopy(self.life);extra.span_id = b"e" * 8
        extra.attributes[2].value.string_value = "2"
        status = copy.deepcopy(self.status); status["lifetimes"].update(admitted=2, completed=2)
        losses, count = collection.javascript([*self.nodes, extra], status, self.spec["collection"])
        self.assertEqual(count, 2);self.assertEqual(losses["lifetimes.requested.admitted"], 1)


if __name__ == "__main__":unittest.main()
