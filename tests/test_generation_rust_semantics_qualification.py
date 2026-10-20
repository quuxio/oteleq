"""Fixed producer qualification keeps literal cases and provenance independent."""
import copy
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import qualify_rust_semantics as qualifier
import test_capture_rust_compiler as compiler_cases


class RustSemanticQualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = compiler_cases.RustCompilerBuildTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def verify(self) -> dict:
        fixture = self.fixture
        result = subprocess.CompletedProcess([], 0, fixture.version.encode(), b"")
        with patch.object(qualifier.compiler_build, "execute", return_value=result):
            return qualifier.verify_bundle(fixture.root, fixture.workspace, fixture.source,
                                            fixture.bundle, fixture.tools, fixture.environment,
                                            {"app.selected": 1}, fixture.request["sources"])

    def test_semantic_scenarios_have_independent_span_denominators(self) -> None:
        self.assertEqual(qualifier.SEMANTIC_NAMES,
                         {"semantics.selected_column": 1, "semantics.selected_caller": 1,
                          "semantics.selected_closure": 1, "semantics.selected_future": 2,
                          "semantics.selected_panic": 1})
        self.assertEqual(qualifier.ALIAS_NAMES,
                         {"first.shared.selected": 1, "second.shared.selected": 1})

    def test_fixed_fixture_provenance_binds_the_original_source_and_target(self) -> None:
        actual = self.verify()
        self.assertEqual(actual["selected_functions"], ["app.selected"])
        self.assertEqual(actual["loaded_sources"], self.fixture.request["sources"])

    def test_rehashed_requests_cannot_substitute_the_policy_or_loaded_source_set(self) -> None:
        fixture = self.fixture
        original = copy.deepcopy(fixture.request)
        for field, value in (("schema_version", True), ("sources", {}), ("discovery_argv", []), ("policy", {}),
                             ("protected_source_roots", [])):
            fixture.request = {**original, field: value}
            fixture.seal()
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.verify()

    def test_cancellation_and_panic_are_two_distinct_expected_error_spans(self) -> None:
        runtime = {"future_observers": {"admission_exhausted": False, "pending": 0},
                   "functions": {"semantics.selected_future": {"count": 2, "cancellations": 1, "unwinds": 0},
                                 "semantics.selected_panic": {"count": 1, "cancellations": 0, "unwinds": 1}}}
        spans = [SimpleNamespace(name="semantics.selected_future", status=SimpleNamespace(code=2, message="cancelled"),
                                 attributes=[SimpleNamespace(key="otelc.cancelled", value=SimpleNamespace(bool_value=True))]),
                 SimpleNamespace(name="semantics.selected_panic", status=SimpleNamespace(code=2, message="escaping unwind"), attributes=[])]
        decoder = SimpleNamespace(FromString=lambda _: None)
        bodies = [(qualifier.capture.TRACE_PATH, b"fixture")]
        with patch.object(qualifier.capture, "witness", return_value={}) as witness, patch.object(qualifier.capture, "service_spans", return_value=spans):
            qualifier.runtime_witness(bodies, runtime, qualifier.SEMANTIC_NAMES, "fixture", decoder, "semantics")
            self.assertEqual(witness.call_args.args[2]["errors"], 2)
            self.assertEqual(witness.call_args.args[2]["trees"], 6)
            for field in ("pending", "cancellations", "unwinds"):
                changed = copy.deepcopy(runtime)
                if field == "pending":
                    changed["future_observers"][field] = 1
                elif field == "cancellations":
                    changed["functions"]["semantics.selected_future"][field] = 0
                else:
                    changed["functions"]["semantics.selected_panic"][field] = 0
                expected_error = ValueError if field == "pending" else AssertionError
                with self.subTest(field=field), self.assertRaises(expected_error):
                    qualifier.runtime_witness(bodies, changed, qualifier.SEMANTIC_NAMES, "fixture", decoder, "semantics")
            spans[0].attributes = []
            with self.assertRaises(AssertionError):
                qualifier.runtime_witness(bodies, runtime, qualifier.SEMANTIC_NAMES, "fixture", decoder, "semantics")
            qualifier.runtime_witness([], runtime, qualifier.ALIAS_NAMES, "fixture", decoder, "aliases")
            self.assertEqual(witness.call_args.args[2]["errors"], 0)

    def test_fixed_bundle_retains_application_channels_and_explicit_capability_gaps(self) -> None:
        folder = self.fixture.base / "fixed"
        for lane in ("baseline", "instrumented_on"):
            for repeat in range(2):
                attempt = folder / (lane + "-" + str(repeat))
                (attempt / "project").mkdir(parents=True)
                (attempt / "project/semantics.rs").write_text("fixed source")
                (attempt / "provenance.json").write_text('{}')
        attempts = {"baseline": [{}, {}], "instrumented_on": [{}, {}]}
        actual = qualifier.comparison_bundle(folder, "semantics", attempts, {"result": 42})
        self.assertEqual(actual["scope"]["channels"], ["stdout", "stderr"])
        self.assertEqual(actual["scope"]["artefact_class"], "diagnostic")
        self.assertTrue(actual["scope"]["gaps"])
        self.assertEqual(actual["cases"][0]["expected_spans"], 6)
        (folder / "baseline-0/project/main.rs").write_text("alias entry")
        self.assertEqual(qualifier.comparison_bundle(folder, "aliases", attempts, {})["cases"][0]["expected_spans"], 2)

    def test_selected_declarations_and_compiler_roles_cannot_be_rebound(self) -> None:
        fixture = self.fixture
        original = copy.deepcopy(fixture.inventory)
        for field, value in (("name", "wrong.target"), ("file", "/untrusted.rs"),
                             ("unsupported", "opaque"), ("startup", True)):
            fixture.inventory = copy.deepcopy(original)
            fixture.inventory["functions"][0][field] = value
            fixture.seal()
            expected_error = ValueError if field in ("name", "startup") else AssertionError
            with self.subTest(field=field), self.assertRaises(expected_error):
                self.verify()


if __name__ == "__main__":
    unittest.main()
