"""Declared domains, failure preservation and sealed replay suite regressions."""
import argparse
import copy
from contextlib import redirect_stdout
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters/generation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import domains
import generation as gen
import harness
import policy
import shrinking
import qualify_shrinking


INTEGER = {"kind": "integer", "minimum": 0, "maximum": 100}
FLOAT = {"kind": "float", "minimum": -100.0, "maximum": 100.0}
STRING = {"kind": "string", "minimum_length": 0, "maximum_length": 20, "alphabet": "abz"}


def fixture_result(case, entry, different=True):
    scalar = {"kind": "integer", "type": "python.int", "bits": None, "signed": True, "value": "0"}
    changed = {**scalar, "value": "1"}
    differences = [{"path": "/outcome/result", "reason": "typed value differs",
                    "baseline": scalar, "instrumented_on": changed}] if different else []
    comparison = {"verdict": "different_observed" if different else "equivalent_observed", "reasons": [],
                  "initial_differences": [], "differences": differences}
    checked = {"verdict": comparison["verdict"], "reasons": [],
               "execution": {"verdict": "equivalent_observed", "reasons": [], "differences": []},
               "pairs": [{"comparison": comparison}]}
    result = {"case": case["id"], "function": entry["otelc_function"], "arguments": case["arguments"],
              "exit_code": int(different), "comparison": {"cases": [checked]}}
    observed = {}
    for lane, value in (("baseline", scalar), ("instrumented_on", changed if different else scalar)):
        observation = {"gaps": [], "outcome": {"kind": "return", "graph": {"roots": {"result": value}, "nodes": []}}}
        observed[lane] = [{"observation": observation}]
    return result, {"cases": [observed]}


class DomainTests(unittest.TestCase):
    def test_actual_qualification_fixture_declares_all_languages_and_scalar_domains(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, config, specs = qualify_shrinking.fixture(Path(temporary))
            resolved = policy.load(config)
            self.assertEqual(set(resolved["languages"]), set(policy.LANGUAGES))
            self.assertEqual(len(specs), 11)
            self.assertEqual(len(resolved["fixtures"]), 11)
            self.assertEqual(len(list(source.iterdir())), 8)
            for row in specs:
                domains.arguments([row["start"]], row["domains"])

    def test_closed_domains_validate_exact_fields_types_and_membership(self):
        for value in (INTEGER, FLOAT, STRING, {"kind": "boolean"}):
            self.assertEqual(domains.validate(value), value)
        bad = [None, {}, {"kind": "object"}, {**INTEGER, "maximum": True}, {**INTEGER, "minimum": 101},
               {**INTEGER, "minimum": -(2**5000)}, {**INTEGER, "extra": 1}, {**FLOAT, "minimum": math.inf},
               {**FLOAT, "maximum": -(2**5000)}, {**STRING, "alphabet": "aa"}, {**STRING, "alphabet": ""},
               {**STRING, "alphabet": "\ud800"}, {**STRING, "minimum_length": -1},
               {**STRING, "maximum_length": 4097}, {"kind": True}]
        for value in bad:
            with self.subTest(domain=value), self.assertRaises(ValueError):
                domains.validate(value)
        for value, domain in ((True, INTEGER), (-1, INTEGER), (101, INTEGER), ("c", STRING), (1, {"kind": "boolean"})):
            self.assertFalse(domains.contains(value, domain))
        self.assertTrue(domains.contains(True, {"kind": "boolean"}))
        self.assertFalse(domains.finite(2**5000))
        with self.assertRaises(ValueError):
            domains.arguments([1], [])

    def test_fixture_domains_are_frozen_checked_and_optional(self):
        document = {"fixtures": [{"function": "sample", "cases": [[100]], "domains": [INTEGER]}]}
        result = policy.validate(document)
        self.assertEqual(result["fixtures"][0]["domains"], [INTEGER])
        self.assertEqual(policy.validate(result), result)
        for declared in (None, [], [{**INTEGER, "maximum": 99}]):
            bad = copy.deepcopy(document)
            bad["fixtures"][0]["domains"] = declared
            with self.assertRaises(ValueError):
                policy.validate(bad)
        ordinary = policy.validate({"fixtures": [{"function": "sample", "cases": [[100]]}]})
        self.assertNotIn("domains", ordinary["fixtures"][0])

    def test_candidates_are_deterministic_strictly_simpler_and_target_typed(self):
        for language, type_ in (("c", "int"), ("cpp", "int"), ("rust", "i32"), ("python", "int"),
                                ("java", "int"), ("javascript", "dynamic"), ("typescript", "number"), ("go", "int")):
            entry = {"language": language, "parameters": [type_], "input_domains": [INTEGER]}
            candidates = list(shrinking.candidates(entry, [100]))
            self.assertEqual(candidates, list(shrinking.candidates(entry, [100])))
            self.assertEqual([int(case[0]) for case in candidates], [0, 50, 75, 88, 94, 97, 99, 99])
        for value, domain in ((False, {"kind": "boolean"}), ("zabba", STRING), (-57, {**INTEGER, "minimum": -100}),
                              (57.25, FLOAT), (-0.0, FLOAT)):
            self.assertEqual(len(domains.rank(value, domain)), 2)
            for candidate in domains.reductions(value, domain):
                if domains.contains(candidate, domain) and domains.rank(candidate, domain) < domains.rank(value, domain):
                    self.assertNotEqual(domains.key([candidate]), domains.key([value]))
        float_entry = {"language": "rust", "parameters": ["f32"], "input_domains": [FLOAT]}
        around_one = list(shrinking.candidates(float_entry, [1.0]))
        self.assertEqual(around_one[:3], [[0.0], [0.5], [0.75]])
        self.assertIn([0.9999999403953552], around_one)
        self.assertGreater(domains.float_step(-1.0, 0.0, 32), -1.0)
        self.assertEqual(domains.float_step(1.0, 0.0, 64), math.nextafter(1.0, 0.0))
        self.assertIn([0.0], list(shrinking.candidates(float_entry, [-0.0])))
        with self.assertRaises(ValueError):
            harness.corpus({"language": "rust", "parameters": ["f32"], "input_cases": [[1.3]],
                            "input_domains": [{**FLOAT, "minimum": 1.3}]}, 1)

    def test_strings_decrease_within_alphabet_and_minimum_length(self):
        entry = {"language": "python", "parameters": ["str"], "input_domains": [{**STRING, "minimum_length": 2}]}
        candidates = list(shrinking.candidates(entry, ["zzab"]))
        self.assertIn(["aa"], candidates)
        self.assertIn(["ab"], candidates)
        self.assertTrue(all(len(case[0]) >= 2 and set(case[0]) <= set("abz") for case in candidates))


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.result, self.bundle = fixture_result({"id": "case", "arguments": [100]}, {"otelc_function": "sample"})

    def test_signature_ignores_values_but_preserves_path_type_and_outcome(self):
        original = shrinking.fingerprint(self.result, self.bundle)
        self.result["comparison"]["cases"][0]["pairs"][0]["comparison"]["differences"][0]["baseline"]["value"] = "100"
        self.assertEqual(shrinking.fingerprint(self.result, self.bundle), original)
        self.result["comparison"]["cases"][0]["pairs"][0]["comparison"]["differences"][0]["path"] = "/after/global"
        self.assertNotEqual(shrinking.fingerprint(self.result, self.bundle), original)
        self.assertIsNone(shrinking.shape(None))
        self.assertEqual(shrinking.shape({"kind": "float", "type": "f32", "bits": "3f800000"})["width"], 32)

    def test_incomplete_blocked_unstable_and_initially_unequal_cases_are_refused(self):
        for exit_code in (0, 2, 3, 4):
            self.assertIsNone(shrinking.fingerprint({**self.result, "exit_code": exit_code}, self.bundle))
        for path, value in (("verdict", "inconclusive"), ("reasons", ["unstable"])):
            result = copy.deepcopy(self.result)
            result["comparison"]["cases"][0][path] = value
            self.assertIsNone(shrinking.fingerprint(result, self.bundle))
        for field in ("reasons", "initial_differences"):
            result = copy.deepcopy(self.result)
            result["comparison"]["cases"][0]["pairs"][0]["comparison"][field] = ["invalid"]
            self.assertIsNone(shrinking.fingerprint(result, self.bundle))
        observed = self.bundle["cases"][0]["baseline"][0]["observation"]
        observed["gaps"] = [{"reason": "opaque"}]
        with self.assertRaises(ValueError):
            shrinking.fingerprint(self.result, self.bundle)

    def test_exception_class_and_all_pair_differences_are_preserved(self):
        observed = self.bundle["cases"][0]["instrumented_on"][0]["observation"]
        observed["outcome"] = {"kind": "error", "category": "exception", "graph": {
            "roots": {"error": {"kind": "reference", "node_id": "n1"}},
            "nodes": [{"id": "n1", "type": "python.ValueError", "fields": {}}]}}
        signature = shrinking.fingerprint(self.result, self.bundle)
        self.assertEqual(signature["outcomes"]["instrumented_on"]["root"]["type"], "python.ValueError")
        observed["outcome"]["graph"]["nodes"][0]["type"] = "python.TypeError"
        self.assertNotEqual(shrinking.fingerprint(self.result, self.bundle), signature)
        report = self.result["comparison"]["cases"][0]
        second = copy.deepcopy(report["pairs"][0])
        second["comparison"]["differences"] = []
        report["pairs"].append(second)
        self.assertIsNone(shrinking.fingerprint(self.result, self.bundle))


class ShrinkWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source, self.root = self.base / "app[1]", self.base / "provider"
        self.source.mkdir(); self.root.mkdir()
        (self.source / "sample.py").write_text("def sample(x:int)->int:return x+1\ndef other():return 0\n")
        cli = self.base / "cli"
        cli.write_text("frozen CLI")
        for context in (patch.dict(os.environ, {"OTELEQ_EXECUTABLE": str(cli)}),
                        patch.object(gen.capture, "selected_tools", return_value={"python": Path(sys.executable)}),
                        patch.object(gen.capture, "artefacts", return_value={"pinned": "sha"}),
                        patch.object(gen, "decoder", return_value=None)):
            context.start(); self.addCleanup(context.stop)
        self.config = self.base / "policy.toml"
        self.config.write_text('''languages=["python"]
[[fixtures]]
function="sample.sample"
cases=[[100]]
domains=[{kind="integer",minimum=0,maximum=100}]
''')
        output = io.StringIO()
        args = argparse.Namespace(source=self.source, otelc_root=self.root, workspace_parent=self.base,
                                  language=None, exclude=[], cases=1, config=self.config)
        with redirect_stdout(output):
            gen.plan(args)
        self.workspace = Path(output.getvalue().strip())
        with redirect_stdout(io.StringIO()):
            gen.generate(argparse.Namespace(workspace=self.workspace))
        self.case = next(case for case in gen.read(self.workspace / "tests/corpus.json")
                         if case["arguments"] == [100])
        self.effect = lambda case: (case["arguments"][0] >= 7, None)
        self.compare = patch.object(gen, "compare_case", side_effect=self.fake_compare)
        self.compare.start(); self.addCleanup(self.compare.stop)

    def fake_compare(self, workspace, data, entry, case, destination, decoder):
        different, code = self.effect(case)
        result, bundle = fixture_result(case, entry, different)
        if code is not None:
            result["exit_code"] = code
        gen.write(destination / gen.TYPED_BUNDLE, bundle)
        return result

    def shrink(self, name="reduced", trials=64):
        args = argparse.Namespace(command="shrink", workspace=self.workspace, case=self.case["id"],
                                  report_dir=self.base / name, trials=trials)
        with redirect_stdout(io.StringIO()):
            code = gen.shrink(args)
        return code, gen.read(args.report_dir / "shrink.json")

    def test_reduction_retains_original_trials_and_a_replayable_owned_suite(self):
        before = gen.manifest(self.workspace / "tests")
        code, result = self.shrink()
        self.assertEqual(code, 1)
        self.assertEqual(result["original_arguments"], [100])
        self.assertEqual(result["reduced_arguments"], [7])
        self.assertEqual(result["status"], "candidate_rule_minimal")
        self.assertEqual(before, gen.manifest(self.workspace / "tests"))
        self.assertTrue((self.base / "reduced/original/report.json").is_file())
        for trial in result["trials"]:
            self.assertTrue(Path(trial["report"]).is_file())
            self.assertTrue((Path(trial["report"]).parent / "trial-plan.json").is_file())
        retained = Path(result["workspace"])
        _, plan = gen.load_workspace(retained, generated=True)
        self.assertEqual(sum(row["status"] == "ready" for row in plan["inventory"]), 1)
        self.assertEqual(plan["configuration"]["limits"], gen.read(self.workspace / "plan.json")["configuration"]["limits"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(gen.run(argparse.Namespace(command="replay", workspace=retained,
                                                        case=gen.read(retained / "tests/corpus.json")[0]["id"])), 1)
            exported = self.base / "exported"
            gen.export_tests(argparse.Namespace(workspace=retained, destination=exported, apply=True))
        gen.load_workspace(exported, generated=True)
        gen.clean(argparse.Namespace(workspace=retained))
        self.assertFalse(retained.exists())

    def test_reduction_preserves_the_python_provider_probe_seal(self):
        provider = self.workspace / gen.python_provider.DIRECTORY
        provider.mkdir()
        gen.write(provider / 'retained-probe.json', {'literal': 'frozen negotiation'})
        expected = gen.manifest(provider)
        data = gen.read(self.workspace / gen.PLAN_FILE)
        data['python_provider_manifest'] = expected
        gen.write(self.workspace / gen.PLAN_FILE, data)
        marker = gen.read(self.workspace / gen.OWNED_MARKER)
        marker['plan_sha256'] = gen.identity(data)
        gen.write(self.workspace / gen.OWNED_MARKER, marker)
        _, result = self.shrink()
        retained = Path(result['workspace'])
        _, derived = gen.load_workspace(retained, generated=True)
        self.assertEqual(derived['python_provider_manifest'], expected)
        self.assertEqual(gen.manifest(retained / gen.python_provider.DIRECTORY), expected)
        self.assertEqual(gen.manifest(provider), expected)
        gen.write(retained / gen.python_provider.DIRECTORY / 'retained-probe.json', {'edited': True})
        with self.assertRaisesRegex(ValueError, 'provider probes changed'):
            gen.load_workspace(retained, generated=True)

    def test_budget_and_incomplete_candidates_never_claim_full_minimisation(self):
        _, result = self.shrink(trials=1)
        self.assertEqual(result["status"], "budget_limited")
        self.assertEqual(len(result["trials"]), 1)
        self.effect = lambda case: (case["arguments"][0] >= 7, 3 if case["arguments"][0] == 0 else None)
        _, result = self.shrink(name="incomplete")
        self.assertEqual(result["status"], "incomplete_candidates")
        self.assertGreater(result["incomplete_trials"], 0)
        self.assertEqual(result["reduced_arguments"], [7])

    def test_unknown_case_no_domains_and_matching_original_are_refused(self):
        bad = argparse.Namespace(command="shrink", workspace=self.workspace, case="missing", report_dir=self.base / "bad", trials=2)
        with self.assertRaisesRegex(ValueError, "unknown case"):
            gen.shrink(bad)
        self.effect = lambda case: (False, None)
        with self.assertRaisesRegex(ValueError, "original case"):
            self.shrink(name="matching")
        self.assertFalse((self.base / "matching/shrink.json").exists())
        plan = gen.read(self.workspace / "plan.json")
        entry = next(row for row in plan["inventory"] if row["id"] == self.case["function_id"])
        del entry["input_domains"]
        gen.write(self.workspace / "plan.json", plan)
        marker = gen.read(self.workspace / gen.OWNED_MARKER)
        marker["plan_sha256"] = gen.identity(plan)
        gen.write(self.workspace / gen.OWNED_MARKER, marker)
        with self.assertRaisesRegex(ValueError, "explicit fixture domains"):
            self.shrink(name="no-domains")

    def test_existing_destinations_and_changed_corpora_are_not_overwritten(self):
        destination = self.base / "reduced"
        destination.mkdir()
        (destination / "user.txt").write_text("keep")
        with self.assertRaises(FileExistsError):
            self.shrink()
        self.assertEqual((destination / "user.txt").read_text(), "keep")
        (self.workspace / "tests/corpus.json").write_text("[]")
        with self.assertRaisesRegex(ValueError, "suite or corpus changed"):
            self.shrink(name="changed")

    def test_final_confirmation_cannot_be_replaced_by_cached_success(self):
        seen = {}
        def failing_final(case):
            value = int(case["arguments"][0])
            seen[value] = seen.get(value, 0) + 1
            return value >= 7 and not (value == 7 and seen[value] >= 2), None
        self.effect = failing_final
        with self.assertRaisesRegex(ValueError, "final confirmation"):
            self.shrink()
        self.assertFalse((self.base / "reduced/shrink.json").exists())

    def test_changed_failure_and_modified_source_never_replace_original_evidence(self):
        original_compare = self.fake_compare
        def different_failure(workspace, data, entry, case, destination, decoder):
            result = original_compare(workspace, data, entry, case, destination, decoder)
            if case["arguments"][0] < 100 and result["exit_code"] == 1:
                result["comparison"]["cases"][0]["pairs"][0]["comparison"]["differences"][0]["path"] = "/after/global"
            return result
        with patch.object(gen, "compare_case", side_effect=different_failure):
            _, result = self.shrink()
        self.assertEqual(result["reduced_arguments"], [100])
        self.assertFalse(any(trial["accepted"] for trial in result["trials"]))
        def changed_source(workspace, data, entry, case, destination, decoder):
            result = original_compare(workspace, data, entry, case, destination, decoder)
            (self.source / "sample.py").write_text("changed source")
            return result
        with patch.object(gen, "compare_case", side_effect=changed_source), self.assertRaisesRegex(ValueError, "source or immutable snapshot"):
            self.shrink(name="changed-source")
        self.assertFalse((self.base / "changed-source/shrink.json").exists())

    def test_cli_trial_budget_is_bounded_and_named_correctly(self):
        self.assertEqual(gen.trial_budget("64"), 64)
        for value in ("0", "1025", "invalid"):
            with self.assertRaisesRegex(argparse.ArgumentTypeError, "--trials"):
                gen.trial_budget(value)
